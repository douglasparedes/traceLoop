"""Guide illustration injection: headings of any produced shape link up.

Regression: guides shaped like "### Step 1: ..." shipped with zero images
even when overlays existed on disk, because the injector only recognized
"### 1." / "### 1)". Ambiguous-identity visuals stay review-only.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from app.tutorial import inject_illustrations  # noqa: E402

STEPS = [
    {"step_number": 1, "objects_used": [1]},
    {"step_number": 2, "objects_used": ["2"]},
    {"step_number": 3, "objects_used": []},
]
OBJECTS = [
    {"obj_id": 1, "label": "flour", "overlay": "obj-1-overlay.png",
     "illustration": "obj-1.png", "status": "ok"},
    {"obj_id": 2, "label": "eggs", "overlay": "obj-2-overlay.png",
     "illustration": "", "status": "ok"},
]


def test_step_heading_shapes():
    bodies = {
        "dotted": "### 1. Show flour (0s-28s)",
        "paren": "### 1) Show flour (0s-28s)",
        "step_colon": "### Step 1: Show flour and sugars (0:01-0:28)",
        "step_of": "### Step 1 of 4: Show flour (0s-28s)",
        "lowercase": "### step 1: show flour",
    }
    for name, heading in bodies.items():
        md = f"# T\n\n## Steps\n\n{heading}\n\nDo it.\n\n### 2. Next\n\nNext.\n"
        out = inject_illustrations(md, STEPS, OBJECTS)
        assert "illustrations/obj-1-overlay.png" in out, name
        assert out.count("illustrations/obj-1-overlay.png") == 1, name


def test_injection_is_idempotent_across_shapes():
    md = "# T\n\n## Steps\n\n### Step 1 of 4: Show flour (0s-28s)\n\nDo it.\n"
    once = inject_illustrations(md, STEPS, OBJECTS)
    assert inject_illustrations(once, STEPS, OBJECTS) == once


def test_obj_id_type_coercion():
    # int obj_id vs str entries in objects_used (and vice versa) still link.
    md = "# T\n\n## Steps\n\n### 2. Next (5s-9s)\n\nNext thing.\n"
    out = inject_illustrations(md, STEPS, OBJECTS)
    assert "illustrations/obj-2-overlay.png" in out


def test_ambiguous_match_stays_review_only():
    md = "# T\n\n## Steps\n\n### 1. Do it (0s-5s)\n\nDo the thing.\n"
    amb = [{"obj_id": 1, "label": "white sugar", "overlay": "obj-1-overlay.png",
            "illustration": "obj-1.png", "status": "needs_tap",
            "ambiguous_match": True}]
    out = inject_illustrations(md, [{"step_number": 1, "objects_used": [1]}], amb)
    assert "illustrations/obj-1-overlay.png" not in out
    # Verified-only rule: even a low-confidence single match stays reviewable
    # until confirmed — unvalidated overlays are never presented as success.
    low = [{"obj_id": 1, "label": "flag", "overlay": "obj-1-overlay.png",
            "illustration": "", "status": "needs_tap"}]
    out2 = inject_illustrations(md, [{"step_number": 1, "objects_used": [1]}], low)
    assert "illustrations/obj-1-overlay.png" not in out2
    ok = [{"obj_id": 1, "label": "flag", "overlay": "obj-1-overlay.png",
           "illustration": "", "status": "ok"}]
    out3 = inject_illustrations(md, [{"step_number": 1, "objects_used": [1]}], ok)
    assert "illustrations/obj-1-overlay.png" in out3


def test_fallback_generator_headings_match_injector():
    from app.ai import fallback_guide_markdown
    steps = [
        {"step_number": 1, "title": "Do it", "start": 0.0, "end": 5.0,
         "summary": "Do it.", "objects_used": [1]},
        {"step_number": 2, "title": "Next", "start": 5.0, "end": 9.0,
         "summary": "Next.", "objects_used": []},
    ]
    objects = [{"obj_id": 1, "label": "flag", "overlay": "obj-1-overlay.png",
                "illustration": "", "status": "ok"}]
    for fmt in ("work_instruction", "reference_manual", "interactive"):
        md = fallback_guide_markdown("T", steps, objects, fmt)
        headings = [l for l in md.splitlines() if l.startswith("###")]
        assert headings, fmt
        for h in headings:
            assert re.match(r"^###\s+(?:Step\s+)?(\d+)(?:\s+of\s+\d+)?[\.\)\:]", h, re.I), (fmt, h)
        out = inject_illustrations(md, steps, objects)
        assert "illustrations/obj-1-overlay.png" in out, fmt


def test_hirez_retry_records_its_attempt(monkeypatch, tmp_path):
    import app.tutorial as tut

    (tmp_path / "tracking-hirez.mp4").write_bytes(b"fake")
    monkeypatch.setattr(tut.ai, "upload_video_file", lambda b, filename="x.mp4": "fid-1")
    monkeypatch.setattr(tut.ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(tut.ai, "segment_video_clip",
                        lambda fid, prompt: {"frames": [], "simulated": False,
                                            "status": "no_match"})

    out, attempt = tut._hirez_retry(tmp_path, tmp_path / "source.mp4",
                                    {"obj_id": 9, "label": "natron"}, "natron")
    assert out is None
    assert attempt["prompt"] == "natron (hi-res retry)"
    assert attempt["status"] == "no_match"
    assert attempt["frames"] == 0

    # A hit returns illustrations AND the attempt trail.
    frames = [{"frame": 6, "objects": [{"object_id": 0,
                                        "bbox_norm": [0.3, 0.3, 0.6, 0.6],
                                        "confidence": 0.9, "mask": None}]}]
    monkeypatch.setattr(tut.ai, "segment_video_clip",
                        lambda fid, prompt: {"frames": frames, "simulated": False,
                                            "status": "ok"})
    monkeypatch.setattr(tut, "make_illustrations",
                        lambda jd, src, obj, best: {"illustration": "obj-9.png",
                                                   "overlay": "obj-9-overlay.png"})
    out, attempt = tut._hirez_retry(tmp_path, tmp_path / "source.mp4",
                                    {"obj_id": 9, "label": "natron"}, "natron")
    assert out is not None and out["status"] == "ok"
    assert out["illustration"] == "obj-9.png"
    assert attempt["frames"] == 1
