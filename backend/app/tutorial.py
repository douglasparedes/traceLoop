"""TutorialMode pipeline: upload -> Muse transcribe (turn timestamps)
-> Spark understanding -> SAM whole-clip tracking -> illustrations -> guide.

Runs in a background thread with DB-backed status/progress so a 2-10 min
tutorial never blocks a request. All provider keys stay server-side.
"""
import hashlib
import io
import json
import re
import subprocess
import threading
from pathlib import Path

from PIL import Image, ImageDraw

from . import ai
from .db import SessionLocal
from . import models as M
from sqlalchemy import func, select

MAX_VIDEO_SEC = 600
TRACKING_FPS = 6
TRACKING_MAX_WIDTH = 512
HIREZ_MAX_WIDTH = 960
# Confidence band: >= OK_CONF auto-accepts; REVIEW_CONF..OK_CONF asks for a
# tap; below REVIEW_CONF (or no match at all) still records needs_tap so the
# object stays correctable instead of vanishing.
OK_CONF = 0.5
REVIEW_CONF = 0.25
# Multi-match is only ambiguous when the top two confidences are close.
CLOSE_MARGIN = 0.15
MAX_PROMPT_ATTEMPTS = 3
BASE = Path(__file__).resolve().parent.parent


def prompt_variants(label: str) -> list[str]:
    """Simplification ladder for SAM prompts (mirrors frontend speechPrompt)."""
    p = re.sub(r"\s+", " ", (label or "").strip().lower())
    if not p:
        return []
    words = p.split(" ")
    out = [p]
    if len(words) >= 3:
        out.append(" ".join(words[1:]))  # drop leading adjective
    if len(words) >= 2:
        out.append(" ".join(words[-2:]))
    out.append(words[-1])  # head noun
    return [v for v in dict.fromkeys(out) if len(v) >= 2][:MAX_PROMPT_ATTEMPTS]


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout)


class NoAudioTrackError(RuntimeError):
    """The uploaded video carries no audio stream — there is nothing to transcribe."""


_AUDIO_STREAM_RE = re.compile(r"Stream #\d+:\d+.*Audio:", re.S)


def probe_video(path: Path) -> dict:
    proc = _run([_ffmpeg(), "-i", str(path)], timeout=60)
    err = proc.stderr.decode("utf-8", "replace")
    dur = 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    w = h = 0
    vm = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    if vm:
        w, h = int(vm.group(1)), int(vm.group(2))
    return {"duration": dur, "width": w, "height": h,
            "has_audio": bool(_AUDIO_STREAM_RE.search(err))}


def _ffmpeg_tail(proc: subprocess.CompletedProcess, limit: int = 400) -> str:
    try:
        err = proc.stderr.decode("utf-8", "replace")
    except Exception:
        err = ""
    lines = [ln.strip() for ln in err.strip().splitlines() if ln.strip()]
    return " ".join(lines[-4:])[-limit:]


def extract_audio_wav(source: Path, out: Path) -> None:
    proc = _run([_ffmpeg(), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(out)])
    if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return
    tail = _ffmpeg_tail(proc)
    if ("matches no streams" in tail or "does not contain any stream" in tail
            or "Stream map" in tail and "matches no streams" in tail):
        raise NoAudioTrackError(
            "This video has no audio track, so there is nothing to transcribe. "
            "Record again with the microphone on and narrate each step as you show it.")
    raise RuntimeError(
        "Could not read the audio track in this video"
        + (f" (ffmpeg: {tail})" if tail else "")
        + ". Try recording again, or convert the file to MP4 with AAC audio.")


def make_tracking_copy(source: Path, out: Path, max_width: int = TRACKING_MAX_WIDTH) -> dict:
    proc = _run([_ffmpeg(), "-y", "-i", str(source), "-vf", f"fps={TRACKING_FPS},scale='min({max_width},iw)':-2",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(out)])
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("Could not build the tracking copy of the video")
    info = probe_video(out)
    return {"width": info["width"], "height": info["height"]}


def extract_frame_image(source: Path, at_sec: float) -> Image.Image:
    with io.BytesIO() as buf:
        pass
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "frame.png"
        proc = _run([_ffmpeg(), "-y", "-ss", f"{max(0.0, at_sec):.2f}", "-i", str(source), "-frames:v", "1", str(out)], timeout=60)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError("Could not extract a frame from the video")
        with Image.open(out) as im:
            return im.convert("RGB").copy()


