"""Cryptographic primitives for staff MFA.

This module does not issue sessions or read application settings. Callers must
supply separately managed key material and persist only encrypted or hashed
values.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .models import StaffMfaChallenge

_TOTP_STEP_SECONDS = 30
_TOTP_DIGITS = 6
_MIN_TOTP_SECRET_BYTES = 20
_AES_KEY_BYTES = 32
_AES_NONCE_BYTES = 12
_RECOVERY_PEPPER_BYTES = 32
_KEY_ID_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
MFA_CHALLENGE_LIFETIME = timedelta(minutes=5)
MFA_CHALLENGE_MAX_ATTEMPTS = 5
MFA_CHALLENGE_PURPOSES = frozenset({"login", "enrollment", "recovery"})


@dataclass(frozen=True)
class StaffMfaKeyMaterial:
    """Validated, independent secret-manager values for staff MFA."""

    key_id: str
    encoded_encryption_key: str
    recovery_pepper: bytes


def generate_totp_secret() -> str:
    """Return a 160-bit Base32 secret suitable for standard authenticator apps."""
    return base64.b32encode(secrets.token_bytes(_MIN_TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode_totp_secret(secret: str) -> bytes:
    normalized = secret.strip().upper()
    padding = "=" * (-len(normalized) % 8)
    try:
        decoded = base64.b32decode(normalized + padding, casefold=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("TOTP secret must be valid Base32") from exc
    if len(decoded) < _MIN_TOTP_SECRET_BYTES:
        raise ValueError("TOTP secret must contain at least 160 bits")
    return decoded


def _totp_for_step(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()  # noqa: S324
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)


def verify_totp(
    secret: str,
    code: str,
    *,
    at: datetime,
    last_accepted_step: int | None = None,
    window: int = 1,
) -> int | None:
    """Return the accepted time step, or None for an invalid or replayed code."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("TOTP verification time must be timezone-aware")
    if window < 0 or window > 1:
        raise ValueError("TOTP window must be zero or one")
    if len(code) != _TOTP_DIGITS or not code.isascii() or not code.isdigit():
        return None

    decoded = _decode_totp_secret(secret)
    current_step = int(at.timestamp()) // _TOTP_STEP_SECONDS
    for candidate_step in range(current_step - window, current_step + window + 1):
        if candidate_step < 0:
            continue
        if last_accepted_step is not None and candidate_step <= last_accepted_step:
            continue
        if secrets.compare_digest(_totp_for_step(decoded, candidate_step), code):
            return candidate_step
    return None


def generate_encryption_key() -> str:
    """Return a Base64URL-encoded AES-256 key for secret-manager provisioning."""
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")


