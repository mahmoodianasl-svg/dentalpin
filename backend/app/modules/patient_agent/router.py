from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .agenda_adapter import DentalPinPatientAppointmentAdapter
from .confirmation import (
    create_appointment_confirmation_token,
    decode_appointment_confirmation_token,
)
from .dental_knowledge_persistence import DatabaseDentalKnowledgeRetriever
from .dependencies import get_patient_principal
from .identity import PatientPrincipal
from .models import (
    PatientAgentAppointmentProposal,
    PatientAgentAuditEvent,
    PatientAgentSession,
)
from .providers.openai_realtime import OpenAIRealtimeProvider
from .safety import AgentRiskLevel
from .schemas import (
    AppointmentAvailabilityRequest,
    AppointmentConfirmedResponse,
    AppointmentConfirmRequest,
    AppointmentProposalRequest,
    AppointmentProposalResponse,
    AppointmentSlotResponse,
    FoundationStatus,
    HumanHandoffRequest,
    IntakeRiskAssessmentRequest,
    IntakeRiskAssessmentResponse,
    PatientDentalKnowledgeSearchRequest,
    PatientDentalKnowledgeSearchResponse,
    PatientDentalKnowledgeSource,
    RealtimeSessionCreate,
    RealtimeSessionCreated,
    RealtimeSessionEnded,
    VisualSnapshotConsentRevoked,
    VisualSnapshotShareAuthorization,
    VisualSnapshotShareRequest,
)
from .service import PatientAgentService
from .tools import AppointmentSlot

router = APIRouter()


@router.get("/foundation", response_model=ApiResponse[FoundationStatus])
async def foundation_status(
    _: Annotated[None, Depends(require_permission("patient_agent.configure"))],
) -> ApiResponse[FoundationStatus]:
    return ApiResponse(data=FoundationStatus())


@router.post("/patient/sessions", response_model=ApiResponse[RealtimeSessionCreated])
async def create_patient_realtime_session(
    payload: RealtimeSessionCreate,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RealtimeSessionCreated]:
    service = PatientAgentService(OpenAIRealtimeProvider())
    try:
        session, client_secret, expires_at = await service.start_session(
            db=db,
            principal=principal,
            channel=payload.channel,
            locale=payload.locale,
            ai_consent=payload.ai_consent,
            audio_consent=payload.audio_consent,
            video_consent=payload.video_consent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Realtime patient assistant is not configured",
        ) from exc
    return ApiResponse(
        data=RealtimeSessionCreated(
            session_id=session.id,
            channel=payload.channel,
            provider=session.provider or "unknown",
            client_secret=client_secret,
            expires_at_epoch=expires_at,
        )
    )


