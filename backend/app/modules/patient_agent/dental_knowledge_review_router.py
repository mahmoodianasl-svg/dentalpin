from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .dental_knowledge_review_schemas import (
    DentalKnowledgeRejectDecision,
    DentalKnowledgeReviewDecision,
    DentalKnowledgeReviewResponse,
)
from .dental_knowledge_review_service import DentalKnowledgeReviewService
from .models import PatientAgentDentalKnowledge

review_router = APIRouter(prefix="/knowledge", tags=["patient-agent-knowledge"])


@review_router.get(
    "",
    response_model=ApiResponse[list[DentalKnowledgeReviewResponse]],
)
async def list_dental_knowledge(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.knowledge.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    review_status: str | None = None,
) -> ApiResponse[list[DentalKnowledgeReviewResponse]]:
    stmt = select(PatientAgentDentalKnowledge).where(
        PatientAgentDentalKnowledge.clinic_id == ctx.clinic_id
    )
    if review_status is not None:
        if review_status not in {"draft", "in_review", "approved", "rejected"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid review status",
            )
        stmt = stmt.where(PatientAgentDentalKnowledge.review_status == review_status)
    stmt = stmt.order_by(
        PatientAgentDentalKnowledge.entry_key.asc(),
        PatientAgentDentalKnowledge.version.desc(),
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return ApiResponse(
        data=[DentalKnowledgeReviewResponse.model_validate(record) for record in records]
    )


@review_router.get(
    "/{record_id}",
    response_model=ApiResponse[DentalKnowledgeReviewResponse],
)
async def get_dental_knowledge(
    record_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.knowledge.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalKnowledgeReviewResponse]:
    record = await DentalKnowledgeReviewService().get_record(
        db=db,
        clinic_id=ctx.clinic_id,
        record_id=record_id,
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge not found")
    return ApiResponse(data=DentalKnowledgeReviewResponse.model_validate(record))


@review_router.post(
    "/{record_id}/submit",
    response_model=ApiResponse[DentalKnowledgeReviewResponse],
)
async def submit_dental_knowledge_for_review(
    record_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.knowledge.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalKnowledgeReviewResponse]:
    record = await _transition(
        DentalKnowledgeReviewService().submit,
        db=db,
        clinic_id=ctx.clinic_id,
        record_id=record_id,
        actor_user_id=ctx.user_id,
    )
    return ApiResponse(data=DentalKnowledgeReviewResponse.model_validate(record))


@review_router.post(
    "/{record_id}/approve",
    response_model=ApiResponse[DentalKnowledgeReviewResponse],
)
async def approve_dental_knowledge(
    record_id: UUID,
    payload: DentalKnowledgeReviewDecision,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.knowledge.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalKnowledgeReviewResponse]:
    record = await _transition(
        DentalKnowledgeReviewService().approve,
        db=db,
        clinic_id=ctx.clinic_id,
        record_id=record_id,
        actor_user_id=ctx.user_id,
        decision_note=payload.decision_note,
    )
    return ApiResponse(data=DentalKnowledgeReviewResponse.model_validate(record))


@review_router.post(
    "/{record_id}/reject",
    response_model=ApiResponse[DentalKnowledgeReviewResponse],
)
async def reject_dental_knowledge(
    record_id: UUID,
    payload: DentalKnowledgeRejectDecision,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_agent.knowledge.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalKnowledgeReviewResponse]:
    record = await _transition(
        DentalKnowledgeReviewService().reject,
        db=db,
        clinic_id=ctx.clinic_id,
        record_id=record_id,
        actor_user_id=ctx.user_id,
        decision_note=payload.decision_note,
    )
    return ApiResponse(data=DentalKnowledgeReviewResponse.model_validate(record))


async def _transition(operation, **kwargs):
    try:
        return await operation(**kwargs)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
