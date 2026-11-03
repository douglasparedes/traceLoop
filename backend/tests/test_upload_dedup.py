"""Upload duplicate handling: identical bytes return the cached finished
tutorial (with an explicit flag); force_new always creates a new job.

Regression for Studio opening a previous video after an upload that
"seemed" to succeed — the server was silently returning the old job.
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _upload_bytes(payload: bytes, title="Dup check", force_new=False):
    sha = hashlib.sha256(payload).hexdigest()
    init = c.post("/api/tutorial/uploads", json={
        "filename": "clip.mp4", "mime": "video/mp4", "total_size": len(payload),
        "sha256": sha, "title": title, "mode": "auto", "origin": "uploaded",
    }, headers=TECH)
    assert init.status_code == 200, init.text
    uid = init.json()["upload_id"]
    put = c.put(f"/api/tutorial/uploads/{uid}/chunks",
                params={"offset": 0}, content=payload,
                headers={**TECH, "Content-Type": "application/octet-stream"})
    assert put.status_code == 200, put.text
    path = f"/api/tutorial/uploads/{uid}/complete"
    if force_new:
        path += "?force_new=1"
    done = c.post(path, headers=TECH)
    assert done.status_code == 200, done.text
    return done.json()


def _mark_done(jid):
    """Mark a job done only after its background worker reached a terminal
    state — otherwise the worker's late status write can clobber "done"
    and make this test (and any dedup check) flaky under load."""
    from app.db import SessionLocal
    from app import models as M
    end = time.time() + 30.0
    while time.time() < end:
        db = SessionLocal()
        try:
            job = db.get(M.TutorialJob, jid)
            if job is not None and job.status in ("done", "error"):
                break
        finally:
            db.close()
        time.sleep(0.2)
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, jid)
        job.status = "done"
        db.commit()
    finally:
        db.close()


def test_identical_bytes_return_cached_job_with_flag():
    payload = os.urandom(2048)
    first = _upload_bytes(payload, title="First")
    assert first.get("cached") is not True
    _mark_done(first["id"])
    second = _upload_bytes(payload, title="Second attempt")
    assert second.get("cached") is True
    assert second["id"] == first["id"]


def test_direct_upload_endpoint_dedups_and_force_new():
    payload = os.urandom(2048)
    r1 = c.post("/api/tutorial/start", files={"file": ("d.mp4", payload, "video/mp4")},
                data={"title": "Direct", "mode": "auto"}, headers=TECH)
    assert r1.status_code == 200, r1.text
    _mark_done(r1.json()["id"])
    r2 = c.post("/api/tutorial/start", files={"file": ("d.mp4", payload, "video/mp4")},
                data={"title": "Direct again", "mode": "auto"}, headers=TECH)
    assert r2.json().get("cached") is True
    assert r2.json()["id"] == r1.json()["id"]
    r3 = c.post("/api/tutorial/start?force_new=1", files={"file": ("d.mp4", payload, "video/mp4")},
                data={"title": "Direct new", "mode": "auto"}, headers=TECH)
    assert not r3.json().get("cached")
    assert r3.json()["id"] != r1.json()["id"]


def test_force_new_creates_a_separate_job():
    payload = os.urandom(2048)
    first = _upload_bytes(payload, title="Original")
    _mark_done(first["id"])
    forced = _upload_bytes(payload, title="Re-processed", force_new=True)
    assert forced.get("cached") is not True
    assert forced["id"] != first["id"]


def test_different_bytes_create_different_jobs():
    a = _upload_bytes(os.urandom(2048), title="A")
    b = _upload_bytes(os.urandom(2048), title="B")
    assert a["id"] != b["id"]
    assert not b.get("cached")
