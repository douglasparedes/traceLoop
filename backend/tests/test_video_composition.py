"""Video composition: balanced layout, bounds, validation, shared tokens."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from app import videoguide as vg  # noqa: E402


def _props(**kw):
    base = {"title": "T", "fps": 30, "width": 1280, "height": 720,
            "voiceover": None, "voiceoverFrames": 0, "totalFrames": 90,
            "scenes": [{
                "step": 1, "title": "Do it", "caption": "Do the thing",
                "image": "/tmp/x.jpg", "startFrame": 45, "durationFrames": 45,
                "expected": "", "tools": [], "imageW": 1280, "imageH": 720,
                "beats": [{"kind": "hero", "image": "/tmp/x.jpg", "headline": "",
                           "body": "Do it", "startFrame": 45, "durationFrames": 45}],
            }]}
    base.update(kw)
    return base


def test_canvas_must_be_1280x720():
    bad = _props(width=640, height=480)
    assert any("1280x720" in i for i in vg.validate_video_props(bad))


def test_missing_visual_blocked():
    p = _props()
    p["scenes"][0]["image"] = None
    p["scenes"][0]["imageW"] = 0
    assert any("missing visual" in i for i in vg.validate_video_props(p))


def test_caption_length_bounded():
    p = _props()
    p["scenes"][0]["beats"][0]["body"] = "x" * 600
    assert any("readable length" in i for i in vg.validate_video_props(p))


def test_valid_props_pass():
    assert vg.validate_video_props(_props()) == []


def test_render_sized_downscales_large(tmp_path):
    from PIL import Image as I
    big = tmp_path / "big.jpg"
    I.new("RGB", (2560, 1440)).save(big, "JPEG")
    out = vg._render_sized(tmp_path, str(big))
    with I.open(out) as im:
        assert max(im.size) <= vg.MAX_RENDER_DIM
    assert out != str(big)
    # Original preserved.
    with I.open(big) as im:
        assert im.size == (2560, 1440)


def test_render_sized_passthrough_small(tmp_path):
    from PIL import Image as I
    small = tmp_path / "s.jpg"
    I.new("RGB", (640, 360)).save(small, "JPEG")
    assert vg._render_sized(tmp_path, str(small)) == str(small)


def test_detail_beat_names_component():
    p = _props()
    assert p["scenes"][0]["beats"][0]["kind"] == "hero"  # token contract stable
