---
module: budget
screen: create
route: /budgets/new
related_endpoints:
  - DELETE /api/v1/budget/budgets/{budget_id}
  - DELETE /api/v1/budget/budgets/{budget_id}/items/{item_id}
  - GET /api/v1/budget/budgets
  - GET /api/v1/budget/budgets/{budget_id}
  - GET /api/v1/budget/budgets/{budget_id}/history
  - GET /api/v1/budget/budgets/{budget_id}/pdf
  - GET /api/v1/budget/budgets/{budget_id}/pdf/preview
  - GET /api/v1/budget/budgets/{budget_id}/pdf/signed
  - GET /api/v1/budget/budgets/{budget_id}/signature
  - GET /api/v1/budget/budgets/{budget_id}/versions
  - POST /api/v1/budget/budgets
  - POST /api/v1/budget/budgets/{budget_id}/accept
  - POST /api/v1/budget/budgets/{budget_id}/accept-in-clinic
  - POST /api/v1/budget/budgets/{budget_id}/cancel
  - POST /api/v1/budget/budgets/{budget_id}/duplicate
  - POST /api/v1/budget/budgets/{budget_id}/items
  - POST /api/v1/budget/budgets/{budget_id}/reject
  - POST /api/v1/budget/budgets/{budget_id}/renegotiate
  - POST /api/v1/budget/budgets/{budget_id}/resend
  - POST /api/v1/budget/budgets/{budget_id}/send
  - POST /api/v1/budget/budgets/{budget_id}/send-reminder
  - POST /api/v1/budget/budgets/{budget_id}/set-public-code
  - POST /api/v1/budget/budgets/{budget_id}/unlock-public
  - PUT /api/v1/budget/budgets/{budget_id}
  - PUT /api/v1/budget/budgets/{budget_id}/items/{item_id}
related_permissions:
  - budget.read
  - budget.write
related_paths:
  - backend/app/modules/budget/frontend/pages/budgets/new.vue
  - backend/app/modules/budget/router.py
last_verified_commit: b1b82f5
---

# Nuevo presupuesto

Formulario para crear un presupuesto desde cero. Al guardar nace en
estado `draft` y el flujo continúa desde el
[detalle](./budgets_id.md).

## De un vistazo

- **Origen del presupuesto.** Suele llegarse aquí desde:
  - La ficha del paciente → *Nuevo presupuesto* (paciente
    preseleccionado).
  - El listado → **Nuevo presupuesto** (selector de paciente
    obligatorio).
  - Un plan de tratamiento → genera un presupuesto sincronizado por
    eventos `treatment_plan.treatment_added` /
    `treatment_plan.budget_sync_requested`.
- **Numeración automática.** El número (`PRES-AAAA-####`) se asigna
  al guardar; no es editable.
- **Validez por defecto** — el formulario propone `valid_from = hoy`
  y `valid_until = hoy + 30 días`. Edítalo si vuestra política es
  otra.
- **Snapshot de precios.** Cada línea guarda el precio del catálogo
  vigente al crear el presupuesto. Cambiar el catálogo después no
  afecta a presupuestos existentes.

## Crear un presupuesto

> Requiere `budget.write`.

1. Si no vienes de la ficha del paciente, selecciona el paciente en
   la cabecera.
2. Añade ítems desde el catálogo. Por cada línea puedes elegir:
   - Diente y superficies (notación FDI).
   - Cantidad, precio unitario (precargado del catálogo),
     descuento por línea (porcentaje o absoluto).
   - Tipo de IVA (precargado del catálogo).
3. Aplica un descuento global si procede.
4. Revisa los totales en el panel lateral.
5. **Guardar**. El presupuesto se crea en `draft` y te lleva al
   [detalle](./budgets_id.md) para enviarlo, firmarlo o
   facturarlo más tarde.

## Crear desde un plan de tratamiento

> Requiere `budget.write` y `treatment_plan.write`.

1. En el plan de tratamiento, pulsa **Generar presupuesto**.
2. Los tratamientos del plan llegan al formulario como líneas
   prerrellenadas mediante un evento snapshot.
3. Ajusta lo que necesites y guarda.

## Permisos

| Lo que ves / puedes hacer | Permiso |
|---------------------------|---------|
| Acceder al formulario y ver el catálogo | `budget.read` |
| Crear el presupuesto | `budget.write` |

## Resolución de problemas

- **El selector de paciente está vacío.** No tienes el permiso
  `patients.read` (sin él el formulario no puede listar pacientes).
- **No encuentro un ítem del catálogo.** Comprueba que esté activo en
  *Ajustes → Catálogo* y que tu rol tenga `catalog.read`.
- **El total no suma lo que espero.** Revisa el descuento por línea
  vs el global. Orden de aplicación: precio × cantidad → descuento
  línea → IVA → descuento global sobre el total.
