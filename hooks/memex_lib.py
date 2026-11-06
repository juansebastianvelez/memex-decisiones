"""
memex_lib.py — utilidades compartidas del hook del Memex (memex_capture.py) y del linter.

Principios:
  - Solo biblioteca estándar (+ yaml si está; hay fallback).
  - Nada aquí lanza hacia afuera: los hooks no deben romper la sesión.
  - Config por proyecto en `.memex/config.json` (todo opcional; ver DEFAULT_CONFIG).
"""

import datetime
import glob
import json
import math
import os
import re
import time
import unicodedata
from collections import Counter

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cache", "memex")
SESSIONS = os.path.join(CACHE, "sessions")

DEFAULT_CONFIG = {
    "enabled": True,
    "retrieval": True,           # UserPromptSubmit: inyecta páginas relevantes
    "retrieval_k": 3,
    "retrieval_min_score": 18.0,
    "guardrails": True,          # PreToolUse: reglas de .memex/guardrails.json
    "lint_gate": False,          # Stop: bloquea si la wiki quedó con problemas críticos
    "autofix": False,            # arregla solo lo mecánico (reciprocidad, índice)
    "distill_min_events": 1,     # eventos pendientes mínimos para pedir destilar (salvo alta señal)
    "state_page": None,          # ruta (desde .memex/) de la página «estado actual»
    "state_watch": [],           # fragmentos de ruta cuyo cambio puede dejar vieja la página de estado
    "required_fields": ["type", "last_updated", "sources", "tags", "related"],
    "session_open_status": ["abierta", "diferida"],
}


# --- errores y estado --------------------------------------------------------

def log_error(where, exc):
    try:
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, "errors.log")
        if os.path.exists(path) and os.path.getsize(path) > 200_000:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {where}: {type(exc).__name__}: {exc}\n")
    except Exception:
        pass


def now_iso():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _session_file(session_id):
    safe = re.sub(r"[^\w.-]", "_", session_id or "nosession")[:80]
    return os.path.join(SESSIONS, safe + ".json")


