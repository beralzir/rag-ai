#!/usr/bin/env python3
"""okf_lib: dicionário do spec OKF v0.2 + helpers compartilhados para bundles.

Open Knowledge Format (Google Cloud, GoogleCloudPlatform/open-knowledge-format, Apache-2.0).
Todos os nomes de campo do spec vivem em OKF_V02_FIELDS: uma mudança de spec (v0.3) é um
edit aqui, não uma caça por vários scripts. Sem dependências externas (stdlib).

Usado por validate_okf.py, export_okf.py, update_index.py (modo okf) e scaffold_base.py.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from ragai_lib import OKF_EXTENSIONS, YamlError, load_yaml_file, split_frontmatter

OKF_VERSION = "0.2"

# Única fonte dos nomes de campo do spec. Chave interna -> nome no frontmatter.
OKF_V02_FIELDS = {
    "version_key": "okf_version",
    "type": "type",
    "title": "title",
    "description": "description",
    "resource": "resource",
    "tags": "tags",
    "sources": "sources",
    "src_resource": "resource",
    "src_id": "id",
    "src_title": "title",
    "src_author": "author",
    "src_usage_count": "usage_count",
    "src_usage_window": "usage_window",
    "src_last_modified": "last_modified",
    "generated": "generated",
    "gen_by": "by",
    "gen_at": "at",
    "verified": "verified",
    "ver_by": "by",
    "ver_at": "at",
    "status": "status",
    "stale_after": "stale_after",
    "runtime": "runtime",
    "parameters": "parameters",
    "computation": "computation",
    "executor": "executor",
    "exec_resource": "resource",
    "exec_receipt": "receipt",
    "attester": "attester",
}
F = OKF_V02_FIELDS

RESERVED_FILES = ("index.md", "log.md")
# Arquivos de instrução do harness/repo, não concepts. Um validador OKF de terceiros pode apontá-los
# (§11.1 exige frontmatter em todo .md não reservado); o export não os copia, e o CLAUDE.md nativo
# fica documentado como housekeeping em references/okf_bundle.md.
HOUSEKEEPING_FILES = ("CLAUDE.md", "README.md", "AGENTS.md")
SKIP_DIRS = {".git", ".claude", ".ragai", "_meta", "staging", "scripts", "node_modules", "__pycache__"}
STATUS_VALUES = ("draft", "stable", "deprecated")
STATUS_DEFAULT = "stable"
ATTESTED_KEYS = (F["runtime"], F["parameters"], F["computation"], F["executor"], F["attester"])

ACTOR_RE = re.compile(r"^(human:[^\s/]+|process:[^\s/]+|[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.+-]*)$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:", re.M)
LINK_RE = re.compile(r"\]\(((?:/|\./|\.\./)[^)#\s]+\.md)(?:#[^)]*)?\)")
LOG_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?:T[\d:.]+Z?)?\s*·\s*(.+)$")

LISTING_BEGIN = "<!-- rag-ai:listing:begin -->"
LISTING_END = "<!-- rag-ai:listing:end -->"
TAGFIRST_STATUS_BEGIN = "<!-- rag-ai:status:begin -->"

# ------------------------------------------------------------- travessia


def is_skipped(rel: Path) -> bool:
    """Diretórios de housekeeping (dotdirs, staging, scripts) não fazem parte do namespace de concepts."""
    return any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts[:-1])


def iter_md(bundle: Path):
    for p in sorted(bundle.rglob("*.md")):
        rel = p.relative_to(bundle)
        if is_skipped(rel):
            continue
        yield p, rel


def iter_concepts(bundle: Path):
    """(path, concept_id) de todo .md não reservado fora de SKIP_DIRS, em ordem estável."""
    for p, rel in iter_md(bundle):
        if p.name in RESERVED_FILES or (p.name in HOUSEKEEPING_FILES and len(rel.parts) == 1):
            continue
        yield p, concept_id(bundle, p)


def iter_reserved(bundle: Path):
    for p, rel in iter_md(bundle):
        if p.name in RESERVED_FILES:
            yield p, rel


def concept_id(bundle: Path, path: Path) -> str:
    rel = path.relative_to(bundle)
    return "/".join(rel.parts)[: -len(".md")]


def read_concept(path: Path):
    """(frontmatter, corpo) com as extensões OKF ligadas. Levanta YamlError."""
    return split_frontmatter(path.read_text(encoding="utf-8"), OKF_EXTENSIONS)


def trust_tier(fm: dict) -> str:
    """Tier derivado do spec: sem verified = unverified; só não-humanos = machine-confirmed; algum human: = human-reviewed."""
    ver = fm.get(F["verified"])
    if not isinstance(ver, list) or not ver:
        return "unverified"
    actors = [str(v.get(F["ver_by"], "")) for v in ver if isinstance(v, dict)]
    if any(a.startswith("human:") for a in actors):
        return "human-reviewed"
    return "machine-confirmed"


def load_bundle_config(bundle: Path) -> dict:
    cfg_path = bundle / ".ragai" / "base_config.yaml"
    if cfg_path.exists():
        return load_yaml_file(cfg_path) or {}
    return {}


def parse_iso_date(value) -> "date | None":
    s = str(value)
    if not ISO_DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ------------------------------------------------------------- emissão YAML

_PLAIN_RE = re.compile(r"^[A-Za-z0-9_./+-]+$")
_RESERVED_WORDS = {"true", "false", "yes", "no", "null", "none", "nenhum", "~"}


def yaml_str(value) -> str:
    """Escalar que o parser restrito lê de volta com o mesmo tipo."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value)
    if _PLAIN_RE.match(s) and s.lower() not in _RESERVED_WORDS and not _looks_numeric(s) and ":" not in s and "#" not in s:
        return s
    if '"' not in s:
        return json.dumps(s, ensure_ascii=False)
    if "'" not in s:
        return "'" + s + "'"
    return json.dumps(s.replace('"', "'"), ensure_ascii=False)


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def emit_yaml(obj, indent: int = 0) -> str:
    """Serializa dict/list/escalar em YAML de bloco que ragai_lib lê de volta. Listas de escalares ficam inline."""
    pad = " " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                if not v:
                    out.append(f"{pad}{k}: {{}}")
                else:
                    out.append(f"{pad}{k}:")
                    out.append(emit_yaml(v, indent + 2))
            elif isinstance(v, list):
                if not v:
                    out.append(f"{pad}{k}: []")
                elif all(not isinstance(i, (dict, list)) for i in v):
                    out.append(f"{pad}{k}: [" + ", ".join(yaml_str(i) for i in v) + "]")
                else:
                    out.append(f"{pad}{k}:")
                    out.append(emit_yaml(v, indent + 2))
            else:
                out.append(f"{pad}{k}: {yaml_str(v)}")
        return "\n".join(out)
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item:
                first = True
                for k, v in item.items():
                    if first:
                        if isinstance(v, (dict, list)) and v:
                            out.append(f"{pad}- {k}:")
                            out.append(emit_yaml(v, indent + 4))
                        elif isinstance(v, dict):
                            out.append(f"{pad}- {k}: {{}}")
                        elif isinstance(v, list):
                            out.append(f"{pad}- {k}: []")
                        else:
                            out.append(f"{pad}- {k}: {yaml_str(v)}")
                        first = False
                    else:
                        out.append(emit_yaml({k: v}, indent + 2))
            else:
                out.append(f"{pad}- {yaml_str(item)}")
        return "\n".join(out)
    return pad + yaml_str(obj)


