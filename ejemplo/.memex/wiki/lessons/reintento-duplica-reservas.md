---
type: lesson
severity: alta
trigger: "reintentos de pago o reservas duplicadas"
status: vigente
alcance: transversal
last_updated: 2026-01-15
sources:
  - raw/changelog.jsonl#2026-01-14T16:40:00-05:00
tags: [pedidos, inventario]
related: [0001-reservas-con-clave-de-idempotencia]
---

# Un reintento duplicó una reserva

Dos solicitudes iguales reservaron la misma bicicleta porque la clave se validaba después de descontar el inventario.

**Qué hacer:** validar primero y seguir [[0001-reservas-con-clave-de-idempotencia]].
