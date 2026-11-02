"""Audio-cut regression tests: the voiceover must survive, be measured,
or degrade to silent video — never vanish into a bare exception.

Covers the historic `job_dir` NameError (successful concat returned
(None, 0.0)) plus missing-audio and over-limit handling.
"""
import os
import sys
import time
import uuid
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import tutorial, videoguide as vgmod  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _av_fixture(path, duration=6.0):
    import subprocess
    r = subprocess.run(
        [tutorial._ffmpeg(), "-y",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
         "-pix_fmt", "yuv420p", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)],
        capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


def _wav_seconds(path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def _job_with_source(suffix, duration=6.0):
    """A done TutorialJob whose storage key points at a real A/V file."""
    from app.db import SessionLocal
    from app import models as M
    from app import storage as _storage
    jid = f"audio-{suffix}-{uuid.uuid4().hex[:8]}"
    d = _storage.media_root() / "tutorials" / jid
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "build.mp4"
    _av_fixture(tmp, duration)
    (d / "source.mp4").write_bytes(tmp.read_bytes())
    tmp.unlink()
    db = SessionLocal()
    try:
        db.add(M.TutorialJob(id=jid, title="Audio cut", actor="tech-1",
                             access_token=uuid.uuid4().hex,
                             video_storage_key=f"data/tutorials/{jid}/source.mp4",
                             status="done", duration_sec=duration))
        db.commit()
        return jid
    finally:
        db.close()


def test_cut_voiceover_returns_measured_wav():
    """The historic bug: successful concat hit NameError and returned silence."""
    from app.db import SessionLocal
    from app import models as M
    jid = _job_with_source("measured")
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, jid)
        out, secs = vgmod.cut_voiceover(job, [
            {"audio_start": 0.0, "audio_end": 2.0},
            {"audio_start": 2.0, "audio_end": 4.0},
        ], db=db, actor="tech-1")
        assert out is not None and out.is_file(), "voiceover WAV must survive a successful concat"
        measured = _wav_seconds(out)
        assert secs == pytest.approx(measured, abs=0.05), "reported duration must be measured, not estimated"
        # 4s of slices + 2x0.4s tails ≈ 4.8s.
        assert 4.5 <= measured <= 5.2, measured
    finally:
        db.close()


def test_cut_voiceover_missing_source_is_silent():
    from app.db import SessionLocal
    from app import models as M
    db = SessionLocal()
    try:
        jid = f"ghost-{uuid.uuid4().hex[:8]}"
        db.add(M.TutorialJob(id=jid, title="Ghost", actor="tech-1",
                             access_token=uuid.uuid4().hex,
                             video_storage_key=f"data/tutorials/{jid}/source.mp4",
                             status="done", duration_sec=10.0))
        db.commit()
    finally:
        db.close()
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, jid)
        out, secs = vgmod.cut_voiceover(job, [{"audio_start": 0.0, "audio_end": 2.0}],
                                          db=db, actor="tech-1")
        assert (out, secs) == (None, 0.0)
    finally:
        db.close()


def test_cut_voiceover_no_ranges_is_silent():
    from app.db import SessionLocal
    from app import models as M
    jid = _job_with_source("norange")
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, jid)
        out, secs = vgmod.cut_voiceover(job, [], db=db, actor="tech-1")
        assert (out, secs) == (None, 0.0)
    finally:
        db.close()


def test_validate_mp4_rejects_garbage_and_accepts_real(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    with pytest.raises(RuntimeError):
        vgmod._validate_mp4(bad)
    with pytest.raises(RuntimeError):
        vgmod._validate_mp4(tmp_path / "missing.mp4")
    good = tmp_path / "good.mp4"
    _av_fixture(good, duration=2.0)
    checked = vgmod._validate_mp4(good)
    assert "video" in checked["streams"]
    assert checked["duration_sec"] > 0
    assert checked["bytes"] > 0


def test_over_limit_duration_refused_before_any_row(tmp_path):
    """The duration cap fires with a 422 before any VideoGuide row exists."""
    from app.db import SessionLocal
    from app import models as M
    jid = _job_with_source("toolong", duration=6.0)
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, jid)
        job.duration_sec = float(vgmod.MAX_VIDEO_GUIDE_SEC) + 60.0
        db.commit()
    finally:
        db.close()
    before = db_count_guides(jid)
    with pytest.raises(ValueError, match="support up to"):
        vgmod.start_video_guide(jid, actor="tech-1")
    assert db_count_guides(jid) == before, "refused generation must not create a row"


def db_count_guides(job_id: str) -> int:
    from sqlalchemy import select, func
    from app.db import SessionLocal
    from app import models as M
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(M.VideoGuide).where(
            M.VideoGuide.tutorial_id == job_id)) or 0
    finally:
        db.close()
