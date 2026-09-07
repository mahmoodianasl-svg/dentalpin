"""Operational safety controls for patient realtime sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .identity import PatientPrincipal
from .models import PatientAgentAuditEvent, PatientAgentSession

REALTIME_SESSION_START_LIMIT = 6
REALTIME_SESSION_START_WINDOW = timedelta(minutes=10)


class RealtimeSessionRateLimitExceeded(HTTPException):
    """HTTP-safe denial used when a patient exceeds the realtime start budget."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many realtime patient session starts. Please try again later.",
            headers={"Retry-After": str(self.retry_after_seconds)},
        )


async def enforce_realtime_session_start_limit(
    *,
    db: AsyncSession,
    principal: PatientPrincipal,
    now: datetime | None = None,
    limit: int = REALTIME_SESSION_START_LIMIT,
    window: timedelta = REALTIME_SESSION_START_WINDOW,
) -> None:
    """Bound provider-session starts per authenticated patient and clinic.

    The limiter is backed by persisted ``PatientAgentSession`` rows rather than
    process memory, so independent application workers share the same evidence.
    A denial is written to the patient-agent audit log before the HTTP 429 is
    raised. Denials themselves do not extend the rolling window.
    """

    if limit <= 0:
        raise ValueError("Realtime session start limit must be positive")
    if window <= timedelta(0):
        raise ValueError("Realtime session start window must be positive")

    observed_at = now or datetime.now(UTC)
    cutoff = observed_at - window
    result = await db.execute(
        select(
            func.count(PatientAgentSession.id),
            func.min(PatientAgentSession.created_at),
        ).where(
            PatientAgentSession.clinic_id == principal.clinic_id,
            PatientAgentSession.patient_id == principal.patient_id,
            PatientAgentSession.created_at >= cutoff,
        )
    )
    recent_attempts, oldest_attempt_at = result.one()
    if int(recent_attempts or 0) < limit:
        return

    retry_after_seconds = max(1, ceil(window.total_seconds()))
    if oldest_attempt_at is not None:
        retry_after_seconds = max(
            1,
            ceil((oldest_attempt_at + window - observed_at).total_seconds()),
        )

    db.add(
        PatientAgentAuditEvent(
            session_id=None,
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            event_type="realtime_session_rate_limited",
            actor_type="system",
            outcome="denied",
            detail={
                "limit": limit,
                "window_seconds": int(window.total_seconds()),
                "recent_attempts": int(recent_attempts or 0),
                "retry_after_seconds": retry_after_seconds,
            },
            reason="Authenticated patient exceeded realtime session start budget",
        )
    )
    await db.commit()
    raise RealtimeSessionRateLimitExceeded(retry_after_seconds=retry_after_seconds)
