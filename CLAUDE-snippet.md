## Memex de decisiones (memoria por proyecto)

Cada proyecto puede tener una memoria de decisiones en `.memex/` (estilo Memex/Zettelkasten). Sirve para registrar de forma congruente qué se hizo y se decidió, y poder consultarlo antes de decidir para no repetir errores. Funciona tanto para flujos de n8n como para desarrollo de código.

**Cómo opera (mayormente automático):**
- Hooks globales (`~/.claude/hooks/memex_capture.py`, registrados en `settings.json`) capturan cada cambio relevante en `.memex/raw/changelog.jsonl`. No-op en proyectos sin `.memex/`.
- Al cerrar sesión, si hay eventos sin destilar, el hook `Stop` te re-despierta automáticamente para ingestarlos en `.memex/wiki/` y **conectarlos con wikilinks** a lo ya indexado (regla dura: ninguna página sin wikilink saliente). El grafo siempre queda navegable.
- `SessionStart` carga al contexto las lecciones y decisiones recientes si hay `.memex/`.

**Comandos (override/consulta manual, disponibles siempre):**
- `/memex-init` — inicializa `.memex/` en el proyecto (única acción manual obligatoria, una vez por proyecto).
- `/registrar-decision <desc>` — registra una decisión (ADR) en el momento.
- `/consultar-historial <tema>` — corre esto antes de decisiones de diseño importantes.
- `/destilar` — fuerza el ingest+conexión a mitad de sesión.
- `/lint-memex` — health-check del grafo.

**Para proyectos nuevos**: si trabajas en un proyecto de desarrollo sin `.memex/`, sugiere `/memex-init`. La wiki curada se versiona en git; `raw/` queda en `.gitignore`.
