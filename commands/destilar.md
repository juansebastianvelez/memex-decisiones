---
description: Destila el changelog crudo del .memex en páginas wiki conectadas con wikilinks
---

Fuerza manualmente el mismo ciclo de ingest + conexión que dispara el hook `Stop` al cerrar sesión. Útil para destilar a mitad de sesión. Argumentos opcionales: `$ARGUMENTS` (ej. `--session <id>` o un rango de fechas).

Lee primero `.memex/CLAUDE.md` del proyecto para refrescar las reglas duras (sobre todo: ninguna página sin wikilink saliente).

## Qué hacer

1. **Localiza el memex**: busca `.memex/` desde cwd hacia arriba. Si no existe, di "este proyecto no tiene memex; corre /memex-init" y termina.

2. **Calcula pendientes**: lee `.memex/raw/.distilled_until` (entero `N`). Lee `.memex/raw/changelog.jsonl`. Los pendientes son las líneas `N+1` en adelante. Si `$ARGUMENTS` filtra por sesión/fecha, aplica el filtro.

3. **Si no hay pendientes**, reporta "0 eventos nuevos" y termina.

4. **Agrupa** los eventos pendientes por tema/sesión/archivo. Para cada grupo decide qué representa:
   - Una **decisión** de diseño/arquitectura → `wiki/decisions/NNNN-titulo.md` (id secuencial; status `accepted`).
   - Una **lección** / error a no repetir → `wiki/lessons/titulo.md` (con `trigger` y `severity`).
   - Un **flujo** reusable (n8n/dev) → `wiki/flows/titulo.md` (con `flow_kind`, `status`).
   - Si un grupo es trivial (ruido), NO crees página; solo quedará en el crudo.

5. **Escribe/actualiza las páginas** con frontmatter completo (`type`, `last_updated`, `sources` con `raw/changelog.jsonl#<ts>` de los eventos del grupo, `tags`, `related`).

6. **CONECTA (regla dura)**: antes de guardar cada página, lee `.memex/index.md` y busca páginas existentes relevantes por tema/tags/título. Añade al menos un wikilink saliente `[[.memex/wiki/.../slug]]` y el backlink recíproco en `related:` de la otra página. Si de verdad no hay vecino, enlázala al índice de su categoría. Ninguna página queda huérfana.

7. **Actualiza `.memex/index.md`** (añade las páginas nuevas en su sección).

8. **Append a `.memex/log.md`**:
   ```
   ## [YYYY-MM-DD] destilar | N eventos -> M decisiones, K lecciones, J flujos
   - Creadas/actualizadas: [[...]], [[...]]
   ```

9. **Avanza el watermark**: escribe en `.memex/raw/.distilled_until` el número total de líneas del changelog (no quedan pendientes).

10. **Ofrece commit** de la wiki (recuerda: `raw/` está en `.gitignore`):
    ```bash
    git add .memex/wiki .memex/index.md .memex/log.md
    git commit -m "memex: destila N eventos -> M páginas"
    ```

11. Reporta qué se creó/actualizó con links clickeables.

## Recordatorio
- No edites `raw/changelog.jsonl` (solo lectura). Lo único que tocas en `raw/` es `.distilled_until`.
- No crees una página por evento aislado y trivial. Agrupa por significado.
