"""Encrypted file storage (E14-05).

Every stored file — uploaded statements, decrypted view copies, evidence photos, signed
memos — is written through here and encrypted with Fernet (AES-128-CBC + HMAC-SHA256,
authenticated: a modified file fails to decrypt rather than returning garbage).

The key comes from FINSONA_STORAGE_KEY, or is generated once into backend/.storage_key
(git-ignored). In a bank deployment it would live in the bank's key vault (see the
compliance page). SHA-256 fingerprints are always of the plaintext as uploaded.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi.responses import Response

from app.config import BACKEND_DIR, settings

MAGIC = b"FNSA1:"  # marks an encrypted file; older plaintext files are still readable

_fernet: Fernet | None = None


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.storage_key
        if not key:
            path = BACKEND_DIR / ".storage_key"
            if not path.exists():
                path.write_bytes(Fernet.generate_key())
            key = path.read_text(encoding="utf-8").strip()
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


class StorageCorrupt(Exception):
    pass


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MAGIC + _f().encrypt(data))


def read(path: Path) -> bytes:
    raw = Path(path).read_bytes()
    if not raw.startswith(MAGIC):
        return raw
    try:
        return _f().decrypt(raw[len(MAGIC):])
    except InvalidToken as e:
        raise StorageCorrupt(f"{path}: failed authentication (tampered or wrong key)") from e


def is_encrypted(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def encrypt_in_place(path: Path) -> None:
    data = Path(path).read_bytes()
    if not data.startswith(MAGIC):
        write(Path(path), data)


def response(path: Path, media_type: str, filename: str) -> Response:
    """Serve a stored file decrypted, inline."""
    from urllib.parse import quote

    return Response(read(path), media_type=media_type,
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"})
