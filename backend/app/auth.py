"""Team passphrase gate (step 1 of auth; per-user accounts are a follow-up).

When APP_PASSWORD is unset, the API is open (local dev behavior, unchanged).
When set, every /api/* request except /api/health and /api/auth/login needs
a valid X-Auth-Token. The token is HMAC-signed with SECRET_KEY and expires;
roles stay self-selected inside the app (demo identity), the gate only proves
team membership.
"""
import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_TTL_SEC = 30 * 24 * 3600
TOKEN_PREFIX = "fg1."
GRANT_PREFIX = "fg-grant."
GRANT_TTL_SEC = 30 * 24 * 3600


def _password() -> str:
    return os.getenv("APP_PASSWORD", "")


def _secret() -> bytes:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        key = "fieldguard-local:" + _password()
    return key.encode("utf-8")


def enabled() -> bool:
    return bool(_password())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token() -> str:
    payload = json.dumps({"v": 1, "exp": int(time.time()) + TOKEN_TTL_SEC}).encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return TOKEN_PREFIX + _b64(payload) + "." + _b64(sig)


def verify_token(token: str) -> bool:
    try:
        if not token or not token.startswith(TOKEN_PREFIX):
            return False
        payload_b64, sig_b64 = token[len(TOKEN_PREFIX):].split(".", 1)
        payload, sig = _unb64(payload_b64), _unb64(sig_b64)
        if not hmac.compare_digest(hmac.new(_secret(), payload, hashlib.sha256).digest(), sig):
            return False
        body = json.loads(payload.decode("utf-8"))
        return int(body.get("exp", 0)) > int(time.time())
    except Exception:
        return False


def check_password(password: str) -> bool:
    expected = _password()
    if not expected:
        return False
    return hmac.compare_digest(password or "", expected)


def create_offline_grant(procedure_id: str, version_id: str, actor: str,
                         ttl_sec: int = GRANT_TTL_SEC) -> str:
    """Sign an offline execution grant for one approved procedure version.

    Bound to procedure + exact version + actor identity + expiry, using the
    same HMAC team secret as session tokens — no second token system. The
    server verifies the grant before accepting an offline job against a
    version that has since become superseded.
    """
    payload = json.dumps({"v": 1, "typ": "offline-grant", "proc": procedure_id,
                          "ver": version_id, "actor": actor,
                          "exp": int(time.time()) + int(ttl_sec)}).encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return GRANT_PREFIX + _b64(payload) + "." + _b64(sig)


def verify_offline_grant(token: str) -> dict | None:
    """Return the grant payload if valid, else None. Never raises."""
    try:
        if not token or not token.startswith(GRANT_PREFIX):
            return None
        payload_b64, sig_b64 = token[len(GRANT_PREFIX):].split(".", 1)
        payload, sig = _unb64(payload_b64), _unb64(sig_b64)
        if not hmac.compare_digest(hmac.new(_secret(), payload, hashlib.sha256).digest(), sig):
            return None
        body = json.loads(payload.decode("utf-8"))
        if body.get("typ") != "offline-grant":
            return None
        if int(body.get("exp", 0)) <= int(time.time()):
            return None
        if not body.get("proc") or not body.get("ver"):
            return None
        return body
    except Exception:
        return None
