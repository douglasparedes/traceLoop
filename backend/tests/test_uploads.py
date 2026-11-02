"""Chunked resumable tutorial uploads: sessions, offsets, resume,
idempotent retries, checksum-gated completion, and cleanup."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import UPLOAD_CHUNK_BYTES, app  # noqa: E402
from app import models as M  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
OTHER = {"X-User": "other-1", "X-Role": "technician"}


def _blob(n=200 * 1024):
    return bytes((i % 251 for i in range(n)))


def _init(blob=None, **kw):
    blob = blob if blob is not None else _blob()
    body = {"filename": "field.mp4", "mime": "video/mp4", "total_size": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(), "title": "Chunked",
            "mode": "visual_first", "origin": "uploaded"}
    body.update(kw)
    return c.post("/api/tutorial/uploads", json=body, headers=TECH), blob


def test_init_validates_input():
    blob = _blob(100)
    r, _ = _init(blob, total_size=0)
    assert r.status_code == 422
    r, _ = _init(blob, mode="teleport")
    assert r.status_code == 422
    r, _ = _init(blob, sha256="nothex")
    assert r.status_code == 422
    r, _ = _init(blob, filename="x.txt", mime="text/plain")
    assert r.status_code == 415
    r = c.post("/api/tutorial/uploads", json={"x": 1}, headers=TECH)
    assert r.status_code in (413, 422)


def test_chunk_resume_idempotent_and_complete(tmp_path):
    r, blob = _init()
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    assert r.json()["chunk_size"] == UPLOAD_CHUNK_BYTES
    # Out-of-order chunk with a gap is rejected with the expected offset.
    bad = c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=100",
                content=blob[100:200], headers={**TECH, "Content-Type": "application/octet-stream"})
    assert bad.status_code == 422 and "0" in bad.json()["detail"]
    # First chunk, then the same chunk again (idempotent retry).
    for _ in range(2):
        ok = c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=0",
                   content=blob[:1000], headers={**TECH, "Content-Type": "application/octet-stream"})
        assert ok.status_code == 200, ok.text
    assert ok.json()["received_bytes"] == 1000
    # Mismatched bytes at an already-received offset are rejected.
    clash = c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=0",
                  content=b"X" * 1000, headers={**TECH, "Content-Type": "application/octet-stream"})
    assert clash.status_code == 409
    # Resume from the recorded offset.
    st = c.get(f"/api/tutorial/uploads/{uid}", headers=TECH).json()
    assert st["received_bytes"] == 1000
    rest = c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=1000",
                 content=blob[1000:], headers={**TECH, "Content-Type": "application/octet-stream"})
    assert rest.status_code == 200
    assert rest.json()["received_bytes"] == len(blob)
    done = c.post(f"/api/tutorial/uploads/{uid}/complete", headers=TECH)
    assert done.status_code == 200, done.text
    job = done.json()
    assert job["status"] in ("uploaded", "transcribing", "understanding", "segmenting", "generating", "done", "error")
    assert job.get("input_mode") == "visual_first"
    # Source bytes persisted and served back identically.
    vid = c.get(f"/api/tutorial/{job['id']}/video?token={job['access_token']}")
    assert vid.status_code == 200 and vid.content == blob
    # Re-completing is gone (session consumed).
    assert c.post(f"/api/tutorial/uploads/{uid}/complete", headers=TECH).status_code == 404


def test_complete_requires_full_receipt_and_matching_hash():
    r, blob = _init()
    uid = r.json()["upload_id"]
    half = len(blob) // 2
    c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=0", content=blob[:half],
          headers={**TECH, "Content-Type": "application/octet-stream"})
    early = c.post(f"/api/tutorial/uploads/{uid}/complete", headers=TECH)
    assert early.status_code == 409
    # Tamper: upload different bytes for the second half, hash must fail.
    other = bytes((255 - (i % 251) for i in range(len(blob) - half)))
    c.put(f"/api/tutorial/uploads/{uid}/chunks?offset={half}", content=other,
          headers={**TECH, "Content-Type": "application/octet-stream"})
    bad = c.post(f"/api/tutorial/uploads/{uid}/complete", headers=TECH)
    assert bad.status_code == 422


def test_chunk_size_cap_and_session_isolation():
    r, blob = _init()
    uid = r.json()["upload_id"]
    big = c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=0", content=b"x" * (17 * 1024 * 1024),
                headers={**TECH, "Content-Type": "application/octet-stream"})
    assert big.status_code == 413
    # Another actor cannot touch this session.
    assert c.get(f"/api/tutorial/uploads/{uid}", headers=OTHER).status_code == 403
    assert c.delete(f"/api/tutorial/uploads/{uid}", headers=OTHER).status_code == 403
    # Abort cleans up the session.
    assert c.delete(f"/api/tutorial/uploads/{uid}", headers=TECH).json()["aborted"] is True
    assert c.get(f"/api/tutorial/uploads/{uid}", headers=TECH).status_code == 404


def test_upload_size_limit_enforced_at_init(monkeypatch):
    import app.main as _main
    monkeypatch.setattr(_main, "TUTORIAL_MAX_BYTES", 100)
    r, _ = _init()
    assert r.status_code == 413, r.status_code


def test_duplicate_bytes_return_cached_job():
    db = SessionLocal()
    try:
        import hashlib as _h
        blob = _blob(500)
        digest = _h.sha256(blob).hexdigest()
        stub = M.TutorialJob(title="Done stub", actor="tech-1", access_token="tok-dup2",
                             video_hash=digest, video_storage_key="data/tutorials/done/source.mp4",
                             status="done")
        db.add(stub)
        db.commit()
        stub_id = stub.id
    finally:
        db.close()
    r, _ = _init(blob)
    uid = r.json()["upload_id"]
    c.put(f"/api/tutorial/uploads/{uid}/chunks?offset=0", content=blob,
          headers={**TECH, "Content-Type": "application/octet-stream"})
    done = c.post(f"/api/tutorial/uploads/{uid}/complete", headers=TECH).json()
    assert done.get("cached") is True and done["title"] == "Done stub"
    assert done["id"] == stub_id  # no duplicate job created
