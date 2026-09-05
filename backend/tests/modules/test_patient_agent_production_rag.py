from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.patient_agent.dental_conversation import DentalKnowledgeEntry, DentalTopic
from app.modules.patient_agent.identity import PatientPrincipal
from app.modules.patient_agent.router import patient_dental_knowledge_search
from app.modules.patient_agent.schemas import PatientDentalKnowledgeSearchRequest


def _principal() -> PatientPrincipal:
    return PatientPrincipal(
        patient_id=uuid4(),
        clinic_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@pytest.mark.asyncio
async def test_patient_knowledge_search_returns_provenance_and_patient_education_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = _principal()
    captured: dict[str, object] = {}

    class FakeRetriever:
        def __init__(self, *, db, clinic_id):  # noqa: ANN001
            captured["db"] = db
            captured["clinic_id"] = clinic_id

        async def search(self, *, query, locale, topic, limit):  # noqa: ANN001
            captured.update(
                query=query,
                locale=locale,
                topic=topic,
                limit=limit,
            )
            return (
                DentalKnowledgeEntry(
                    entry_id="implant-basics:v2",
                    topic=DentalTopic.IMPLANTS,
                    title="Dental implant basics",
                    content="Dentist-reviewed patient education about implants.",
                    source_name="Clinic knowledge",
                    source_reference="kb://implant-basics/2",
                    reviewed_by=str(uuid4()),
                    locale="en",
                ),
            )

    monkeypatch.setattr(
        "app.modules.patient_agent.router.DatabaseDentalKnowledgeRetriever",
        FakeRetriever,
    )
    db = SimpleNamespace()

    response = await patient_dental_knowledge_search(
        PatientDentalKnowledgeSearchRequest(
            query="implant appointment",
            locale="en",
            topic=DentalTopic.IMPLANTS,
            limit=5,
        ),
        principal,
        db,
    )

    assert captured["clinic_id"] == principal.clinic_id
    assert captured["query"] == "implant appointment"
    assert response.data.fallback_required is False
    assert response.data.patient_education_only is True
    assert len(response.data.sources) == 1
    source = response.data.sources[0]
    assert source.entry_id == "implant-basics:v2"
    assert source.source_name == "Clinic knowledge"
    assert source.source_reference == "kb://implant-basics/2"
    assert source.content.startswith("Dentist-reviewed")


@pytest.mark.asyncio
async def test_patient_knowledge_search_requires_safe_fallback_when_no_approved_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyRetriever:
        def __init__(self, *, db, clinic_id):  # noqa: ANN001
            del db, clinic_id

        async def search(self, *, query, locale, topic, limit):  # noqa: ANN001
            del query, locale, topic, limit
            return ()

    monkeypatch.setattr(
        "app.modules.patient_agent.router.DatabaseDentalKnowledgeRetriever",
        EmptyRetriever,
    )

    response = await patient_dental_knowledge_search(
        PatientDentalKnowledgeSearchRequest(query="unknown dental question"),
        _principal(),
        SimpleNamespace(),
    )

    assert response.data.sources == []
    assert response.data.fallback_required is True
    assert response.data.patient_education_only is True


def test_patient_knowledge_search_request_caps_retrieval_limit() -> None:
    with pytest.raises(ValueError):
        PatientDentalKnowledgeSearchRequest(query="implant", limit=6)
