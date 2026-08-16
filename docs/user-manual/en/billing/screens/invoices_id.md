---
module: billing
screen: detail
route: /invoices/[id]
related_endpoints:
  - DELETE /api/v1/billing/invoices/{invoice_id}
  - DELETE /api/v1/billing/invoices/{invoice_id}/items/{item_id}
  - GET /api/v1/billing/invoices
  - GET /api/v1/billing/invoices/{invoice_id}
  - GET /api/v1/billing/invoices/{invoice_id}/history
  - GET /api/v1/billing/invoices/{invoice_id}/payments
  - GET /api/v1/billing/invoices/{invoice_id}/pdf
  - GET /api/v1/billing/invoices/{invoice_id}/pdf/preview
  - GET /api/v1/billing/patients/{patient_id}/summary
  - GET /api/v1/billing/series
  - GET /api/v1/billing/settings
  - PATCH /api/v1/billing/invoices/{invoice_id}/billing-party
  - POST /api/v1/billing/invoices/{invoice_id}/credit-note
  - POST /api/v1/billing/invoices/{invoice_id}/issue
  - POST /api/v1/billing/invoices/{invoice_id}/items
  - POST /api/v1/billing/invoices/{invoice_id}/payments
  - POST /api/v1/billing/invoices/{invoice_id}/send-email
  - POST /api/v1/billing/invoices/{invoice_id}/void
  - PUT /api/v1/billing/invoices/{invoice_id}
  - PUT /api/v1/billing/invoices/{invoice_id}/items/{item_id}
related_permissions:
  - billing.read
  - billing.write
  - billing.admin
related_paths:
  - backend/app/modules/billing/frontend/pages/invoices/[id]/index.vue
  - backend/app/modules/billing/router.py
last_verified_commit: b1b82f5
---

# Invoice detail

View of one invoice. Header with legal data (issuer, receiver, tax
ID, address), line items, totals, and a sidebar with linked
payments, history, and fiscal submission state (verifactu). From
here you issue, send to the patient, and — when appropriate — void
or issue a credit note.

## At a glance

- **Legal data** — receiver (patient or third-party payer), tax ID,
  fiscal address, series + number (on `issued`). If the payer is
  not the patient, a *Different payer* chip is shown.
- **Linked payments.** A list of `invoice_payments` with amount and
  method. The invoice has no *Charge* button of its own: to collect,
  use the `payments` module and link the payment to the invoice.
- **PDF.** Two formats: draft (watermarked preview) and final (only
  for `issued`). PDF generation uses WeasyPrint.
- **History.** Status changes and key events in chronological order.
- **VeriFactu.** When the module is installed, issuing the invoice
  queues the AEAT submission. State (`pending`, `sent`, `rejected`)
  is shown in the sidebar.

## Issue an invoice

> Requires `billing.write`.

1. Verify that the legal data and line items are correct. Once
   issued, the document cannot be edited.
2. Click **Issue**. The active series assigns the fiscal number,
   `invoice.issued` is published, and the document is frozen.
3. If `verifactu` is installed, the hook will queue the AEAT
   submission and you'll see the state on the sidebar.

## Send by email

> Requires `billing.write`.

1. Click **Send by email**. The PDF is sent to the receiver's
   contact email.
2. `invoice.sent` is published. The history records the send.

## Void or issue a credit note

> Voiding requires `billing.admin`; issuing a credit note requires
> `billing.write`.

- **Void** — marks the invoice as `void`. Its number stays in the
  history for audit. Admin only.
- **Create credit note** — issues a credit note tied to the source
  invoice's amounts. Goes through the same issuing workflow.

## Permissions

| What you see / can do | Permission |
|-----------------------|------------|
| View invoice, PDF, history | `billing.read` |
| Edit draft, issue, send email, create credit notes | `billing.write` |
| Void an issued invoice | `billing.admin` |

## Troubleshooting

- **Cannot edit lines.** The invoice is no longer in `draft`. Void
  and issue a new one, or issue a partial credit note.
- **The downloaded PDF is the watermarked preview.** The invoice
  is in `draft` or `void`. The final PDF only exists for issued
  invoices.
- **VeriFactu is `rejected`.** Check the sidebar or the
  `verifactu` module for the reason. Usually requires editing
  issuer or receiver data and re-submitting manually.
- **No *Charge* button.** It does not live here. Create the
  payment under `/payments` (or from the patient record) and link
  it to this invoice via `invoice_payments`.
