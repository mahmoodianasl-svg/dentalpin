"""Recalls router smoke tests.

Cover the API surface a receptionist hits while working a call list:
create + duplicate guard, list, log attempt with auto-transition,
snooze, settings GET/PUT, dashboard stats, do_not_contact filter.

Issue #62.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.modules.patients.models import Patient
from app.modules.recalls.models import Recall


@pytest.mark.asyncio
async def test_create_then_duplicate_guard_updates_existing(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
):
    payload = {
        "patient_id": str(test_patient.id),
        "due_month": "2026-08-01",
        "reason": "hygiene",
        "priority": "normal",
        "reason_note": "first",
    }
    res = await client.post("/api/v1/recalls/", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    first = res.json()["data"]
    assert first["status"] == "pending"
    assert first["due_month"] == "2026-08-01"

    # Same patient + reason + active status → guard updates instead of insert.
    payload2 = {
        **payload,
        "due_month": "2026-09-01",
        "priority": "high",
        "reason_note": "second",
    }
    res2 = await client.post("/api/v1/recalls/", json=payload2, headers=auth_headers)
    assert res2.status_code == 201, res2.text
    second = res2.json()["data"]
    assert second["id"] == first["id"]  # same row
    assert second["due_month"] == "2026-09-01"
    assert second["priority"] == "high"

    # List shows exactly one row.
    list_res = await client.get(
        f"/api/v1/recalls/?patient_id={test_patient.id}&page_size=10",
        headers=auth_headers,
    )
    assert list_res.status_code == 200
    body = list_res.json()
    assert body["total"] == 1
    assert body["data"][0]["patient"]["first_name"] == "Test"


@pytest.mark.asyncio
async def test_scheduled_appointment_auto_links_recall_after_commit(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    test_patient: Patient,
    db_session: AsyncSession,
) -> None:
    """The recalls subscriber must see the appointment in its own session."""
    membership = (
        await db_session.execute(
            select(ClinicMembership).where(ClinicMembership.clinic_id == test_clinic.id)
        )
    ).scalar_one()
    membership.is_professional = True

    recall_response = await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "2026-08-01",
            "reason": "checkup",
        },
        headers=auth_headers,
    )
    assert recall_response.status_code == 201, recall_response.text
    recall_id = recall_response.json()["data"]["id"]
    await db_session.commit()

    async with asyncio.timeout(15):
        appointment_response = await client.post(
            "/api/v1/agenda/appointments",
            json={
                "patient_id": str(test_patient.id),
                "professional_id": str(membership.user_id),
                "cabinet": "Gabinete 1",
                "start_time": "2026-09-01T10:00:00Z",
                "end_time": "2026-09-01T10:30:00Z",
                "treatment_type": "Check-up",
            },
            headers=auth_headers,
        )
    assert appointment_response.status_code == 201, appointment_response.text

    recall = await db_session.get(Recall, UUID(recall_id))
    assert recall is not None
    await db_session.refresh(recall)
    assert str(recall.linked_appointment_id) == appointment_response.json()["data"]["id"]
    assert recall.status == "contacted_scheduled"


@pytest.mark.asyncio
async def test_create_recall_for_foreign_patient_rejected(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic: Clinic,
    db_session: AsyncSession,
):
    """A recall may not be created against a patient in another clinic —
    that would leak the foreign patient's name/phone back through the
    list/export (audit multi-tenancy #1)."""
    from uuid import uuid4

    other_clinic = Clinic(
        id=uuid4(),
        name="Other",
        tax_id="B77777777",
        address={"street": "x", "city": "y"},
        settings={},
    )
    db_session.add(other_clinic)
    foreign_patient = Patient(
        id=uuid4(),
        clinic_id=other_clinic.id,
        first_name="Foreign",
        last_name="Patient",
        phone="+34600000000",
    )
    db_session.add(foreign_patient)
    await db_session.commit()

    res = await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(foreign_patient.id),
            "due_month": "2026-08-01",
            "reason": "hygiene",
        },
        headers=auth_headers,
    )
    assert res.status_code == 404, res.text

    # And the caller's list stays empty — nothing leaked.
    lst = await client.get("/api/v1/recalls/?page_size=10", headers=auth_headers)
    assert lst.json()["total"] == 0


