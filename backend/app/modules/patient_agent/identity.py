"""Signed patient-session identity for the patient-facing AI surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt

from app.config import settings

PATIENT_TOKEN_TYPE = "patient_agent"
PATIENT_TOKEN_TTL_MINUTES = 15


@dataclass(frozen=True)
class PatientPrincipal:
    patient_id: UUID
    clinic_id: UUID
    expires_at: datetime


def create_patient_session_token(*, patient_id: UUID, clinic_id: UUID) -> str:
    """Create a short-lived token after an upstream patient-authentication flow succeeds.

    AI-1 intentionally does not implement patient enrollment/login. Callers must
    only mint this token after verifying the patient through the future portal
    authentication flow.
    """
    expires_at = datetime.now(UTC) + timedelta(minutes=PATIENT_TOKEN_TTL_MINUTES)
    payload = {
        "sub": str(patient_id),
        "clinic_id": str(clinic_id),
        "type": PATIENT_TOKEN_TYPE,
        "aud": "dentalpin-patient-agent",
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_patient_session_token(token: str) -> PatientPrincipal:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience="dentalpin-patient-agent",
        )
        if payload.get("type") != PATIENT_TOKEN_TYPE:
            raise ValueError("wrong token type")
        patient_id = UUID(str(payload["sub"]))
        clinic_id = UUID(str(payload["clinic_id"]))
        expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid or expired patient session token") from exc
    return PatientPrincipal(patient_id=patient_id, clinic_id=clinic_id, expires_at=expires_at)
