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
    return {"duration": dur, "width": w, "height": h}


def extract_audio_wav(source: Path, out: Path) -> None:
    proc = _run([_ffmpeg(), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(out)])
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("Could not extract an audio track from the video")


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


def inject_illustrations(md: str, steps: list[dict], objects: list[dict]) -> str:
    """Deterministically embed illustration links into guide Markdown.

    Appends an illustration block per step (for every objects_used entry
    that has PNGs) delimited by HTML comment markers, so re-running is
    idempotent: previous blocks are stripped first.
    """
    md = re.sub(r"\n?<!-- illustrations:\d+:start -->.*?<!-- illustrations:\d+:end -->\n?", "\n", md or "", flags=re.S)
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
    if not step_files:
        return md.strip() + "\n"
    out_lines: list[str] = []
    buf: list[str] = []
    cur: int | None = None

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
        cur = None

    for line in (md.strip() + "\n").split("\n"):
        m_step = re.match(r"^###\s+(\d+)[\.\)]", line)
        if m_step:
            flush()
            cur = int(m_step.group(1))
            buf.append(line)
        elif re.match(r"^##\s+", line):
            flush()
            buf.append(line)
        else:
            buf.append(line)
    flush()
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
        proc_obj = {int(o.get("obj_id", 0)): o for o in (objects or [])}
        ev_by_obj: dict[int, list[str]] = {}
        overlay_by_obj: dict[int, list[str]] = {}
        for o in (objects or []):
            # Link BOTH the annotated overlay (display) and the isolated cutout
            # (source detail) as evidence; visual_refs carries the overlay as
            # the primary presentation image, evidence_refs carries everything.
            oid = int(o.get("obj_id", 0))
            names = [("overlay", o.get("overlay")), ("cutout", o.get("illustration"))]
            for kind, name in names:
                if not name:
                    continue
                path = BASE / "data" / "tutorials" / job.id / name
                if not path.is_file():
                    continue
                e = M.Evidence(capture_session_id=None, evidence_type="image",
                               storage_key=f"data/tutorials/{job.id}/{name}",
                               description=f"Tutorial illustration ({kind}): {o.get('label', 'object')}",
                               source_reference=f"tutorial:{job.id}", created_by=actor or job.actor,
                               extra={"tutorial_id": job.id, "obj_id": o.get("obj_id"), "kind": kind})
                db.add(e)
                db.flush()
                ev_by_obj.setdefault(oid, []).append(e.id)
                if kind == "overlay":
                    overlay_by_obj.setdefault(oid, []).append(e.id)
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
                             "transcript_chars": len(job.full_transcript or ""),
                             "segments": len(job.timed_segments or []),
                             "objects": [{"obj_id": o.get("obj_id"), "label": o.get("label"),
                                          "status": o.get("status")} for o in (objects or [])]})
        db.add(ver)
        db.flush()
        for s in (steps or []):
            used = [int(x) for x in (s.get("objects_used") or []) if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
            refs: list[str] = []
            visuals: list[str] = []
            for oid in used:
                refs.extend(ev_by_obj.get(int(oid), []))
                visuals.extend(overlay_by_obj.get(int(oid), []))
            try:
                start_sec = float(s.get("start")) if s.get("start") is not None else None
            except (TypeError, ValueError):
                start_sec = None
            try:
                end_sec = float(s.get("end")) if s.get("end") is not None else None
            except (TypeError, ValueError):
                end_sec = None
            db.add(M.ProcedureStep(
                procedure_version_id=ver.id, step_order=int(s.get("step_number", 1)),
                title=str(s.get("title", "")) or f"Step {s.get('step_number', 1)}",
                instruction=str(s.get("summary", "")),
                expected_result="", required_tools=[],
                evidence_refs=refs, visual_refs=visuals,
                start_sec=start_sec, end_sec=end_sec,
                verification_notes="From tutorial narration; verify against source video."))
        db.flush()
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
            _set(db, job, duration_sec=info["duration"], width=info["width"], height=info["height"], progress=8)

            _set(db, job, status="transcribing", progress=12)
            wav = job_dir / "audio.wav"
            extract_audio_wav(source, wav)
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
                md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, objects)
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
            file_id = ai.upload_video_file(tracking.read_bytes(), "tracking.mp4")
            try:
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
                ai.delete_video_file(file_id)

            _set(db, job, status="generating", progress=88, objects=done_objects)
            fmt, fsrc, why = _format_for_job(job)
            _set(db, job, guide_format=fmt, format_source=fsrc, format_rationale=why)
            with proc.timed() as t:
                guide = ai.generate_guide(job.title, steps, done_objects, tr["segments"], guide_format=fmt)
            md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, done_objects)
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
        if not tracking.exists():
            make_tracking_copy(source, tracking)
        objects = list(job.objects or [])
        obj = next((o for o in objects if int(o.get("obj_id", 0)) == obj_id), None)
        if obj is None:
            raise ValueError("Object not found")
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
        objects = [updated if int(o.get("obj_id", 0)) == obj_id else o for o in objects]
        _set(db, job, objects=objects)
        try:
            snapshot_guide(db, job, "tap", job.guide_markdown or "", objects,
                           model=ai.SAM_MODEL, simulated=bool(updated.get("simulated", True)),
                           materials=job.materials or [])
            db.commit()
        except Exception:
            db.rollback()
        proc.safe_record(db, "tutorial", job_id, "tap", updated.get("status", "corrected"),
                         operation="tap_correction", provider="meta", model=ai.SAM_MODEL,
                         duration_ms=timer.ms, actor=job.actor or "",
                         summary={"obj_id": obj_id, "tap_nx": round(nx, 4), "tap_ny": round(ny, 4),
                                  "prompt_used": updated.get("prompt_used"),
                                  "attempts": [{"prompt": a.get("prompt"), "status": a.get("status"),
                                              "frames": a.get("frames")} for a in (updated.get("attempts") or [])],
                                  "best_confidence": updated.get("best_confidence"),
                                  "note": updated.get("note", "")})
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
