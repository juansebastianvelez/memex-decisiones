#!/usr/bin/env python3
"""
memex_capture.py v2 — Hook global del "Memex de Decisiones por Proyecto".

Un solo script para varios hookpoints, diferenciados por `hook_event_name` (stdin):

  SessionStart     -> inyecta lo vigente: página de estado, lecciones abiertas, salud del memex.
  UserPromptSubmit -> recupera lecciones/decisiones relevantes al mensaje (por `trigger`/tags/título).
  PreToolUse       -> guardarraíles de `.memex/guardrails.json` (avisar o bloquear).
  PostToolUse      -> captura cruda a raw/changelog.jsonl (con intención y señal) y valida
                      al instante las páginas de la wiki que se acaban de escribir.
  Stop             -> (1) puerta de integridad de la wiki, (2) pide destilar si hay señal suficiente.

Configuración por proyecto: `.memex/config.json`. Apagar todo: MEMEX_HOOK_DISABLE=1.
Invariantes: nunca rompe la sesión (todo en try/except, sale 0); no-op si no hay .memex/;
raw/ es solo append; la wiki solo se toca con --fix mecánico y solo si `autofix` está activo.
"""

import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memex_lib as L  # noqa: E402
import memex_lint as LINT  # noqa: E402

# --- Filtros anti-ruido --------------------------------------------------------

IGNORE_PATH_SEGMENTS = (
    "/.memex/", "/node_modules/", "/.venv/", "/venv/", "/dist/", "/build/", "/.git/",
    "/.next/", "/__pycache__/",
    "/.claude/plans/", "/.claude/projects/", "/.claude/hooks/", "/.cache/", "/tmp/claude-",
)
IGNORE_PATH_SUFFIXES = (".lock", ".log", ".DS_Store", ".pyc", ".tmp")

# Bash que cambia estado (en minúsculas). El resto (ls/cat/grep...) no se registra.
BASH_STATE_MARKERS = (
    "git commit", "git merge", "git rebase", "git checkout", "git reset",
    "git cherry-pick", "git revert", "git tag", "git push",
    "migrate", "migration", "npm install", "npm i ", "pnpm install", "yarn add", "pip install",
    "docker build", "docker compose", "docker-compose", "docker run",
    "launchctl", "systemctl", "deploy", "terraform apply", "alembic",
)
# Escrituras HTTP a una API (n8n...) y SQL de cambio: alta señal.
HTTP_WRITE_RE = re.compile(r"(-x\s*(put|post|patch|delete)|requests\.(put|post|patch|delete)|httpx\.(put|post|patch|delete))")
HTTP_TARGET_RE = re.compile(r"(n8n|/api/v1/|workflows|/mcp)")
SQL_WRITE_RE = re.compile(r"\b(?:insert\s+into|update\s+\w+\s+set|delete\s+from|alter\s+table|create\s+(?:table|index|trigger|function)|drop\s+\w+|truncate\b)")
PROMOTE_RE = re.compile(r"\b(push_wf\w*|promote_\w+|mirror_apply\w*|apply_\w+\.py)\b")
HIGH_MARKERS = ("git commit", "git push", "deploy", "docker", "migrat", "terraform", "systemctl")

SELF_REFERENCE = (".memex/", ".memex ", "memex_", ".claude/hooks", "memex_capture")
DEDUP_SECONDS = 60
MAX_EVENTS_IN_REASON = 30


# --- helpers de changelog ------------------------------------------------------

def changelog_path(memex):
    return os.path.join(memex, "raw", "changelog.jsonl")


