---
module: billing
last_verified_commit: 0000000
---

# Billing — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

| Event | When | Consumers |
|-------|------|-----------|
| `invoice.issued` | An invoice or credit note is issued | verifactu, notifications, reports |
| `invoice.sent` | Invoice delivery is requested | notifications |
| `invoice.paid` | Recalculation moves an invoice to `paid` | notifications, reports |

## Subscribed

| Event | Handler | Effect |
|-------|---------|--------|
| `payment.refunded` | `billing/events.py::on_payment_refunded` | Opens a new session and recomputes linked invoice status from committed allocations and refunds. |

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, after the DB commit succeeds.
3. Add the row to the table(s) above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
