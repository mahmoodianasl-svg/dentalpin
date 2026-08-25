---
module: clinical_notes
last_verified_commit: 50cce0f
---

# Clinical-notes — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

One event per note type. The publish call passes a variable resolved
from the `_NOTE_TYPE_TO_EVENT` map in `service.py`, so the catalog
attributes these from the `EventType` constants referenced in that file.

| Event | When | Consumers |
|-------|------|-----------|
| `clinical_notes.diagnosis_created` | After a diagnosis note commits | patient_timeline |
| `clinical_notes.treatment_created` | After a treatment note commits | patient_timeline |
| `clinical_notes.plan_created` | After a treatment-plan note commits | patient_timeline |
| `clinical_notes.administrative_created` | After an administrative note commits | patient_timeline |
| `clinical_notes.appointment_clinical_created` | After a clinical appointment note commits | — |
| `clinical_notes.appointment_administrative_created` | After an administrative appointment note commits | — |

> **Known gap (audit event-bus #7):** the two `appointment_*` note
> events have no subscriber, so notes captured on an appointment do not
> currently reach the patient timeline. Tracked separately from this
> docs backfill.

Payloads carry `clinic_id`, `patient_id`, and a `body_excerpt`.

`NoteService.create` flushes the note and any attachment links but does not
publish. Its live route completes through `commit_and_publish_created`, which
commits the producer transaction before dispatching the event. This ordering is
required because `patient_timeline` records projections in an independent
session: if the producer commit fails, no lifecycle event is emitted and no
orphan timeline row can be committed.

## Subscribed

_This module does not subscribe to any events_ (`get_event_handlers`
returns `{}`).

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, **after the DB commit succeeds**.
3. Add the row to the table above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
