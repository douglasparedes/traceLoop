import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
TECH = {"X-User": "tech-1", "X-Role": "technician"}


def _capture_with_text_evidence():
    cap = c.post("/api/capture-sessions", json={"title": "VS", "task_description": "d"}, headers=TECH).json()
    ev = c.post(f"/api/capture-sessions/{cap['id']}/evidence",
                json={"evidence_type": "transcript", "text_content": "x"}, headers=TECH).json()
    return cap, ev


def test_segment_empty_prompt_rejected_and_suggest_requires_image():
    _, ev = _capture_with_text_evidence()
    assert c.post(f"/api/evidence/{ev['id']}/segment", json={"prompt_text": ""}, headers=TECH).status_code in (400, 422)
    assert c.post(f"/api/evidence/{ev['id']}/suggest-prompts", headers=TECH).status_code == 400


def test_suggest_and_point_segment_simulated_without_key():
    import io
    from PIL import Image
    cap = c.post("/api/capture-sessions", json={"title": "VS2", "task_description": "d"}, headers=TECH).json()
    buf = io.BytesIO(); Image.new("RGB", (64, 48), (40, 100, 220)).save(buf, format="JPEG")
    img = c.post(f"/api/capture-sessions/{cap['id']}/image",
                 files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")}, headers=TECH).json()
    s = c.post(f"/api/evidence/{img['id']}/suggest-prompts", headers=TECH)
    assert s.status_code == 200 and s.json()["simulated"] is True and s.json()["suggestions"] == []
    seg = c.post(f"/api/evidence/{img['id']}/segment",
                 json={"prompt_text": "", "prompt_nx": 0.5, "prompt_ny": 0.5}, headers=TECH)
    assert seg.status_code == 200 and seg.json()["simulated"] is True


def test_voice_realtime_without_key_sends_simulated_error():
    with c.websocket_connect("/api/voice/realtime") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["simulated"] is True
