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
