"""Storage isolation: MEDIA_ROOT redirects every media read/write.

Guards the legacy pattern of resolving media under backend/data directly,
which breaks deployments with a mounted volume. With MEDIA_ROOT pointed
at a temp dir: uploads land there, processing outputs land there, and
path traversal is refused.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

import pytest  # noqa: E402


def test_media_root_resolution_and_traversal(monkeypatch, tmp_path):
    from app import storage as st
    vol = tmp_path / "media"
    monkeypatch.setenv("MEDIA_ROOT", str(vol))
    assert st.media_root() == vol.resolve()
    with pytest.raises(ValueError):
        st.media_path("../evil.mp4")
    with pytest.raises(ValueError):
        st.media_path("/abs/path.mp4")
    with pytest.raises(ValueError):
        st.media_path("data/../evil.mp4")
    p = st.media_path("data/tutorials/j1/source.mp4")
    assert str(p).startswith(str(vol.resolve()))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    assert p.is_file()


def test_tutorial_pipeline_writes_under_media_root(monkeypatch, tmp_path):
    """End-to-end: a full tutorial upload + process cycle with MEDIA_ROOT
    set writes the source video under the volume and serves it back."""
    import time
    from fastapi.testclient import TestClient
    from app import ai, tutorial
    from app.main import app

    vol = tmp_path / "vol"
    monkeypatch.setenv("MEDIA_ROOT", str(vol))

    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video",
                        lambda p: {"duration": 8.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav",
                        lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy",
                        lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "do this thing", "segments": [{"text": "do this thing", "start": 0.0, "end": 2.0}],
        "simulated": False, "model": ai.VOICE_MODEL})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [], "steps": [{"step_number": 1, "title": "Do it", "start": 0.0,
                                  "end": 2.0, "summary": "Do it.", "objects_used": []}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [], "simulated": True, "status": "no_match"})
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# G\n", "materials": [], "simulated": False})

    c = TestClient(app)
    tech = {"X-User": "tech-1", "X-Role": "technician"}
    up = c.post("/api/tutorial/start", files={"file": ("m.mp4", b"fake-bytes-media-root", "video/mp4")},
                data={"title": "Media root", "mode": "auto"}, headers=tech)
    assert up.status_code == 200, up.text
    jid, token = up.json()["id"], up.json()["access_token"]
    hdr = dict(tech)
    hdr["X-Tutorial-Token"] = token
    end = time.time() + 20.0
    while time.time() < end:
        r = c.get(f"/api/tutorial/{jid}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] == "done":
            break
        time.sleep(0.2)
    else:
        raise AssertionError("tutorial did not finish")
    stored = list((vol / "tutorials" / jid).glob("source*"))
    assert stored, "source video must live under MEDIA_ROOT"
    assert all(str(p).startswith(str(vol.resolve())) for p in stored)
    vid = c.get(f"/api/tutorial/{jid}/video", params={"token": token})
    assert vid.status_code == 200
    assert vid.content == b"fake-bytes-media-root"
    # Traversal via storage key can never escape the volume.
    from app import storage as st
    with pytest.raises(ValueError):
        st.media_path("../../outside.mp4")
