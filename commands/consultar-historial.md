---
description: Consulta qué se decidió/hizo antes en este proyecto para no repetir errores
---

Responde una pregunta navegando la memoria curada del proyecto. El tema viene en `$ARGUMENTS` (si está vacío, pregunta sobre qué quiere consultar el usuario). Es read-only: no escribe salvo que el usuario acepte filar la síntesis.

Lee primero `.memex/CLAUDE.md`.

## Qué hacer

1. **Localiza el memex** (`.memex/` desde cwd hacia arriba). Si no existe, dilo y termina.

2. **Lee en este orden de prioridad** (el objetivo es "no repetir errores", así que las lecciones van primero):
   a. `.memex/index.md` para el mapa general.
   b. `.memex/wiki/lessons/*.md` — busca por `trigger`, `tags` y título lo que matchee el tema. PRIORIDAD.
   c. `.memex/wiki/decisions/*.md` — ADRs relevantes (ojo al `status`: marca las `superseded`/`deprecated`).
   d. `.memex/wiki/flows/*.md` — flujos reusables relacionados.
   e. Navega los `[[wikilinks]]` de las páginas encontradas para traer contexto vecino.
   f. Opcional: `grep` sobre `.memex/raw/changelog.jsonl` por keyword/archivo para ver qué se tocó de verdad.

3. **Sintetiza la respuesta** en 3 bloques:
   - **Qué se decidió antes** — con links a las ADRs (señala las superseded).
   - **Errores ya cometidos (no repetir)** — con links a las lecciones y su regla.
   - **Flujos / patrones reusables** — con links a flows.
   Cita siempre con wikilinks clickeables.

4. **Si la cobertura es insuficiente** (poco o nada en la wiki), dilo explícitamente y sugiere correr `/destilar` por si hay crudo sin procesar.

5. **Ofrece filar** la síntesis en `.memex/wiki/synthesis/kebab-tema.md` (solo si el usuario acepta). Si la filas, conéctala con wikilinks a las páginas citadas y añádela al index.
