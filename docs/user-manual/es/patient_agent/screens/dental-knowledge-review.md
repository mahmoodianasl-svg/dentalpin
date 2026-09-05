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

# Revisión de conocimiento dental

Utiliza esta pantalla para revisar contenido curado de educación al paciente antes de que pueda ser utilizado por la IA para pacientes.

## Qué puedes hacer

- Filtrar registros por estado de revisión.
- Abrir un registro para leer el contenido completo y su referencia de origen.
- Enviar registros en borrador o rechazados a revisión.
- Aprobar contenido para educación al paciente.
- Rechazar contenido indicando obligatoriamente el motivo de la decisión.

## Permisos

- `patient_agent.knowledge.read` permite ver la cola de revisión y los detalles de los registros.
- `patient_agent.knowledge.review` permite al personal dentista/administrador autorizado enviar, aprobar o rechazar registros.

El personal sin permiso de revisión solo puede consultar el contenido y no puede cambiar su estado.

## Límite de seguridad

La aprobación hace que el contenido curado sea elegible para educación al paciente. No autoriza a la IA a diagnosticar, prescribir, aprobar planes de tratamiento ni modificar la historia clínica.

## Solución de problemas

- **La página te redirige.** Tu rol no tiene `patient_agent.knowledge.read`.
- **Los botones de revisión no están disponibles.** Tu rol no tiene `patient_agent.knowledge.review`.
- **No se puede completar el rechazo.** Introduce un motivo de rechazo no vacío.
- **Un registro desaparece después de cambiar su estado.** El filtro actual ya no incluye ese estado; selecciona el nuevo estado o Todos.