def _svg_points(svg_path: str, mw: int, mh: int) -> list[tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", svg_path or "")]
    pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
    return pts


def make_illustrations(job_dir: Path, source: Path, obj: dict, best: dict) -> dict:
    """Crop + transparent cutout + mask overlay PNGs for one tracked object."""
    frame_img = extract_frame_image(source, best["time"])
    W, H = frame_img.size
    x1, y1, x2, y2 = [float(v) for v in best["bbox_norm"]]
    bx1, by1, bx2, by2 = int(x1 * W), int(y1 * H), int(x2 * W), int(y2 * H)
    pad_x, pad_y = int((bx2 - bx1) * 0.2), int((by2 - by1) * 0.2)
    cx1, cy1, cx2, cy2 = max(0, bx1 - pad_x), max(0, by1 - pad_y), min(W, bx2 + pad_x), min(H, by2 + pad_y)
    crop = frame_img.crop((cx1, cy1, cx2, cy2))

    # Mask polygon (mask-space coords -> original frame coords -> crop coords).
    mask = best.get("mask") or {}
    pts_frame: list[tuple[float, float]] = []
    if mask.get("svg_path") and mask.get("width") and mask.get("height"):
        raw = _svg_points(mask["svg_path"], int(mask["width"]), int(mask["height"]))
        mw, mh = float(mask["width"]), float(mask["height"])
        bw, bh = max(1.0, float(bx2 - bx1)), max(1.0, float(by2 - by1))
        pts_frame = [(bx1 + (px / mw) * bw - cx1, by1 + (py / mh) * bh - cy1) for px, py in raw]

    name = f"obj-{obj['obj_id']}"
    overlay = crop.convert("RGB")
    od = ImageDraw.Draw(overlay, "RGBA")
    if pts_frame:
        od.polygon(pts_frame, fill=(255, 176, 32, 90), outline=(255, 176, 32, 255), width=3)
    else:
        od.rectangle([bx1 - cx1, by1 - cy1, bx2 - cx1, by2 - cy1], outline=(255, 176, 32), width=3)
    overlay_path = job_dir / f"{name}-overlay.png"
    overlay.save(overlay_path)

    isolated = crop.convert("RGBA")
    alpha = Image.new("L", crop.size, 0)
    ad = ImageDraw.Draw(alpha)
    if pts_frame:
        ad.polygon(pts_frame, fill=255)
    else:
        ad.rectangle([bx1 - cx1, by1 - cy1, bx2 - cx1, by2 - cy1], fill=255)
    isolated.putalpha(alpha)
    iso_path = job_dir / f"{name}.png"
    isolated.save(iso_path)
    return {"illustration": iso_path.name, "overlay": overlay_path.name}


def _best_track(frames: list[dict]) -> tuple[dict | None, int, float]:
    """Pick best (object, frame) with temporal support.

    Score = confidence x area-weight x run-length bonus, so a sustained
    track beats a one-frame confident blip. Returns (best, distinct_count
    on the best frame, top-two confidence margin there).
    """
    runs: dict = {}
    for fr in frames or []:
        for o in fr.get("objects") or []:
            oid = o.get("object_id")
            f = fr.get("frame", 0)
            r = runs.setdefault(oid, {"last": None, "run": 0, "maxrun": 0})
            r["run"] = r["run"] + 1 if r["last"] is not None and f == r["last"] + 1 else 1
            r["last"] = f
            r["maxrun"] = max(r["maxrun"], r["run"])
    best: dict | None = None
    best_score = -1.0
    distinct_best = 1
    margin_best = 1.0
    for fr in frames or []:
        objs = fr.get("objects") or []
        confs = sorted([float(o.get("confidence")) for o in objs if o.get("confidence") is not None], reverse=True)
        margin = (confs[0] - confs[1]) if len(confs) >= 2 else 1.0
        for o in objs:
            conf = o.get("confidence")
            x1, y1, x2, y2 = o.get("bbox_norm") or [0, 0, 0, 0]
            area = max(0.0, (x2 - x1) * (y2 - y1))
            base = float(conf) if conf is not None else min(1.0, area * 4)
            run_bonus = 1 + 0.1 * min(runs.get(o.get("object_id"), {}).get("maxrun", 1), 10)
            score = base * (0.5 + 0.5 * min(1.0, area * 8)) * run_bonus
            if score > best_score:
                best_score = score
                best = {**o, "frame": fr.get("frame", 0), "time": float(fr.get("frame", 0)) / TRACKING_FPS,
                        "mask": o.get("mask")}
                distinct_best = len(objs)
                margin_best = margin
    return best, distinct_best, margin_best


def inject_illustrations(md: str, steps: list[dict], objects: list[dict],
                         extra_visuals: dict[int, list[tuple[str, str]]] | None = None) -> str:
    """Deterministically embed illustration links into guide Markdown.

    Appends an illustration block per step (for every objects_used entry
    that has PNGs) delimited by HTML comment markers, so re-running is
    idempotent: previous blocks are stripped first. Accepted review visuals
    (human-approved derivatives) can be attached via extra_visuals as
    {step_number: [(image_url, caption)]} — labelled as accepted, never as
    source evidence.
    """
    md = re.sub(r"\n?<!-- illustrations:\d+:start -->.*?<!-- illustrations:\d+:end -->\n?", "\n", md or "", flags=re.S)
    md = re.sub(r"\n?<!-- accepted-visuals:\d+:start -->.*?<!-- accepted-visuals:\d+:end -->\n?", "\n", md or "", flags=re.S)
    md = re.sub(r"\n?<!-- accepted-visuals:general:start -->.*?<!-- accepted-visuals:general:end -->\n?", "\n", md or "", flags=re.S)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    step_files: dict[int, list[tuple[dict, list[str]]]] = {}
    for o in objects or []:
        files = [f for f in [o.get("overlay"), o.get("illustration")] if f]
        if not files:
            continue
        for s in steps or []:
            if o.get("obj_id") in (s.get("objects_used") or []):
                step_files.setdefault(int(s.get("step_number", 0)), []).append((o, files))
    extra = extra_visuals or {}
    if not step_files and not extra:
        return md.strip() + "\n"
    out_lines: list[str] = []
    buf: list[str] = []
    cur: int | None = None
    seen_steps: set[int] = set()

    def flush() -> None:
        nonlocal buf, cur
        out_lines.extend(buf)
        buf = []
        if cur in step_files:
            out_lines.append(f"<!-- illustrations:{cur}:start -->")
            for o, files in step_files[cur]:
                for f in files:
                    out_lines.append(f"![{o.get('label', 'object')}](illustrations/{f})")
            out_lines.append(f"<!-- illustrations:{cur}:end -->")
            out_lines.append("")
        if cur in extra:
            out_lines.append(f"<!-- accepted-visuals:{cur}:start -->")
            for url, caption in extra[cur]:
                out_lines.append(f"![accepted visual — {caption}]({url})")
            out_lines.append(f"<!-- accepted-visuals:{cur}:end -->")
            out_lines.append("")
        cur = None

    for line in (md.strip() + "\n").split("\n"):
        m_step = re.match(r"^###\s+(\d+)[\.\)]", line)
        if m_step:
            flush()
            cur = int(m_step.group(1))
            seen_steps.add(cur)
            buf.append(line)
        elif re.match(r"^##\s+", line):
            flush()
            buf.append(line)
        else:
            buf.append(line)
    flush()
    # Accepted visuals whose step has no matching ### section (e.g. terse
    # model output) are appended once under their own heading rather than
    # silently dropped — still labelled, still idempotent.
    leftover = {n: v for n, v in extra.items() if n not in seen_steps}
    if leftover:
        out_lines.append("<!-- accepted-visuals:general:start -->")
        out_lines.append("## Accepted visuals")
        out_lines.append("")
        for n in sorted(leftover):
            for url, caption in leftover[n]:
                out_lines.append(f"![accepted visual — step {n}: {caption}]({url})")
        out_lines.append("<!-- accepted-visuals:general:end -->")
        out_lines.append("")
    return "\n".join(out_lines).strip() + "\n"


def _set(db, job: M.TutorialJob, **kw) -> None:
    for k, v in kw.items():
        setattr(job, k, v)
    db.commit()


def _segment_object(job_dir: Path, source: Path, tracking: Path, file_id: str, obj: dict, prompt_override: str | None = None) -> dict:
    candidates = [prompt_override] if prompt_override is not None else prompt_variants(obj["label"])
    frames: list[dict] = []
    result: dict = {"simulated": True, "status": "error", "note": "No SAM attempt was made."}
    tried: list[dict] = []
    prompt_used = obj["label"]
    for cand in candidates[:MAX_PROMPT_ATTEMPTS]:
        result = ai.segment_video_clip(file_id, cand)
        tried.append({"prompt": cand, "status": result.get("status"), "frames": len(result.get("frames", [])),
                      "simulated": bool(result.get("simulated"))})
        prompt_used = cand
        if result.get("simulated"):
            break  # provider down: stop burning calls
        if result.get("status") != "no_match" and result.get("frames"):
            break
    out = {**obj, "track": [], "simulated": result.get("simulated", True), "prompt_used": prompt_used, "attempts": tried}
    out.update(_track_stats(result.get("frames", [])))
    out.update({"distinct_count": 0, "margin": None, "best_frame": None, "best_time": None,
                "best_confidence": None, "best_bbox_norm": None, "diagnostic_frame": None})
    if result.get("simulated"):
        out.update({"status": "error", "confidence": None, "note": result.get("note", "SAM unavailable")})
        return out
    best, distinct, margin = _best_track(result.get("frames", []))
    out["distinct_count"] = distinct
    out["margin"] = margin
    if best:
        out["track"] = [{"frame": f.get("frame", 0), "objects": [
            {"object_id": o.get("object_id"), "bbox_norm": o.get("bbox_norm"), "confidence": o.get("confidence")}
            for o in (f.get("objects") or [])]} for f in result.get("frames", [])]
    if not best:
        # One bounded hi-res retry before giving up: small objects are the
        # most common miss at 512px tracking resolution. Earlier attempts are
        # kept so the timeline shows the full trail.
        hired = _hirez_retry(job_dir, source, obj, prompt_used, prior_attempts=tried)
        if hired is not None:
            return hired
        out.update({"status": "needs_tap", "confidence": None,
                    "note": f"SAM found no match for “{obj['label']}” (tried: {', '.join('“' + t['prompt'] + '”' for t in tried)}). Tap the object in the guide to correct it."})
        return out
    conf = best.get("confidence")
    out["confidence"] = conf
    out["best_frame"] = best["frame"]
    out["best_time"] = float(best.get("frame", 0)) / TRACKING_FPS
    out["best_confidence"] = conf
    out["best_bbox_norm"] = best.get("bbox_norm")
    ill = make_illustrations(job_dir, source, obj, best)
    out.update(ill)
    ambiguous = distinct > 1 and (conf is None or margin < CLOSE_MARGIN)
    if conf is not None and conf < REVIEW_CONF:
        out["status"] = "needs_tap"
        out["note"] = f"Very low SAM confidence ({conf:.0%}) — tap the object in the guide to correct it."
    elif ambiguous or (conf is not None and conf < OK_CONF):
        out["status"] = "needs_tap"
        out["note"] = "Low confidence or multiple matches — tap the object in the guide to correct it."
    else:
        out["status"] = "ok"
    return out


GUIDE_FORMATS: dict[str, dict[str, str]] = {
    "work_instruction": {
        "name": "Illustrated Work Instruction",
        "tagline": "Visual, numbered instructions with relevant images and concise actions.",
        "best_for": "Technicians who need to understand and perform a task without reading a long manual.",
    },
    "reference_manual": {
        "name": "Reference Manual",
        "tagline": "A structured technical reference with sections, diagrams, source material, and supporting details.",
        "best_for": "Finding information, understanding context, and returning to specific sections later.",
    },
    "interactive": {
        "name": "Interactive Guided Execution",
        "tagline": "A step-by-step workflow for completing the task and recording outcomes in the field.",
        "best_for": "Field execution with minimal distractions, large touch targets, and recorded outcomes.",
    },
}

FORMAT_STRUCTURE_HINTS = {
    "work_instruction": (
        "Structure: # title, a 2-3 sentence task objective, ## Before you start (prerequisites + tools), "
        "## Safety only if the transcript supports it, ## Steps with one ### per step including its time range like (0:45-1:10) "
        "and 2-4 imperative sentences starting with a verb, each step ending with an 'Expected:' verification line where supported, "
        "## If something goes wrong only if supported. Never invent tools, values, warnings, or steps."
    ),
    "reference_manual": (
        "Structure: # title plus scope, ## Equipment (only if identifiable from input, else omit), "
        "## Prerequisites, ## Tools and materials (only items named in the input), ## Safety (only transcript-supported notes), "
        "## Procedure overview (2-3 sentences), ## Numbered procedure (same ### per step with time ranges), "
        "## Expected outcomes (only supported checkpoints), ## Troubleshooting (only supported), "
        "## Sources (transcript ranges and objects used). Never invent torque, ratings, measurements, model identities, "
        "or specifications; omit unsupported sections entirely."
    ),
    "interactive": (
        "Structure: # title, one-line objective, ## Before you start (prerequisites + tools only if in input), "
        "## Steps with one ### per step including its time range, each step exactly: one imperative instruction paragraph, "
        "then an 'Expected:' line only if verifiable from input, then a 'Watch for:' safety line only if transcript-supported. "
        "Keep each step self-contained for field execution. Never invent checks, values, or warnings."
    ),
}


def recommend_format(job: M.TutorialJob) -> dict:
    """Deterministic default-format recommendation from actual source data.

    Returns {format, rationale, scores}. No LLM call: the inputs are counts
    the pipeline already measured, so the choice is explainable and stable.
    """
    steps = job.steps or []
    objects = job.objects or []
    segments = job.timed_segments or []
    text_len = len(job.full_transcript or "")
    n_steps = len(steps)
    n_objects = len(objects)
    n_illustrated = sum(1 for o in objects if o.get("illustration") or o.get("overlay"))
    n_verified = sum(1 for o in objects if o.get("status") == "ok")
    expected_hits = sum(1 for s in steps if (s.get("summary") or "").strip())
    has_times = sum(1 for s in steps if s.get("start") is not None and s.get("end") is not None)
    reasons: list[str] = []
    scores = {
        "work_instruction": 0,
        "reference_manual": 0,
        "interactive": 0,
    }
    if n_steps >= 2:
        scores["work_instruction"] += 2
        scores["interactive"] += 2
        reasons.append(f"{n_steps} distinct steps")
    if n_illustrated > 0:
        scores["work_instruction"] += 2
        scores["interactive"] += 1
        reasons.append(f"{n_illustrated} illustrated object(s)")
    if n_verified > 0:
        scores["work_instruction"] += 1
    if text_len >= 200 or len(segments) >= 3:
        scores["reference_manual"] += 2
        reasons.append("rich transcript for context sections")
    if expected_hits == n_steps and n_steps > 0:
        scores["interactive"] += 1
        scores["reference_manual"] += 1
        reasons.append("every step has a verifiable outcome")
    if has_times == n_steps and n_steps > 0:
        scores["interactive"] += 1
        reasons.append("all steps timestamped for execution order")
    if (job.materials or []):
        scores["reference_manual"] += 1
        reasons.append("materials list available")
    if not steps:
        return {"format": "reference_manual",
                "rationale": "No structured steps were detected; a reference-style document preserves the transcript without inventing a procedure.",
                "scores": scores}
    best = max(scores, key=lambda k: scores[k])
    if best == "work_instruction":
        why = "the tutorial contains clear sequential actions" + (f" with {n_illustrated} illustrated object(s)" if n_illustrated else "")
    elif best == "interactive":
        why = "steps are sequential and timestamped for field execution"
    else:
        why = "the source is richest in explanatory context"
    if reasons:
        why += " (" + "; ".join(reasons[:3]) + ")"
    return {"format": best, "rationale": f"Recommended because {why}.", "scores": scores}


def _format_for_job(job: M.TutorialJob) -> tuple[str, str, str]:
    """Effective (format, source, rationale): explicit user choice wins."""
    if job.guide_format in GUIDE_FORMATS:
        src = job.format_source or "user"
        why = job.format_rationale or "Selected explicitly; kept as-is."
        return job.guide_format, src, why
    rec = recommend_format(job)
    return rec["format"], "recommended", rec["rationale"]


def _track_stats(frames: list[dict]) -> dict:
    """Coverage diagnostics for one SAM result: how many frames carried a match."""
    seen = len(frames or [])
    matched = sum(1 for f in (frames or []) if f.get("objects"))
    return {"frames_seen": seen, "frames_with_match": matched,
            "coverage": (matched / seen) if seen else 0.0}


def _hirez_retry(job_dir: Path, source: Path, obj: dict, prompt: str,
                 prior_attempts: list[dict] | None = None) -> dict | None:
    """One bounded re-run on a higher-res tracking copy for failed objects.

    Prior low-res attempts are preserved (appended, never replaced) so the
    processing timeline shows the full diagnostic trail.
    """
    try:
        hired = job_dir / "tracking-hirez.mp4"
        if not hired.exists():
            make_tracking_copy(source, hired, max_width=HIREZ_MAX_WIDTH)
        file_id = ai.upload_video_file(hired.read_bytes(), "tracking-hirez.mp4")
        try:
            result = ai.segment_video_clip(file_id, prompt)
        finally:
            ai.delete_video_file(file_id)
        if result.get("simulated") or not result.get("frames"):
            return None
        best, distinct, margin = _best_track(result.get("frames", []))
        if not best:
            return None
        out = {**obj, "simulated": False, "prompt_used": prompt,
               "attempts": list(prior_attempts or []) + [
                   {"prompt": prompt + " (hi-res retry)", "status": result.get("status"),
                    "frames": len(result.get("frames", [])), "simulated": False}],
               "track": [{"frame": f.get("frame", 0), "objects": [
                   {"object_id": o.get("object_id"), "bbox_norm": o.get("bbox_norm"), "confidence": o.get("confidence")}
                   for o in (f.get("objects") or [])]} for f in result.get("frames", [])]}
        out.update(_track_stats(result.get("frames", [])))
        conf = best.get("confidence")
        out["confidence"] = conf
        out["best_frame"] = best["frame"]
        out["best_time"] = float(best.get("frame", 0)) / TRACKING_FPS
        out["best_confidence"] = conf
        out["best_bbox_norm"] = best.get("bbox_norm")
        out["distinct_count"] = distinct
        out["margin"] = margin
        out.update(make_illustrations(job_dir, source, obj, best))
        ambiguous = distinct > 1 and (conf is None or margin < CLOSE_MARGIN)
        if (conf is not None and conf < REVIEW_CONF) or ambiguous:
            out["status"] = "needs_tap"
            out["note"] = "Matched at higher resolution but still uncertain — tap to confirm."
        else:
            out["status"] = "ok"
        return out
    except Exception:
        return None


def accepted_visuals_by_step(db, version_id: str) -> dict[int, list[tuple[str, str]]]:
    """Accepted review visuals per draft step_order, for guide injection.

    Only visuals a human explicitly accepted (Evidence rows carrying a
    visual_asset_id) are included, labelled as accepted — never presented
    as source evidence. Missing rows/assets are skipped, never fabricated.
    """
    out: dict[int, list[tuple[str, str]]] = {}
    ver = db.get(M.ProcedureVersion, version_id) if version_id else None
    if ver is None:
        return out
    for st in sorted(ver.steps, key=lambda x: x.step_order):
        for eid in (st.visual_refs or []):
            e = db.get(M.Evidence, eid)
            if e is None or e.evidence_type != "image":
                continue
            va_id = (e.extra or {}).get("visual_asset_id")
            if not va_id:
                continue
            va = db.get(M.VisualAsset, va_id)
            if va is None or va.status != "accepted":
                continue
            kind = va.kind.replace("_", " ")
            caption = f"{kind} — {va.instruction or va_id[:8]}".strip()
            out.setdefault(st.step_order, []).append((f"/api/evidence/{e.id}/image", caption))
    return out


def _canon_list(steps: list) -> list[dict]:
    """JSON-stable canonical step identity (order, title, instruction)."""
    return [{"n": int(s.get("step_number", 0)), "t": str(s.get("title", "")),
             "i": str(s.get("summary", ""))} for s in (steps or [])]


def _canonical_hash(steps: list) -> str:
    """Stable identity of the canonical step list (titles + instructions)."""
    import hashlib as _hashlib
    import json as _json
    return _hashlib.sha256(_json.dumps(_canon_list(steps), sort_keys=True).encode("utf-8")).hexdigest()


def _ensure_object_evidence(db, job: M.TutorialJob, objects: list) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """Ensure one Evidence row per illustration/cutout/diagnostic file.

    Idempotent: existing rows (same tutorial + storage key) are reused, so
    re-syncs never duplicate evidence. Returns (all_refs, overlay_refs) by
    obj_id. Diagnostic frames are linked as evidence (not presentation
    visuals) so reviewers always see what SAM was asked about.
    """
    existing = {e.storage_key: e.id for e in
                db.scalars(select(M.Evidence).where(
                    M.Evidence.source_reference == f"tutorial:{job.id}")).all()}
    ev_by_obj: dict[int, list[str]] = {}
    overlay_by_obj: dict[int, list[str]] = {}
    for o in (objects or []):
        oid = int(o.get("obj_id", 0))
        names = [("overlay", o.get("overlay")), ("cutout", o.get("illustration")),
                 ("diagnostic", o.get("diagnostic_frame")), ("tap", o.get("tap_frame"))]
        for kind, name in names:
            if not name:
                continue
            key = f"data/tutorials/{job.id}/{name}"
            eid = existing.get(key)
            if eid is None:
                path = BASE / "data" / "tutorials" / job.id / name
                if not path.is_file():
                    continue
                e = M.Evidence(capture_session_id=None, evidence_type="image",
                               storage_key=key,
                               description=f"Tutorial illustration ({kind}): {o.get('label', 'object')}",
                               source_reference=f"tutorial:{job.id}", created_by=job.actor,
                               extra={"tutorial_id": job.id, "obj_id": o.get("obj_id"), "kind": kind})
                db.add(e)
                db.flush()
                eid = e.id
                existing[key] = eid
            ev_by_obj.setdefault(oid, []).append(eid)
            if kind == "overlay":
                overlay_by_obj.setdefault(oid, []).append(eid)
    return ev_by_obj, overlay_by_obj


def _build_draft_steps(db, ver: M.ProcedureVersion, steps: list, objects: list,
                       ev_by_obj: dict[int, list[str]], overlay_by_obj: dict[int, list[str]],
                       preserve_visual_refs: dict[int, list[str]] | None = None) -> list:
    """Replace all steps of an editable draft from the canonical step list.

    Manually linked visuals (accepted Muse Image outputs etc.) that are not
    derived from object illustrations are preserved per step_order.
    Returns the created step rows (the ver.steps collection is stale after
    delete+flush, so callers must use the return value, not ver.steps).
    """
    for s in list(ver.steps):
        db.delete(s)
    db.flush()
    created: list = []
    for s in (steps or []):
        used = [int(x) for x in (s.get("objects_used") or []) if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
        refs: list[str] = []
        visuals: list[str] = []
        for oid in used:
            refs.extend(ev_by_obj.get(int(oid), []))
            visuals.extend(overlay_by_obj.get(int(oid), []))
        order = int(s.get("step_number", 1))
        for extra in (preserve_visual_refs or {}).get(order, []):
            if extra not in visuals:
                visuals.append(extra)
        try:
            start_sec = float(s.get("start")) if s.get("start") is not None else None
        except (TypeError, ValueError):
            start_sec = None
        try:
            end_sec = float(s.get("end")) if s.get("end") is not None else None
        except (TypeError, ValueError):
            end_sec = None
        row = M.ProcedureStep(
            procedure_version_id=ver.id, step_order=order,
            title=str(s.get("title", "")) or f"Step {s.get('step_number', 1)}",
            instruction=str(s.get("summary", "")),
            expected_result="", required_tools=[],
            evidence_refs=refs, visual_refs=visuals,
            start_sec=start_sec, end_sec=end_sec,
            verification_notes="From tutorial narration; verify against source video.")
        db.add(row)
        created.append(row)
    db.flush()
    return created


def _draft_step_hash(ver: M.ProcedureVersion) -> str:
    import hashlib as _hashlib
    import json as _json
    cur = [{"n": s.step_order, "t": s.title or "", "i": s.instruction or ""}
           for s in sorted(ver.steps, key=lambda x: x.step_order)]
    return _hashlib.sha256(_json.dumps(cur, sort_keys=True).encode("utf-8")).hexdigest()


def sync_review_draft(db, job: M.TutorialJob, steps: list, objects: list, md: str,
                      materials: list, model: str = "", simulated: bool = True,
                      actor: str = "", snapshot_id: str = "") -> tuple[M.ProcedureVersion | None, str, dict]:
    """Sync the linked Review draft with regenerated canonical content.

    Returns (version, action, detail) with action in:
    - "created": no draft existed; one was created.
    - "updated": editable draft steps replaced from canonical content.
    - "unchanged": editable draft already matches canonical content.
    - "conflict": draft has expert step edits AND canonical content changed;
      draft steps are kept, conflicting steps flagged for review.
    - "locked": draft is pending_review/approved/superseded; caller must fork.
    Never modifies locked versions. Never fabricates content.
    """
    from . import processing as proc
    detail: dict = {"changed_steps": [], "conflicting_steps": []}
    if not job.draft_version_id:
        ver = _ensure_review_draft(db, job, steps, objects, md, materials,
                                   model=model, simulated=simulated, actor=actor,
                                   snapshot_id=snapshot_id)
        return ver, ("created" if ver is not None else "failed"), detail
    ver = db.get(M.ProcedureVersion, job.draft_version_id)
    if ver is None:
        job.draft_version_id = ""
        ver = _ensure_review_draft(db, job, steps, objects, md, materials,
                                   model=model, simulated=simulated, actor=actor,
                                   snapshot_id=snapshot_id)
        return ver, ("created" if ver is not None else "failed"), detail
    if ver.status not in ("draft", "rejected"):
        return ver, "locked", detail
    ev_by_obj, overlay_by_obj = _ensure_object_evidence(db, job, objects)
    new_canon = _canon_list(steps)
    new_hash = _canonical_hash(steps)
    stored_canon: list[dict] = list((ver.source_evidence or {}).get("canonical_steps", []))
    stored_by_n = {c["n"]: c for c in stored_canon}
    new_by_n = {c["n"]: c for c in new_canon}
    draft_by_n = {s.step_order: {"n": s.step_order, "t": s.title or "", "i": s.instruction or ""}
                  for s in ver.steps}
    # Preserve manually linked visuals (accepted derivatives) across rebuilds.
    preserved: dict[int, list[str]] = {}
    fresh_visuals: dict[int, set[str]] = {}
    for s in (steps or []):
        used = [int(x) for x in (s.get("objects_used") or []) if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
        refs: set[str] = set()
        for oid in used:
            refs.update(overlay_by_obj.get(int(oid), []))
        fresh_visuals[int(s.get("step_number", 1))] = refs
    for st in ver.steps:
        extra = [v for v in (st.visual_refs or []) if v not in fresh_visuals.get(st.step_order, set())]
        if extra:
            preserved.setdefault(st.step_order, []).extend(extra)
    if new_canon == stored_canon and stored_canon:
        action = "unchanged"
    else:
        # Per-step 3-way sync. Steps the expert never touched follow the new
        # canonical text automatically (including brand-new and removed
        # steps). A step the expert edited AND whose canonical source also
        # changed is kept verbatim and flagged. Steps that exist only in the
        # draft (expert additions) are preserved as-is and never flagged.
        auto_orders: list[int] = []
        conflict_orders: list[int] = []
        for n in set(draft_by_n) | set(new_by_n) | set(stored_by_n):
            d, s, w = draft_by_n.get(n), stored_by_n.get(n), new_by_n.get(n)
            if w == d:
                continue
            if d == s:
                auto_orders.append(n)
            elif d is not None and w is not None:
                conflict_orders.append(n)
        detail["changed_steps"] = sorted(auto_orders)
        detail["conflicting_steps"] = sorted(conflict_orders)
        expert_only = [draft_by_n[n] for n in sorted(set(draft_by_n) - set(new_by_n) - set(stored_by_n))]
        kept = {n: draft_by_n[n] for n in conflict_orders if n in draft_by_n}
        created = _build_draft_steps(db, ver, steps, objects, ev_by_obj, overlay_by_obj, preserved)
        used_orders = {st.step_order for st in created}
        for st in created:
            if st.step_order in kept:
                st.title, st.instruction = kept[st.step_order]["t"], kept[st.step_order]["i"]
        for ex in expert_only:
            order = ex["n"] if ex["n"] not in used_orders else max(used_orders | {0}) + 1
            used_orders.add(order)
            db.add(M.ProcedureStep(procedure_version_id=ver.id, step_order=order,
                                   title=ex["t"], instruction=ex["i"],
                                   expected_result="", required_tools=[],
                                   evidence_refs=[], visual_refs=[],
                                   verification_notes="Added by expert review; not from tutorial narration."))
        db.flush()
        action = "conflict" if conflict_orders else "updated"
    se = dict(ver.source_evidence or {})
    se.update({"tutorial_id": job.id, "guide_snapshot_id": snapshot_id or se.get("guide_snapshot_id", ""),
               "guide_format": job.guide_format or "", "format_source": job.format_source or "",
                "canonical_hash": new_hash,
                "canonical_steps": new_canon,
               "sync": {"action": action, "snapshot_id": snapshot_id,
                        "changed_steps": detail["changed_steps"],
                        "conflicting_steps": detail["conflicting_steps"]}})
    ver.source_evidence = se
    from sqlalchemy.orm.attributes import flag_modified as _flag_modified
    _flag_modified(ver, "source_evidence")
    db.commit()
    db.refresh(ver)
    proc.safe_record(db, "tutorial", job.id, "draft", "succeeded", operation="sync_review_draft",
                     actor=actor or job.actor,
                     summary={"version_id": ver.id, "action": action,
                              "changed_steps": detail["changed_steps"],
                              "conflicting_steps": detail["conflicting_steps"]})
    return ver, action, detail


def fork_locked_revision(db, base: M.ProcedureVersion, job: M.TutorialJob, actor: str,
                          snapshot_id: str, fmt: str, model: str = "", simulated: bool = True) -> M.ProcedureVersion:
    """Fork a new editable revision from a locked version (byte-identical copy).

    Used when fresh content arrives while the linked draft is locked: the
    locked version is never mutated, per the normal review flow.
    """
    from . import main as _main
    nxt = (db.scalar(select(func.max(M.ProcedureVersion.version_number)).where(
        M.ProcedureVersion.procedure_id == base.procedure_id)) or 0) + 1
    nv = M.ProcedureVersion(procedure_id=base.procedure_id, version_number=nxt, status="draft",
                            summary=base.summary, prerequisites=base.prerequisites,
                            source_evidence=dict(base.source_evidence or {}, tutorial_id=job.id,
                                                  guide_snapshot_id=snapshot_id, guide_format=fmt),
                            ai_model=model, ai_simulated=1 if simulated else 0,
                            created_by=actor)
    db.add(nv)
    db.flush()
    for s in base.steps:
        db.add(M.ProcedureStep(procedure_version_id=nv.id, step_order=s.step_order, title=s.title,
                               instruction=s.instruction, expected_result=s.expected_result,
                               required_tools=list(s.required_tools or []),
                               evidence_refs=list(s.evidence_refs or []),
                               visual_refs=list(s.visual_refs or []),
                               verification_notes=s.verification_notes,
                               start_sec=s.start_sec, end_sec=s.end_sec))
    job.draft_version_id = nv.id
    db.commit()
    db.refresh(nv)
    _main.audit(db, actor, "procedure.draft", "procedure_version", nv.id,
                {"tutorial_id": job.id, "from_format_change": True, "snapshot_id": snapshot_id})
    return nv


def regenerate_guide_for_job(db, job: M.TutorialJob, trigger: str, fmt: str | None = None,
                             actor: str = "") -> dict:
    """Regenerate the guide markdown from current canonical content and sync the draft.

    Single choke point for tap corrections, visual acceptance, refresh, and
    format changes: new snapshot every time (history preserved), draft synced
    or forked (never silently mutated), approved versions untouched.
    Returns {snapshot_id, markdown_chars, draft_version_id, draft_action, format}.
    """
    from . import processing as proc
    if fmt is None:
        fmt, fsrc, why = _format_for_job(job)
    else:
        fsrc, why = "user", "Selected explicitly by the user."
    if fmt != (job.guide_format or ""):
        job.format_source, job.format_rationale = fsrc, why
        job.guide_format = fmt
    steps, objects = job.steps or [], job.objects or []
    with proc.timed() as t:
        guide = ai.generate_guide(job.title, steps, objects, job.timed_segments or [], guide_format=fmt)
    md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, objects, fmt)
    md = inject_illustrations(md, steps, objects)
    # Accepted review visuals ride along as labelled presentation assets
    # (human-approved derivatives, never source evidence).
    try:
        extra = accepted_visuals_by_step(db, job.draft_version_id or "")
        if extra:
            md = inject_illustrations(md, steps, objects, extra)
    except Exception:
        pass
    proc.safe_record(db, "tutorial", job.id, "guide", "simulated" if guide.get("simulated") else "succeeded",
                     operation="regenerate_guide", provider="meta", model=guide.get("model", ""),
                     duration_ms=t.ms, actor=actor or job.actor,
                     summary={"trigger": trigger, "format": fmt, "format_source": fsrc,
                              "markdown_chars": len(md), "materials": len(guide.get("materials", [])),
                              "note": guide.get("note", "")})
    snap = snapshot_guide(db, job, trigger, md, objects, model=guide.get("model", ""),
                          simulated=bool(guide.get("simulated", True)), materials=guide.get("materials", []),
                          guide_format=fmt, format_source=fsrc, format_rationale=why)
    job.guide_markdown = md
    job.materials = guide.get("materials", [])
    db.commit()
    db.refresh(job)
    ver, action, detail = sync_review_draft(db, job, steps, objects, md, guide.get("materials", []),
                                            model=guide.get("model", ""),
                                            simulated=bool(guide.get("simulated", True)),
                                            actor=actor or job.actor, snapshot_id=snap.id)
    draft_status = (ver.status if ver is not None else None)
    if action == "locked":
        base = db.get(M.ProcedureVersion, job.draft_version_id) if job.draft_version_id else None
        if base is not None:
            nv = fork_locked_revision(db, base, job, actor or job.actor, snap.id, fmt,
                                     model=guide.get("model", ""),
                                     simulated=bool(guide.get("simulated", True)))
            proc.safe_record(db, "tutorial", job.id, "draft", "succeeded", operation="new_revision_from_format",
                             actor=actor or job.actor,
                             summary={"version_id": nv.id, "version_number": nv.version_number})
            ver, draft_status = nv, "new_revision"
    return {"snapshot_id": snap.id, "markdown_chars": len(md),
            "draft_version_id": job.draft_version_id or None,
            "draft_status": draft_status, "draft_action": action,
            "detail": detail, "format": fmt, "format_source": fsrc, "rationale": why}


def _ensure_review_draft(db, job: M.TutorialJob, steps: list, objects: list, md: str,
                         materials: list, model: str = "", simulated: bool = True,
                         actor: str = "", snapshot_id: str = "") -> M.ProcedureVersion | None:
    """Create (once) the persistent Review-queue draft linked to a tutorial.

    Idempotent on job.draft_version_id: re-running never duplicates the draft.
    Evidence rows point at the tutorial's illustration PNGs so reviewers see
    the SAM highlights beside the draft. Failures are recorded as events and
    re-raised for the caller to mark retryable.
    """
    from . import processing as proc
    if job.draft_version_id:
        existing = db.get(M.ProcedureVersion, job.draft_version_id)
        if existing is not None:
            return existing
    with proc.timed() as t:
        ev_by_obj, overlay_by_obj = _ensure_object_evidence(db, job, objects)
        procedure = M.Procedure(title=f"{job.title} (tutorial)", asset_type="training-assembly",
                          created_by=actor or job.actor)
        db.add(procedure)
        db.flush()
        ver = M.ProcedureVersion(
            procedure_id=procedure.id, version_number=1, status="draft",
            summary=f"Draft generated from tutorial “{job.title}”. Review SAM highlights and transcript before approving.",
            prerequisites="", ai_model=model or "tutorial-pipeline",
            ai_simulated=1 if simulated else 0, created_by=actor or job.actor,
            source_evidence={"tutorial_id": job.id,
                             "guide_format": job.guide_format or "",
                             "format_source": job.format_source or "",
                             "guide_snapshot_id": snapshot_id,
                             "canonical_hash": _canonical_hash(steps),
                             "canonical_steps": _canon_list(steps),
                             "transcript_chars": len(job.full_transcript or ""),
                             "segments": len(job.timed_segments or []),
                             "objects": [{"obj_id": o.get("obj_id"), "label": o.get("label"),
                                          "status": o.get("status")} for o in (objects or [])]})
        db.add(ver)
        db.flush()
        n_steps = _build_draft_steps(db, ver, steps, objects, ev_by_obj, overlay_by_obj)
        job.draft_procedure_id = procedure.id
        job.draft_version_id = ver.id
        from . import main as _main  # local import: audit lives on the app module
        _main.audit(db, actor or job.actor, "procedure.draft", "procedure_version", ver.id,
                   {"tutorial_id": job.id, "simulated": bool(simulated)})
        db.commit()
    proc.safe_record(db, "tutorial", job.id, "draft", "succeeded",
                     operation="ensure_review_draft", model=model, duration_ms=t.ms, actor=actor or job.actor,
                     summary={"procedure_id": procedure.id, "version_id": ver.id,
                              "steps": len(steps or []), "evidence": sum(len(v) for v in ev_by_obj.values())})
    return ver


def _diagnostic_frame(job_dir: Path, source: Path, obj: dict) -> str | None:
    """Save a small JPEG of the frame where the object was first mentioned.

    Used when SAM found nothing to track: reviewers see what the model was
    asked to find instead of an empty state.
    """
    try:
        t = float(obj.get("first_mentioned_at") or 0)
        frame = extract_frame_image(source, t)
        frame.thumbnail((640, 640))
        name = f"diag-obj-{int(obj.get('obj_id', 0))}.jpg"
        frame.convert("RGB").save(job_dir / name, "JPEG", quality=80)
        return name
    except Exception:
        return None


def snapshot_guide(db, job: M.TutorialJob, trigger: str, md: str, objects: list | None,
                   model: str = "", simulated: bool = True, materials: list | None = None,
                   guide_format: str = "", format_source: str = "", format_rationale: str = "") -> M.GuideSnapshot:
    """Persist an immutable record of one guide generation.

    The live guide_markdown on TutorialJob keeps moving (refreshes, tap
    corrections); snapshots preserve what each generation produced, with
    which models, from which objects, in which format, and why.
    """
    import hashlib as _hashlib
    snap = M.GuideSnapshot(
        tutorial_id=job.id, trigger=trigger, model=model, simulated=bool(simulated),
        guide_markdown=md or "", guide_hash=_hashlib.sha256((md or "").encode("utf-8")).hexdigest(),
        materials=list(materials or []),
        guide_format=guide_format or getattr(job, "guide_format", "") or "",
        format_source=format_source or getattr(job, "format_source", "") or "",
        format_rationale=format_rationale or getattr(job, "format_rationale", ""),
        object_statuses=[{"obj_id": o.get("obj_id"), "label": o.get("label"),
                          "status": o.get("status"), "confidence": o.get("confidence")}
                         for o in (objects or [])])
    db.add(snap)
    db.flush()
    return snap


def run_job(job_id: str) -> None:
    from . import processing as proc
    db = SessionLocal()
    proc.new_correlation()
    try:
        job = db.get(M.TutorialJob, job_id)
        if job is None:
            return
        actor = job.actor or ""
        job_dir = BASE / "data" / "tutorials" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source = BASE / job.video_storage_key
        try:
            with proc.timed() as t:
                info = probe_video(source)
            proc.safe_record(db, "tutorial", job_id, "probe", "succeeded", operation="probe_video",
                             duration_ms=t.ms, actor=actor,
                             summary={"duration_sec": info["duration"], "width": info["width"], "height": info["height"]})
            if info["duration"] <= 0:
                raise RuntimeError("Could not read the uploaded video (unsupported format?)")
            if info["duration"] > MAX_VIDEO_SEC + 5:
                raise RuntimeError(f"Video is {info['duration']:.0f}s — tutorials are limited to {MAX_VIDEO_SEC}s (10 minutes)")
            if not info.get("has_audio", True):
                # Fail fast with an actionable message: retrying a silent video
                # can never succeed, and transcribing silence is not an option.
                proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                 operation="extract_audio_wav", duration_ms=0, actor=actor,
                                 summary={"has_audio": False,
                                          "note": "probe found no audio stream; failing before transcription"})
                raise NoAudioTrackError(
                    "This video has no audio track, so there is nothing to transcribe. "
                    "Record again with the microphone on and narrate each step as you show it.")
            _set(db, job, duration_sec=info["duration"], width=info["width"], height=info["height"], progress=8)

            _set(db, job, status="transcribing", progress=12)
            wav = job_dir / "audio.wav"
            try:
                extract_audio_wav(source, wav)
            except NoAudioTrackError:
                proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                 operation="extract_audio_wav", duration_ms=0, actor=actor,
                                 summary={"has_audio": False})
                raise
            except RuntimeError as ee:
                proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                 operation="extract_audio_wav", duration_ms=0, actor=actor,
                                 summary={"error_type": "RuntimeError", "ffmpeg": str(ee)[-300:]})
                raise
            with proc.timed() as t:
                tr = ai.transcribe_timed("audio.wav", wav.read_bytes(), duration_sec=info["duration"])
            proc.safe_record(
                db, "tutorial", job_id, "transcribe", "failed" if tr.get("error") else ("simulated" if tr.get("simulated") else "succeeded"),
                operation="transcribe_timed", provider="meta", model=tr.get("model", ""), duration_ms=t.ms, actor=actor,
                summary={"audio_sec": info["duration"], "text_chars": len(tr.get("text") or ""),
                         "segments": len(tr.get("segments") or []), "error": tr.get("error", ""),
                         "note": tr.get("note", "")})
            if tr.get("error"):
                raise RuntimeError(tr["error"])
            if not (tr.get("text") or "").strip():
                raise RuntimeError("No speech was transcribed. Check the microphone track and try again.")
            _set(db, job, full_transcript=tr["text"], timed_segments=tr["segments"], progress=30)

            _set(db, job, status="understanding", progress=38)
            with proc.timed() as t:
                und = ai.understand_tutorial(tr["segments"], info["duration"])
            objects, steps = und.get("objects", []), und.get("steps", [])
            proc.safe_record(
                db, "tutorial", job_id, "understand", "simulated" if und.get("simulated") else "succeeded",
                operation="understand_tutorial", provider="meta", model=und.get("model", ""), duration_ms=t.ms, actor=actor,
                summary={"objects": len(objects), "steps": len(steps),
                         "labels": [o.get("label") for o in objects],
                         "first_mentioned_at": [o.get("first_mentioned_at") for o in objects],
                         "note": und.get("note", "")})
            _set(db, job, objects=objects, steps=steps, progress=45)
            if not objects:
                _set(db, job, status="generating", progress=90)
                fmt, fsrc, why = _format_for_job(job)
                _set(db, job, guide_format=fmt, format_source=fsrc, format_rationale=why)
                with proc.timed() as t:
                    guide = ai.generate_guide(job.title, steps, objects, tr["segments"], guide_format=fmt)
                md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, objects, fmt)
                md = inject_illustrations(md, steps, objects)
                proc.safe_record(db, "tutorial", job_id, "guide", "simulated" if guide.get("simulated") else "succeeded",
                                 operation="generate_guide", provider="meta", model=guide.get("model", ""),
                                 duration_ms=t.ms, actor=actor,
                                 summary={"markdown_chars": len(md), "materials": len(guide.get("materials", [])),
                                          "note": guide.get("note", "")})
                snapshot = snapshot_guide(db, job, "initial", md, objects, model=guide.get("model", ""),
                                            simulated=bool(guide.get("simulated", True)), materials=guide.get("materials", []),
                                            guide_format=fmt, format_source=fsrc, format_rationale=why)
                db.commit()
                try:
                    _ensure_review_draft(db, job, steps, objects, md, guide.get("materials", []),
                                         model=guide.get("model", ""), simulated=bool(guide.get("simulated", True)),
                                         actor=actor, snapshot_id=snapshot.id)
                except Exception as de:
                    proc.safe_record(db, "tutorial", job_id, "draft", "failed",
                                     operation="ensure_review_draft", duration_ms=0, actor=actor,
                                     summary={"error_type": type(de).__name__, "error": str(de)[:300]})
                _set(db, job, guide_markdown=md, materials=guide.get("materials", []), status="done", progress=100)
                return

            _set(db, job, status="segmenting", progress=50)
            tracking = job_dir / "tracking.mp4"
            tinfo = make_tracking_copy(source, tracking)
            _set(db, job, track_width=tinfo["width"], track_height=tinfo["height"])
            if not ai.live_enabled():
                # Fully offline deterministic path: no provider calls at all.
                # Objects keep needs_tap status with REAL diagnostic frames
                # (local ffmpeg) so reviewers see what SAM was asked to find.
                done_objects = []
                for i, obj in enumerate(objects):
                    oo = dict(obj)
                    oo.update({"status": "needs_tap", "simulated": True, "confidence": None,
                               "note": "Simulated run — live SAM unavailable. Tap the object to correct it, or configure META_API_KEY and retry."})
                    try:
                        oo["diagnostic_frame"] = _diagnostic_frame(job_dir, source, obj)
                    except Exception:
                        oo["diagnostic_frame"] = None
                    proc.safe_record(db, "tutorial", job_id, "segment", "needs_tap",
                                     operation="segment_video_clip", provider="meta", model=ai.SAM_MODEL,
                                     duration_ms=0, actor=actor,
                                     summary={"obj_id": oo.get("obj_id"), "label": oo.get("label"),
                                              "note": "simulated: segmentation skipped offline"})
                    done_objects.append(oo)
                    _set(db, job, objects=done_objects + objects[i + 1:], progress=50 + int(30 * (i + 1) / max(len(objects), 1)))
            else:
                file_id = ai.upload_video_file(tracking.read_bytes(), "tracking.mp4")
            try:
                if ai.live_enabled():
                    done_objects = []
                    for i, obj in enumerate(objects):
                        with proc.timed() as t:
                            seg = _segment_object(job_dir, source, tracking, file_id, obj)
                        if seg.get("status") == "needs_tap" and not seg.get("illustration"):
                            seg["diagnostic_frame"] = _diagnostic_frame(job_dir, source, obj)
                        proc.safe_record(
                            db, "tutorial", job_id, "segment", seg.get("status") or "error",
                            operation="segment_video_clip", provider="meta", model=ai.SAM_MODEL,
                            duration_ms=t.ms, actor=actor,
                            summary={"obj_id": obj.get("obj_id"), "label": obj.get("label"),
                                     "prompt_used": seg.get("prompt_used"),
                                     "attempts": [{"prompt": a.get("prompt"), "status": a.get("status"),
                                                  "frames": a.get("frames"), "simulated": a.get("simulated")}
                                                 for a in (seg.get("attempts") or [])],
                                     "frames_seen": seg.get("frames_seen", 0),
                                     "frames_with_match": seg.get("frames_with_match", 0),
                                     "coverage": seg.get("coverage", 0.0),
                                     "distinct_count": seg.get("distinct_count", 0),
                                     "margin": seg.get("margin"),
                                     "best_frame": seg.get("best_frame"), "best_time": seg.get("best_time"),
                                     "best_confidence": seg.get("best_confidence"),
                                     "best_bbox_norm": seg.get("best_bbox_norm"),
                                     "has_illustration": bool(seg.get("illustration")),
                                     "note": seg.get("note", "")})
                        done_objects.append(seg)
                        _set(db, job, objects=done_objects + objects[i + 1:], progress=50 + int(30 * (i + 1) / len(objects)))
            finally:
                if ai.live_enabled():
                    ai.delete_video_file(file_id)

            _set(db, job, status="generating", progress=88, objects=done_objects)
            fmt, fsrc, why = _format_for_job(job)
            _set(db, job, guide_format=fmt, format_source=fsrc, format_rationale=why)
            with proc.timed() as t:
                guide = ai.generate_guide(job.title, steps, done_objects, tr["segments"], guide_format=fmt)
            md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, done_objects, fmt)
            md = inject_illustrations(md, steps, done_objects)
            proc.safe_record(db, "tutorial", job_id, "guide", "simulated" if guide.get("simulated") else "succeeded",
                             operation="generate_guide", provider="meta", model=guide.get("model", ""),
                             duration_ms=t.ms, actor=actor,
                             summary={"format": fmt, "format_source": fsrc,
                                      "markdown_chars": len(md), "materials": len(guide.get("materials", [])),
                                      "ok_objects": sum(1 for o in done_objects if o.get("status") == "ok"),
                                      "needs_tap": sum(1 for o in done_objects if o.get("status") == "needs_tap"),
                                      "note": guide.get("note", "")})
            snapshot = snapshot_guide(db, job, "initial", md, done_objects, model=guide.get("model", ""),
                                        simulated=bool(guide.get("simulated", True)), materials=guide.get("materials", []),
                                        guide_format=fmt, format_source=fsrc, format_rationale=why)
            db.commit()
            try:
                _ensure_review_draft(db, job, steps, done_objects, md,
                                     guide.get("materials", [o["label"] for o in done_objects]),
                                     model=guide.get("model", ""), simulated=bool(guide.get("simulated", True)),
                                     actor=actor, snapshot_id=snapshot.id)
            except Exception as de:
                proc.safe_record(db, "tutorial", job_id, "draft", "failed",
                                 operation="ensure_review_draft", duration_ms=0, actor=actor,
                                 summary={"error_type": type(de).__name__, "error": str(de)[:300]})
            _set(db, job, guide_markdown=md, materials=guide.get("materials", [o["label"] for o in done_objects]),
                 status="done", progress=100)
        except Exception as e:
            from . import processing as proc
            proc.safe_record(db, "tutorial", job_id, "run", "failed", operation="run_job",
                             summary={"error_type": type(e).__name__, "error": str(e)[:300]})
            _set(db, job, status="error", error=f"{type(e).__name__}: {str(e)[:300]}")
        finally:
            db.close()
    finally:
        try:
            db.close()
        except Exception:
            pass


