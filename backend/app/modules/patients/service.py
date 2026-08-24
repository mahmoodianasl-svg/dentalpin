"""PatientService — business logic for patient CRUD.

Moved from ``app.modules.clinical.service`` in Fase B.1 chunk 2.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, column, func, or_, select, table, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventType, event_bus
from app.core.list_query import parse_sort

from .models import Patient

# Public field name → SQL column. Decouples the URL from internal naming
# and prevents callers from sorting by arbitrary columns.
#
# ``last_visit`` is handled out-of-band (see ``list_patients``) because it
# lives in the ``agenda.appointments`` table and ``patients`` is foundational
# (``depends=[]``) — same workaround as ``get_recent_patients``.
_SORT_ALLOW = {
    "last_name": Patient.last_name,
    "first_name": Patient.first_name,
    "created_at": Patient.created_at,
    "updated_at": Patient.updated_at,
}
_SORT_DEFAULT = "last_visit:desc"
_SORT_LAST_VISIT = "last_visit"

# Lightweight reference to the agenda ``appointments`` table — avoids
# importing ``Appointment`` from the agenda module while keeping the
# query in SQLAlchemy Core rather than raw text(). The table name is
# the only contract; agenda renames must be coordinated here.
_appointments_t = table(
    "appointments",
    column("patient_id"),
    column("clinic_id"),
    column("start_time"),
)


# Fields a free-text search term is matched against. Concatenated
# ``first_name || ' ' || last_name`` is added per-term so a single term
# can span the name boundary (e.g. matching "an Sm" against "Juan Smith").
_SEARCH_FIELDS = (
    Patient.first_name,
    Patient.last_name,
    Patient.phone,
    Patient.email,
    Patient.national_id,
)
_FULL_NAME = func.concat(Patient.first_name, " ", Patient.last_name)


def _search_condition(search: str | None):
    """Build the WHERE clause for a free-text patient search.

    The query is split on whitespace into terms. A patient matches when
    **every** term matches **some** field (AND across terms, OR across
    fields). This makes "first last" — and the reversed "last first" —
    find a patient whose name is split across ``first_name`` and
    ``last_name``, which a single substring ILIKE could never do.
    """
    if not search or not search.strip():
        return None
    terms = search.split()
    per_term = []
    for term in terms:
        like = f"%{term}%"
        per_term.append(
            or_(
                *(field.ilike(like) for field in _SEARCH_FIELDS),
                _FULL_NAME.ilike(like),
            )
        )
    return and_(*per_term)


class PatientService:
    """Service for patient CRUD."""

    @staticmethod
    async def get_recent_patients(
        db: AsyncSession,
        clinic_id: UUID,
        limit: int = 8,
    ) -> list[Patient]:
        """Patients ordered by last visit, falling back to newest created.

        ``last_visit`` lives in the consumer ``agenda.appointments``
        table. ``patients`` is foundational (``depends=[]``) so we
        cannot import the ``Appointment`` model — instead we read the
        table through a raw SQL fragment. The table name is the only
        contract; agenda renames must be coordinated here.
        """
        last_visit_rows = (
            await db.execute(
                text(
                    """
                    SELECT patient_id, MAX(start_time) AS last_visit
                    FROM appointments
                    WHERE clinic_id = :clinic_id
                      AND patient_id IS NOT NULL
                    GROUP BY patient_id
                    ORDER BY last_visit DESC
                    LIMIT :limit
                    """
                ),
                {"clinic_id": clinic_id, "limit": limit},
            )
        ).all()

        ordered_ids: list[UUID] = [row.patient_id for row in last_visit_rows]

        if not ordered_ids:
            result = await db.execute(
                select(Patient)
                .where(
                    Patient.clinic_id == clinic_id,
                    Patient.status != "archived",
                )
                .order_by(Patient.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

        result = await db.execute(
            select(Patient).where(
                Patient.clinic_id == clinic_id,
                Patient.id.in_(ordered_ids),
                Patient.status != "archived",
            )
        )
        by_id = {p.id: p for p in result.scalars().all()}
        # Preserve the visit-ordered ranking from the raw query.
        return [by_id[i] for i in ordered_ids if i in by_id]

    @staticmethod
    async def list_patients(
        db: AsyncSession,
        clinic_id: UUID,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
        *,
        patient_ids: list[UUID] | None = None,
        city: str | None = None,
        do_not_contact: bool | None = None,
        include_archived: bool = False,
        sort: str | None = None,
    ) -> tuple[list[Patient], int]:
        """List patients with optional search + filters + sort.

        ``patient_ids`` is used by cross-module intersections (e.g.
        "Patients with debt > 0" comes from the payments module). Empty
        list short-circuits to an empty result so callers can pass the
        payments-side result without extra branching.
        """
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * page_size

        # Empty intersection set → no rows. Don't query.
        if patient_ids is not None and not patient_ids:
            return [], 0

        conditions = [Patient.clinic_id == clinic_id]
        if not include_archived:
            conditions.append(Patient.status != "archived")

        if patient_ids:
            conditions.append(Patient.id.in_(patient_ids))

        if city:
            # JSONB ->> 'city' ilike. address may be null.
            conditions.append(Patient.address["city"].astext.ilike(f"%{city}%"))

        if do_not_contact is not None:
            conditions.append(Patient.do_not_contact.is_(do_not_contact))

        search_clause = _search_condition(search)
        if search_clause is not None:
            conditions.append(search_clause)

        total = (await db.execute(select(func.count(Patient.id)).where(*conditions))).scalar() or 0

        sort_raw = (sort or _SORT_DEFAULT).strip()
        sort_field, _, sort_dir = sort_raw.partition(":")
        sort_field = sort_field.strip()
        sort_dir = (sort_dir or "asc").strip().lower()

        if sort_field == _SORT_LAST_VISIT:
            if sort_dir not in ("asc", "desc"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid sort direction {sort_dir!r}. Use 'asc' or 'desc'.",
                )
            last_visit_sq = (
                select(
                    _appointments_t.c.patient_id.label("patient_id"),
                    func.max(_appointments_t.c.start_time).label("last_visit"),
                )
                .where(
                    _appointments_t.c.clinic_id == clinic_id,
                    _appointments_t.c.patient_id.is_not(None),
                )
                .group_by(_appointments_t.c.patient_id)
                .subquery()
            )
            last_visit_col = last_visit_sq.c.last_visit
            order_clause = (
                last_visit_col.desc().nulls_last()
                if sort_dir == "desc"
                else last_visit_col.asc().nulls_last()
            )
            query = (
                select(Patient)
                .outerjoin(last_visit_sq, last_visit_sq.c.patient_id == Patient.id)
                .where(*conditions)
                .order_by(order_clause, Patient.last_name, Patient.first_name)
                .offset(offset)
                .limit(page_size)
            )
        else:
            query = (
                select(Patient)
                .where(*conditions)
                .order_by(parse_sort(sort, _SORT_ALLOW, _SORT_DEFAULT), Patient.first_name)
                .offset(offset)
                .limit(page_size)
            )

        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def get_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> Patient | None:
        result = await db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_patient(db: AsyncSession, clinic_id: UUID, data: dict) -> Patient:
        """Create and flush a patient without publishing its event.

        Live callers must follow this with :meth:`commit_and_publish_created`;
        batch callers must queue the same canonical payload and publish it only
        after their outer transaction commits.
        """
        patient = Patient(clinic_id=clinic_id, **data)
        db.add(patient)
        await db.flush()
        return patient

    @staticmethod
    def created_event_payload(patient: Patient) -> dict:
        """Build the canonical ``patient.created`` payload."""
        return {
            "patient_id": str(patient.id),
            "clinic_id": str(patient.clinic_id),
        }

    @staticmethod
    async def commit_and_publish_created(db: AsyncSession, patient: Patient) -> None:
        """Commit a new patient before publishing its live event."""
        await db.commit()
        await event_bus.publish(
            EventType.PATIENT_CREATED,
            PatientService.created_event_payload(patient),
        )

    @staticmethod
    async def update_patient(db: AsyncSession, patient: Patient, data: dict) -> Patient:
        """Update an existing patient.

        ``data`` should come from ``model_dump(exclude_unset=True)`` so
        unspecified fields are preserved and explicit ``None`` clears. This
        method only flushes; live callers must commit and publish explicitly.
        """
        for key, value in data.items():
            setattr(patient, key, value)

        await db.flush()
        return patient

    @staticmethod
    def updated_event_payload(patient: Patient, changes: list[str]) -> dict:
        """Build the canonical ``patient.updated`` payload."""
        return {
            "patient_id": str(patient.id),
            "clinic_id": str(patient.clinic_id),
            "changes": changes,
        }

    @staticmethod
    async def commit_and_publish_updated(
        db: AsyncSession,
        patient: Patient,
        changes: list[str],
    ) -> None:
        """Commit a patient update before publishing its live event."""
        await db.commit()
        await event_bus.publish(
            EventType.PATIENT_UPDATED,
            PatientService.updated_event_payload(patient, changes),
        )

    @staticmethod
    async def archive_patient(db: AsyncSession, patient: Patient) -> Patient:
        """Soft-archive and flush a patient without publishing its event."""
        patient.status = "archived"
        await db.flush()
        return patient

    @staticmethod
    def archived_event_payload(patient: Patient) -> dict:
        """Build the canonical ``patient.archived`` payload."""
        return {
            "patient_id": str(patient.id),
            "clinic_id": str(patient.clinic_id),
        }

    @staticmethod
    async def commit_and_publish_archived(db: AsyncSession, patient: Patient) -> None:
        """Commit a patient archive before publishing its live event."""
        await db.commit()
        await event_bus.publish(
            EventType.PATIENT_ARCHIVED,
            PatientService.archived_event_payload(patient),
        )
