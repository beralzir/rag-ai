#!/usr/bin/env python3
"""Fumaça ponta a ponta dos scripts da skill rag-ai (stdlib unittest + subprocess).

Cobre: scaffold nos dois formatos, gates verdes, erros plantados (concept sem type, okf_version fora
da raiz, hash divergente), export tag-first→OKF com round-trip, filtro internal_only, guardas de
diretório, corpus_tokens e query_lexical. Cada teste usa diretório temporário próprio.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from ragai_lib import content_hash  # noqa: E402

TAXONOMY = """axes: [topic, industry, geography]
topic:
  - id: ctv
    label_pt: "TV conectada"
    label_en: "Connected TV"
    aliases: [smart tv, "connected tv"]
    scope_note: "vídeo em aparelho conectado"
    status: ativo
industry:
  - id: advertising
    label_pt: "Publicidade"
    label_en: "Advertising"
    aliases: []
    scope_note: "mercado publicitário"
    status: ativo
geography:
  - id: brazil
    label_pt: "Brasil"
    label_en: "Brazil"
    aliases: [br]
    scope_note: "recorte nacional"
    status: ativo
"""
SOURCE_MAPPING = """sources:
  - source: "Estudo Exemplo 2026"
    source_file: "estudo_exemplo_2026.pdf"
    category: midia-digital
    access_basis: publico
  - source: "Painel Pago 2026"
    source_file: "painel_pago_2026.pdf"
    category: consumo
    access_basis: assinatura
    licensor: "Painel Ltda"
