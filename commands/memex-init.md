---
description: Inicializa el .memex/ (memoria de decisiones) en el proyecto actual
---

Crea la estructura `.memex/` en la raíz del proyecto actual (cwd). Es la única acción manual obligatoria del sistema; después la captura y la conexión son automáticas.

## Qué hacer

1. **Idempotencia**: si ya existe `.memex/` en cwd, NO sobreescribas nada. Reporta "ya inicializado" y termina.

2. **Detecta el tipo de proyecto** (para la semilla del CLAUDE.md): ¿hay `package.json`, `pyproject.toml`, workflows de n8n, etc.? Anótalo en una frase.

3. **Crea el árbol de carpetas**:
   ```
   .memex/raw/
   .memex/wiki/decisions/
   .memex/wiki/lessons/
   .memex/wiki/flows/
   .memex/wiki/synthesis/
   ```

4. **Crea `.memex/raw/changelog.jsonl`** vacío y **`.memex/raw/.distilled_until`** con el contenido `0`.

5. **Crea `.memex/.gitignore`** con:
   ```
   # El changelog crudo es ruido local; la wiki curada SÍ se versiona.
   raw/
   ```

6. **Crea `.memex/CLAUDE.md`** con este contenido (ajusta la primera frase al tipo de proyecto detectado):
   ```markdown
   # Memex de decisiones — <nombre del proyecto>

   Memoria de decisiones, lecciones y flujos de este proyecto, estilo Memex/Zettelkasten.
   Tu rol: bibliotecario. Conectas todo con wikilinks para poder indagar entre contenido indexado.

   ## Capas
   - `raw/changelog.jsonl` — INMUTABLE. Lo escriben los hooks (append). Nunca lo edites a mano salvo el watermark.
   - `raw/.distilled_until` — watermark: nº de líneas del changelog ya destiladas.
   - `wiki/` — tu propiedad: decisions/ (ADRs), lessons/ (errores a no repetir), flows/ (flujos reusables), synthesis/.
   - `index.md` / `log.md` — catálogo y changelog curado.

   ## Reglas duras
   1. Cada página lleva frontmatter: `type`, `last_updated`, `sources`, `tags`, `related`.
   2. NINGUNA página se guarda sin al menos un wikilink saliente `[[...]]` a contenido relevante existente.
      Añade el backlink recíproco en `related:` del otro lado. Si no hay vecino, enlázala al índice de su categoría.
   3. Cada claim se rastrea a un evento en `raw/changelog.jsonl` (campo `sources` con `raw/changelog.jsonl#<ts>`) o a una fuente real.
   4. No inventes. Sin source -> no lo escribas.
   5. Naming: `kebab-case.md`. ADRs: `NNNN-titulo.md` (id secuencial). H1 legible en español.

   ## Tipos de página
   | type | carpeta | uso |
   |------|---------|-----|
   | decision | wiki/decisions/ | ADR: Contexto -> Decisión -> Alternativas -> Consecuencias. Campos extra: `id`, `status`, `supersedes`. |
   | lesson | wiki/lessons/ | Error a no repetir. Campos extra: `severity`, `trigger` (situación que la dispara, buscable). Cuerpo: Qué pasó -> Por qué fue error -> Regla -> Cómo detectarlo antes. |
   | flow | wiki/flows/ | Flujo reusable (n8n/dev). Campos extra: `flow_kind`, `status`. Links a las decisions y lessons asociadas. |
   | synthesis | wiki/synthesis/ | Respuestas curadas de /consultar-historial. |

   ## Automático (sin comandos)
   - Los hooks registran cada cambio en `raw/changelog.jsonl`.
   - Al cerrar sesión, si hay eventos sin destilar, Claude los ingesta y conecta con wikilinks solo.
   - Comandos manuales disponibles: /registrar-decision, /consultar-historial, /destilar, /lint-memex.
   ```

7. **Crea `.memex/index.md`**:
   ```markdown
   # Índice del Memex

   Catálogo de toda la memoria curada. Punto de entrada para /consultar-historial.

   ## Decisiones (ADRs)
   _(ninguna todavía)_

   ## Lecciones (errores a no repetir)
   _(ninguna todavía)_

   ## Flujos
   _(ninguno todavía)_

   ## Síntesis
   _(ninguna todavía)_
   ```

8. **Crea `.memex/log.md`**:
   ```markdown
   # Log del Memex (append-only)

   Formato: `## [YYYY-MM-DD] <action> | <descripción>`. Actions: init, destilar, decision, consulta, lint.

   ## [<HOY>] init | memex inicializado
   ```
   Usa la fecha real de hoy.

9. **No commitees** automáticamente. Reporta al usuario qué se creó, recuérdale que `.gitignore` deja `raw/` fuera de git, y que de ahora en adelante todo es automático (solo sugiere `/destilar` si quiere forzar el primer ingest).
