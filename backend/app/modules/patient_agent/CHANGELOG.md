# Changelog — patient_agent module

## Unreleased

- Added realtime provider session issuance with patient identity binding and short-lived client credentials.
- Added patient-scoped appointment availability, signed confirmation tokens, and confirmation-only booking commits.
- Added human handoff APIs and audit coverage.
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
