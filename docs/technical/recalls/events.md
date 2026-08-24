---
module: recalls
last_verified_commit: HEAD
---

# Recalls — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

| Event | When |
|-------|------|
| `recall.created` | A new recall is inserted (duplicate-guard updates do not publish) |
| `recall.completed` | A recall transitions to `done` |
| `recall.snoozed` | A recall is moved to a later due month |
| `recall.cancelled` | A recall is cancelled |

`recall.due` is reserved for a future scheduler and is not published in V1.

## Subscribed

| Event | Handler | Effect |
|-------|---------|--------|
| `appointment.cancelled` | `events.on_appointment_cancelled` | Unlink active recalls and revert `contacted_scheduled` to `pending` |
| `appointment.completed` | `events.on_appointment_completed` | Mark the recall linked to that appointment `done` |
| `appointment.scheduled` | `events.on_appointment_scheduled` | In a fresh DB session, auto-link one unambiguous due recall after the appointment has committed |
| `patient.archived` | `events.on_patient_archived` | Move active recalls to `needs_review` |
| `treatment_plan.treatment_completed` | `events.on_treatment_plan_completed` | Logging-only hook; suggestions remain pull-based |

The `appointment.scheduled` producer must publish after commit: this handler
opens an independent session and persists an FK back to the appointment.
The same boundary applies to `patient.archived`: its handler commits recall
updates independently, so it must not run for an archive that can still roll
back.

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, after the DB commit succeeds.
3. Add the row to the table(s) above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
