---
description: Registra una decisión de diseño (ADR) en el memex, conectada al grafo
---

Crea una página de decisión (ADR) a mano, sin esperar al destilado automático. La decisión a registrar viene en `$ARGUMENTS` (si está vacío, pregunta al usuario qué decisión registrar).

Lee primero `.memex/CLAUDE.md` para refrescar las reglas.

## Qué hacer

1. **Localiza el memex** (`.memex/` desde cwd hacia arriba). Si no existe, sugiere `/memex-init` y termina.

2. **Calcula el id**: mira `.memex/wiki/decisions/`, toma el mayor `NNNN` y suma 1 (4 dígitos, ej. `0007`).

3. **Detecta relaciones**:
   - ¿Hay una ADR existente sobre el mismo tema que esta decisión reemplaza? Si sí, cambia su `status` a `superseded` y rellena el campo `supersedes` de la nueva con su id.
   - Busca en `.memex/index.md` decisiones, lecciones y flujos relacionados para enlazar.

4. **Auto-puebla `sources`**: revisa los eventos recientes en `.memex/raw/changelog.jsonl` de esta sesión y referencia los relevantes como `raw/changelog.jsonl#<ts>`.

5. **Crea `.memex/wiki/decisions/NNNN-kebab-titulo.md`**:
   ```markdown
   ---
   type: decision
   id: NNNN
   title: <título de la decisión>
   status: accepted
   date: <HOY>
   last_updated: <HOY>
   tags: [<tema>, ...]
   sources:
     - raw/changelog.jsonl#<ts>
   related:
     - "[[.memex/wiki/...]]"
   supersedes: null
   ---

   # <Título de la decisión>

   ## Contexto
   <Por qué se tomó, qué problema resuelve.>

   ## Decisión
   <Qué se decidió, en concreto.>

   ## Alternativas consideradas
   <Qué otras opciones se evaluaron y por qué se descartaron.>

   ## Consecuencias (trade-offs)
   <Qué gana y qué cuesta esta decisión.>

   ## Conexiones
   <Wikilinks a decisiones/lecciones/flujos relacionados.>
   ```

6. **Regla dura**: la nueva ADR debe tener al menos un wikilink saliente en `related:` o en Conexiones. Añade el backlink recíproco en la página enlazada. Si no hay vecino real, enlázala al `.memex/index.md`.

7. **Actualiza `.memex/index.md`** (sección Decisiones) y **append a `.memex/log.md`**:
   ```
   ## [YYYY-MM-DD] decision | NNNN <título>
   ```

8. Ofrece commit de la wiki. Reporta el path de la ADR creada.
