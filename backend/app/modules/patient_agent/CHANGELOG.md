# Changelog — patient_agent module

## Unreleased

- Added realtime provider session issuance with patient identity binding and short-lived client credentials.
- Added patient-scoped appointment availability, signed confirmation tokens, and confirmation-only booking commits.
- Added human handoff APIs and audit coverage.
- Added clinic-scoped staff handoff queue, detail, and single-claim acceptance with staff audit evidence.
- Added optional patient-selected PNG/JPEG visual snapshots to realtime voice sessions with explicit snapshot-scoped consent, while continuous video and recording remain disabled.
- Added server-side visual snapshot share preflight with patient/session scope checks, persisted metadata-only audit evidence, and a rolling per-session share limit before provider delivery.
- Serialized visual snapshot preflight on the scoped patient-agent session so concurrent authorization requests cannot race the rolling share limit.
- Added metadata-only audit evidence for visual snapshot attempts denied because snapshot-scoped consent is absent.
- Visual snapshots are sent as realtime context only and remain subject to the patient-agent prohibition on autonomous diagnosis, prescribing, treatment approval, and clinical-record writes.
- Raw snapshot content is not persisted by DentalPin; visual-share audit evidence contains only authorization metadata such as MIME type, byte size and an opaque snapshot ID.
- Declared `agenda` and `schedules` as explicit module dependencies for the patient scheduling adapter.
- Refreshed the generated DentalPin module catalog after AI-1 dependency integration.

## 0.1.0 — 2026-09-03

- Added disabled-by-default patient-facing AI module foundation.
- Added text/voice/video realtime session state model.
- Added separate AI, audio, video, and recording consent evidence.
- Added patient-agent audit event persistence.
- Added provider-neutral realtime session contract.
- Added safety policy blocking autonomous diagnosis, prescribing, treatment approval, and clinical-record finalization.
- Added explicit confirmation boundaries for appointment and other sensitive administrative mutations.
- Added reversible isolated `pag_0001` Alembic migration branch.
- Added administrator foundation-status API and focused contract tests.
- Registered the module in the generated DentalPin module catalog.