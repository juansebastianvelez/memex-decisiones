---
type: decision
id: 0001
status: vigente
alcance: transversal
last_updated: 2026-01-15
sources:
  - raw/changelog.jsonl#2026-01-12T09:14:00-05:00
tags: [pedidos, inventario]
related: [reintento-duplica-reservas, flujo-de-reserva]
---

# Reservas con clave de idempotencia

## Contexto
La pasarela ficticia de Ruta Verde reintenta las solicitudes cuando no recibe respuesta.

## Decisión
Cada reserva exige una clave de idempotencia. Si la clave ya existe, se devuelve la reserva original.

## Alternativas
Bloquear el inventario por cliente. Se descartó porque no evita el reintento de la misma solicitud.

## Consecuencias
La tabla de reservas guarda la clave con índice único. El proceso completo está en [[flujo-de-reserva]] y el error que lo motivó en [[reintento-duplica-reservas]].