@pytest.mark.asyncio
async def test_log_attempt_auto_transitions_status(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
):
    # Seed a recall.
    create = await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "2026-07-01",
            "reason": "checkup",
        },
        headers=auth_headers,
    )
    rid = create.json()["data"]["id"]

    res = await client.post(
        f"/api/v1/recalls/{rid}/attempts",
        json={"channel": "phone", "outcome": "no_answer"},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text

    detail = (await client.get(f"/api/v1/recalls/{rid}", headers=auth_headers)).json()["data"]
    assert detail["status"] == "contacted_no_answer"
    assert detail["contact_attempt_count"] == 1
    assert len(detail["attempts"]) == 1


@pytest.mark.asyncio
async def test_snooze_bumps_due_month_forward(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
):
    create = await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "2026-06-01",
            "reason": "hygiene",
        },
        headers=auth_headers,
    )
    rid = create.json()["data"]["id"]

    res = await client.post(
        f"/api/v1/recalls/{rid}/snooze",
        json={"months": 4},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["due_month"] == "2026-10-01"


@pytest.mark.asyncio
async def test_settings_lazy_create_and_update(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
):
    res = await client.get("/api/v1/recalls/settings", headers=auth_headers)
    assert res.status_code == 200
    settings = res.json()["data"]
    assert settings["clinic_id"] == str(test_clinic.id)
    assert settings["reason_intervals"]["hygiene"] == 6
    assert settings["category_to_reason"]["preventivo"] == "hygiene"
    assert settings["auto_suggest_on_treatment_completed"] is True

    update = await client.put(
        "/api/v1/recalls/settings",
        json={
            "reason_intervals": {**settings["reason_intervals"], "hygiene": 4},
            "auto_suggest_on_treatment_completed": False,
        },
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text
    updated = update.json()["data"]
    assert updated["reason_intervals"]["hygiene"] == 4
    assert updated["auto_suggest_on_treatment_completed"] is False


@pytest.mark.asyncio
async def test_dashboard_stats_endpoint(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
):
    # Seed a recall so the counters are non-zero where relevant.
    await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "1900-01-01",
            "reason": "checkup",
        },
        headers=auth_headers,
    )
    res = await client.get("/api/v1/recalls/stats/dashboard", headers=auth_headers)
    assert res.status_code == 200
    stats = res.json()["data"]
    assert stats["overdue"] >= 1
    assert isinstance(stats["conversion_rate"], float)


@pytest.mark.asyncio
async def test_do_not_contact_excluded_from_active_list(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_patient: Patient,
):
    await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "2026-08-01",
            "reason": "hygiene",
        },
        headers=auth_headers,
    )
    test_patient.do_not_contact = True
    await db_session.commit()

    res = await client.get("/api/v1/recalls/?page_size=10", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 0

    # Opting in surfaces the row again.
    res2 = await client.get(
        "/api/v1/recalls/?include_do_not_contact=true&page_size=10",
        headers=auth_headers,
    )
    assert res2.status_code == 200
    assert res2.json()["total"] == 1


@pytest.mark.asyncio
async def test_suggestion_returns_null_when_no_mapping(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
):
    res = await client.get(
        f"/api/v1/recalls/suggestions/next?patient_id={test_patient.id}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["data"] is None


@pytest.mark.asyncio
async def test_suggestion_uses_category_map(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
):
    res = await client.get(
        f"/api/v1/recalls/suggestions/next?patient_id={test_patient.id}"
        f"&treatment_category_key=preventivo",
        headers=auth_headers,
    )
    assert res.status_code == 200
    suggestion = res.json()["data"]
    assert suggestion is not None
    assert suggestion["reason"] == "hygiene"
    assert suggestion["interval_months"] == 6
    assert suggestion["matched_setting"] is True