def frontmatter_block(fm: dict) -> str:
    return "---\n" + emit_yaml(fm) + "\n---\n"


# ---------------------------------------------------------------- índices


def _concept_summary(bundle: Path, path: Path) -> dict:
    cid = concept_id(bundle, path)
    try:
        fm, _ = read_concept(path)
    except (YamlError, UnicodeDecodeError):
        return {"id": cid, "title": cid, "description": "(frontmatter ilegível)", "type": "?", "status": "?", "tier": "?"}
    return {
        "id": cid,
        "title": str(fm.get(F["title"]) or cid),
        "description": str(fm.get(F["description"]) or "").strip(),
        "type": str(fm.get(F["type"]) or "?"),
        "status": str(fm.get(F["status"]) or STATUS_DEFAULT),
        "tier": trust_tier(fm),
    }


def render_listing(entries: list, subdirs: list) -> str:
    lines = [LISTING_BEGIN, f"_Atualizado em {date.today().isoformat()} por update_index.py; não edite este bloco à mão._", ""]
    for d in subdirs:
        lines.append(f"- [{d}/](/{d}/index.md)")
    for e in entries:
        desc = f": {e['description']}" if e["description"] else ""
        lines.append(f"- [{e['title']}](/{e['id']}.md){desc} ({e['type']} · {e['status']} · {e['tier']})")
    if not entries and not subdirs:
        lines.append("_(sem concepts neste diretório)_")
    lines.append(LISTING_END)
    return "\n".join(lines)


