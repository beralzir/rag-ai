#!/usr/bin/env python3
"""corpus_tokens: gate da leitura integral (skill rag-ai).

Estima os tokens do corpus (tag-first: corpus/<cat>/*.md; OKF: concepts + index.md/log.md)
com heurística stdlib e compara com `read_all.max_tokens` do base_config.yaml (default 150000,
abaixo da orientação de 200k tokens com folga para system prompt, skill, pergunta e resposta).
Imprime a ordem de leitura determinística para o agente envolver cada arquivo em
<document index="n"><source>caminho</source>...</document>.

Fator default 3.2 chars/token: a régua comum de ~4 chars/token é para prosa em inglês; PT-BR
acentuado, frontmatter YAML denso e slugs kebab-case tokenizam mais denso. 3.2 superestima de
propósito (o erro barato é dizer "não cabe"). Ajuste em `read_all.chars_per_token` ou --chars-per-token.

Uso:
  python3 corpus_tokens.py --base <dir> [--include cat1,cat2] [--exclude cat3]
                           [--max-tokens N] [--chars-per-token F] [--json]
Exit: 0 cabe; 1 excede; 2 falha de infraestrutura.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ragai_lib import CHUNK_ID_RE, YamlError, load_base  # noqa: E402

DEFAULT_MAX_TOKENS = 150000
DEFAULT_CHARS_PER_TOKEN = 3.2
WRAPPER_OVERHEAD_TOKENS = 25  # tags <document>/<source> por arquivo


def _chunk_order_key(path: Path):
    m = CHUNK_ID_RE.match(path.stem)
    return (0, int(m.group(2)), path.name) if m else (1, 0, path.name)


def collect_tagfirst(base: Path, cfg: dict, include, exclude):
    corpus = base / "corpus"
    if not corpus.is_dir():
        return []
    declared = [str(c) for c in (cfg.get("categories") or [])]
    present = sorted(p.name for p in corpus.iterdir() if p.is_dir() and not p.name.startswith("_"))
    ordered = [c for c in declared if c in present] + [c for c in present if c not in declared]
    files = []
    for cat in ordered:
        if include and cat not in include:
            continue
        if exclude and cat in exclude:
            continue
        for f in sorted((corpus / cat).glob("*.md"), key=_chunk_order_key):
            files.append((cat, f))
    return files


def collect_okf(base: Path, include, exclude):
    from okf_lib import iter_concepts, iter_reserved
    files = []
    for p, rel in iter_reserved(base):
        files.append(("(reservados)", p))
    for p, cid in iter_concepts(base):
        cat = cid.split("/", 1)[0] if "/" in cid else "(raiz)"
        if include and cat not in include:
            continue
        if exclude and cat in exclude:
            continue
        files.append((cat, p))
    return files


def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def main():
    ap = argparse.ArgumentParser(description="Estimativa de tokens do corpus e gate de leitura integral")
    ap.add_argument("--base", required=True)
    ap.add_argument("--include", help="categorias a incluir (vírgula)")
    ap.add_argument("--exclude", help="categorias a excluir (vírgula)")
    ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--chars-per-token", type=float)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = Path(args.base).expanduser().resolve()
    if not base.is_dir():
        print(f"[FATAL] base não encontrada: {base}")
        sys.exit(2)
    try:
        data = load_base(base)
        cfg, fmt = data["config"], data["format"]
    except FileNotFoundError:
        cfg, fmt = {}, "tagfirst"
    except YamlError as e:
        print(f"[FATAL] base_config.yaml ilegível: {e}")
        sys.exit(2)
    ra = cfg.get("read_all") if isinstance(cfg.get("read_all"), dict) else {}
    max_tokens = args.max_tokens or int(ra.get("max_tokens") or DEFAULT_MAX_TOKENS)
    factor = args.chars_per_token or float(ra.get("chars_per_token") or DEFAULT_CHARS_PER_TOKEN)
    include = {s.strip() for s in args.include.split(",")} if args.include else set()
    exclude = {s.strip() for s in args.exclude.split(",")} if args.exclude else set()

    files = collect_okf(base, include, exclude) if fmt == "okf" else collect_tagfirst(base, cfg, include, exclude)
    per_cat: dict = {}
    order = []
    total_chars = 0
    for cat, f in files:
        try:
            chars = len(f.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            chars = f.stat().st_size
        total_chars += chars
        c = per_cat.setdefault(cat, {"files": 0, "chars": 0})
        c["files"] += 1
        c["chars"] += chars
        order.append(str(f.relative_to(base)))
    tokens_est = int(total_chars / factor) + WRAPPER_OVERHEAD_TOKENS * len(files)
    fits = tokens_est <= max_tokens
    result = {
        "base": base.name, "format": fmt, "chars_per_token": factor, "max_tokens": max_tokens,
        "files": len(files), "chars": total_chars, "tokens_est": tokens_est, "fits": fits,
        "by_category": {k: dict(v, tokens_est=int(v["chars"] / factor) + WRAPPER_OVERHEAD_TOKENS * v["files"]) for k, v in per_cat.items()},
        "read_order": order,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[LEITURA_INTEGRAL] base: {base.name} · formato: {fmt} · fator: {factor} chars/token · limite: {fmt_int(max_tokens)}")
        print("| Categoria | Arquivos | Chars | Tokens est. |")
        print("| --- | ---: | ---: | ---: |")
        for cat, v in result["by_category"].items():
            print(f"| {cat} | {v['files']} | {fmt_int(v['chars'])} | {fmt_int(v['tokens_est'])} |")
        print(f"| **TOTAL** | **{len(files)}** | **{fmt_int(total_chars)}** | **{fmt_int(tokens_est)}** |")
        if files:
            print('Ordem de leitura (envolva cada arquivo em <document index="n"><source>caminho</source>...</document>):')
            for i, rel in enumerate(order, start=1):
                print(f"  {i} {rel}")
        else:
            print("(corpus vazio)")
        verdict = "ok" if fits else "excede"
        cmp = "<=" if fits else ">"
        print(f"LEITURA_INTEGRAL: {verdict}   ({fmt_int(tokens_est)} {cmp} {fmt_int(max_tokens)})")
    sys.exit(0 if fits else 1)


if __name__ == "__main__":
    main()
