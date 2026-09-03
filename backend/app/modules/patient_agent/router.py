from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .agenda_adapter import DentalPinPatientAppointmentAdapter
from .confirmation import create_appointment_confirmation_token
from .dependencies import get_patient_principal
from .identity import PatientPrincipal
from .models import PatientAgentSession
from .providers.openai_realtime import OpenAIRealtimeProvider
from .schemas import (
    AppointmentAvailabilityRequest,
    AppointmentConfirmedResponse,
    AppointmentConfirmRequest,
    AppointmentProposalRequest,
    AppointmentProposalResponse,
    AppointmentSlotResponse,
    FoundationStatus,
    HumanHandoffRequest,
    RealtimeSessionCreate,
    RealtimeSessionCreated,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability not found") from exc
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
) -> ApiResponse[AppointmentProposalResponse]:
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid appointment slot")
    token = create_appointment_confirmation_token(
        clinic_id=principal.clinic_id,
        patient_id=principal.patient_id,
        professional_id=payload.professional_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    return ApiResponse(
        data=AppointmentProposalResponse(
            slot=AppointmentSlotResponse(
                professional_id=payload.professional_id,
                starts_at=payload.starts_at,
                ends_at=payload.ends_at,
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Confirmation rejected") from exc
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
    result = await db.execute(select(PatientAgentSession).where(PatientAgentSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    service = PatientAgentService(OpenAIRealtimeProvider())
    try:
        await service.request_handoff(
            db=db,
            principal=principal,
            session=session,
            reason=payload.reason,
            urgency=payload.urgency,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc
    return ApiResponse(data={"session_id": str(session_id), "handoff_state": "requested"})