def start_job(job_id: str) -> None:
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


def resegment_object_tap(job_id: str, obj_id: int, nx: float, ny: float) -> dict:
    """Re-track one object from a user tap (normalized coords on a video frame)."""
    from . import processing as proc
    proc.new_correlation()
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, job_id)
        if job is None:
            raise ValueError("Tutorial not found")
        job_dir = BASE / "data" / "tutorials" / job_id
        source = BASE / job.video_storage_key
        tracking = job_dir / "tracking.mp4"
        if ai.live_enabled() and not tracking.exists():
            # Live SAM needs the tracking copy; simulated tap only needs the
            # source video, so a broken/unsupported container must not block it.
            make_tracking_copy(source, tracking)
        objects = list(job.objects or [])
        obj = next((o for o in objects if int(o.get("obj_id", 0)) == obj_id), None)
        if obj is None:
            raise ValueError("Object not found")
        obj = dict(obj)
        obj.setdefault("taps", []).append({"nx": round(nx, 4), "ny": round(ny, 4)})
        if not ai.live_enabled():
            # Offline: no SAM call is possible. Record the tap with a REAL
            # local frame excerpt (ffmpeg) linked as evidence, refresh the
            # diagnostic frame, and regenerate from canonical content
            # (fallback renderer). Never claim tracking succeeded.
            try:
                frame = extract_frame_image(source, float(obj.get("first_mentioned_at", 0)))
                frame.thumbnail((960, 960))
                tap_name = f"tap-obj-{obj_id}.jpg"
                frame.convert("RGB").save(job_dir / tap_name, "JPEG", quality=85)
                obj["tap_frame"] = tap_name
            except Exception:
                pass
            obj.update({"status": "needs_tap", "simulated": True,
                        "note": "Tap recorded with a real frame excerpt; live SAM is unavailable so the object was not re-tracked. Configure META_API_KEY and retry, or correct the label in Review."})
            try:
                obj["diagnostic_frame"] = _diagnostic_frame(job_dir, source, obj) or obj.get("diagnostic_frame")
            except Exception:
                pass
            objects = [obj if int(o.get("obj_id", 0)) == obj_id else o for o in objects]
            _set(db, job, objects=objects)
            out = regenerate_guide_for_job(db, job, "tap", actor=job.actor or "")
            proc.safe_record(db, "tutorial", job_id, "tap", "recorded",
                             operation="tap_correction", provider="meta", model=ai.SAM_MODEL,
                             duration_ms=0, actor=job.actor or "",
                             summary={"obj_id": obj_id, "tap_nx": round(nx, 4), "tap_ny": round(ny, 4),
                                      "simulated": True, "snapshot_id": out["snapshot_id"],
                                      "draft_action": out["draft_action"]})
            obj["regenerated_snapshot_id"] = out["snapshot_id"]
            obj["draft_action"] = out["draft_action"]
            return obj
        t = float(obj.get("first_mentioned_at", 0))
        frame_idx = int(round(t * TRACKING_FPS))
        tw, th = job.track_width or TRACKING_MAX_WIDTH, job.track_height or 288
        prompt = ai.build_point_prompt(min(max(int(nx * tw), 0), tw - 1), min(max(int(ny * th), 0), th - 1), tw, th, obj_id=obj_id, frame=frame_idx)
        file_id = ai.upload_video_file(tracking.read_bytes(), "tracking.mp4")
        try:
            with proc.timed() as timer:
                updated = _segment_object(job_dir, source, tracking, file_id, obj, prompt_override=prompt)
        finally:
            ai.delete_video_file(file_id)
        if updated.get("status") == "needs_tap" and updated.get("illustration"):
            updated["status"] = "ok"  # user-confirmed tap is ground truth for this demo
            updated["note"] = "Corrected from your tap."
        updated.setdefault("taps", obj.get("taps", []))
        objects = [updated if int(o.get("obj_id", 0)) == obj_id else o for o in objects]
        _set(db, job, objects=objects)
        out = regenerate_guide_for_job(db, job, "tap", actor=job.actor or "")
        proc.safe_record(db, "tutorial", job_id, "tap", updated.get("status", "corrected"),
                         operation="tap_correction", provider="meta", model=ai.SAM_MODEL,
                         duration_ms=timer.ms, actor=job.actor or "",
                         summary={"obj_id": obj_id, "tap_nx": round(nx, 4), "tap_ny": round(ny, 4),
                                  "prompt_used": updated.get("prompt_used"),
                                  "attempts": [{"prompt": a.get("prompt"), "status": a.get("status"),
                                              "frames": a.get("frames")} for a in (updated.get("attempts") or [])],
                                  "best_confidence": updated.get("best_confidence"),
                                  "snapshot_id": out["snapshot_id"], "draft_action": out["draft_action"],
                                  "note": updated.get("note", "")})
        updated["regenerated_snapshot_id"] = out["snapshot_id"]
        updated["draft_action"] = out["draft_action"]
        return updated
    finally:
        db.close()


def start_tap_correction(job_id: str, obj_id: int, nx: float, ny: float) -> None:
    def _work():
        db = SessionLocal()
        try:
            job = db.get(M.TutorialJob, job_id)
            if job is not None:
                objs = list(job.objects or [])
                for o in objs:
                    if int(o.get("obj_id", 0)) == obj_id:
                        o["status"] = "processing"
                _set(db, job, objects=objs)
        finally:
            db.close()
        resegment_object_tap(job_id, obj_id, nx, ny)

    threading.Thread(target=_work, daemon=True).start()