def _listing_core(text: str):
    if LISTING_BEGIN not in text or LISTING_END not in text:
        return None
    inner = text.split(LISTING_BEGIN, 1)[1].split(LISTING_END, 1)[0]
    return [l for l in inner.splitlines() if l.strip() and not l.startswith("_Atualizado em")]


def _splice(text: str, block: str) -> str:
    if LISTING_BEGIN in text and LISTING_END in text:
        pre, rest = text.split(LISTING_BEGIN, 1)
        _, post = rest.split(LISTING_END, 1)
        return pre + block + post
    return text.rstrip("\n") + "\n\n" + block + "\n"


def update_bundle_indexes(bundle: Path, check: bool = False, title: str | None = None) -> int:
    """Regenera o bloco de listagem de cada index.md (um nível de roteamento por diretório).

    check=True não escreve; retorna 1 se algum index.md estiver defasado. Cria index.md ausente
    (raiz recebe okf_version). Também grava .ragai/ingestion_report.json fora do modo check.
    """
    concepts_by_dir: dict = {}
    for p, cid in iter_concepts(bundle):
        concepts_by_dir.setdefault(p.parent, []).append(p)
    dirs = set(concepts_by_dir)
    dirs.add(bundle)
    for d in list(dirs):
        while d != bundle:
            d = d.parent
            dirs.add(d)
    stale = []
    report = {"schema_version": 1, "generated_at": date.today().isoformat(), "okf_version": OKF_VERSION,
              "concepts_by_dir": {}, "total_concepts": 0, "by_type": {}, "by_status": {}, "by_tier": {}}
    for d in sorted(dirs):
        entries = [_concept_summary(bundle, p) for p in sorted(concepts_by_dir.get(d, []))]
        subdirs = sorted(
            "/".join(s.relative_to(bundle).parts) for s in d.iterdir()
            if s.is_dir() and s in dirs and s != d
        )
        rel = "/".join(d.relative_to(bundle).parts) or "."
        report["concepts_by_dir"][rel] = len(entries)
        report["total_concepts"] += len(entries)
        for e in entries:
            for key, val in (("by_type", e["type"]), ("by_status", e["status"]), ("by_tier", e["tier"])):
                report[key][val] = report[key].get(val, 0) + 1
        block = render_listing(entries, subdirs)
        idx = d / "index.md"
        if idx.exists():
            text = idx.read_text(encoding="utf-8")
        else:
            fm = {F["type"]: "index", F["title"]: (title or bundle.name) if d == bundle else rel}
            if d == bundle:
                fm[F["version_key"]] = OKF_VERSION
            text = frontmatter_block(fm) + f"\n# {fm[F['title']]}\n\n"
        new_text = _splice(text, block)
        if check:
            if _listing_core(text) != _listing_core(new_text):
                stale.append(rel)
        elif new_text != text:
            idx.write_text(new_text, encoding="utf-8")
    if check:
        if stale:
            print("[FAIL] index.md defasado em: " + ", ".join(stale) + "; rode update_index.py")
            return 1
        print("[OK] índices do bundle em dia")
        return 0
    meta = bundle / ".ragai"
    if meta.is_dir():
        (meta / "ingestion_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] índices do bundle atualizados ({report['total_concepts']} concepts em {len(dirs)} diretório(s))")
    return 0


# ------------------------------------------------------------------- log


def append_log(bundle: Path, actor: str, lines: list, when: str | None = None) -> None:
    """Acrescenta uma entrada ao log.md reservado (append-only por convenção; o hook reforça)."""
    log = bundle / "log.md"
    head = f"## {when or now_iso()} · {actor}\n"
    body = "".join(f"- {l}\n" for l in lines)
    if log.exists():
        text = log.read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + head + body
    else:
        text = frontmatter_block({F["type"]: "log", F["title"]: "Histórico do bundle"}) + "\n# Histórico\n\n" + head + body
    log.write_text(text, encoding="utf-8")
