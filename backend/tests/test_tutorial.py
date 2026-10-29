import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient

from app import ai, tutorial
from app.main import app

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _fake_illustrations(job_dir, source, obj, best):
    for _n in ("obj-1.png", "obj-1-overlay.png"):
        (job_dir / _n).write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    return {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"}


def _patch_pipeline(monkeypatch):
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "This is my flag. Hold it up.", "simulated": False,
        "segments": [{"text": "This is my flag.", "start": 1.0, "end": 4.0}, {"text": "Hold it up.", "start": 4.0, "end": 8.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending", "confidence": None, "illustration": "", "overlay": "", "track": []}],
        "steps": [{"step_number": 1, "title": "Show the flag", "start": 0.0, "end": 8.0, "summary": "Hold the flag up.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "bbox_px": [96, 72, 192, 144],
                                             "image_size": [320, 240], "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    monkeypatch.setattr(tutorial, "make_illustrations", _fake_illustrations)
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


def test_tutorial_pipeline_end_to_end(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    up = c.post("/api/tutorial/start", files={"file": ("tut.mp4", b"fake-video-bytes", "video/mp4")},
                data={"title": "Flag tutorial"}, headers=TECH)
    assert up.status_code == 200
    job = up.json()
    assert job["access_token"]
    # Detail requires the token.
    assert c.get(f"/api/tutorial/{job['id']}", headers=TECH).status_code == 403
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "done", done
    assert done["progress"] == 100
    assert done["objects"][0]["status"] == "ok" and done["objects"][0]["illustration"] == "obj-1.png"
    assert done["steps"][0]["title"] == "Show the flag"
    assert "Show the flag" in done["guide_markdown"]
    assert done["timed_segments"][0]["start"] == 1.0


def test_tutorial_upload_codec_qualified_content_types(monkeypatch):
    _patch_pipeline(monkeypatch)
    up = c.post("/api/tutorial/start",
                files={"file": ("tut.webm", b"codec-qualified-bytes", 'video/webm;codecs="vp8,opus"')},
                data={"title": "Codec test"}, headers=TECH)
    assert up.status_code == 200, up.text
    done = _wait_done(up.json()["id"], up.json()["access_token"])
    assert done["status"] == "done"
    up2 = c.post("/api/tutorial/start",
                 files={"file": ("tut.mp4", b"codec-qualified-mp4", 'video/mp4;codecs="avc1.42E01E,mp4a.40.2"')},
                 headers=TECH)
    assert up2.status_code == 200, up2.text
    assert _wait_done(up2.json()["id"], up2.json()["access_token"])["status"] == "done"


def test_prompt_ladder_falls_back_to_simpler_label(monkeypatch):
    from app import tutorial as tut_mod
    assert tut_mod.prompt_variants("blue adjustment knob") == ["blue adjustment knob", "adjustment knob", "knob"]
    assert tut_mod.prompt_variants("flag") == ["flag"]

    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(tut_mod, "probe_video", lambda p: {"duration": 20.0, "width": 320, "height": 240})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "blue adjustment knob", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending", "confidence": None, "illustration": "", "overlay": "", "track": []}],
        "steps": [{"step_number": 1, "title": "Show it", "start": 0.0, "end": 8.0, "summary": "Show it.", "objects_used": [1]}],
        "simulated": False})

    def fake_segment(file_id, prompt):
        if prompt == "blue adjustment knob":
            return {"frames": [], "simulated": False, "status": "no_match"}
        return {"frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "bbox_px": [96, 72, 192, 144],
                                                     "image_size": [320, 240], "confidence": 0.9, "mask": None}]}],
                "simulated": False, "status": "ok"}
    monkeypatch.setattr(ai, "segment_video_clip", fake_segment)

    up = c.post("/api/tutorial/start", files={"file": ("ladder.mp4", b"ladder-bytes", "video/mp4")}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    obj = done["objects"][0]
    assert obj["status"] == "ok", obj
    assert obj["prompt_used"] == "adjustment knob"
    assert [a["prompt"] for a in obj["attempts"]] == ["blue adjustment knob", "adjustment knob"]
    assert "adjustment knob" in done["guide_markdown"] or "illustrations/obj-1-overlay.png" in done["guide_markdown"]


def test_confidence_band_and_multimatch_need_tap(monkeypatch):
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6], "bbox_px": [96, 72, 192, 144],
                                             "image_size": [320, 240], "confidence": 0.3, "mask": None}]}],
        "simulated": False, "status": "ok"})
    up = c.post("/api/tutorial/start", files={"file": ("band.mp4", b"band-bytes-1", "video/mp4")}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    obj = done["objects"][0]
    assert obj["status"] == "needs_tap", obj
    assert obj["illustration"] == "obj-1.png"  # illustrations still generated for tap review


def test_inject_illustrations_is_idempotent():
    from app.tutorial import inject_illustrations
    md = "# T\n\n## Steps\n\n### 1. Do it (0s-5s)\n\nDo the thing.\n\n### 2. Next (5s-9s)\n\nNext thing.\n"
    steps = [{"step_number": 1, "objects_used": [1]}, {"step_number": 2, "objects_used": []}]
    objects = [{"obj_id": 1, "label": "flag", "overlay": "obj-1-overlay.png", "illustration": "obj-1.png"}]
    once = inject_illustrations(md, steps, objects)
    assert "![flag](illustrations/obj-1-overlay.png)" in once
    assert "![flag](illustrations/obj-1.png)" in once
    assert once.count("illustrations/obj-1-overlay.png") == 1
    assert inject_illustrations(once, steps, objects) == once
    # Objects without files never inject.
    assert inject_illustrations(md, steps, [{"obj_id": 1, "overlay": "", "illustration": ""}]) == md.strip() + "\n"


def test_refresh_guide_and_bundle_zip(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    up = c.post("/api/tutorial/start", files={"file": ("bundle.mp4", b"bundle-bytes-1", "video/mp4")}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done"
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    # Refresh is idempotent and keeps illustrations.
    r = c.post(f"/api/tutorial/{done['id']}/refresh-guide", headers=hdr)
    assert r.status_code == 200 and r.json()["guide_markdown"].count("illustrations/obj-1-overlay.png") == 1
    assert _wait_done(done["id"], done["access_token"])["guide_markdown"].count("illustrations/obj-1-overlay.png") == 1
    # Bundle zip contains the guide plus PNGs.
    z = c.get(f"/api/tutorial/{done['id']}/bundle.zip", params={"token": done["access_token"]})
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    import io as _io
    import zipfile as _zip
    names = _zip.ZipFile(_io.BytesIO(z.content)).namelist()
    assert "guide.md" in names and "illustrations/obj-1-overlay.png" in names
    # Wrong token is rejected.
    assert c.get(f"/api/tutorial/{done['id']}/bundle.zip", params={"token": "nope"}).status_code == 403


def test_tutorial_upload_validation_and_hash_cache(monkeypatch):
    _patch_pipeline(monkeypatch)
    bad = c.post("/api/tutorial/start", files={"file": ("x.txt", b"hi", "text/plain")}, headers=TECH)
    assert bad.status_code == 415
    up1 = c.post("/api/tutorial/start", files={"file": ("tut2.mp4", b"same-bytes-123", "video/mp4")}, headers=TECH).json()
    done = _wait_done(up1["id"], up1["access_token"])
    assert done["status"] == "done"
    up2 = c.post("/api/tutorial/start", files={"file": ("tut2.mp4", b"same-bytes-123", "video/mp4")}, headers=TECH).json()
    assert up2["id"] == up1["id"] and up2.get("cached") is True


def _make_fixture_video(path, with_audio: bool):
    import subprocess
    ff = tutorial._ffmpeg()
    if with_audio:
        cmd = [ff, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=1",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
               "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)]
    else:
        cmd = [ff, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=1",
               "-c:v", "mpeg4", "-an", str(path)]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


def test_probe_detects_audio_presence(tmp_path):
    silent = tmp_path / "silent.mp4"
    toned = tmp_path / "toned.mp4"
    _make_fixture_video(silent, with_audio=False)
    _make_fixture_video(toned, with_audio=True)
    ps, pt = tutorial.probe_video(silent), tutorial.probe_video(toned)
    assert ps["duration"] > 0 and ps["has_audio"] is False
    assert pt["duration"] > 0 and pt["has_audio"] is True


def test_extract_audio_rejects_silent_video(tmp_path):
    import pytest
    silent = tmp_path / "silent.mp4"
    toned = tmp_path / "toned.mp4"
    _make_fixture_video(silent, with_audio=False)
    _make_fixture_video(toned, with_audio=True)
    with pytest.raises(tutorial.NoAudioTrackError, match="no audio track"):
        tutorial.extract_audio_wav(silent, tmp_path / "silent.wav")
    out = tmp_path / "tone.wav"
    tutorial.extract_audio_wav(toned, out)
    assert out.stat().st_size > 0


def test_pipeline_fails_fast_on_silent_video(tmp_path):
    # No pipeline mocks: the real probe finds no audio stream, so the job
    # must fail with an actionable message (retrying can never succeed).
    silent = tmp_path / "silent.mp4"
    _make_fixture_video(silent, with_audio=False)
    up = c.post("/api/tutorial/start", files={"file": ("silent.mp4", silent.read_bytes(), "video/mp4")},
                data={"title": "Silent test"}, headers=TECH)
    assert up.status_code == 200
    job = up.json()
    done = _wait_done(job["id"], job["access_token"])
    assert done["status"] == "error", done
    assert "no audio track" in (done.get("error") or "").lower()
