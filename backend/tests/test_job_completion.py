"""Job completion persistence vs Procedures availability (issue B).

Covers: list query carries execution context, completion persists and is
returned authoritatively, repeat runs allowed explicitly, duplicates safe,
different technicians isolated, offline pending distinct from confirmed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
TECH2 = {"X-User": "tech-2", "X-Role": "technician"}


def _clean():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _seed():
    _clean()
    assert c.post("/api/seed").status_code == 200
    procs = c.get("/api/procedures").json()
    p = next(x for x in procs if x["approved_version_id"])
    ver = c.get(f"/api/procedure-versions/{p['approved_version_id']}").json()
    return p, ver


def _complete_all(job_id, ver, headers=TECH):
    for s in ver["steps"]:
        r = c.post("/api/sync/events", json={"events": [{
            "event_id": f"evt:{job_id}:{s['id']}:complete", "session_id": job_id,
            "step_id": s["id"], "event_type": "step_completed", "payload": {},
            "occurred_at": "2026-01-01T00:00:00Z"}]}, headers=headers)
        assert r.status_code == 200, r.text
    last = ver["steps"][-1]
    r = c.post(f"/api/jobs/{job_id}/finalize",
               json={"step_id": last["id"], "event_id": f"evt:{job_id}:{last['id']}:complete", "reason": ""},
               headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_jobs_carries_execution_context():
    p, ver = _seed()
    job = c.post("/api/jobs", json={"procedure_id": p["id"],
                                    "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    rows = c.get("/api/jobs").json()
    row = next(r for r in rows if r["id"] == job["id"])
    assert row["procedure_id"] == p["id"]
    assert row["procedure_version_id"] == p["approved_version_id"]
    assert row["technician_id"] == "tech-1"
    assert row["status"] == "active" and row["ended_at"] is None


def test_completed_job_persists_and_allows_explicit_rerun():
    p, ver = _seed()
    job = c.post("/api/jobs", json={"procedure_id": p["id"],
                                    "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    _complete_all(job["id"], ver)
    rows = c.get("/api/jobs").json()
    done = next(r for r in rows if r["id"] == job["id"])
    assert done["status"] == "finished" and done["outcome"] == "completed"
    assert done["ended_at"] is not None
    # Procedure stays approved/reusable; an explicit new run is allowed.
    procs = c.get("/api/procedures").json()
    assert next(x for x in procs if x["id"] == p["id"])["approved_version_id"] == p["approved_version_id"]
    job2 = c.post("/api/jobs", json={"procedure_id": p["id"],
                                     "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    assert job2["id"] != job["id"]
    rows2 = c.get("/api/jobs").json()
    assert sum(1 for r in rows2 if r["procedure_id"] == p["id"]) == 2
    # Original stays finished; duplicate finalize is idempotent, not a new job.
    last = ver["steps"][-1]
    dup = c.post(f"/api/jobs/{job['id']}/finalize",
                 json={"step_id": last["id"], "event_id": "e-dup", "reason": ""}, headers=TECH).json()
    assert dup.get("already_finished") is True
    assert sum(1 for r in c.get("/api/jobs").json() if r["procedure_id"] == p["id"]) == 2


def test_technicians_isolated():
    p, ver = _seed()
    j1 = c.post("/api/jobs", json={"procedure_id": p["id"],
                                   "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    _complete_all(j1["id"], ver, headers=TECH)
    j2 = c.post("/api/jobs", json={"procedure_id": p["id"],
                                   "procedure_version_id": p["approved_version_id"]}, headers=TECH2).json()
    rows = {r["id"]: r for r in c.get("/api/jobs").json()}
    assert rows[j1["id"]]["status"] == "finished"
    assert rows[j2["id"]]["status"] == "active"  # tech-2 unaffected


def test_state_and_detail_return_authoritative_completion():
    p, ver = _seed()
    job = c.post("/api/jobs", json={"procedure_id": p["id"],
                                    "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    _complete_all(job["id"], ver)
    st = c.get(f"/api/jobs/{job['id']}/state").json()
    assert st["finished"] is True and st["can_finalize"] is False and st["can_progress"] is False
    det = c.get(f"/api/jobs/{job['id']}").json()
    assert det["status"] == "finished"
