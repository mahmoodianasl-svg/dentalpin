from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.auth.service import create_access_token
from app.modules.patient_agent.identity import (
    create_patient_session_token,
    decode_patient_session_token,
)
from app.modules.patient_agent.providers.base import RealtimeSessionRequest
from app.modules.patient_agent.providers.openai_realtime import OpenAIRealtimeProvider


def test_patient_token_binds_patient_and_clinic() -> None:
    patient_id = uuid4()
    clinic_id = uuid4()
    token = create_patient_session_token(patient_id=patient_id, clinic_id=clinic_id)
    principal = decode_patient_session_token(token)
    assert principal.patient_id == patient_id
    assert principal.clinic_id == clinic_id


def test_staff_access_token_cannot_be_used_as_patient_token() -> None:
    token = create_access_token(uuid4(), clinic_id=uuid4())
    with pytest.raises(ValueError, match="Invalid or expired patient session token"):
        decode_patient_session_token(token)


@pytest.mark.asyncio
async def test_realtime_provider_fails_closed_without_server_api_key() -> None:
    provider = OpenAIRealtimeProvider(api_key="")
    provider.api_key = None
    with pytest.raises(RuntimeError, match="not configured"):
        await provider.create_session(
            RealtimeSessionRequest(
                session_id=str(uuid4()),
                channel="voice",
                locale="en",
                modalities=("audio", "text"),
            )
        )


def test_patient_token_rejects_tampering() -> None:
    token = create_patient_session_token(patient_id=uuid4(), clinic_id=uuid4())
    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"
    with pytest.raises(ValueError, match="Invalid or expired patient session token"):
        decode_patient_session_token(tampered)
