#!/usr/bin/env python3
"""Instalador idempotente del memex-kit para Claude Code.

Uso:  python3 install.py            instala / actualiza
      python3 install.py --dry-run  muestra lo que haría sin tocar nada
"""
import json, os, shutil, subprocess, sys, time

KIT = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE, "hooks")
CMDS_DIR = os.path.join(CLAUDE, "commands")
SETTINGS = os.path.join(CLAUDE, "settings.json")
CLAUDE_MD = os.path.join(CLAUDE, "CLAUDE.md")
START, END = "<!-- memex-kit:start -->", "<!-- memex-kit:end -->"
DRY = "--dry-run" in sys.argv
STAMP = time.strftime("%Y%m%d-%H%M%S")

PY = "python3" if os.name != "nt" else f'"{sys.executable}"'
SCRIPT = os.path.join(HOOKS_DIR, "memex_capture.py")
CMD = f'{PY} "{SCRIPT}"'

# (evento, matcher o None, timeout)
HOOKS = [
    ("PreToolUse", "Bash|Write|Edit|MultiEdit", 10),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit", 10),
    ("PostToolUse", "Bash", 10),
    ("PostToolUse", "mcp__postgres__query", 10),
    ("Stop", None, 15),
    ("SessionStart", None, 10),
    ("UserPromptSubmit", None, 10),
]


def log(msg):
    print(("[dry-run] " if DRY else "") + msg)


def backup(path):
    if os.path.exists(path):
        dst = f"{path}.bak-{STAMP}"
        if not DRY:
            shutil.copy2(path, dst)
        log(f"backup: {dst}")


def copy_tree(src, dst):
    for root, _, files in os.walk(src):
        rel = os.path.relpath(root, src)
        if "__pycache__" in rel:
            continue
        target_dir = os.path.normpath(os.path.join(dst, rel))
        if not DRY:
            os.makedirs(target_dir, exist_ok=True)
        for f in files:
            if f.endswith(".pyc"):
                continue
            s, d = os.path.join(root, f), os.path.join(target_dir, f)
            if os.path.exists(d):
                with open(s, "rb") as a, open(d, "rb") as b:
                    if a.read() == b.read():
                        continue
                backup(d)
            if not DRY:
                shutil.copy2(s, d)
            log(f"copiado: {d}")


def is_memex(h):
    return "memex_capture.py" in str(h.get("command", ""))


def merge_settings():
    data = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                sys.exit(f"ERROR: {SETTINGS} no es JSON válido ({e}). Arréglalo y vuelve a correr.")
    hooks = data.setdefault("hooks", {})

    # 1) quitar cualquier entrada previa del memex (idempotencia / actualización)
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            g = dict(g)
            g["hooks"] = [h for h in g.get("hooks", []) if not is_memex(h)]
            if g["hooks"]:
                groups.append(g)
        hooks[event] = groups

    # 2) agregar las entradas actuales
    for event, matcher, timeout in HOOKS:
        group = {"hooks": [{"type": "command", "command": CMD, "timeout": timeout}]}
        if matcher:
            group = {"matcher": matcher, **group}
        hooks.setdefault(event, []).append(group)

    for event in [e for e, v in hooks.items() if not v]:
        del hooks[event]

    backup(SETTINGS)
    if not DRY:
        os.makedirs(CLAUDE, exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    log(f"hooks registrados en {SETTINGS} ({len(HOOKS)} entradas) -> {CMD}")


def merge_claude_md():
    with open(os.path.join(KIT, "CLAUDE-snippet.md"), encoding="utf-8") as f:
        block = f"{START}\n{f.read().strip()}\n{END}\n"
    text = ""
    if os.path.exists(CLAUDE_MD):
        with open(CLAUDE_MD, encoding="utf-8") as f:
            text = f.read()
    if START in text and END in text:
        a, b = text.index(START), text.index(END) + len(END)
        new = text[:a] + block.rstrip("\n") + text[b:]
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    if new == text:
        return
    backup(CLAUDE_MD)
    if not DRY:
        with open(CLAUDE_MD, "w", encoding="utf-8") as f:
            f.write(new)
    log(f"sección Memex escrita en {CLAUDE_MD}")


def run_tests():
    if DRY:
        return True
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                        os.path.join(HOOKS_DIR, "tests"), "-q"],
                       capture_output=True, text=True)
    print(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "(sin salida de tests)")
    if r.returncode != 0:
        print(r.stderr)
    return r.returncode == 0


def main():
    if sys.version_info < (3, 8):
        sys.exit("ERROR: se necesita Python 3.8 o superior.")
    log(f"instalando memex-kit en {CLAUDE}")
    copy_tree(os.path.join(KIT, "hooks"), HOOKS_DIR)
    copy_tree(os.path.join(KIT, "commands"), CMDS_DIR)
    merge_settings()
    merge_claude_md()
    ok = run_tests()
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("Nota: PyYAML no está instalado (opcional). Para validación estricta del frontmatter:"
              " python3 -m pip install --user pyyaml")
    print("\nOK: memex instalado." if ok else "\nATENCIÓN: los tests fallaron (ver arriba).")
    print("Reinicia Claude Code para que cargue los hooks. Luego, en un proyecto: /memex-init")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
