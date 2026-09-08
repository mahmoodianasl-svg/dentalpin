from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.models import (
    PatientAgentAuditEvent,
    PatientAgentConsent,
    PatientAgentSession,
)
from app.modules.patient_agent.providers.base import (
    RealtimeAIProvider,
    RealtimeSessionDescriptor,
    RealtimeSessionRequest,
)
from app.modules.patient_agent.runtime_controls import (
    VISUAL_SNAPSHOT_SHARE_LIMIT,
    VisualSnapshotRateLimitExceeded,
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


async def _active_visual_session(
    *,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
    granted: bool = True,
) -> PatientAgentSession:
    session = PatientAgentSession(
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        channel="voice",
        status="active",
        authenticated=True,
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        PatientAgentConsent(
            session_id=session.id,
            clinic_id=test_clinic.id,
            patient_id=test_patient.id,
            consent_type="video",
            granted=granted,
            policy_version="patient-agent-safety-v1",
            evidence={
                "source": "patient_session",
                "scope": "visual_snapshot_only",
                "continuous_video": False,
            },
        )
    )
    await db_session.commit()
    return session


@pytest.mark.asyncio
async def test_visual_snapshot_share_requires_server_side_consent_and_audits_metadata_only(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_visual_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)
    service = PatientAgentService(SuccessfulRealtimeProvider())

    snapshot_id = await service.authorize_visual_snapshot_share(
        db=db_session,
        principal=principal,
        session=session,
        mime_type="image/png",
        size_bytes=2048,
    )
    await db_session.commit()

    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "visual_snapshot_share_authorized",
            )
        )
    ).scalar_one()
    assert audit.outcome == "authorized"
    assert audit.detail == {
        "snapshot_id": str(snapshot_id),
        "mime_type": "image/png",
        "size_bytes": 2048,
        "scope": "visual_snapshot_only",
        "media_content_persisted": False,
        "continuous_video": False,
    }
    assert "image_url" not in audit.detail
    assert "base64" not in str(audit.detail).lower()


@pytest.mark.asyncio
async def test_visual_snapshot_share_rejects_missing_consent_and_commits_denial_audit(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_visual_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
        granted=False,
    )
    service = PatientAgentService(SuccessfulRealtimeProvider())

    with pytest.raises(PermissionError, match="Visual snapshot consent"):
        await service.authorize_visual_snapshot_share(
            db=db_session,
            principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
            session=session,
            mime_type="image/jpeg",
            size_bytes=1024,
        )

    await db_session.rollback()

    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "visual_snapshot_share_denied",
            )
        )
    ).scalar_one()
    assert audit.outcome == "denied"
    assert audit.detail == {
        "reason": "snapshot_consent_missing",
        "mime_type": "image/jpeg",
        "size_bytes": 1024,
        "scope": "visual_snapshot_only",
        "media_content_persisted": False,
        "continuous_video": False,
    }
    assert "image_url" not in audit.detail
    assert "base64" not in str(audit.detail).lower()


@pytest.mark.asyncio
async def test_visual_snapshot_consent_revocation_blocks_future_authorization(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_visual_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)
    service = PatientAgentService(SuccessfulRealtimeProvider())

    await service.revoke_visual_snapshot_consent(
        db=db_session,
        principal=principal,
        session=session,
    )
    await db_session.commit()

    consents = (
        (
            await db_session.execute(
                select(PatientAgentConsent)
                .where(
                    PatientAgentConsent.session_id == session.id,
                    PatientAgentConsent.consent_type == "video",
                )
                .order_by(PatientAgentConsent.created_at, PatientAgentConsent.id)
            )
        )
        .scalars()
        .all()
    )
    assert [consent.granted for consent in consents] == [True, False]
    assert consents[-1].evidence["revoked_mid_session"] is True

    with pytest.raises(PermissionError, match="Visual snapshot consent"):
        await service.authorize_visual_snapshot_share(
            db=db_session,
            principal=principal,
            session=session,
            mime_type="image/png",
            size_bytes=1024,
        )


@pytest.mark.asyncio
async def test_visual_snapshot_consent_revocation_is_idempotent_and_audited_once(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_visual_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    principal = _principal(clinic_id=test_clinic.id, patient_id=test_patient.id)
    service = PatientAgentService(SuccessfulRealtimeProvider())

    await service.revoke_visual_snapshot_consent(
        db=db_session,
        principal=principal,
        session=session,
    )
    await db_session.commit()
    await service.revoke_visual_snapshot_consent(
        db=db_session,
        principal=principal,
        session=session,
    )
    await db_session.commit()

    revoked_consents = (
        (
            await db_session.execute(
                select(PatientAgentConsent).where(
                    PatientAgentConsent.session_id == session.id,
                    PatientAgentConsent.consent_type == "video",
                    PatientAgentConsent.granted.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    audits = (
        (
            await db_session.execute(
                select(PatientAgentAuditEvent).where(
                    PatientAgentAuditEvent.session_id == session.id,
                    PatientAgentAuditEvent.event_type == "visual_snapshot_consent_revoked",
                )
            )
        )
        .scalars()
        .all()
    )

    assert len(revoked_consents) == 1
    assert len(audits) == 1
    assert audits[0].outcome == "recorded"
    assert audits[0].detail == {
        "scope": "visual_snapshot_only",
        "media_content_persisted": False,
        "continuous_video": False,
    }


@pytest.mark.asyncio
async def test_visual_snapshot_consent_revocation_rejects_patient_scope_mismatch(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_visual_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    service = PatientAgentService(SuccessfulRealtimeProvider())

    with pytest.raises(PermissionError, match="scope mismatch"):
        await service.revoke_visual_snapshot_consent(
            db=db_session,
            principal=_principal(clinic_id=test_clinic.id, patient_id=uuid4()),
            session=session,
        )


@pytest.mark.asyncio
async def test_visual_snapshot_share_limit_is_session_scoped_and_audited(
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    session = await _active_visual_session(
        db_session=db_session,
        test_clinic=test_clinic,
        test_patient=test_patient,
    )
    now = datetime.now(UTC)
    for index in range(VISUAL_SNAPSHOT_SHARE_LIMIT):
        db_session.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=test_clinic.id,
                patient_id=test_patient.id,
                event_type="visual_snapshot_share_authorized",
                actor_type="patient",
                outcome="authorized",
                detail={"snapshot_id": f"prior-{index}"},
                created_at=now - timedelta(seconds=index),
            )
        )
    await db_session.commit()

    service = PatientAgentService(SuccessfulRealtimeProvider())
    with pytest.raises(VisualSnapshotRateLimitExceeded) as exc_info:
        await service.authorize_visual_snapshot_share(
            db=db_session,
            principal=_principal(clinic_id=test_clinic.id, patient_id=test_patient.id),
            session=session,
            mime_type="image/png",
            size_bytes=1024,
        )
    assert exc_info.value.status_code == 429
    assert int(exc_info.value.headers["Retry-After"]) >= 1

    audit = (
        await db_session.execute(
            select(PatientAgentAuditEvent).where(
                PatientAgentAuditEvent.session_id == session.id,
                PatientAgentAuditEvent.event_type == "visual_snapshot_rate_limited",
            )
        )
    ).scalar_one()
    assert audit.outcome == "denied"
    assert audit.detail["limit"] == VISUAL_SNAPSHOT_SHARE_LIMIT
    assert audit.detail["recent_shares"] == VISUAL_SNAPSHOT_SHARE_LIMIT
    assert audit.detail["media_content_persisted"] is False
