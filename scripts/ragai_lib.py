#!/usr/bin/env python3
"""ragai_lib: parser de YAML restrito + loaders comuns da base rag-ai.

Sem dependências externas (stdlib). O formato aceito é o "YAML restrito"
documentado em references/frontmatter_schema.md:
  - mapas aninhados por indentação de 2 espaços
  - listas em bloco (`- item` / `- chave: valor` com continuação indentada)
  - listas inline `[a, b, "c d"]`
  - escalares: strings (com ou sem aspas), int, float, true/false, null
  - comentários com `#` fora de aspas
O primeiro `:` de cada linha separa chave de valor; o valor pode conter `:` sem aspas, mas evite `:` em chaves.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# ---------------------------------------------------------------- escalares


def _strip_comment(line: str) -> str:
    out, in_s, in_d = [], False, False
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_scalar(tok: str):
    tok = tok.strip()
    if tok == "":
        return None
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        items, buf, in_s, in_d = [], [], False, False
        for ch in inner:
            if ch == "'" and not in_d:
                in_s = not in_s
            elif ch == '"' and not in_s:
                in_d = not in_d
            if ch == "," and not in_s and not in_d:
                items.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        items.append("".join(buf))
        return [parse_scalar(i) for i in items]
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


def parse_restricted_yaml(text: str):
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
            else:
                result[key] = parse_scalar(rest)
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
                item = {key: parse_scalar(val_txt) if val_txt else None}
                pos += 1
                if pos < len(lines) and lines[pos][0] == indent + 2 and not lines[pos][1].startswith("- "):
                    item.update(_parse_map(indent + 2))
                result.append(item)
            else:
                result.append(parse_scalar(body))
                pos += 1
        return result

    result = parse_block(lines[0][0] if lines else 0)
    if pos < len(lines):
        raise YamlError(f"conteúdo não consumido a partir de {lines[pos][1]!r} (estrutura mista mapa/lista?)")
    return result


# ------------------------------------------------------------- frontmatter


def split_frontmatter(md_text: str):
    """Retorna (frontmatter_dict, corpo) ou levanta YamlError."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", md_text, re.DOTALL)
    if not m:
        raise YamlError("frontmatter ausente ou não delimitado por ---")
    return parse_restricted_yaml(m.group(1)), m.group(2)


def content_hash(body: str) -> str:
    norm = re.sub(r"\s+", " ", body).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


# ----------------------------------------------------------------- loaders


def load_yaml_file(path: Path):
    return parse_restricted_yaml(path.read_text(encoding="utf-8"))


def load_base(base: Path):
    """Carrega config + taxonomia + source_mapping da base. Retorna dict."""
    meta = base / "_meta"
    cfg = load_yaml_file(meta / "base_config.yaml")
    taxonomy = load_yaml_file(meta / "taxonomy.yaml")
    mapping_path = meta / "source_mapping.yaml"
    mapping = load_yaml_file(mapping_path) if mapping_path.exists() else {}
    return {"config": cfg or {}, "taxonomy": taxonomy or {}, "mapping": mapping or {}, "root": base}


DATE_RE = re.compile(r"^\d{4}(-\d{2})?(-\d{2})?$")
CHUNK_ID_RE = re.compile(r"^([a-z0-9-]+)-(\d{4,})$")
