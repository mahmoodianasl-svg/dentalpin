"""Enrolled staff need a one-use second factor before browser credentials are issued."""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.mfa import (
    _totp_for_step,
    encrypt_totp_secret,
    generate_encryption_key,
    generate_recovery_codes,
    hash_recovery_code,
)
from app.core.auth.models import (
    RefreshSession,
    StaffMfaAuditEvent,
    StaffMfaChallenge,
    StaffMfaFactor,
    StaffMfaRecoveryCode,
    User,
)

SETUP = {
    "admin_first_name": "Admin",
    "admin_last_name": "User",
    "admin_email": "admin@example.com",
    "admin_password": "Secure Staff Passphrase 2026",
    "clinic_name": "My Clinic",
    "clinic_tax_id": "B12345678",
}
PATH = "/api/v1/auth"
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def current_code() -> str:
    return _totp_for_step(base64.b32decode(SECRET), int(datetime.now(UTC).timestamp()) // 30)


async def enroll(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str]:
    setup = await client.post(
        f"{PATH}/setup",
        json=SETUP,
        headers={"X-DentalPin-Setup-Token": settings.SETUP_TOKEN},
    )
    assert setup.status_code == 201
    old_access = setup.json()["access_token"]
    old_refresh = client.cookies.get("dentalpin_refresh")
    old_csrf = client.cookies.get("dentalpin_csrf")
    assert old_refresh and old_csrf
    user = await db.scalar(select(User).where(User.email == SETUP["admin_email"]))
    assert user
    key = generate_encryption_key()
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY_ID", "primary")
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", key)
    monkeypatch.setattr(
        settings, "MFA_RECOVERY_PEPPER", base64.urlsafe_b64encode(b"r" * 32).decode()
    )
    now = datetime.now(UTC)
    db.add(
        StaffMfaFactor(
            user_id=user.id,
            encrypted_secret=encrypt_totp_secret(
                SECRET, user_id=user.id, key_id="primary", encoded_key=key
            ),
            key_id="primary",
            enrolled_at=now,
            created_at=now,
        )
    )
    await db.commit()
    return old_access, old_refresh, old_csrf


async def challenge(client: AsyncClient) -> str:
    response = await client.post(
        f"{PATH}/login",
        data={"username": SETUP["admin_email"], "password": SETUP["admin_password"]},
    )
    assert response.status_code == 200
    assert response.json()["mfa_required"] is True
    assert "access_token" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    return response.json()["challenge"]


@pytest.mark.asyncio
async def test_enrolled_account_requires_mfa_on_access_refresh_and_login(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_access, old_refresh, old_csrf = await enroll(client, db_session, monkeypatch)
    old_me = await client.get(f"{PATH}/me", headers={"Authorization": f"Bearer {old_access}"})
    assert old_me.status_code == 401
    old_session = await client.post(f"{PATH}/refresh", headers={"X-DentalPin-CSRF-Token": old_csrf})
    assert old_session.status_code == 401
    assert client.cookies.get("dentalpin_refresh") == old_refresh

    client.cookies.clear()
    token = await challenge(client)
    assert client.cookies.get("dentalpin_refresh") is None
    used_code = current_code()
    completed = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": token, "code": used_code}
    )
    assert completed.status_code == 200
    assert completed.json()["token_type"] == "bearer"
    assert client.cookies.get("dentalpin_refresh")
    me = await client.get(
        f"{PATH}/me", headers={"Authorization": f"Bearer {completed.json()['access_token']}"}
    )
    assert me.status_code == 200
    refreshed = await client.post(
        f"{PATH}/refresh",
        headers={"X-DentalPin-CSRF-Token": client.cookies.get("dentalpin_csrf")},
    )
    assert refreshed.status_code == 200

    replay = await client.post(f"{PATH}/mfa/complete", json={"challenge": token, "code": used_code})
    assert replay.status_code == 401
    repeated_code = await challenge(client)
    repeated = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": repeated_code, "code": used_code}
    )
    assert repeated.status_code == 401
    events = (
        await db_session.scalars(select(StaffMfaAuditEvent).order_by(StaffMfaAuditEvent.created_at))
    ).all()
    assert [event.event_type for event in events] == [
        "login_challenge_issued",
        "login_totp_verified",
        "login_challenge_issued",
        "login_code_rejected",
    ]


@pytest.mark.asyncio
async def test_challenge_expires_and_limits_wrong_codes(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await enroll(client, db_session, monkeypatch)
    token = await challenge(client)
    for _ in range(5):
        result = await client.post(
            f"{PATH}/mfa/complete", json={"challenge": token, "code": "not-a-code"}
        )
        assert result.status_code == 401
    locked = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": token, "code": current_code()}
    )
    assert locked.status_code == 401
    record = await db_session.scalar(
        select(StaffMfaChallenge).where(StaffMfaChallenge.attempts == 5)
    )
    assert record and record.consumed_at is None

    another = await challenge(client)
    record = await db_session.scalar(
        select(StaffMfaChallenge).where(StaffMfaChallenge.challenge_hash != record.challenge_hash)
    )
    assert record
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    expired = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": another, "code": current_code()}
    )
    assert expired.status_code == 401


@pytest.mark.asyncio
async def test_new_challenges_cannot_reset_the_account_guess_budget(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await enroll(client, db_session, monkeypatch)
    for _ in range(2):
        token = await challenge(client)
        for _ in range(5):
            wrong = await client.post(
                f"{PATH}/mfa/complete", json={"challenge": token, "code": "not-a-code"}
            )
            assert wrong.status_code == 401

    fresh = await challenge(client)
    blocked = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": fresh, "code": current_code()}
    )
    assert blocked.status_code == 429
    records = (await db_session.scalars(select(StaffMfaChallenge))).all()
    assert sorted(record.attempts for record in records) == [0, 5, 5]

    # Aging the exhausted challenges out of the account window re-enables a
    # still-valid challenge without bypassing its own expiry or attempt limit.
    for record in records:
        if record.attempts:
            record.created_at = datetime.now(UTC) - timedelta(minutes=11)
    await db_session.commit()
    completed = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": fresh, "code": current_code()}
    )
    assert completed.status_code == 200


@pytest.mark.asyncio
async def test_recovery_code_is_consumed_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await enroll(client, db_session, monkeypatch)
    user = await db_session.scalar(select(User).where(User.email == SETUP["admin_email"]))
    assert user
    code = generate_recovery_codes(1)[0]
    db_session.add(
        StaffMfaRecoveryCode(
            user_id=user.id,
            code_hash=hash_recovery_code(code, pepper=b"r" * 32),
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    first = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": await challenge(client), "code": code}
    )
    assert first.status_code == 200
    second = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": await challenge(client), "code": code}
    )
    assert second.status_code == 401
    sessions = (await db_session.scalars(select(RefreshSession))).all()
    assert len([session for session in sessions if session.mfa_verified_at is not None]) == 1
