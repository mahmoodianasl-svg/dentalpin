# Changelog — patients_clinical module

## Unreleased

- refactor(types): drop the ``as unknown as Record<string, unknown>`` cast in ``useMedicalHistory`` now that ``useApi`` accepts ``object`` payloads.
- Added per-module `CLAUDE.md` for AI-agent context (2026-04-27).

## 0.1.0 — initial

- Normalized medical history, allergies, medications, emergency contacts.
- `patient.medical_updated` event for the timeline.
- Role-scoped permissions: hygienists read-only on medical, write on emergency.
