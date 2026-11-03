"""Beat/narration harmony: on-screen text must follow the voiceover.

Each narrative beat's body is the transcript actually overlapping that
beat's own time window — never a positional pick from a list, never a
repeat of the previous beat when alternatives exist, never empty.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from app import videoguide as vgmod  # noqa: E402

FPS = vgmod.VIDEO_FPS


def _scene(**kw):
    base = {"step": 1, "step_number": 1, "title": "Do the thing",
            "caption": "Do the thing carefully.",
            "audio_start": 0.0, "audio_end": 4.0, "objects_used": []}
    base.update(kw)
    return base


def test_beat_bodies_follow_their_own_time_window():
    # Scene 0-8s (240 frames -> long: hero/detail/caption/verify).
    # Segment A lives in the first half, B in the second half.
    scene = _scene(audio_end=8.0)
    segments = [{"text": "first half narration", "start": 0.5, "end": 3.0},
                {"text": "second half narration", "start": 5.0, "end": 7.5}]
    beats = vgmod.plan_visual_beats(scene, segments, 240, 45)
    assert [b["kind"] for b in beats] == ["hero", "detail", "caption", "verify"]
    assert beats[0]["body"] == "first half narration"
    # Detail beat window [2.4, 4.8): A is still being spoken -> A again.
    assert beats[1]["body"] == "first half narration"
    # Caption beat window [4.8, 6.8): only B overlaps.
    assert beats[2]["body"] == "second half narration"
    total = sum(b["durationFrames"] for b in beats)
    assert total == 240
    for prev, nxt in zip(beats, beats[1:]):
        assert nxt["startFrame"] == prev["startFrame"] + prev["durationFrames"]


def test_no_consecutive_duplicate_bodies():
    # One segment, long scene, full guide content: every beat differs.
    scene = _scene(audio_end=20.0, expected_result="Bench clear and level.",
                   required_tools=["Bowl", "Scale"])
    segments = [{"text": "only line spoken", "start": 1.0, "end": 3.0}]
    beats = vgmod.plan_visual_beats(scene, segments, 600, 45)
    assert len(beats) == 4
    bodies = [b["body"] for b in beats]
    assert all(bodies), "no beat may be empty"
    assert bodies[0] == "only line spoken"
    for prev, cur in zip(bodies, bodies[1:]):
        assert cur != prev, f"consecutive beats repeat: {cur!r}"


def test_degenerate_scene_never_empty():
    # No narration, no caption, no expected, no tools: beats still render
    # something (a recap) rather than an empty panel.
    scene = _scene(audio_end=10.0, title="Silent step", caption="",
                   expected_result="", required_tools=[])
    beats = vgmod.plan_visual_beats(scene, [], 300, 45)
    assert len(beats) == 4
    assert all(b["body"] for b in beats)


def test_silent_scene_falls_back_without_empties():
    scene = _scene(audio_end=10.0, caption="Look closely at the seal.",
                   expected_result="Seal face clean.",
                   required_tools=["Mirror", "Cloth"])
    beats = vgmod.plan_visual_beats(scene, [], 300, 45)
    assert len(beats) == 4
    assert all(b["body"] for b in beats)
    assert any("Seal face clean" in b["body"] for b in beats)


def test_verify_beat_prefers_expected_result_and_tools():
    scene = _scene(audio_end=12.0, expected_result="Fitting seated, no play.",
                   required_tools=["Wrench", "Cloth"])
    segments = [{"text": "turn it now", "start": 0.0, "end": 2.0}]
    beats = vgmod.plan_visual_beats(scene, segments, 360, 45)
    verify = [b for b in beats if b["kind"] == "verify"]
    assert len(verify) == 1
    assert "Fitting seated" in verify[0]["body"]


def test_short_scene_two_beats_contiguous():
    scene = _scene(audio_end=4.0)
    segments = [{"text": "gather the bowl", "start": 0.0, "end": 4.0}]
    beats = vgmod.plan_visual_beats(scene, segments, 132, 45)
    assert [b["kind"] for b in beats] == ["hero", "detail"]
    assert sum(b["durationFrames"] for b in beats) == 132
    assert beats[0]["body"] == "gather the bowl"
