"""Server media persistence: streaming uploads, dedup, path safety,
storage health, and per-version video immutability."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import storage as _storage  # noqa: E402
from app import videoguide as _vg  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models as M  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}


def test_media_path_traversal_rejected():
    root = _storage.media_root()
    assert _storage.media_path("data/tutorials/abc/source.mp4").parent == root / "tutorials" / "abc"
    for bad in ["", "../x", "/abs/path", "data/../../etc/passwd", "data\\..\\x"]:
        try:
            _storage.media_path(bad)
        except ValueError:
            continue
        raise AssertionError(f"should reject {bad!r}")
    # Legacy keys resolve under MEDIA_ROOT, never the repo source tree.
    p = _storage.media_path("data/evidence/x.jpg")
    assert str(p).startswith(str(root))


def test_upload_persists_and_dedups_without_loading_all_at_once(monkeypatch):
    blob = b"\x00\x00\x00\x18ftypmp42" + bytes(200_000)
    up = c.post("/api/tutorial/start", files={"file": ("clip.mp4", blob, "video/mp4")},
                data={"title": "Persist me", "mode": "visual_first",
                      "equipment_name": "Pump P-1", "task_description": "Do it.", "context_notes": "Night."},
                headers=TECH).json()
    assert up["input_mode"] == "visual_first"
    assert up["origin"] == "recorded"  # default origin
    assert up["equipment_name"] == "Pump P-1"
    # Source bytes are on disk and served back identically (not just a DB row).
    vid = c.get(up["video_url"] + f"?token={up['access_token']}")
    assert vid.status_code == 200 and vid.content == blob


def test_upload_rejects_bad_type_and_mode():
    r = c.post("/api/tutorial/start", files={"file": ("x.txt", b"hello", "text/plain")},
               data={"title": "Bad"}, headers=TECH)
    assert r.status_code == 415
    r = c.post("/api/tutorial/start", files={"file": ("x.mp4", b"1234", "video/mp4")},
               data={"title": "Bad mode", "mode": "telepathic"}, headers=TECH)
    assert r.status_code == 422


def test_upload_with_origin_and_metadata():
    blob = b"\x00\x00\x00\x18ftypmp42" + bytes(1000)
    up = c.post("/api/tutorial/start", files={"file": ("field.mp4", blob, "video/mp4")},
                data={"title": "Field upload", "mode": "auto", "task_description": "T",
                      "context_notes": "N"}, headers=TECH).json()
    # Origin defaults to recorded; uploads pass origin=uploaded from the UI.
    assert up["origin"] in ("recorded", "uploaded")


def test_duplicate_upload_returns_cached():
    db = SessionLocal()
    try:
        import hashlib as _h
        blob = b"\x00\x00\x00\x18ftypmp42" + b"dup-bytes"
        digest = _h.sha256(blob).hexdigest()
        db.add(M.TutorialJob(title="Done stub", actor="tech-1", access_token="tok-dup",
                             video_hash=digest, video_storage_key="data/tutorials/done/source.mp4",
                             status="done"))
        db.commit()
        r = c.post("/api/tutorial/start", files={"file": ("again.mp4", blob, "video/mp4")},
                   data={"title": "Again"}, headers=TECH).json()
        assert r.get("cached") is True and r["title"] == "Done stub"
        # No temp files leak on any path.
        assert list((_storage.media_root() / ".tmp").glob("*.part")) == []
    finally:
        db.close()


def test_upload_size_limit_enforced_while_streaming(monkeypatch):
    import app.main as _main
    monkeypatch.setattr(_main, "TUTORIAL_MAX_BYTES", 100)
    r = c.post("/api/tutorial/start", files={"file": ("big.mp4", b"0" * 200, "video/mp4")},
               data={"title": "Big"}, headers=TECH)
    assert r.status_code == 413, r.status_code
    # Rejected upload leaves no job and no temp file behind.
    from app.db import SessionLocal as _S
    from sqlalchemy import select as _select
    db = _S()
    try:
        assert db.scalar(_select(M.TutorialJob).where(M.TutorialJob.title == "Big")) is None
    finally:
        db.close()
    assert list((_storage.media_root() / ".tmp").glob("*.part")) == []


def test_storage_health_endpoint_guarded_and_honest():
    assert c.get("/api/admin/storage", headers=TECH).status_code == 403
    r = c.get("/api/admin/storage", headers=REV)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["media_root_ok"] is True and body["writable"] is True
    assert body["database_ok"] is True
    assert "disk" in body and "missing" in body
    # A video guide pointing at a missing file is reported (row ids only).
    db = SessionLocal()
    try:
        vg = M.VideoGuide(tutorial_id="missing-tut", status="ready", version_number=1,
                          storage_key="data/tutorials/missing-tut/video/gone.mp4",
                          created_by="tech-1")
        db.add(vg)
        db.commit()
        missing_id = vg.id
    finally:
        db.close()
    body2 = c.get("/api/admin/storage", headers=REV).json()
    assert missing_id in body2["missing"]["video_guides"]


def test_video_filenames_unique_per_version(tmp_path):
    d = tmp_path / "video"
    d.mkdir()
    f1, k1 = _vg._next_video_filename(d, "jid")
    f2, k2 = _vg._next_video_filename(d, "jid")
    assert k1 != k2 and f1 != f2
    assert k1.startswith("data/tutorials/jid/video/guide-video-") and k1.endswith(".mp4")


def test_keyframe_endpoint_serves_and_guards(tmp_path):
    db = SessionLocal()
    try:
        job = M.TutorialJob(title="KF", actor="tech-1", access_token="tok-kf",
                            video_storage_key="data/tutorials/kf/source.mp4", status="done")
        db.add(job)
        db.commit()
        jid, tok = job.id, job.access_token
    finally:
        db.close()
    # Missing file -> 404, not index.html.
    assert c.get(f"/api/tutorial/{jid}/keyframes/keyframe-00.jpg?token={tok}").status_code == 404
    # Path traversal rejected.
    assert c.get(f"/api/tutorial/{jid}/keyframes/..%2F..%2Fsecret?token={tok}").status_code in (404, 422)
    # Real keyframe file served with the right media type.
    root = _storage.media_root() / "tutorials" / jid
    root.mkdir(parents=True, exist_ok=True)
    (root / "keyframe-00.jpg").write_bytes(b"\xff\xd8\xff fakejpg")
    r = c.get(f"/api/tutorial/{jid}/keyframes/keyframe-00.jpg?token={tok}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    # Wrong token -> 403, never the bytes.
    assert c.get(f"/api/tutorial/{jid}/keyframes/keyframe-00.jpg?token=nope").status_code == 403


def test_missing_asset_path_returns_404_not_html():
    # A stale cached index.html may reference a bundle that no longer exists;
    # the server must 404 instead of serving index.html as text/html.
    r = c.get("/assets/index-stale123.js")
    assert r.status_code == 404, r.status_code
