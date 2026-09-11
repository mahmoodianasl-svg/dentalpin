# Patient agent module

Owns DentalPin's disabled-by-default patient-facing AI boundary: realtime session state, consent evidence, audit events, provider abstraction, reviewed dental knowledge, guarded appointment integration and human handoff.

## Public API

Routes are mounted at `/api/v1/patient_agent/` when the module is installed. Current capabilities include:

- `GET /foundation` — exposes the capability/safety contract; permission `patient_agent.configure`.
- Patient-scoped realtime session creation and termination using short-lived provider session material.
- Patient-controlled visual snapshot consent revocation and server-side snapshot-share authorization.
- Patient dental-knowledge search over reviewed clinic-scoped content.
- Patient appointment availability, proposal and explicit-confirmation booking flows.
- Patient human-handoff requests plus clinic-scoped staff handoff review/acceptance routes.
- Patient portal and dental-knowledge review routes registered by the module.

## Dependencies

`manifest.depends = ["agenda", "schedules", "patients"]`.

Cross-module behavior must stay behind DentalPin adapters/contracts and preserve the underlying authorization and confirmation rules. The AI must never receive arbitrary database access or bypass feature-module permissions.

## Permissions

- `patient_agent.session.read`
- `patient_agent.audit.read`
- `patient_agent.handoff.accept`
- `patient_agent.configure`
- `patient_agent.knowledge.read`
- `patient_agent.knowledge.review`

## Tools and integrations

`get_tools()` currently exports no generic plugin tools. Patient-agent routes use explicit internal adapters/contracts for appointment and knowledge capabilities instead of exposing unrestricted feature-module services to the model.

## Events emitted

None currently declared as module events.

## Events consumed

None currently declared as module events.

## Lifecycle

- `installable=True`
- `auto_install=False`
- `removable=True`
- The module remains opt-in so installing the code does not silently change existing clinical workflows.
- Migration branch label: `patient_agent` (`pag_*`).

## Realtime and visual-snapshot boundary

- Long-lived provider credentials remain server-side; clients receive only short-lived session material.
- Realtime sessions are scoped to the authenticated clinic and patient.
- Visual snapshots require explicit snapshot-scoped video consent plus a server-side authorization preflight.
- Snapshot authorization is serialized on the scoped session to protect consent and rolling-share-limit checks from races.
- Mid-session visual consent revocation keeps voice active while blocking future snapshot authorization.
- The frontend also blocks programmatic snapshot sends while revocation is pending and re-checks consent state before provider delivery.
- Raw snapshot bytes are not persisted by DentalPin; audit evidence is metadata-only (for example MIME type, byte size and opaque snapshot identifier).
- Continuous video and recording are not enabled by snapshot consent.

## Gotchas / non-obvious invariants

- Never autonomously diagnose, prescribe, approve treatment plans, alter clinical records, or finalize clinical notes.
- Appointment creation/reschedule/cancellation and other sensitive writes require explicit patient confirmation; clinical writes additionally require authorized human approval.
- AI/audio/video/recording consent are separate auditable decisions. Recording must never be inferred from microphone/camera consent.
- Every patient session, consent, audit and mutation lookup must be scoped by clinic and authenticated patient identity where applicable.
- Human handoff must preserve the session summary and audit trail without granting the AI broader staff permissions.
- Video/snapshots are intake and communication aids, not autonomous diagnostic channels.
- Knowledge surfaced to patients must remain within the reviewed/published knowledge boundary and preserve source attribution/fallback behavior.
- At most one approved version of an entry may be active for patient education. Approval serializes on the clinic and entry key, retires older versions, and must never replace an equal or newer active version.
- Withdrawing approved knowledge requires an explicit staff reason, clears patient-education eligibility and semantic index data, and emits metadata-only audit evidence.

## Related ADRs

- `docs/adr/0015-realtime-patient-ai-agent.md` — realtime/WebRTC boundary, consent, safety, audit and human-control decisions.
- `docs/adr/0001-modular-plugin-architecture.md` — module isolation and lifecycle.
- `docs/adr/0002-per-module-alembic-branches.md` — isolated migration branch requirement.
- `docs/adr/0003-event-bus-over-direct-imports.md` — cross-module integration rule.

## CHANGELOG

See `./CHANGELOG.md`.
