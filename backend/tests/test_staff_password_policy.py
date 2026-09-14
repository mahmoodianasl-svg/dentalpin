"""SEC-004: new staff credentials must reject weak choices without truncation."""

import bcrypt
import pytest

from app.core.auth.service import hash_password, validate_staff_password, verify_password


@pytest.mark.parametrize(
    "password",
    ["ShortPhrase26", "films+pic+galeries", "x" * 1025],
)
def test_rejects_short_common_or_unbounded_staff_password(password: str) -> None:
    assert validate_staff_password(password)[0] is False


def test_accepts_long_passphrase_without_composition_rules() -> None:
    assert validate_staff_password("long passphrase with spaces")[0] is True
    assert validate_staff_password("é" * 64)[0] is True


def test_hash_verifies_entire_password_beyond_bcrypt_72_byte_limit() -> None:
    password = "a" * 72 + "first ending"
    stored = hash_password(password)
    assert stored.startswith("bcrypt-sha256$")
    assert verify_password(password, stored)
    assert not verify_password("a" * 72 + "other ending", stored)


def test_existing_bcrypt_passwords_still_verify_without_truncation_bypass() -> None:
    stored = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode("ascii")
    assert verify_password("legacy-password", stored)
    assert not verify_password("legacy-password" + "x" * 80, stored)