def read_events(memex):
    out = []
    try:
        with open(changelog_path(memex), "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        out.append({"summary": line.strip()[:120]})
    except OSError:
        pass
    return out


def read_watermark(memex):
    try:
        with open(os.path.join(memex, "raw", ".distilled_until"), "r", encoding="utf-8") as fh:
            return int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        return 0


def git_branch(cwd):
    try:
        with open(os.path.join(cwd, ".git", "HEAD"), "r", encoding="utf-8") as fh:
            ref = fh.read().strip()
        return ref.rsplit("/", 1)[-1] if ref.startswith("ref:") else ref[:8]
    except OSError:
        return None


def last_event(memex, nbytes=4096):
    try:
        path = changelog_path(memex)
        with open(path, "rb") as fh:
            fh.seek(max(0, os.path.getsize(path) - nbytes))
            lines = [ln for ln in fh.read().decode("utf-8", "ignore").splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        return None


def _epoch(iso):
    try:
        import datetime
        return datetime.datetime.fromisoformat(iso).timestamp()
    except Exception:
        return 0


def append_event(memex, event):
    prev = last_event(memex)
    if prev and prev.get("tool") == event.get("tool") and prev.get("summary") == event.get("summary") \
            and abs(_epoch(event["ts"]) - _epoch(prev.get("ts", ""))) < DEDUP_SECONDS:
        return
    with open(changelog_path(memex), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))


# --- PostToolUse: captura ------------------------------------------------------

def classify_bash(cmd):
    """(registrar, alta_señal) para un comando Bash."""
    low = cmd.lower()
    high = False
    if any(s in low for s in SELF_REFERENCE):  # comandos que editan el memex o el propio hook
        return False, False
    if HTTP_WRITE_RE.search(low) and HTTP_TARGET_RE.search(low):
        return True, True
    if SQL_WRITE_RE.search(low) and ("psql" in low or "postgres" in low or "mcp" in low):
        return True, True
    if PROMOTE_RE.search(low):
        return True, True
    if any(m in low for m in BASH_STATE_MARKERS):
        high = any(m in low for m in HIGH_MARKERS)
        return True, high
    return False, False


def handle_post_tool_use(data, memex, cfg):
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    proj = L.project_root(memex)
    sid = data.get("session_id", "")
    path = L.target_path(data)

    # 1) Validación inmediata de páginas de la wiki recién escritas
    if tool in ("Edit", "Write", "MultiEdit") and path:
        norm = "/" + path.strip("/")
        if "/.memex/wiki/" in norm and norm.endswith(".md"):
            probs = LINT.validate_page(memex, path)
            if probs:
                emit({"hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": "[Memex] La página que acabas de escribir no cumple las reglas del memex:\n"
                                         + "\n".join("- " + p for p in probs[:8])
                                         + "\nCorrígela ahora (ver .memex/CLAUDE.md)."}})
            return

    # 2) Captura cruda
    high = False
    state_touch = False
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        norm = "/" + path.strip("/")
        if any(seg in norm for seg in IGNORE_PATH_SEGMENTS) or path.endswith(IGNORE_PATH_SUFFIXES):
            return
        if not os.path.abspath(path).startswith(proj + os.sep):
            return
        summary = f"{tool} {os.path.basename(path)}"
        rel = os.path.relpath(path, proj)
        watch = [w for w in cfg.get("state_watch", []) if w and w in rel]
        state_touch = bool(watch)
        high = state_touch
        extra = {"file": rel}
    elif tool == "Bash":
        cmd = (ti.get("command") or "").strip()
        record, high = classify_bash(cmd)
        if not record:
            return
        first = cmd.splitlines()[0] if cmd else ""
        summary = f"bash: {first[:120]}"
        extra = {"command": first[:200]}
        state_touch = high and any(w and w.lower() in cmd.lower() for w in cfg.get("state_watch", []))
    elif tool.startswith("mcp__postgres"):
        sql = (ti.get("sql") or ti.get("query") or "").strip()
        if not SQL_WRITE_RE.search(sql.lower()):
            return
        summary = f"sql: {sql.splitlines()[0][:120]}"
        extra = {"command": sql.splitlines()[0][:200]}
        high = True
    else:
        return

    session = L.load_session(sid)
    event = {
        "ts": L.now_iso(), "event": "PostToolUse", "tool": tool, "summary": summary,
        "cwd": data.get("cwd") or os.getcwd(), "session_id": sid,
    }
    event.update(extra)
    if session.get("intent"):
        event["intent"] = session["intent"]
    if high:
        event["high"] = True
    if state_touch:
        event["state_touch"] = True
    br = git_branch(proj)
    if br:
        event["git_branch"] = br
    append_event(memex, event)


# --- UserPromptSubmit: recuperación -------------------------------------------

def handle_user_prompt(data, memex, cfg):
    prompt = (data.get("prompt") or "").strip()
    sid = data.get("session_id", "")
    session = L.load_session(sid)
    session["intent"] = re.sub(r"\s+", " ", prompt)[:160]
    if not cfg.get("retrieval") or len(prompt) < 12:
        L.save_session(sid, session)
        return
    pages = L.load_pages(memex)
    shown = set(session.get("shown", []))
    hits = L.retrieve(pages, prompt, k=int(cfg["retrieval_k"]),
                      min_score=float(cfg["retrieval_min_score"]), exclude=shown)
    if hits:
        session["shown"] = sorted(shown | {s for _, s, _ in hits})
        lines = [L.describe(pages[s]) for _, s, _ in hits]
        emit({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "[Memex] Páginas del memex que podrían aplicar a este mensaje "
                                 "(léelas antes de actuar si son relevantes):\n" + "\n".join(lines)}})
    L.save_session(sid, session)


