"""Automatic step visuals: accepted -> source -> Muse Image -> graphic.

Every scene must end with a real visual; empty panels are a defect.
Muse Image is mocked (no network/credits); storage, caching, fallback,
and provenance are all exercised for real.
"""
import base64
import io
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _png_bytes(w=320, h=240, color=(20, 40, 30)):
    from PIL import Image as _Img
    buf = io.BytesIO()
    _Img.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _job(db, jid, **kw):
    from app import models as M
    from app import storage as _storage
    d = _storage.media_root() / "tutorials" / jid
    d.mkdir(parents=True, exist_ok=True)
    job = M.TutorialJob(id=jid, title=kw.get("title", "Visual check"), actor="tech-1",
                        access_token=uuid.uuid4().hex,
                        video_storage_key=f"data/tutorials/{jid}/source.mp4",
                        status="done", duration_sec=kw.get("duration_sec", 30.0),
                        steps=kw.get("steps", []), objects=kw.get("objects", []),
                        timed_segments=kw.get("segments", []),
                        keyframes=kw.get("keyframes", []),
                        guide_markdown=kw.get("guide_markdown", "# G\n\nDo it.\n"),
                        guide_format=kw.get("guide_format", "work_instruction"),
                        content_revision=kw.get("content_revision", 1))
    db.add(job)
    db.commit()
    return job


def _steps():
    return [
        {"step_number": 1, "title": "Gather the baking tools",
         "start": 0.0, "end": 6.0, "summary": "Gather bowl, scale and tray.",
         "objects_used": [1], "expected_result": "Tools on the bench.",
         "required_tools": ["Bowl", "Scale"]},
        {"step_number": 2, "title": "Inspect the pump seal",
         "start": 6.0, "end": 20.0, "summary": "Look at the seal face.",
         "objects_used": [], "expected_result": "Seal face clean."},
    ]


def test_accepted_visual_is_reused_for_matching_step():
    from app.db import SessionLocal
    from app import models as M
    from app import videoguide as vgmod
    from app import storage as _storage
    jid = f"vis-acc-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps(), objects=[
            {"obj_id": 1, "label": "bowl", "overlay": "obj-1-overlay.png"}])
        d = _storage.media_root() / "tutorials" / jid / "visuals"
        d.mkdir(parents=True, exist_ok=True)
        (d / "acc-bowl.png").write_bytes(_png_bytes())
        db.add(M.VisualAsset(id=uuid.uuid4().hex, tutorial_id=jid, parent_id="p",
                             kind="enhanced", status="accepted",
                             storage_key=f"data/tutorials/{jid}/visuals/acc-bowl.png",
                             mime_type="image/png", width=320, height=240,
                             instruction="Bowl close-up for gathering step",
                             model="m", simulated=False, provenance={},
                             created_by="tech-1"))
        db.commit()
        scenes = [{"step": 1, "step_number": 1, "title": "Gather the baking tools",
                   "caption": "Gather bowl, scale and tray.",
                   "audio_start": 0.0, "audio_end": 6.0, "objects_used": [1],
                   "visual": {}}]
        out, report = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        assert out[0]["visual"].get("name") == "acc-bowl.png"
        assert out[0]["visual"].get("kind") == "accepted"
        assert report["accepted"] == 1
    finally:
        db.close()


def test_source_overlay_wins_without_accepted():
    from app.db import SessionLocal
    from app import videoguide as vgmod
    from app import storage as _storage
    jid = f"vis-src-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps(), objects=[
            {"obj_id": 1, "label": "bowl", "overlay": "obj-1-overlay.png"}])
        d = _storage.media_root() / "tutorials" / jid
        (d / "obj-1-overlay.png").write_bytes(_png_bytes())
        scenes = [{"step": 1, "step_number": 1, "title": "Gather the baking tools",
                   "caption": "Gather bowl, scale and tray.",
                   "audio_start": 0.0, "audio_end": 6.0, "objects_used": [1],
                   "visual": {}}]
        out, report = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        assert out[0]["visual"].get("name") == "obj-1-overlay.png"
        assert report["source"] == 1
    finally:
        db.close()


