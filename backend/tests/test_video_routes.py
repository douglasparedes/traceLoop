"""Version-specific video file route: the exact endpoint the frontend uses.

Reproduces the reported preview/download failures: with APP_PASSWORD set,
the media gate blocked this route (401 JSON to <video>/<a> tags), and the
endpoint never distinguished preview (inline) from download (attachment).
"""
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _tiny_mp4(path, duration=1.0):
    r = subprocess.run(
        [tutorial._ffmpeg(), "-y", "-f", "lavfi", "-i",
         f"testsrc=duration={duration}:size=320x240:rate=30",
         "-pix_fmt", "yuv420p", "-c:v", "mpeg4", str(path)],
        capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


def _seed_ready_version(filename="route-v1.mp4"):
    """A done job + ready VideoGuide whose storage_key is a real MP4."""
    from app.db import SessionLocal
    from app import models as M
    from app import storage as _storage
    jid = f"route-{uuid.uuid4().hex[:8]}"
    token = uuid.uuid4().hex
    d = _storage.media_root() / "tutorials" / jid / "video"
    d.mkdir(parents=True, exist_ok=True)
    _tiny_mp4(d / filename)
    db = SessionLocal()
    try:
        db.add(M.TutorialJob(id=jid, title="Route check", actor="route-seed",
                             access_token=token,
                             video_storage_key=f"data/tutorials/{jid}/source.mp4",
                             status="done", duration_sec=10.0))
        vg = M.VideoGuide(id=uuid.uuid4().hex, tutorial_id=jid, status="ready",
                          progress=100, version_number=3,
                          storage_key=f"data/tutorials/{jid}/video/{filename}",
                          created_by="route-seed",
                          provenance={"canonical_hash": "x"})
        db.add(vg)
        db.commit()
        return jid, token, vg.id
    finally:
        db.close()


def test_preview_is_inline_mp4():
    jid, token, vgid = _seed_ready_version()
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file", params={"token": token})
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["content-disposition"].startswith("inline")
    assert int(r.headers["content-length"]) > 0
    assert r.content[:4] == b"\x00\x00\x00\x18" or r.content[:3] == b"\x00\x00\x00"


def test_download_is_attachment_with_filename():
    jid, token, vgid = _seed_ready_version(filename="route-dl.mp4")
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file",
              params={"token": token, "download": 1})
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "video/mp4"
    disp = r.headers["content-disposition"]
    assert disp.startswith("attachment"), disp
    assert "Route%20check-v3.mp4" in disp, disp


def test_bad_token_is_403_not_401():
    jid, _token, vgid = _seed_ready_version(filename="route-403.mp4")
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file", params={"token": "wrong"})
    assert r.status_code == 403, r.status_code


def test_unrelated_version_is_404():
    jid, token, _vgid = _seed_ready_version(filename="route-404a.mp4")
    jid2, _t2, vgid2 = _seed_ready_version(filename="route-404b.mp4")
    assert jid2 != jid
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid2}/file", params={"token": token})
    assert r.status_code == 404, r.status_code


def test_unfinished_render_is_409():
    from app.db import SessionLocal
    from app import models as M
    jid, token, vgid = _seed_ready_version(filename="route-409.mp4")
    db = SessionLocal()
    try:
        vg = db.get(M.VideoGuide, vgid)
        vg.status = "rendering"
        db.commit()
    finally:
        db.close()
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file", params={"token": token})
    assert r.status_code == 409, r.status_code


def test_missing_file_is_404_with_diagnostics():
    from app.db import SessionLocal
    from app import models as M
    from app import storage as _storage
    jid, token, vgid = _seed_ready_version(filename="route-gone.mp4")
    ( _storage.media_root() / "tutorials" / jid / "video" / "route-gone.mp4").unlink()
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file", params={"token": token})
    assert r.status_code == 404, r.status_code
    body = r.json()
    assert "MEDIA_ROOT" in body["detail"] or "missing" in body["detail"], body


def test_range_request_returns_partial_content():
    jid, token, vgid = _seed_ready_version(filename="route-range.mp4")
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file",
              params={"token": token}, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206, r.status_code
    assert r.headers["content-type"] == "video/mp4"
    assert len(r.content) == 100
    assert r.headers["content-range"].startswith("bytes 0-99/")


def test_media_gate_allows_version_route_with_tutorial_token(monkeypatch):
    """Regression: with APP_PASSWORD set, a browser-style media request
    (no X-Auth-Token header, only ?token=) must pass the gate and be
    validated by the endpoint — this was the preview/download failure."""
    monkeypatch.setenv("APP_PASSWORD", "team-secret")
    jid, token, vgid = _seed_ready_version(filename="route-gate.mp4")
    r = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file", params={"token": token})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.headers["content-type"] == "video/mp4"
    # Non-media API still requires the global token.
    r2 = c.get("/api/assets")
    assert r2.status_code == 401, r2.status_code
    # Wrong tutorial token still 403 through the gate.
    r3 = c.get(f"/api/tutorial/{jid}/video-guides/{vgid}/file", params={"token": "nope"})
    assert r3.status_code == 403, r3.status_code
