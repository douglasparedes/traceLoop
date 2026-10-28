"""Live (near-live) SAM video sessions — Option A: clip chunking.

Meta SAM 3.1 on the Model API segments whole clips, not stateful frame
streams. A live session therefore collects short frame chunks client-side;
this module assembles each chunk to MP4 (bundled ffmpeg), uploads it to
the Meta Files API, runs one SAM video segmentation, and chains tracking
across chunks by re-prompting the next chunk with the last tracked bbox.

Sessions are in-memory (single-process demo), token-guarded, TTL-bound,
and chunk-capped for cost control. No API key ever leaves the server.
"""
import io
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image

from . import ai

SESSION_TTL_SECONDS = 600
MAX_CHUNKS_PER_SESSION = 75
MAX_FRAMES_PER_CHUNK = 90
MAX_FRAME_BYTES = 1024 * 1024

_lock = threading.Lock()
_sessions: dict[str, dict] = {}


def _cleanup(now: float) -> None:
    expired = [sid for sid, s in _sessions.items() if now - s["last_seen"] > SESSION_TTL_SECONDS]
    for sid in expired:
        del _sessions[sid]


def create_session(actor: str, recording_id: str = "") -> dict:
    now = time.time()
    with _lock:
        _cleanup(now)
        sid = secrets.token_urlsafe(16)
        token = secrets.token_urlsafe(32)
        _sessions[sid] = {
            "actor": actor, "token": token, "created": now, "last_seen": now,
            "chunks": 0, "last_bbox_px": None, "image_size": None, "recording_id": recording_id,
        }
    return {"session_id": sid, "token": token, "expires_in": SESSION_TTL_SECONDS,
            "model": ai.SAM_MODEL, "simulated": not ai.live_enabled(), "recording_id": recording_id}


def get_session(session_id: str, token: str) -> dict | None:
    now = time.time()
    with _lock:
        _cleanup(now)
        s = _sessions.get(session_id)
        if not s or not token or not secrets.compare_digest(s["token"], token):
            return None
        s["last_seen"] = now
        return s


def end_session(session_id: str, token: str) -> bool:
    with _lock:
        s = _sessions.get(session_id)
        if not s or not token or not secrets.compare_digest(s["token"], token):
            return False
        del _sessions[session_id]
        return True


def validate_frames(frames: list[bytes]) -> tuple[int, int]:
    """Decode-check every frame with Pillow. Returns (width, height) of frame 0."""
    if not frames:
        raise ValueError("No frames supplied")
    if len(frames) > MAX_FRAMES_PER_CHUNK:
        raise ValueError(f"Too many frames in chunk (max {MAX_FRAMES_PER_CHUNK})")
    size: tuple[int, int] | None = None
    for f in frames:
        if len(f) > MAX_FRAME_BYTES:
            raise ValueError("Frame too large (max 1 MB per frame)")
        try:
            with Image.open(io.BytesIO(f)) as im:
                im.verify()
            with Image.open(io.BytesIO(f)) as im:
                if im.format not in ("JPEG", "PNG"):
                    raise ValueError("Frames must be JPEG or PNG")
                if size is None:
                    size = im.size
                elif im.size != size:
                    raise ValueError("All frames in a chunk must share dimensions")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Undecodable frame image ({type(e).__name__})") from e
    assert size is not None
    return size


