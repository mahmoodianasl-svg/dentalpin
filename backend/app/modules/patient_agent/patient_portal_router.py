from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .patient_portal_auth import (
    authenticate_patient_portal_account,
    disable_patient_portal_account,
    enroll_patient_portal_account,
)
from .schemas import (
    PatientPortalAccountResponse,
    PatientPortalEnrollmentRequest,
    PatientPortalLoginRequest,
    PatientPortalLoginResponse,
)

portal_router = APIRouter(prefix="/portal")


@portal_router.post(
    "/enroll",
    response_model=ApiResponse[PatientPortalAccountResponse],
    status_code=status.HTTP_201_CREATED,
)
async def enroll_patient_portal(
    payload: PatientPortalEnrollmentRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientPortalAccountResponse]:
    try:
        account = await enroll_patient_portal_account(
            db=db,
            clinic_id=ctx.clinic_id,
            patient_id=payload.patient_id,
            email=payload.email,
            password=payload.password,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ApiResponse(
        data=PatientPortalAccountResponse(
            patient_id=account.patient_id,
            clinic_id=account.clinic_id,
            email=account.email,
            is_active=account.is_active,
        )
    )


@portal_router.post("/login", response_model=ApiResponse[PatientPortalLoginResponse])
async def login_patient_portal(
    payload: PatientPortalLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientPortalLoginResponse]:
    try:
        account, token = await authenticate_patient_portal_account(
            db=db,
            clinic_id=payload.clinic_id,
            email=payload.email,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid portal credentials",
        ) from exc

    return ApiResponse(
        data=PatientPortalLoginResponse(
            patient_token=token,
            patient_id=account.patient_id,
            clinic_id=account.clinic_id,
        )
    )


@portal_router.post(
    "/patients/{patient_id}/disable",
    response_model=ApiResponse[PatientPortalAccountResponse],
)
async def disable_patient_portal(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientPortalAccountResponse]:
    try:
        account = await disable_patient_portal_account(
            db=db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient portal account not found",
        ) from exc

    return ApiResponse(
        data=PatientPortalAccountResponse(
            patient_id=account.patient_id,
            clinic_id=account.clinic_id,
            email=account.email,
            is_active=account.is_active,
        )
    )
