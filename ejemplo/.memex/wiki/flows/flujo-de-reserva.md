---
type: flow
flow_kind: dev
status: vigente
alcance: transversal
last_updated: 2026-01-15
sources:
  - raw/changelog.jsonl#2026-01-15T11:02:00-05:00
tags: [pedidos, inventario]
related: [0001-reservas-con-clave-de-idempotencia]
---

# Flujo de reserva

1. Recibir el pedido con su clave de idempotencia.
2. Buscar la clave. Si existe, devolver la reserva original.
3. Descontar el inventario y guardar la reserva en la misma transacción.

La regla viene de [[0001-reservas-con-clave-de-idempotencia]].
