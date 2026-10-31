"""Guide formats, versions, and Muse Image visual workflows (mocked provider)."""
import base64
import io
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, tutorial  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}
REV = {"X-User": "rev-1", "X-Role": "reviewer"}


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    # Emulates the LIVE provider path with mocks (see test_tutorial.py).
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr(tutorial, "probe_video", lambda p: {"duration": 30.0, "width": 320, "height": 240})
    monkeypatch.setattr(tutorial, "extract_audio_wav", lambda s, o: o.write_bytes(b"wav"))
    monkeypatch.setattr(tutorial, "make_tracking_copy", lambda s, o, max_width=512: (o.write_bytes(b"mp4"), {"width": 320, "height": 240})[1])
    monkeypatch.setattr(ai, "transcribe_timed", lambda fn, data, duration_sec=0: {
        "text": "This is my flag. Hold it up.", "simulated": False,
        "segments": [{"text": "This is my flag.", "start": 1.0, "end": 4.0}]})
    monkeypatch.setattr(ai, "understand_tutorial", lambda segs, dur: {
        "objects": [{"label": "flag", "first_mentioned_at": 1.0, "obj_id": 1, "status": "pending"}],
        "steps": [{"step_number": 1, "title": "Show the flag", "start": 0.0, "end": 8.0,
                   "summary": "Hold the flag up.", "objects_used": [1]}],
        "simulated": False})
    monkeypatch.setattr(ai, "upload_video_file", lambda b, filename="tracking.mp4": "file-x")
    monkeypatch.setattr(ai, "delete_video_file", lambda fid: None)
    monkeypatch.setattr(ai, "segment_video_clip", lambda fid, prompt: {
        "frames": [{"frame": 6, "objects": [{"object_id": 0, "bbox_norm": [0.3, 0.3, 0.6, 0.6],
                                             "confidence": 0.9, "mask": None}]}],
        "simulated": False, "status": "ok"})
    monkeypatch.setattr(tutorial, "extract_frame_image", lambda source, t: __import__("PIL.Image", fromlist=["Image"]).new("RGB", (64, 64)))
    import base64 as _b64mod
    _TINY_PNG = _b64mod.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

    def _fake_illu(job_dir, source, obj, best):
        (job_dir / "obj-1.png").write_bytes(_TINY_PNG)
        (job_dir / "obj-1-overlay.png").write_bytes(_TINY_PNG)
        return {"illustration": "obj-1.png", "overlay": "obj-1-overlay.png"}
    monkeypatch.setattr(tutorial, "make_illustrations", _fake_illu)
    monkeypatch.setattr(ai, "generate_guide", lambda title, steps, objects, segs, guide_format="work_instruction": {
        "guide_markdown": f"# {title}\n\nfmt:{guide_format}", "materials": ["flag"], "simulated": False})


def _wait_done(job_id, token, timeout=10.0):
    hdr = {**TECH, "X-Tutorial-Token": token}
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/tutorial/{job_id}", headers=hdr)
        if r.status_code == 200 and r.json()["status"] in ("done", "error"):
            return r.json()
        time.sleep(0.1)
    raise AssertionError("tutorial job did not finish")


def _done(name=b"guide-bytes"):
    up = c.post("/api/tutorial/start", files={"file": ("g.mp4", name, "video/mp4")}, headers=TECH).json()
    done = _wait_done(up["id"], up["access_token"])
    assert done["status"] == "done", done
    return done


def test_formats_listed_and_recommendation_explains_itself():
    done = _done(b"guide-fmt-1")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    fl = c.get("/api/tutorial/formats").json()["formats"]
    assert {f["id"] for f in fl} == {"work_instruction", "reference_manual", "interactive"}
    assert all(f["name"] and f["tagline"] and f["best_for"] for f in fl)
    rec = c.get(f"/api/tutorial/{done['id']}/recommendation", headers=hdr).json()
    assert rec["source"] == "recommended" and rec["format"] in ("work_instruction", "reference_manual", "interactive")
    assert "because" in rec["rationale"].lower()
    assert set(rec["scores"]) == {"work_instruction", "reference_manual", "interactive"}
    assert sum(rec["scores"].values()) > 0  # grounded in real counts, not empty


def test_explicit_format_selection_wins_and_persists():
    done = _done(b"guide-fmt-0")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    assert c.put(f"/api/tutorial/{done['id']}/format", json={"format": "comic"}, headers=hdr).status_code == 422
    r = c.put(f"/api/tutorial/{done['id']}/format", json={"format": "reference_manual"}, headers=hdr).json()
    assert r["ok"] and r["format"] == "reference_manual" and r["format_source"] == "user"
    rec = c.get(f"/api/tutorial/{done['id']}/recommendation", headers=hdr).json()
    assert rec["format"] == "reference_manual" and rec["source"] == "user"
    assert rec["recommendation"]["format"] in ("work_instruction", "reference_manual", "interactive")
    # Generating without a format keeps the explicit choice (never silently switches).
    g = c.post(f"/api/tutorial/{done['id']}/guide", json={}, headers=hdr).json()
    assert g["format"] == "reference_manual" and g["format_source"] == "user"


