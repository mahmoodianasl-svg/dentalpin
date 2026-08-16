# Catalog module

Treatment catalog, categories, VAT types. Foundational pricing source
of truth for budgets and billing.

## Public API

Routes mounted at `/api/v1/catalog/`.

## Dependencies

`manifest.depends = []`. Foundational.

## Permissions

`catalog.read`, `catalog.write`, `catalog.admin`.

## Tools exposed

Agent tools in `tools.py` (wrap `CatalogService`, no logic duplicated).

| Tool | Category | Wraps | Permission |
|---|---|---|---|
| `list_catalog_items` | READ | `CatalogService.list_items` | `catalog.read` |
| `get_catalog_item` | READ | `CatalogService.get_item` | `catalog.read` |

Both filter by `ctx.clinic_id`. `names`/`descriptions` are localized
JSONB; the tools collapse to `es` → `en` → first value for the agent.

## Events emitted

None.

## Events consumed

None.

## Lifecycle

- `removable=False`. Budget, billing, odontogram, treatment_plan all
  depend on this.

## Gotchas

- **Session template** (``CatalogItemSession``) is optional per item;
  when present, the sum of ``default_price`` across sessions must
  equal the item's ``default_price`` (tolerance ±0.01). PUT
  ``/items/{id}`` with ``sessions`` (list, even empty) replaces the
  template atomically via ORM ``item.sessions.clear()`` + re-append;
  omitting the key preserves the existing template. Consumers
  (treatment_plan) snapshot this template at plan-add time.
- **VAT types are versioned** — when changing a VAT rate, create a new
  version rather than mutating in place. Historical invoices must
  reproduce their original VAT.
- **Pricing rules live in `pricing.py`** — keep service code thin and
  delegate calculations there.
- **Seed data** is shipped via `seed.py` and idempotent — re-running it
  must not duplicate categories.

## Related ADRs

- `docs/adr/0001-modular-plugin-architecture.md`

## CHANGELOG

See `./CHANGELOG.md`.
