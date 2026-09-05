from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.service import hash_password, validate_password_strength, verify_password
from app.modules.patients.models import Patient

from .identity import create_patient_session_token
from .models import PatientPortalAccount


async def enroll_patient_portal_account(
    *,
    db: AsyncSession,
    clinic_id: UUID,
    patient_id: UUID,
    email: str,
    password: str,
) -> PatientPortalAccount:
    normalized_email = email.strip().lower()
    valid, reason = validate_password_strength(password)
    if not valid:
        raise ValueError(reason)

    patient = await db.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
    )
    if patient is None or patient.status != "active":
        raise LookupError("Patient not found")

    existing = await db.scalar(
        select(PatientPortalAccount).where(
            (PatientPortalAccount.patient_id == patient_id)
            | (
                (PatientPortalAccount.clinic_id == clinic_id)
                & (func.lower(PatientPortalAccount.email) == normalized_email)
            )
        )
    )
    if existing is not None:
        raise ValueError("Patient portal account already exists")

    account = PatientPortalAccount(
        clinic_id=clinic_id,
        patient_id=patient_id,
        email=normalized_email,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(account)
    await db.flush()
    return account


async def authenticate_patient_portal_account(
    *, db: AsyncSession, clinic_id: UUID, email: str, password: str
) -> tuple[PatientPortalAccount, str]:
    normalized_email = email.strip().lower()
    account = await db.scalar(
        select(PatientPortalAccount).where(
            PatientPortalAccount.clinic_id == clinic_id,
            func.lower(PatientPortalAccount.email) == normalized_email,
        )
    )
    if (
        account is None
        or not account.is_active
        or not verify_password(password, account.password_hash)
    ):
        raise ValueError("Invalid portal credentials")

    patient = await db.scalar(
        select(Patient).where(
            Patient.id == account.patient_id,
            Patient.clinic_id == clinic_id,
            Patient.status == "active",
        )
    )
    if patient is None:
        raise ValueError("Invalid portal credentials")

    account.last_login_at = datetime.now(UTC)
    token = create_patient_session_token(patient_id=account.patient_id, clinic_id=account.clinic_id)
    await db.flush()
    return account, token


async def disable_patient_portal_account(
    *, db: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> PatientPortalAccount:
    account = await db.scalar(
        select(PatientPortalAccount).where(
            PatientPortalAccount.clinic_id == clinic_id,
            PatientPortalAccount.patient_id == patient_id,
        )
    )
    if account is None:
        raise LookupError("Patient portal account not found")
    account.is_active = False
    account.token_version += 1
    await db.flush()
    return account
