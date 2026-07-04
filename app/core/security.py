import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

pwd_hasher = PasswordHash.recommended()

API_KEY_PREFIX = "sk_live_"
REFRESH_TOKEN_EXPIRE_DAYS = 30


@dataclass(frozen=True)
class ApiKeyResponse:
    raw_key: str
    hashed_key: str
    api_key_prefix: str


def hash_password(password: str) -> str:
    return pwd_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_hasher.verify(password, hashed)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> ApiKeyResponse:
    raw_key = f"{API_KEY_PREFIX}{secrets.token_hex(24)}"
    return ApiKeyResponse(
        raw_key=raw_key, hashed_key=hash_api_key(raw_key), api_key_prefix=raw_key[:12]
    )


def create_access_token(
    subject: str,
    token_version: int,
    extra: dict | None = None,
) -> str:
    payload = {
        "sub": subject,
        "tv": token_version,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


def generate_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Store only the hash."""
    raw = secrets.token_hex(40)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
