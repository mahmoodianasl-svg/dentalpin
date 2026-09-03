from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.dependencies import require_permission
from app.core.schemas import ApiResponse

from .schemas import FoundationStatus

router = APIRouter()


@router.get("/foundation", response_model=ApiResponse[FoundationStatus])
async def foundation_status(
    _: Annotated[None, Depends(require_permission("patient_agent.configure"))],
) -> ApiResponse[FoundationStatus]:
    """Expose the immutable AI-0 safety/capability contract to administrators.

    No realtime provider session is created in AI-0. This endpoint exists so
    UI/ops can verify the module contract before enabling later phases.
    """
    return ApiResponse(data=FoundationStatus())
