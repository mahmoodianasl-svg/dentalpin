# ADR 0015: Realtime patient AI agent boundary

- Status: Proposed
- Date: 2026-09-03

## Context

DentalPin v2.2.3 already contains a staff-facing Copilot built on the core agent engine. The next product increment adds a patient-facing agent capable of natural text, realtime voice and realtime video. Patient-facing media and clinical context create a materially different trust boundary from staff Copilot.

## Decision

Create a removable `patient_agent` module that is disabled by default and owns realtime session, consent and audit state. Reuse DentalPin's plugin, RBAC, agent-tool and event patterns; do not give the model direct database access.

The realtime transport is provider-neutral. WebRTC is the preferred browser transport for low-latency microphone/camera sessions. Provider credentials stay server-side and clients may receive only short-lived session credentials.

Every session is clinic-scoped and, once identity is established, patient-scoped. AI/audio/video consent is recorded independently; recording consent is separate and optional. Raw audio/video recording is not required for the MVP and must remain off unless explicitly enabled with policy and retention controls.

## Safety invariants

The patient agent may converse, collect structured intake, retrieve information authorized for that patient, explain approved material, propose appointments and hand off to humans.

It may not autonomously diagnose, prescribe, approve treatment plans, finalize clinical notes or alter clinical records. Appointment create/reschedule/cancel operations require explicit patient confirmation. Higher-risk clinical actions require human approval and the normal DentalPin service boundary.

Urgency detection is escalation support, not diagnosis. Emergency-risk signals must switch the agent to an escalation response and human/emergency guidance policy rather than continuing ordinary scheduling.

## Audit

Persist session lifecycle events, consent decisions, tool invocations/outcomes, handoffs and safety decisions with clinic/patient/session identifiers. Do not put provider secrets in audit payloads. Media contents are not persisted by default.

## Consequences

- Existing v2.2.3 behavior is unchanged because the module is not auto-installed.
- The first implementation can validate schema, policy and provider contracts without enabling external AI traffic.
- Text/voice/video can share one session model and safety policy.
- A later patient-auth tranche is required before exposing realtime sessions to patients.
- A later provider tranche must add ephemeral credential issuance, rate limits, abuse controls and media-session observability.