# --- PreToolUse: guardarraíles ------------------------------------------------

def handle_pre_tool_use(data, memex, cfg):
    if not cfg.get("guardrails"):
        return
    rules = L.load_guardrails(memex)
    if not rules:
        return
    hits = L.check_guardrails(rules, data)
    if not hits:
        return
    sid = data.get("session_id", "")
    session = L.load_session(sid)
    warned = set(session.get("warned", []))
    blocks = [r for r in hits if r.get("action") == "block"]
    if blocks:
        r = blocks[0]
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": f"[Memex · guardarraíl {r.get('id','?')}] {r.get('message','')}"
                                        + (f" (lección: .memex/wiki/lessons/{r['ref']}.md)" if r.get("ref") else "")}})
        return
    new = [r for r in hits if r.get("id") not in warned]
    if not new:
        return
    session["warned"] = sorted(warned | {r.get("id", "?") for r in new})
    L.save_session(sid, session)
    msg = "\n".join(f"- {r.get('message','')}" + (f" (ver .memex/wiki/lessons/{r['ref']}.md)" if r.get("ref") else "")
                    for r in new)
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                 "additionalContext": "[Memex · aviso antes de actuar]\n" + msg}})


# --- Stop: integridad + destilación -------------------------------------------

def _wiki_mtime(memex):
    latest = 0.0
    for root, _, files in os.walk(os.path.join(memex, "wiki")):
        for f in files:
            if f.endswith(".md"):
                latest = max(latest, os.path.getmtime(os.path.join(root, f)))
    try:
        latest = max(latest, os.path.getmtime(os.path.join(memex, "index.md")))
    except OSError:
        pass
    return latest


def handle_stop(data, memex, cfg):
    if data.get("stop_hook_active"):
        return
    sid = data.get("session_id", "")
    session = L.load_session(sid)
    notes = []

    # (1) puerta de integridad: solo si la wiki cambió desde la última vez
    if cfg.get("lint_gate") or cfg.get("autofix"):
        mt = _wiki_mtime(memex)
        if mt > session.get("lint_mtime", 0):
            res = LINT.run(memex, fix=bool(cfg.get("autofix")), cfg=cfg)
            session["lint_mtime"] = _wiki_mtime(memex)
            L.save_session(sid, session)
            if cfg.get("lint_gate") and res["critical"]:
                emit({"decision": "block", "reason":
                      "[Memex automático] La wiki quedó con problemas críticos. Corrígelos antes de terminar "
                      "(sin preguntar):\n" + "\n".join("- " + x for x in res["critical"][:15])
                      + "\nPuedes verificar con: python3 ~/.claude/hooks/memex_lint.py"})
                return
            if res.get("fixed"):
                notes.append("Arreglos mecánicos aplicados por el hook: " + "; ".join(res["fixed"][:5]))

    # (2) destilación con umbral
    total = len(read_events(memex))
    distilled = read_watermark(memex)
    pending = total - distilled
    if pending <= 0:
        return
    events = read_events(memex)[distilled:]
    high = any(e.get("high") for e in events)
    if pending < int(cfg.get("distill_min_events", 1)) and not high:
        return  # se mostrará al próximo SessionStart

    groups, order = {}, []
    for e in events:
        key = e.get("intent") or "(sin intención registrada)"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    lines = []
    for key in order[:12]:
        evs = groups[key]
        files = sorted({os.path.basename(e.get("file") or e.get("command") or e.get("summary", "")) for e in evs})
        mark = " ⚑" if any(e.get("high") for e in evs) else ""
        lines.append(f"- «{key[:100]}»{mark}: {len(evs)} evento(s) — " + ", ".join(files[:5]) + ("…" if len(files) > 5 else ""))
    state_touch = any(e.get("state_touch") for e in events)
    proj = L.project_root(memex)
    state_page = cfg.get("state_page")

    steps = [
        "1. Lee las líneas pendientes del changelog (y `.memex/index.md` solo si vas a crear/mover páginas).",
        "2. Si todos los eventos son rutinarios (ediciones menores, sin decisión ni aprendizaje), NO crees páginas "
        "ni entrada de log: solo avanza el watermark (paso 5).",
        "3. Si hubo decisiones, errores corregidos o flujos nuevos, crea o actualiza las páginas en "
        "`.memex/wiki/{decisions,lessons,flows}/` con frontmatter completo (type, alcance, status, last_updated, "
        "sources, tags, related; lecciones también `trigger`) y al menos un wikilink saliente + backlink recíproco.",
    ]
    if state_touch and state_page:
        steps.append(f"4. Se tocó algo que describe la página de estado: revisa que `.memex/{state_page}` siga vigente "
                     "y actualízala si cambió lo que corre en producción.")
    else:
        steps.append("4. Si añadiste páginas, actualiza `.memex/index.md` y agrega UNA línea a `.memex/log.md` "
                     "(`## [YYYY-MM-DD] destilar | N eventos -> M páginas`).")
    steps.append(f"5. Escribe {total} en `.memex/raw/.distilled_until`.")
    steps.append(f"6. Si el proyecto versiona la wiki, ofrece commitear (carpeta {proj}).")
    reason = (
        f"[Memex automático] {pending} evento(s) crudo(s) sin destilar (líneas {distilled + 1}–{total}), "
        f"agrupados por lo que se pedía:\n" + "\n".join(lines) + "\n\nEjecuta el ciclo de ingest SIN preguntar:\n"
        + "\n".join(steps) + ("\n" + "\n".join(notes) if notes else "") + "\nCuando termines, ya puedes parar."
    )
    emit({"decision": "block", "reason": reason})


