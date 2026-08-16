---
module: budget
screen: create
route: /budgets/new
related_endpoints:
  - DELETE /api/v1/budget/budgets/{budget_id}
  - DELETE /api/v1/budget/budgets/{budget_id}/items/{item_id}
  - GET /api/v1/budget/budgets
  - GET /api/v1/budget/budgets/{budget_id}
  - GET /api/v1/budget/budgets/{budget_id}/history
  - GET /api/v1/budget/budgets/{budget_id}/pdf
  - GET /api/v1/budget/budgets/{budget_id}/pdf/preview
  - GET /api/v1/budget/budgets/{budget_id}/pdf/signed
  - GET /api/v1/budget/budgets/{budget_id}/signature
  - GET /api/v1/budget/budgets/{budget_id}/versions
  - POST /api/v1/budget/budgets
  - POST /api/v1/budget/budgets/{budget_id}/accept
  - POST /api/v1/budget/budgets/{budget_id}/accept-in-clinic
  - POST /api/v1/budget/budgets/{budget_id}/cancel
  - POST /api/v1/budget/budgets/{budget_id}/duplicate
  - POST /api/v1/budget/budgets/{budget_id}/items
  - POST /api/v1/budget/budgets/{budget_id}/reject
  - POST /api/v1/budget/budgets/{budget_id}/renegotiate
  - POST /api/v1/budget/budgets/{budget_id}/resend
  - POST /api/v1/budget/budgets/{budget_id}/send
  - POST /api/v1/budget/budgets/{budget_id}/send-reminder
  - POST /api/v1/budget/budgets/{budget_id}/set-public-code
  - POST /api/v1/budget/budgets/{budget_id}/unlock-public
  - PUT /api/v1/budget/budgets/{budget_id}
  - PUT /api/v1/budget/budgets/{budget_id}/items/{item_id}
related_permissions:
  - budget.read
  - budget.write
related_paths:
  - backend/app/modules/budget/frontend/pages/budgets/new.vue
  - backend/app/modules/budget/router.py
last_verified_commit: b1b82f5
---

# New budget

Form to create a budget from scratch. The budget is born in `draft`
state on save, and the workflow continues from the
[detail](./budgets_id.md).

## At a glance

- **How you usually get here.**
  - From the patient record → *New budget* (patient pre-selected).
  - From the list → **New budget** (patient picker required).
  - From a treatment plan → generates a budget kept in sync via
    `treatment_plan.treatment_added` /
    `treatment_plan.budget_sync_requested` events.
- **Auto-numbering.** The number (`PRES-YYYY-####`) is assigned on
  save; it is not editable.
- **Default validity** — the form proposes `valid_from = today` and
  `valid_until = today + 30 days`. Adjust if your policy differs.
- **Price snapshot.** Each line records the catalog price effective
  at creation time. Editing the catalog later does not change
  existing budgets.

## Create a budget

> Requires `budget.write`.

1. If you didn't come from a patient record, pick the patient in
   the header.
2. Add items from the catalog. For each line you can choose:
   - Tooth and surfaces (FDI notation).
   - Quantity, unit price (prefilled from the catalog), line
     discount (percent or absolute).
   - VAT type (prefilled from the catalog).
3. Apply a global discount if needed.
4. Review the totals in the sidebar.
5. **Save**. The budget is created in `draft` and you land on the
   [detail](./budgets_id.md) to send it, sign it, or invoice it
   later.

## Create from a treatment plan

> Requires `budget.write` and `treatment_plan.write`.

1. On the treatment plan, click **Generate budget**.
2. The plan's treatments arrive in the form as prefilled lines via
   a snapshot event payload.
3. Adjust what you need and save.

## Permissions

| What you see / can do | Permission |
|-----------------------|------------|
| Access the form and see the catalog | `budget.read` |
| Create the budget | `budget.write` |

## Troubleshooting

- **Patient picker is empty.** You lack `patients.read` (without it
  the form cannot list patients).
- **A catalog item is missing.** Make sure it is active under
  *Settings → Catalog* and your role has `catalog.read`.
- **Totals don't match what you expect.** Check line vs global
  discount. Application order: price × quantity → line discount →
  VAT → global discount on the total.
