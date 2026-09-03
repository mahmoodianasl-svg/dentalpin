# Changelog — patient_agent module

## Unreleased

- Realtime provider session issuance, patient identity binding, appointment tools, and human handoff APIs are planned for subsequent AI tranches.

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
