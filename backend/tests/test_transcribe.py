"""Transcription robustness: local WAV validation, provider error parsing
with the server's own message, and auto-mode fallback to visual-first on
deterministic provider rejections (never silent, never retried blindly)."""
import io
import os
import struct
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _wav_bytes(*, channels=1, rate=24000, bits=16, seconds=2.0, audio_format=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        n = int(rate * seconds)
        w.writeframes(b"\x00\x01" * n if bits == 16 else b"\x00" * n)
    raw = bytearray(buf.getvalue())
    if audio_format != 1:
        struct.pack_into("<H", raw, 20, audio_format)
    return bytes(raw)


def test_wav_info_accepts_valid_mono_pcm():
    ok, reason, info = ai._wav_info(_wav_bytes())
    assert ok, reason
    assert info["channels"] == 1 and info["sample_rate"] == 24000 and info["bits"] == 16
    assert info["seconds"] == 2.0


def test_wav_info_rejects_bad_inputs():
    ok, reason, _ = ai._wav_info(b"not audio at all....................................")
    assert not ok and "RIFF" in reason
    ok, reason, _ = ai._wav_info(_wav_bytes(channels=2))
    assert not ok and "mono" in reason
    ok, reason, _ = ai._wav_info(_wav_bytes(rate=44100))
    assert not ok and "24 kHz" in reason
    ok, reason, _ = ai._wav_info(_wav_bytes(audio_format=3))
    assert not ok and "PCM" in reason
    ok, reason, _ = ai._wav_info(_wav_bytes(seconds=0.1))
    assert not ok and "usable" in reason


class _FakeResponse:
    def __init__(self, status, payload):
        import json as _json
        self.status_code = status
        self.text = _json.dumps(payload)


class _HttpError(Exception):
    def __init__(self, status, payload):
        super().__init__(f"400 Client Error for url")
        import json as _json
        self.response = _FakeResponse(status, payload)


def _patch_live(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)


def test_provider_400_message_is_preserved_not_just_status(monkeypatch):
    _patch_live(monkeypatch)
    import httpx as _hx

    def boom(*a, **k):
        raise _HttpError(400, {"error": {"message": "audio is not a supported WAV file", "type": "invalid_request", "code": "bad_audio"}})

    monkeypatch.setattr(_hx, "post", boom)
    out = ai.transcribe_timed("audio.wav", _wav_bytes(), duration_sec=5.0)
    assert out.get("error", "").startswith("Transcription failed (HTTP 400)")
    assert "not a supported WAV file" in out["error"]
    assert "(code: bad_audio)" in out["error"]
    assert "Unexpected token" not in out["error"]
    assert out.get("fallback_visual") is True
    assert "HTTPStatusError" not in out["error"]


def test_provider_413_429_500_are_classified(monkeypatch):
    _patch_live(monkeypatch)
    import httpx as _hx

    monkeypatch.setattr(_hx, "post", lambda *a, **k: (_ for _ in ()).throw(
        _HttpError(413, {"error": {"message": "body too large", "type": "invalid_request"}})))
    out = ai.transcribe_timed("audio.wav", _wav_bytes(), duration_sec=5.0)
    assert "32 MB" in out["error"] and out.get("fallback_visual") is True

    monkeypatch.setattr(_hx, "post", lambda *a, **k: (_ for _ in ()).throw(
        _HttpError(429, {"error": {"message": "concurrency limit", "type": "rate_limited"}})))
    out = ai.transcribe_timed("audio.wav", _wav_bytes(), duration_sec=5.0)
    assert "429" in out["error"] and "retry processing" in out["error"].lower()
    assert out.get("retryable") is True and not out.get("fallback_visual")

    monkeypatch.setattr(_hx, "post", lambda *a, **k: (_ for _ in ()).throw(
        _HttpError(500, {"error": {"message": "internal", "type": "server"}})))
    out = ai.transcribe_timed("audio.wav", _wav_bytes(), duration_sec=5.0)
    assert "retry once" in out["error"].lower() and out.get("retryable") is True


def test_overlong_audio_fails_before_any_http_call(monkeypatch):
    _patch_live(monkeypatch)
    import httpx as _hx
    called = []
    # 700s of silence at 24kHz mono16 = ~33MB; build sparsely via wave module.
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 24000 * 700)
    data = buf.getvalue()

    def _boom(*a, **k):
        called.append(True)
        raise AssertionError("must not call the provider for over-long audio")

    monkeypatch.setattr(_hx, "post", _boom)
    out = ai.transcribe_timed("audio.wav", data, duration_sec=700.0)
    assert "10-minute" in out["error"]
    assert out.get("fallback_visual") is True
    assert not called


def _wait_done(job_id, token, timeout=20.0):
    hdr = dict(TECH)
    hdr["X-Tutorial-Token"] = token
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.2)
    raise AssertionError("tutorial job did not finish")


def _patch_pipeline(monkeypatch, **over):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video",
                        lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy",
                        lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {"frames": [], "simulated": True, "status": "no_match"})
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# Guide\n", "materials": [], "simulated": True})


def test_auto_falls_back_to_visual_on_provider_rejection(monkeypatch):
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "", "segments": [], "simulated": False, "model": ai.VOICE_MODEL,
        "error": "Transcription failed (HTTP 400): audio is not a supported WAV file.",
        "note": "provider 400 type=invalid_request: audio is not a supported WAV file",
        "fallback_visual": True})
    monkeypatch.setattr(ai, "analyze_tutorial_frames", lambda frames, hint, dur: {
        "analysis_mode": "visual_first", "observations": [], "candidate_steps": [],
        "missing_information": ["none"], "dropped": [], "simulated": True, "model": ai.SPARK_MODEL,
        "note": "simulated"})
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", b"fake-bytes-fallback", "video/mp4")},
                data={"title": "Fallback demo", "mode": "auto"}, headers=TECH)
    done = _wait_done(up.json()["id"], up.json()["access_token"])
    assert done["status"] == "done", done
    assert done.get("analysis_strategy") == "visual_first"
    assert "not a supported WAV" in (done.get("strategy_reason") or "")
    assert done.get("full_transcript") == ""


def test_narrated_keeps_hard_fail_with_provider_message(monkeypatch):
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "", "segments": [], "simulated": False, "model": ai.VOICE_MODEL,
        "error": "Transcription failed (HTTP 400): audio is not a supported WAV file.",
        "note": "provider 400", "fallback_visual": True})
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", b"fake-bytes-narrated", "video/mp4")},
                data={"title": "Narrated hard fail", "mode": "narrated"}, headers=TECH)
    done = _wait_done(up.json()["id"], up.json()["access_token"])
    assert done["status"] == "error", done
    assert "not a supported WAV" in (done.get("error") or "")