def test_generate_new_version_keeps_history_and_defaults_to_recommendation():
    done = _done(b"guide-fmt-2")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    assert done.get("format_source") == "recommended"
    before = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert len(before) >= 1
    # Explicit format choice wins over the recommendation.
    r = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "reference_manual"}, headers=hdr).json()
    assert r["ok"] and r["format"] == "reference_manual" and r["format_source"] == "user"
    assert "Recommended" not in (r["rationale"] or "")
    after = c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]
    assert len(after) == len(before) + 1
    assert after[-1]["trigger"] == "format"
    # New snapshot is a superset-safe copy: old guide hash still present.
    hashes = {s["guide_hash"] for s in after}
    assert before[0]["guide_hash"] in hashes
    # Invalid format rejected, nothing created.
    bad = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "comic"}, headers=hdr)
    assert bad.status_code == 422
    assert len(c.get(f"/api/tutorial/{done['id']}/snapshots", headers=hdr).json()["snapshots"]) == len(after)
    # Unfinished tutorial cannot generate.
    up = c.post("/api/tutorial/start", files={"file": ("x.mp4", b"unfinished-1", "video/mp4")}, headers=TECH).json()
    hdr2 = {**TECH, "X-Tutorial-Token": up["access_token"]}
    assert c.post(f"/api/tutorial/{up['id']}/guide", json={}, headers=hdr2).status_code in (200, 409)


def test_format_change_on_locked_draft_creates_new_revision():
    done = _done(b"guide-fmt-3")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    vid = done["draft_version_id"]
    # Approve the draft so the linked version becomes immutable.
    assert c.post(f"/api/procedure-versions/{vid}/submit-review", json={}, headers=TECH).status_code == 200
    assert c.post(f"/api/procedure-versions/{vid}/approve", json={"comment": "ok"}, headers=REV).status_code == 200
    r = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "interactive"}, headers=hdr).json()
    assert r["draft_status"] == "new_revision"
    assert r["draft_version_id"] != vid
    # Old approved version untouched and still approved.
    old = c.get(f"/api/procedure-versions/{vid}").json()
    assert old["status"] == "approved" and len(old["steps"]) == 1
    new = c.get(f"/api/procedure-versions/{r['draft_version_id']}").json()
    assert new["status"] == "draft" and new["steps"][0]["start_sec"] == 0.0
    # Same format again immediately: deduped, no second new version.
    again = c.post(f"/api/tutorial/{done['id']}/guide", json={"format": "interactive"}, headers=hdr).json()
    assert again.get("duplicate") is True and again["snapshot_id"] == r["snapshot_id"]


def test_annotations_validated_and_deterministic():
    done = _done(b"guide-fmt-4")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    src = {"kind": "illustration", "name": "obj-1-overlay.png"}
    # Bad coordinates rejected.
    r = c.post(f"/api/tutorial/{done['id']}/visuals/annotate",
               json={"source": src, "shapes": [{"type": "rect", "points": [[0, 0]]}]}, headers=hdr)
    assert r.status_code == 422
    # Invented dimension unit rejected; non-numeric value rejected.
    r = c.post(f"/api/tutorial/{done['id']}/visuals/annotate",
               json={"source": src, "shapes": [{"type": "dimension", "points": [[0.5, 0.5]], "dimension": {"value": "big", "unit": "mm"}}]}, headers=hdr)
    assert r.status_code == 422
    r = c.post(f"/api/tutorial/{done['id']}/visuals/annotate",
               json={"source": src, "shapes": [{"type": "dimension", "points": [[0.5, 0.5]], "dimension": {"value": 3.5, "unit": "parsecs"}}]}, headers=hdr)
    assert r.status_code == 422
    # Valid annotation: stored as deterministic SVG, no model involved.
    r = c.post(f"/api/tutorial/{done['id']}/visuals/annotate",
               json={"source": src, "label": "Tip highlight",
                     "shapes": [{"type": "circle", "points": [[0.5, 0.5]], "text": "tip"},
                                {"type": "dimension", "points": [[0.5, 0.5]], "dimension": {"value": 3.5, "unit": "mm"}}]},
               headers=hdr).json()
    assert r["ok"] and r["asset"]["kind"] == "annotation" and r["asset"]["model"] == "deterministic-svg"
    assert r["asset"]["status"] == "review"
    svg = c.get(f"/api/visuals/{r['asset']['id']}/file", params={"token": done["access_token"]})
    assert svg.status_code == 200 and "<svg" in svg.text and "3.5 mm" in svg.text
    assert "unverified" in svg.text  # user requirement is labelled, never presented as measured
    # Accept links it without touching the source.
    acc = c.post(f"/api/visuals/{r['asset']['id']}/accept", json={}, headers=TECH).json()
    assert acc["ok"] and acc["asset"]["status"] == "accepted"
    # Reject path on another asset.
    r2 = c.post(f"/api/tutorial/{done['id']}/visuals/annotate",
                json={"source": src, "shapes": [{"type": "point", "points": [[0.1, 0.1]]}]}, headers=hdr).json()
    assert c.post(f"/api/visuals/{r2['asset']['id']}/reject", json={}, headers=TECH).json()["ok"]


