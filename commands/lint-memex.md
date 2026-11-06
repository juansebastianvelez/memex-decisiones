---
description: Health-check del grafo de decisiones del memex (huérfanas, links rotos, etc.)
---

Valida la integridad del `.memex/` del proyecto actual. No modifica nada sin confirmación.

Lee primero `.memex/CLAUDE.md`.

## Qué hacer

1. **Localiza el memex** (`.memex/` desde cwd hacia arriba). Si no existe, dilo y termina.

2. **Revisa y clasifica los hallazgos** en Críticos / Importantes / Sugerencias:

   **Conexión del grafo (lo primero):**
   - Páginas SIN ningún wikilink saliente ni `related:` → huérfanas (viola la regla dura). CRÍTICO.
   - Wikilinks `[[...]]` que apuntan a páginas inexistentes → links rotos. CRÍTICO.
   - Backlinks no recíprocos (A enlaza a B pero B no menciona a A en `related:`). IMPORTANTE.

   **Frontmatter / contenido:**
   - Páginas sin `type`, `last_updated` o `sources`. IMPORTANTE.
   - Lecciones sin campo `trigger`. IMPORTANTE.
   - ADRs `superseded`/`deprecated` aún referenciadas como vigentes en otras páginas. IMPORTANTE.
   - Decisiones `accepted` que se contradicen entre sí. CRÍTICO si aplica.

   **Sincronía:**
   - `.memex/index.md` desincronizado (páginas que existen pero no están en el índice, o al revés). IMPORTANTE.
   - Watermark atrasado: muchas líneas de `changelog.jsonl` por encima de `.distilled_until` (crudo sin destilar). Sugiere `/destilar`. SUGERENCIA.
   - Tags inconsistentes (variantes del mismo tag). SUGERENCIA.

3. **Reporta** en formato:
   ```
   ## Lint del memex — [fecha]
   ### 🔴 Críticos
   ### 🟡 Importantes
   ### 🔵 Sugerencias
   ### 📊 Métricas (N decisiones, N lecciones, N flujos, watermark X/Y)
   ```

4. **Solo con confirmación del usuario**, aplica arreglos automáticos (conectar huérfanas, reparar links, sincronizar index). Append a `.memex/log.md` si se aplicó algo.
