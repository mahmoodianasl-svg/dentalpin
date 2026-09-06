from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.patient_agent.schemas import PatientPortalLoginRequest

portal_router_module = importlib.import_module("app.modules.patient_agent.patient_portal_router")


@pytest.mark.asyncio
async def test_patient_portal_login_returns_patient_agent_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clinic_id = uuid4()
    patient_id = uuid4()
    account = SimpleNamespace(patient_id=patient_id, clinic_id=clinic_id)

    async def fake_authenticate(*, db, clinic_id, email, password):  # noqa: ANN001
        assert db is not None
        assert clinic_id == clinic_id_expected
        assert email == "patient@example.com"
        assert password == "Strongpass1"
        return account, "signed-patient-agent-token"

    clinic_id_expected = clinic_id
    monkeypatch.setattr(
        portal_router_module,
        "authenticate_patient_portal_account",
        fake_authenticate,
    )

    response = await portal_router_module.login_patient_portal(
        PatientPortalLoginRequest(
            clinic_id=clinic_id,
            email="patient@example.com",
            password="Strongpass1",
        ),
        SimpleNamespace(),
    )

    assert response.data.patient_token == "signed-patient-agent-token"
    assert response.data.token_type == "bearer"
    assert response.data.expires_in_seconds == 900
    assert response.data.patient_id == patient_id
    assert response.data.clinic_id == clinic_id


@pytest.mark.asyncio
async def test_patient_portal_login_hides_credential_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_authenticate(**kwargs):  # noqa: ANN003
        del kwargs
        raise ValueError("account inactive")

    monkeypatch.setattr(
        portal_router_module,
        "authenticate_patient_portal_account",
        fake_authenticate,
    )

    with pytest.raises(HTTPException) as exc_info:
        await portal_router_module.login_patient_portal(
            PatientPortalLoginRequest(
                clinic_id=uuid4(),
                email="patient@example.com",
                password="Strongpass1",
            ),
            SimpleNamespace(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid portal credentials"


def test_patient_portal_login_requires_strong_minimum_payload() -> None:
    with pytest.raises(ValueError):
        PatientPortalLoginRequest(
            clinic_id=uuid4(),
            email="a",
            password="short",
        )
