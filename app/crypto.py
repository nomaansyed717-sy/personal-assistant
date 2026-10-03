"""Per-user encryption for tokens and raw message content.

Each user gets a key derived from the master key with HKDF, so one user's data
can never be decrypted with another user's key, and deleting a user leaves no
usable ciphertext behind once the rows are gone.
"""
import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings


class CryptoError(Exception):
    pass


def _master() -> bytes:
    key = get_settings().master_key
    if not key:
        raise CryptoError("MASTER_KEY is not set")
    return base64.urlsafe_b64decode(key)


@lru_cache(maxsize=4096)
def _fernet_for(user_id: int, master: bytes) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"assistant-user-key-v1",
        info=f"user:{user_id}".encode(),
    ).derive(master)
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(user_id: int, plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet_for(user_id, _master()).encrypt(plaintext.encode()).decode()


def decrypt(user_id: int, ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _fernet_for(user_id, _master()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError("could not decrypt value for this user") from exc
