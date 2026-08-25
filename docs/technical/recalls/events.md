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
| `recall.created` | A new recall transaction commits (duplicate-guard updates commit without publishing) |
| `recall.completed` | A recall `done` transition commits |
| `recall.snoozed` | A recall snooze transaction commits |
| `recall.cancelled` | A recall cancellation transaction commits |

`recall.due` is reserved for a future scheduler and is not published in V1.

Live HTTP and Copilot-tool mutations use the service's
`commit_and_publish_*` helpers. The appointment-completion subscriber batches
all matching recall updates into one transaction and publishes their
`recall.completed` events only after that commit succeeds. Failed commits emit
no recall lifecycle events.

## Subscribed

| Event | Handler | Effect |
|-------|---------|--------|
| `appointment.cancelled` | `events.on_appointment_cancelled` | After the transition commits, unlink active recalls and revert `contacted_scheduled` to `pending` |
| `appointment.completed` | `events.on_appointment_completed` | After the transition commits, mark the recall linked to that appointment `done` |
| `appointment.scheduled` | `events.on_appointment_scheduled` | In a fresh DB session, auto-link one unambiguous due recall after the appointment has committed |
| `patient.archived` | `events.on_patient_archived` | Move active recalls to `needs_review` |
| `treatment_plan.treatment_completed` | `events.on_treatment_plan_completed` | Logging-only hook; suggestions remain pull-based |

The `appointment.scheduled` producer must publish after commit: this handler
opens an independent session and persists an FK back to the appointment.
The same boundary applies to `patient.archived`: its handler commits recall
updates independently, so it must not run for an archive that can still roll
back.

The completion and cancellation handlers also commit recall changes in fresh
sessions. Agenda therefore publishes both terminal events only after the
appointment status transaction commits.

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, after the DB commit succeeds.
3. Add the row to the table(s) above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
