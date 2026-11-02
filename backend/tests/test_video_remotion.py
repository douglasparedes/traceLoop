"""Actual Remotion integration: render ProcedureVideo end to end.

No mocks of the renderer. Builds a minimal composition (title + one
scene + real voiceover WAV + real step image), runs video/render.mjs,
and validates the MP4 the same way the worker does. Slow (minutes):
skipped automatically when Node.js is unavailable.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

import pytest  # noqa: E402

NODE = shutil.which("node") or shutil.which("node.exe")

needs_node = pytest.mark.skipif(not NODE, reason="Node.js not on PATH")


def _ffmpeg():
    from app import tutorial
    return tutorial._ffmpeg()


def _make_wav(path, duration=2.0):
    r = subprocess.run([_ffmpeg(), "-y", "-f", "lavfi",
                        "-i", f"sine=frequency=440:duration={duration}",
                        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(path)],
                       capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


def _make_png(path):
    r = subprocess.run([_ffmpeg(), "-y", "-f", "lavfi",
                        "-i", "testsrc=size=640x360:rate=1:duration=1",
                        "-frames:v", "1", str(path)],
                       capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]


@needs_node
def test_real_remotion_render_with_voiceover(tmp_path):
    """Full SSR render incl. the title-offset voiceover Sequence.

    Asserts: valid MP4, video stream, positive duration, and an audio
    stream — i.e. the voiceover actually made it into the render.
    """
    from app import videoguide as vgmod
    work = tmp_path / "render"
    work.mkdir()
    wav = work / "voiceover.wav"
    img = work / "step.png"
    _make_wav(wav)
    _make_png(img)
    props = {
        "title": "Remotion integration check",
        "fps": 30, "width": 1280, "height": 720,
        "voiceover": str(wav), "voiceoverFrames": 60,
        "scenes": [{"step": 1, "title": "Check", "caption": "Caption check",
                    "image": str(img), "startFrame": 45, "durationFrames": 60}],
        "totalFrames": 120,
    }
    props_path = work / "props.json"
    props_path.write_text(json.dumps(props), encoding="utf-8")
    paths = {"dir": work, "voiceover": wav, "props": props_path,
             "progress": work / "progress.json",
             "output": work / "guide-video-render.mp4"}
    out = vgmod._render_video(props_path, paths)
    assert out is not None and out.exists(), "Remotion must produce a file"
    checked = vgmod._validate_mp4(out)
    assert "video" in checked["streams"]
    assert "audio" in checked["streams"], "voiceover WAV must be audible in the render"
    assert checked["duration_sec"] > 0
    assert checked["bytes"] > 0
    assert checked.get("codec", "").startswith("h264")


@needs_node
def test_real_remotion_render_silent(tmp_path):
    """Silent tutorials render a valid voiceless MP4 (no empty audio stream)."""
    from app import videoguide as vgmod
    work = tmp_path / "render-silent"
    work.mkdir()
    props = {
        "title": "Silent check",
        "fps": 30, "width": 1280, "height": 720,
        "voiceover": None, "voiceoverFrames": 0,
        "scenes": [{"step": 1, "title": "Quiet step", "caption": "Follow the caption",
                    "image": None, "startFrame": 45, "durationFrames": 60}],
        "totalFrames": 120,
    }
    props_path = work / "props.json"
    props_path.write_text(json.dumps(props), encoding="utf-8")
    paths = {"dir": work, "voiceover": work / "voiceover.wav", "props": props_path,
             "progress": work / "progress.json",
             "output": work / "guide-video-render.mp4"}
    out = vgmod._render_video(props_path, paths)
    assert out is not None and out.exists()
    checked = vgmod._validate_mp4(out)
    assert "video" in checked["streams"]
    assert "audio" not in checked["streams"]
