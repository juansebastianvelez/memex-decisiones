# Instalar el Memex de Decisiones — instrucciones para Claude Code

Eres Claude Code y el usuario te pidió instalar este kit. Síguelo en orden y reporta
el resultado de cada paso. No improvises copiando archivos a mano: usa `install.py`,
que fusiona `settings.json` de forma segura (backup + sin duplicados + sin pisar
hooks existentes).

## Qué es

Una memoria de decisiones por proyecto (`.memex/`, estilo Zettelkasten):
- Hooks globales capturan cada cambio relevante en `.memex/raw/changelog.jsonl`.
- Al cerrar sesión, el hook `Stop` pide destilar esos eventos en páginas wiki
  conectadas con `[[wikilinks]]` (`.memex/wiki/`).
- `SessionStart` / `UserPromptSubmit` cargan lecciones y decisiones relevantes.
- En proyectos sin `.memex/` los hooks no hacen nada.

Contenido del kit:
- `hooks/` → `memex_capture.py`, `memex_lib.py`, `memex_lint.py` + `tests/` (solo stdlib de Python)
- `commands/` → `/memex-init`, `/destilar`, `/registrar-decision`, `/consultar-historial`, `/lint-memex`
- `CLAUDE-snippet.md` → sección que se agrega a `~/.claude/CLAUDE.md`
- `install.py` / `uninstall.py`

## Pasos

1. **Requisitos.** Corre `python3 --version` (necesita 3.8+). Si no existe, díselo al
   usuario y para. En Windows usa `python` en lugar de `python3` en todos los pasos.

2. **Revisa antes de tocar.** Lee `install.py` y los archivos de `hooks/` y `commands/`
   para que sepas qué vas a instalar. Si `~/.claude/settings.json` existe, muéstrale al
   usuario qué hooks tiene ya (solo la clave `hooks`) para confirmar que se conservan.

3. **Simulación.** `python3 install.py --dry-run` y muestra la salida.

4. **Instalación.** `python3 install.py`. Debe terminar con `OK: memex instalado.` y los
   tests en `OK`. Si los tests fallan, muestra el error y no sigas al paso 5.

5. **Verificación de la fusión.** Lee `~/.claude/settings.json` y confirma:
   - es JSON válido,
   - hay 7 entradas con `memex_capture.py` (PreToolUse 1, PostToolUse 3, Stop 1,
     SessionStart 1, UserPromptSubmit 1), cada una una sola vez,
   - los hooks que el usuario tenía antes siguen ahí.

6. **Prueba real de captura** (en una carpeta temporal, sin tocar proyectos del usuario):
   ```bash
   T=$(mktemp -d) && mkdir -p "$T/.memex/raw" && echo 'print(1)' > "$T/app.py"
   echo "{\"hook_event_name\":\"PostToolUse\",\"cwd\":\"$T\",\"session_id\":\"test\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$T/app.py\",\"content\":\"print(1)\"},\"tool_response\":{}}" \
     | python3 ~/.claude/hooks/memex_capture.py
   cat "$T/.memex/raw/changelog.jsonl"; rm -rf "$T"
   ```
   Debe aparecer una línea JSON con el evento. Si `changelog.jsonl` no existe, reporta el fallo.

7. **Cierre.** Dile al usuario:
   - que **reinicie Claude Code** (los hooks se cargan al arrancar),
   - que en cada proyecto donde lo quiera corra **`/memex-init`** una vez,
   - los comandos disponibles: `/registrar-decision <desc>`, `/consultar-historial <tema>`,
     `/destilar`, `/lint-memex`,
   - que puede apagarlo temporalmente con la variable `MEMEX_HOOK_DISABLE=1`,
   - y que `python3 uninstall.py` lo quita todo (no borra los `.memex/` de sus proyectos).
   - Los backups quedan como `~/.claude/settings.json.bak-<fecha>` y `CLAUDE.md.bak-<fecha>`.

## Notas

- Correr `install.py` otra vez es seguro: actualiza archivos y no duplica hooks.
- El capturador da peso extra a comandos de n8n y `mcp__postgres` (el autor
  original los usa). Si el usuario no usa eso, simplemente no se activa; no hay que cambiar nada.
- Si el usuario ya tiene comandos con los mismos nombres en `~/.claude/commands/`, el
  instalador los respalda (`.bak-<fecha>`) antes de reemplazarlos. Avísale si pasó.
