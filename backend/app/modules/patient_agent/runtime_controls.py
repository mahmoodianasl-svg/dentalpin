"""Operational safety controls for patient realtime sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .identity import PatientPrincipal
from .models import PatientAgentAuditEvent, PatientAgentSession

REALTIME_SESSION_START_LIMIT = 6
REALTIME_SESSION_START_WINDOW = timedelta(minutes=10)
VISUAL_SNAPSHOT_SHARE_LIMIT = 8
VISUAL_SNAPSHOT_SHARE_WINDOW = timedelta(minutes=5)


class RealtimeSessionRateLimitExceeded(HTTPException):
    """HTTP-safe denial used when a patient exceeds the realtime start budget."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many realtime patient session starts. Please try again later.",
            headers={"Retry-After": str(self.retry_after_seconds)},
        )


class VisualSnapshotRateLimitExceeded(HTTPException):
    """HTTP-safe denial used when a session exceeds its visual-share budget."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many visual snapshot shares. Please try again later.",
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


async def enforce_visual_snapshot_share_limit(
    *,
    db: AsyncSession,
    principal: PatientPrincipal,
    session_id: UUID,
    now: datetime | None = None,
    limit: int = VISUAL_SNAPSHOT_SHARE_LIMIT,
    window: timedelta = VISUAL_SNAPSHOT_SHARE_WINDOW,
) -> None:
    """Bound audited visual-share preflights per patient realtime session.

    Only successful ``visual_snapshot_share_authorized`` audit events count
    toward the rolling budget. The image bytes never pass through or persist in
    this limiter. A denial is committed before raising so the abuse-control
    decision remains auditable even though the request returns HTTP 429.
    """

    if limit <= 0:
        raise ValueError("Visual snapshot share limit must be positive")
    if window <= timedelta(0):
        raise ValueError("Visual snapshot share window must be positive")

    observed_at = now or datetime.now(UTC)
    cutoff = observed_at - window
    result = await db.execute(
        select(
            func.count(PatientAgentAuditEvent.id),
            func.min(PatientAgentAuditEvent.created_at),
        ).where(
            PatientAgentAuditEvent.session_id == session_id,
            PatientAgentAuditEvent.clinic_id == principal.clinic_id,
            PatientAgentAuditEvent.patient_id == principal.patient_id,
            PatientAgentAuditEvent.event_type == "visual_snapshot_share_authorized",
            PatientAgentAuditEvent.created_at >= cutoff,
        )
    )
    recent_shares, oldest_share_at = result.one()
    if int(recent_shares or 0) < limit:
        return

    retry_after_seconds = max(1, ceil(window.total_seconds()))
    if oldest_share_at is not None:
        retry_after_seconds = max(
            1,
            ceil((oldest_share_at + window - observed_at).total_seconds()),
        )

    db.add(
        PatientAgentAuditEvent(
            session_id=session_id,
            clinic_id=principal.clinic_id,
            patient_id=principal.patient_id,
            event_type="visual_snapshot_rate_limited",
            actor_type="system",
            outcome="denied",
            detail={
                "limit": limit,
                "window_seconds": int(window.total_seconds()),
                "recent_shares": int(recent_shares or 0),
                "retry_after_seconds": retry_after_seconds,
                "media_content_persisted": False,
            },
            reason="Authenticated patient exceeded visual snapshot share budget",
        )
    )
    await db.commit()
    raise VisualSnapshotRateLimitExceeded(retry_after_seconds=retry_after_seconds)