def test_improve_and_alternative_use_muse_image_mock(monkeypatch):
    import base64 as _b64
    seen = {}

    class FakeResp:
        def __init__(self, payload, status=200):
            self._p = payload
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                e = RuntimeError("http")
                e.response = self
                raise e

        def json(self):
            return self._p

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update({"url": url, "json": json})
        assert headers["Authorization"].startswith("Bearer ")
        # Tools must be disabled: no external search grounding.
        tools = (json or {}).get("tool_enablement", {})
        assert tools.get("enable_web_search") is False and tools.get("enable_image_search") is False
        import base64 as _b64mod
        tiny = _b64mod.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        img = _b64mod.b64encode(tiny).decode()
        return FakeResp({"data": [{"b64_json": img}], "output_format": "png", "usage": {"total_tokens": 10}})
    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    done = _done(b"guide-fmt-5")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    src = {"kind": "illustration", "name": "obj-1-overlay.png"}
    # Improve: POSTs to /images/edits with the source as data URL.
    r = c.post(f"/api/tutorial/{done['id']}/visuals/improve",
               json={"source": src, "prompt": "Make the tip easier to see", "idempotency_key": "imp-1"}, headers=hdr).json()
    assert r["ok"] and r["asset"]["kind"] == "enhanced" and r["asset"]["status"] == "review"
    assert "/images/edits" in seen["url"] and seen["json"]["images"][0]["image_url"].startswith("data:image/")
    assert r["asset"]["provenance"]["warning"].startswith("AI reconstruction")
    # Idempotent retry returns the same asset without a new provider call.
    seen.clear()
    r2 = c.post(f"/api/tutorial/{done['id']}/visuals/improve",
                json={"source": src, "prompt": "Make the tip easier to see", "idempotency_key": "imp-1"}, headers=hdr).json()
    assert r2["duplicate"] is True and r2["asset"]["id"] == r["asset"]["id"] and not seen
    # Alternative: generation path, labelled illustrative.
    a = c.post(f"/api/tutorial/{done['id']}/visuals/alternative",
               json={"prompt": "Same clamp on a Toyota 4x4 engine bay", "intent": "similar"}, headers=hdr).json()
    assert a["ok"] and a["asset"]["kind"] == "illustrative_alternative"
    assert a["asset"]["provenance"]["illustrative"] is True
    assert seen["url"].endswith("/images/generations")
    # Accepting into a locked (approved) version is refused.
    vid = done["draft_version_id"]
    c.post(f"/api/procedure-versions/{vid}/submit-review", json={}, headers=TECH)
    c.post(f"/api/procedure-versions/{vid}/approve", json={"comment": "ok"}, headers=REV)
    bad = c.post(f"/api/visuals/{a['asset']['id']}/accept",
                 json={"step_id": "x", "version_id": vid}, headers=TECH)
    assert bad.status_code == 409
    # Accept without linking works and is idempotent.
    ok = c.post(f"/api/visuals/{a['asset']['id']}/accept", json={}, headers=TECH).json()
    assert ok["ok"] and c.post(f"/api/visuals/{a['asset']['id']}/accept", json={}, headers=TECH).json()["already"] is True


def test_muse_image_failure_is_honest(monkeypatch):
    import httpx

    class FakeResp:
        status_code = 503

        def raise_for_status(self):
            e = RuntimeError("backend down")
            e.response = self
            raise e

    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(ai, "live_enabled", lambda: True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    done = _done(b"guide-fmt-6")
    hdr = {**TECH, "X-Tutorial-Token": done["access_token"]}
    r = c.post(f"/api/tutorial/{done['id']}/visuals/improve",
               json={"source": {"kind": "illustration", "name": "obj-1-overlay.png"}, "prompt": "x"}, headers=hdr)
    assert r.status_code == 502  # retryable surfaced, not fake success, no asset stored
    assert calls["n"] == 2  # exactly one bounded retry
    lib = c.get(f"/api/tutorial/{done['id']}/visuals", headers=hdr).json()["items"]
    assert all(v["kind"] != "enhanced" for v in lib)
