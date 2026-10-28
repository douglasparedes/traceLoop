import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient
from PIL import Image

from app import ai
from app.main import app

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _jpeg(w=64, h=48, color=(40, 100, 220)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


def _start():
    r = c.post("/api/live-session/start", headers=TECH)
    assert r.status_code == 200
    return r.json()


def test_live_session_token_guard_and_end():
    s = _start()
    files = [("frames", ("f0.jpg", _jpeg(), "image/jpeg"))]
    data = {"fps": "6", "prompt_text": "blue circle"}
    bad = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files, data=data, headers=TECH)
    assert bad.status_code == 403
    hdr = {**TECH, "X-Live-Token": s["token"]}
    end = c.post(f"/api/live-session/{s['session_id']}/end", headers=hdr)
    assert end.status_code == 200
    # Session is gone: a chunk after end is rejected.
    again = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files, data=data, headers=hdr)
    assert again.status_code == 403


def test_live_chunk_simulated_without_key(monkeypatch):
    monkeypatch.setattr(ai, "upload_video_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not upload without key")))
    s = _start()
    hdr = {**TECH, "X-Live-Token": s["token"]}
    files = [("frames", (f"f{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    r = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
               data={"fps": "6", "prompt_text": "blue circle"}, headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert body["simulated"] is True and body["frames"] == [] and body["frame_count"] == 3


def test_live_chunk_live_parse_and_chain(monkeypatch):
    s = _start()
    hdr = {**TECH, "X-Live-Token": s["token"]}
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(ai, "upload_video_file", lambda mp4, filename="live-chunk.mp4": "file-123")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    seen_prompts = []

    def fake_segment(file_id, prompt):
        seen_prompts.append(prompt)
        return {"frames": [{"frame": 0, "objects": [{"object_id": 0, "bbox_norm": [0.1, 0.2, 0.5, 0.6],
                                                     "bbox_px": [6, 9, 32, 28], "image_size": [64, 48],
                                                     "confidence": 0.9, "mask": None}]}],
                "simulated": False, "status": "ok", "model": "sam-3.1"}

    monkeypatch.setattr(ai, "segment_video_clip", fake_segment)
    import app.live as live_mod
    monkeypatch.setattr(live_mod, "assemble_mp4", lambda frames, fps: b"mp4")

    files = [("frames", (f"f{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    r1 = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
                data={"fps": "6", "prompt_text": "blue circle"}, headers=hdr)
    assert r1.status_code == 200
    assert r1.json()["prompt_kind"] == "concept" and r1.json()["frames"][0]["objects"][0]["bbox_norm"] == [0.1, 0.2, 0.5, 0.6]
    # Second chunk with no prompt re-prompts from the chained bbox.
    r2 = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
                data={"fps": "6", "prompt_text": ""}, headers=hdr)
    assert r2.status_code == 200 and r2.json()["prompt_kind"] == "chained-box"
    assert "<|box;" in seen_prompts[-1]


def test_live_chunk_rejects_bad_frames():
    s = _start()
    hdr = {**TECH, "X-Live-Token": s["token"]}
    files = [("frames", ("f0.jpg", b"not-an-image", "image/jpeg"))]
    r = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
               data={"fps": "6", "prompt_text": "x"}, headers=hdr)
    assert r.status_code == 422


def test_recording_persists_and_replays(monkeypatch):
    import app.live as live_mod
    monkeypatch.setattr(live_mod, "assemble_mp4", lambda frames, fps: b"\x00\x00\x00\x18ftypmp42-fake")
    s = _start()
    hdr = {**TECH, "X-Live-Token": s["token"]}
    rid = s["recording_id"]
    files = [("frames", (f"f{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    r = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
               data={"fps": "6", "prompt_text": "blue circle"}, headers=hdr)
    assert r.status_code == 200 and r.json()["recording_id"] == rid and r.json()["video_url"]
    # Manifest requires the recording token.
    assert c.get(f"/api/live-recordings/{rid}", headers=TECH).status_code == 403
    man = c.get(f"/api/live-recordings/{rid}", headers=hdr)
    assert man.status_code == 200 and len(man.json()["chunks"]) == 1
    assert man.json()["chunks"][0]["review_status"] == "pending"
    # Video is served (token via query for <video> elements).
    vid = c.get(f"/api/live-recordings/{rid}/chunks/1/video", params={"token": s["token"]})
    assert vid.status_code == 200 and vid.content.startswith(b"\x00\x00\x00\x18ftyp")
    # Review + finish + delete lifecycle.
    rev = c.post(f"/api/live-recordings/{rid}/chunks/1/review", json={"status": "verified"}, headers=hdr)
    assert rev.status_code == 200 and rev.json()["review_status"] == "verified"
    lst = c.get("/api/live-recordings", headers=TECH).json()
    assert any(x["id"] == rid for x in lst)
    assert c.request("DELETE", f"/api/live-recordings/{rid}", headers=hdr).status_code == 200
    assert c.get(f"/api/live-recordings/{rid}", headers=hdr).status_code == 403


def test_chunk_audio_mux_and_transcript(monkeypatch):
    import io
    import subprocess
    import imageio_ffmpeg
    s = _start()
    hdr = {**TECH, "X-Live-Token": s["token"]}
    rid = s["recording_id"]
    # 0.5s silent WAV as stand-in chunk audio (ffmpeg muxes any input to AAC).
    import struct
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(struct.pack("<h", 0) * 12000)
    files = [("frames", (f"f{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    files.append(("audio", ("chunk-audio.wav", buf.getvalue(), "audio/wav")))
    r = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
               data={"fps": "6", "prompt_text": "blue circle"}, headers=hdr)
    assert r.status_code == 200
    man = c.get(f"/api/live-recordings/{rid}", headers=hdr).json()
    path = man["chunks"][0]
    vid = c.get(f"/api/live-recordings/{rid}/chunks/1/video", params={"token": s["token"]})
    assert vid.status_code == 200
    # Probe the stored MP4 stream list with bundled ffmpeg.
    import tempfile
    import os as _os
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
        tf.write(vid.content); tmp = tf.name
    try:
        probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", tmp], capture_output=True, text=True)
        assert "Audio:" in probe.stderr and "aac" in probe.stderr.lower()
    finally:
        _os.unlink(tmp)
    # Timed transcript segments persist per chunk and at recording level.
    tr = c.post(f"/api/live-recordings/{rid}/transcript",
                json={"segments": [{"chunk_index": 1, "start_ms": 0, "end_ms": 2000, "text": "This is my flag."},
                                    {"chunk_index": 1, "start_ms": 2000, "end_ms": 4000, "text": "Hold it up."}]},
                headers=hdr)
    assert tr.status_code == 200 and tr.json()["transcript"] == "This is my flag. Hold it up."
    man2 = c.get(f"/api/live-recordings/{rid}", headers=hdr).json()
    assert man2["chunks"][0]["transcript"] == "This is my flag. Hold it up."
    assert c.request("DELETE", f"/api/live-recordings/{rid}", headers=hdr).status_code == 200


def test_chunk_delete_single_and_batch(monkeypatch):
    import app.live as live_mod
    monkeypatch.setattr(live_mod, "assemble_mp4", lambda frames, fps: b"\x00\x00\x00\x18ftypmp42-fake")
    s = _start()
    hdr = {**TECH, "X-Live-Token": s["token"]}
    rid = s["recording_id"]
    files = [("frames", (f"f{i}.jpg", _jpeg(), "image/jpeg")) for i in range(3)]
    for _ in range(3):
        r = c.post(f"/api/live-session/{s['session_id']}/chunk", files=files,
                   data={"fps": "6", "prompt_text": "blue circle", "chunk_start_ms": "0", "chunk_end_ms": "5000", "prompt_source": "speech", "speech_phrase": "flag"}, headers=hdr)
        assert r.status_code == 200
    man = c.get(f"/api/live-recordings/{rid}", headers=hdr).json()
    assert len(man["chunks"]) == 3 and man["chunks"][0]["start_ms"] == 0 and man["chunks"][0]["speech_phrase"] == "flag"
    c.post(f"/api/live-recordings/{rid}/transcript",
           json={"segments": [{"chunk_index": 2, "start_ms": 5000, "end_ms": 7000, "text": "Chunk two text."}]}, headers=hdr)
    # Wrong token cannot delete.
    assert c.request("DELETE", f"/api/live-recordings/{rid}/chunks/1", headers=TECH).status_code == 403
    # Batch delete dedupes and reports missing.
    out = c.post(f"/api/live-recordings/{rid}/chunks/delete", json={"chunk_indexes": [1, 3, 3, 99]}, headers=hdr)
    assert out.status_code == 200
    body = out.json()
    assert body["deleted"] == [1, 3] and body["not_found"] == [99] and body["remaining"] == 1
    assert c.get(f"/api/live-recordings/{rid}/chunks/1/video", params={"token": s["token"]}).status_code == 404
    assert c.get(f"/api/live-recordings/{rid}/chunks/2/video", params={"token": s["token"]}).status_code == 200
    man2 = c.get(f"/api/live-recordings/{rid}", headers=hdr).json()
    assert man2["transcript"] == "Chunk two text."  # rebuilt from survivors
    # Single delete of the last chunk empties the recording.
    out2 = c.request("DELETE", f"/api/live-recordings/{rid}/chunks/2", headers=hdr)
    assert out2.status_code == 200 and out2.json()["recording_empty"] is True
    assert c.request("DELETE", f"/api/live-recordings/{rid}/chunks/2", headers=hdr).status_code == 404
    assert c.request("DELETE", f"/api/live-recordings/{rid}", headers=hdr).status_code == 200