"""
BODY_A = ("# Penetração de CTV 2026\n\nA penetração de CTV nos lares brasileiros chegou a 61% em 2026, contra 54% em 2025, "
          "segundo o Instituto Exemplo. O crescimento concentra-se nas classes B e C e nas capitais do Sudeste, "
          "com a TV linear caindo para 72% de alcance semanal.")
BODY_B = ("# Projeção de consumo de vídeo 2027\n\nO painel projeta que o consumo de vídeo sob demanda crescerá 18% em 2027, "
          "com estabilidade da TV linear. Projeção proprietária, uso interno, válida até meados de 2027 segundo a metodologia do painel.")


def run(script, *args, cwd=None):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, cwd=cwd)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def chunk(chunk_id, cat, source, source_file, body, extra=""):
    return (
        "---\n"
        f'chunk_id: "{chunk_id}"\nsource: "{source}"\nsource_file: "{source_file}"\nprimary_category: "{cat}"\n'
        "chunk_index: 1\ntotal_chunks: 1\ndate_ingested: \"2026-09-04\"\n"
        f'content_hash: "{content_hash(body)}"\n'
        "tags:\n  topic: [ctv]\n  industry: [advertising]\n  geography: [brazil]\n"
        'context: "Trecho sobre penetração de CTV no Brasil em 2026, base de comparação com TV linear. Termos-ponte: connected tv, streaming."\n'
        'data_kind: medido\nattributed_to: "Instituto Exemplo"\non_behalf_of: nenhum\nevidence_locator: "p. 41"\n'
        'extraction_quality: nativo\npublished: "2026-03"\nstatus: validated\n'
        f"{extra}\nverbatim: false\ncontains_personal_data: false\n---\n{body}\n"
    )


def make_tagfirst(base: Path):
    code, out = run("scaffold_base.py", "--path", base, "--name", "Base Teste", "--categories", "midia-digital,consumo")
    assert code == 0, out
    (base / "_meta" / "taxonomy.yaml").write_text(TAXONOMY, encoding="utf-8")
    (base / "_meta" / "source_mapping.yaml").write_text(SOURCE_MAPPING, encoding="utf-8")
    (base / "corpus" / "midia-digital" / "midia-digital-0001.md").write_text(
        chunk("midia-digital-0001", "midia-digital", "Estudo Exemplo 2026", "estudo_exemplo_2026.pdf", BODY_A, "access_basis: publico"),
        encoding="utf-8")
    (base / "corpus" / "consumo" / "consumo-0001.md").write_text(
        chunk("consumo-0001", "consumo", "Painel Pago 2026", "painel_pago_2026.pdf", BODY_B,
              'access_basis: assinatura\nlicensor: "Painel Ltda"\npermitted_use: internal_only\ntdm_ai_clause: allowed\n'
              'review_date: "2027-03-01"\nvalid_until: "2027-06"'),
        encoding="utf-8")
    (base / "tabular" / "dictionary.yaml").write_text(
        'table: dados_canonicos\ngrain: "uma linha = um investimento por mês"\ncolumns:\n  - name: mes\n    type: date\n    required: true\n'
        "  - name: investimento_brl\n    type: number\n    required: true\nlineage:\n  - name: fonte_arquivo\n    type: string\n    required: true\n"
        "  - name: lote\n    type: string\n    required: true\n  - name: linha_origem\n    type: string\n    required: true\n", encoding="utf-8")
    (base / "tabular" / "canonical" / "dados_canonicos.csv").write_text(
        "mes,investimento_brl,fonte_arquivo,lote,linha_origem\n2026-01-01,1500.5,plano.xlsx,lote-1,r2\n", encoding="utf-8")
    code, out = run("update_index.py", "--base", base)
    assert code == 0, out


class ScaffoldTagFirst(unittest.TestCase):
    def test_scaffold_validates_and_index_in_sync(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "b"
            code, out = run("scaffold_base.py", "--path", base, "--name", "Base", "--categories", "a,b")
            self.assertEqual(code, 0, out)
            self.assertIn("format: tagfirst", (base / "_meta" / "base_config.yaml").read_text())
            self.assertEqual(run("validate_base.py", "--base", base, "--strict")[0], 0)
            self.assertEqual(run("update_index.py", "--base", base, "--check")[0], 0)
            for s in ("ragai_lib.py", "validate_base.py", "update_index.py", "corpus_tokens.py", "query_lexical.py"):
                self.assertTrue((base / "scripts" / s).exists(), s)

    def test_refuses_non_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "x").write_text("")
            code, out = run("scaffold_base.py", "--path", td, "--name", "B", "--categories", "a")
            self.assertEqual(code, 2)
            self.assertIn("não está vazio", out)

    def test_full_base_passes_with_tabular(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "b"
            make_tagfirst(base)
            code, out = run("validate_base.py", "--base", base, "--strict", "--tabular")
            self.assertEqual(code, 0, out)


class ScaffoldOkf(unittest.TestCase):
    def test_scaffold_okf_validates(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "k"
            code, out = run("scaffold_base.py", "--path", base, "--name", "Bundle", "--categories", "midia,consumo", "--format", "okf")
            self.assertEqual(code, 0, out)
            self.assertIn("format: okf", (base / ".ragai" / "base_config.yaml").read_text())
            self.assertIn('okf_version: "0.2"', (base / "index.md").read_text())
            self.assertNotIn("okf_version", (base / "midia" / "index.md").read_text())
            self.assertTrue((base / "log.md").exists())
            code, out = run("validate_okf.py", "--bundle", base, "--strict", "--profile", "ragai")
            self.assertEqual(code, 0, out)
            self.assertEqual(run("update_index.py", "--base", base, "--check")[0], 0)
            code, out = run("validate_base.py", "--base", base)
            self.assertEqual(code, 2)
            self.assertIn("validate_okf.py", out)

    def test_planted_missing_type(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "k"
            run("scaffold_base.py", "--path", base, "--name", "Bundle", "--categories", "midia", "--format", "okf")
            (base / "midia" / "ruim.md").write_text("---\ntitle: x\nsources:\n  - id: s9\n---\ncorpo\n", encoding="utf-8")
            code, out = run("validate_okf.py", "--bundle", base, "--strict", "--profile", "base")
            self.assertEqual(code, 1)
            self.assertIn("`type` ausente", out)
            self.assertIn("sem `resource`", out)

    def test_planted_okf_version_outside_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "k"
            run("scaffold_base.py", "--path", base, "--name", "Bundle", "--categories", "midia", "--format", "okf")
            idx = base / "midia" / "index.md"
            idx.write_text(idx.read_text().replace("type: index", 'type: index\nokf_version: "0.2"'), encoding="utf-8")
            code, out = run("validate_okf.py", "--bundle", base, "--strict")
            self.assertEqual(code, 1)
            self.assertIn("só é permitido no index.md da raiz", out)

    def test_planted_hash_mismatch_native(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "k"
            run("scaffold_base.py", "--path", base, "--name", "Bundle", "--categories", "midia", "--format", "okf")
            body = "Corpo do concept com texto suficiente para passar no gate de tamanho mínimo da skill rag-ai. " * 3
            (base / "midia" / "c-0001.md").write_text(
                "---\ntype: chunk\ntitle: T\ndescription: D\nsources:\n  - id: s1\n    resource: urn:x\n"
                f"generated: {{by: rag-ai/0.2.0, at: 2026-09-04}}\nstatus: stable\ncontent_hash: {content_hash(body)}\n---\n{body}\n",
                encoding="utf-8")
            self.assertEqual(run("validate_okf.py", "--bundle", base, "--strict")[0], 0)
            with (base / "midia" / "c-0001.md").open("a", encoding="utf-8") as fh:
                fh.write("adulterado\n")
            code, out = run("validate_okf.py", "--bundle", base, "--strict", "--errors-only")
            self.assertEqual(code, 1)
            self.assertIn("content_hash divergente", out)
            code, out = run("validate_okf.py", "--bundle", base, "--file", base / "midia" / "c-0001.md", "--strict", "--errors-only")
            self.assertEqual(code, 1)

    def test_reserved_category_refused(self):
        with tempfile.TemporaryDirectory() as td:
            code, out = run("scaffold_base.py", "--path", Path(td) / "k", "--name", "B", "--categories", "references", "--format", "okf")
            self.assertEqual(code, 2)


class Export(unittest.TestCase):
    def test_export_roundtrip_and_internal_filter(self):
        with tempfile.TemporaryDirectory() as td:
            base, out = Path(td) / "b", Path(td) / "bundle"
            make_tagfirst(base)
            code, log = run("export_okf.py", "--base", base, "--out", out)
            self.assertEqual(code, 0, log)
            self.assertTrue((out / "midia-digital" / "midia-digital-0001.md").exists())
            self.assertFalse((out / "consumo").exists(), "internal_only deveria ficar de fora")
            self.assertIn("consumo/consumo-0001", (out / "log.md").read_text())
            self.assertTrue((out / "references" / "AVISO_GOVERNANCA.md").exists())
            self.assertEqual(run("validate_okf.py", "--bundle", out, "--strict")[0], 0)
            self.assertEqual(run("update_index.py", "--base", out, "--check")[0], 0)
            concept = (out / "midia-digital" / "midia-digital-0001.md").read_text()
            self.assertIn("type: chunk", concept)
            self.assertIn("ragai_status: validated", concept)
            self.assertIn('"topic:ctv"', concept)
            self.assertTrue(concept.endswith(BODY_A + "\n"), "corpo deve ser byte-idêntico")
            with (out / "midia-digital" / "midia-digital-0001.md").open("a", encoding="utf-8") as fh:
                fh.write("adulterado\n")
            code, log = run("validate_okf.py", "--bundle", out, "--strict", "--errors-only")
            self.assertEqual(code, 1)
            self.assertIn("content_hash divergente", log)

    def test_export_allow_internal_and_tabular(self):
        with tempfile.TemporaryDirectory() as td:
            base, out = Path(td) / "b", Path(td) / "bundle"
            make_tagfirst(base)
            code, log = run("export_okf.py", "--base", base, "--out", out, "--allow-internal", "--include-tabular")
            self.assertEqual(code, 0, log)
            c = (out / "consumo" / "consumo-0001.md").read_text()
            self.assertIn("stale_after: 2027-06-30", c)
            self.assertIn("permitted_use: internal_only", c)
            self.assertTrue((out / "tabular" / "dados_canonicos.md").exists())
            self.assertTrue((out / "references" / "tabular" / "dados_canonicos.csv").exists())
            self.assertIn("--allow-internal", (out / "log.md").read_text())

    def test_export_refuses_broken_origin_and_non_empty_out(self):
        with tempfile.TemporaryDirectory() as td:
            base, out = Path(td) / "b", Path(td) / "bundle"
            make_tagfirst(base)
            with (base / "corpus" / "midia-digital" / "midia-digital-0001.md").open("a", encoding="utf-8") as fh:
                fh.write("editado via bash\n")
            code, log = run("export_okf.py", "--base", base, "--out", out)
            self.assertEqual(code, 2)
            self.assertIn("content_hash divergente", log)
            self.assertFalse(out.exists())
            out.mkdir()
            (out / "x").write_text("")
            self.assertEqual(run("export_okf.py", "--base", base, "--out", out)[0], 2)


class Tokens(unittest.TestCase):
    def test_gate(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "b"
            make_tagfirst(base)
            code, out = run("corpus_tokens.py", "--base", base)
            self.assertEqual(code, 0, out)
            self.assertIn("LEITURA_INTEGRAL: ok", out)
            self.assertIn("corpus/midia-digital/midia-digital-0001.md", out)
            code, out = run("corpus_tokens.py", "--base", base, "--max-tokens", "10")
            self.assertEqual(code, 1)
            self.assertIn("LEITURA_INTEGRAL: excede", out)
            code, out = run("corpus_tokens.py", "--base", base, "--json")
            self.assertEqual(code, 0)
            self.assertIn('"read_order"', out)


class Lexical(unittest.TestCase):
    def test_expansion_and_hits(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "b"
            make_tagfirst(base)
            code, out = run("query_lexical.py", "--base", base, "--term", "ctv")
            self.assertEqual(code, 0, out)
            self.assertIn("[QUERY]", out.splitlines()[0])
            self.assertIn("Connected TV", out)
            self.assertIn("midia-digital-0001 · corpus/midia-digital/midia-digital-0001.md", out)
            code, out = run("query_lexical.py", "--base", base, "--term", "xyzzy")
            self.assertEqual(code, 1)
            self.assertIn("[MISS]", out)
            code, out = run("query_lexical.py", "--base", base, "--term", "penetracao", "--no-accents")
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
