from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .handoff_staff_schemas import StaffHandoffResponse
from .handoff_staff_service import StaffHandoffService
from .models import PatientAgentSession

handoff_staff_router = APIRouter(prefix="/staff/handoffs", tags=["patient-agent-handoff"])


@handoff_staff_router.get(
    "",
    response_model=ApiResponse[list[StaffHandoffResponse]],
)
async def list_staff_handoffs(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.session.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[StaffHandoffResponse]]:
    sessions = await StaffHandoffService().list_pending(db=db, clinic_id=ctx.clinic_id)
    return ApiResponse(data=[_handoff_response(session) for session in sessions])


@handoff_staff_router.get(
    "/{session_id}",
    response_model=ApiResponse[StaffHandoffResponse],
)
async def get_staff_handoff(
    session_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.session.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[StaffHandoffResponse]:
    session = await StaffHandoffService().get_handoff(
        db=db,
        clinic_id=ctx.clinic_id,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient handoff not found")
    return ApiResponse(data=_handoff_response(session))


@handoff_staff_router.post(
    "/{session_id}/accept",
    response_model=ApiResponse[StaffHandoffResponse],
)
async def accept_staff_handoff(
    session_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.handoff.accept"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[StaffHandoffResponse]:
    try:
        session = await StaffHandoffService().accept(
            db=db,
            clinic_id=ctx.clinic_id,
            session_id=session_id,
            actor_user_id=ctx.user_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient handoff not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=_handoff_response(session))


def _handoff_response(session: PatientAgentSession) -> StaffHandoffResponse:
    context = session.context or {}
    return StaffHandoffResponse(
        session_id=session.id,
        patient_id=session.patient_id,
        channel=session.channel,
        handoff_state=session.handoff_state,
        urgency=context.get("handoff_urgency"),
        summary=context.get("handoff_summary"),
        accepted_by=context.get("handoff_accepted_by"),
        accepted_at=context.get("handoff_accepted_at"),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
