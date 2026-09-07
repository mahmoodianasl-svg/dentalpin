from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.models import PatientAgentConsent
from app.modules.patient_agent.providers.base import (
    RealtimeAIProvider,
    RealtimeSessionDescriptor,
    RealtimeSessionRequest,
)
from app.modules.patient_agent.service import PatientAgentService
from app.modules.patients.models import Patient


class SuccessfulRealtimeProvider(RealtimeAIProvider):
    name = "test-provider"

    async def create_session(self, request: RealtimeSessionRequest) -> RealtimeSessionDescriptor:
        return RealtimeSessionDescriptor(
            provider=self.name,
            provider_session_ref=f"provider-{request.session_id}",
            client_secret="ephemeral-test-secret",
            expires_at_epoch=2_000_000_000,
        )

    async def close_session(self, provider_session_ref: str) -> None:
        del provider_session_ref


def _principal(*, clinic_id, patient_id) -> PatientPrincipal:  # noqa: ANN001
    return PatientPrincipal(
        patient_id=patient_id,
        clinic_id=clinic_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@pytest.mark.asyncio
async def test_voice_session_persists_snapshot_scoped_visual_consent(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    service = PatientAgentService(SuccessfulRealtimeProvider())
    session, _, _ = await service.start_session(
        db=db_session,
        principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
        channel="voice",
        locale="en",
        ai_consent=True,
        audio_consent=True,
        video_consent=True,
    )

    consents = (
        await db_session.execute(
            select(PatientAgentConsent).where(PatientAgentConsent.session_id == session.id)
        )
    ).scalars().all()
    by_type = {consent.consent_type: consent for consent in consents}

    assert set(by_type) == {"ai", "audio", "video"}
    assert by_type["video"].granted is True
    assert by_type["video"].evidence == {
        "source": "patient_session",
        "scope": "visual_snapshot_only",
        "continuous_video": False,
    }


@pytest.mark.asyncio
async def test_voice_session_persists_visual_consent_denial_by_default(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    service = PatientAgentService(SuccessfulRealtimeProvider())
    session, _, _ = await service.start_session(
        db=db_session,
        principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
        channel="voice",
        locale="en",
        ai_consent=True,
        audio_consent=True,
        video_consent=False,
    )

    visual_consent = (
        await db_session.execute(
            select(PatientAgentConsent).where(
                PatientAgentConsent.session_id == session.id,
                PatientAgentConsent.consent_type == "video",
            )
        )
    ).scalar_one()

    assert visual_consent.granted is False
    assert visual_consent.evidence["scope"] == "visual_snapshot_only"
    assert visual_consent.evidence["continuous_video"] is False