def test_keyframe_used_when_no_overlay():
    from app.db import SessionLocal
    from app import videoguide as vgmod
    from app import storage as _storage
    jid = f"vis-kf-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps(), keyframes=[{"t": 8.0, "name": "keyframe-8.jpg"}])
        d = _storage.media_root() / "tutorials" / jid
        (d / "keyframe-8.jpg").write_bytes(_png_bytes())
        scenes = [{"step": 2, "step_number": 2, "title": "Inspect the pump seal",
                   "caption": "Look at the seal face.",
                   "audio_start": 6.0, "audio_end": 20.0, "objects_used": [],
                   "visual": {}}]
        out, report = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        assert out[0]["visual"].get("name") == "keyframe-8.jpg"
        assert out[0]["visual"].get("kind") == "keyframe"
    finally:
        db.close()


def _mock_generate(monkeypatch, png=None, calls=None):
    from app import ai
    png = png if png is not None else _png_bytes()
    b64 = base64.b64encode(png).decode()

    def fake(prompt, reference_bytes=None):
        if calls is not None:
            calls.append(prompt)
        assert "Torque" not in prompt or "Do NOT" in prompt
        assert "text" not in prompt.lower() or "Do NOT render any text" in prompt
        return {"ok": True, "model": "muse-image-1.0", "simulated": False,
                "status": "ok", "image_b64": b64, "output_format": "png",
                "usage": {}}

    monkeypatch.setattr(ai, "image_generate", fake)


def test_missing_visual_triggers_muse_image_with_provenance(monkeypatch):
    from app.db import SessionLocal
    from app import models as M
    from app import videoguide as vgmod
    from app import storage as _storage
    jid = f"vis-gen-{uuid.uuid4().hex[:8]}"
    _mock_generate(monkeypatch)
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps())
        scenes = [{"step": 2, "step_number": 2, "title": "Inspect the pump seal",
                   "caption": "Look at the seal face.",
                   "audio_start": 6.0, "audio_end": 20.0, "objects_used": [],
                   "visual": {}}]
        out, report = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        vis = out[0]["visual"]
        assert vis.get("name"), "generated visual must have a stored file"
        assert vis.get("kind") == "illustrative_alternative"
        assert report["generated"] == 1
        row = db.scalars(__import__("sqlalchemy").select(M.VisualAsset).where(
            M.VisualAsset.tutorial_id == jid)).all()
        gen = [a for a in row if a.kind == "illustrative_alternative"]
        assert len(gen) == 1
        a = gen[0]
        assert a.status == "review"
        assert (_storage.media_path(a.storage_key)).is_file()
        prov = a.provenance or {}
        assert prov.get("illustrative") is True
        assert prov.get("auto") is True
        assert prov.get("step_number") == 2
        assert prov.get("fingerprint")
        assert "verify against the actual equipment" in (prov.get("warning") or "").lower()
    finally:
        db.close()


def test_same_guide_reuses_generated_image(monkeypatch):
    from app.db import SessionLocal
    from app import videoguide as vgmod
    jid = f"vis-cache-{uuid.uuid4().hex[:8]}"
    calls: list = []
    _mock_generate(monkeypatch, calls=calls)
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps())
        scenes = [{"step": 2, "step_number": 2, "title": "Inspect the pump seal",
                   "caption": "Look at the seal face.",
                   "audio_start": 6.0, "audio_end": 20.0, "objects_used": [],
                   "visual": {}}]
        out1, _r1 = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        out2, report2 = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        assert len(calls) == 1, "unchanged guide must not spend generation credits twice"
        assert out2[0]["visual"].get("name") == out1[0]["visual"].get("name")
        assert report2["cached"] == 1
    finally:
        db.close()