@router.post(
    "/patient/sessions/{session_id}/end",
    response_model=ApiResponse[RealtimeSessionEnded],
)
async def end_patient_realtime_session(
    session_id: UUID,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RealtimeSessionEnded]:
    result = await db.execute(
        select(PatientAgentSession)
        .where(
            PatientAgentSession.id == session_id,
            PatientAgentSession.clinic_id == principal.clinic_id,
            PatientAgentSession.patient_id == principal.patient_id,
        )
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    service = PatientAgentService(OpenAIRealtimeProvider())
    ended_at = await service.end_session(db=db, principal=principal, session=session)
    return ApiResponse(data=RealtimeSessionEnded(session_id=session.id, ended_at=ended_at))


@router.post(
    "/patient/sessions/{session_id}/visual-snapshot-consent/revoke",
    response_model=ApiResponse[VisualSnapshotConsentRevoked],
)
async def revoke_patient_visual_snapshot_consent(
    session_id: UUID,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[VisualSnapshotConsentRevoked]:
    result = await db.execute(
        select(PatientAgentSession)
        .where(
            PatientAgentSession.id == session_id,
            PatientAgentSession.clinic_id == principal.clinic_id,
            PatientAgentSession.patient_id == principal.patient_id,
        )
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    service = PatientAgentService(OpenAIRealtimeProvider())
    try:
        await service.revoke_visual_snapshot_consent(
            db=db,
            principal=principal,
            session=session,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ApiResponse(data=VisualSnapshotConsentRevoked(session_id=session.id))


@router.post(
    "/patient/sessions/{session_id}/visual-snapshots/authorize",
    response_model=ApiResponse[VisualSnapshotShareAuthorization],
)
async def authorize_patient_visual_snapshot(
    session_id: UUID,
    payload: VisualSnapshotShareRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[VisualSnapshotShareAuthorization]:
    result = await db.execute(
        select(PatientAgentSession)
        .where(
            PatientAgentSession.id == session_id,
            PatientAgentSession.clinic_id == principal.clinic_id,
            PatientAgentSession.patient_id == principal.patient_id,
        )
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    service = PatientAgentService(OpenAIRealtimeProvider())
    try:
        snapshot_id = await service.authorize_visual_snapshot_share(
            db=db,
            principal=principal,
            session=session,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ApiResponse(data=VisualSnapshotShareAuthorization(snapshot_id=snapshot_id))


@router.post(
    "/patient/sessions/{session_id}/intake-risk/assess",
    response_model=ApiResponse[IntakeRiskAssessmentResponse],
)
async def assess_patient_intake_risk(
    session_id: UUID,
    payload: IntakeRiskAssessmentRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[IntakeRiskAssessmentResponse]:
    result = await db.execute(
        select(PatientAgentSession)
        .where(
            PatientAgentSession.id == session_id,
            PatientAgentSession.clinic_id == principal.clinic_id,
            PatientAgentSession.patient_id == principal.patient_id,
        )
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    service = PatientAgentService(OpenAIRealtimeProvider())
    try:
        urgency = await service.assess_intake_risk(
            db=db,
            principal=principal,
            session=session,
            reason=payload.reason,
            signals=frozenset(payload.signals),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    must_handoff = urgency.value in {"urgent", "emergency_escalation"}
    return ApiResponse(
        data=IntakeRiskAssessmentResponse(
            session_id=session.id,
            urgency=urgency.value,
            must_handoff=must_handoff,
            handoff_state=session.handoff_state,
        )
    )


@router.post(
    "/patient/knowledge/search",
    response_model=ApiResponse[PatientDentalKnowledgeSearchResponse],
)
async def patient_dental_knowledge_search(
    payload: PatientDentalKnowledgeSearchRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientDentalKnowledgeSearchResponse]:
    retriever = DatabaseDentalKnowledgeRetriever(db=db, clinic_id=principal.clinic_id)
    entries = await retriever.search(
        query=payload.query,
        locale=payload.locale,
        topic=payload.topic,
        limit=payload.limit,
    )
    sources = [
        PatientDentalKnowledgeSource(
            entry_id=entry.entry_id,
            topic=entry.topic,
            title=entry.title,
            content=entry.content,
            source_name=entry.source_name,
            source_reference=entry.source_reference,
            locale=entry.locale,
        )
        for entry in entries
    ]
    fallback_required = not sources
    db.add(
        PatientAgentAuditEvent(
            session_id=None,
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            event_type="patient_knowledge_search_completed",
            actor_type="system",
            outcome="fallback" if fallback_required else "success",
            detail={
                "tool_name": "search_patient_dental_knowledge",
                "result_count": len(sources),
                "fallback_required": fallback_required,
                "locale": payload.locale,
                "topic": payload.topic.value if payload.topic is not None else None,
                "query_length": len(payload.query.strip()),
                "patient_education_only": True,
            },
            reason="Clinic-approved patient education knowledge lookup",
        )
    )
    await db.flush()
    return ApiResponse(
        data=PatientDentalKnowledgeSearchResponse(
            sources=sources,
            fallback_required=fallback_required,
        )
    )


@router.post(
    "/patient/appointments/availability",
    response_model=ApiResponse[list[AppointmentSlotResponse]],
)
async def patient_appointment_availability(
    payload: AppointmentAvailabilityRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AppointmentSlotResponse]]:
    if payload.ends_before <= payload.starts_after:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time range")
    adapter = DentalPinPatientAppointmentAdapter(db)
    try:
        slots = await adapter.search_available_slots(
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            starts_after=payload.starts_after,
            ends_before=payload.ends_before,
            professional_id=payload.professional_id,
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Availability not found"
        ) from exc
    return ApiResponse(
        data=[
            AppointmentSlotResponse(
                professional_id=slot.professional_id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
            )
            for slot in slots
        ]
    )


@router.post(
    "/patient/appointments/proposal",
    response_model=ApiResponse[AppointmentProposalResponse],
)
async def propose_patient_appointment(
    payload: AppointmentProposalRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentProposalResponse]:
    adapter = DentalPinPatientAppointmentAdapter(db)
    try:
        slot = await adapter.validate_slot_available(
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            slot=AppointmentSlot(
                professional_id=payload.professional_id,
                starts_at=payload.starts_at,
                ends_at=payload.ends_at,
            ),
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    token = create_appointment_confirmation_token(
        clinic_id=principal.clinic_id,
        patient_id=principal.patient_id,
        professional_id=slot.professional_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
    )
    claims = decode_appointment_confirmation_token(
        token,
        clinic_id=principal.clinic_id,
        patient_id=principal.patient_id,
    )
    expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
    proposal = PatientAgentAppointmentProposal(
        jti=claims["jti"],
        clinic_id=principal.clinic_id,
        patient_id=principal.patient_id,
        professional_id=slot.professional_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        expires_at=expires_at,
    )
    db.add(proposal)
    db.add(
        PatientAgentAuditEvent(
            session_id=None,
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            event_type="appointment_proposal_created",
            actor_type="patient",
            outcome="recorded",
            detail={
                "proposal_jti": proposal.jti,
                "professional_id": str(slot.professional_id),
                "starts_at": slot.starts_at.isoformat(),
                "ends_at": slot.ends_at.isoformat(),
            },
        )
    )
    await db.flush()
    return ApiResponse(
        data=AppointmentProposalResponse(
            slot=AppointmentSlotResponse(
                professional_id=slot.professional_id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
            ),
            confirmation_token=token,
        )
    )


@router.post(
    "/patient/appointments/confirm",
    response_model=ApiResponse[AppointmentConfirmedResponse],
)
async def confirm_patient_appointment(
    payload: AppointmentConfirmRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AppointmentConfirmedResponse]:
    adapter = DentalPinPatientAppointmentAdapter(db)
    slot = AppointmentSlot(
        professional_id=payload.professional_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    try:
        appointment_id = await adapter.create_appointment(
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            slot=slot,
            confirmation_token=payload.confirmation_token,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Confirmation rejected"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=AppointmentConfirmedResponse(appointment_id=appointment_id))


@router.post("/patient/sessions/{session_id}/handoff", response_model=ApiResponse[dict])
async def request_patient_handoff(
    session_id: UUID,
    payload: HumanHandoffRequest,
    principal: Annotated[PatientPrincipal, Depends(get_patient_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    result = await db.execute(
        select(PatientAgentSession).where(
            PatientAgentSession.id == session_id,
            PatientAgentSession.clinic_id == principal.clinic_id,
            PatientAgentSession.patient_id == principal.patient_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    service = PatientAgentService(OpenAIRealtimeProvider())
    await service.request_handoff(
        db=db,
        principal=principal,
        session=session,
        reason=payload.reason,
        urgency=AgentRiskLevel(payload.urgency),
    )
    return ApiResponse(data={"session_id": str(session_id), "handoff_state": session.handoff_state})
