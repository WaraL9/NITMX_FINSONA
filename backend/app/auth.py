"""Authentication (E14-01): password hashing and signed session tokens.

Standard library only:
  * passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user random salt;
  * sessions: `base64url(payload).base64url(HMAC-SHA256(secret, payload))`, 12h expiry;
    the user is re-loaded (and must still be active) on every request, so disabling a
    user takes effect immediately;
  * login throttling: 5 failures lock the username for 60 seconds.

The signing secret comes from FINSONA_SECRET_KEY, or is generated once into
backend/.secret (git-ignored) so tokens survive restarts on a dev machine.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.config import BACKEND_DIR, settings

ITERATIONS = 200_000
TOKEN_TTL = 12 * 3600
MAX_FAILURES = 5
LOCKOUT_S = 60


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt, dk = stored.split("$")
        assert algo == "pbkdf2_sha256"
    except (ValueError, AssertionError):
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(iters))
    return hmac.compare_digest(got, _unb64(dk))


_secret: bytes | None = None


def _key() -> bytes:
    global _secret
    if _secret is None:
        if settings.secret_key:
            _secret = settings.secret_key.encode()
        else:
            path = BACKEND_DIR / ".secret"
            if not path.exists():
                path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            _secret = path.read_text(encoding="utf-8").strip().encode()
    return _secret


def issue_token(user_id: int, role: str, ttl: int = TOKEN_TTL) -> str:
    payload = _b64(json.dumps({"uid": user_id, "role": role, "exp": int(time.time()) + ttl}).encode())
    sig = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


class InvalidToken(Exception):
    pass


def read_token(token: str) -> int:
    try:
        payload, sig = token.split(".")
    except ValueError as e:
        raise InvalidToken("malformed token") from e
    expected = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise InvalidToken("bad signature")
    data = json.loads(_unb64(payload))
    if data.get("exp", 0) < time.time():
        raise InvalidToken("expired")
    return int(data["uid"])


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: float = 0.0


_attempts: dict[str, _Attempts] = {}


def locked(username: str) -> float:
    a = _attempts.get(username)
    return max(0.0, a.locked_until - time.time()) if a else 0.0


def record_failure(username: str) -> None:
    a = _attempts.setdefault(username, _Attempts())
    a.failures += 1
    if a.failures >= MAX_FAILURES:
        a.locked_until, a.failures = time.time() + LOCKOUT_S, 0


def record_success(username: str) -> None:
    _attempts.pop(username, None)