def assemble_mp4(frames: list[bytes], fps: float) -> bytes:
    """Assemble JPEG/PNG frames into an H.264 MP4 (faststart) via bundled ffmpeg."""
    import imageio_ffmpeg

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i, f in enumerate(frames):
            (td / f"frame_{i:04d}.jpg").write_bytes(f if f[:2] == b"\xff\xd8" else _to_jpeg(f))
        out = td / "chunk.mp4"
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [exe, "-y", "-framerate", str(fps), "-i", str(td / "frame_%04d.jpg"),
             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-r", str(fps), str(out)],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError("ffmpeg failed to assemble clip")
        return out.read_bytes()


def _to_jpeg(data: bytes) -> bytes:
    buf = io.BytesIO()
    with Image.open(io.BytesIO(data)) as im:
        im.convert("RGB").save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def mux_audio(video_mp4: bytes, audio_bytes: bytes, audio_suffix: str = ".webm") -> bytes:
    """Mux a chunk audio track (AAC) into the silent frames MP4. Silent on failure."""
    import imageio_ffmpeg

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        vin, ain, out = td / "v.mp4", td / f"a{audio_suffix}", td / "out.mp4"
        vin.write_bytes(video_mp4); ain.write_bytes(audio_bytes)
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [exe, "-y", "-i", str(vin), "-i", str(ain), "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out)],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0 or not out.exists():
            return video_mp4
        return out.read_bytes()


def process_chunk(session: dict, frames: list[bytes], fps: float, prompt_text: str,
                  prompt_point: tuple[int, int] | None, reset: bool, db=None,
                  audio_bytes: bytes | None = None, audio_suffix: str = ".webm",
                  start_ms: int = 0, end_ms: int = 0, prompt_source: str = "", speech_phrase: str = "") -> dict:
    """Validate -> assemble -> persist -> upload -> segment -> chain."""
    from . import models as M

    w, h = validate_frames(frames)
    if session["chunks"] >= MAX_CHUNKS_PER_SESSION:
        raise PermissionError(f"Session chunk limit reached ({MAX_CHUNKS_PER_SESSION}). Start a new live session.")
    if reset:
        session["last_bbox_px"] = None

    # Prompt selection: explicit point > chained bbox > concept phrase (never mixed).
    if prompt_point is not None:
        px, py = prompt_point
        if not (0 <= px < w and 0 <= py < h):
            raise ValueError("Tap point lies outside the frame")
        prompt = ai.build_point_prompt(px, py, w, h)
        prompt_kind = "point"
    elif session.get("last_bbox_px") and session.get("image_size") == [w, h]:
        prompt = ai.build_box_prompt(session["last_bbox_px"], w, h)
        prompt_kind = "chained-box"
    elif prompt_text.strip():
        prompt = prompt_text.strip()
        prompt_kind = "concept"
    else:
        raise ValueError("A prompt is required: type a concept or tap the object on the preview")

    # Assemble + persist the clip first so it can be replayed/corrected later.
    mp4 = assemble_mp4(frames, fps)
    if audio_bytes:
        mp4 = mux_audio(mp4, audio_bytes, audio_suffix)
    chunk_index = session["chunks"] + 1
    storage_key = ""
    recording_id = session.get("recording_id") or ""
    if recording_id:
        store_dir = Path(__file__).resolve().parent.parent / "data" / "live" / recording_id
        store_dir.mkdir(parents=True, exist_ok=True)
        name = f"chunk-{chunk_index:03d}.mp4"
        (store_dir / name).write_bytes(mp4)
        storage_key = f"data/live/{recording_id}/{name}"

    if not ai.live_enabled():
        result = {"frames": [], "simulated": True, "status": "ok",
                  "note": "No META_API_KEY configured; live video segmentation unavailable (no simulated video masks are fabricated)."}
    else:
        file_id = ai.upload_video_file(mp4)
        try:
            result = ai.segment_video_clip(file_id, prompt)
        finally:
            ai.delete_video_file(file_id)

    # Chain: remember the last frame's first object bbox for the next chunk.
    if result.get("frames"):
        last = result["frames"][-1]
        if last.get("objects"):
            session["last_bbox_px"] = last["objects"][0]["bbox_px"]
            session["image_size"] = last["objects"][0]["image_size"]
    elif result.get("status") == "no_match":
        session["last_bbox_px"] = None

    session["chunks"] += 1
    payload = {"frames": result.get("frames", []), "simulated": result.get("simulated", True),
               "status": result.get("status", "ok"), "note": result.get("note", ""),
               "prompt_kind": prompt_kind, "prompt_used": prompt_text.strip() if prompt_kind == "concept" else prompt_kind,
               "start_ms": int(start_ms or 0), "end_ms": int(end_ms or 0),
               "image_size": [w, h], "frame_count": len(frames),
               "model": ai.SAM_MODEL, "recording_id": recording_id}
    if db is not None and recording_id:
        rec = db.get(M.LiveRecording, recording_id)
        if rec is not None:
            row = M.LiveChunk(recording_id=recording_id, chunk_index=chunk_index, storage_key=storage_key,
                              frame_count=len(frames), fps=fps, width=w, height=h,
                              prompt_text=prompt_text, prompt_kind=prompt_kind,
                              result_status=result.get("status", "ok"),
                              simulated=1 if result.get("simulated") else 0,
                              segmentation={"frames": result.get("frames", [])},
                              start_ms=int(start_ms or 0), end_ms=int(end_ms or 0),
                              prompt_source=prompt_source or "", speech_phrase=speech_phrase or "")
            db.add(row); db.commit(); db.refresh(row)
            payload["chunk_id"] = row.id
            payload["video_url"] = f"/api/live-recordings/{recording_id}/chunks/{chunk_index}/video"
    return payload
