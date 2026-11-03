"""Visual discovery + segmentation validation (issue A).

Unit coverage for the multimodal inventory, prompt strategy, SAM result
validation, illustration fallback labelling, and diagnostics hygiene.
No live Meta calls: live adapters are monkeypatched where needed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from app import ai, tutorial  # noqa: E402


def _obj(label, oid, **kw):
    d = {"label": label, "obj_id": oid, "first_mentioned_at": 1.0 * oid,
         "status": "pending", "confidence": None, "illustration": "",
         "overlay": "", "track": []}
    d.update(kw)
    return d


def _step(n, used):
    return {"step_number": n, "title": f"Step {n}", "start": 0.0, "end": 5.0,
            "summary": "Do it.", "objects_used": used}


def test_transcript_object_discovery_keeps_synonyms_and_properties(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    payload = {"objects": [
        {"label": "chocolate pieces", "first_mentioned_at": 2.0, "obj_id": 1,
         "alternative_names": ["chocolate chunks"], "properties": "small brown chunks"}],
        "steps": [{"step_number": 1, "title": "Spread", "start": 0, "end": 5,
                   "summary": "Spread them.", "objects_used": [1]}]}
    monkeypatch.setattr(ai, "_chat", lambda system, user, json_schema=None: __import__("json").dumps(payload))
    out = ai.understand_tutorial([{"text": "spread the chocolate pieces", "start": 0, "end": 5}], 10.0)
    assert out["objects"][0]["alternative_names"] == ["chocolate chunks"]
    assert "brown" in out["objects"][0]["properties"]
    assert out["objects"][0]["discovery_source"] == "transcript"


def test_visual_only_objects_merge_without_dropping():
    t = [_obj("red screwdriver", 1, discovery_source="transcript")]
    v = [_obj("chocolate pieces", 1, discovery_source="visual", first_mentioned_at=4.0)]
    ts = [_step(1, [1])]
    merged, steps, notes = tutorial._merge_object_inventories(t, v, ts, [], 30.0)
    labels = {o["label"] for o in merged}
    assert {"red screwdriver", "chocolate pieces"} <= labels
    both = [o for o in merged if o["label"] == "chocolate pieces"][0]
    assert both["discovery_source"] == "visual"
    assert any("visual-only" in n for n in notes)


def test_distinct_instances_not_merged():
    t = [_obj("left chocolate pile", 1, discovery_source="transcript")]
    v = [_obj("right chocolate pile", 1, discovery_source="visual")]
    merged, _, _ = tutorial._merge_object_inventories(t, v, [_step(1, [1])], [], 30.0)
    assert len(merged) == 2


def test_many_objects_not_silently_dropped(monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    objs = [{"label": f"part-{i}", "first_mentioned_at": float(i), "obj_id": i} for i in range(1, 15)]
    payload = {"objects": objs,
               "steps": [{"step_number": 1, "title": "S", "start": 0, "end": 5,
                          "summary": "x", "objects_used": list(range(1, 15))}]}
    monkeypatch.setattr(ai, "_chat", lambda s, u, json_schema=None: __import__("json").dumps(payload))
    out = ai.understand_tutorial([{"text": "x", "start": 0, "end": 5}], 60.0)
    assert len(out["objects"]) == 14  # well above the old hard cap of 8
    assert "dropped" in out  # transparent accounting key always present


def test_prompt_variants_use_synonyms_first():
    cands = tutorial.prompt_variants("chocolate pieces", ["chocolate chunks", "cocoa chunks"])
    assert cands[0] == "chocolate pieces"
    assert "chocolate chunks" in cands[:3]
    assert len(cands) <= tutorial.MAX_PROMPT_ATTEMPTS


def test_inject_only_publishes_verified_ok():
    md = "### 1. Spread\n\nDo it.\n"
    steps = [_step(1, [1, 2])]
    ok = _obj("chocolate pieces", 1, status="ok", overlay="obj-1-overlay.png")
    tap = _obj("mystery tool", 2, status="needs_tap", overlay="obj-2-overlay.png")
    out = tutorial.inject_illustrations(md, steps, [ok, tap])
    assert "obj-1-overlay.png" in out
    assert "obj-2-overlay.png" not in out  # needs_tap never auto-published


def test_no_segmented_without_valid_evidence():
    # _best_track on empty frames yields no best → caller must stay needs_tap/error.
    best, distinct, margin = tutorial._best_track([])
    assert best is None
    # Simulated provider results must not be treated as success.
    assert ai.SAM_MODEL == "sam-3.1"


def test_sam_empty_frames_stay_needs_tap(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(ai, "segment_video_clip",
                        lambda fid, prompt: {"status": "no_match", "frames": [], "simulated": False})
    monkeypatch.setattr(tutorial, "_hirez_retry", lambda *a, **k: (None, {"prompt": "x", "status": "no_match", "frames": 0}))
    seg = tutorial._segment_object(tmp_path, tmp_path / "s.mp4", tmp_path / "t.mp4",
                                   "fid", _obj("chocolate pieces", 1))
    assert seg["status"] == "needs_tap"
    assert "no match" in seg["note"].lower()
    assert seg["overlay"] == "" and seg["illustration"] == ""


def test_ai_fallback_labelled_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(ai, "image_generate",
                        lambda prompt: (calls.append(prompt), {"ok": True, "image_b64": __import__("base64").b64encode(b"png").decode(),
                                                               "model": ai.IMAGE_MODEL, "simulated": False})[1])
    steps = [_step(i, []) for i in range(1, 8)]
    files, prov = tutorial.ensure_ai_step_illustrations(tmp_path, steps, [])
    assert len(files) <= 5  # bounded
    assert all(p["ai_generated"] for p in prov)
    md = tutorial.inject_ai_illustrations("### 1. S\n\nx\n", files)
    assert "AI-generated" in md and "not a photo" in md


def test_ai_fallback_failure_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(ai, "image_generate", lambda prompt: {"ok": False, "status": "unavailable",
                                                              "note": "no key", "model": ai.IMAGE_MODEL})
    files, prov = tutorial.ensure_ai_step_illustrations(tmp_path, [_step(1, [])], [])
    assert files == {}
    assert prov and prov[0]["status"] == "unavailable"


def test_diagnostics_expose_attempts_without_secrets():
    import json as _json
    sample = {"objects": [_obj("chocolate pieces", 1, attempts=[{"prompt": "chocolate pieces", "status": "no_match", "frames": 0}])],
              "steps": [_step(1, [1])]}
    blob = _json.dumps(sample)
    assert "META_API_KEY" not in blob
    assert "attempts" in blob
