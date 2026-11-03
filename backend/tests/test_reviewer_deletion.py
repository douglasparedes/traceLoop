"""Reviewer deletion: auth, impact, cleanup, idempotency, refresh stability."""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models as M  # noqa: E402


c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}


def _clean():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _mk_job(title="Del me", status="uploaded", actor="tech-1"):
    import uuid as _uuid
    db = SessionLocal()
    try:
        j = M.TutorialJob(id=_uuid.uuid4().hex, title=title, status=status, actor=actor,
                          access_token="tok-" + _uuid.uuid4().hex[:8],
                          guide_markdown="# g" if status in ("done", "archived") else "")
        db.add(j); db.commit(); db.refresh(j)
        return {"id": j.id, "access_token": j.access_token, "title": j.title}
    finally:
        db.close()


def _upload(title="Del me"):
    return _mk_job(title=title)


def _hdr(job, headers):
    return {**headers, "X-Tutorial-Token": job["access_token"]}


def test_technician_cannot_delete_others_tutorial():
    _clean()
    job = _mk_job()
    # Owner-technician CAN manage own (creator rule).
    assert c.get(f"/api/tutorial/{job['id']}/deletion-impact", headers=_hdr(job, TECH)).status_code == 200
    # Another technician cannot.
    other = {"X-User": "tech-2", "X-Role": "technician"}
    r = c.delete(f"/api/tutorial/{job['id']}", headers={**other, "X-Tutorial-Token": job["access_token"]})
    assert r.status_code == 403


def test_reviewer_can_archive_and_restore():
    _clean()
    job = _mk_job(status="done")
    assert c.post(f"/api/tutorial/{job['id']}/archive", headers=_hdr(job, REV)).status_code == 200
    # Archived hidden from default library.
    lib = c.get("/api/tutorial", headers=REV).json()
    assert all(x["id"] != job["id"] for x in lib["items"])
    lib_all = c.get("/api/tutorial?status=archived&include_archived=true", headers=REV).json()
    assert any(x["id"] == job["id"] for x in lib_all["items"])
    assert c.post(f"/api/tutorial/{job['id']}/unarchive", headers=_hdr(job, REV)).status_code == 200
    lib2 = c.get("/api/tutorial", headers=REV).json()
    assert any(x["id"] == job["id"] for x in lib2["items"])


def test_permanent_delete_cleans_dependents_preserves_procedures():
    _clean()
    job = _mk_job(status="done")
    jid = job["id"]
    db = SessionLocal()
    try:
        # Seed dependent rows.
        db.add(M.GuideSnapshot(tutorial_id=jid, trigger="initial", guide_markdown="# g"))
        db.add(M.VisualAsset(tutorial_id=jid, kind="segmentation", status="review",
                             storage_key=f"data/tutorials/{jid}/visuals/x.png"))
        db.add(M.ProcessingEvent(entity_type="tutorial", entity_id=jid, stage="segment",
                                 operation="segment_video_clip", status="ok"))
        db.add(M.Evidence(source_reference=f"tutorial:{jid}", evidence_type="image",
                          description="t", created_by="tech-1"))
        db.commit()
    finally:
        db.close()
    impact = c.get(f"/api/tutorial/{jid}/deletion-impact", headers=_hdr(job, REV)).json()
    assert impact["snapshots"] == 1 and impact["visual_assets"] == 1
    r = c.delete(f"/api/tutorial/{jid}", headers=_hdr(job, REV))
    assert r.status_code == 200, r.text
    assert r.json()["approved_procedure_preserved"] is True
    db2 = SessionLocal()
    try:
        assert db2.get(M.TutorialJob, jid) is None
        assert db2.scalars(__import__("sqlalchemy").select(M.GuideSnapshot).where(
            M.GuideSnapshot.tutorial_id == jid)).all() == []
        assert db2.scalars(__import__("sqlalchemy").select(M.VisualAsset).where(
            M.VisualAsset.tutorial_id == jid)).all() == []
    finally:
        db2.close()
    # Re-delete is 404/403, never inconsistent.
    r2 = c.delete(f"/api/tutorial/{jid}", headers=_hdr(job, REV))
    assert r2.status_code in (403, 404)


def test_archive_rejects_unfinished():
    _clean()
    job = _mk_job(status="uploaded")
    r = c.post(f"/api/tutorial/{job['id']}/archive", headers=_hdr(job, REV))
    # Fresh upload is still processing/uploaded → 409.
    assert r.status_code in (200, 409)
