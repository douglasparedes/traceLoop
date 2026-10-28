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
    if result.get("simulated"):
        out.update({"status": "error", "confidence": None, "note": result.get("note", "SAM unavailable")})
        return out
    best, distinct, margin = _best_track(result.get("frames", []))
    if best:
        out["track"] = [{"frame": f.get("frame", 0), "objects": [
            {"object_id": o.get("object_id"), "bbox_norm": o.get("bbox_norm"), "confidence": o.get("confidence")}
            for o in (f.get("objects") or [])]} for f in result.get("frames", [])]
    if not best:
        # One bounded hi-res retry before giving up: small objects are the
        # most common miss at 512px tracking resolution.
        hired = _hirez_retry(job_dir, source, obj, prompt_used)
        if hired is not None:
            return hired
        out.update({"status": "needs_tap", "confidence": None,
                    "note": f"SAM found no match for “{obj['label']}” (tried: {', '.join('“' + t['prompt'] + '”' for t in tried)}). Tap the object in the guide to correct it."})
        return out
    conf = best.get("confidence")
    out["confidence"] = conf
    out["best_frame"] = best["frame"]
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


def _hirez_retry(job_dir: Path, source: Path, obj: dict, prompt: str) -> dict | None:
    """One bounded re-run on a higher-res tracking copy for failed objects."""
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
               "attempts": [{"prompt": prompt + " (hi-res retry)", "status": result.get("status"),
                             "frames": len(result.get("frames", [])), "simulated": False}],
               "track": [{"frame": f.get("frame", 0), "objects": [
                   {"object_id": o.get("object_id"), "bbox_norm": o.get("bbox_norm"), "confidence": o.get("confidence")}
                   for o in (f.get("objects") or [])]} for f in result.get("frames", [])]}
        conf = best.get("confidence")
        out["confidence"] = conf
        out["best_frame"] = best["frame"]
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


def run_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, job_id)
        if job is None:
            return
        job_dir = BASE / "data" / "tutorials" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source = BASE / job.video_storage_key
        try:
            info = probe_video(source)
            if info["duration"] <= 0:
                raise RuntimeError("Could not read the uploaded video (unsupported format?)")
            if info["duration"] > MAX_VIDEO_SEC + 5:
                raise RuntimeError(f"Video is {info['duration']:.0f}s — tutorials are limited to {MAX_VIDEO_SEC}s (10 minutes)")
            _set(db, job, duration_sec=info["duration"], width=info["width"], height=info["height"], progress=8)

            _set(db, job, status="transcribing", progress=12)
            wav = job_dir / "audio.wav"
            extract_audio_wav(source, wav)
            tr = ai.transcribe_timed("audio.wav", wav.read_bytes(), duration_sec=info["duration"])
            if tr.get("error"):
                raise RuntimeError(tr["error"])
            if not (tr.get("text") or "").strip():
                raise RuntimeError("No speech was transcribed. Check the microphone track and try again.")
            _set(db, job, full_transcript=tr["text"], timed_segments=tr["segments"], progress=30)

            _set(db, job, status="understanding", progress=38)
            und = ai.understand_tutorial(tr["segments"], info["duration"])
            objects, steps = und.get("objects", []), und.get("steps", [])
            _set(db, job, objects=objects, steps=steps, progress=45)
            if not objects:
                _set(db, job, status="generating", progress=90)
                guide = ai.generate_guide(job.title, steps, objects, tr["segments"])
                md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, objects)
                md = inject_illustrations(md, steps, objects)
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
                    done_objects.append(_segment_object(job_dir, source, tracking, file_id, obj))
                    _set(db, job, objects=done_objects + objects[i + 1:], progress=50 + int(30 * (i + 1) / len(objects)))
            finally:
                ai.delete_video_file(file_id)

            _set(db, job, status="generating", progress=88, objects=done_objects)
            guide = ai.generate_guide(job.title, steps, done_objects, tr["segments"])
            md = guide.get("guide_markdown") or ai.fallback_guide_markdown(job.title, steps, done_objects)
            md = inject_illustrations(md, steps, done_objects)
            _set(db, job, guide_markdown=md, materials=guide.get("materials", [o["label"] for o in done_objects]),
                 status="done", progress=100)
        except Exception as e:
            _set(db, job, status="error", error=f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        db.close()


def start_job(job_id: str) -> None:
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


def resegment_object_tap(job_id: str, obj_id: int, nx: float, ny: float) -> dict:
    """Re-track one object from a user tap (normalized coords on a video frame)."""
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
            updated = _segment_object(job_dir, source, tracking, file_id, obj, prompt_override=prompt)
        finally:
            ai.delete_video_file(file_id)
        if updated.get("status") == "needs_tap" and updated.get("illustration"):
            updated["status"] = "ok"  # user-confirmed tap is ground truth for this demo
            updated["note"] = "Corrected from your tap."
        objects = [updated if int(o.get("obj_id", 0)) == obj_id else o for o in objects]
        _set(db, job, objects=objects)
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
