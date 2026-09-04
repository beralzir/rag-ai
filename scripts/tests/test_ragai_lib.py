#!/usr/bin/env python3
"""Testes do parser YAML restrito (ragai_lib). Pinam o comportamento tag-first antes e depois das extensões OKF."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ragai_lib as rl  # noqa: E402

SCHEMA_EXAMPLE = """---
chunk_id: "midia-digital-0007"
source: "Estudo Exemplo 2026"
source_file: "estudo_exemplo_2026.pdf"
primary_category: "midia-digital"
chunk_index: 7
total_chunks: 31
date_ingested: "2026-07-02"
content_hash: "a1b2c3d4"
tags:
  topic: [ctv]
  industry: [advertising]
  geography: [brazil]
context: "Seção 3 do Estudo Exemplo 2026, trecho sobre penetração de CTV. Termos-ponte: connected tv, CTV adoption, streaming."
data_kind: medido
attributed_to: "Instituto Exemplo"
on_behalf_of: nenhum
evidence_locator: "p. 41"
extraction_quality: nativo
published: "2026-03"
status: validated
access_basis: publico
verbatim: false
contains_personal_data: false
---
Corpo do chunk.
"""

SCHEMA_EXPECTED = {
    "chunk_id": "midia-digital-0007",
    "source": "Estudo Exemplo 2026",
    "source_file": "estudo_exemplo_2026.pdf",
    "primary_category": "midia-digital",
    "chunk_index": 7,
    "total_chunks": 31,
    "date_ingested": "2026-07-02",
    "content_hash": "a1b2c3d4",
    "tags": {"topic": ["ctv"], "industry": ["advertising"], "geography": ["brazil"]},
    "context": "Seção 3 do Estudo Exemplo 2026, trecho sobre penetração de CTV. Termos-ponte: connected tv, CTV adoption, streaming.",
    "data_kind": "medido",
    "attributed_to": "Instituto Exemplo",
    "on_behalf_of": "nenhum",
    "evidence_locator": "p. 41",
    "extraction_quality": "nativo",
    "published": "2026-03",
    "status": "validated",
    "access_basis": "publico",
    "verbatim": False,
    "contains_personal_data": False,
}

TAXONOMY = """# taxonomia
axes: [topic, industry, geography]
topic:
  - id: ctv
    label_pt: "TV conectada"
    label_en: "Connected TV"
    aliases: [smart tv, "connected tv", streaming na tv]
    scope_note: "Consumo de vídeo via aparelho conectado"
    status: ativo
  - id: retail-media
    label_pt: "Retail media"
    label_en: "Retail media"
    aliases: []
    status: candidato
industry: []
geography: []
"""

TAXONOMY_EXPECTED = {
    "axes": ["topic", "industry", "geography"],
    "topic": [
        {
            "id": "ctv",
            "label_pt": "TV conectada",
            "label_en": "Connected TV",
            "aliases": ["smart tv", "connected tv", "streaming na tv"],
            "scope_note": "Consumo de vídeo via aparelho conectado",
            "status": "ativo",
        },
        {"id": "retail-media", "label_pt": "Retail media", "label_en": "Retail media", "aliases": [], "status": "candidato"},
    ],
    "industry": [],
    "geography": [],
}

SOURCE_MAPPING = """sources:
  - source: "Estudo Exemplo 2026"  # comentário
    primary_category: midia-digital
    default_tags:
      topic: [ctv]
    license: publico
