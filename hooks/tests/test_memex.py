"""Tests del hook del memex. Ejecutar: python3 -m unittest discover -s ~/.claude/hooks/tests -v"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS)
import memex_lib as L  # noqa: E402
import memex_lint as LINT  # noqa: E402

HOOK = os.path.join(HOOKS, "memex_capture.py")

PAGE = """---
type: {type}
status: {status}
alcance: transversal
last_updated: 2026-10-27
sources:
  - raw/changelog.jsonl#1
tags: [{tags}]
related: [{related}]
{extra}---

# {title}

{body}
"""


def page(slug_title, type_="lesson", status="vigente", tags="n8n", related="", body="Texto [[otra]].", trigger=None):
    extra = f'trigger: "{trigger}"\n' if trigger else ""
    return PAGE.format(type=type_, status=status, tags=tags, related=related, title=slug_title, body=body, extra=extra)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, "proj")
        self.memex = os.path.join(self.proj, ".memex")
        for d in ("raw", "wiki/lessons", "wiki/synthesis"):
            os.makedirs(os.path.join(self.memex, d))
        open(os.path.join(self.memex, "raw", "changelog.jsonl"), "w").close()
        self.cache = os.path.join(self.tmp, "cache")
        L.CACHE = self.cache
        L.SESSIONS = os.path.join(self.cache, "sessions")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, text):
        p = os.path.join(self.memex, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def cfg(self, **kw):
        self.w("config.json", json.dumps(kw))

    def run_hook(self, payload):
        env = dict(os.environ, HOME=self.tmp)
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def events(self):
        with open(os.path.join(self.memex, "raw", "changelog.jsonl")) as fh:
            return [json.loads(x) for x in fh if x.strip()]


class TestLib(Fixture):
    def test_memex_por_ruta_de_archivo_no_por_cwd(self):
        self.assertEqual(L.memex_for({"cwd": "/", "tool_input": {"file_path": os.path.join(self.proj, "a", "b.py")}}), self.memex)

    def test_tokens_acentos_guiones_y_raiz(self):
        t = L.tokens("El WF-01 está diluyendo contraindicación")
        self.assertIn("wf01", t)
        self.assertIn(L.stem("diluye"), t)

    @unittest.skipIf(L.yaml is None, "PyYAML no instalado (opcional)")
    def test_frontmatter_invalido_se_reporta(self):
        _, err = L.parse_fm("a: b: c")
        self.assertTrue(err)

    def test_retrieve_usa_trigger(self):
        self.w("wiki/lessons/put-sin-diff.md", page("PUT sin diff", trigger="hacer PUT del workflow a producción sin diff nodo a nodo", tags="n8n, put"))
        self.w("wiki/lessons/otra.md", page("Otra cosa", trigger="calcular el IMC del paciente", tags="clinico"))
        pages = L.load_pages(self.memex)
        hits = L.retrieve(pages, "voy a hacer un PUT del workflow a producción", min_score=1.0)
        self.assertEqual(hits[0][1], "put-sin-diff")

    def test_retrieve_ignora_prompts_triviales(self):
        self.w("wiki/lessons/a.md", page("A", trigger="algo importante de n8n"))
        self.assertEqual(L.retrieve(L.load_pages(self.memex), "ok gracias", min_score=0.1), [])


class TestGuardrails(Fixture):
    RULES = [
        {"id": "ig", "tools": ["Write", "Bash"], "patterns": ["graph\\.instagram\\.com/v\\d+\\.\\d+/(?!me/)\\d{10,}/messages"],
         "unless": "\\.memex", "action": "block", "message": "no hardcodear"},
        {"id": "put", "tools": ["Bash"], "patterns": [["(-X\\s*PUT)", "workflows"]], "unless": "\\.memex", "action": "warn", "message": "diff antes"},
    ]

    def setUp(self):
        super().setUp()
        self.w("guardrails.json", json.dumps(self.RULES))

    def payload(self, tool, **ti):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "cwd": self.proj, "session_id": "s1"}

    def test_bloquea_id_hardcodeado(self):
        out = self.run_hook(self.payload("Write", file_path=os.path.join(self.proj, "wf.json"),
                                         content='"url": "https://graph.instagram.com/v24.0/17841476890204674/messages"'))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_permite_me(self):
        self.assertIsNone(self.run_hook(self.payload("Write", file_path=os.path.join(self.proj, "wf.json"),
                                                     content="https://graph.instagram.com/v24.0/me/messages")))

    def test_no_bloquea_documentar_en_el_memex(self):
        self.assertIsNone(self.run_hook(self.payload("Bash", command="cat >> .memex/wiki/x.md <<EOF\ngraph.instagram.com/v24.0/17841476890204674/messages\nEOF")))

    def test_aviso_una_sola_vez_por_sesion(self):
        p = self.payload("Bash", command="curl -X PUT https://n8n/api/v1/workflows/abc")
        first = self.run_hook(p)
        self.assertIn("diff antes", first["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.run_hook(p))

    def test_desactivable_por_config(self):
        self.cfg(guardrails=False)
        self.assertIsNone(self.run_hook(self.payload("Write", file_path=os.path.join(self.proj, "wf.json"),
                                                     content="graph.instagram.com/v24.0/17841476890204674/messages")))


class TestCaptura(Fixture):
    def post(self, tool, **ti):
        return {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "cwd": self.proj, "session_id": "s1"}

    def test_edicion_de_codigo_se_registra(self):
        self.run_hook(self.post("Edit", file_path=os.path.join(self.proj, "src", "a.py")))
        self.assertEqual(len(self.events()), 1)

    def test_ruido_no_se_registra(self):
        self.run_hook(self.post("Write", file_path=os.path.join(self.tmp, ".claude", "plans", "x.md")))
        self.run_hook(self.post("Write", file_path=os.path.join(self.proj, "node_modules", "x.js")))
        self.run_hook(self.post("Bash", command="ls -la"))
        self.run_hook(self.post("Bash", command="curl -s https://n8n/api/v1/workflows/abc"))  # GET: no es escritura
        self.assertEqual(self.events(), [])

    def test_comandos_que_escriben_el_memex_no_se_registran(self):
        self.run_hook(self.post("Bash", command="cat > .memex/guardrails.json <<'EOF'\n-X PUT workflows deploy\nEOF"))
        self.assertEqual(self.events(), [])

    def test_put_a_n8n_es_alta_senal(self):
        self.run_hook(self.post("Bash", command="curl -X PUT https://n8n.example/api/v1/workflows/abc -d @wf.json"))
        ev = self.events()
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev[0]["high"])

    def test_sql_de_cambio_se_registra_y_select_no(self):
        self.run_hook(self.post("mcp__postgres__query", sql="UPDATE leads SET x=1"))
        self.run_hook(self.post("mcp__postgres__query", sql="SELECT 1"))
        self.assertEqual(len(self.events()), 1)

    def test_intencion_viene_del_prompt(self):
        self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "arregla el bug del cerrador por favor", "cwd": self.proj, "session_id": "s1"})
        self.run_hook(self.post("Edit", file_path=os.path.join(self.proj, "a.py")))
        self.assertIn("cerrador", self.events()[0]["intent"])

    def test_duplicados_seguidos_se_colapsan(self):
        for _ in range(3):
            self.run_hook(self.post("Edit", file_path=os.path.join(self.proj, "a.py")))
        self.assertEqual(len(self.events()), 1)

    def test_state_watch_marca_state_touch(self):
        self.cfg(state_watch=["cerebro/"])
        self.run_hook(self.post("Edit", file_path=os.path.join(self.proj, "cerebro", "x.py")))
        self.assertTrue(self.events()[0]["state_touch"])

    def test_pagina_wiki_invalida_avisa_al_instante(self):
        p = self.w("wiki/lessons/mala.md", "---\ntype: lesson\n---\n# Mala\nsin links\n")
        out = self.run_hook(self.post("Write", file_path=p))
        self.assertIn("no cumple", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.events(), [])  # y no ensucia el changelog


class TestStop(Fixture):
    def stop(self, **kw):
        return self.run_hook(dict({"hook_event_name": "Stop", "cwd": self.proj, "session_id": "s1"}, **kw))

    def add_events(self, n, high=False):
        with open(os.path.join(self.memex, "raw", "changelog.jsonl"), "a") as fh:
            for i in range(n):
                e = {"ts": f"2026-10-27T10:0{i}:00-05:00", "tool": "Edit", "summary": f"Edit f{i}.py", "file": f"f{i}.py", "intent": "arreglar X"}
                if high:
                    e["high"] = True
                fh.write(json.dumps(e) + "\n")

    def test_bajo_el_umbral_no_bloquea(self):
        self.cfg(distill_min_events=4)
        self.add_events(2)
        self.assertIsNone(self.stop())

    def test_alta_senal_bloquea_aunque_sea_uno(self):
        self.cfg(distill_min_events=4)
        self.add_events(1, high=True)
        out = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("arreglar X", out["reason"])
        self.assertIn("rutinarios", out["reason"])

    def test_umbral_alcanzado_bloquea(self):
        self.cfg(distill_min_events=4)
        self.add_events(4)
        self.assertEqual(self.stop()["decision"], "block")

    def test_sin_config_se_comporta_como_antes(self):
        self.add_events(1)
        self.assertEqual(self.stop()["decision"], "block")

    def test_no_reentra_si_stop_hook_active(self):
        self.add_events(5)
        self.assertIsNone(self.stop(stop_hook_active=True))

    def test_watermark_al_dia_no_bloquea(self):
        self.add_events(3)
        self.w("raw/.distilled_until", "3")
        self.assertIsNone(self.stop())

    def test_lint_gate_bloquea_por_enlace_roto(self):
        self.cfg(lint_gate=True)
        self.w("wiki/lessons/a.md", page("A", body="enlace [[no-existe]]"))
        self.w("index.md", "# i\n(wiki/lessons/a.md)\n")
        out = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("no-existe", out["reason"])

    def test_autofix_reciprocidad_e_indice(self):
        self.cfg(autofix=True)
        self.w("wiki/lessons/a.md", page("A", related="b", body="ve [[b]]", trigger="cuando A"))
        self.w("wiki/lessons/b.md", page("B", related="", body="ve [[a]]", trigger="cuando B"))
        self.w("index.md", "# i\n- [A](wiki/lessons/a.md)\n")
        self.stop()
        res = LINT.run(self.memex)
        self.assertEqual(res["important"], [])
        with open(os.path.join(self.memex, "wiki/lessons/b.md")) as fh:
            self.assertIn("related: [a]", fh.read())
        with open(os.path.join(self.memex, "index.md")) as fh:
            self.assertIn("wiki/lessons/b.md", fh.read())


class TestSessionStart(Fixture):
    def test_inyecta_estado_y_lecciones_abiertas(self):
        self.cfg(state_page="wiki/synthesis/estado.md")
        self.w("wiki/synthesis/estado.md", page("Estado", type_="synthesis", status="", body="## Qué corre\nEl cerebro. [[a]]"))
        self.w("wiki/lessons/a.md", page("Lección abierta", status="abierta", body="[[estado]]"))
        out = self.run_hook({"hook_event_name": "SessionStart", "cwd": self.proj, "session_id": "s1"})
        txt = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("El cerebro", txt)
        self.assertIn("Lección abierta", txt)

    def test_sin_lecciones_abiertas_no_falla(self):
        self.w("wiki/lessons/a.md", page("A", status="vigente", trigger="algo"))
        self.w("wiki/lessons/b.md", page("B", status="vigente", trigger="otro"))
        out = self.run_hook({"hook_event_name": "SessionStart", "cwd": self.proj, "session_id": "s1"})
        self.assertIn("Lecciones (2)", out["hookSpecificOutput"]["additionalContext"])

    def test_sin_memex_no_hace_nada(self):
        self.assertIsNone(self.run_hook({"hook_event_name": "SessionStart", "cwd": self.tmp}))

    def _start(self, cwd=None):
        out = self.run_hook({"hook_event_name": "SessionStart", "cwd": cwd or self.proj, "session_id": "s1"})
        return out["hookSpecificOutput"]["additionalContext"]

    def test_incluye_fecha_local_y_puntero_al_indice(self):
        self.w("wiki/lessons/a.md", page("A", trigger="algo"))
        txt = self._start()
        self.assertIn("Hoy: ", txt)
        self.assertIn("UTC", txt)
        self.assertIn(".memex/index.md", txt)

    def test_estado_largo_se_inyecta_completo_y_el_limite_es_configurable(self):
        body = "\n".join(f"Linea {i} de contenido del estado." for i in range(150)) + "\n[[a]]"
        self.cfg(state_page="wiki/synthesis/estado.md")
        self.w("wiki/synthesis/estado.md", page("Estado", type_="synthesis", status="", body=body))
        self.w("wiki/lessons/a.md", page("A", trigger="algo", body="[[estado]]"))
        self.assertIn("Linea 149", self._start())
        self.assertNotIn("sigue en la página", self._start())
        self.cfg(state_page="wiki/synthesis/estado.md", state_excerpt_chars=500)
        self.assertIn("sigue en la página", self._start())

    def test_mapa_rapido_lista_decisiones_vigentes(self):
        os.makedirs(os.path.join(self.memex, "wiki", "decisions"), exist_ok=True)
        self.w("wiki/decisions/0001-usar-x.md", page("ADR 0001 — Usar X", type_="decision", status="aceptada", body="[[a]]"))
        self.w("wiki/decisions/0002-vieja.md", page("Vieja", type_="decision", status="rechazada", body="[[a]]"))
        self.w("wiki/lessons/a.md", page("A", trigger="algo"))
        txt = self._start()
        self.assertIn("0001 Usar X", txt)
        self.assertNotIn("Vieja", txt)

    def test_mapa_rapido_desactivable(self):
        self.cfg(session_index=False)
        os.makedirs(os.path.join(self.memex, "wiki", "decisions"), exist_ok=True)
        self.w("wiki/decisions/0001-usar-x.md", page("Usar X", type_="decision", status="aceptada", body="[[a]]"))
        self.w("wiki/lessons/a.md", page("A", trigger="algo"))
        self.assertNotIn("Mapa rápido", self._start())

    def test_avisa_si_el_estado_quedo_viejo(self):
        self.cfg(state_page="wiki/synthesis/estado.md", state_watch=["svc/"])
        sp = self.w("wiki/synthesis/estado.md", page("Estado", type_="synthesis", status="", body="Ok. [[a]]"))
        self.w("wiki/lessons/a.md", page("A", trigger="algo", body="[[estado]]"))
        os.makedirs(os.path.join(self.proj, "svc"))
        code = os.path.join(self.proj, "svc", "app.py")
        open(code, "w").close()
        os.utime(sp, (1_700_000_000, 1_700_000_000))
        os.utime(code, (1_700_000_000 + 2 * 86400, 1_700_000_000 + 2 * 86400))
        self.assertIn("VIEJA", self._start())
        os.utime(code, (1_700_000_000 - 100, 1_700_000_000 - 100))
        self.assertNotIn("VIEJA", self._start())

    def test_cwd_dentro_del_propio_memex_lo_encuentra(self):
        self.w("wiki/lessons/a.md", page("A", trigger="algo"))
        self.assertIn("Memex de este proyecto", self._start(cwd=os.path.join(self.memex, "wiki")))
        self.assertIn("Memex de este proyecto", self._start(cwd=self.memex))


class TestRobustez(Fixture):
    def test_kill_switch(self):
        env = dict(os.environ, HOME=self.tmp, MEMEX_HOOK_DISABLE="1")
        r = subprocess.run([sys.executable, HOOK], input=json.dumps({"hook_event_name": "Stop", "cwd": self.proj}),
                           capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_enabled_false(self):
        self.cfg(enabled=False)
        with open(os.path.join(self.memex, "raw", "changelog.jsonl"), "a") as fh:
            fh.write('{"tool":"Edit"}\n')
        self.assertIsNone(self.run_hook({"hook_event_name": "Stop", "cwd": self.proj, "session_id": "s"}))

    def test_basura_no_rompe(self):
        r = subprocess.run([sys.executable, HOOK], input="{{{", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_config_corrupta_no_rompe(self):
        self.w("config.json", "{no es json")
        self.assertIsNone(self.run_hook({"hook_event_name": "Stop", "cwd": self.proj, "session_id": "s"}))


if __name__ == "__main__":
    unittest.main()
