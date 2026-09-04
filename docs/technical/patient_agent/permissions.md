# Patient Agent permissions

The `patient_agent` module exposes the following module permissions. Runtime access remains subject to DentalPin clinic membership, authentication, tenant isolation, and the additional patient-boundary rules introduced by later AI tranches.

| Permission | Purpose |
|---|---|
| `patient_agent.session.read` | Read patient-agent session metadata for authorized staff workflows. |
| `patient_agent.audit.read` | Read patient-agent audit events for authorized staff and governance workflows. |
| `patient_agent.handoff.accept` | Accept or act on a patient-agent escalation/handoff. |
| `patient_agent.configure` | Inspect and configure patient-agent foundation/runtime settings. |

## Role defaults

The module manifest grants:

- `admin`: all module permissions;
- `dentist`: `session.read`, `audit.read`, and `handoff.accept`;
- `receptionist`: `session.read` and `handoff.accept`.

Patients are not represented by these staff role defaults. Patient-facing access must use the authenticated patient identity boundary and purpose-built patient endpoints rather than reusing staff permissions.

## Invariants

- Permission checks never replace clinic/tenant scoping.
- Staff permission must never grant arbitrary access to another clinic's patient-agent sessions or audit events.
- Patient-facing endpoints must bind requests to the authenticated patient and must not accept an arbitrary patient identifier as authority.
- Realtime provider credentials must never be exposed through `configure` or other staff read permissions.
- Clinical actions remain constrained by the AI safety policy even when the caller has a broad DentalPin staff role.