"""

SOURCE_MAPPING_EXPECTED = {
    "sources": [
        {
            "source": "Estudo Exemplo 2026",
            "primary_category": "midia-digital",
            "default_tags": {"topic": ["ctv"]},
            "license": "publico",
        }
    ]
}


class TagFirstGolden(unittest.TestCase):
    def test_schema_example(self):
        fm, body = rl.split_frontmatter(SCHEMA_EXAMPLE)
        self.assertEqual(fm, SCHEMA_EXPECTED)
        self.assertEqual(body, "Corpo do chunk.\n")

    def test_taxonomy(self):
        self.assertEqual(rl.parse_restricted_yaml(TAXONOMY), TAXONOMY_EXPECTED)

    def test_source_mapping(self):
        self.assertEqual(rl.parse_restricted_yaml(SOURCE_MAPPING), SOURCE_MAPPING_EXPECTED)

    def test_content_hash_pinned(self):
        self.assertEqual(rl.content_hash("Corpo   do\n chunk. "), rl.content_hash("Corpo do chunk."))
        self.assertEqual(len(rl.content_hash("x")), 8)
        self.assertEqual(rl.content_sha256("x")[:8], rl.content_hash("x"))

    def test_block_scalar_rejected_without_extension(self):
        with self.assertRaises(rl.YamlError):
            rl.parse_restricted_yaml("description: >\n  linha um\n  linha dois\n")

    def test_flow_map_is_string_without_extension(self):
        self.assertEqual(rl.parse_restricted_yaml("generated: {by: x, at: y}\n"), {"generated": "{by: x, at: y}"})

    def test_hash_inside_token_kept(self):
        self.assertEqual(rl.parse_restricted_yaml("resource: https://x/y#z\n"), {"resource": "https://x/y#z"})
        self.assertEqual(rl.parse_restricted_yaml("k: v # comentário\n"), {"k": "v"})
        self.assertEqual(rl.parse_restricted_yaml("  # só comentário\nk: 1\n"), {"k": 1})

    def test_bom(self):
        fm, _ = rl.split_frontmatter("﻿---\ntype: x\n---\ncorpo")
        self.assertEqual(fm, {"type": "x"})

    def test_nested_block_objects_already_work(self):
        text = "sources:\n  - resource: https://a\n    id: s1\ngenerated:\n  by: rag-ai/0.2.0\n  at: 2026-09-04\nverified:\n  - by: human:bera\n    at: 2026-09-04\n"
        got = rl.parse_restricted_yaml(text)
        self.assertEqual(got["sources"], [{"resource": "https://a", "id": "s1"}])
        self.assertEqual(got["generated"], {"by": "rag-ai/0.2.0", "at": "2026-09-04"})
        self.assertEqual(got["verified"], [{"by": "human:bera", "at": "2026-09-04"}])


class OkfExtensions(unittest.TestCase):
    def test_flow_map(self):
        got = rl.parse_restricted_yaml("generated: {by: rag-ai/0.2.0, at: \"2026-09-04\"}\n", rl.OKF_EXTENSIONS)
        self.assertEqual(got, {"generated": {"by": "rag-ai/0.2.0", "at": "2026-09-04"}})

    def test_flow_map_nested(self):
        got = rl.parse_restricted_yaml("executor: {resource: x, receipt: {id: 1, ok: true}}\n", rl.OKF_EXTENSIONS)
        self.assertEqual(got, {"executor": {"resource": "x", "receipt": {"id": 1, "ok": True}}})
        self.assertEqual(rl.parse_restricted_yaml("e: {}\n", rl.OKF_EXTENSIONS), {"e": {}})

    def test_block_scalar(self):
        got = rl.parse_restricted_yaml("description: >\n  linha um\n  linha dois\ntype: table\n", rl.OKF_EXTENSIONS)
        self.assertEqual(got, {"description": "linha um linha dois", "type": "table"})
        got = rl.parse_restricted_yaml("description: |-\n  linha um\n  linha dois\n", rl.OKF_EXTENSIONS)
        self.assertEqual(got, {"description": "linha um\nlinha dois"})

    def test_block_scalar_in_list_item(self):
        got = rl.parse_restricted_yaml("sources:\n  - resource: https://a\n    title: >\n      um título\n      longo\n    id: s1\n", rl.OKF_EXTENSIONS)
        self.assertEqual(got, {"sources": [{"resource": "https://a", "title": "um título longo", "id": "s1"}]})

    def test_tagfirst_still_restricted_with_extensions_off(self):
        self.assertEqual(rl.split_frontmatter(SCHEMA_EXAMPLE, rl.OKF_EXTENSIONS)[0], SCHEMA_EXPECTED)


class LoadBase(unittest.TestCase):
    def test_meta_dir_and_format(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / ".ragai").mkdir()
            (base / ".ragai" / "base_config.yaml").write_text("format: okf\nname: x\n", encoding="utf-8")
            data = rl.load_base(base)
            self.assertEqual(data["format"], "okf")
            self.assertEqual(data["meta"], base / ".ragai")
            self.assertEqual(data["taxonomy"], {})
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "_meta").mkdir()
            (base / "_meta" / "base_config.yaml").write_text("format: bogus\n", encoding="utf-8")
            with self.assertRaises(rl.YamlError):
                rl.load_base(base)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                rl.load_base(Path(td))


if __name__ == "__main__":
    unittest.main()
