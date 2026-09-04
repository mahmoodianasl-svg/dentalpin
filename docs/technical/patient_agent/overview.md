# Patient Agent technical overview

The `patient_agent` module is the disabled-by-default foundation for patient-facing AI communication in DentalPin. It owns realtime session state, consent evidence, audit events, provider-neutral realtime contracts, and the safety boundary for future text, voice, and video interactions.

## Scope

AI-0 establishes infrastructure only. It does not create live provider sessions and does not expose autonomous clinical behavior.

The module is designed to support later tranches for:

- authenticated patient text conversations;
- low-latency voice sessions;
- WebRTC video sessions;
- patient-context retrieval through explicit DentalPin service/tool contracts;
- appointment availability and confirmation flows;
- receptionist or dentist handoff;
- complete auditability of significant AI actions.

## Safety boundary

The patient agent may eventually converse, retrieve authorized context, collect intake information, explain approved information, and propose administrative actions. It must not autonomously diagnose, prescribe, approve treatment plans, finalize clinical notes, or alter clinical records.

Sensitive administrative mutations such as appointment creation, rescheduling, or cancellation require explicit patient confirmation before DentalPin services execute the change.

## Data ownership

The module owns:

- `patient_agent_sessions`;
- `patient_agent_consents`;
- `patient_agent_audit_events`.

Every patient-agent query and future tool call must remain tenant-scoped by `clinic_id`. Patient-specific operations must additionally enforce the authenticated patient boundary.

## Realtime provider boundary

`providers/base.py` defines a provider-neutral realtime interface. Long-lived provider credentials remain server-side. Future provider implementations may issue only short-lived client session material suitable for the authenticated browser or mobile client.

Video transport is expected to use WebRTC in a later tranche. AI-0 stores only the session and consent foundation and does not persist media by default.

## Consent

Consent types are modeled separately for AI interaction, audio, video, and recording. Recording is optional and must never be inferred from audio or video consent.

## Audit

Significant patient-agent events are persisted with clinic, patient/session context, actor type, outcome, detail, reason, and timestamp. Later tranches must record tool invocation, confirmation, handoff, provider-session lifecycle, and other material actions.

## Lifecycle

The module is installable and removable but has `auto_install=False`. Existing DentalPin behavior therefore remains unchanged until the module is deliberately enabled and later-phase runtime functionality is configured.

## Related ADR

- `docs/adr/0015-patient-realtime-ai-agent.md` — architecture, realtime boundary, consent, clinical safety, and delivery phasing.
