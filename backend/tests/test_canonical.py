"""Canonical procedure: simulated pipeline, propagation, regeneration, fallbacks, intent.

Runs WITHOUT mocks for the simulated path (real ffmpeg fixtures, no key) and
with live-adapter mocks for the correction/propagation path.
"""
import base64
import io
import os
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}
_TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _fixture_video(path, duration=30, salt=0):
    import subprocess
    ff = tutorial._ffmpeg()
    # salt changes the tone frequency so each test gets unique bytes
    # (identical bytes would hit the upload hash cache and share a job).
    freq = 440 + salt
    cmd = [ff, "-y", "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=10:d={duration}",
           "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
           "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


def _wait_done(job_id, token, timeout=60.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.2)
    raise AssertionError("tutorial job did not finish")


def test_simulated_pipeline_end_to_end_no_key(tmp_path):
    """Test 1: complete deterministic tutorial with NO credentials and NO mocks."""
    assert not ai.live_enabled()
    vid = tmp_path / "sim.mp4"
    _fixture_video(vid)
    up = c.post("/api/tutorial/start", files={"file": ("sim.mp4", vid.read_bytes(), "video/mp4")},
                data={"title": "Simulated reseat"}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    assert len(done["full_transcript"]) > 50
    assert len(done["timed_segments"]) >= 2
    assert all(s["end"] > s["start"] for s in done["timed_segments"])
    assert len(done["steps"]) >= 2
    assert len(done["objects"]) >= 1
    assert done["guide_markdown"] and "Simulated" in done["guide_markdown"]
    snaps = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert snaps and all(s["simulated"] for s in snaps)
    # Draft mirrors canonical steps exactly.
    assert done["draft_version_id"]
    ver = c.get(f"/api/procedure-versions/{done['draft_version_id']}").json()
    assert ver["ai_simulated"] is True
    assert [s["title"] for s in ver["steps"]] == [s["title"] for s in done["steps"]]
    # All three formats generate distinct, usable structures offline.
    seen = {}
    for fmt, marker in (("work_instruction", "## What you need"),
                        ("reference_manual", "## Numbered procedure"),
                        ("interactive", "Step 1 of")):
        r = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": fmt}, headers=hdr).json()
        assert r["format"] == fmt and r["format_source"] == "user", r
        snap = c.get(f"/api/tutorial/{done['id']}/snapshots/{r['snapshot_id']}", headers=hdr).json()
        assert marker in snap["guide_markdown"], (fmt, snap["guide_markdown"][:200])
        seen[fmt] = snap["guide_markdown"]
    assert len({seen["work_instruction"], seen["reference_manual"], seen["interactive"]}) == 3
    snaps2 = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert len(snaps2) == len(snaps) + 3
    # Simulated output is never presented as live.
    for s in snaps2:
        assert s["simulated"] is True


def test_regeneration_approval_pinning_and_conflict(monkeypatch, tmp_path):
    """Test 3: regen syncs drafts, approval is immutable, jobs pin revisions,
    expert edits survive conflicts."""
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "Show the flag.", "simulated": False,
        "segments": [{"text": "Show the flag.", "start": 0.0, "end": 8.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "Show the flag", "start": 0.0, "end": 8.0,
                   "summary": "Hold the flag up.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    monkeypatch.setattr(tutorial, "make_illustrations", lambda job_dir, source, obj, best: (
        (job_dir / "obj-1.png").write_bytes(_TINY_PNG),
        (job_dir / "obj-1-overlay.png").write_bytes(_TINY_PNG),
        {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"})[2])
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": f"# {title}\n\n## Steps\n\n### 1. Show the flag (0s-8s)\n\nHold it up.\n", "materials": ["flag"], "simulated": False})

    vid = tmp_path / "pin.mp4"
    _fixture_video(vid, duration=5, salt=1)
    up = c.post("/api/tutorial/start", files={"file": ("pin.mp4", vid.read_bytes(), "video/mp4")},
                data={"title": "Pin me"}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    vid0 = done["draft_version_id"]

    # Regenerate in another format: new snapshot, same canonical steps in draft.
    r = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "interactive"}, headers=hdr).json()
    assert r["draft_action"] in ("updated", "unchanged", "new_revision"), r
    v1 = c.get(f"/api/procedure-versions/{vid0}").json()
    job = c.get(f"/api/tutorial/{done['id']}", headers=hdr).json()
    assert [s["title"] for s in v1["steps"]] == [s["title"] for s in job["steps"]]
    assert v1["source_evidence"]["canonical_hash"]

    # Expert edits a draft step, then canonical content changes -> conflict keeps expert text.
    edited = dict(v1)
    edited["steps"] = [dict(s, instruction="EXPERT: wave it slowly, twice.") for s in v1["steps"]]
    c.put(f"/api/procedure-versions/{vid0}", json={"steps": edited["steps"]}, headers=TECH)
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        from app import models as M
        j = db.get(M.TutorialJob, done["id"])
        steps = list(j.steps or [])
        steps[0] = dict(steps[0], summary="Hold the flag up high and steady.")
        j.steps = steps
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(j, "steps")
        db.commit()
    finally:
        db.close()
    r2 = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "reference_manual"}, headers=hdr).json()
    assert r2["draft_action"] == "conflict", r2
    v1b = c.get(f"/api/procedure-versions/{vid0}").json()
    assert v1b["steps"][0]["instruction"] == "EXPERT: wave it slowly, twice."
    assert v1b["source_evidence"]["sync"]["action"] == "conflict"
    # Resolve: apply canonical text to step 1 only; expert keeps everything else.
    res = c.post(f"/api/procedure-versions/{vid0}/resolve-conflict", json={"step_orders": [1]}, headers=TECH).json()
    assert res["applied"] == [1] and res["remaining"] == [] and res["action"] == "resolved"
    v1d = c.get(f"/api/procedure-versions/{vid0}").json()
    assert v1d["steps"][0]["instruction"] == "Hold the flag up high and steady."
    assert v1d["source_evidence"]["sync"]["action"] == "resolved"

    # Approve: immutable, jobs pin the revision.
    assert c.post(f"/api/procedure-versions/{vid0}/submit-review", json={}, headers=TECH).status_code == 200
    assert c.post(f"/api/procedure-versions/{vid0}/approve", json={"comment": "ok"}, headers=REV).status_code == 200
    v1c = c.get(f"/api/procedure-versions/{vid0}").json()
    assert v1c["status"] == "approved"
    assert c.put(f"/api/procedure-versions/{vid0}", json={"summary": "mutate"}, headers=TECH).status_code == 409
    # Locked versions refuse conflict resolution too.
    assert c.post(f"/api/procedure-versions/{vid0}/resolve-conflict", json={"step_orders": [1]}, headers=TECH).status_code == 409
    proc = c.get(f"/api/procedure-versions/{vid0}").json()
    job_start = c.post("/api/jobs", json={"procedure_id": proc["procedure_id"],
                                          "procedure_version_id": vid0}, headers=TECH).json()
    assert job_start["procedure_version_id"] == vid0
    # New revision does not move the running job.
    nv = c.post(f"/api/procedure-versions/{vid0}/new-revision", json={}, headers=TECH).json()
    assert nv["id"] != vid0
    assert c.get(f"/api/jobs/{job_start['id']}").json()["procedure_version_id"] == vid0
    # Jobs cannot start from drafts.
    bad = c.post("/api/jobs", json={"procedure_id": proc["procedure_id"],
                                    "procedure_version_id": nv["id"]}, headers=TECH)
    assert bad.status_code == 409


def test_correction_propagates_to_guide_and_draft(monkeypatch, tmp_path):
    """Test 2: a tap correction regenerates the guide and syncs the draft."""
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "Show the flag.", "simulated": False,
        "segments": [{"text": "Show the flag.", "start": 0.0, "end": 8.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "Show the flag", "start": 0.0, "end": 8.0,
                   "summary": "Hold the flag up.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(tutorial, "extract_frame_image", lambda source, t: __import__("PIL.Image", fromlist=["Image"]).new("RGB", (64, 64)))

    def fake_seg(fid, prompt):
        o = {"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "confidence": 0.9, "mask": None}
        return {"frames": [{"frame": 6, "objects": [o]}], "simulated": False, "status": "ok"}

    def fake_illu(job_dir, source, obj, best):
        (job_dir / "obj-1.png").write_bytes(_TINY_PNG)
        (job_dir / "obj-1-overlay.png").write_bytes(_TINY_PNG)
        return {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"}

    monkeypatch.setattr(ai, "segment_video_clip", fake_seg)
    monkeypatch.setattr(tutorial, "make_illustrations", fake_illu)
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": f"# {title}\n\n## Steps\n\n### 1. Show the flag (0s-8s)\n\nHold it up.\n", "materials": ["flag"], "simulated": False})

    vid = tmp_path / "tap.mp4"
    _fixture_video(vid, duration=5, salt=2)
    up = c.post("/api/tutorial/start", files={"file": ("tap.mp4", vid.read_bytes(), "video/mp4")},
                data={"title": "Tap me"}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    snaps_before = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert not any(s["trigger"] == "tap" for s in snaps_before)

    updated = tutorial.resegment_object_tap(done["id"], 1, 0.5, 0.5)
    assert updated["status"] == "ok"
    assert updated.get("regenerated_snapshot_id")
    job = c.get(f"/api/tutorial/{done['id']}", headers=hdr).json()
    assert "obj-1-overlay.png" in job["guide_markdown"]
    snaps_after = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    tap_snaps = [s for s in snaps_after if s["trigger"] == "tap"]
    assert tap_snaps
    tap_full = c.get(f"/api/tutorial/{done['id']}/snapshots/{tap_snaps[0]['id']}", headers=hdr).json()
    assert tap_full["guide_markdown"] == job["guide_markdown"]
    # Draft steps link the corrected visual evidence; originals remain.
    ver = c.get(f"/api/procedure-versions/{job['draft_version_id']}").json()
    assert ver["steps"] and ver["steps"][0]["visual_refs"], ver["steps"]
    assert ver["source_evidence"]["sync"]["action"] in ("updated", "unchanged")
    # Original source pixels untouched: cutout + overlay both linked.
    assert len(ver["steps"][0]["evidence_refs"]) >= 2


def test_simulated_tap_records_real_frame(tmp_path):
    """Simulated tap: no SAM call, but a real local frame excerpt + evidence."""
    vid = tmp_path / "simtap.mp4"
    _fixture_video(vid, duration=10, salt=9)
    up = c.post("/api/tutorial/start", files={"file": ("simtap.mp4", vid.read_bytes(), "video/mp4")},
                data={"title": "Sim tap"}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}

    updated = tutorial.resegment_object_tap(done["id"], 1, 0.4, 0.6)
    assert updated["status"] == "needs_tap"
    assert updated.get("taps") == [{"nx": 0.4, "ny": 0.6}]
    assert updated.get("tap_frame", "").startswith("tap-obj-1")
    from app.tutorial import BASE
    assert (BASE / "data" / "tutorials" / done["id"] / updated["tap_frame"]).is_file()
    assert "no SAM" in updated.get("note", "").lower() or "unavailable" in updated.get("note", "").lower()
    snaps = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert any(s["trigger"] == "tap" for s in snaps)
    # Tap frame linked as evidence on the draft (reviewable), originals intact.
    ver = c.get(f"/api/procedure-versions/{done['draft_version_id']}").json()
    assert ver["steps"] and ver["steps"][0]["evidence_refs"]


def test_fallback_formats_distinct_and_honest():
    """Test 4: offline fallbacks are structurally distinct and never invent facts."""
    steps = [{"step_number": 1, "title": "Isolate power", "start": 0.0, "end": 8.0,
              "summary": "Verify the indicator light is off.", "objects_used": [1]},
             {"step_number": 2, "title": "Remove panel", "start": 8.0, "end": 20.0,
              "summary": "Loosen each screw.", "objects_used": [1]}]
    objects = [{"obj_id": 1, "label": "red screwdriver", "first_mentioned_at": 0.0, "status": "needs_tap"}]
    from app.ai import fallback_guide_markdown
    wi = fallback_guide_markdown("T", steps, objects, "work_instruction")
    rm = fallback_guide_markdown("T", steps, objects, "reference_manual")
    ix = fallback_guide_markdown("T", steps, objects, "interactive")
    assert len({wi, rm, ix}) == 3
    assert "## What you need" in wi and "## Scope" not in wi
    assert "## Scope" in rm and "## Numbered procedure" in rm
    assert "Step 1 of 2" in ix and "Blocked? Record the issue" in ix
    for md in (wi, rm, ix):
        assert "Isolate power" in md and "Remove panel" in md
        for banned in ("torque", "N·m", "voltage", "VAC", "warranty approved"):
            assert banned not in md.lower()
    unknown = fallback_guide_markdown("T", [{"step_number": 1, "title": "Mystery step", "start": 0.0, "end": 5.0,
                                                "summary": "", "objects_used": []}], [])
    assert "unknown" in unknown.lower()


def test_intent_shapes_generation_and_comparison(monkeypatch, tmp_path):
    """Test 6: user intent changes the model request; comparison is recorded."""
    import base64 as _b64
    import httpx
    seen = {}

    class FakeResp:
        def __init__(self, payload):
            self._p = payload
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self._p

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update({"url": url, "json": json})
        img = _b64.b64encode(_TINY_PNG).decode()
        return FakeResp({"data": [{"b64_json": img}], "output_format": "png", "usage": {}})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": True})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "x", "simulated": False, "segments": [{"text": "x", "start": 0.0, "end": 1.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "S", "start": 0.0, "end": 1.0, "summary": "s", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    monkeypatch.setattr(tutorial, "make_illustrations", lambda job_dir, source, obj, best: (
        (job_dir / "obj-1.png").write_bytes(_TINY_PNG),
        (job_dir / "obj-1-overlay.png").write_bytes(_TINY_PNG),
        {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"})[2])
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# G", "materials": [], "simulated": False})

    vid = tmp_path / "intent.mp4"
    _fixture_video(vid, duration=5, salt=3)
    up = c.post("/api/tutorial/start", files={"file": ("intent.mp4", vid.read_bytes(), "video/mp4")},
                data={"title": "Intent"}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}

    # Highlight intent constrains the edit instruction (geometry-preserving).
    r = c.post(f"/api/tutorial/{done['id']}/visuals/improve",
               json={"source": {"kind": "illustration", "name": "obj-1-overlay.png"},
                     "prompt": "Highlight the tip", "intent": "highlight"}, headers=hdr).json()
    assert r["ok"] and "Emphasize the described region" in seen["json"]["prompt"]
    # Alternative intent produces a comparison record, unapproved by default.
    a = c.post(f"/api/tutorial/{done['id']}/visuals/alternative",
               json={"prompt": "Same clamp, newer model", "intent": "newer"}, headers=hdr).json()
    assert a["ok"] and "Create an illustrative depiction of the described newer model" in seen["json"]["prompt"]
    assert a["asset"]["status"] == "review"
    comp = a["asset"]["provenance"]["comparison"]
    assert comp["requested"] == "Same clamp, newer model"
    assert comp["verdict"] == "unverified"
    assert comp["generated_asset"] == a["asset"]["id"]
    # Accepting with a step link records a visual_accept snapshot.
    vid0 = done["draft_version_id"]
    ver = c.get(f"/api/procedure-versions/{vid0}").json()
    acc = c.post(f"/api/visuals/{a['asset']['id']}/accept",
                 json={"step_id": ver["steps"][0]["id"], "version_id": vid0}, headers=TECH).json()
    assert acc["ok"] and acc["evidence_id"]
    snaps = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert any(s["trigger"] == "visual_accept" for s in snaps)
    # The accepted visual is now inline in the visible guide, labelled as accepted.
    job = c.get(f"/api/tutorial/{done['id']}", headers=hdr).json()
    assert f"/api/evidence/{acc['evidence_id']}/image" in job["guide_markdown"]
    assert "accepted visual" in job["guide_markdown"]
    # A later regeneration preserves the accepted visual (no silent loss).
    g2 = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "work_instruction"}, headers=hdr).json()
    assert g2.get("duplicate") is not True
    snap2 = c.get(f"/api/tutorial/{done['id']}/snapshots/{g2['snapshot_id']}", headers=hdr).json()
    assert f"/api/evidence/{acc['evidence_id']}/image" in snap2["guide_markdown"]
