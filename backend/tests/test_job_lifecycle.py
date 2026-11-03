"""Job lifecycle: finalize-once semantics, server-side state projection,
transition validation, and ownership guards.

Covers the finalize endpoint (atomic last-step + finish), the state
reconstruction endpoint used for resume/reload recovery, sync-event
validation (unknown types, post-finish writes), and idempotent
registration.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""  # tests must never call the live Meta API

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
TECH2 = {"X-User": "tech-2", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}


def _seed():
    r = c.post("/api/seed")
    assert r.status_code == 200, r.text
    procs = c.get("/api/procedures").json()
    p = next(x for x in procs if x["approved_version_id"])
    ver = c.get(f"/api/procedure-versions/{p['approved_version_id']}").json()
    assert ver["status"] == "approved" and len(ver["steps"]) == 5
    return p, ver


def _start_job(p, headers=TECH):
    r = c.post("/api/jobs", json={"procedure_id": p["id"],
                                  "procedure_version_id": p["approved_version_id"]}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _sync(events, headers=TECH, expect=200):
    r = c.post("/api/sync/events", json={"events": events}, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def _step_events(job_id, ver, kinds):
    """kinds: list of (step_index, event_type) using stable test event ids."""
    evs = []
    for idx, kind in kinds:
        s = ver["steps"][idx]
        evs.append({"event_id": f"evt:{job_id}:{s['id']}:{kind}", "session_id": job_id,
                    "step_id": s["id"], "event_type": kind,
                    "payload": {"step_order": s["step_order"]}, "occurred_at": "2026-01-01T00:00:00Z"})
    return evs


def test_finalize_happy_path_and_idempotent():
    p, ver = _seed()
    job = _start_job(p)
    _sync(_step_events(job["id"], ver, [(i, "step_completed") for i in range(5)]))
    last = ver["steps"][-1]
    r = c.post(f"/api/jobs/{job['id']}/finalize",
               json={"step_id": last["id"], "event_id": f"evt:{job['id']}:{last['id']}:complete", "reason": ""},
               headers=TECH)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "outcome": "completed"}
    again = c.post(f"/api/jobs/{job['id']}/finalize",
                   json={"step_id": last["id"], "event_id": f"evt:{job['id']}:{last['id']}:complete", "reason": ""},
                   headers=TECH)
    assert again.json().get("already_finished") is True
    st = c.get(f"/api/jobs/{job['id']}/state").json()
    assert st["finished"] is True and st["outcome"] == "completed"
    assert st["counts"] == {"total": 5, "completed": 5, "skipped": 0, "blocked": 0}
    assert st["current"] is None


def test_finalize_rejects_unfinished_steps():
    p, ver = _seed()
    job = _start_job(p)
    _sync(_step_events(job["id"], ver, [(0, "step_completed"), (1, "step_completed")]))
    last = ver["steps"][-1]
    r = c.post(f"/api/jobs/{job['id']}/finalize",
               json={"step_id": last["id"], "event_id": "e-final-1", "reason": ""}, headers=TECH)
    assert r.status_code == 422, r.text
    # Steps 3 and 4 lack any terminal event; step 5 is covered by the
    # finalize call itself.
    assert r.json()["detail"].startswith("Steps still need an outcome")


def test_finalize_with_skip_yields_exceptions():
    p, ver = _seed()
    job = _start_job(p)
    kinds = [(0, "step_completed"), (1, "step_completed"), (2, "step_skipped"),
             (3, "step_completed"), (4, "step_completed")]
    _sync(_step_events(job["id"], ver, kinds))
    last = ver["steps"][-1]
    r = c.post(f"/api/jobs/{job['id']}/finalize",
               json={"step_id": last["id"], "event_id": "e-final-2", "reason": ""}, headers=TECH)
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "finished-with-exceptions"
    assert r.json()["outcome"] == "finished-with-exceptions"


def test_finalize_unknown_step_and_wrong_job():
    p, ver = _seed()
    job = _start_job(p)
    r = c.post(f"/api/jobs/{job['id']}/finalize",
               json={"step_id": "nope", "event_id": "e-x", "reason": ""}, headers=TECH)
    assert r.status_code == 422
    assert c.post("/api/jobs/does-not-exist/finalize",
                  json={"step_id": "x", "event_id": "e-x", "reason": ""}, headers=TECH).status_code == 404


def test_finalize_forbidden_for_other_technician():
    p, ver = _seed()
    job = _start_job(p, headers=TECH)
    last = ver["steps"][-1]
    assert c.post(f"/api/jobs/{job['id']}/finalize",
                  json={"step_id": last["id"], "event_id": "e-x", "reason": ""},
                  headers=TECH2).status_code == 403
    # ...but allowed for a reviewer resolving someone else's job.
    _sync(_step_events(job["id"], ver, [(i, "step_completed") for i in range(5)]), headers=TECH)
    r = c.post(f"/api/jobs/{job['id']}/finalize",
               json={"step_id": last["id"], "event_id": "e-x2", "reason": ""}, headers=REV)
    assert r.status_code == 200, r.text


def test_sync_rejects_unknown_types_and_post_finish_events():
    p, ver = _seed()
    job = _start_job(p)
    s0 = ver["steps"][0]["id"]
    out = _sync([{"event_id": "e-bogus", "session_id": job["id"], "step_id": s0,
                  "event_type": "teleport_completed", "payload": {}, "occurred_at": "2026-01-01T00:00:00Z"}])
    assert out["failed"] and out["acknowledged"] == []
    _sync(_step_events(job["id"], ver, [(i, "step_completed") for i in range(5)]))
    last = ver["steps"][-1]
    c.post(f"/api/jobs/{job['id']}/finalize",
           json={"step_id": last["id"], "event_id": "e-fin", "reason": ""}, headers=TECH)
    # Step outcome changes are rejected after finalization, but evidence and
    # notes reconcile so offline photos are never lost.
    late = _sync([{"event_id": "e-late", "session_id": job["id"], "step_id": s0,
                   "event_type": "field_note", "payload": {"note": "hi"}, "occurred_at": "2026-01-01T00:00:00Z"}])
    assert late["acknowledged"] == ["e-late"] and not late["failed"]
    late_step = _sync([{"event_id": "e-late-step", "session_id": job["id"], "step_id": s0,
                        "event_type": "step_completed", "payload": {}, "occurred_at": "2026-01-01T00:00:01Z"}])
    assert late_step["failed"] and "finished" in late_step["failed"][0]["error"]
    # Duplicates of already-synced events stay idempotent.
    dup = _sync([{"event_id": f"evt:{job['id']}:{s0}:step_completed", "session_id": job["id"],
                  "step_id": s0, "event_type": "step_completed", "payload": {},
                  "occurred_at": "2026-01-01T00:00:00Z"}])
    assert dup["duplicates"]


def test_state_projection_blocked_resume_cycle():
    p, ver = _seed()
    job = _start_job(p)
    s0, s1 = ver["steps"][0]["id"], ver["steps"][1]["id"]
    _sync([
        {"event_id": "e-c0", "session_id": job["id"], "step_id": s0,
         "event_type": "step_completed", "payload": {}, "occurred_at": "2026-01-01T00:00:00Z"},
        {"event_id": "e-b1", "session_id": job["id"], "step_id": s1,
         "event_type": "step_blocked", "payload": {}, "occurred_at": "2026-01-01T00:00:01Z"},
    ])
    st = c.get(f"/api/jobs/{job['id']}/state").json()
    assert st["finished"] is False
    assert st["counts"] == {"total": 5, "completed": 1, "skipped": 0, "blocked": 1}
    # A blocked step halts the job: it is the current blocker, not skipped.
    assert st["is_blocked"] is True and st["can_progress"] is False and st["can_finalize"] is False
    assert st["current"]["step_id"] == s1
    assert st["blocked_step"]["step_id"] == s1
    assert st["blocked_step_orders"] == [2]
    by_id = {s["step_id"]: s["state"] for s in st["steps"]}
    assert by_id[s1] == "blocked"
    _sync([{"event_id": "e-r1", "session_id": job["id"], "step_id": s1,
            "event_type": "step_resumed", "payload": {}, "occurred_at": "2026-01-01T00:00:02Z"}])
    st2 = c.get(f"/api/jobs/{job['id']}/state").json()
    assert {s["step_id"]: s["state"] for s in st2["steps"]}[s1] == "pending"
    assert st2["current"]["step_id"] == s1


def test_start_duplicate_id_is_idempotent():
    p, _ = _seed()
    body = {"procedure_id": p["id"], "procedure_version_id": p["approved_version_id"], "id": "job-stable-1"}
    r1 = c.post("/api/jobs", json=body, headers=TECH)
    assert r1.status_code == 200, r1.text
    r2 = c.post("/api/jobs", json=body, headers=TECH)
    assert r2.json().get("already_registered") is True
    assert r2.json()["id"] == "job-stable-1"


def test_finish_requires_owner_or_reviewer():
    p, ver = _seed()
    job = _start_job(p, headers=TECH)
    assert c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed", "reason": "", "summary": ""},
                  headers=TECH2).status_code == 403
    # Reviewer passes auth but coverage still applies: empty job cannot finish.
    assert c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed", "reason": "", "summary": ""},
                  headers=REV).status_code == 422
    _sync(_step_events(job["id"], ver, [(i, "step_completed") for i in range(5)]), headers=TECH)
    assert c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed", "reason": "", "summary": ""},
                  headers=REV).json()["ok"] is True


def test_finalize_rejects_blocked_step_until_resolved():
    p, ver = _seed()
    job = _start_job(p)
    _sync(_step_events(job["id"], ver, [(0, "step_completed"), (1, "step_blocked"),
                                        (2, "step_completed"), (3, "step_completed"),
                                        (4, "step_completed")]))
    last = ver["steps"][-1]
    r = c.post(f"/api/jobs/{job['id']}/finalize",
               json={"step_id": last["id"], "event_id": "e-blocked-fin", "reason": ""}, headers=TECH)
    assert r.status_code == 422, r.text
    assert "Blocked steps must be resolved" in r.json()["detail"]
    s1 = ver["steps"][1]["id"]
    _sync([{"event_id": "e-resume-1", "session_id": job["id"], "step_id": s1,
            "event_type": "step_resumed", "payload": {}, "occurred_at": "2026-01-01T00:00:02Z"}])
    _sync([{"event_id": "e-done-1", "session_id": job["id"], "step_id": s1,
            "event_type": "step_completed", "payload": {}, "occurred_at": "2026-01-01T00:00:03Z"}])
    r2 = c.post(f"/api/jobs/{job['id']}/finalize",
                json={"step_id": last["id"], "event_id": "e-blocked-fin-2", "reason": ""}, headers=TECH)
    assert r2.status_code == 200 and r2.json()["outcome"] == "completed"


def test_finish_adapter_enforces_identical_rules():
    p, ver = _seed()
    job = _start_job(p)
    # Empty job: both paths reject with 422.
    last = ver["steps"][-1]
    assert c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed"}, headers=TECH).status_code == 422
    assert c.post(f"/api/jobs/{job['id']}/finalize",
                  json={"step_id": last["id"], "event_id": "e-x", "reason": ""}, headers=TECH).status_code == 422
    # Blocked job: both paths reject until resolved.
    _sync(_step_events(job["id"], ver, [(0, "step_completed"), (1, "step_blocked")]))
    assert c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed"}, headers=TECH).status_code == 422
    assert c.post(f"/api/jobs/{job['id']}/finalize",
                  json={"step_id": last["id"], "event_id": "e-y", "reason": ""}, headers=TECH).status_code == 422
