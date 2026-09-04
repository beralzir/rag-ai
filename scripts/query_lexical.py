#!/usr/bin/env python3
"""query_lexical: consulta lexical registrada (skill rag-ai).

Expande um termo em alternation regex a partir da taxonomia (id + label_pt + label_en + aliases),
roda `rg -n -i -e <regex>` sobre o corpus (ou varredura Python equivalente quando não há binário
rg) e imprime PRIMEIRO o comando exato: ele é a "query registrada" que acompanha qualquer número
ou citação na resposta. Cada hit sai como `chunk_id · caminho:linha · texto`.

Uso:
  python3 query_lexical.py --base <dir> --term <id-da-taxonomia | texto livre>
                           [--axis topic] [--no-accents] [--context N] [--limit 50] [--pdf]
--no-accents: vogais viram classes ([aáàâã] etc.), útil para consulta sem acento em corpus acentuado.
--pdf: só sugere o comando pdfgrep sobre staging/*.pdf (pdfgrep não é dependência; se ausente, use o
       texto canônico gerado no staging e declare "sem localizador de página").
Exit: 0 com hits; 1 sem hits (registre em search_misses.md se a busca era legítima); 2 infra.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ragai_lib import OKF_EXTENSIONS, YamlError, load_base, split_frontmatter  # noqa: E402

ACCENT_CLASSES = {
    "a": "[aáàâãä]", "e": "[eéèêë]", "i": "[iíìîï]", "o": "[oóòôõö]", "u": "[uúùûü]", "c": "[cç]",
}


def expand_term(taxonomy: dict, term: str, axis: str | None):
    axes = [axis] if axis else list(taxonomy.get("axes") or [])
    for ax in axes:
        for t in (taxonomy.get(ax) or []):
            if isinstance(t, dict) and str(t.get("id")) == term:
                variants = [term, t.get("label_pt"), t.get("label_en")] + list(t.get("aliases") or [])
                return [str(v) for v in variants if v], ax
    return [term], None


def build_regex(variants, no_accents: bool) -> str:
    parts = []
    for v in variants:
        esc = re.escape(v)
        if no_accents:
            esc = "".join(ACCENT_CLASSES.get(ch.lower(), ch) if ch.isalpha() else ch for ch in esc)
        parts.append(esc)
    return "|".join(dict.fromkeys(parts))


def corpus_files(base: Path, fmt: str):
    if fmt == "okf":
        from okf_lib import iter_concepts
        return [p for p, _ in iter_concepts(base)]
    corpus = base / "corpus"
    if not corpus.is_dir():
        return []
    return [f for d in sorted(corpus.iterdir()) if d.is_dir() and not d.name.startswith("_") for f in sorted(d.glob("*.md"))]


def unit_id(path: Path, base: Path, fmt: str, cache: dict) -> str:
    if path in cache:
        return cache[path]
    uid = "?"
    try:
        fm, _ = split_frontmatter(path.read_text(encoding="utf-8"), OKF_EXTENSIONS if fmt == "okf" else frozenset())
        if fmt == "okf":
            from okf_lib import concept_id
            uid = concept_id(base, path)
        else:
            uid = str(fm.get("chunk_id") or path.stem)
    except (YamlError, UnicodeDecodeError):
        uid = path.stem
    cache[path] = uid
    return uid


def main():
    ap = argparse.ArgumentParser(description="Consulta lexical registrada (rg) sobre a base rag-ai")
    ap.add_argument("--base", required=True)
    ap.add_argument("--term", required=True)
    ap.add_argument("--axis")
    ap.add_argument("--no-accents", action="store_true")
    ap.add_argument("--context", type=int, default=0, help="linhas de contexto (-C do rg)")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--pdf", action="store_true")
    args = ap.parse_args()

    base = Path(args.base).expanduser().resolve()
    try:
        data = load_base(base)
        taxonomy, fmt = data["taxonomy"], data["format"]
    except FileNotFoundError:
        taxonomy, fmt = {}, "tagfirst"
    except YamlError as e:
        print(f"[FATAL] config/taxonomia ilegível: {e}")
        sys.exit(2)

    variants, axis = expand_term(taxonomy, args.term, args.axis)
    regex = build_regex(variants, args.no_accents)
    files = corpus_files(base, fmt)
    search_root = "corpus/" if fmt == "tagfirst" else "."
    rg_cmd = ["rg", "-n", "-i"] + (["-C", str(args.context)] if args.context else []) + ["-e", regex, "--glob", "*.md", search_root]
    print(f"[QUERY] cd {base} && " + " ".join(_sh(c) for c in rg_cmd))
    if axis:
        print(f"[EXPANSÃO] termo `{args.term}` (eixo {axis}) → {len(variants)} variante(s): {', '.join(variants)}")
    else:
        print(f"[EXPANSÃO] `{args.term}` não é id da taxonomia; busca literal" + (" sem acentos" if args.no_accents else ""))
    if args.pdf:
        print(f"[PDF] sugerido (pdfgrep não é dependência): pdfgrep -n -i -e {_sh(regex)} staging/*.pdf")

    rg_bin = shutil.which("rg")
    hits = []
    if rg_bin and files:
        r = subprocess.run([rg_bin] + rg_cmd[1:], cwd=str(base), capture_output=True, text=True)
        for line in r.stdout.splitlines():
            m = re.match(r"^(.+?\.md)[:-](\d+)[:-](.*)$", line)
            if m:
                hits.append((base / m.group(1), int(m.group(2)), m.group(3)))
        mode = "rg"
    else:
        pat = re.compile(regex, re.IGNORECASE)
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(lines, start=1):
                if pat.search(line):
                    lo, hi = max(0, i - 1 - args.context), min(len(lines), i + args.context)
                    for j in range(lo, hi):
                        hits.append((f, j + 1, lines[j]))
        mode = "varredura Python (sem binário rg no PATH; resultado equivalente)"
    print(f"[MODO] {mode} · {len(hits)} linha(s)")
    cache: dict = {}
    for f, n, text in hits[: args.limit]:
        try:
            rel = f.relative_to(base)
        except ValueError:
            rel = f
        print(f"{unit_id(f, base, fmt, cache)} · {rel}:{n} · {text.strip()}")
    if len(hits) > args.limit:
        print(f"… {len(hits) - args.limit} linha(s) omitida(s); use --limit")
    if not hits:
        misses = "_meta/search_misses.md" if fmt == "tagfirst" else ".ragai/search_misses.md"
        print(f"[MISS] nenhum hit. Busca legítima sem resultado → registre em {misses} (data, consulta, o que esperava).")
        sys.exit(1)
    sys.exit(0)


def _sh(s: str) -> str:
    return s if re.match(r"^[\w./=-]+$", s) else "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    main()