# --- SessionStart --------------------------------------------------------------

def looks_like_dev_project(cwd):
    if not os.path.isdir(os.path.join(cwd, ".git")):
        return False
    manifests = ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml",
                 "go.mod", "pom.xml", "Gemfile", "composer.json", "Package.swift")
    return any(os.path.exists(os.path.join(cwd, m)) for m in manifests)


def _state_excerpt(memex, state_page, limit=7000):
    try:
        with open(os.path.join(memex, state_page), "r", encoding="utf-8") as fh:
            _, body = L.split_fm(fh.read())
    except OSError:
        return ""
    body = re.sub(r"^> .*\n", "", body, flags=re.M).strip()
    if len(body) > limit:
        body = body[:limit].rsplit("\n", 1)[0] + "\n…(sigue en la página)"
    return body


_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".memex", "_archive"}


def _newest_watched(root, fragments, max_files=20000):
    """(mtime, relpath) del archivo más reciente cuya ruta contiene algún fragmento de state_watch."""
    best, seen = (0.0, ""), 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            seen += 1
            if seen > max_files:
                return best
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            if any(fr in rel for fr in fragments):
                try:
                    mt = os.path.getmtime(os.path.join(dirpath, f))
                except OSError:
                    continue
                if mt > best[0]:
                    best = (mt, rel)
    return best


def _state_staleness(memex, cfg):
    state, watch = cfg.get("state_page"), cfg.get("state_watch") or []
    if not state or not watch:
        return ""
    try:
        state_mt = os.path.getmtime(os.path.join(memex, state))
    except OSError:
        return ""
    mt, rel = _newest_watched(L.project_root(memex), watch)
    if mt - state_mt > 3600:
        days = (mt - state_mt) / 86400
        return (f"⚠ La página de estado puede estar VIEJA: `{rel}` cambió {days:.1f} día(s) después de ella. "
                "Verifica contra el sistema vivo antes de afirmar qué corre hoy.")
    return ""


def _compact_index(pages, limit_chars=3500):
    """Decisiones vigentes (id + título) y lecciones vigentes (título), para ubicarse sin abrir index.md."""
    dec = sorted((p for p in pages.values() if p["type"] == "decision"
                  and p["status"] not in ("rechazada", "reemplazada", "supersedida")),
                 key=lambda p: p["slug"])
    les = sorted((p for p in pages.values() if p["type"] == "lesson" and p["status"] not in ("resuelta",)),
                 key=lambda p: p["slug"])
    lines = []
    if dec:
        lines.append(f"Decisiones vigentes ({len(dec)}):")
        for p in dec:
            num = (re.match(r"\d+", p["slug"]) or [""])[0]
            title = re.sub(r"^(ADR\s*)?\d+\s*[—-]\s*", "", p["title"])
            lines.append(f"- {num} {title} → {p['path']}")
    out, used = [], 0
    for ln in lines:
        used += len(ln) + 1
        if used > limit_chars:
            out.append("…(más en .memex/index.md)")
            break
        out.append(ln)
    if les:
        out.append(f"Lecciones no resueltas ({len(les)}): usa /consultar-historial <tema>; el hook sugiere las relevantes por mensaje.")
    return "\n".join(out)