def test_changed_guide_regenerates(monkeypatch):
    from app.db import SessionLocal
    from app import videoguide as vgmod
    jid = f"vis-change-{uuid.uuid4().hex[:8]}"
    calls: list = []
    _mock_generate(monkeypatch, calls=calls)
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps(), content_revision=1)
        scenes = [{"step": 2, "step_number": 2, "title": "Inspect the pump seal",
                   "caption": "Look at the seal face.",
                   "audio_start": 6.0, "audio_end": 20.0, "objects_used": [],
                   "visual": {}}]
        vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        job.content_revision = 2
        db.commit()
        vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        assert len(calls) == 2, "changed content revision must not reuse the obsolete illustration"
    finally:
        db.close()


def test_unavailable_model_falls_back_without_empty_panel(monkeypatch):
    from app.db import SessionLocal
    from app import ai
    from app import videoguide as vgmod
    jid = f"vis-fb-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(ai, "image_generate", lambda prompt, reference_bytes=None: {
        "ok": False, "model": "muse-image-1.0", "simulated": False,
        "status": "unavailable", "note": "No META_API_KEY configured."})
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps())
        scenes = [{"step": 1, "step_number": 1, "title": "Gather the baking tools",
                   "caption": "Gather bowl, scale and tray.",
                   "audio_start": 0.0, "audio_end": 6.0, "objects_used": [1],
                   "visual": {}}]
        out, report = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        vis = out[0]["visual"]
        assert vis.get("name"), "fallback must still produce a real visual"
        assert vis.get("kind") == "guide_visual"
        assert report["graphic"] == 1
        assert report["empty"] == 0
        assert any(f.get("stage") == "generate" for f in report["failures"])
    finally:
        db.close()


def test_asset_paths_resolve_under_custom_media_root(monkeypatch, tmp_path):
    from app.db import SessionLocal
    from app import videoguide as vgmod
    vol = tmp_path / "vol2"
    monkeypatch.setenv("MEDIA_ROOT", str(vol))
    jid = f"vis-root-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        job = _job(db, jid, steps=_steps(), objects=[
            {"obj_id": 1, "label": "bowl", "illustration": "obj-1.png"}])
        (vol / "tutorials" / jid / "obj-1.png").write_bytes(_png_bytes())
        scenes = [{"step": 1, "step_number": 1, "title": "Gather the baking tools",
                   "caption": "Gather bowl, scale and tray.",
                   "audio_start": 0.0, "audio_end": 6.0, "objects_used": [1],
                   "visual": {}}]
        out, _r = vgmod.resolve_scene_visuals(db, job, scenes, actor="tech-1")
        assert out[0]["visual"].get("name") == "obj-1.png"
        img, diag = vgmod._resolve_visual_file(vol / "tutorials" / jid, out[0]["visual"])
        assert img is not None and diag == ""
        assert str(img).startswith(str(vol.resolve()))
    finally:
        db.close()


def test_beats_are_contiguous_and_captioned():
    from app import videoguide as vgmod
    scene = {"step": 1, "step_number": 1, "title": "Do it",
             "caption": "Do the thing.", "audio_start": 0.0, "audio_end": 5.0}
    segments = [{"text": "first part", "start": 0.0, "end": 2.0},
                {"text": "second part", "start": 2.0, "end": 5.0}]
    beats = vgmod.plan_visual_beats(scene, segments, 150, 45)
    assert len(beats) == 2, "short scenes get establish + focus"
    assert beats[0]["startFrame"] == 45
    assert beats[0]["startFrame"] + beats[0]["durationFrames"] == beats[1]["startFrame"]
    assert sum(b["durationFrames"] for b in beats) == 150
    assert beats[0]["body"] == "first part"
    long_scene = dict(scene, audio_end=25.0)
    long_beats = vgmod.plan_visual_beats(long_scene, segments, 750, 45)
    kinds = [b["kind"] for b in long_beats]
    assert kinds == ["hero", "detail", "caption", "verify"]
    assert sum(b["durationFrames"] for b in long_beats) == 750
    assert long_beats[-1]["body"], "verify beat always carries text"
