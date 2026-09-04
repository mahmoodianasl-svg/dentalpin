"""Short-lived, patient-bound confirmation tokens for appointment mutations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from jose import JWTError, jwt

from app.config import settings

_CONFIRMATION_TTL_MINUTES = 10
_CONFIRMATION_PURPOSE = "patient_agent_appointment_confirmation"


def create_appointment_confirmation_token(
    *,
    clinic_id: UUID,
    patient_id: UUID,
    professional_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "type": "patient_confirmation",
        "purpose": _CONFIRMATION_PURPOSE,
        "jti": uuid4().hex,
        "clinic_id": str(clinic_id),
        "patient_id": str(patient_id),
        "professional_id": str(professional_id),
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "iat": now,
        "exp": now + timedelta(minutes=_CONFIRMATION_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_appointment_confirmation_token(
    token: str,
    *,
    clinic_id: UUID,
    patient_id: UUID,
) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired confirmation token") from exc

    if (
        payload.get("type") != "patient_confirmation"
        or payload.get("purpose") != _CONFIRMATION_PURPOSE
    ):
        raise ValueError("Invalid appointment confirmation token")
    if not isinstance(payload.get("jti"), str) or not payload["jti"]:
        raise ValueError("Invalid appointment confirmation token")
    if payload.get("clinic_id") != str(clinic_id) or payload.get("patient_id") != str(patient_id):
        raise PermissionError("Confirmation token scope mismatch")
    return payload
