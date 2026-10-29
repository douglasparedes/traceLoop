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


def test_assetlinks_served_as_json_for_twa_verification():
    import json as _json
    r = c.get("/.well-known/assetlinks.json")
    assert r.status_code == 200, r.text[:200]
    assert "application/json" in r.headers.get("content-type", "")
    body = _json.loads(r.text)
    assert isinstance(body, list) and body
    assert body[0]["relation"] == ["delegate_permission/common.handle_all_urls"]
    assert body[0]["target"]["namespace"] == "android_app"
    assert body[0]["target"]["package_name"]
    fps = body[0]["target"]["sha256_cert_fingerprints"]
    assert isinstance(fps, list) and fps and all(isinstance(f, str) for f in fps)
    # Must be real fingerprints: Android ignores placeholders and the TWA
    # falls back to a Custom Tab with the address bar. Skipped (not failed)
    # until the signing key is available — the key lives with whoever built
    # the APK, so CI cannot provide it. See docs/deployment-coolify.md.
    if any("REPLACE" in f for f in fps):
        pytest.skip("assetlinks.json still has the placeholder fingerprint — paste the APK signing key (docs/deployment-coolify.md §3)")
    import re as _re
    for f in fps:
        assert _re.fullmatch(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){31}", f), f"not a SHA-256 fingerprint: {f}"
REV = {"X-User": "rev-1", "X-Role": "reviewer"}
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def test_frontend_static_and_spa_fallback():
    # Production single-origin serving: built PWA is served by the API app.
    # Skipped in environments without a frontend build.
    from pathlib import Path
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        import pytest as _pt
        _pt.skip("frontend/dist not built")
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    man = c.get("/manifest.webmanifest")
    assert man.status_code == 200 and "manifest" in man.headers["content-type"]
    assert c.get("/sw.js").status_code == 200
    spa = c.get("/procedures")
    assert spa.status_code == 200 and "text/html" in spa.headers["content-type"]
    assert c.get("/api/does-not-exist").status_code == 404
    assert c.get("/api/health").status_code == 200


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


def test_job_evidence_attach_and_list():
    c.post("/api/seed")
    procs = c.get("/api/procedures").json()
    assert "asset_type" in procs[0]
    p = [x for x in procs if x["approved_version_id"]][0]
    job = c.post("/api/jobs", json={"procedure_id": p["id"], "procedure_version_id": p["approved_version_id"]}, headers=TECH).json()
    assert c.get(f"/api/jobs/{job['id']}/evidence").json() == {"job_id": job["id"], "evidence": []}
    assert c.get(f"/api/jobs/{job['id']}").json()["evidence"] == []
    assert c.post(f"/api/jobs/does-not-exist/evidence", files={"file": ("a.jpg", b"x", "image/jpeg")}).status_code == 404
    bad_type = c.post(f"/api/jobs/{job['id']}/evidence", files={"file": ("a.txt", b"x", "text/plain")}, headers=TECH)
    assert bad_type.status_code == 415
    png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 64
    r = c.post(f"/api/jobs/{job['id']}/evidence", files={"file": ("step.png", png, "image/png")}, data={"step_id": "s1", "description": "Housing open"}, headers=TECH)
    assert r.status_code == 200 and "id" in r.json()
    listing = c.get(f"/api/jobs/{job['id']}/evidence", headers=TECH).json()
    assert len(listing["evidence"]) == 1 and listing["evidence"][0]["step_id"] == "s1"
    assert listing["evidence"][0]["image_url"].startswith("/api/evidence/")
    img = c.get(listing["evidence"][0]["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    detail = c.get(f"/api/jobs/{job['id']}").json()
    assert len(detail["evidence"]) == 1
    c.post(f"/api/jobs/{job['id']}/finish", json={"outcome": "completed", "reason": "", "summary": ""}, headers=TECH)
    late = c.post(f"/api/jobs/{job['id']}/evidence", files={"file": ("b.png", png, "image/png")}, headers=TECH)
    assert late.status_code == 409


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


def test_offline_job_registration_with_client_id():
    # A job created offline keeps its client id; registering it on reconnect
    # is idempotent and its queued events then sync exactly once.
    c.post("/api/seed")
    procs = c.get("/api/procedures").json()
    p = [x for x in procs if x["approved_version_id"]][0]
    body = {"id": "11111111-2222-3333-4444-555555555555", "procedure_id": p["id"], "procedure_version_id": p["approved_version_id"]}
    r1 = c.post("/api/jobs", json=body, headers=TECH)
    assert r1.status_code == 200 and r1.json()["id"] == body["id"]
    r2 = c.post("/api/jobs", json=body, headers=TECH)
    assert r2.status_code == 200 and r2.json().get("already_registered") is True
    assert len([j for j in c.get("/api/jobs").json() if j["id"] == body["id"]]) == 1
    ev = {"event_id": "evt-offline-1", "session_id": body["id"], "event_type": "step_completed", "payload": {}}
    s1 = c.post("/api/sync/events", json={"events": [ev]}, headers=TECH).json()
    s2 = c.post("/api/sync/events", json={"events": [ev]}, headers=TECH).json()
    assert s1["acknowledged"] == ["evt-offline-1"] and s2["duplicates"] == ["evt-offline-1"]
    # Mismatched reuse of the id is rejected.
    bad = c.post("/api/jobs", json={"id": body["id"], "procedure_id": p["id"], "procedure_version_id": "nope"}, headers=TECH)
    assert bad.status_code in (404, 409)


def test_version_evidence_endpoint():
    cap = c.post("/api/capture-sessions", json={"title": "EV", "task_description": "d", "asset_name": "Trainer"}, headers=TECH).json()
    c.put(f"/api/capture-sessions/{cap['id']}/transcript", json={"transcript_corrected": "First do A. Then do B."}, headers=TECH)
    ver = c.post("/api/procedures/draft", json={"capture_session_id": cap["id"]}, headers=TECH).json()
    r = c.get(f"/api/procedure-versions/{ver['id']}/evidence")
    assert r.status_code == 200
    body = r.json()
    assert body["capture_session_id"] == cap["id"] and isinstance(body["evidence"], list)
    assert c.get("/api/procedure-versions/does-not-exist/evidence").status_code == 404
    assert c.get("/api/evidence/does-not-exist/image").status_code == 404


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

