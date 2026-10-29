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
