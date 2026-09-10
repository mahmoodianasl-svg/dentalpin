# Changelog — patient_agent module

## Unreleased

- Added clinic-scoped semantic ranking for approved patient-education knowledge with content-bound embeddings, cosine similarity, deterministic lexical fallback, approval-time indexing, stale-vector invalidation, and a controlled staff reindex endpoint for already-approved knowledge.
- Added metadata-only realtime tool and safety-decision audit coverage: patient knowledge searches now persist success/fallback outcomes without raw queries; intake-risk decisions record tool/action provenance; automatic escalation is attributed to the system; and handoff audits no longer persist raw patient summaries.
- Added server-side deterministic intake-risk assessment for structured patient safety signals; urgent and emergency-risk assessments automatically trigger human handoff, and an existing higher-risk session state cannot be downgraded by later lower-risk input.
- Removed model-assigned handoff urgency from the realtime tool boundary; direct handoff requests now inherit DentalPin's server-derived session risk.
- Added realtime provider session issuance with patient identity binding and short-lived client credentials.
- Added patient-scoped appointment availability, signed confirmation tokens, and confirmation-only booking commits.
- Added human handoff APIs and audit coverage.
- Added clinic-scoped staff handoff queue, detail, and single-claim acceptance with staff audit evidence.
- Added optional patient-selected PNG/JPEG visual snapshots to realtime voice sessions with explicit snapshot-scoped consent, while continuous video and recording remain disabled.
- Added server-side visual snapshot share preflight with patient/session scope checks, persisted metadata-only audit evidence, and a rolling per-session share limit before provider delivery.
- Serialized visual snapshot preflight on the scoped patient-agent session so concurrent authorization requests cannot race the rolling share limit.
- Added metadata-only audit evidence for visual snapshot attempts denied because snapshot-scoped consent is absent.
- Committed consent-denied visual snapshot audit evidence before returning HTTP 403 so request rollback cannot erase the security event.
- Added patient-scoped realtime session termination with lifecycle audit evidence and best-effort provider cleanup so ended sessions can no longer authorize visual snapshots.
- Added patient-controlled mid-session visual snapshot consent revocation that keeps voice active, appends a denial consent event, serializes with snapshot preflight on the session row, and makes the latest video-consent event authoritative for future image sharing.
- Added a client-side revocation race guard so visual snapshot authorization and provider delivery are refused while consent revocation is in progress, including programmatic sends outside the normal UI controls.
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