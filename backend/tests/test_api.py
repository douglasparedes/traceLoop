import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""  # tests must never call the live Meta API
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def _clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

c = TestClient(app)
REV = {"X-User": "rev-1", "X-Role": "reviewer"}
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def test_health():
    r = c.get("/api/health"); assert r.status_code == 200 and r.json()["status"] == "ok"


def test_seed_and_job_flow_idempotent_sync():
    assert c.post("/api/seed").json()["seeded"] in (True, False)
    procs = c.get("/api/procedures").json()
    p = [x for x in procs if x["approved_version_id"]][0]
    job = c.post("/api/jobs", json={"procedure_id": p["id"], "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    ev = {"event_id": "evt-test-1", "session_id": job["id"], "event_type": "step_completed", "payload": {}}
    r1 = c.post("/api/sync/events", json={"events": [ev]}, headers=TECH).json()
    r2 = c.post("/api/sync/events", json={"events": [ev]}, headers=TECH).json()
    assert r1["acknowledged"] == ["evt-test-1"] and r2["duplicates"] == ["evt-test-1"]
    detail = c.get(f"/api/jobs/{job['id']}").json()
    assert len([e for e in detail["events"] if e["event_id"] == "evt-test-1"]) == 1


def test_approval_requires_reviewer_and_approved_immutable():
    cap = c.post("/api/capture-sessions", json={"title": "T", "task_description": "d", "asset_name": "Trainer"}, headers=TECH).json()
    c.put(f"/api/capture-sessions/{cap['id']}/transcript", json={"transcript_corrected": "First do A. Then do B."}, headers=TECH)
    ver = c.post("/api/procedures/draft", json={"capture_session_id": cap["id"]}, headers=TECH).json()
    assert ver["status"] == "draft" and len(ver["steps"]) >= 1
    assert c.post(f"/api/procedure-versions/{ver['id']}/submit-review", json={}, headers=TECH).status_code == 200
    assert c.post(f"/api/procedure-versions/{ver['id']}/approve", json={"comment": ""}, headers=TECH).status_code == 403
    assert c.post(f"/api/procedure-versions/{ver['id']}/approve", json={"comment": "ok"}, headers=REV).status_code == 200
    assert c.put(f"/api/procedure-versions/{ver['id']}", json={"summary": "hack"}, headers=REV).status_code == 409


def test_job_requires_approved_version():
    cap = c.post("/api/capture-sessions", json={"title": "T2", "task_description": "d"}, headers=TECH).json()
    ver = c.post("/api/procedures/draft", json={"capture_session_id": cap["id"]}, headers=TECH).json()
    r = c.post("/api/jobs", json={"procedure_id": ver["procedure_id"], "procedure_version_id": ver["id"]}, headers=TECH)
    assert r.status_code == 409


def test_upload_validation_and_manual_search():
    bad = c.post("/api/manuals", files={"file": ("x.txt", b"hi", "text/plain")}, headers=TECH)
    assert bad.status_code == 415
    hits = c.get("/api/manuals/search", params={"q": "knob"}).json()
    assert isinstance(hits, list)


def test_sync_same_batch_duplicates_do_not_500():
    c.post("/api/seed")
    procs = c.get("/api/procedures").json()
    p = [x for x in procs if x["approved_version_id"]][0]
    job = c.post("/api/jobs", json={"procedure_id": p["id"], "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    ev = {"event_id": "evt-batch-1", "session_id": job["id"], "event_type": "step_completed", "payload": {}}
    r = c.post("/api/sync/events", json={"events": [ev, ev]}, headers=TECH)
    assert r.status_code == 200
    body = r.json()
    assert body["acknowledged"] == ["evt-batch-1"] and body["duplicates"] == ["evt-batch-1"]
    detail = c.get(f"/api/jobs/{job['id']}").json()
    assert len([e for e in detail["events"] if e["event_id"] == "evt-batch-1"]) == 1


def test_job_procedure_mismatch_and_finish_idempotent():
    c.post("/api/seed")
    procs = c.get("/api/procedures").json()
    p = [x for x in procs if x["approved_version_id"]][0]
    bad = c.post("/api/jobs", json={"procedure_id": "not-the-procedure", "procedure_version_id": p["approved_version_id"]}, headers=TECH)
    assert bad.status_code == 409
    job = c.post("/api/jobs", json={"procedure_id": p["id"], "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    assert c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed"}, headers=TECH).json()["ok"] is True
    again = c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed"}, headers=TECH).json()
    assert again.get("already_finished") is True


def test_reject_requires_reason_and_rejected_can_resubmit():
    cap = c.post("/api/capture-sessions", json={"title": "T3", "task_description": "d"}, headers=TECH).json()
    ver = c.post("/api/procedures/draft", json={"capture_session_id": cap["id"]}, headers=TECH).json()
    assert c.post(f"/api/procedure-versions/{ver['id']}/submit-review", json={}, headers=TECH).status_code == 200
    assert c.post(f"/api/procedure-versions/{ver['id']}/reject", json={"comment": ""}, headers=REV).status_code == 422
    assert c.post(f"/api/procedure-versions/{ver['id']}/reject", json={"comment": "Needs clearer step 2"}, headers=REV).status_code == 200
    assert c.post(f"/api/procedure-versions/{ver['id']}/submit-review", json={}, headers=TECH).status_code == 200


def test_segment_requires_image_and_simulated_transcribe_keeps_text():
    cap = c.post("/api/capture-sessions", json={"title": "T4", "task_description": "d"}, headers=TECH).json()
    c.put(f"/api/capture-sessions/{cap['id']}/transcript", json={"transcript_corrected": "Keep me"}, headers=TECH)
    ev = c.post(f"/api/capture-sessions/{cap['id']}/evidence", json={"evidence_type": "transcript", "text_content": "Keep me"}, headers=TECH).json()
    assert c.post(f"/api/evidence/{ev['id']}/segment", json={"prompt_text": "knob"}, headers=TECH).status_code == 400
    tr = c.post(f"/api/capture-sessions/{cap['id']}/transcribe", files={"file": ("n.webm", b"fake", "audio/webm")}, headers=TECH)
    assert tr.status_code == 200 and tr.json()["simulated"] is True
    got = c.get(f"/api/capture-sessions/{cap['id']}").json()
    assert got["transcript_corrected"] == "Keep me"

