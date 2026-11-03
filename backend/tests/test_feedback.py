"""Field feedback → improvement proposal loop, stage rollup, and canonical
step enrichment. Direct-DB fixtures keep these fast (pipeline behavior is
covered by test_studio.py / test_canonical.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import tutorial as tutmod  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import models as M  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}


def _approved_procedure(title="Pump seal check"):
    db = SessionLocal()
    try:
        p = M.Procedure(title=title, asset_type="pump", created_by="tech-1")
        db.add(p)
        db.flush()
        v = M.ProcedureVersion(procedure_id=p.id, version_number=1, status="approved",
                              summary="Check the seal.", prerequisites="Isolate power.",
                              source_evidence={}, created_by="tech-1")
        db.add(v)
        db.flush()
        steps = []
        for i, (t, ins) in enumerate([("Isolate power", "Switch the trainer off first."),
                                      ("Inspect seal", "Look at the seal closely.")], start=1):
            s = M.ProcedureStep(procedure_version_id=v.id, step_order=i, title=t, instruction=ins,
                                expected_result=f"Result {i}", required_tools=["driver"] if i == 1 else [],
                                evidence_refs=[], visual_refs=[], verification_notes=f"Check {i}",
                                start_sec=float((i - 1) * 5), end_sec=float(i * 5))
            db.add(s)
            steps.append(s)
        db.flush()
        v.steps = steps
        db.commit()
        return p.id, v.id, [s.id for s in steps]
    finally:
        db.close()


def _start_finish_job(pid, vid):
    j = c.post("/api/jobs", json={"procedure_id": pid, "procedure_version_id": vid}, headers=TECH).json()
    jid = j["id"]
    # some events first (proves proposals see execution evidence, not just feedback)
    c.post("/api/sync/events", json={"events": [
        {"event_id": f"{jid}-e1", "session_id": jid, "step_id": None,
         "event_type": "step_completed", "payload": {"step_order": 1},
         "occurred_at": "2026-01-01T00:00:00"},
        {"event_id": f"{jid}-e2", "session_id": jid, "step_id": None,
         "event_type": "issue_recorded", "payload": {"issue_type": "Instructions unclear", "note": "Which screw?"},
         "occurred_at": "2026-01-01T00:01:00"}]}, headers=TECH)
    assert c.post(f"/api/jobs/{jid}/finish", json={"outcome": "finished-with-exceptions", "reason": "step 2 unclear"}, headers=TECH).status_code == 200
    return jid


def _feedback_body(step_ids, status="confusing", note="Which screw do you mean?"):
    return {"step_outcomes": [{"step_id": step_ids[1], "status": status, "note": note}],
            "missing_info": "Screw sizes missing.",
            "unexpected": "Seal was already seated.",
            "visual_correct": True, "assistance_needed": False,
            "overall": "Almost worked."}


def test_feedback_validation_and_lifecycle():
    pid, vid, sids = _approved_procedure("Feedback validation")
    jid = _start_finish_job(pid, vid)
    # Unknown step rejected, not silently dropped.
    bad = _feedback_body(sids)
    bad["step_outcomes"] = [{"step_id": "nope", "status": "confusing", "note": "x"}]
    assert c.post(f"/api/jobs/{jid}/feedback", json=bad, headers=TECH).status_code == 422
    # Bad status rejected.
    bad2 = _feedback_body(sids)
    bad2["step_outcomes"][0]["status"] = "meh"
    assert c.post(f"/api/jobs/{jid}/feedback", json=bad2, headers=TECH).status_code == 422
    # Submit ok.
    r = c.post(f"/api/jobs/{jid}/feedback", json=_feedback_body(sids), headers=TECH)
    assert r.status_code == 200, r.text
    # Duplicate without replace -> 409, history preserved.
    assert c.post(f"/api/jobs/{jid}/feedback", json=_feedback_body(sids), headers=TECH).status_code == 409
    got = c.get(f"/api/jobs/{jid}/feedback", headers=TECH).json()
    assert len(got["feedback"]) == 1
    assert got["feedback"][0]["payload"]["visual_correct"] is True
    assert got["feedback"][0]["payload"]["step_outcomes"][0]["step_id"] == sids[1]
    # Replace supersedes but keeps history.
    r = c.post(f"/api/jobs/{jid}/feedback", json={**_feedback_body(sids), "replace": True}, headers=TECH).json()
    assert r["superseded"] == 1
    got = c.get(f"/api/jobs/{jid}/feedback", headers=TECH).json()
    assert len(got["feedback"]) == 2


def test_propose_improvement_guards_and_draft():
    pid, vid, sids = _approved_procedure("Proposal guards")
    jid = _start_finish_job(pid, vid)
    # Technician cannot propose.
    assert c.post(f"/api/jobs/{jid}/propose-improvement", json={}, headers=TECH).status_code == 403
    # No feedback yet -> 409.
    assert c.post(f"/api/jobs/{jid}/propose-improvement", json={}, headers=REV).status_code == 409
    # Unfinished job -> 409.
    j2 = c.post("/api/jobs", json={"procedure_id": pid, "procedure_version_id": vid}, headers=TECH).json()["id"]
    assert c.post(f"/api/jobs/{j2}/propose-improvement", json={}, headers=REV).status_code == 409
    # With feedback -> draft fork with before/after, simulated-labelled.
    assert c.post(f"/api/jobs/{jid}/feedback", json=_feedback_body(sids), headers=TECH).status_code == 200
    r = c.post(f"/api/jobs/{jid}/propose-improvement", json={}, headers=REV).json()
    assert r["ok"] and r["simulated"] is True, r
    assert r["changes"], r
    ch = r["changes"][0]
    assert ch["step_order"] == 2 and ch["before"] != ch["after"]
    assert "Which screw" in ch["after"]  # technician's words, not invented content
    assert ch["confidence"] == "low"
    nv = c.get(f"/api/procedure-versions/{r['version_id']}", headers=TECH).json()
    assert nv["status"] == "draft" and nv["version_number"] == 2
    assert nv["ai_simulated"] is True
    prop = nv["source_evidence"]["proposal"]
    assert prop["job_id"] == jid and prop["base_version_id"] == vid
    assert prop["feedback_event_id"]
    # The applied draft step carries the suggestion; base untouched.
    flagged = [s for s in nv["steps"] if s["step_order"] == 2][0]
    assert "Which screw" in (flagged["verification_notes"] or "")
    base = c.get(f"/api/procedure-versions/{vid}", headers=TECH).json()
    assert base["status"] == "approved"
    assert all("Which screw" not in (s["verification_notes"] or "") for s in base["steps"])


def test_full_loop_feedback_proposal_approval_pinning():
    """Journey D end-to-end: feedback becomes a new revision; old jobs stay pinned."""
    pid, vid, sids = _approved_procedure("Full loop")
    jid = _start_finish_job(pid, vid)
    assert c.post(f"/api/jobs/{jid}/feedback", json=_feedback_body(sids), headers=TECH).status_code == 200
    r = c.post(f"/api/jobs/{jid}/propose-improvement", json={}, headers=REV).json()
    assert r["ok"] and len(r["changes"]) == 1
    nv_id = r["version_id"]
    # New draft goes through normal review.
    assert c.post(f"/api/procedure-versions/{nv_id}/submit-review", json={}, headers=TECH).status_code == 200
    v2 = c.post(f"/api/procedure-versions/{nv_id}/approve", json={"comment": "verified"}, headers=REV).json()
    assert v2["status"] == "approved"
    # Old revision superseded, never mutated.
    v1 = c.get(f"/api/procedure-versions/{vid}", headers=TECH).json()
    assert v1["status"] == "superseded"
    assert all("Which screw" not in (s["verification_notes"] or "") for s in v1["steps"])
    assert any("Which screw" in (s["verification_notes"] or "") for s in
               c.get(f"/api/procedure-versions/{nv_id}", headers=TECH).json()["steps"])
    # Original job still pinned to v1; new jobs use v2.
    assert c.get(f"/api/jobs/{jid}", headers=TECH).json()["procedure_version_id"] == vid
    j3 = c.post("/api/jobs", json={"procedure_id": pid, "procedure_version_id": nv_id}, headers=TECH).json()
    assert j3["procedure_version_id"] == nv_id
    # Jobs cannot start from the superseded/draft states.
    assert c.post("/api/jobs", json={"procedure_id": pid, "procedure_version_id": vid}, headers=TECH).status_code == 409


def test_stages_rollup_and_states():
    db = SessionLocal()
    try:
        job = M.TutorialJob(title="Stages", actor="tech-1", access_token="tok-stages",
                            status="done", full_transcript="x", timed_segments=[],
                            objects=[], steps=[], guide_markdown="g")
        db.add(job)
        db.flush()
        from app import processing as proc
        proc.safe_record(db, "tutorial", job.id, "probe", "succeeded", operation="probe_video",
                         provider="", model="", duration_ms=10, summary={})
        proc.safe_record(db, "tutorial", job.id, "extract_audio", "succeeded", operation="extract_audio_wav",
                         provider="", model="", duration_ms=5, summary={})
        proc.safe_record(db, "tutorial", job.id, "transcribe", "simulated", operation="transcribe_timed",
                         provider="meta", model="muse-voice-transcribe-1.0", duration_ms=20,
                         summary={"note": "no key"})
        proc.safe_record(db, "tutorial", job.id, "segment", "needs_tap", operation="segment_video_clip",
                         provider="meta", model="sam-3.1", duration_ms=30,
                         summary={"obj_id": 1, "note": "needs tap"})
        proc.safe_record(db, "tutorial", job.id, "guide", "simulated", operation="generate_guide",
                         provider="meta", model="muse-spark-1.3", duration_ms=40, summary={})
        db.commit()
        jid = job.id
    finally:
        db.close()
    hdr = {**TECH, "X-Tutorial-Token": "tok-stages"}
    r = c.get(f"/api/tutorial/{jid}/stages", headers=hdr).json()
    by_key = {s["stage"]: s for s in r["stages"]}
    assert by_key["ingest"]["state"] == "completed"
    assert by_key["transcribe"]["mode"] == "simulated"
    assert by_key["segment"]["state"] == "needs_review"
    assert by_key["guide"]["model"] == "muse-spark-1.3"
    # Draft stage never ran on this fixture -> pending (job done, no draft events).
    assert by_key["draft"]["state"] == "pending"
    # Wrong token rejected.
    bad = dict(hdr)
    bad["X-Tutorial-Token"] = "wrong"
    assert c.get(f"/api/tutorial/{jid}/stages", headers=bad).status_code == 403


def test_canonical_enrichment_flows_into_draft():
    db = SessionLocal()
    try:
        job = M.TutorialJob(title="Enrich", actor="tech-1", access_token="tok-enrich",
                            status="uploaded",
                            steps=[{"step_number": 1, "title": "Power off", "summary": "Switch it off.",
                                    "start": 0, "end": 5, "objects_used": [],
                                    "expected_result": "Light goes dark.",
                                    "verification_notes": "Check the indicator.",
                                    "required_tools": ["insulated gloves"]}],
                            objects=[], timed_segments=[], materials=[])
        db.add(job)
        db.flush()
        jid = job.id
        ver = tutmod._ensure_review_draft(db, job, job.steps, [], "# g", [], model="m",
                                         simulated=True, actor="tech-1", snapshot_id="s1")
        db.commit()
        vid = ver.id
    finally:
        db.close()
    ver = c.get(f"/api/procedure-versions/{vid}", headers=TECH).json()
    st = ver["steps"][0]
    assert st["expected_result"] == "Light goes dark."
    assert st["required_tools"] == ["insulated gloves"]
    assert st["verification_notes"] == "Check the indicator."


def test_version_carries_transcript_segments():
    db = SessionLocal()
    try:
        job = M.TutorialJob(title="Seg link", actor="tech-1", access_token="tok-seglink",
                            status="uploaded",
                            timed_segments=[{"text": "First power off.", "start": 0.0, "end": 4.0},
                                            {"text": "Then inspect.", "start": 4.0, "end": 9.0}],
                            steps=[{"step_number": 1, "title": "Power off", "summary": "Switch it off.",
                                    "start": 1.0, "end": 3.0, "objects_used": []}],
                            objects=[], materials=[])
        db.add(job)
        db.flush()
        jid = job.id
        ver = tutmod._ensure_review_draft(db, job, job.steps, [], "# g", [], model="m",
                                         simulated=True, actor="tech-1", snapshot_id="s1")
        db.commit()
        vid = ver.id
    finally:
        db.close()
    ver = c.get(f"/api/procedure-versions/{vid}", headers=TECH).json()
    segs = ver["steps"][0]["transcript_segments"]
    assert len(segs) == 1 and segs[0]["text"] == "First power off."
