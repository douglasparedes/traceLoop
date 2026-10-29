"""Team passphrase gate: open by default, locked when APP_PASSWORD is set."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["META_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)


def test_open_by_default_without_password(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert auth.enabled() is False
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/auth/status").json() == {"auth_enabled": False}
    # No gate: protected routes work without a token.
    assert c.get("/api/procedures").status_code == 200
    assert c.get("/api/tutorial?limit=1").status_code == 200
    # Login endpoint reports the open demo mode.
    r = c.post("/api/auth/login", json={"password": "anything"})
    assert r.status_code == 200 and r.json()["demo_open"] is True


def test_locked_with_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "team-secret")
    assert auth.enabled() is True
    assert c.get("/api/auth/status").json() == {"auth_enabled": True}
    # Health stays public; everything else needs a token.
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/procedures").status_code == 401
    assert c.get("/api/processing/events").status_code == 401
    assert c.get("/api/tutorial?limit=1").status_code == 401
    # Wrong passphrase rejected.
    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    # Right passphrase returns a token that unlocks the API.
    tok = c.post("/api/auth/login", json={"password": "team-secret"}).json()["token"]
    assert tok.startswith("fg1.")
    hdr = {"X-Auth-Token": tok}
    assert c.get("/api/procedures", headers=hdr).status_code == 200
    assert c.get("/api/auth/me", headers=hdr).json() == {"ok": True}
    # Tampered and expired tokens rejected.
    assert c.get("/api/procedures", headers={"X-Auth-Token": tok + "x"}).status_code == 401
    assert c.get("/api/procedures", headers={"X-Auth-Token": "bogus"}).status_code == 401
    # Token survives server-side secret rotation check: wrong secret fails.
    monkeypatch.setenv("SECRET_KEY", "different-secret")
    assert c.get("/api/procedures", headers=hdr).status_code == 401


def test_token_format_and_expiry(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "team-secret")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    t = auth.create_token()
    assert auth.verify_token(t) is True
    assert auth.verify_token("") is False
    assert auth.verify_token("fg1.bm90anNvbg.sig") is False


def test_media_exempt_paths():
    from app.main import MEDIA_GATE_EXEMPT_RE as rx
    good = [
        "/api/tutorial/abc-123/video",
        "/api/tutorial/abc-123/bundle.zip",
        "/api/tutorial/abc-123/illustrations/obj-1-overlay.png",
        "/api/tutorial/abc-123/diagnostics/frame/2",
        "/api/visuals/def-456/file",
        "/api/live-recordings/r1/chunks/3/video",
        "/api/evidence/e1/image",
    ]
    for p in good:
        assert rx.match(p), p
    bad = [
        "/api/procedures",
        "/api/tutorial",
        "/api/tutorial/abc-123",
        "/api/tutorial/abc-123/guide",
        "/api/tutorial/abc-123/snapshots",
        "/api/visuals/def-456/accept",
        "/api/evidence/e1",
        "/api/tutorial/abc-123/video/extra",
        "/api/tutorial/abc-123/illustrations/../../secret",
    ]
    for p in bad:
        assert not rx.match(p), p


def _seed_media_job():
    import uuid
    from pathlib import Path
    from app import models as M
    from app.db import SessionLocal
    from app.tutorial import BASE
    db = SessionLocal()
    try:
        jid, tok = str(uuid.uuid4()), str(uuid.uuid4())
        job = M.TutorialJob(id=jid, title="Gate media test", actor="tech-1",
                            access_token=tok, video_hash="gate-" + jid,
                            status="done", video_storage_key=f"data/tutorials/{jid}/source.mp4")
        db.add(job)
        db.flush()
        d = BASE / "data" / "tutorials" / jid
        d.mkdir(parents=True, exist_ok=True)
        (d / "source.mp4").write_bytes(b"fake-video-bytes")
        (d / "obj-1-overlay.png").write_bytes(b"fake-png-bytes")
        (d / "visuals").mkdir(exist_ok=True)
        (d / "visuals" / "v1.png").write_bytes(b"fake-visual-bytes")
        va = M.VisualAsset(id=str(uuid.uuid4()), tutorial_id=jid, kind="enhanced",
                           status="review", storage_key=f"data/tutorials/{jid}/visuals/v1.png",
                           mime_type="image/png", width=4, height=4, created_by="tech-1")
        db.add(va)
        db.flush()
        ev = M.Evidence(id=str(uuid.uuid4()), evidence_type="image",
                        storage_key=f"data/tutorials/{jid}/obj-1-overlay.png",
                        description="gate test", source_reference=f"tutorial:{jid}",
                        created_by="tech-1")
        db.add(ev)
        db.commit()
        return jid, tok, va.id, ev.id
    finally:
        db.close()


def test_headerless_media_uses_tutorial_bearer(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "team-secret")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    jid, tok, va_id, ev_id = _seed_media_job()
    team = c.post("/api/auth/login", json={"password": "team-secret"}).json()["token"]
    team_hdr = {"X-Auth-Token": team}
    tut_hdr = {**team_hdr, "X-Tutorial-Token": tok}

    # JSON endpoints still need the team header.
    assert c.get(f"/api/tutorial/{jid}", headers={"X-Tutorial-Token": tok}).status_code == 401
    assert c.get(f"/api/tutorial/{jid}", headers=tut_hdr).status_code == 200

    vid = f"/api/tutorial/{jid}/video?token={tok}"
    ill = f"/api/tutorial/{jid}/illustrations/obj-1-overlay.png?token={tok}"
    bundle = f"/api/tutorial/{jid}/bundle.zip?token={tok}"
    vis = f"/api/visuals/{va_id}/file?token={tok}"
    evi = f"/api/evidence/{ev_id}/image"
    live_missing = "/api/live-recordings/nope/chunks/0/video?token=nope"

    # Gate passes headerless media through; the endpoint still guards the bearer.
    assert c.get(f"/api/tutorial/{jid}/video").status_code == 403
    assert c.get(f"/api/tutorial/{jid}/video?token=wrong").status_code == 403
    assert c.get(f"/api/tutorial/{jid}/illustrations/obj-1-overlay.png").status_code == 403

    # Correct bearer serves bytes with no team header (img/video/anchor tags).
    assert c.get(vid).content == b"fake-video-bytes"
    assert c.get(ill).content == b"fake-png-bytes"
    assert c.get(bundle).status_code == 200
    assert c.get(vis).content == b"fake-visual-bytes"
    # Evidence images keep their pre-gate behavior (unguessable UUID URL).
    assert c.get(evi).content == b"fake-png-bytes"
    # Unknown recording still 403, not 401 (gate exempt, endpoint rejects).
    assert c.get(live_missing).status_code == 403

    # Non-GET to an exempt path stays behind the team gate.
    assert c.post(f"/api/tutorial/{jid}/video?token={tok}").status_code in (401, 404, 405)

    # Team header also still works on media (does not break header clients).
    assert c.get(vid, headers=team_hdr).content == b"fake-video-bytes"
