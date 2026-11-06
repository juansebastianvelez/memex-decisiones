#!/usr/bin/env python3
"""Desinstala el memex-kit: quita los hooks de settings.json, la sección del CLAUDE.md,
los scripts y los comandos. NO toca las carpetas .memex/ de tus proyectos."""
import json, os, shutil, time

CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")
SETTINGS = os.path.join(CLAUDE, "settings.json")
CLAUDE_MD = os.path.join(CLAUDE, "CLAUDE.md")
START, END = "<!-- memex-kit:start -->", "<!-- memex-kit:end -->"
STAMP = time.strftime("%Y%m%d-%H%M%S")

if os.path.exists(SETTINGS):
    shutil.copy2(SETTINGS, f"{SETTINGS}.bak-{STAMP}")
    with open(SETTINGS, encoding="utf-8") as f:
        data = json.load(f)
    hooks = data.get("hooks", {})
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            g["hooks"] = [h for h in g.get("hooks", []) if "memex_capture.py" not in str(h.get("command", ""))]
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[ev] = groups
        else:
            del hooks[ev]
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("hooks quitados de settings.json")

if os.path.exists(CLAUDE_MD):
    t = open(CLAUDE_MD, encoding="utf-8").read()
    if START in t and END in t:
        t = t[:t.index(START)] + t[t.index(END) + len(END):]
        open(CLAUDE_MD, "w", encoding="utf-8").write(t.rstrip("\n") + "\n")
        print("sección Memex quitada de CLAUDE.md")

for f in ("memex_capture.py", "memex_lib.py", "memex_lint.py"):
    p = os.path.join(CLAUDE, "hooks", f)
    if os.path.exists(p):
        os.remove(p)
p = os.path.join(CLAUDE, "hooks", "tests", "test_memex.py")
if os.path.exists(p):
    os.remove(p)
for c in ("memex-init", "destilar", "registrar-decision", "consultar-historial", "lint-memex"):
    p = os.path.join(CLAUDE, "commands", c + ".md")
    if os.path.exists(p):
        os.remove(p)
print("listo. Reinicia Claude Code.")
