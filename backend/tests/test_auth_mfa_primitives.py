"""SEC-004 cryptographic primitives are bounded, replay-aware, and fail closed."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from app.core.auth.mfa import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_encryption_key,
    generate_pending_challenge,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    verify_pending_challenge,
    verify_recovery_code,
    verify_totp,
)


def test_totp_matches_rfc_6238_sha1_vector_and_rejects_replay() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    at = datetime.fromtimestamp(59, tz=UTC)

    accepted_step = verify_totp(secret, "287082", at=at, window=0)

    assert accepted_step == 1
    assert verify_totp(secret, "287082", at=at, last_accepted_step=accepted_step) is None


def test_totp_accepts_only_narrow_window_and_ascii_six_digits() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    at = datetime.fromtimestamp(89, tz=UTC)

    assert verify_totp(secret, "287082", at=at, window=1) == 1
    assert verify_totp(secret, "287082", at=at, window=0) is None
    assert verify_totp(secret, "２８７０８２", at=at) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_totp(secret, "287082", at=datetime(1970, 1, 1))


def test_totp_secret_has_160_bits_and_round_trips_through_aes_gcm() -> None:
    user_id = uuid4()
    secret = generate_totp_secret()
    encoded_key = generate_encryption_key()

    envelope = encrypt_totp_secret(
        secret,
        user_id=user_id,
        key_id="primary-2026",
        encoded_key=encoded_key,
    )

    assert envelope.startswith("v1.")
    assert secret not in envelope
    assert (
        decrypt_totp_secret(
            envelope,
            user_id=user_id,
            key_id="primary-2026",
            encoded_key=encoded_key,
        )
        == secret
    )


def test_encrypted_seed_is_bound_to_user_key_id_and_ciphertext() -> None:
    user_id = uuid4()
    encoded_key = generate_encryption_key()
    envelope = encrypt_totp_secret(
        generate_totp_secret(),
        user_id=user_id,
        key_id="primary-2026",
        encoded_key=encoded_key,
    )

    with pytest.raises(InvalidTag):
        decrypt_totp_secret(
            envelope,
            user_id=uuid4(),
            key_id="primary-2026",
            encoded_key=encoded_key,
        )
    with pytest.raises(InvalidTag):
        decrypt_totp_secret(
            envelope,
            user_id=user_id,
            key_id="replacement-2026",
            encoded_key=encoded_key,
        )


@pytest.mark.parametrize("encoded_key", ["", "c2hvcnQ=", "not base64!"])
def test_seed_encryption_rejects_missing_or_malformed_keys(encoded_key: str) -> None:
    with pytest.raises(ValueError, match="MFA encryption key"):
        encrypt_totp_secret(
            generate_totp_secret(),
            user_id=uuid4(),
            key_id="primary-2026",
            encoded_key=encoded_key,
        )


def test_pending_challenge_persists_only_digest() -> None:
    challenge, digest = generate_pending_challenge()

    assert challenge != digest
    assert len(digest) == 64
    assert verify_pending_challenge(challenge, digest)
    assert not verify_pending_challenge(challenge + "x", digest)


def test_recovery_codes_are_unique_keyed_and_format_tolerant() -> None:
    pepper = b"r" * 32
    codes = generate_recovery_codes()

    assert len(codes) == 10
    assert len(set(codes)) == 10
    digest = hash_recovery_code(codes[0], pepper=pepper)
    assert codes[0] not in digest
    assert verify_recovery_code(codes[0].lower().replace("-", " "), digest, pepper=pepper)
    assert not verify_recovery_code(codes[1], digest, pepper=pepper)


def test_recovery_digest_rejects_short_pepper_and_invalid_code() -> None:
    with pytest.raises(ValueError, match="at least 256 bits"):
        hash_recovery_code(generate_recovery_codes(1)[0], pepper=b"short")
    with pytest.raises(ValueError, match="exactly 128 bits"):
        hash_recovery_code("not-a-code", pepper=b"r" * 32)
