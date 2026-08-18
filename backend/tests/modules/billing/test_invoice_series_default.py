"""Invoice-series default replacement regression coverage."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.billing.models import InvoiceSeries
from app.modules.billing.service import InvoiceSeriesService


@pytest.mark.asyncio
async def test_creating_default_replaces_only_same_type_default(
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    original = await InvoiceSeriesService.create_series(
        db_session,
        test_clinic.id,
        {
            "prefix": "FAC",
            "series_type": "invoice",
            "is_default": True,
        },
    )
    credit_note = await InvoiceSeriesService.create_series(
        db_session,
        test_clinic.id,
        {
            "prefix": "RECT",
            "series_type": "credit_note",
            "is_default": True,
        },
    )
    await db_session.commit()

    replacement = await InvoiceSeriesService.create_series(
        db_session,
        test_clinic.id,
        {
            "prefix": "FAC-NEW",
            "series_type": "invoice",
            "is_default": True,
        },
    )
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                select(InvoiceSeries).where(InvoiceSeries.clinic_id == test_clinic.id)
            )
        )
        .scalars()
        .all()
    )
    defaults = {
        (series.prefix, series.series_type): series.is_default
        for series in rows
    }

    assert defaults == {
        ("FAC", "invoice"): False,
        ("FAC-NEW", "invoice"): True,
        ("RECT", "credit_note"): True,
    }
    assert original.is_default is False
    assert replacement.is_default is True
    assert credit_note.is_default is True
