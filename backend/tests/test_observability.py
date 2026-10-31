"""Observability + tutorial persistence: processing events, guide snapshots,
diagnostics bundle, cross-actor library, auto-created Review drafts.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
OTHER = {"X-User": "other-1", "X-Role": "technician"}


import base64 as _b64mod

_TINY_PNG = _b64mod.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    # Emulates the LIVE provider path with mocks; simulated-mode coverage
    # lives in dedicated end-to-end tests (no key + real ffmpeg).
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "This is my flag. Hold it up.", "simulated": False,
        "segments": [{"text": "This is my flag.", "start": 1.0, "end": 4.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "Show the flag", "start": 0.0, "end": 8.0,
                   "summary": "Hold the flag up.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6],
                                             "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    def _fake_illu(job_dir, source, obj, best):
        (job_dir / "obj-1.png").write_bytes(_TINY_PNG)
        (job_dir / "obj-1-overlay.png").write_bytes(_TINY_PNG)
        return {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"}
    monkeypatch.setattr(tutorial, "make_illustrations", _fake_illu)
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# Guide\n\n## Steps\n\n### 1. Show the flag (0s-8s)", "materials": ["flag"], "simulated": False})


def _wait_done(job_id, token, timeout=10.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.1)
    raise AssertionError("tutorial job did not finish")


def _done_job(monkeypatch, name=b"obs-bytes", title="Obs tutorial", headers=TECH):
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", name, "video/mp4")},
                data={"title": title}, headers=headers).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    return done


def test_processing_events_recorded_for_pipeline(monkeypatch):
    done = _done_job(monkeypatch, name=b"obs-ev-1")
    tok = done["access_token"]
    ev = c.get("/api/processing/events", params={"entity_type": "tutorial", "entity_id": done["id"]}).json()
    stages = {e["stage"] for e in ev["items"]}
    assert {"probe", "transcribe", "understand", "segment", "guide", "draft"} <= stages, stages
    seg = [e for e in ev["items"] if e["stage"] == "segment"][0]
    assert seg["model"] == "sam-3.1" and seg["status"] == "ok"
    assert seg["summary"]["attempts"] and seg["summary"]["best_confidence"] == 0.9
    assert seg["summary"]["frames_seen"] == 1 and seg["summary"]["coverage"] == 1.0
    # Correlation id shared across the run.
    corrs = {e["correlation_id"] for e in ev["items"] if e["correlation_id"]}
    assert len(corrs) == 1
    # Filter by model and status works.
    sam = c.get("/api/processing/events", params={"model": "sam-3.1"}).json()
    assert sam["total"] >= 1 and all(e["model"] == "sam-3.1" for e in sam["items"])


def test_hirez_attempts_append_not_replace(monkeypatch):
    calls = {"n": 0}

    def fake_segment(fid, prompt):
        calls["n"] += 1
        if calls["n"] <= 3:
            return {"frames": [], "simulated": False, "status": "no_match"}
        return {"frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6],
                                                     "confidence": 0.9, "mask": None}]}],
                "simulated": False, "status": "ok"}

    monkeypatch.setattr(ai, "segment_video_clip", fake_segment)
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "blue adjustment knob", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "Show it", "start": 0.0, "end": 8.0, "summary": "Show it.", "objects_used": [1]}],
        "simulated": False})
    done = _done_job(monkeypatch, name=b"obs-hirez-1", title="Hirez trail")
    obj = done["objects"][0]
    assert obj["status"] == "ok", obj
    prompts = [a["prompt"] for a in obj["attempts"]]
    assert prompts[:3] == ["blue adjustment knob", "adjustment knob", "knob"]
    assert prompts[3].endswith("(hi-res retry)")
    assert obj["best_confidence"] == 0.9 and obj["best_frame"] == 6


def test_tutorial_visible_across_roles_and_paginated(monkeypatch):
    d1 = _done_job(monkeypatch, name=b"obs-lib-1", title="Zebra guide", headers=TECH)
    d2 = _done_job(monkeypatch, name=b"obs-lib-2", title="Alpha guide", headers=OTHER)
    # A different demo identity still sees both tutorials.
    lib = c.get("/api/tutorial", headers=OTHER).json()
    ids = {i["id"] for i in lib["items"]}
    assert {d1["id"], d2["id"]} <= ids
    assert lib["total"] >= 2
    # Search filters to one.
    f = c.get("/api/tutorial", params={"q": "zebra"}).json()
    assert {i["id"] for i in f["items"]} == {d1["id"]}
    # Pagination pages through everything.
    p1 = c.get("/api/tutorial", params={"limit": 1, "offset": 0}).json()
    p2 = c.get("/api/tutorial", params={"limit": 1, "offset": 1}).json()
    assert p1["items"] and p2["items"] and p1["items"][0]["id"] != p2["items"][0]["id"]
    # Status filter works.
    only_done = c.get("/api/tutorial", params={"status": "done"}).json()
    assert only_done["total"] >= 2 and all(i["status"] == "done" for i in only_done["items"])


def test_auto_draft_created_and_idempotent(monkeypatch):
    done = _done_job(monkeypatch, name=b"obs-draft-1", title="Draft me")
    assert done["draft_version_id"], done
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    # Re-requesting returns the same draft, no duplicate.
    r1 = c.post(f"/api/tutorial/{done['id']}/draft", headers=hdr).json()
    r2 = c.post(f"/api/tutorial/{done['id']}/draft", headers=hdr).json()
    assert r1["version_id"] == done["draft_version_id"] == r2["version_id"]
    assert r1["created"] is False and r2["created"] is False
    # The draft is a real Review-queue version with tutorial evidence linked.
    v = c.get(f"/api/procedure-versions/{done['draft_version_id']}").json()
    assert v["status"] == "draft" and len(v["steps"]) == 1
    assert v["steps"][0]["visual_refs"], v["steps"][0]
    ev = c.get(f"/api/procedure-versions/{done['draft_version_id']}/evidence").json()
    assert ev["evidence"], ev
    # Draft appears in the Review queue listing.
    procs = c.get("/api/procedures").json()
    mine = [p for p in procs if p["id"] == r1["procedure_id"]]
    assert mine and mine[0]["has_pending_review"] is False  # drafts are not pending_review
    assert any(vv["status"] == "draft" for vv in mine[0]["versions"])


def test_draft_endpoint_rejects_unfinished(monkeypatch):
    # No background thread: the job deterministically stays "uploaded".
    monkeypatch.setattr(tutorial, "start_job", lambda job_id: None)
    up = c.post("/api/tutorial/start", files={"file": ("unfin.mp4", b"unfin-1", "video/mp4")}, headers=TECH).json()
    hdr = {**TECH, "X-Tutorial-Token": up["access_token"]}
    r = c.post(f"/api/tutorial/{up['id']}/draft", headers=hdr)
    assert r.status_code == 409


def test_snapshots_and_diagnostics(monkeypatch):
    done = _done_job(monkeypatch, name=b"obs-snap-1", title="Snap me")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    snaps = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()
    assert len(snaps["snapshots"]) >= 1 and snaps["snapshots"][0]["trigger"] == "initial"
    sid = snaps["snapshots"][0]["id"]
    one = c.get(f"/api/tutorial/{done['id']}/snapshots/{sid}", headers=hdr).json()
    assert "Show the flag" in one["guide_markdown"]
    # Refresh adds another snapshot instead of overwriting.
    c.post(f"/api/tutorial/{done['id']}/refresh-guide", headers=hdr)
    snaps2 = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()
    assert len(snaps2["snapshots"]) == len(snaps["snapshots"]) + 1
    assert snaps2["snapshots"][-1]["trigger"] == "refresh"
    # Diagnostics bundle combines transcript, objects, snapshots, events.
    diag = c.get(f"/api/tutorial/{done['id']}/diagnostics", headers=hdr).json()
    assert diag["full_transcript"].startswith("This is my flag")
    assert diag["objects"][0]["label"] == "flag"
    assert any(e["stage"] == "segment" for e in diag["events"])
    assert diag["draft_version_id"]


def test_archive_and_restore(monkeypatch):
    done = _done_job(monkeypatch, name=b"obs-arch-1", title="Archive me")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    assert c.post(f"/api/tutorial/{done['id']}/archive", headers=hdr).json()["status"] == "archived"
    lib = c.get("/api/tutorial", headers=TECH).json()
    assert done["id"] not in {i["id"] for i in lib["items"]}
    assert c.post(f"/api/tutorial/{done['id']}/unarchive", headers=hdr).json()["status"] == "done"
    lib2 = c.get("/api/tutorial", headers=TECH).json()
    assert done["id"] in {i["id"] for i in lib2["items"]}
