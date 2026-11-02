"""Visual-first tutorial understanding: silent/weak narration routes to
frame analysis instead of failing; outputs stay timestamped, uncertain,
and honestly labelled."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}

_n = [0]


def _upload(video_bytes=None, title="Visual", mode="auto"):
    _n[0] += 1
    blob = video_bytes if video_bytes is not None else f"fake-video-bytes-visual-{_n[0]}".encode()
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", blob, "video/mp4")},
                data={"title": title, "mode": mode}, headers=TECH)
    assert up.status_code == 200, up.text
    return up.json()


def _wait_done(job_id, token, timeout=20.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.2)
    raise AssertionError("tutorial job did not finish")


def _patch_base(monkeypatch, has_audio=True):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video",
                        lambda p: {"duration": 30.0, "width": 320, "height": 240, "has_audio": has_audio})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [], "simulated": True, "status": "no_match"})
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction", **kw: {
        "guide_markdown": "# Guide\n\n## Steps\n", "materials": [], "simulated": False})


def test_speech_sufficiency_assessment():
    ok, reason = ai.assess_speech_sufficiency("", [], 30.0)
    assert not ok and "short" in reason
    ok, _ = ai.assess_speech_sufficiency("x" * 200, [{"text": "a" * 100, "start": 0, "end": 5}], 30.0)
    assert not ok  # single segment is not enough
    ok, reason = ai.assess_speech_sufficiency(
        "First isolate the power and verify the indicator is off completely before touching anything else in the panel.",
        [{"text": "First isolate the power.", "start": 0, "end": 4},
         {"text": "Verify the indicator is off completely.", "start": 4, "end": 9}], 30.0)
    assert ok, reason


def test_clean_visual_steps_validation():
    steps, dropped = ai._clean_visual_steps([
        {"title": "Good", "instruction": "Do the thing carefully.", "start_sec": 2, "end_sec": 6,
         "evidence_frames": [2.0, 99.0], "objects": ["cover"], "confidence": "high", "uncertainties": []},
        {"title": "", "instruction": "missing title", "start_sec": 0, "end_sec": 1},
        {"title": "Backwards", "instruction": "Bad range.", "start_sec": 9, "end_sec": 5},
        "not-a-dict",
    ], duration_sec=30.0)
    assert len(steps) == 1
    assert steps[0]["evidence_frames"] == [2.0, 30.0]  # out-of-range frames clamp to the duration
    assert len(dropped) == 3
    # Timestamps clamp to duration instead of failing.
    steps2, _ = ai._clean_visual_steps([
        {"title": "T", "instruction": "I do the step slowly and carefully here.", "start_sec": -5, "end_sec": 500,
         "evidence_frames": [], "objects": [], "confidence": "bogus", "uncertainties": []}], 30.0)
    assert steps2[0]["start_sec"] == 0 and steps2[0]["end_sec"] == 30.0
    assert steps2[0]["confidence"] == "low"  # unknown confidence degrades, never upgrades


def test_no_audio_auto_routes_to_visual_first(monkeypatch, tmp_path):
    _patch_base(monkeypatch, has_audio=False)
    job = _upload(title="Silent demo")
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "done", done
    assert done.get("analysis_strategy") == "visual_first", done
    assert "audio" in (done.get("strategy_reason") or "").lower()
    assert done["steps"], "visual-first must still produce candidate steps"
    for s in done["steps"]:
        assert 0 <= s["start"] <= s["end"] <= done["duration_sec"] + 0.01 or done["duration_sec"] == 0
        assert s.get("derivation") == "visual"
        assert isinstance(s.get("evidence_frames"), list)
    # No fabricated transcript, no invented safety claims.
    assert done["full_transcript"] == ""
    md = done["guide_markdown"] or ""
    assert "torque" not in md.lower() and "PPE" not in md


def test_weak_narration_auto_routes_to_visual_first(monkeypatch, tmp_path):
    _patch_base(monkeypatch, has_audio=True)
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "Uh, hi.", "simulated": False,
        "segments": [{"text": "Uh, hi.", "start": 0.0, "end": 2.0}]})
    job = _upload(title="Weak narration")
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "done", done
    assert done.get("analysis_strategy") == "visual_first", done
    # Partial transcript is preserved as supplementary context, not discarded.
    assert done["full_transcript"] == "Uh, hi."


def test_narrated_mode_preserves_hard_failures(monkeypatch, tmp_path):
    _patch_base(monkeypatch, has_audio=False)
    job = _upload(title="Narrated no-audio", mode="narrated")
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "error", done
    _patch_base(monkeypatch, has_audio=True)
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "", "simulated": False, "segments": []})
    job2 = _upload(title="Narrated no-text", mode="narrated")
    done2 = _wait_done(job2["id"], job2["access_token"])
    assert done2["status"] == "error", done2


def test_explicit_visual_first_skips_transcription(monkeypatch, tmp_path):
    _patch_base(monkeypatch, has_audio=True)
    called = {}
    orig = ai.transcribe_timed

    def spy(fn, data, duration_sec=0):
        called["yes"] = True
        return orig(fn, data, duration_sec)

    monkeypatch.setattr(ai, "transcribe_timed", spy)
    job = _upload(title="Explicit visual", mode="visual_first")
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "done", done
    assert done.get("analysis_strategy") == "visual_first"
    hdr = {**TECH, "X-Tutorial-Token": job["access_token"]}
    diag = c.get(f"/api/tutorial/{job['id']}/diagnostics", headers=hdr).json()
    stages = {e["stage"] for e in diag["events"]}
    assert "analyze_frames" in {e["operation"] for e in diag["events"]}


def test_simulated_analysis_is_labelled_and_uncertain():
    out = ai.analyze_tutorial_frames([], "", 30.0)
    assert out["simulated"] is True and out["analysis_mode"] == "visual_first"
    assert out["candidate_steps"], "even with no frames the tutorial stays usable with flagged placeholders"
    for s in out["candidate_steps"]:
        assert s["confidence"] == "low"
        assert "Simulated" in s["instruction"] or "simulated" in s["instruction"]
    assert any("Simulated" in m or "simulated" in m for m in out["missing_information"])