def load_session(session_id):
    try:
        with open(_session_file(session_id), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_session(session_id, state):
    try:
        os.makedirs(SESSIONS, exist_ok=True)
        state["ts"] = time.time()
        tmp = _session_file(session_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, _session_file(session_id))
    except Exception as exc:
        log_error("save_session", exc)


def prune_sessions(max_age_days=5):
    try:
        limit = time.time() - max_age_days * 86400
        for p in glob.glob(os.path.join(SESSIONS, "*.json")):
            if os.path.getmtime(p) < limit:
                os.remove(p)
    except Exception:
        pass


# --- localización y config ---------------------------------------------------

def find_memex_root(start):
    """Sube desde `start` buscando un dir con .memex/raw/. None si no hay."""
    if not start:
        return None
    cur = os.path.abspath(start)
    while True:
        candidate = os.path.join(cur, ".memex")
        if os.path.isdir(os.path.join(candidate, "raw")):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def target_path(data):
    ti = data.get("tool_input") or {}
    return ti.get("file_path") or ti.get("notebook_path") or ""


def memex_for(data):
    """El memex se elige por la RUTA del archivo tocado; si no hay, por el cwd."""
    path = target_path(data)
    if path and os.path.isabs(path):
        found = find_memex_root(os.path.dirname(path))
        if found:
            return found
    return find_memex_root(data.get("cwd") or os.getcwd())


def load_config(memex):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(os.path.join(memex, "config.json"), "r", encoding="utf-8") as fh:
            user = json.load(fh)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    except FileNotFoundError:
        pass
    except Exception as exc:
        log_error("load_config", exc)
    return cfg


def project_root(memex):
    return os.path.dirname(memex)


# --- texto -------------------------------------------------------------------

def fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


STOP = set(
    """
    que los las del con una uno unos unas por para como pero sus este esta esto estos estas ese esa eso
    esos esas aqui alli muy mas menos sin sobre entre desde hasta cuando donde quien cual cuales todo
    toda todos todas tambien tiene tienen tener hacer hace hacen hecho vamos quiero quieres puedes puede
    podemos favor gracias hola bien ahora ver dame dime necesito necesitamos seria sera son era eran
    fue ser estar estoy estamos esta estan hay han has haber otro otra otros otras cada tras ante bajo
    segun solo ademas aun asi tal tan tanto mismo misma nos les mis tus mio mia nada algo algun alguna
    the and for with this that from have not are you your can will
    """.split()
)


def tokens(s):
    s = fold(s)
    s = re.sub(r"(?<=[a-z])-(?=\d)", "", s)  # wf-01 -> wf01
    return [stem(t) for t in re.findall(r"[a-z0-9]+", s) if len(t) >= 3 and t not in STOP]


def stem(t):
    """Raíz barata: prefijo de 5 letras (diluyendo/diluye -> diluy). Deja intactos los tokens cortos o con dígitos."""
    return t if len(t) <= 5 or any(c.isdigit() for c in t) else t[:5]


# --- frontmatter y páginas ---------------------------------------------------

def split_fm(text):
    if not text.startswith("---"):
        return None, text
    m = re.match(r"---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)(.*)", text, re.S)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def parse_fm(fm_text):
    """Devuelve (dict, error|None)."""
    if fm_text is None:
        return {}, "sin frontmatter"
    if yaml is not None:
        try:
            d = yaml.safe_load(fm_text)
            if not isinstance(d, dict):
                return {}, "frontmatter no es un mapa"
            return d, None
        except Exception as exc:
            return _loose_fm(fm_text), "YAML inválido: " + str(exc).splitlines()[0][:80]
    return _loose_fm(fm_text), None


def _loose_fm(fm_text):
    d = {}
    for m in re.finditer(r"^([A-Za-z_][\w-]*):[ \t]*(.*)$", fm_text, re.M):
        k, v = m.group(1), m.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            d[k] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
        else:
            d[k] = v.strip("\"'")
    return d


def as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def slug_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def load_pages(memex):
    pages = {}
    for p in sorted(glob.glob(os.path.join(memex, "wiki", "**", "*.md"), recursive=True)):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        fm_text, body = split_fm(text)
        d, err = parse_fm(fm_text)
        h1 = re.search(r"^# (.+)$", body, re.M)
        slug = slug_of(p)
        pages[slug] = {
            "slug": slug,
            "abs": p,
            "path": os.path.relpath(p, memex),
            "fm_text": fm_text,
            "fm": d,
            "fm_error": err,
            "body": body,
            "type": str(d.get("type") or ""),
            "status": str(d.get("status") or ""),
            "alcance": str(d.get("alcance") or ""),
            "trigger": str(d.get("trigger") or ""),
            "tags": as_list(d.get("tags")),
            "related": [os.path.basename(x.strip()) for x in as_list(d.get("related"))],
            "sources": as_list(d.get("sources")),
            "last_updated": str(d.get("last_updated") or ""),
            "title": h1.group(1).strip() if h1 else slug,
            "wikilinks": sorted({os.path.basename(x.strip()) for x in re.findall(r"\[\[([^\]|#]+)", body)}),
        }
    return pages


# --- recuperación de páginas relevantes --------------------------------------

STATUS_FACTOR = {"no-aplica": 0.25, "historica": 0.5, "supersedida": 0.3}
TYPE_FACTOR = {"lesson": 1.0, "decision": 1.0, "flow": 0.6}
FIELD_W = {"trigger": 3.0, "title": 2.0, "tags": 1.5, "slug": 1.0}


def retrieve(pages, prompt, k=3, min_score=5.0, exclude=()):
    q = set(tokens(prompt))
    if len(q) < 2:
        return []
    docs = {}
    for slug, pg in pages.items():
        if pg["type"] not in TYPE_FACTOR:
            continue
        docs[slug] = {
            "trigger": set(tokens(pg["trigger"])),
            "title": set(tokens(pg["title"])),
            "tags": set(tokens(" ".join(pg["tags"]))),
            "slug": set(tokens(slug.replace("-", " "))),
        }
    n = max(len(docs), 1)
    df = Counter()
    for d in docs.values():
        for t in set().union(*d.values()):
            df[t] += 1
    scored = []
    for slug, d in docs.items():
        if slug in exclude:
            continue
        matched, score = set(), 0.0
        for field, w in FIELD_W.items():
            for t in q & d[field]:
                score += w * math.log((n + 1) / (df[t] + 0.5))
                matched.add(t)
        if len(matched) < 2:
            continue
        pg = pages[slug]
        score *= STATUS_FACTOR.get(pg["status"], 1.0) * TYPE_FACTOR.get(pg["type"], 1.0)
        if score >= min_score:
            scored.append((score, slug, sorted(matched)))
    scored.sort(reverse=True)
    if scored:  # corte relativo: lo que puntúa mucho menos que lo mejor es ruido
        scored = [x for x in scored if x[0] >= 0.4 * scored[0][0]]
    return scored[:k]


def describe(pg, max_trigger=230):
    bits = [x for x in (pg["type"], pg["status"], pg["alcance"]) if x]
    trig = pg["trigger"].strip()
    if len(trig) > max_trigger:
        trig = trig[: max_trigger - 1].rstrip() + "…"
    line = f"- {pg['title']} ({' · '.join(bits)}) → .memex/{pg['path']}"
    if trig:
        line += f"\n  cuándo aplica: {trig}"
    return line


# --- guardarraíles (PreToolUse) ----------------------------------------------

def load_guardrails(memex):
    try:
        with open(os.path.join(memex, "guardrails.json"), "r", encoding="utf-8") as fh:
            rules = json.load(fh)
        return [r for r in rules if isinstance(r, dict) and not r.get("_comment")]
    except FileNotFoundError:
        return []
    except Exception as exc:
        log_error("load_guardrails", exc)
        return []


def tool_text(data):
    """Texto que la herramienta va a escribir/ejecutar."""
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        return ti.get("command") or ""
    if tool == "Write":
        return ti.get("content") or ""
    if tool == "Edit":
        return ti.get("new_string") or ""
    if tool == "MultiEdit":
        return "\n".join((e or {}).get("new_string") or "" for e in ti.get("edits") or [])
    return ""


def _alt_matches(alt, text):
    parts = [alt] if isinstance(alt, str) else list(alt)
    return all(re.search(p, text, re.I | re.S) for p in parts)


def check_guardrails(rules, data):
    """Devuelve la lista de reglas que aplican a esta llamada."""
    tool = data.get("tool_name", "")
    text = tool_text(data)
    path = target_path(data)
    hits = []
    for r in rules:
        if tool not in r.get("tools", []):
            continue
        if r.get("path_regex") and not re.search(r["path_regex"], path or ""):
            continue
        unless = r.get("unless")
        subject = text if tool == "Bash" else path
        if unless and re.search(unless, subject or "", re.I):
            continue
        if any(_alt_matches(a, text) for a in r.get("patterns", [])):
            hits.append(r)
    return hits
