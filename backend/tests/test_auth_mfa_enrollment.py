"""Staff authenticator enrollment requires a password and confirmed seed."""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.mfa import _totp_for_step, generate_encryption_key
from app.core.auth.models import (
    RefreshSession,
    StaffMfaAuditEvent,
    StaffMfaChallenge,
    StaffMfaFactor,
    StaffMfaRecoveryCode,
    User,
)
from app.core.auth.service import decode_token

PATH = "/api/v1/auth"
PASSWORD = "Secure Staff Passphrase 2026"
SETUP = {
    "admin_first_name": "Admin",
    "admin_last_name": "User",
    "admin_email": "admin@example.com",
    "admin_password": PASSWORD,
    "clinic_name": "My Clinic",
    "clinic_tax_id": "B12345678",
}


async def setup(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY_ID", "primary")
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", generate_encryption_key())
    monkeypatch.setattr(
        settings, "MFA_RECOVERY_PEPPER", base64.urlsafe_b64encode(b"r" * 32).decode()
    )
    response = await client.post(
        f"{PATH}/setup",
        json=SETUP,
        headers={"X-DentalPin-Setup-Token": settings.SETUP_TOKEN},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def code_for(secret: str) -> str:
    raw = base64.b32decode(secret)
    return _totp_for_step(raw, int(datetime.now(UTC).timestamp()) // 30)


@pytest.mark.asyncio
async def test_recovery_rotation_requires_step_up_and_invalidates_old_codes(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await setup(client, monkeypatch)
    started = (
        await client.post(f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers)
    ).json()
    confirmed = await client.post(
        f"{PATH}/mfa/enroll/confirm",
        json={"challenge": started["challenge"], "code": code_for(started["secret"])},
        headers=headers,
    )
    assert confirmed.status_code == 200
    old_codes = confirmed.json()["recovery_codes"]
    verified = {"Authorization": f"Bearer {confirmed.json()['access_token']}"}
    next_step = int(datetime.now(UTC).timestamp()) // 30 + 1
    next_code = _totp_for_step(base64.b32decode(started["secret"]), next_step)
    url = f"{PATH}/mfa/recovery/rotate"

    assert (
        await client.post(url, json={"password": PASSWORD, "code": next_code}, headers=headers)
    ).status_code == 401

    assert (
        await client.post(url, json={"password": "wrong", "code": next_code}, headers=verified)
    ).status_code == 401
    assert (
        await client.post(url, json={"password": PASSWORD, "code": "xxxxxx"}, headers=verified)
    ).status_code == 401
    assert (await client.get(f"{PATH}/mfa/status", headers=verified)).json()[
        "recovery_codes_remaining"
    ] == 10

    rotated = await client.post(
        url, json={"password": PASSWORD, "code": next_code}, headers=verified
    )
    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    new_codes = rotated.json()["recovery_codes"]
    assert len(set(new_codes)) == 10 and not set(new_codes).intersection(old_codes)
    stored = (await db_session.scalars(select(StaffMfaRecoveryCode))).all()
    assert len(stored) == 10
    assert all(old not in row.code_hash for old in old_codes for row in stored)
    assert (
        await client.post(url, json={"password": PASSWORD, "code": next_code}, headers=verified)
    ).status_code == 401

    async def pending_login() -> str:
        response = await client.post(
            f"{PATH}/login", data={"username": SETUP["admin_email"], "password": PASSWORD}
        )
        assert response.status_code == 200
        return response.json()["challenge"]

    rejected = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": await pending_login(), "code": old_codes[0]}
    )
    assert rejected.status_code == 401
    accepted = await client.post(
        f"{PATH}/mfa/complete", json={"challenge": await pending_login(), "code": new_codes[0]}
    )
    assert accepted.status_code == 200
    events = (
        await db_session.scalars(select(StaffMfaAuditEvent).order_by(StaffMfaAuditEvent.created_at))
    ).all()
    types = [event.event_type for event in events]
    assert types.count("recovery_rotation_rejected") == 3
    assert types.count("recovery_codes_rotated") == 1
    assert types.count("login_recovery_code_used") == 1
    assert "login_code_rejected" in types
    assert all(event.user_id and event.created_at for event in events)
    # The audit schema has no free-form payload for codes, seeds, or passwords.
    assert set(StaffMfaAuditEvent.__table__.columns.keys()) == {
        "id",
        "user_id",
        "event_type",
        "created_at",
    }


@pytest.mark.asyncio
async def test_enrollment_revokes_old_sessions_and_returns_recovery_codes_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await setup(client, monkeypatch)
    initial_status = await client.get(f"{PATH}/mfa/status", headers=headers)
    assert initial_status.status_code == 200
    assert initial_status.json() == {"enrolled": False, "recovery_codes_remaining": 0}
    old_refresh = client.cookies.get("dentalpin_refresh")
    old_csrf = client.cookies.get("dentalpin_csrf")
    assert old_refresh and old_csrf

    started = await client.post(
        f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers
    )
    assert started.status_code == 200
    assert started.headers["cache-control"] == "no-store"
    payload = started.json()
    assert payload["secret"] in payload["provisioning_uri"]
    assert "admin%40example.com" in payload["provisioning_uri"]
    factor = await db_session.scalar(select(StaffMfaFactor))
    assert factor and factor.enrolled_at is None and factor.pending_expires_at
    assert payload["secret"] not in factor.encrypted_secret
    assert client.cookies.get("dentalpin_refresh") == old_refresh

    confirmed = await client.post(
        f"{PATH}/mfa/enroll/confirm",
        json={"challenge": payload["challenge"], "code": code_for(payload["secret"])},
        headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.headers["cache-control"] == "no-store"
    codes = confirmed.json()["recovery_codes"]
    assert len(codes) == len(set(codes)) == 10
    assert all(len(code.replace("-", "")) == 32 for code in codes)
    stored = (await db_session.scalars(select(StaffMfaRecoveryCode))).all()
    assert len(stored) == 10
    assert all(code not in row.code_hash for code in codes for row in stored)
    await db_session.refresh(factor)
    assert factor.enrolled_at and factor.pending_expires_at is None
    assert factor.last_accepted_step is not None
    events = (
        await db_session.scalars(select(StaffMfaAuditEvent).order_by(StaffMfaAuditEvent.created_at))
    ).all()
    assert [event.event_type for event in events] == ["enrollment_started", "enrollment_completed"]

    old_token = await client.get(f"{PATH}/me", headers=headers)
    assert old_token.status_code == 401
    fresh_headers = {"Authorization": f"Bearer {confirmed.json()['access_token']}"}
    assert (await client.get(f"{PATH}/me", headers=fresh_headers)).status_code == 200
    status_response = await client.get(f"{PATH}/mfa/status", headers=fresh_headers)
    assert status_response.json() == {"enrolled": True, "recovery_codes_remaining": 10}
    client.cookies.set("dentalpin_refresh", old_refresh)
    client.cookies.set("dentalpin_csrf", old_csrf)
    assert (
        await client.post(f"{PATH}/refresh", headers={"X-DentalPin-CSRF-Token": old_csrf})
    ).status_code == 401
    sessions = (await db_session.scalars(select(RefreshSession))).all()
    prior_id = decode_token(old_refresh)["sid"]
    assert next(row for row in sessions if str(row.id) == prior_id).revoked_at
    assert len([row for row in sessions if row.mfa_verified_at and not row.revoked_at]) == 1

    assert (
        await client.post(
            f"{PATH}/mfa/enroll/confirm",
            json={"challenge": payload["challenge"], "code": code_for(payload["secret"])},
            headers=fresh_headers,
        )
    ).status_code == 401
    assert (
        await client.post(
            f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=fresh_headers
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_enrollment_requires_password_and_configured_keys(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await setup(client, monkeypatch)
    bad = await client.post(f"{PATH}/mfa/enroll/start", json={"password": "wrong"}, headers=headers)
    assert bad.status_code == 401
    assert await db_session.scalar(select(StaffMfaFactor)) is None
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", "")
    unavailable = await client.post(
        f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers
    )
    assert unavailable.status_code == 503
    assert await db_session.scalar(select(StaffMfaFactor)) is None
    unauthenticated = await client.post(f"{PATH}/mfa/enroll/start", json={"password": PASSWORD})
    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def test_restarting_enrollment_invalidates_prior_challenge(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await setup(client, monkeypatch)
    first = (
        await client.post(f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers)
    ).json()
    second = (
        await client.post(f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers)
    ).json()
    old = await client.post(
        f"{PATH}/mfa/enroll/confirm",
        json={"challenge": first["challenge"], "code": code_for(second["secret"])},
        headers=headers,
    )
    assert old.status_code == 401
    rows = (await db_session.scalars(select(StaffMfaChallenge))).all()
    assert len(rows) == 2 and len([row for row in rows if row.consumed_at]) == 1
    assert (
        await client.post(
            f"{PATH}/mfa/enroll/confirm",
            json={"challenge": second["challenge"], "code": code_for(second["secret"])},
            headers=headers,
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_enrollment_attempt_limit_and_factor_expiry(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await setup(client, monkeypatch)
    started = (
        await client.post(f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers)
    ).json()
    for _ in range(5):
        wrong = await client.post(
            f"{PATH}/mfa/enroll/confirm",
            json={"challenge": started["challenge"], "code": "xxxxxx"},
            headers=headers,
        )
        assert wrong.status_code == 401
    assert (
        await client.post(
            f"{PATH}/mfa/enroll/confirm",
            json={"challenge": started["challenge"], "code": code_for(started["secret"])},
            headers=headers,
        )
    ).status_code == 401
    record = await db_session.scalar(select(StaffMfaChallenge))
    assert record and record.attempts == 5

    next_started = (
        await client.post(f"{PATH}/mfa/enroll/start", json={"password": PASSWORD}, headers=headers)
    ).json()
    factor = await db_session.scalar(select(StaffMfaFactor))
    assert factor
    factor.pending_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    expired = await client.post(
        f"{PATH}/mfa/enroll/confirm",
        json={"challenge": next_started["challenge"], "code": code_for(next_started["secret"])},
        headers=headers,
    )
    assert expired.status_code == 401
    user = await db_session.scalar(select(User).where(User.email == SETUP["admin_email"]))
    assert user and user.token_version == 0
