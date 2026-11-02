"""Offline execution grants: superseded-revision registration, grant
validation, expiry, and actor/binding enforcement."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import auth as _auth  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models as M  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}


def _approved_pair():
    db = SessionLocal()
    try:
        p = M.Procedure(title="Grant pump", asset_type="pump", created_by="tech-1")
        db.add(p)
        db.flush()
        v1 = M.ProcedureVersion(procedure_id=p.id, version_number=1, status="approved",
                               summary="v1", prerequisites="", source_evidence={},
                               created_by="tech-1")
        db.add(v1)
        db.commit()
        return p.id, v1.id
    finally:
        db.close()


def _supersede(pid, vid):
    db = SessionLocal()
    try:
        v2 = M.ProcedureVersion(procedure_id=pid, version_number=2, status="draft",
                                summary="v2", prerequisites="", source_evidence={},
                                created_by="rev-1")
        db.add(v2)
        db.flush()
        # Mirror the approve endpoint: demote the old approved revision.
        v1 = db.get(M.ProcedureVersion, vid)
        v1.status = "superseded"
        v2.status = "approved"
        db.flush()
        got = {v.version_number: v.status for v in db.scalars(
            __import__("sqlalchemy").select(M.ProcedureVersion).where(
                M.ProcedureVersion.procedure_id == pid)).all()}
        assert got == {1: "superseded", 2: "approved"}, got
        db.commit()
        return v2.id
    finally:
        db.close()


def test_grant_issued_only_for_approved():
    pid, v1 = _approved_pair()
    r = c.post(f"/api/procedure-versions/{v1}/offline-grant", headers=TECH)
    assert r.status_code == 200, r.text
    g = r.json()["offline_grant"]
    assert g.startswith("fg-grant.")
    assert r.json()["procedure_version_id"] == v1
    # Unknown version -> 404.
    assert c.post("/api/procedure-versions/nope/offline-grant", headers=TECH).status_code == 404


def test_superseded_registration_with_grant_and_pinning():
    pid, v1 = _approved_pair()
    # Offline tech downloads v1 (grant issued while approved).
    grant = c.post(f"/api/procedure-versions/{v1}/offline-grant", headers=TECH).json()["offline_grant"]
    # Meanwhile v2 is approved; v1 becomes superseded.
    v2 = _supersede(pid, v1)
    # New jobs pin v2; plain registration against v1 is rejected.
    assert c.post("/api/jobs", json={"procedure_id": pid, "procedure_version_id": v1}, headers=TECH).status_code == 409
    # With the grant, the offline job registers against v1 and stays pinned.
    r = c.post("/api/jobs", json={"id": "offline-job-1", "procedure_id": pid,
                                  "procedure_version_id": v1, "offline_grant": grant}, headers=TECH)
    assert r.status_code == 200, r.text
    assert r.json().get("grant_used") is True
    jid = r.json()["id"]
    # Its events sync and the job stays pinned to v1; new jobs use v2.
    sync = c.post("/api/sync/events", json={"events": [
        {"event_id": "ge1", "session_id": jid, "step_id": None,
         "event_type": "step_completed", "payload": {"step_order": 1},
         "occurred_at": "2026-01-01T00:00:00"}]}, headers=TECH).json()
    assert sync["acknowledged"] == ["ge1"], sync
    got = c.get(f"/api/jobs/{jid}", headers=TECH).json()
    assert got["procedure_version_id"] == v1
    j3 = c.post("/api/jobs", json={"procedure_id": pid, "procedure_version_id": v2}, headers=TECH).json()
    assert j3["procedure_version_id"] == v2
    # Idempotent re-registration under the same id still works.
    again = c.post("/api/jobs", json={"id": jid, "procedure_id": pid,
                                      "procedure_version_id": v1, "offline_grant": grant}, headers=TECH).json()
    assert again.get("already_registered") is True


def test_grant_rejected_when_wrong_version_actor_or_expired():
    pid, v1 = _approved_pair()
    grant = c.post(f"/api/procedure-versions/{v1}/offline-grant", headers=TECH).json()["offline_grant"]
    v2 = _supersede(pid, v1)
    other = "x" * 8
    # Grant is ignored (not needed) when the version is still approved.
    ok = c.post("/api/jobs", json={"id": f"ok-{other}0", "procedure_id": pid,
                                   "procedure_version_id": v2, "offline_grant": grant}, headers=TECH)
    assert ok.status_code == 200 and "grant_used" not in ok.json(), ok.text
    # Wrong scope binding: grant for (pid, v1) used against another
    # procedure's superseded version.
    pid_b, v1b = _approved_pair()
    grant_b = c.post(f"/api/procedure-versions/{v1b}/offline-grant", headers=TECH).json()["offline_grant"]
    _supersede(pid_b, v1b)
    cross = c.post("/api/jobs", json={"id": f"bad-{other}A", "procedure_id": pid_b,
                                      "procedure_version_id": v1b, "offline_grant": grant}, headers=TECH)
    assert cross.status_code == 409, cross.text
    # Wrong actor binding (grant was issued to tech-1, not rev-1).
    other_actor = c.post("/api/jobs", json={"id": f"bad-{other}B", "procedure_id": pid,
                                            "procedure_version_id": v1, "offline_grant": grant}, headers=REV)
    assert other_actor.status_code == 409, other_actor.text
    # Tampered token.
    tampered = c.post("/api/jobs", json={"id": f"bad-{other}C", "procedure_id": pid,
                                         "procedure_version_id": v1, "offline_grant": grant[:-2] + "AA"}, headers=TECH)
    assert tampered.status_code == 409, tampered.text
    # Expired grant.
    expired = _auth.create_offline_grant(pid, v1, "tech-1", ttl_sec=-1)
    exp = c.post("/api/jobs", json={"id": f"bad-{other}D", "procedure_id": pid,
                                    "procedure_version_id": v1, "offline_grant": expired}, headers=TECH)
    assert exp.status_code == 409, exp.text
    # Draft versions can never use grants.
    db = SessionLocal()
    try:
        vd = M.ProcedureVersion(procedure_id=pid, version_number=9, status="draft",
                                summary="d", prerequisites="", source_evidence={}, created_by="rev-1")
        db.add(vd)
        db.commit()
        draft_id = vd.id
    finally:
        db.close()
    assert c.post(f"/api/procedure-versions/{draft_id}/offline-grant", headers=TECH).status_code == 409
    forged = _auth.create_offline_grant(pid, draft_id, "tech-1")
    assert c.post("/api/jobs", json={"id": f"bad-{other}E", "procedure_id": pid,
                                     "procedure_version_id": draft_id, "offline_grant": forged}, headers=TECH).status_code == 409
