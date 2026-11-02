"""Tutorial Studio editing: metadata, canonical content revisions, and
video-guide scene plans + versioned renders.

Covers the Phase 11 backend contract: validation, optimistic concurrency,
original preservation, snapshot/video immutability, and authorization.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient

from app import ai, tutorial
from app import videoguide as vgmod
from app.main import app
from app.models import VideoGuide
from app.db import SessionLocal

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _fake_illustrations(job_dir, source, obj, best):
    for _n in ("obj-1.png", "obj-1-overlay.png"):
        (job_dir / _n).write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    return {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"}


def _patch_pipeline(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "This is my flag. Hold it up.", "simulated": False,
        "segments": [{"text": "This is my flag.", "start": 1.0, "end": 4.0},
                     {"text": "Hold it up.", "start": 4.0, "end": 8.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending",
                     "confidence": None, "illustration": "", "overlay": "", "track": []}],
        "steps": [{"step_number": 1, "title": "Show the flag", "start": 0.0, "end": 8.0,
                   "summary": "Hold the flag up.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6],
                                             "bbox_px": [96, 72, 192, 144], "image_size": [320, 240],
                                             "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    monkeypatch.setattr(tutorial, "make_illustrations", _fake_illustrations)
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# Guide\n\n## Steps\n\n### 1. Show the flag (0s-8s)",
        "materials": ["flag"], "simulated": False})


def _wait_done(job_id, token, timeout=15.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.1)
    raise AssertionError("tutorial job did not finish")


def _make_done(monkeypatch):
    _patch_pipeline(monkeypatch)
    # Unique bytes per suite: tutorial_start dedups identical (hash, actor)
    # uploads, so shared fixtures would return another test's cached job.
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", b"fake-video-bytes-studio-tests", "video/mp4")},
                data={"title": "Flag tutorial"}, headers=TECH)
    assert up.status_code == 200
    job = up.json()
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "done", done
    return done


def _hdr(job):
    return {**TECH, "X-Tutorial-Token": job["access_token"]}


def test_metadata_update_and_validation(monkeypatch):
    job = _make_done(monkeypatch)
    hdr = _hdr(job)
    r = c.put(f"/api/tutorial/{job['id']}", json={"title": "  ", **{}}, headers=hdr)
    assert r.status_code == 422
    r = c.put(f"/api/tutorial/{job['id']}",
              json={"title": "Reseat harness", "equipment_name": "Trainer v1",
                    "task_description": "Do the thing.", "context_notes": "Night shift."},
              headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Reseat harness"
    assert body["equipment_name"] == "Trainer v1"
    # Original video untouched: same storage-backed video still served.
    v = c.get(f"/api/tutorial/{job['id']}/video?token={job['access_token']}")
    assert v.status_code == 200


def test_content_save_revision_conflict_and_restore(monkeypatch):
    job = _make_done(monkeypatch)
    hdr = _hdr(job)
    got = c.get(f"/api/tutorial/{job['id']}/content", headers=hdr).json()
    assert got["content_revision"] >= 1
    assert got["transcript_original"] == "This is my flag. Hold it up."  # AI original shown until corrected
    assert got["transcript_corrected"] == ""
    rev0 = got["content_revision"]

    steps = [{"title": "Show the flag", "summary": "Hold the flag up high.",
              "start": 0, "end": 8, "objects_used": [1]}]
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"transcript_corrected": "This is my flag. Hold it up high.",
                    "steps": steps, "expected_revision": rev0},
              headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["content_revision"] == rev0 + 1

    # Original transcription preserved separately; live transcript corrected.
    got2 = c.get(f"/api/tutorial/{job['id']}/content", headers=hdr).json()
    assert got2["transcript_original"] == "This is my flag. Hold it up."
    assert got2["transcript_corrected"] == "This is my flag. Hold it up high."
    assert got2["steps"][0]["summary"] == "Hold the flag up high."
    assert got2["steps"][0]["step_number"] == 1

    # Stale save is rejected, not merged.
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"transcript_corrected": "stale", "expected_revision": rev0},
              headers=hdr)
    assert r.status_code == 409

    # Invalid steps rejected.
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"steps": [{"title": "", "summary": "x"}], "expected_revision": rev0 + 1},
              headers=hdr)
    assert r.status_code == 422
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"steps": [{"title": "T", "summary": "x", "start": 5, "end": 2}],
                    "expected_revision": rev0 + 1},
              headers=hdr)
    assert r.status_code == 422

    # Revision history lists the save; restore creates a NEW revision.
    revs = c.get(f"/api/tutorial/{job['id']}/revisions", headers=hdr).json()
    assert revs["current_revision"] == rev0 + 1
    assert len(revs["revisions"]) == 1
    rid = revs["revisions"][0]["id"]

    # Save something else, then restore the first revision.
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"transcript_corrected": "Second version.", "expected_revision": rev0 + 1},
              headers=hdr)
    assert r.status_code == 200
    r = c.post(f"/api/tutorial/{job['id']}/revisions/{rid}/restore",
               json={"expected_revision": rev0 + 2}, headers=hdr)
    assert r.status_code == 200, r.text
    got3 = c.get(f"/api/tutorial/{job['id']}/content", headers=hdr).json()
    assert got3["transcript_corrected"] == "This is my flag. Hold it up high."
    revs2 = c.get(f"/api/tutorial/{job['id']}/revisions", headers=hdr).json()
    assert len(revs2["revisions"]) == 3  # history preserved, never rewritten

    # Wrong token is rejected.
    bad = dict(hdr)
    bad["X-Tutorial-Token"] = "wrong"
    assert c.get(f"/api/tutorial/{job['id']}/content", headers=bad).status_code == 403


def test_content_save_then_regen_syncs_draft_without_touching_approved(monkeypatch):
    job = _make_done(monkeypatch)
    hdr = _hdr(job)
    got = c.get(f"/api/tutorial/{job['id']}/content", headers=hdr).json()
    # Edit canonical steps.
    steps = [{"title": "Show the flag, corrected", "summary": "Hold the flag up, corrected.",
              "start": 0, "end": 8, "objects_used": [1]}]
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"steps": steps, "expected_revision": got["content_revision"]}, headers=hdr)
    assert r.status_code == 200, r.text
    # Guide snapshots are immutable: regen creates a new one.
    before = c.get(f"/api/tutorial/{job['id']}/snapshots", headers=hdr).json()["snapshots"]
    r = c.post(f"/api/tutorial/{job['id']}/guide", json={}, headers=hdr).json()
    assert r["ok"]
    after = c.get(f"/api/tutorial/{job['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert len(after) == len(before) + 1
    assert after[0]["id"] == before[0]["id"]  # first snapshot untouched
    # Draft synced (editable), and approving it then editing again forks.
    draft_id = r["draft_version_id"]
    assert draft_id
    admin = {"X-User": "rev-1", "X-Role": "reviewer"}
    c.post(f"/api/procedure-versions/{draft_id}/submit-review", json={}, headers=TECH)
    assert c.post(f"/api/procedure-versions/{draft_id}/approve", json={}, headers=admin).status_code == 200
    approved = c.get(f"/api/procedure-versions/{draft_id}", headers=TECH).json()
    before_title = approved["steps"][0]["title"]
    got = c.get(f"/api/tutorial/{job['id']}/content", headers=hdr).json()
    r = c.put(f"/api/tutorial/{job['id']}/content",
              json={"steps": [{"title": "Edited after approval", "summary": "New wording.",
                               "start": 0, "end": 8, "objects_used": [1]}],
                    "expected_revision": got["content_revision"]}, headers=hdr)
    assert r.status_code == 200
    r = c.post(f"/api/tutorial/{job['id']}/guide", json={}, headers=hdr).json()
    assert r["ok"] and r["draft_version_id"] != draft_id  # forked, not mutated
    still = c.get(f"/api/procedure-versions/{draft_id}", headers=TECH).json()
    assert still["status"] == "approved" and still["steps"][0]["title"] == before_title


def test_video_scene_plan_validation_versioning_and_files(monkeypatch, tmp_path):
    job = _make_done(monkeypatch)
    hdr = _hdr(job)

    # No versions yet.
    hist = c.get(f"/api/tutorial/{job['id']}/video-guides", headers=hdr).json()
    assert hist["versions"] == []

    # Render without a plan is rejected.
    r = c.post(f"/api/tutorial/{job['id']}/video-guide/render", json={}, headers=hdr)
    assert r.status_code == 422

    # Invalid plans rejected: empty, untitled, inverted, out-of-range.
    for bad in ([], [{"title": "", "audio_start": 0, "audio_end": 2}],
                [{"title": "S", "audio_start": 5, "audio_end": 2}],
                [{"title": "S", "audio_start": 0, "audio_end": 9999}],
                [{"title": "S", "audio_start": 0, "audio_end": 2, "include": False}]):
        r = c.put(f"/api/tutorial/{job['id']}/video-guide/scenes", json={"scenes": bad}, headers=hdr)
        assert r.status_code == 422, bad

    # Fake the render pipeline: real ffmpeg cut of silence + stub Remotion.
    def fake_cut(job_rec, scenes):
        out = vgmod._video_paths(job_rec.id)["voiceover"]
        out.write_bytes(b"RIFF....WAVEfake")
        return out, 2.0

    def fake_render(props_path, paths):
        out = paths["dir"] / "guide-video-render.mp4"
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        return out

    monkeypatch.setattr(vgmod, "cut_voiceover", fake_cut)
    monkeypatch.setattr(vgmod, "_render_video", fake_render)

    r = c.put(f"/api/tutorial/{job['id']}/video-guide/scenes",
              json={"scenes": [{"title": "Show the flag", "caption": "Hold it up.",
                                 "audio_start": 0, "audio_end": 4}]},
              headers=hdr)
    assert r.status_code == 200, r.text

    r = c.post(f"/api/tutorial/{job['id']}/video-guide/render", json={}, headers=hdr).json()
    assert r["ok"], r
    vgid1 = r["video_guide"]["id"]

    end = time.time() + 15.0
    while time.time() < end:
        st = c.get(f"/api/tutorial/{job['id']}/video-guide", headers=hdr).json()
        if st["status"] == "ready":
            break
        time.sleep(0.2)
    assert st["status"] == "ready", st

    # Second edited plan renders a NEW version; the first MP4 stays available.
    r = c.put(f"/api/tutorial/{job['id']}/video-guide/scenes",
              json={"scenes": [{"title": "Show the flag, tighter",
                                 "caption": "Hold it higher.", "audio_start": 1, "audio_end": 5}]},
              headers=hdr)
    assert r.status_code == 200
    r = c.post(f"/api/tutorial/{job['id']}/video-guide/render", json={}, headers=hdr).json()
    assert r["ok"]
    vgid2 = r["video_guide"]["id"]
    assert vgid2 != vgid1

    end = time.time() + 15.0
    while time.time() < end:
        hist = c.get(f"/api/tutorial/{job['id']}/video-guides", headers=hdr).json()
        ready = [v for v in hist["versions"] if v["status"] == "ready"]
        if len(ready) >= 2:
            break
        time.sleep(0.2)
    hist = c.get(f"/api/tutorial/{job['id']}/video-guides", headers=hdr).json()
    vers = [v for v in hist["versions"] if v["status"] == "ready"]
    assert len(vers) >= 2, hist
    assert [v["version_number"] for v in vers] == sorted(v["version_number"] for v in vers)
    assert vers[0]["id"] == vgid1  # first version preserved, not overwritten

    f1 = c.get(f"/api/tutorial/{job['id']}/video-guides/{vgid1}/file?token={job['access_token']}")
    assert f1.status_code == 200 and f1.headers["content-type"] == "video/mp4"
    f2 = c.get(f"/api/tutorial/{job['id']}/video-guides/{vgid2}/file?token={job['access_token']}")
    assert f2.status_code == 200
    # Unknown version id is a 404, not a 500.
    assert c.get(f"/api/tutorial/{job['id']}/video-guides/nope/file?token={job['access_token']}").status_code == 404
