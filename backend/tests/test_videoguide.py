"""Video guide: plan fallback, endpoint flow, guards."""
import base64
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
_TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _fixture_video(path, duration=5, salt=77):
    import subprocess
    ff = tutorial._ffmpeg()
    cmd = [ff, "-y", "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=10:d={duration}",
           "-f", "lavfi", "-i", f"sine=frequency={440 + salt}:duration={duration}",
           "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


def _wait_done(job_id, token, timeout=60.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.2)
    raise AssertionError("tutorial job did not finish")


def _video_pipeline(monkeypatch, tmp_path, salt=77):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "Do it now.", "simulated": False,
        "segments": [{"text": "Do it now.", "start": 0.0, "end": 2.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "knob", "first_mentioned_at": 0.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "Turn the knob", "start": 0.0, "end": 2.0,
                   "summary": "Turn the knob clockwise.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    monkeypatch.setattr(tutorial, "make_illustrations", lambda job_dir, source, obj, best: (
        (job_dir / "obj-1.png").write_bytes(_TINY_PNG),
        (job_dir / "obj-1-overlay.png").write_bytes(_TINY_PNG),
        {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"})[2])
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# G\n\n## Steps\n\n### 1. Turn the knob (0s-2s)\n\nTurn it.\n", "materials": [], "simulated": False})
    vid = tmp_path / f"vg-{salt}.mp4"
    _fixture_video(vid, duration=5, salt=salt)
    up = c.post("/api/tutorial/start", files={"file": (f"vg-{salt}.mp4", vid.read_bytes(), "video/mp4")},
                data={"title": "Video me"}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    return done


def _wait_video(job_id, token, statuses=("ready", "error"), timeout=120.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}/video-guide", headers=hdr).json()
        if r["status"] in statuses:
            return r
        time.sleep(0.5)
    raise AssertionError("video guide did not finish")


def test_video_guide_plan_fallback_no_key():
    """Planner fallback: deterministic scenes from canonical content, no network."""
    from app.ai import plan_video_scenes
    steps = [{"step_number": 1, "title": "Turn the knob", "start": 0.0, "end": 2.0,
              "summary": "Turn it clockwise.", "objects_used": [1]}]
    objects = [{"obj_id": 1, "label": "knob", "first_mentioned_at": 0.0,
                "overlay": "obj-1-overlay.png", "illustration": "obj-1.png"}]
    segs = [{"text": "Turn the knob now.", "start": 0.0, "end": 2.0}]
    out = plan_video_scenes("T", steps, objects, segs)
    assert out["simulated"] is True and len(out["scenes"]) == 1
    sc = out["scenes"][0]
    assert sc["audio_start"] == 0.0 and sc["audio_end"] == 2.0
    assert sc["visual"] == {"kind": "overlay", "name": "obj-1-overlay.png", "label": "knob"}
    assert "Turn the knob now" in sc["narration"]  # verbatim transcript, never invented


def test_video_guide_endpoint_flow(monkeypatch, tmp_path):
    """POST starts a background render; status polls to ready; file serves."""
    from app import videoguide as vgmod
    done = _video_pipeline(monkeypatch, tmp_path, salt=81)

    def fake_render(props_path, paths):
        out = paths["dir"] / "guide-video-render.mp4"
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        return out

    monkeypatch.setattr(vgmod, "_render_video", fake_render)
    monkeypatch.setattr(vgmod.ai, "plan_video_scenes", lambda title, steps, objects, segs: {
        "scenes": [{"step_number": 1, "title": "Turn the knob", "narration": "Do it now.",
                    "caption": "Do it now.", "audio_start": 0.0, "audio_end": 2.0,
                    "objects_used": [1], "visual": {"kind": "overlay", "name": "obj-1-overlay.png", "label": "knob"}}],
        "simulated": False, "model": "muse-spark-1.3"})
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    assert c.get(f"/api/tutorial/{done['id']}/video-guide", headers=hdr).json()["status"] == "none"
    r = c.post(f"/api/tutorial/{done['id']}/video-guide", json={}, headers=hdr).json()
    assert r["ok"] and r["video_guide"]["status"] in ("queued", "rendering", "ready")
    # Duplicate in-flight request returns the same job, no second render.
    r2 = c.post(f"/api/tutorial/{done['id']}/video-guide", json={}, headers=hdr).json()
    assert r2["ok"] and r2["duplicate"] is True and r2["video_guide"]["id"] == r["video_guide"]["id"]
    fin = _wait_video(done["id"], done["access_token"])
    assert fin["status"] == "ready", fin
    assert fin["video_guide"]["asset_id"]
    assert fin["video_guide"]["simulated"] is False
    assert len(fin["video_guide"]["scenes"]) == 1
    # File serves with the tutorial bearer; impostors get 403.
    f = c.get(f"/api/tutorial/{done['id']}/video-guide/file", params={"token": done["access_token"]})
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4"
    assert c.get(f"/api/tutorial/{done['id']}/video-guide/file", params={"token": "nope"}).status_code == 403


def test_video_guide_guards(monkeypatch, tmp_path):
    """Unfinished tutorials, over-long tutorials, and quota breaches are refused honestly."""
    from app import videoguide as vgmod
    from app.db import SessionLocal
    from app import models as _M
    done = _video_pipeline(monkeypatch, tmp_path, salt=82)
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    # Over-long tutorial refused.
    monkeypatch.setattr(vgmod, "VIDEO_MAX_SEC", 1)
    r = c.post(f"/api/tutorial/{done['id']}/video-guide", json={}, headers=hdr)
    assert r.status_code == 422
    monkeypatch.setattr(vgmod, "VIDEO_MAX_SEC", 180)
    # Unfinished tutorial refused (deterministic: job row created directly).
    import uuid as _uuid
    db2 = SessionLocal()
    try:
        pend = _M.TutorialJob(id=str(_uuid.uuid4()), title="Pending", actor="tech-1",
                              access_token=str(_uuid.uuid4()), video_hash="vg-pending-1",
                              status="uploaded", video_storage_key="data/tutorials/x/source.mp4")
        db2.add(pend)
        db2.commit()
        pend_id, pend_tok = pend.id, pend.access_token
    finally:
        db2.close()
    hdr_pend = {**TECH, "X-Tutorial-Token": pend_tok}
    assert c.post(f"/api/tutorial/{pend_id}/video-guide", json={}, headers=hdr_pend).status_code == 409
    # Quota exhausted refused.
    monkeypatch.setattr(vgmod, "VIDEO_QUOTA_PER_DAY", 1)
    db = SessionLocal()
    try:
        db.add(_M.VideoGuide(tutorial_id=done["id"], status="ready", created_by="tech-1"))
        db.commit()
    finally:
        db.close()
    assert c.post(f"/api/tutorial/{done['id']}/video-guide", json={}, headers=hdr).status_code == 429
