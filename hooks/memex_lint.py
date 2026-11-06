#!/usr/bin/env python3
"""
memex_lint.py — chequeo determinista de la integridad de un .memex/ (y arreglo de lo mecánico).

Uso:
    python3 ~/.claude/hooks/memex_lint.py [ruta_del_proyecto_o_.memex] [--fix] [--json]

Críticos : enlaces rotos, sin frontmatter / YAML inválido, sin wikilink saliente, campos requeridos.
Importantes: huérfanas, `related` no recíproco o roto, lecciones sin `trigger`, índice desincronizado.
Info     : páginas posiblemente desactualizadas (una fuente cambió después de last_updated), crudo pendiente.
--fix    : solo lo mecánico y reversible: reciprocidad de `related` y páginas faltantes en el índice.
"""

import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memex_lib as L  # noqa: E402

INDEX_SECTION = "## Sin clasificar (añadidas automáticamente)"


def _read_index(memex):
    try:
        with open(os.path.join(memex, "index.md"), "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _stale(pages, memex, limit=10):
    root = L.project_root(memex)
    out = []
    path_re = re.compile(r"^([^\s(][^()]*?\.(?:py|json|md|js|ts|sql|sh|ya?ml|html))(?:[\s(#]|$)")
    for pg in pages.values():
        if not re.match(r"\d{4}-\d{2}-\d{2}", pg["last_updated"]):
            continue
        try:
            upd = datetime.date.fromisoformat(pg["last_updated"][:10])
        except ValueError:
            continue
        for s in pg["sources"]:
            m = path_re.match(s.strip())
            if not m:
                continue
            f = os.path.join(root, m.group(1).strip())
            if "raw/changelog" in f or not os.path.isfile(f):
                continue
            mt = datetime.date.fromtimestamp(os.path.getmtime(f))
            if (mt - upd).days > 2:
                out.append(((mt - upd).days, pg["slug"], m.group(1).strip()))
                break
    out.sort(reverse=True)
    return out[:limit]


def run(memex, fix=False, cfg=None):
    cfg = cfg or L.load_config(memex)
    pages = L.load_pages(memex)
    index = _read_index(memex)
    crit, imp, info, fixed = [], [], [], []

    inbound = {s: 0 for s in pages}
    for slug, pg in pages.items():
        if pg["fm_text"] is None:
            crit.append(f"{slug}: sin frontmatter")
            continue
        if pg["fm_error"]:
            crit.append(f"{slug}: {pg['fm_error']}")
        for f in cfg["required_fields"]:
            if f not in pg["fm"]:
                crit.append(f"{slug}: falta el campo `{f}`")
        if not pg["wikilinks"]:
            crit.append(f"{slug}: sin wikilink saliente en el cuerpo")
        for target in pg["wikilinks"]:
            if target in pages:
                if target != slug:
                    inbound[target] += 1
            else:
                crit.append(f"{slug}: enlace roto [[{target}]]")
        for target in pg["related"]:
            if target not in pages:
                imp.append(f"{slug}: `related` apunta a página inexistente «{target}»")
        if pg["type"] == "lesson" and not pg["trigger"]:
            imp.append(f"{slug}: lección sin `trigger`")

    for slug, n in inbound.items():
        if n == 0:
            imp.append(f"{slug}: huérfana (nadie la enlaza)")

    # reciprocidad de related
    missing_back = {}
    for a, pa in pages.items():
        for b in pa["related"]:
            if b in pages and a not in pages[b]["related"]:
                missing_back.setdefault(b, []).append(a)
    for b, srcs in missing_back.items():
        imp.append(f"{b}: `related` no incluye a {len(srcs)} página(s) que la citan ({', '.join(sorted(srcs)[:3])}…)")

    # índice
    not_in_index = [s for s, p in pages.items() if p["path"] not in index]
    for s in not_in_index:
        imp.append(f"{s}: no está en index.md")
    for ref in sorted(set(re.findall(r"\((wiki/[^)\s]+\.md)\)", index))):
        if not os.path.exists(os.path.join(memex, ref)):
            imp.append(f"index.md apunta a un archivo que no existe: {ref}")

    # info
    for days, slug, src in _stale(pages, memex):
        info.append(f"{slug}: fuente «{src}» cambió {days} día(s) después de su last_updated")
    changelog = os.path.join(memex, "raw", "changelog.jsonl")
    total = _count_lines(changelog)
    done = _watermark(memex)
    if total - done > 0:
        info.append(f"{total - done} evento(s) crudo(s) sin destilar ({done}/{total})")

    if fix:
        fixed = _apply_fixes(memex, pages, missing_back, not_in_index)
        if fixed:
            return run(memex, fix=False, cfg=cfg) | {"fixed": fixed}

    return {"critical": crit, "important": imp, "info": info, "fixed": fixed,
            "pages": len(pages)}


def _count_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return sum(1 for ln in fh if ln.strip())
    except OSError:
        return 0


def _watermark(memex):
    try:
        with open(os.path.join(memex, "raw", ".distilled_until"), "r", encoding="utf-8") as fh:
            return int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        return 0


def _apply_fixes(memex, pages, missing_back, not_in_index):
    fixed = []
    rel_re = re.compile(r"^related:[ \t]*\[(.*?)\][ \t]*$", re.M)
    for b, srcs in missing_back.items():
        pg = pages[b]
        try:
            with open(pg["abs"], "r", encoding="utf-8") as fh:
                text = fh.read()
            fm_text, _ = L.split_fm(text)
            m = rel_re.search(fm_text or "")
            if not m:
                continue  # related multilínea u omitido: no lo toco
            items = [x.strip() for x in m.group(1).split(",") if x.strip()]
            for s in sorted(srcs):
                items.append(s if re.fullmatch(r"[\w./+-]+", s) else json.dumps(s, ensure_ascii=False))
            new_fm = fm_text[: m.start()] + "related: [" + ", ".join(items) + "]" + fm_text[m.end():]
            new_text = text.replace(fm_text, new_fm, 1)
            _, err = L.parse_fm(L.split_fm(new_text)[0])
            if err:
                continue  # no escribo nada que invalide el YAML
            _atomic_write(pg["abs"], new_text)
            fixed.append(f"{b}: añadido related ← {', '.join(sorted(srcs))}")
        except Exception as exc:
            L.log_error("fix_related " + b, exc)
    if not_in_index:
        try:
            idx_path = os.path.join(memex, "index.md")
            idx = _read_index(memex)
            add = ""
            if INDEX_SECTION not in idx:
                add += f"\n{INDEX_SECTION}\n"
            for s in not_in_index:
                pg = pages[s]
                add += f"- [{pg['title']}]({pg['path']}) — {pg['type']}\n"
            _atomic_write(idx_path, idx.rstrip("\n") + "\n" + add)
            fixed.append(f"index.md: añadidas {len(not_in_index)} página(s) sin clasificar")
        except Exception as exc:
            L.log_error("fix_index", exc)
    return fixed


def validate_page(memex, path):
    """Validación inmediata de UNA página recién escrita. Devuelve lista de problemas."""
    pages = L.load_pages(memex)
    slug = L.slug_of(path)
    pg = pages.get(slug)
    if pg is None:
        return []
    cfg = L.load_config(memex)
    probs = []
    if pg["fm_text"] is None:
        return [f"{slug}: no tiene frontmatter (`---` al inicio y al cierre)."]
    if pg["fm_error"]:
        probs.append(f"{slug}: {pg['fm_error']} (entrecomilla los valores con `:` o comillas).")
    for f in cfg["required_fields"]:
        if f not in pg["fm"]:
            probs.append(f"{slug}: falta `{f}` en el frontmatter.")
    if not pg["wikilinks"]:
        probs.append(f"{slug}: necesita al menos un wikilink [[...]] saliente (regla dura 2).")
    for t in pg["wikilinks"]:
        if t not in pages:
            probs.append(f"{slug}: [[{t}]] no existe.")
    if pg["type"] == "lesson" and not pg["trigger"]:
        probs.append(f"{slug}: las lecciones llevan `trigger`.")
    return probs


def format_report(res, limit=12):
    out = []
    for title, key in (("🔴 Críticos", "critical"), ("🟡 Importantes", "important"), ("🔵 Info", "info")):
        items = res[key]
        out.append(f"{title} ({len(items)})")
        out += [f"  - {x}" for x in items[:limit]]
        if len(items) > limit:
            out.append(f"  … y {len(items) - limit} más")
    if res.get("fixed"):
        out.append(f"🛠 Arreglado ({len(res['fixed'])})")
        out += [f"  - {x}" for x in res["fixed"][:limit]]
    return "\n".join(out)


def main(argv):
    fix = "--fix" in argv
    as_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    start = args[0] if args else os.getcwd()
    memex = start if os.path.basename(os.path.abspath(start)) == ".memex" else L.find_memex_root(start)
    if not memex:
        print("No se encontró .memex/")
        return 2
    res = run(memex, fix=fix)
    print(json.dumps(res, ensure_ascii=False, indent=1) if as_json else format_report(res))
    return 1 if res["critical"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
