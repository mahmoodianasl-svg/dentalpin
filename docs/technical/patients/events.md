---
module: patients
last_verified_commit: HEAD
---

# Patients — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

| Event | Source | When | Payload |
|-------|--------|------|---------|
| `patient.created` | `service.py:PatientService.commit_and_publish_created` | After the create transaction commits. | `patient_id` (UUID string), `clinic_id` (UUID string) |
| `patient.updated` | `service.py:PatientService.commit_and_publish_updated` | After the update transaction commits. | `patient_id` (UUID string), `clinic_id` (UUID string), `changes` (list of field names) |
| `patient.archived` | `service.py:PatientService.commit_and_publish_archived` | After the soft-archive transaction commits. | `patient_id` (UUID string), `clinic_id` (UUID string) |

Subscribers are listed in the auto-generated [events catalog](../../events-catalog.md).

The mutation methods only flush. HTTP and copilot callers use the matching
`commit_and_publish_*` helper. Migration imports build the same payload and
queue it until their containing batch commit succeeds.

## Subscribed

This module does not subscribe to any events.

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, after the DB commit succeeds.
3. Add a row to the table above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the global
   catalog.
