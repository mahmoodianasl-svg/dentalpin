# Patient agent module

Owns the disabled-by-default patient-facing realtime AI boundary: session state, consent evidence, audit events, provider abstraction and safety invariants for future text, voice, video and human handoff.

## Public API

- Routes mounted at `/api/v1/patient_agent/` when the module is installed.
- `GET /foundation` — exposes the AI-0 capability/safety contract; permission `patient_agent.configure`.
- AI-0 does not issue provider sessions and does not expose patient-facing realtime endpoints.

## Dependencies

`manifest.depends = []`. The module does not import feature-module services directly. Future patient/appointment capabilities must be consumed through registered tools/contracts so caller authorization remains enforceable.

The initial migration uses core `clinics.id`; patient references are deliberately stored as scoped identifiers in AI-0 rather than introducing a feature-module FK dependency.

## Permissions

- `patient_agent.session.read`
- `patient_agent.audit.read`
- `patient_agent.handoff.accept`
- `patient_agent.configure`

## Tools exposed

None in AI-0. Future tools must wrap existing DentalPin services and preserve their permission checks; the AI must never receive arbitrary database access.

## Events emitted

None in AI-0.

## Events consumed

None in AI-0.

## Lifecycle

- `installable=True`
- `auto_install=False`
- `removable=True`
- The module is intentionally opt-in so adding the code cannot alter existing v2.2.3 clinical behavior.
- Migration branch label: `patient_agent` (`pag_*`).

## Gotchas / non-obvious invariants

- Never autonomously diagnose, prescribe, approve treatment plans, alter clinical records, or finalize clinical notes.
- Appointment creation/reschedule/cancellation and other sensitive writes require explicit patient confirmation; clinical writes additionally require authorized human approval.
- AI/audio/video/recording consent are separate auditable decisions. Recording must never be inferred from microphone/camera consent.
- Realtime provider credentials stay server-side. A client may receive only short-lived session material.
- Every session/audit lookup must be scoped by clinic and, when a patient is authenticated, by that patient identity.
- Human handoff must preserve the session summary and audit trail without granting the AI broader staff permissions.
- Video is an intake/communication aid, not an autonomous diagnostic channel.

## Related ADRs

- `docs/adr/0015-patient-agent-realtime-boundary.md` — realtime/WebRTC boundary, consent, safety, audit and human-control decisions.
- `docs/adr/0001-modular-plugin-architecture.md` — module isolation and lifecycle.
- `docs/adr/0002-per-module-alembic-branches.md` — isolated migration branch requirement.
- `docs/adr/0003-event-bus-over-direct-imports.md` — cross-module integration rule.

## CHANGELOG

See `./CHANGELOG.md`.
