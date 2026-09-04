from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.patient_agent.confirmation import (
    create_appointment_confirmation_token,
    decode_appointment_confirmation_token,
)


def test_confirmation_token_is_bound_to_patient_clinic_professional_and_slot() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()
    professional_id = uuid4()
    starts_at = datetime.now(UTC) + timedelta(days=1)
    ends_at = starts_at + timedelta(minutes=30)

    token = create_appointment_confirmation_token(
        clinic_id=clinic_id,
        patient_id=patient_id,
        professional_id=professional_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    claims = decode_appointment_confirmation_token(
        token,
        clinic_id=clinic_id,
        patient_id=patient_id,
    )

    assert claims["professional_id"] == str(professional_id)
    assert claims["starts_at"] == starts_at.isoformat()
    assert claims["ends_at"] == ends_at.isoformat()


def test_confirmation_token_rejects_cross_patient_scope() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()
    starts_at = datetime.now(UTC) + timedelta(days=1)
    token = create_appointment_confirmation_token(
        clinic_id=clinic_id,
        patient_id=patient_id,
        professional_id=uuid4(),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
    )

    with pytest.raises(PermissionError):
        decode_appointment_confirmation_token(
            token,
            clinic_id=clinic_id,
            patient_id=uuid4(),
        )


def test_confirmation_token_rejects_cross_clinic_scope() -> None:
    patient_id = uuid4()
    starts_at = datetime.now(UTC) + timedelta(days=1)
    token = create_appointment_confirmation_token(
        clinic_id=uuid4(),
        patient_id=patient_id,
        professional_id=uuid4(),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
    )

    with pytest.raises(PermissionError):
        decode_appointment_confirmation_token(
            token,
            clinic_id=uuid4(),
            patient_id=patient_id,
        )
