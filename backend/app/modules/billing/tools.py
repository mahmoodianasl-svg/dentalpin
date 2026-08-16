"""Agent tools for the billing module — READ ONLY.

Invoice axis only (off-books contract): these tools never return paid /
pending amounts and never join payments. ``get_invoice`` is called with
``include_payments=False`` so the two axes can't be juxtaposed. No
issuing/voiding tools — invoice emission stays manual (Veri*Factu
chaining is irreversible). See
``docs/technical/copilot-agentic-architecture.md`` §3.
"""

from __future__ import annotations

from datetime import date as date_cls
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.agents import AgentContext, Tool, ToolCategory

from .schemas import InvoiceStatus
from .service import InvoiceService


class ListInvoicesArgs(BaseModel):
    patient_id: UUID | None = None
    status: list[InvoiceStatus] | None = None
    date_from: date_cls | None = None
    date_to: date_cls | None = None
    overdue: bool | None = Field(
        default=None, description="Solo facturas emitidas/parciales con vencimiento pasado."
    )
    is_credit_note: bool | None = None
    limit: int = Field(default=20, ge=1, le=50)


class GetInvoiceArgs(BaseModel):
    invoice_id: UUID


def _invoice_summary(invoice) -> dict:
    patient = invoice.patient
    # Invoice axis only: no paid/pending amounts here (off-books rule).
    return {
        "id": invoice.id,
        "number": invoice.invoice_number,
        "patient_id": invoice.patient_id,
        "patient_name": (
            f"{patient.first_name} {patient.last_name}" if patient is not None else None
        ),
        "status": invoice.status,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "total": invoice.total,
    }


async def _list_invoices(ctx: AgentContext, params: ListInvoicesArgs) -> dict:
    items, total = await InvoiceService.list_invoices(
        ctx.db,
        ctx.clinic_id,
        page=1,
        page_size=params.limit,
        patient_id=params.patient_id,
        status=list(params.status) if params.status else None,
        date_from=params.date_from,
        date_to=params.date_to,
        overdue=params.overdue,
        is_credit_note=params.is_credit_note,
    )
    return {"total": total, "invoices": [_invoice_summary(i) for i in items]}


async def _get_invoice(ctx: AgentContext, params: GetInvoiceArgs) -> dict:
    invoice = await InvoiceService.get_invoice(
        ctx.db,
        ctx.clinic_id,
        params.invoice_id,
        include_items=True,
        include_payments=False,  # off-books: never juxtapose the two axes
    )
    if invoice is None:
        return {"error": "not_found"}
    data = _invoice_summary(invoice)
    data["items"] = [
        {"description": i.description, "quantity": i.quantity, "total": i.line_total}
        for i in invoice.items
    ]
    return data


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="list_invoices",
            description=(
                "Listar facturas de la clínica: por paciente, estado (draft, "
                "issued, partial, paid, cancelled, voided), fechas, vencidas "
                "o rectificativas. Solo lectura."
            ),
            parameters=ListInvoicesArgs,
            handler=_list_invoices,
            permissions=["billing.read"],
            category=ToolCategory.READ,
        ),
        Tool(
            name="get_invoice",
            description="Detalle de una factura con sus líneas. Solo lectura.",
            parameters=GetInvoiceArgs,
            handler=_get_invoice,
            permissions=["billing.read"],
            category=ToolCategory.READ,
        ),
    ]
