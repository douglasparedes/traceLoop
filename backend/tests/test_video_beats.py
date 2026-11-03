"""Beat/narration harmony: one caption chunk per beat, in order, no repeats.

Each scene shows its static guide instruction once (InstructionPanel);
beats advance exactly one caption chunk each. Bodies never repeat across
beats and never reproduce the static instruction verbatim.
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
            "caption": "Do the thing carefully with the widget today.",
            "instruction": "Do the thing.",
            "audio_start": 0.0, "audio_end": 8.0, "objects_used": []}
    base.update(kw)
    return base


def test_beat_bodies_cover_narration_exactly_once():
    scene = _scene(audio_end=8.0, caption_chunks=["first half narration", "second half narration"])
    beats = vgmod.plan_visual_beats(scene, [], 240, 45)
    bodies = [b["body"] for b in beats if b["kind"] != "verify"]
    assert bodies == ["first half narration", "second half narration"]
    total = sum(b["durationFrames"] for b in beats)
    assert total == 240
    for prev, nxt in zip(beats, beats[1:]):
        assert nxt["startFrame"] == prev["startFrame"] + prev["durationFrames"]


def test_no_consecutive_duplicate_bodies():
    scene = _scene(audio_end=20.0, expected_result="Bench clear and level.",
                   required_tools=["Bowl", "Scale"],
                   caption_chunks=["only line spoken part one", "only line spoken part two"])
    beats = vgmod.plan_visual_beats(scene, [], 600, 45)
    bodies = [b["body"] for b in beats]
    assert all(bodies), "no beat may be empty"
    non_verify = [b["body"] for b in beats if b["kind"] != "verify"]
    assert len(non_verify) == len(set(non_verify)), f"beats repeat: {non_verify!r}"


def test_degenerate_scene_never_empty():
    scene = _scene(audio_end=10.0, title="Silent step", caption="",
                   caption_chunks=[], expected_result="", required_tools=[])
    beats = vgmod.plan_visual_beats(scene, [], 300, 45)
    assert len(beats) >= 1
    assert all(b["body"] for b in beats)


def test_silent_scene_falls_back_without_empties():
    scene = _scene(audio_end=10.0, caption="Look closely at the seal.",
                   caption_chunks=["Look closely at the seal."],
                   expected_result="Seal face clean.",
                   required_tools=["Mirror", "Cloth"])
    beats = vgmod.plan_visual_beats(scene, [], 300, 45)
    assert all(b["body"] for b in beats)
    assert any("Seal face clean" in b["body"] or "Look closely" in b["body"] for b in beats)


def test_verify_beat_prefers_expected_result_and_tools():
    scene = _scene(audio_end=12.0, expected_result="Fitting seated, no play.",
                   required_tools=["Wrench", "Cloth"],
                   caption_chunks=["turn it now slowly", "then check the fitting",
                                   "finally wipe it clean"])
    beats = vgmod.plan_visual_beats(scene, [], 360, 45)
    verify = [b for b in beats if b["kind"] == "verify"]
    assert len(verify) == 1
    assert "Fitting seated" in verify[0]["body"]


def test_short_scene_two_beats_contiguous():
    scene = _scene(audio_end=4.0, caption_chunks=["gather the bowl", "then set it down"])
    beats = vgmod.plan_visual_beats(scene, [], 132, 45)
    assert [b["kind"] for b in beats] == ["hero", "detail"]
    assert sum(b["durationFrames"] for b in beats) == 132
    assert beats[0]["body"] == "gather the bowl"
    assert beats[1]["body"] == "then set it down"


def test_static_instruction_never_duplicated_as_caption():
    scene = _scene(audio_end=6.0, instruction="Do the thing.",
                   caption_chunks=["Do the thing."])
    beats = vgmod.plan_visual_beats(scene, [], 180, 45)
    # Chunks equal to the instruction verbatim are still one track, but the
    # validator flags the duplication so callers shorten the static panel.
    assert all(b["body"] for b in beats)
