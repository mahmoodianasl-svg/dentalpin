---
module: patient_agent
screen: dental-knowledge-review
route: /ai/dental-knowledge
related_endpoints:
  - GET /api/v1/patient_agent/knowledge
  - GET /api/v1/patient_agent/knowledge/{record_id}
  - POST /api/v1/patient_agent/knowledge/{record_id}/submit
  - POST /api/v1/patient_agent/knowledge/{record_id}/approve
  - POST /api/v1/patient_agent/knowledge/{record_id}/reject
related_permissions:
  - patient_agent.knowledge.read
  - patient_agent.knowledge.review
related_paths:
  - backend/app/modules/patient_agent/frontend/pages/ai/dental-knowledge/index.vue
  - backend/app/modules/patient_agent/frontend/composables/useDentalKnowledgeReview.ts
last_verified_commit: 8fb18b6
---

# Dental knowledge review

Use this screen to review curated patient-education content before it becomes eligible for the patient AI.

## What you can do

- Filter records by review status.
- Open a record to read the full patient-education content and its source reference.
- Submit draft or rejected records for review.
- Approve content for patient education.
- Reject content with a required decision reason.

## Permissions

- `patient_agent.knowledge.read` allows staff to view the review queue and record details.
- `patient_agent.knowledge.review` allows permitted dentist/admin staff to submit, approve, or reject records.

Staff without review permission can read only and cannot change review status.

## Safety boundary

Approval makes curated content eligible for patient education. It does not authorize the AI to diagnose, prescribe, approve treatment plans, or modify clinical records.

## Troubleshooting

- **The page redirects away.** Your role does not have `patient_agent.knowledge.read`.
- **Review buttons are unavailable.** Your role does not have `patient_agent.knowledge.review`.
- **Reject does not complete.** Enter a non-empty rejection reason.
- **A record disappears after a status change.** The current status filter no longer includes the record; choose the new status or All.
