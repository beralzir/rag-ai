#!/usr/bin/env python3
"""ragai_lib: parser de YAML restrito + loaders comuns da base rag-ai.

Sem dependências externas (stdlib). O formato aceito é o "YAML restrito"
documentado em references/frontmatter_schema.md:
  - mapas aninhados por indentação de 2 espaços
  - listas em bloco (`- item` / `- chave: valor` com continuação indentada)
  - listas inline `[a, b, "c d"]`
  - escalares: strings (com ou sem aspas), int, float, true/false, null
  - comentários com `#` fora de aspas (o `#` precisa estar no início da linha
    ou precedido de espaço, como no YAML; `abc#def` é valor literal)
O primeiro `:` de cada linha separa chave de valor; o valor pode conter `:` sem aspas, mas evite `:` em chaves.

Extensões opcionais (usadas só para bundles OKF, nunca no tag-first):
  - EXT_FLOW_MAP: mapa inline `{by: x, at: y}`
  - EXT_BLOCK_SCALAR: escalar em bloco `|` / `>` (leitura tolerante e com perda:
    comentários e linhas vazias já foram descartados no pré-processamento)
Passe `extensions=OKF_EXTENSIONS` para ativar. Sem o argumento, o comportamento
é o restrito de sempre.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

SKILL_VERSION = "0.2.0"

EXT_FLOW_MAP = "flow_map"
EXT_BLOCK_SCALAR = "block_scalar"
OKF_EXTENSIONS = frozenset({EXT_FLOW_MAP, EXT_BLOCK_SCALAR})

FORMATS = ("tagfirst", "okf")
META_DIRS = ("_meta", ".ragai")

_BLOCK_INDICATOR_RE = re.compile(r"^[|>][+-]?$")

# ---------------------------------------------------------------- escalares


def _strip_comment(line: str) -> str:
    out, in_s, in_d = [], False, False
    for i, ch in enumerate(line):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _split_top_level(inner: str, sep: str = ",") -> list:
    items, buf, in_s, in_d, depth = [], [], False, False, 0
    for ch in inner:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        if not in_s and not in_d:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
        if ch == sep and not in_s and not in_d and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return items


def parse_scalar(tok: str, extensions: frozenset = frozenset()):
    tok = tok.strip()
    if tok == "":
        return None
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(i, extensions) for i in _split_top_level(inner)]
    if EXT_FLOW_MAP in extensions and tok.startswith("{") and tok.endswith("}"):
        inner = tok[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for pair in _split_top_level(inner):
            if ":" not in pair:
                raise YamlError(f"par inválido em mapa inline: {pair!r}")
            k, v = pair.split(":", 1)
            result[parse_scalar(k, extensions)] = parse_scalar(v, extensions)
        return result
    if (tok.startswith('"') and tok.endswith('"') and len(tok) >= 2) or (
        tok.startswith("'") and tok.endswith("'") and len(tok) >= 2
    ):
        return tok[1:-1]
    low = tok.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", "none", "nenhum"):
        return tok if low == "nenhum" else None
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok


# ------------------------------------------------------------------ parser


class YamlError(ValueError):
    pass


def parse_restricted_yaml(text: str, extensions: frozenset = frozenset()):
    """Parseia o subconjunto de YAML descrito no cabeçalho. Retorna dict/list."""
    lines = []
    for raw in text.splitlines():
        line = _strip_comment(raw.replace("\t", "  "))
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    pos = 0

    def parse_block(indent: int):
        nonlocal pos
        if pos >= len(lines):
            return {}
        is_list = lines[pos][1].startswith("- ") or lines[pos][1] == "-"
        return _parse_list(indent) if is_list else _parse_map(indent)

    def _consume_block_scalar(indicator: str, base_indent: int) -> str:
        # Consome as linhas mais indentadas que base_indent como texto (com perda: sem linhas vazias/comentários).
        nonlocal pos
        parts = []
        while pos < len(lines) and lines[pos][0] > base_indent:
            parts.append(lines[pos][1])
            pos += 1
        joiner = "\n" if indicator.startswith("|") else " "
        return joiner.join(parts)

    def _parse_map(indent: int):
        nonlocal pos
        result = {}
        while pos < len(lines):
            ind, content = lines[pos]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError(f"indentação inesperada: {content!r}")
            if content.startswith("- "):
                break
            m = re.match(r"^([^:]+):(.*)$", content)
            if not m:
                raise YamlError(f"linha sem chave: {content!r}")
            key = parse_scalar(m.group(1))
            rest = m.group(2).strip()
            pos += 1
            if rest == "":
                if pos < len(lines) and lines[pos][0] > indent:
                    result[key] = parse_block(lines[pos][0])
                else:
                    result[key] = None
            elif EXT_BLOCK_SCALAR in extensions and _BLOCK_INDICATOR_RE.match(rest):
                result[key] = _consume_block_scalar(rest, indent)
            else:
                result[key] = parse_scalar(rest, extensions)
        return result

    def _parse_list(indent: int):
        nonlocal pos
        result = []
        while pos < len(lines):
            ind, content = lines[pos]
            if ind != indent or not (content.startswith("- ") or content == "-"):
                if ind < indent:
                    break
                raise YamlError(f"item de lista malformado: {content!r}")
            body = content[2:].strip() if content != "-" else ""
            if body == "":
                pos += 1
                result.append(parse_block(indent + 2))
            elif re.match(r"^[^:]+:(\s|$)", body) and not body.startswith(("http:", "https:")):
                # item-dicionário: primeira chave nesta linha, demais indentadas +2
                m = re.match(r"^([^:]+):(.*)$", body)
                key = parse_scalar(m.group(1))
                val_txt = m.group(2).strip()
                pos += 1
                if val_txt and EXT_BLOCK_SCALAR in extensions and _BLOCK_INDICATOR_RE.match(val_txt):
                    item = {key: _consume_block_scalar(val_txt, indent + 2)}
                elif val_txt:
                    item = {key: parse_scalar(val_txt, extensions)}
                elif pos < len(lines) and lines[pos][0] > indent + 2:
                    item = {key: parse_block(lines[pos][0])}
                else:
                    item = {key: None}
                if pos < len(lines) and lines[pos][0] == indent + 2 and not lines[pos][1].startswith("- "):
                    item.update(_parse_map(indent + 2))
                result.append(item)
            else:
                result.append(parse_scalar(body, extensions))
                pos += 1
        return result

    result = parse_block(lines[0][0] if lines else 0)
    if pos < len(lines):
        raise YamlError(f"conteúdo não consumido a partir de {lines[pos][1]!r} (estrutura mista mapa/lista?)")
    return result


# ------------------------------------------------------------- frontmatter


def split_frontmatter(md_text: str, extensions: frozenset = frozenset()):
    """Retorna (frontmatter_dict, corpo) ou levanta YamlError."""
    md_text = md_text.lstrip("﻿")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", md_text, re.DOTALL)
    if not m:
        raise YamlError("frontmatter ausente ou não delimitado por ---")
    return parse_restricted_yaml(m.group(1), extensions), m.group(2)


def content_hash(body: str) -> str:
    norm = re.sub(r"\s+", " ", body).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


def content_sha256(body: str) -> str:
    """Hash completo do corpo normalizado (mesma normalização do content_hash)."""
    norm = re.sub(r"\s+", " ", body).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- loaders


def load_yaml_file(path: Path, extensions: frozenset = frozenset()):
    return parse_restricted_yaml(path.read_text(encoding="utf-8"), extensions)


def meta_dir(base: Path) -> Path:
    """Diretório de metadados da base: `_meta/` (tag-first) ou `.ragai/` (bundle OKF)."""
    for d in META_DIRS:
        if (base / d / "base_config.yaml").exists():
            return base / d
    raise FileNotFoundError(f"base_config.yaml não encontrado em {base}/_meta nem {base}/.ragai")


def load_base(base: Path):
    """Carrega config + taxonomia + source_mapping da base. Retorna dict.

    Chaves: config, taxonomy, mapping, root, meta (Path), format ("tagfirst" | "okf").
    """
    meta = meta_dir(base)
    cfg = load_yaml_file(meta / "base_config.yaml") or {}
    fmt = str(cfg.get("format") or "tagfirst")
    if fmt not in FORMATS:
        raise YamlError(f"format inválido em base_config.yaml: {fmt!r} (use tagfirst|okf)")
    tax_path = meta / "taxonomy.yaml"
    if fmt == "tagfirst" or tax_path.exists():
        taxonomy = load_yaml_file(tax_path) or {}
    else:
        taxonomy = {}
    mapping_path = meta / "source_mapping.yaml"
    mapping = load_yaml_file(mapping_path) if mapping_path.exists() else {}
    return {
        "config": cfg,
        "taxonomy": taxonomy,
        "mapping": mapping or {},
        "root": base,
        "meta": meta,
        "format": fmt,
    }


DATE_RE = re.compile(r"^\d{4}(-\d{2})?(-\d{2})?$")
CHUNK_ID_RE = re.compile(r"^([a-z0-9-]+)-(\d{4,})$")
