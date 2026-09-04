#!/usr/bin/env python3
"""update_index: regenera o índice mestre e o report da base rag-ai.

Conta chunks e fontes por categoria (corpus/), quarentena e linhas das
tabelas canônicas; grava `_meta/ingestion_report.json` e reescreve o bloco
gerenciado de `index.md` (entre os marcadores rag-ai:status). Em base
`format: okf` delega a okf_lib.update_bundle_indexes (listagem por diretório).

Uso:
  python3 update_index.py --base <path> [--check]

--check: não escreve nada; exit 1 se o index.md estiver defasado.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ragai_lib import YamlError, load_base, split_frontmatter  # noqa: E402

BEGIN = "<!-- rag-ai:status:begin -->"
END = "<!-- rag-ai:status:end -->"


def collect(base: Path):
    corpus = base / "corpus"
    chunks = defaultdict(int)
    sources = defaultdict(set)
    if corpus.is_dir():
        for catdir in sorted(p for p in corpus.iterdir() if p.is_dir() and not p.name.startswith("_")):
            for f in catdir.glob("*.md"):
                chunks[catdir.name] += 1
                try:
                    fm, _ = split_frontmatter(f.read_text(encoding="utf-8"))
                    if fm.get("source"):
                        sources[catdir.name].add(str(fm["source"]))
                except (YamlError, UnicodeDecodeError):
                    sources[catdir.name].add("(frontmatter ilegível)")
    quarantine = len(list((corpus / "_quarentena").glob("*.md"))) if (corpus / "_quarentena").is_dir() else 0

    tabular = {}
    canon = base / "tabular" / "canonical"
    if canon.is_dir():
        for c in sorted(canon.glob("*.csv")):
            with c.open(newline="", encoding="utf-8") as fh:
                tabular[c.name] = max(0, sum(1 for _ in csv.reader(fh)) - 1)
    tab_quar = len(list((base / "tabular" / "_quarentena").glob("*"))) if (base / "tabular" / "_quarentena").is_dir() else 0

    return {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "chunks_by_category": dict(sorted(chunks.items())),
        "sources_by_category": {k: sorted(v) for k, v in sorted(sources.items())},
        "total_chunks": sum(chunks.values()),
        "total_sources": len(set().union(*sources.values())) if sources else 0,
        "quarantine_chunks": quarantine,
        "tabular_rows": tabular,
        "tabular_quarantine_items": tab_quar,
    }


def render_block(report: dict) -> str:
    lines = [BEGIN, f"_Atualizado em {report['generated_at']} por update_index.py; não edite este bloco à mão._", ""]
    lines.append("| Categoria | Chunks | Fontes |")
    lines.append("| --- | ---: | ---: |")
    for cat, n in report["chunks_by_category"].items():
        lines.append(f"| {cat} | {n} | {len(report['sources_by_category'].get(cat, []))} |")
    lines.append(f"| **TOTAL** | **{report['total_chunks']}** | **{report['total_sources']}** |")
    lines.append("")
    lines.append(f"Quarentena (corpus): **{report['quarantine_chunks']}** chunk(s)")
    if report["tabular_rows"]:
        lines.append("")
        lines.append("| Tabela canônica | Linhas |")
        lines.append("| --- | ---: |")
        for name, n in report["tabular_rows"].items():
            lines.append(f"| {name} | {n} |")
        lines.append(f"Quarentena (tabular): **{report['tabular_quarantine_items']}** item(ns)")
    lines.append(END)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Índice mestre da base rag-ai")
    ap.add_argument("--base", required=True)
    ap.add_argument("--check", action="store_true", help="só verifica defasagem (exit 1 se defasado)")
    args = ap.parse_args()
    base = Path(args.base).expanduser().resolve()
    try:
        fmt = load_base(base)["format"]
    except FileNotFoundError:
        fmt = "tagfirst"  # bases antigas sem config continuam funcionando
    except YamlError as e:
        print(f"[FATAL] base_config.yaml ilegível: {e}")
        sys.exit(2)
    if fmt == "okf":
        from okf_lib import update_bundle_indexes  # import tardio: bases tag-first não carregam okf_lib
        sys.exit(update_bundle_indexes(base, check=args.check))
    index_path = base / "index.md"
    if not index_path.exists():
        print(f"[FATAL] index.md não encontrado em {base}")
        sys.exit(2)

    report = collect(base)
    block = render_block(report)
    text = index_path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print("[FATAL] marcadores rag-ai:status ausentes do index.md")
        sys.exit(2)
    pre, rest = text.split(BEGIN, 1)
    _, post = rest.split(END, 1)
    new_text = pre + block + post

    if args.check:
        # comparação ignora a linha de data (muda todo dia sem mudar contagens)
        def _core(t):
            return [l for l in t.splitlines() if not l.startswith("_Atualizado em")]

        if _core(text.split(BEGIN, 1)[1].split(END, 1)[0]) != _core(block.replace(BEGIN, "").replace(END, "")):
            print("[FAIL] index.md defasado em relação ao filesystem; rode update_index.py")
            sys.exit(1)
        print("[OK] index.md em dia")
        sys.exit(0)

    (base / "_meta").mkdir(exist_ok=True)
    (base / "_meta" / "ingestion_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    index_path.write_text(new_text, encoding="utf-8")
    print(f"[OK] index.md e _meta/ingestion_report.json atualizados "
          f"({report['total_chunks']} chunks, {report['total_sources']} fontes, "
          f"{report['quarantine_chunks']} em quarentena)")


if __name__ == "__main__":
    main()