def _decode_encryption_key(encoded_key: str) -> bytes:
    try:
        key = base64.b64decode(encoded_key, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("MFA encryption key must be valid Base64 or Base64URL") from exc
    if len(key) != _AES_KEY_BYTES:
        raise ValueError("MFA encryption key must contain exactly 256 bits")
    return key


def _decode_recovery_pepper(encoded_pepper: str) -> bytes:
    try:
        pepper = base64.b64decode(encoded_pepper, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("MFA recovery pepper must be valid Base64 or Base64URL") from exc
    if len(pepper) < _RECOVERY_PEPPER_BYTES:
        raise ValueError("MFA recovery pepper must contain at least 256 bits")
    return pepper


def _factor_aad(user_id: UUID, key_id: str) -> bytes:
    if not 1 <= len(key_id) <= 64 or any(
        character not in _KEY_ID_CHARACTERS for character in key_id
    ):
        raise ValueError("MFA encryption key id must use 1 to 64 safe characters")
    return f"dentalpin:staff-mfa:v1:{key_id}:{user_id}".encode()


def load_staff_mfa_key_material(
    *,
    key_id: str,
    encoded_encryption_key: str,
    encoded_recovery_pepper: str,
) -> StaffMfaKeyMaterial:
    """Validate deployment secrets before any enrollment or recovery operation."""
    _factor_aad(UUID(int=0), key_id)
    _decode_encryption_key(encoded_encryption_key)
    return StaffMfaKeyMaterial(
        key_id=key_id,
        encoded_encryption_key=encoded_encryption_key,
        recovery_pepper=_decode_recovery_pepper(encoded_recovery_pepper),
    )


def encrypt_totp_secret(secret: str, *, user_id: UUID, key_id: str, encoded_key: str) -> str:
    """Encrypt a validated TOTP secret with user- and key-bound associated data."""
    _decode_totp_secret(secret)
    nonce = secrets.token_bytes(_AES_NONCE_BYTES)
    ciphertext = AESGCM(_decode_encryption_key(encoded_key)).encrypt(
        nonce,
        secret.encode("ascii"),
        _factor_aad(user_id, key_id),
    )
    payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"v1.{payload}"


def decrypt_totp_secret(
    envelope: str,
    *,
    user_id: UUID,
    key_id: str,
    encoded_key: str,
) -> str:
    """Authenticate and decrypt a stored TOTP seed."""
    version, separator, encoded_payload = envelope.partition(".")
    if separator != "." or version != "v1":
        raise ValueError("Unsupported MFA secret envelope")
    try:
        payload = base64.b64decode(encoded_payload, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("MFA secret envelope must be valid Base64URL") from exc
    if len(payload) <= _AES_NONCE_BYTES:
        raise ValueError("MFA secret envelope is truncated")
    plaintext = AESGCM(_decode_encryption_key(encoded_key)).decrypt(
        payload[:_AES_NONCE_BYTES],
        payload[_AES_NONCE_BYTES:],
        _factor_aad(user_id, key_id),
    )
    secret = plaintext.decode("ascii")
    _decode_totp_secret(secret)
    return secret


def generate_pending_challenge() -> tuple[str, str]:
    """Return a 256-bit opaque challenge and the SHA-256 digest to persist."""
    challenge = secrets.token_urlsafe(32)
    return challenge, hash_pending_challenge(challenge)


def hash_pending_challenge(challenge: str) -> str:
    """Digest a high-entropy pending-auth challenge for database storage."""
    if not challenge:
        raise ValueError("Pending-auth challenge must not be empty")
    return hashlib.sha256(challenge.encode("utf-8")).hexdigest()


def verify_pending_challenge(challenge: str, expected_hash: str) -> bool:
    """Compare an opaque pending-auth challenge with its stored digest."""
    if not challenge or len(expected_hash) != 64:
        return False
    return secrets.compare_digest(hash_pending_challenge(challenge), expected_hash)


def issue_pending_challenge(
    *,
    user_id: UUID,
    purpose: str,
    now: datetime,
) -> tuple[str, StaffMfaChallenge]:
    """Build a short-lived password-verified challenge ready for persistence."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Pending-auth challenge time must be timezone-aware")
    if purpose not in MFA_CHALLENGE_PURPOSES:
        raise ValueError("Unsupported pending-auth challenge purpose")
    challenge, challenge_hash = generate_pending_challenge()
    return challenge, StaffMfaChallenge(
        user_id=user_id,
        challenge_hash=challenge_hash,
        purpose=purpose,
        attempts=0,
        expires_at=now + MFA_CHALLENGE_LIFETIME,
        created_at=now,
    )


def pending_challenge_is_usable(
    record: StaffMfaChallenge,
    challenge: str,
    *,
    now: datetime,
) -> bool:
    """Check a locked record; callers remain responsible for atomic mutation."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Pending-auth challenge time must be timezone-aware")
    return (
        record.consumed_at is None
        and record.expires_at > now
        and record.attempts < MFA_CHALLENGE_MAX_ATTEMPTS
        and verify_pending_challenge(challenge, record.challenge_hash)
    )


def _normalize_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def generate_recovery_codes(count: int = 10) -> list[str]:
    """Return independently generated 128-bit, human-transcribable recovery codes."""
    if count < 1 or count > 20:
        raise ValueError("Recovery-code count must be between 1 and 20")
    codes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(16).upper()
        codes.append("-".join(raw[index : index + 4] for index in range(0, len(raw), 4)))
    return codes


def hash_recovery_code(code: str, *, pepper: bytes) -> str:
    """Return a keyed digest; the pepper must be managed separately from JWT keys."""
    if len(pepper) < _RECOVERY_PEPPER_BYTES:
        raise ValueError("MFA recovery pepper must contain at least 256 bits")
    normalized = _normalize_recovery_code(code)
    if len(normalized) != 32 or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        raise ValueError("Recovery code must encode exactly 128 bits as hexadecimal")
    return hmac.new(pepper, normalized.encode("ascii"), hashlib.sha256).hexdigest()


def verify_recovery_code(code: str, expected_hash: str, *, pepper: bytes) -> bool:
    """Compare a recovery code with its separately keyed stored digest."""
    return secrets.compare_digest(hash_recovery_code(code, pepper=pepper), expected_hash)
