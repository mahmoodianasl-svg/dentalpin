from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .dependencies import get_patient_principal
from .identity import PatientPrincipal
from .models import PatientAgentSession
from .providers.openai_realtime import OpenAIRealtimeProvider
from .schemas import (
    FoundationStatus,
    HumanHandoffRequest,
    RealtimeSessionCreate,
    RealtimeSessionCreated,
)
from .service import PatientAgentService

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
