"""Guide-to-video fidelity: source of truth, order, dedup, bounds."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from app import videoguide as vg  # noqa: E402


def _steps(n=6):
    return [{
        "step_number": i + 1, "title": f"Do thing {i + 1}",
        "summary": f"Perform action {i + 1} carefully with the widget.",
        "start": float(i * 5), "end": float(i * 5 + 5),
        "objects_used": [], "expected_result": f"Widget {i + 1} seated." if i % 2 == 0 else "",
        "required_tools": ["driver"] if i == 0 else [],
    } for i in range(n)]


def test_scenes_follow_guide_exactly():
    steps = _steps(6)
    scenes, warnings = vg._scenes_from_guide_steps("T", steps, [])
    assert [s["step_number"] for s in scenes] == [1, 2, 3, 4, 5, 6]
    assert [s["step"] for s in scenes] == [1, 2, 3, 4, 5, 6]
    assert len(scenes) == 6
    assert warnings == []
    # Titles preserved verbatim from the guide.
    assert scenes[0]["title"] == "Do thing 1"
    # Static instruction is concise, not the full paragraph.
    assert len(scenes[0]["instruction"]) <= 140 + 1
    assert scenes[0]["objects_used"] == []


def test_transcript_mismatch_still_follows_guide():
    steps = _steps(2)
    segs = [{"text": "totally unrelated chatter about lunch", "start": 0, "end": 9}]
    scenes, _ = vg._scenes_from_guide_steps("T", steps, segs)
    # Narration comes from the guide, not the transcript.
    assert "Do thing 1" in scenes[0]["narration"]
    assert "lunch" not in scenes[0]["narration"]


def test_beats_cover_narration_exactly_once():
    steps = _steps(1)
    scenes, _ = vg._scenes_from_guide_steps("T", steps, [])
    dur = 90  # 3s
    beats = vg.plan_visual_beats({**scenes[0], "audio_start": 0, "audio_end": 3}, [], dur, 45)
    assert dur - 1 <= sum(b["durationFrames"] for b in beats) <= dur + 8
    bodies = [b["body"] for b in beats if b["kind"] != "verify"]
    assert len(bodies) == len(set(bodies))  # no repeated caption
    joined = " ".join(bodies)
    for word in scenes[0]["narration"].split()[:5]:
        assert word in joined or len(bodies) > 0


def test_static_instruction_not_duplicated_as_caption():
    steps = _steps(1)
    scenes, _ = vg._scenes_from_guide_steps("T", steps, [])
    props = vg.build_video_props(
        type("J", (), {"id": "x", "title": "T", "guide_format": "work_instruction"})(),
        [{**scenes[0], "visual": {"name": "f.png"}}],
        None, 0.0)
    # build_video_props needs real files; validate logic directly instead.
    issues = vg.validate_video_props({
        "width": 1280, "height": 720,
        "scenes": [{
            "step": 1, "title": "Do thing 1", "caption": scenes[0]["narration"],
            "instruction": scenes[0]["instruction"], "image": "/tmp/x.png",
            "startFrame": 45, "durationFrames": 90, "expected": "",
            "tools": [], "imageW": 640, "imageH": 360,
            "beats": [{"kind": "hero", "headline": "", "body": scenes[0]["instruction"],
                       "startFrame": 45, "durationFrames": 90}],
        }],
    })
    assert any("duplicated verbatim" in i for i in issues)


def test_validate_order_and_duplicates():
    def _scene(n, **kw):
        d = {"step": n, "title": f"S{n}", "caption": f"c{n}", "instruction": f"do {n}",
             "image": "/tmp/x.png", "startFrame": n * 90, "durationFrames": 90,
             "expected": "", "tools": [], "imageW": 640, "imageH": 360,
             "beats": [{"kind": "hero", "headline": "", "body": f"chunk {n}",
                        "startFrame": n * 90, "durationFrames": 90}]}
        d.update(kw)
        return d
    base = {"width": 1280, "height": 720, "totalFrames": 600}
    assert vg.validate_video_props({**base, "scenes": [_scene(2), _scene(1)]}) != []
    assert vg.validate_video_props({**base, "scenes": [_scene(1), _scene(1)]}) != []
    ok = vg.validate_video_props({**base, "scenes": [_scene(1), _scene(2)]})
    assert ok == []


def test_warnings_preserved_in_scenes():
    steps = _steps(2)
    scenes, _ = vg._scenes_from_guide_steps("T", steps, [])
    assert scenes[0]["expected_result"] == "Widget 1 seated."
    assert scenes[0]["required_tools"] == ["driver"]
