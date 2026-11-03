"""TutorialMode pipeline: upload -> Muse transcribe (turn timestamps)
-> Spark understanding -> SAM whole-clip tracking -> illustrations -> guide.

Runs in a background thread with DB-backed status/progress so a 2-10 min
tutorial never blocks a request. All provider keys stay server-side.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from PIL import Image, ImageDraw

from . import ai
from .db import SessionLocal
from . import models as M
from . import storage as _storage
from sqlalchemy import func, select

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


def prompt_variants(label: str, synonyms: list[str] | None = None) -> list[str]:
    """SAM prompt candidates: canonical label, synonyms, then simplification.

    Order matters (MAX_PROMPT_ATTEMPTS tries in sequence): exact phrase
    first, then a more specific synonym, then progressively simpler
    fallbacks. Mirrors frontend speechPrompt for consistency.
    """
    p = re.sub(r"\s+", " ", (label or "").strip().lower())
    if not p:
        return []
    cands: list[str] = [p]
    for s in (synonyms or []):
        q = re.sub(r"\s+", " ", str(s or "").strip().lower())
        if q and len(q) >= 2 and q not in cands:
            cands.append(q)
        if len(cands) >= MAX_PROMPT_ATTEMPTS:
            break
    words = p.split(" ")
    fallbacks: list[str] = []
    if len(words) >= 3:
        fallbacks.append(" ".join(words[1:]))  # drop leading adjective
    if len(words) >= 2:
        fallbacks.append(" ".join(words[-2:]))
    fallbacks.append(words[-1])  # head noun
    for f in fallbacks:
        if f not in cands and len(f) >= 2:
            cands.append(f)
        if len(cands) >= MAX_PROMPT_ATTEMPTS:
            break
    return cands[:MAX_PROMPT_ATTEMPTS]


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


def _illustration_quality(frame_w: int, frame_h: int, bx1: int, by1: int, bx2: int, by2: int,
                            cx1: int, cy1: int, cx2: int, cy2: int, mask_points: int) -> dict:
    """Automated quality checks for one generated crop.

    Flags (never silently fixes): empty/invalid masks, tiny crops below a
    useful resolution, boxes cut off by the crop edge, extreme aspect
    ratios, and crops with almost no surrounding context. A failing crop is
    still saved but marked needs_review with a recovery note.
    """
    bw, bh = max(0, bx2 - bx1), max(0, by2 - by1)
    cw, ch = max(0, cx2 - cx1), max(0, cy2 - cy1)
    issues: list[str] = []
    if not mask_points:
        issues.append("no mask polygon — bbox outline only")
    if min(cw, ch) < 48:
        issues.append(f"crop very small ({cw}x{ch}px) — may be illegible")
    # Box touches the crop edge on a side where the crop also touches the
    # frame edge: the component itself is likely cut off in the source frame.
    cut_sides = []
    if bx1 <= cx1 and cx1 <= 0:
        cut_sides.append("left")
    if by1 <= cy1 and cy1 <= 0:
        cut_sides.append("top")
    if bx2 >= cx2 and cx2 >= frame_w:
        cut_sides.append("right")
    if by2 >= cy2 and cy2 >= frame_h:
        cut_sides.append("bottom")
    if cut_sides:
        issues.append(f"component possibly cut off at frame edge ({', '.join(cut_sides)})")
    if cw and ch:
        ratio = max(cw, ch) / max(1, min(cw, ch))
        if ratio > 6:
            issues.append(f"extreme aspect ratio ({ratio:.1f}:1) — verify the crop")
    if bw and bh and cw and ch:
        context = (cw * ch) / max(1, bw * bh)
        if context < 1.2:
            issues.append("almost no surrounding context — hard to locate the component")
    return {"crop_px": [cw, ch], "frame_px": [frame_w, frame_h],
            "mask_points": mask_points, "cut_sides": cut_sides,
            "issues": issues, "needs_review": bool(issues)}


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
    quality = _illustration_quality(W, H, bx1, by1, bx2, by2, cx1, cy1, cx2, cy2, len(pts_frame))
    return {"illustration": iso_path.name, "overlay": overlay_path.name, "quality": quality}


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


def ensure_ai_step_illustrations(job_dir: Path, steps: list[dict], objects: list[dict],
                                 max_steps: int = 5) -> tuple[dict[int, str], list[dict]]:
    """Muse Image fallback for steps lacking verified SAM visuals.

    Only called when live. Generates at most `max_steps` explanatory
    illustrations (PNG) for steps with no ok overlay, using step text as
    context. Returns ({step_number: filename}, provenance_records).
    Results are ALWAYS labelled AI-generated, never as photos or SAM masks.
    Safety: prompts describe the action generically and never invent
    precise measurements, torque values, or safety-critical details — the
    caption directs technicians to verify against the real equipment and
    the original frame.
    """
    import base64 as _b64
    ok_steps = set()
    for o in objects or []:
        if o.get("status") == "ok" and (o.get("overlay") or o.get("illustration")):
            for s in steps or []:
                if str(o.get("obj_id")) in {str(x) for x in (s.get("objects_used") or [])}:
                    try:
                        ok_steps.add(int(s.get("step_number", 0)))
                    except (TypeError, ValueError):
                        pass
    out: dict[int, str] = {}
    prov: list[dict] = []
    if not ai.live_enabled():
        return out, prov
    made = 0
    for s in steps or []:
        try:
            n = int(s.get("step_number", 0))
        except (TypeError, ValueError):
            continue
        if n in ok_steps or made >= max_steps:
            continue
        title = str(s.get("title") or f"Step {n}")[:200]
        summary = str(s.get("summary") or "")[:800]
        if not (title.strip() or summary.strip()):
            continue
        prompt = (
            f"Explanatory technical illustration for a maintenance guide step. "
            f"Step {n}: {title}. {summary} "
            f"Clean line-art style, neutral background, show hands/tools generically. "
            f"Do NOT invent brand logos, precise measurements, torque values, or safety warnings. "
            f"This is a generic visual aid, not a photo of the exact equipment."
        )
        try:
            gen = ai.image_generate(prompt)
        except Exception as e:
            prov.append({"step_number": n, "status": "error",
                         "note": f"Muse Image failed ({type(e).__name__})", "ai_generated": True})
            continue
        if not gen.get("ok") or not gen.get("image_b64"):
            prov.append({"step_number": n, "status": gen.get("status", "error"),
                         "note": gen.get("note", "Muse Image unavailable"),
                         "model": gen.get("model", ai.IMAGE_MODEL),
                         "simulated": bool(gen.get("simulated", False)),
                         "ai_generated": True})
            continue
        try:
            raw = _b64.b64decode(gen["image_b64"])
            name = f"ai-step-{n}.png"
            (job_dir / name).write_bytes(raw)
            out[n] = name
            made += 1
            prov.append({"step_number": n, "status": "ok", "file": name,
                         "model": gen.get("model", ai.IMAGE_MODEL),
                         "simulated": False, "ai_generated": True,
                         "note": "AI-generated explanatory illustration — not a photo, not a SAM mask. Verify against real equipment."})
        except Exception as e:
            prov.append({"step_number": n, "status": "error",
                         "note": f"Could not persist illustration ({type(e).__name__})",
                         "ai_generated": True})
    return out, prov


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
    # Step headings come in several shapes (live model output, offline
    # fallbacks, user edits). Anything unrecognized keeps its text;
    # matching is never guessed.
    for o in objects or []:
        files = [f for f in [o.get("overlay"), o.get("illustration")] if f]
        if not files:
            continue
        # Only verified SAM segmentations (status ok) are auto-published as
        # step evidence. needs_tap/error/ambiguous visuals stay reviewable
        # in Visuals/diagnostics with their diagnostic frames — a bounding
        # box or low-confidence crop is never presented as a successful
        # segmentation.
        if o.get("status") != "ok":
            continue
        for s in steps or []:
            if str(o.get("obj_id")) in {str(x) for x in (s.get("objects_used") or [])}:
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
        # Step headings come in several shapes: "### 1. Title",
        # "### 1) Title", "### Step 1: Title", "### Step 1 of 4: Title".
        m_step = re.match(r"^###\s+(?:Step\s+)?(\d+)(?:\s+of\s+\d+)?[\.\)\:]", line, re.I)
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


def inject_ai_illustrations(md: str, ai_files: dict[int, str]) -> str:
    """Append AI-generated explanatory illustrations, clearly labelled.

    Idempotent: previous ai-illustration blocks are stripped first. Each
    image is captioned as AI-generated (not a photo, not a SAM mask) with
    a verify-against-equipment note. Never invents safety-critical detail.
    """
    md = re.sub(r"\n?<!-- ai-illustrations:\d+:start -->.*?<!-- ai-illustrations:\d+:end -->\n?",
                "\n", md or "", flags=re.S)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    if not ai_files:
        return md.strip() + "\n"
    out_lines: list[str] = []
    buf: list[str] = []
    cur: int | None = None

    def flush() -> None:
        nonlocal buf, cur
        out_lines.extend(buf)
        buf = []
        if cur in ai_files:
            out_lines.append(f"<!-- ai-illustrations:{cur}:start -->")
            out_lines.append(
                f"![AI-generated explanatory illustration for step {cur} "
                f"(not a photo of your equipment — verify against the real part)](illustrations/{ai_files[cur]})")
            out_lines.append(f"_AI-generated visual aid — verify against the real equipment._")
            out_lines.append(f"<!-- ai-illustrations:{cur}:end -->")
            out_lines.append("")
        cur = None

    for line in (md.strip() + "\n").split("\n"):
        m_step = re.match(r"^###\s+(?:Step\s+)?(\d+)(?:\s+of\s+\d+)?[\.\)\:]", line, re.I)
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
    candidates = [prompt_override] if prompt_override is not None else prompt_variants(obj["label"], obj.get("alternative_names"))
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
    out["ambiguous_match"] = False
    if not best:
        # One bounded hi-res retry before giving up: small objects are the
        # most common miss at 512px tracking resolution. Earlier attempts are
        # kept so the timeline shows the full trail.
        hired, hired_attempt = _hirez_retry(job_dir, source, obj, prompt_used, prior_attempts=tried)
        tried.append(hired_attempt)
        out["attempts"] = tried
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
    out["ambiguous_match"] = bool(ambiguous)
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
        "## Safety only if the transcript supports it, ## Steps with one ### per step shaped EXACTLY like "
        "`### 1. Do the thing (0:45-1:10)` (number, period, title, time range — no other heading shape), "
        "and 2-4 imperative sentences starting with a verb, each step ending with an 'Expected:' verification line where supported, "
        "## If something goes wrong only if supported. Never invent tools, values, warnings, or steps."
    ),
    "reference_manual": (
        "Structure: # title plus scope, ## Equipment (only if identifiable from input, else omit), "
        "## Prerequisites, ## Tools and materials (only items named in the input), ## Safety (only transcript-supported notes), "
        "## Procedure overview (2-3 sentences), ## Numbered procedure (same ### per step shaped EXACTLY like "
        "`### 1. Do the thing (0:45-1:10)`), "
        "## Expected outcomes (only supported checkpoints), ## Troubleshooting (only supported), "
        "## Sources (transcript ranges and objects used). Never invent torque, ratings, measurements, model identities, "
        "or specifications; omit unsupported sections entirely."
    ),
    "interactive": (
        "Structure: # title, one-line objective, ## Before you start (prerequisites + tools only if in input), "
        "## Steps with one ### per step shaped EXACTLY like `### 1. Do the thing (0:45-1:10)` "
        "including its time range, each step exactly: one imperative instruction paragraph, "
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
                 prior_attempts: list[dict] | None = None) -> tuple[dict | None, dict]:
    """One bounded re-run on a higher-res tracking copy for failed objects.

    Prior low-res attempts are preserved (appended, never replaced) so the
    processing timeline shows the full diagnostic trail. Returns
    (result_or_None, attempt_record) — the record is always populated so
    callers can show whether hi-res was tried and what it saw.
    """
    attempt: dict = {"prompt": prompt + " (hi-res retry)", "status": "not_run",
                     "frames": 0, "simulated": False}
    try:
        hired = job_dir / "tracking-hirez.mp4"
        if not hired.exists():
            make_tracking_copy(source, hired, max_width=HIREZ_MAX_WIDTH)
        file_id = ai.upload_video_file(hired.read_bytes(), "tracking-hirez.mp4")
        try:
            result = ai.segment_video_clip(file_id, prompt)
        finally:
            ai.delete_video_file(file_id)
        attempt["status"] = result.get("status")
        attempt["frames"] = len(result.get("frames", []))
        attempt["simulated"] = bool(result.get("simulated"))
        if result.get("simulated") or not result.get("frames"):
            return None, attempt
        best, distinct, margin = _best_track(result.get("frames", []))
        if not best:
            return None, attempt
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
        out["ambiguous_match"] = bool(ambiguous)
        if (conf is not None and conf < REVIEW_CONF) or ambiguous:
            out["status"] = "needs_tap"
            out["note"] = "Matched at higher resolution but still uncertain — tap to confirm."
        else:
            out["status"] = "ok"
        return out, attempt
    except Exception as e:
        attempt["status"] = f"failed: {type(e).__name__}"
        return None, attempt


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
    """JSON-stable canonical step identity (order, title, instruction, plus
    reviewer-visible fields so expert edits to expected results, tools, or
    verification notes participate in 3-way sync instead of being silently
    overwritten)."""
    return [{"n": int(s.get("step_number", 0)), "t": str(s.get("title", "")),
             "i": str(s.get("summary", "")),
             "e": str(s.get("expected_result", "") or ""),
             "v": str(s.get("verification_notes", "") or ""),
             "r": [str(t) for t in (s.get("required_tools", []) or [])]} for s in (steps or [])]


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
                try:
                    path = _storage.media_path(key)
                except ValueError:
                    continue
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
            expected_result=str(s.get("expected_result", "") or "") or None,
            required_tools=[str(t)[:120] for t in (s.get("required_tools", []) or []) if str(t).strip()][:20],
            evidence_refs=refs, visual_refs=visuals,
            start_sec=start_sec, end_sec=end_sec,
            verification_notes=str(s.get("verification_notes", "") or "") or "From tutorial narration; verify against source video.")
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
    # Backward compatibility: canonical snapshots written before expected
    # results/tools/verification joined the identity get empty defaults, so
    # the first post-upgrade sync compares like-for-like.
    for _c in stored_canon:
        _c.setdefault("e", "")
        _c.setdefault("v", "")
        _c.setdefault("r", [])
    stored_by_n = {c["n"]: c for c in stored_canon}
    new_by_n = {c["n"]: c for c in new_canon}
    draft_by_n = {s.step_order: {"n": s.step_order, "t": s.title or "", "i": s.instruction or "",
                                 "e": s.expected_result or "", "v": s.verification_notes or "",
                                 "r": list(s.required_tools or [])}
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
                st.expected_result = kept[st.step_order].get("e") or None
                st.verification_notes = kept[st.step_order].get("v") or st.verification_notes
                st.required_tools = list(kept[st.step_order].get("r") or [])
        for ex in expert_only:
            order = ex["n"] if ex["n"] not in used_orders else max(used_orders | {0}) + 1
            used_orders.add(order)
            db.add(M.ProcedureStep(procedure_version_id=ver.id, step_order=order,
                                   title=ex["t"], instruction=ex["i"],
                                   expected_result=ex.get("e") or None,
                                   required_tools=list(ex.get("r") or []),
                                   evidence_refs=[], visual_refs=[],
                                   verification_notes=ex.get("v") or "Added by expert review; not from tutorial narration."))
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


def _guide_source_note(job: M.TutorialJob) -> str:
    """Provenance note distinguishing visually-observed from narrated content."""
    if getattr(job, "analysis_strategy", "") == "visual_first":
        return ("Steps derive from visual observation of the recording (visual-first analysis); "
                "narration was absent or insufficient. Treat uncertainties as unresolved until reviewed.")
    return ""


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
        guide = ai.generate_guide(job.title, steps, objects, job.timed_segments or [], guide_format=fmt, source_note=_guide_source_note(job))
    md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, objects, fmt, _guide_source_note(job))
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
        content_revision=int(getattr(job, "content_revision", 1) or 1),
        object_statuses=[{"obj_id": o.get("obj_id"), "label": o.get("label"),
                          "status": o.get("status"), "confidence": o.get("confidence")}
                         for o in (objects or [])])
    db.add(snap)
    db.flush()
    return snap


def decide_analysis_strategy(input_mode: str, has_audio: bool, text: str,
                               segments: list, duration_sec: float) -> tuple[str, str]:
    """Choose narrated vs visual-first understanding. Returns (strategy, reason).

    Never fabricates: weak narration routes to visual analysis with the
    partial transcript kept as supplementary context.
    """
    if input_mode == "visual_first":
        return "visual_first", "visual-first mode requested by the user"
    if not has_audio:
        return "visual_first", "no audio track in the recording — analyzing visible actions instead"
    ok, detail = ai.assess_speech_sufficiency(text, segments or [], duration_sec)
    if ok:
        return "narrated", detail
    if input_mode == "narrated":
        return "narrated", "narrated mode requested; transcription is sparse (" + detail + ")"
    return "visual_first", detail


def sample_keyframes(job_dir: Path, source: Path, duration_sec: float,
                     max_frames: int = 8) -> list[dict]:
    """Sample up to max_frames JPEGs uniformly across the recording.

    Bounded and timestamped: each frame carries its source time so candidate
    steps stay aligned with the video. Uses local ffmpeg + Pillow only.
    """
    from PIL import Image as _Image
    import io as _io
    dur = max(float(duration_sec or 0), 1.0)
    n = max(2, min(int(max_frames), int(dur // 20) + 1, 8))
    out: list[dict] = []
    for i in range(n):
        t = round(min((i + 0.5) * dur / n, max(0.0, dur - 0.1)), 1)
        try:
            frame = extract_frame_image(source, t)
            frame.thumbnail((640, 640))
            name = f"keyframe-{i:02d}.jpg"
            frame.convert("RGB").save(job_dir / name, "JPEG", quality=70)
            with open(job_dir / name, "rb") as fh:
                raw = fh.read()
            out.append({"t": t, "name": name, "image": raw})
        except Exception:
            continue
    return out


def _normalize_label(label: str) -> str:
    """Canonical key for dedup: lowercase, collapse whitespace, strip."""
    import re as _re
    return _re.sub(r"\s+", " ", (label or "").strip().lower())


def _merge_object_inventories(transcript_objs: list[dict], visual_objs: list[dict],
                              transcript_steps: list[dict], visual_steps: list[dict],
                              duration_sec: float) -> tuple[list[dict], list[dict], list[str]]:
    """Unified multimodal inventory: transcript ∪ visual, deduplicated.

    Two labels merge only when normalized labels match exactly — visually
    similar but distinct instances (e.g. 'left chocolate pile' vs 'right
    chocolate pile') stay separate. Merged objects keep the transcript
    label, union alternative_names, earliest timestamp, union steps, and
    discovery_source transcript|visual|both. Stable sequential obj_ids.
    Returns (objects, steps, notes).
    """
    notes: list[str] = []
    # Index transcript by normalized label.
    t_by_norm: dict[str, dict] = {}
    for o in transcript_objs or []:
        n = _normalize_label(o.get("label", ""))
        if n and n not in t_by_norm:
            t_by_norm[n] = dict(o)
    merged: list[dict] = [dict(o) for o in transcript_objs or []]
    # Map label->obj for step remapping (rebuilt after merge).
    for v in visual_objs or []:
        lab = str(v.get("label") or "").strip()[:80]
        if not lab:
            continue
        n = _normalize_label(lab)
        if n in t_by_norm:
            ex = t_by_norm[n]
            # Union synonyms + properties.
            alt = list(dict.fromkeys(
                [*(ex.get("alternative_names") or []), *(v.get("alternative_names") or []), lab]
            ))[:5]
            # Drop the canonical label itself from synonyms.
            alt = [a for a in alt if _normalize_label(a) != _normalize_label(ex.get("label", ""))][:4]
            ex["alternative_names"] = alt
            if v.get("first_mentioned_at") is not None:
                try:
                    ex["first_mentioned_at"] = round(min(float(ex.get("first_mentioned_at", 1e9)),
                                                         float(v.get("first_mentioned_at", 1e9))), 1)
                except (TypeError, ValueError):
                    pass
            # Union evidence frames.
            ef = list(dict.fromkeys([*(ex.get("evidence_frames") or []), *(v.get("evidence_frames") or [])]))[:8]
            if ef:
                ex["evidence_frames"] = ef
            if ex.get("discovery_source") != "both":
                ex["discovery_source"] = "both" if ex.get("discovery_source") == "transcript" else (ex.get("discovery_source") or "visual")
            if not ex.get("properties") and v.get("properties"):
                ex["properties"] = str(v.get("properties"))[:200]
        else:
            oo = dict(v)
            oo["discovery_source"] = "visual"
            oo.setdefault("alternative_names", [])
            merged.append(oo)
            t_by_norm[n] = oo
            notes.append(f"visual-only object kept: {lab}")
    # Stable ids by earliest appearance.
    try:
        merged.sort(key=lambda o: float(o.get("first_mentioned_at", 0)))
    except (TypeError, ValueError):
        pass
    old_to_new: dict[int, int] = {}
    # Build mapping from old ids (both lists) — transcript ids shift, visual
    # ids remapped by label.
    # Simplest deterministic approach: reassign 1..N, remap steps by label.
    label_to_new = {_normalize_label(o.get("label", "")): i + 1 for i, o in enumerate(merged)}
    for i, o in enumerate(merged, start=1):
        o["obj_id"] = i
    # Remap steps: combine both step lists, remap objects_used via labels.
    # Transcript steps reference old transcript ids; visual steps reference
    # old visual ids. Rebuild via label lookup.
    t_labels = {_normalize_label(o.get("label", "")): o.get("label", "") for o in transcript_objs or []}
    # Actually simpler: keep transcript steps as primary timeline, append
    # visual-only steps that don't overlap? For now concatenate with
    # renumbering and remap via normalized labels of each source.
    new_steps: list[dict] = []
    def _remap(step_list, source_objs):
        id_to_norm = {}
        for o in source_objs or []:
            try:
                id_to_norm[int(o.get("obj_id", 0))] = _normalize_label(o.get("label", ""))
            except (TypeError, ValueError):
                pass
        out = []
        for s in step_list or []:
            used = []
            for x in (s.get("objects_used") or []):
                try:
                    norm = id_to_norm.get(int(x))
                except (TypeError, ValueError):
                    norm = None
                if norm and norm in label_to_new:
                    used.append(label_to_new[norm])
            # Also map by direct label match for visual steps (already ids).
            ns = dict(s)
            ns["objects_used"] = sorted(set(used))
            out.append(ns)
        return out
    # Note: after merge, source obj_ids changed; use pre-merge copies.
    new_steps.extend(_remap(transcript_steps, transcript_objs))
    # Append visual steps only when transcript has none (avoid duplicating
    # the timeline); otherwise fold visual evidence into matching steps.
    if not transcript_steps and visual_steps:
        new_steps.extend(_remap(visual_steps, visual_objs))
    elif visual_steps and transcript_steps:
        notes.append(f"{len(visual_steps)} visual candidate steps folded as evidence (transcript timeline kept)")
    for j, s in enumerate(new_steps, start=1):
        s["step_number"] = j
    # Cap with transparent reporting.
    import os as _os
    cap = int(_os.getenv("TRACELOOP_MAX_OBJECTS", "32"))
    dropped: list[str] = []
    if len(merged) > cap:
        dropped.append(f"{len(merged) - cap} objects beyond cap {cap} deferred")
        merged = sorted(merged, key=lambda o: float(o.get("first_mentioned_at", 0) or 0))[:cap]
        for i, o in enumerate(merged, start=1):
            o["obj_id"] = i
    return merged, new_steps, notes + dropped


def _visual_objects_and_steps(analysis: dict, duration_sec: float) -> tuple[list[dict], list[dict]]:
    """Map visual analysis output onto the canonical step/object schema.

    Labels become tracked objects (first appearance = earliest evidence
    frame or step start); candidate steps become canonical steps carrying
    evidence_frames + confidence + derivation so reviewers can tell visual
    observation apart from narration and human edits.
    """
    raw_steps = analysis.get("candidate_steps") or []
    label_first: dict[str, float] = {}
    for s in raw_steps:
        if not isinstance(s, dict):
            continue
        ev = s.get("evidence_frames") or []
        try:
            t0 = min([float(x) for x in ev])
        except (TypeError, ValueError):
            try:
                t0 = float(s.get("start_sec", 0) or 0)
            except (TypeError, ValueError):
                t0 = 0.0
        for lab in (s.get("objects") or []):
            lab = str(lab).strip()[:80]
            if lab and (lab not in label_first or t0 < label_first[lab]):
                label_first[lab] = round(t0, 1)
    labels = sorted(label_first, key=lambda l: label_first[l])
    obj_ids = {lab: i + 1 for i, lab in enumerate(labels)}
    objects = [{"label": lab, "first_mentioned_at": label_first[lab], "obj_id": obj_ids[lab],
                "status": "pending", "confidence": None, "illustration": "", "overlay": "", "track": [],
                "alternative_names": [], "properties": "", "discovery_source": "visual"}
               for lab in labels]
    steps = []
    for j, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            continue
        used = sorted({obj_ids[str(lab).strip()[:80]] for lab in (s.get("objects") or [])
                       if str(lab).strip()[:80] in obj_ids})
        steps.append({
            "step_number": j + 1,
            "title": str(s.get("title", "") or f"Step {j + 1}"),
            "summary": str(s.get("instruction", "") or ""),
            "start": float(s.get("start_sec", 0) or 0),
            "end": float(s.get("end_sec", 0) or 0),
            "objects_used": used,
            "expected_result": "",
            "verification_notes": "; ".join(str(u) for u in (s.get("uncertainties") or []) if str(u).strip())[:2000],
            "required_tools": [],
            "evidence_frames": [float(x) for x in (s.get("evidence_frames") or [])][:8],
            "confidence": s.get("confidence", "low"),
            "derivation": "visual",
        })
    return objects, steps


def run_job(job_id: str) -> None:
    from . import processing as proc
    db = SessionLocal()
    proc.new_correlation()
    try:
        job = db.get(M.TutorialJob, job_id)
        if job is None:
            return
        actor = job.actor or ""
        job_dir = _storage.media_root() / "tutorials" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        try:
            source = _storage.media_path(job.video_storage_key or "")
        except ValueError:
            raise RuntimeError("The uploaded video file is missing or has an invalid storage reference")
        try:
            with proc.timed() as t:
                info = probe_video(source)
            proc.safe_record(db, "tutorial", job_id, "probe", "succeeded", operation="probe_video",
                             duration_ms=t.ms, actor=actor,
                             summary={"duration_sec": info["duration"], "width": info["width"], "height": info["height"]})
            if info["duration"] <= 0:
                raise RuntimeError("Could not read the uploaded video (unsupported format?)")
            # NOTE: no maximum duration — long tutorials are accepted as-is.
            # NOTE: no-audio is handled below per input_mode (narrated fails
            # fast; auto/visual_first continue with visual analysis).
            _set(db, job, duration_sec=info["duration"], width=info["width"], height=info["height"], progress=8)
            input_mode = getattr(job, "input_mode", "auto") or "auto"
            if input_mode not in ("auto", "narrated", "visual_first"):
                input_mode = "auto"
            has_audio = bool(info.get("has_audio", True))

            def _best_effort_transcript() -> dict:
                """Transcribe without failing: partial speech stays available
                as supplementary context for visual-first analysis."""
                try:
                    _wav = job_dir / "audio.wav"
                    extract_audio_wav(source, _wav)
                    out = ai.transcribe_timed("audio.wav", _wav.read_bytes(), duration_sec=info["duration"])
                    out.pop("error", None)
                    return out
                except Exception as ee:
                    return {"text": "", "segments": [], "simulated": False,
                            "note": f"Transcription unavailable ({type(ee).__name__}); continuing visually."}

            tr: dict = {"text": "", "segments": [], "simulated": False, "model": ""}
            strategy, reason = "narrated", ""
            if input_mode == "visual_first":
                strategy, reason = "visual_first", "visual-first mode requested by the user"
                if has_audio:
                    _set(db, job, status="transcribing", progress=12)
                    tr = _best_effort_transcript()
                    proc.safe_record(
                        db, "tutorial", job_id, "transcribe",
                        "simulated" if tr.get("simulated") else ("succeeded" if (tr.get("text") or "").strip() else "skipped"),
                        operation="transcribe_timed", provider="meta", model=tr.get("model", ""), duration_ms=0, actor=actor,
                        summary={"audio_sec": info["duration"], "text_chars": len(tr.get("text") or ""),
                                 "segments": len(tr.get("segments") or []), "note": tr.get("note", "")})
                    _set(db, job, full_transcript=tr["text"], timed_segments=tr["segments"])
                else:
                    proc.safe_record(db, "tutorial", job_id, "extract_audio", "skipped",
                                     operation="extract_audio_wav", duration_ms=0, actor=actor,
                                     summary={"has_audio": False,
                                              "note": "visual-first mode: narration optional, skipping audio extraction"})
                    _set(db, job, full_transcript="", timed_segments=[])
            elif not has_audio:
                if input_mode == "narrated":
                    # Fail fast with an actionable message: retrying a silent video
                    # can never succeed, and transcribing silence is not an option.
                    proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                     operation="extract_audio_wav", duration_ms=0, actor=actor,
                                     summary={"has_audio": False,
                                              "note": "probe found no audio stream; failing before transcription"})
                    raise NoAudioTrackError(
                        "This video has no audio track, so there is nothing to transcribe. "
                        "Record again with the microphone on and narrate each step as you show it, "
                        "or switch to Visual-First mode to analyze the actions shown.")
                strategy, reason = "visual_first", "no audio track in the recording — analyzing visible actions instead"
                proc.safe_record(db, "tutorial", job_id, "extract_audio", "skipped",
                                 operation="extract_audio_wav", duration_ms=0, actor=actor,
                                 summary={"has_audio": False, "fallback": "visual_first",
                                          "note": "probe found no audio stream; continuing visually"})
                _set(db, job, full_transcript="", timed_segments=[])
            else:
                _set(db, job, status="transcribing", progress=12)
                wav = job_dir / "audio.wav"
                try:
                    extract_audio_wav(source, wav)
                except NoAudioTrackError:
                    if input_mode == "auto":
                        strategy, reason = "visual_first", "audio track unreadable — analyzing visible actions instead"
                        tr = {"text": "", "segments": [], "simulated": False, "model": "",
                              "note": "extract_audio_wav found no audio; visual-first fallback"}
                        proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                         operation="extract_audio_wav", duration_ms=0, actor=actor,
                                         summary={"has_audio": False, "fallback": "visual_first"})
                        _set(db, job, full_transcript="", timed_segments=[])
                    else:
                        proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                         operation="extract_audio_wav", duration_ms=0, actor=actor,
                                         summary={"has_audio": False})
                        raise
                except RuntimeError as ee:
                    proc.safe_record(db, "tutorial", job_id, "extract_audio", "failed",
                                     operation="extract_audio_wav", duration_ms=0, actor=actor,
                                     summary={"error_type": "RuntimeError", "ffmpeg": str(ee)[-300:]})
                    raise
                if not strategy or strategy == "narrated":
                    with proc.timed() as t:
                        tr = ai.transcribe_timed("audio.wav", wav.read_bytes(), duration_sec=info["duration"])
                    proc.safe_record(
                        db, "tutorial", job_id, "transcribe", "failed" if tr.get("error") else ("simulated" if tr.get("simulated") else "succeeded"),
                        operation="transcribe_timed", provider="meta", model=tr.get("model", ""), duration_ms=t.ms, actor=actor,
                        summary={"audio_sec": info["duration"], "text_chars": len(tr.get("text") or ""),
                                 "segments": len(tr.get("segments") or []), "error": tr.get("error", ""),
                                 "note": tr.get("note", "")})
                    if tr.get("error"):
                        if input_mode == "narrated" or not tr.get("fallback_visual"):
                            raise RuntimeError(tr["error"])
                        # Deterministic provider rejection in auto mode (bad audio,
                        # over limits): the narration path is a dead end, but the
                        # video itself is still analyzable. Fall back instead of
                        # failing, and say so.
                        strategy = "visual_first"
                        reason = (tr.get("error", "") + " Continuing with visual analysis; " +
                                  "no transcript will be available.").strip()
                        _set(db, job, full_transcript="", timed_segments=[])
                    if strategy != "visual_first":
                        sufficient, detail = ai.assess_speech_sufficiency(
                            tr.get("text") or "", tr.get("segments") or [], info["duration"])
                        if sufficient:
                            strategy, reason = "narrated", detail
                            _set(db, job, full_transcript=tr["text"], timed_segments=tr["segments"], progress=30)
                        elif input_mode == "auto":
                            strategy, reason = "visual_first", detail + " — analyzing visible actions instead; transcript kept as supplementary context"
                            _set(db, job, full_transcript=tr["text"], timed_segments=tr["segments"], progress=30)
                        else:
                            raise RuntimeError("No speech was transcribed. Check the microphone track and try again, or switch to Visual-First mode.")

            _set(db, job, analysis_strategy=strategy, strategy_reason=reason)
            _set(db, job, status="understanding", progress=38)
            objects: list = []
            steps: list = []
            if strategy == "visual_first":
                frames = sample_keyframes(job_dir, source, info["duration"])
                _set(db, job, keyframes=[{"t": f["t"], "name": f["name"]} for f in frames])
                proc.safe_record(db, "tutorial", job_id, "understand", "succeeded",
                                 operation="sample_keyframes", provider="", model="",
                                 duration_ms=0, actor=actor,
                                 summary={"frames": len(frames),
                                          "timestamps": [f["t"] for f in frames]})
                with proc.timed() as t:
                    analysis = ai.analyze_tutorial_frames(
                        [{"t": f["t"], "image": f["image"]} for f in frames],
                        (tr.get("text") or "")[:2000], info["duration"])
                objects, steps = _visual_objects_and_steps(analysis, duration_sec=info["duration"])
                proc.safe_record(
                    db, "tutorial", job_id, "understand",
                    "simulated" if analysis.get("simulated") else "succeeded",
                    operation="analyze_frames", provider="meta", model=analysis.get("model", ""),
                    duration_ms=t.ms, actor=actor,
                    summary={"analysis_mode": analysis.get("analysis_mode", "visual_first"),
                             "frames": len(frames), "observations": len(analysis.get("observations") or []),
                             "steps": len(steps), "objects": len(objects),
                             "missing_information": analysis.get("missing_information") or [],
                             "dropped": analysis.get("dropped") or [],
                             "note": analysis.get("note", "")})
                # Multimodal merge: transcript mentions supplement visual
                # discovery so spoken-but-briefly-visible tools are not lost.
                if (tr.get("segments") or tr.get("text")):
                    try:
                        with proc.timed() as t2:
                            und2 = ai.understand_tutorial(tr.get("segments") or [], info["duration"])
                        t_objs, t_steps = und2.get("objects", []), und2.get("steps", [])
                        if t_objs:
                            merged, m_steps, m_notes = _merge_object_inventories(
                                t_objs, objects, t_steps, steps, info["duration"])
                            proc.safe_record(
                                db, "tutorial", job_id, "understand",
                                "simulated" if und2.get("simulated") else "succeeded",
                                operation="understand_tutorial_supplement", provider="meta",
                                model=und2.get("model", ""), duration_ms=t2.ms, actor=actor,
                                summary={"transcript_objects": len(t_objs),
                                         "merged_objects": len(merged), "notes": m_notes,
                                         "dropped": und2.get("dropped") or []})
                            objects, steps = merged, m_steps or steps
                    except Exception as me:
                        proc.safe_record(db, "tutorial", job_id, "understand", "skipped",
                                         operation="understand_tutorial_supplement", duration_ms=0, actor=actor,
                                         summary={"note": f"transcript supplement skipped ({type(me).__name__})"})
                _set(db, job, objects=objects, steps=steps, progress=45)
            else:
                with proc.timed() as t:
                    und = ai.understand_tutorial(tr["segments"], info["duration"])
                objects, steps = und.get("objects", []), und.get("steps", [])
                proc.safe_record(
                    db, "tutorial", job_id, "understand", "simulated" if und.get("simulated") else "succeeded",
                    operation="understand_tutorial", provider="meta", model=und.get("model", ""), duration_ms=t.ms, actor=actor,
                    summary={"objects": len(objects), "steps": len(steps),
                             "labels": [o.get("label") for o in objects],
                             "first_mentioned_at": [o.get("first_mentioned_at") for o in objects],
                             "note": und.get("note", ""), "dropped": und.get("dropped") or []})
                # Multimodal merge: visual supplement catches task-relevant
                # objects the speaker never mentions (bounded ≤8 frames).
                try:
                    v_frames = sample_keyframes(job_dir, source, info["duration"])
                    if v_frames:
                        with proc.timed() as tv:
                            v_analysis = ai.analyze_tutorial_frames(
                                [{"t": f["t"], "image": f["image"]} for f in v_frames],
                                (tr.get("text") or "")[:2000], info["duration"])
                        v_objs, v_steps = _visual_objects_and_steps(v_analysis, duration_sec=info["duration"])
                        if v_objs:
                            merged_objs, _, m_notes = _merge_object_inventories(
                                objects, v_objs, steps, [], info["duration"])
                            proc.safe_record(
                                db, "tutorial", job_id, "understand",
                                "simulated" if v_analysis.get("simulated") else "succeeded",
                                operation="analyze_frames_supplement", provider="meta",
                                model=v_analysis.get("model", ""), duration_ms=tv.ms, actor=actor,
                                summary={"visual_objects": len(v_objs), "merged_objects": len(merged_objs),
                                         "notes": m_notes, "dropped": v_analysis.get("dropped") or []})
                            # Transcript timeline stays authoritative; adopt the
                            # merged object inventory for SAM tracking.
                            objects = merged_objs
                except Exception as ve:
                    proc.safe_record(db, "tutorial", job_id, "understand", "skipped",
                                     operation="analyze_frames_supplement", duration_ms=0, actor=actor,
                                     summary={"note": f"visual supplement skipped ({type(ve).__name__})"})
                _set(db, job, objects=objects, steps=steps, progress=45)
            if not objects:
                _set(db, job, status="generating", progress=90)
                fmt, fsrc, why = _format_for_job(job)
                _set(db, job, guide_format=fmt, format_source=fsrc, format_rationale=why)
                with proc.timed() as t:
                    guide = ai.generate_guide(job.title, steps, objects, tr["segments"], guide_format=fmt, source_note=_guide_source_note(job))
                md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, objects, fmt, _guide_source_note(job))
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
                                     "quality": (seg.get("quality") or {}).get("issues", []),
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
                guide = ai.generate_guide(job.title, steps, done_objects, tr["segments"], guide_format=fmt, source_note=_guide_source_note(job))
            md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, done_objects, fmt, _guide_source_note(job))
            md = inject_illustrations(md, steps, done_objects)
            # Muse Image fallback for steps still lacking verified visuals.
            # Clearly labelled AI-generated aids; never photos or SAM masks.
            ai_prov: list[dict] = []
            try:
                ai_files, ai_prov = ensure_ai_step_illustrations(job_dir, steps, done_objects)
                if ai_files:
                    md = inject_ai_illustrations(md, ai_files)
            except Exception as ae:
                ai_prov = [{"status": "error", "note": f"AI illustration fallback skipped ({type(ae).__name__})"}]
            proc.safe_record(db, "tutorial", job_id, "guide", "simulated" if guide.get("simulated") else "succeeded",
                             operation="generate_guide", provider="meta", model=guide.get("model", ""),
                             duration_ms=t.ms, actor=actor,
                             summary={"format": fmt, "format_source": fsrc,
                                      "markdown_chars": len(md), "materials": len(guide.get("materials", [])),
                                      "ok_objects": sum(1 for o in done_objects if o.get("status") == "ok"),
                                      "needs_tap": sum(1 for o in done_objects if o.get("status") == "needs_tap"),
                                      "ai_illustrations": ai_prov,
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
        job_dir = _storage.media_root() / "tutorials" / job_id
        try:
            source = _storage.media_path(job.video_storage_key or "")
        except ValueError:
            raise ValueError("The uploaded video file is missing or has an invalid storage reference")
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
