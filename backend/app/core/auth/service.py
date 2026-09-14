"""Authentication service for JWT and password handling."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import bcrypt
from jose import jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Hash all UTF-8 bytes, including passwords longer than bcrypt's 72-byte limit."""
    digest = sha256(password.encode("utf-8")).digest()
    return "bcrypt-sha256$" + bcrypt.hashpw(digest, bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify new pre-hashed passwords and legacy bcrypt accounts."""
    encoded = plain_password.encode("utf-8")
    if hashed_password.startswith("bcrypt-sha256$"):
        return bcrypt.checkpw(sha256(encoded).digest(), hashed_password[14:].encode("ascii"))
    if len(encoded) > 72:
        return False  # Never accept a legacy hash on the strength of a truncated prefix.
    return bcrypt.checkpw(encoded, hashed_password.encode("ascii"))


_COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")
_COMMON_PASSWORDS = frozenset(
    line.casefold() for line in _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
)


def validate_staff_password(password: str) -> tuple[bool, str]:
    """Require a long passphrase and block known common credentials, without composition rules."""
    if len(password) < 15:
        return False, "Password must be at least 15 characters"
    if len(password) > 1024:
        return False, "Password must be at most 1024 characters"
    if password.casefold() in _COMMON_PASSWORDS:
        return False, "Choose a password that is not commonly used"
    return True, ""


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets minimum requirements.

    Returns (is_valid, error_message).
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)

    if not has_letter or not has_number:
        return False, "Password must contain at least one letter and one number"

    return True, ""


def create_access_token(
    user_id: UUID,
    clinic_id: UUID | None = None,
    token_version: int = 0,
) -> str:
    """Create a JWT access token."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
        "token_version": token_version,
    }
    if clinic_id:
        payload["clinic_id"] = str(clinic_id)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    user_id: UUID,
    token_version: int = 0,
    *,
    session_id: UUID,
    absolute_expires_at: datetime,
) -> str:
    """Issue a unique, session-bound refresh credential with bounded lifetime."""
    expire = min(
        datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        absolute_expires_at,
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "token_version": token_version,
        "sid": str(session_id),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def refresh_credential_hash(token: str) -> str:
    """Keep the bearer credential itself out of the session table."""
    return sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Raises JWTError if token is invalid or expired.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