def handle_session_start(data):
    cwd = data.get("cwd") or os.getcwd()
    memex = L.find_memex_root(cwd)
    if not memex:
        if looks_like_dev_project(cwd):
            emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
                  "Este proyecto de desarrollo no tiene memex de decisiones. "
                  "Para activar el registro automático de cambios y decisiones, ejecuta `/memex-init` una vez."}})
        return
    cfg = L.load_config(memex)
    if not cfg.get("enabled"):
        return
    L.prune_sessions()
    pages = L.load_pages(memex)
    now = datetime.datetime.now().astimezone()
    parts = ["# Memex de este proyecto (cargado automáticamente)",
             f"Hoy: {now:%Y-%m-%d} (hora local {now:%z}; UTC {now.astimezone(datetime.timezone.utc):%Y-%m-%d}). "
             "Las páginas del memex pueden estar fechadas en UTC, así que una fecha de «mañana» puede ser de hoy."]
    state = cfg.get("state_page")
    excerpt = _state_excerpt(memex, state, int(cfg.get("state_excerpt_chars", 7000))) if state else ""
    if excerpt:
        parts.append(f"## Estado vigente (de `.memex/{state}`)\n{excerpt}")
    else:
        try:
            with open(os.path.join(memex, "log.md"), "r", encoding="utf-8") as fh:
                heads = [ln.strip() for ln in fh if ln.startswith("## [")][-6:]
            if heads:
                parts.append("## Últimas entradas del log\n" + "\n".join(heads))
        except OSError:
            pass
    warn = _state_staleness(memex, cfg)
    if warn:
        parts.insert(2, warn)
    open_status = set(cfg.get("session_open_status", []))
    opened = [p for p in pages.values() if p["type"] == "lesson" and p["status"] in open_status]
    if opened:
        parts.append("## Lecciones abiertas (pendientes de resolver o medir)\n" + "\n".join(
            f"- {p['title']} [{p['status']}] → .memex/{p['path']}" for p in opened[:8]))
    else:
        lessons = sorted((p for p in pages.values() if p["type"] == "lesson"), key=lambda p: p["slug"])
        if lessons:
            parts.append(f"## Lecciones ({len(lessons)}) — usa /consultar-historial <tema>; "
                         "el hook también sugiere las relevantes a cada mensaje.")
    if cfg.get("session_index", True):
        idx = _compact_index(pages)
        if idx:
            parts.append("## Mapa rápido\n" + idx)
    try:
        res = LINT.run(memex, cfg=cfg)
        problems = len(res["critical"]) + len(res["important"])
        health = f"{res['pages']} páginas; salud: " + ("sin problemas" if not problems else
                 f"{len(res['critical'])} críticos y {len(res['important'])} importantes "
                 "(corre `python3 ~/.claude/hooks/memex_lint.py`)")
        pend = [x for x in res["info"] if "sin destilar" in x]
        stale = [x for x in res["info"] if "cambió" in x]
        if pend:
            health += "; " + pend[0] + " (se destilarán con /destilar o al acumular señal)"
        if stale:
            health += f"; {len(stale)} página(s) posiblemente desactualizadas"
        parts.append("## Salud del memex\n" + health)
    except Exception as exc:
        L.log_error("session_start_lint", exc)
    parts.append("Mapa completo del memex: `.memex/index.md` (léelo si vas a tocar un área nueva).")
    parts.append("Antes de decisiones importantes: `/consultar-historial <tema>`. "
                 "Las páginas relevantes a cada mensaje se sugieren solas; el ingest ocurre al cerrar turnos con señal.")
    text = "\n\n".join(parts)
    emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text[:int(cfg.get("session_max_chars", 10000))]}})


# --- Entrypoint ---------------------------------------------------------------

def main():
    if os.environ.get("MEMEX_HOOK_DISABLE"):
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    event = data.get("hook_event_name", "")
    try:
        if event == "SessionStart":
            handle_session_start(data)
        else:
            memex = L.memex_for(data)
            if memex is not None:
                cfg = L.load_config(memex)
                if cfg.get("enabled"):
                    if event == "PostToolUse":
                        handle_post_tool_use(data, memex, cfg)
                    elif event == "UserPromptSubmit":
                        handle_user_prompt(data, memex, cfg)
                    elif event == "PreToolUse":
                        handle_pre_tool_use(data, memex, cfg)
                    elif event == "Stop":
                        handle_stop(data, memex, cfg)
    except Exception as exc:  # un hook nunca debe romper la sesión
        L.log_error(event or "main", exc)
    sys.exit(0)


if __name__ == "__main__":
    main()
