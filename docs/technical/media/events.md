---
module: media
last_verified_commit: HEAD
---

# Media — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

| Event | Source | Effect |
|-------|--------|--------|
| `document.uploaded` | `service.py:DocumentService.upload_document` | Announces a non-photo document upload. |
| `document.deleted` | `service.py:DocumentService.delete_document` | Announces a document soft-delete. |
| `media.photo_uploaded` | `service.py:DocumentService.upload_document` | Announces a photo or X-ray upload. |
| `media.pair_created` | `service.py:PhotoService.create_pair` | Announces a before/after pair. |
| `media.pair_removed` | `service.py:PhotoService.remove_pair` | Announces pair removal. |
| `media.attachment_linked` | `service.py:AttachmentService.link` | Announces an attachment link. |
| `media.attachment_unlinked` | `service.py:AttachmentService.unlink` | Announces attachment unlinking. |

## Subscribed

| Event | Handler | Effect |
|-------|---------|--------|
| `patient.archived` | `MediaModule._on_patient_archived` | After the patient commit, soft-archive its documents in an independent transaction. |

Post-commit delivery is required: the media cascade commits independently and
must not survive a rolled-back patient archive.

## Adding a new event

1. Add the constant to `backend/app/core/events/types.py` (`EventType`).
2. Publish from a service method, after the DB commit succeeds.
3. Add the row to the table(s) above.
4. Run `python backend/scripts/generate_catalogs.py` to refresh the
   global catalog.
