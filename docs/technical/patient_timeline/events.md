---
module: patient_timeline
last_verified_commit: 0000000
---

# Patient Timeline — events

> _Scaffolded stub — replace with proper documentation when this module is next touched._

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

_This module does not publish any events._

## Subscribed

| Event | Handler | Effect |
|-------|---------|--------|
| `agenda.visit_note_updated` | _Handler module path._ | _What it does in response._ |
| `appointment.cancelled` | `events.on_appointment_cancelled` | Append a cancellation entry after the transition commits. |
| `appointment.checked_in` | `events.on_appointment_checked_in` | Append a check-in entry after the transition commits. |
| `appointment.completed` | `events.on_appointment_completed` | Append a completion entry after the transition commits. |
| `appointment.confirmed` | `events.on_appointment_confirmed` | Append a confirmation entry after the transition commits. |
| `appointment.in_treatment` | `events.on_appointment_in_treatment` | Append an in-treatment entry after the transition commits. |
| `appointment.no_show` | `events.on_appointment_no_show` | Append a no-show entry after the transition commits. |
| `appointment.scheduled` | _Handler module path._ | _What it does in response._ |
| `budget.accepted` | _Handler module path._ | _What it does in response._ |
| `budget.expired` | _Handler module path._ | _What it does in response._ |
| `budget.rejected` | _Handler module path._ | _What it does in response._ |
| `budget.reminder_sent` | _Handler module path._ | _What it does in response._ |
| `budget.renegotiated` | _Handler module path._ | _What it does in response._ |
| `budget.sent` | _Handler module path._ | _What it does in response._ |
| `budget.viewed` | _Handler module path._ | _What it does in response._ |
| `clinical_notes.administrative_created` | _Handler module path._ | _What it does in response._ |
| `clinical_notes.diagnosis_created` | _Handler module path._ | _What it does in response._ |
| `clinical_notes.plan_created` | _Handler module path._ | _What it does in response._ |
| `clinical_notes.treatment_created` | _Handler module path._ | _What it does in response._ |
| `document.uploaded` | _Handler module path._ | _What it does in response._ |
| `email.failed` | _Handler module path._ | _What it does in response._ |
| `email.sent` | _Handler module path._ | _What it does in response._ |
| `invoice.issued` | _Handler module path._ | _What it does in response._ |
| `invoice.paid` | _Handler module path._ | _What it does in response._ |
| `media.pair_created` | _Handler module path._ | _What it does in response._ |
| `media.photo_uploaded` | _Handler module path._ | _What it does in response._ |
| `odontogram.treatment.performed` | _Handler module path._ | _What it does in response._ |
| `patient.medical_updated` | _Handler module path._ | _What it does in response._ |
| `treatment_plan.closed` | _Handler module path._ | _What it does in response._ |
| `treatment_plan.confirmed` | _Handler module path._ | _What it does in response._ |
| `treatment_plan.created` | _Handler module path._ | _What it does in response._ |
| `treatment_plan.item_completed_without_note` | _Handler module path._ | _What it does in response._ |
| `treatment_plan.reactivated` | _Handler module path._ | _What it does in response._ |
| `treatment_plan.treatment_completed` | _Handler module path._ | _What it does in response._ |

Appointment lifecycle handlers write append-only rows and commit in independent
sessions. Agenda owns the boundary and publishes each status event only after
the appointment transition commit succeeds.

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, after the DB commit succeeds.
3. Add the row to the table(s) above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
