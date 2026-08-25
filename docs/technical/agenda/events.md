---
module: agenda
last_verified_commit: HEAD
---

# Agenda — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

Appointment lifecycle. The specific `appointment.<status>` event is
dispatched from a status→`EventType` map in
`AppointmentService.commit_and_publish_transition` (`service.py`), so the publish
call passes a variable — the catalog resolves it from the constants
referenced in that file.

| Event | When | Consumers |
|-------|------|-----------|
| `appointment.scheduled` | Appointment transaction committed (or import batch committed) | notifications, patient_timeline, recalls, schedules |
| `appointment.updated` | Appointment fields edited | schedules |
| `appointment.status_changed` | Status transition committed (generic) | — |
| `appointment.confirmed` | Committed → confirmed | patient_timeline |
| `appointment.checked_in` | Committed → checked-in | patient_timeline |
| `appointment.in_treatment` | Committed → in-treatment | patient_timeline |
| `appointment.completed` | Committed → completed | patient_timeline, recalls, treatment_plan |
| `appointment.cancelled` | Committed → cancelled | copilot, notifications, patient_timeline, recalls, schedules |
| `appointment.no_show` | Committed → no-show | patient_timeline |
| `appointment.cabinet_changed` | Cabinet reassigned | — |
| `agenda.visit_note_updated` | Visit note / completion flag edited on an appointment-treatment | patient_timeline |

Payloads carry `clinic_id`, `appointment_id`, and (where relevant)
`patient_id` / `professional_id` / status fields. See the module
`CLAUDE.md` for the per-event payload contract.

`AppointmentService.create_appointment` is persistence-only. Live callers
commit and publish through `commit_and_publish_scheduled`; migration imports
queue the same payload and release it after the containing batch commit.

`AppointmentService.transition` is also persistence-only. Live HTTP and agent
callers use `commit_and_publish_transition`, which commits before publishing
the canonical payload first as `appointment.status_changed` and then as the
status-specific event. A failed commit publishes neither event.

## Subscribed

_This module does not subscribe to any events._

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, **after the DB commit succeeds**.
3. Add the row to the table above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
