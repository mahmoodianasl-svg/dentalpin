"""SEC-004 cryptographic primitives are bounded, replay-aware, and fail closed."""

import base64
from datetime import UTC, datetime, timedelta
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
    issue_pending_challenge,
    load_staff_mfa_key_material,
    pending_challenge_is_usable,
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
    assert not verify_pending_challenge("", digest)
    assert not verify_pending_challenge(challenge, "")


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


def test_deployment_key_material_requires_three_independent_valid_values() -> None:
    encryption_key = generate_encryption_key()
    encoded_pepper = base64.urlsafe_b64encode(b"r" * 32).decode("ascii")

    material = load_staff_mfa_key_material(
        key_id="primary-2026",
        encoded_encryption_key=encryption_key,
        encoded_recovery_pepper=encoded_pepper,
    )

    assert material.key_id == "primary-2026"
    assert material.encoded_encryption_key == encryption_key
    assert material.recovery_pepper == b"r" * 32


@pytest.mark.parametrize(
    ("key_id", "encryption_key", "pepper"),
    [
        ("", generate_encryption_key(), base64.urlsafe_b64encode(b"r" * 32).decode("ascii")),
        (
            "unsafe:key",
            generate_encryption_key(),
            base64.urlsafe_b64encode(b"r" * 32).decode("ascii"),
        ),
        ("primary", "", base64.urlsafe_b64encode(b"r" * 32).decode("ascii")),
        ("primary", generate_encryption_key(), ""),
    ],
)
def test_deployment_key_material_fails_closed(
    key_id: str,
    encryption_key: str,
    pepper: str,
) -> None:
    with pytest.raises(ValueError, match="MFA"):
        load_staff_mfa_key_material(
            key_id=key_id,
            encoded_encryption_key=encryption_key,
            encoded_recovery_pepper=pepper,
        )


def test_pending_challenge_record_is_short_lived_and_database_ready() -> None:
    user_id = uuid4()
    now = datetime(2026, 9, 14, tzinfo=UTC)

    challenge, record = issue_pending_challenge(user_id=user_id, purpose="login", now=now)

    assert record.user_id == user_id
    assert record.purpose == "login"
    assert record.challenge_hash != challenge
    assert record.attempts == 0
    assert record.created_at == now
    assert record.expires_at == now + timedelta(minutes=5)
    assert pending_challenge_is_usable(record, challenge, now=now)


def test_pending_challenge_rejects_expiry_attempt_limit_consumption_and_replay() -> None:
    now = datetime(2026, 9, 14, tzinfo=UTC)
    challenge, record = issue_pending_challenge(user_id=uuid4(), purpose="login", now=now)

    assert not pending_challenge_is_usable(record, challenge + "x", now=now)
    assert not pending_challenge_is_usable(record, challenge, now=now + timedelta(minutes=5))
    record.attempts = 5
    assert not pending_challenge_is_usable(record, challenge, now=now)
    record.attempts = 0
    record.consumed_at = now
    assert not pending_challenge_is_usable(record, challenge, now=now)


def test_pending_challenge_rejects_unknown_purpose_and_naive_time() -> None:
    with pytest.raises(ValueError, match="purpose"):
        issue_pending_challenge(
            user_id=uuid4(),
            purpose="admin-bypass",
            now=datetime(2026, 9, 14, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        issue_pending_challenge(
            user_id=uuid4(),
            purpose="login",
            now=datetime(2026, 9, 14),
        )
