from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PatientAgentAuditEvent, PatientAgentSession

_PENDING_HANDOFF_STATES = ("requested", "emergency_escalation")
_VISIBLE_HANDOFF_STATES = (*_PENDING_HANDOFF_STATES, "accepted")


class StaffHandoffService:
    """Clinic-scoped staff operations for patient human-handoff requests."""

    async def list_pending(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
    ) -> list[PatientAgentSession]:
        result = await db.execute(
            select(PatientAgentSession)
            .where(
                PatientAgentSession.clinic_id == clinic_id,
                PatientAgentSession.handoff_state.in_(_PENDING_HANDOFF_STATES),
            )
            .order_by(
                case(
                    (PatientAgentSession.handoff_state == "emergency_escalation", 0),
                    else_=1,
                ),
                PatientAgentSession.created_at.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_handoff(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        session_id: UUID,
    ) -> PatientAgentSession | None:
        result = await db.execute(
            select(PatientAgentSession).where(
                PatientAgentSession.id == session_id,
                PatientAgentSession.clinic_id == clinic_id,
                PatientAgentSession.handoff_state.in_(_VISIBLE_HANDOFF_STATES),
            )
        )
        return result.scalar_one_or_none()

    async def accept(
        self,
        *,
        db: AsyncSession,
        clinic_id: UUID,
        session_id: UUID,
        actor_user_id: UUID,
    ) -> PatientAgentSession:
        result = await db.execute(
            select(PatientAgentSession)
            .where(
                PatientAgentSession.id == session_id,
                PatientAgentSession.clinic_id == clinic_id,
                PatientAgentSession.handoff_state.in_(_VISIBLE_HANDOFF_STATES),
            )
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise LookupError("Patient handoff not found")
        if session.handoff_state == "accepted":
            raise ValueError("Patient handoff has already been accepted")
        if session.handoff_state not in _PENDING_HANDOFF_STATES:
            raise ValueError("Patient handoff is not pending")

        previous_state = session.handoff_state
        accepted_at = datetime.now(UTC)
        context = dict(session.context or {})
        context["handoff_accepted_by"] = str(actor_user_id)
        context["handoff_accepted_at"] = accepted_at.isoformat()
        session.context = context
        session.handoff_state = "accepted"

        db.add(
            PatientAgentAuditEvent(
                session_id=session.id,
                clinic_id=session.clinic_id,
                patient_id=session.patient_id,
                event_type="patient_handoff_accepted",
                actor_type="staff",
                outcome="success",
                detail={
                    "actor_user_id": str(actor_user_id),
                    "previous_handoff_state": previous_state,
                    "handoff_urgency": context.get("handoff_urgency"),
                },
            )
        )
        await db.flush()
        return session
