"""Scene suggestion: AI-planned initial plan from processed tutorial content.

Read-only — creates no versions, saves no drafts. The plan must be
render-acceptable (validate_scene_plan) and reference only real files.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _upload_finished_tutorial(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video",
                        lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav",
                        lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy",
                        lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "first do this then do that", "segments": [
            {"text": "first do this", "start": 0.0, "end": 5.0},
            {"text": "then do that", "start": 5.0, "end": 10.0}],
        "simulated": False})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "knob", "first_mentioned_at": 0.0, "obj_id": 1, "status": "pending"}],
        "steps": [
            {"step_number": 1, "title": "Do this first", "start": 0.0, "end": 5.0,
             "summary": "First do this.", "objects_used": [1]},
            {"step_number": 2, "title": "Do that next", "start": 5.0, "end": 10.0,
             "summary": "Then do that.", "objects_used": []}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [], "simulated": True, "status": "no_match"})
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# Guide\n", "materials": [], "simulated": False})
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", b"fake-bytes-suggest", "video/mp4")},
                data={"title": "Suggest demo", "mode": "auto"}, headers=TECH)
    assert up.status_code == 200, up.text
    jid, token = up.json()["id"], up.json()["access_token"]
    hdr = dict(TECH)
    hdr["X-Tutorial-Token"] = token
    end = time.time() + 20.0
    while time.time() < end:
        r = c.get(f"/api/tutorial/{jid}", headers=hdr)
        assert r.status_code == 200, r.text
        if r.json()["status"] == "done":
            return jid, token
        time.sleep(0.2)
    raise AssertionError("tutorial did not finish")


def test_suggest_returns_validated_plan_from_processed_content(monkeypatch):
    jid, token = _upload_finished_tutorial(monkeypatch)
    hdr = dict(TECH)
    hdr["X-Tutorial-Token"] = token
    r = c.get(f"/api/tutorial/{jid}/video-guide/suggest", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    scenes = body["scenes"]
    assert len(scenes) == 2
    for s in scenes:
        assert s["title"]
        assert s["audio_end"] > s["audio_start"] >= 0
        assert s["audio_end"] <= 30.5
        assert s.get("include", True) is True
    # Read-only: no versions created, no drafts saved.
    hist = c.get(f"/api/tutorial/{jid}/video-guides", headers=hdr)
    assert hist.status_code == 200
    assert hist.json()["versions"] == []


def test_suggest_rejects_bad_token(monkeypatch):
    jid, token = _upload_finished_tutorial(monkeypatch)
    bad = dict(TECH)
    bad["X-Tutorial-Token"] = "wrong"
    r = c.get(f"/api/tutorial/{jid}/video-guide/suggest", headers=bad)
    assert r.status_code in (401, 403), r.text


def test_suggest_plan_unit_no_steps():
    from app import videoguide as vgmod

    class _Job:
        title = "Empty"
        steps = []
        objects = []
        timed_segments = []
        duration_sec = 30.0

    try:
        vgmod.suggest_scene_plan(_Job())  # type: ignore[arg-type]
    except ValueError as e:
        assert "No guide steps" in str(e)
    else:
        raise AssertionError("expected ValueError for a job with no steps")
