#!/usr/bin/env python3
"""validate_base: gate estrito da base rag-ai (framework tag-first 2.0).

Valida taxonomia, chunks do corpus e (opcional) tabelas canônicas contra o
schema 2.0. Sem dependências externas.

Uso:
  python3 validate_base.py --base <path> [--strict] [--tabular] [--file <chunk.md>] [--quiet]

Saída: relatório de erros/avisos + contadores.
Exit code: com --strict, 1 se houver QUALQUER issue (erro ou aviso); sem
--strict, sempre 0 (modo relatório). Erro de infraestrutura (config ausente,
YAML ilegível) sai com 2.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ragai_lib import (  # noqa: E402
    CHUNK_ID_RE,
    DATE_RE,
    YamlError,
    content_hash,
    load_base,
    load_yaml_file,
    split_frontmatter,
)

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COVERS_RE = re.compile(r"^\d{4}(-\d{2})?(\s*-\s*\d{4}(-\d{2})?)?$")

DATA_KIND = {"medido", "modelado", "framework", "terceiro"}
EXTRACTION_QUALITY = {"nativo", "ocr", "visao"}
METODO_EXTRACAO = {"tabela_nativa", "rotulo_impresso", "estimado_eixo"}
STATUS = {"not_validated", "validated", "archived"}
ACCESS_BASIS = {"assinatura", "compra", "publico"}
PERMITTED_USE = {"internal_only", "quotable_with_credit", "external_specific"}
TDM_AI = {"allowed", "training_restricted", "consent_required", "silent"}
TERM_STATUS = {"candidato", "ativo", "deprecado"}


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def err(self, where, msg):
        self.errors.append(f"[ERRO] {where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"[AVISO] {where}: {msg}")

    def info(self, where, msg):
        self.infos.append(f"[INFO] {where}: {msg}")


# ------------------------------------------------------------- taxonomia


def validate_taxonomy(base_data, rep: Report):
    cfg, tax = base_data["config"], base_data["taxonomy"]
    axes = cfg.get("axes") or []
    if not axes:
        rep.err("base_config.yaml", "campo 'axes' ausente ou vazio")
        return {}
    tax_axes = tax.get("axes") or []
    if list(tax_axes) != list(axes):
        rep.err("taxonomy.yaml", f"axes {tax_axes} difere do base_config {axes}")

    terms_by_axis: dict[str, dict] = {}
    all_ids: dict[str, str] = {}
    alias_owner: dict[str, str] = {}

    for axis in axes:
        terms = tax.get(axis) or []
        if not isinstance(terms, list):
            rep.err("taxonomy.yaml", f"eixo '{axis}' não é uma lista de termos")
            terms = []
        axis_terms = {}
        for t in terms:
            if not isinstance(t, dict) or "id" not in t:
                rep.err("taxonomy.yaml", f"termo malformado no eixo '{axis}': {t!r}")
                continue
            tid = str(t["id"])
            where = f"taxonomy.yaml:{axis}:{tid}"
            if not SLUG_RE.match(tid):
                rep.err(where, "id deve ser ASCII kebab-case sem acento")
            if tid in all_ids:
                rep.err(where, f"id duplicado (já existe no eixo '{all_ids[tid]}')")
            all_ids[tid] = axis
            status = t.get("status")
            if status not in TERM_STATUS:
                rep.err(where, f"status inválido: {status!r} (use candidato|ativo|deprecado)")
            if status == "deprecado" and not t.get("replaced_by"):
                rep.err(where, "termo deprecado exige replaced_by")
            for field in ("label_pt", "label_en", "scope_note"):
                if not t.get(field):
                    rep.warn(where, f"campo '{field}' ausente")
            for al in t.get("aliases") or []:
                key = str(al).strip().lower()
                if key in alias_owner and alias_owner[key] != tid:
                    rep.err(where, f"alias ambíguo: '{al}' também pertence a '{alias_owner[key]}'")
                alias_owner[key] = tid
            axis_terms[tid] = t
        terms_by_axis[axis] = axis_terms

    # replaced_by aponta para termo ativo existente
    for axis, terms in terms_by_axis.items():
        for tid, t in terms.items():
            rb = t.get("replaced_by")
            if t.get("status") == "deprecado" and rb:
                target = None
                for ax2, ts2 in terms_by_axis.items():
                    if rb in ts2:
                        target = ts2[rb]
                if target is None:
                    rep.err(f"taxonomy.yaml:{axis}:{tid}", f"replaced_by '{rb}' não existe")
                elif target.get("status") != "ativo":
                    rep.err(f"taxonomy.yaml:{axis}:{tid}", f"replaced_by '{rb}' não é termo ativo")
        # alias que colide com id de OUTRO termo
        for al, owner in alias_owner.items():
            if al in all_ids and all_ids.get(al) and al != owner and al in terms:
                rep.err(f"taxonomy.yaml:{axis}", f"alias '{al}' colide com o id de outro termo")
    return terms_by_axis


# ----------------------------------------------------------------- chunks


def _req(fm, field, where, rep, enum=None):
    val = fm.get(field, None)
    if val is None or val == "" or (isinstance(val, list) and not val):
        rep.err(where, f"campo obrigatório ausente: {field}")
        return None
    if enum and str(val) not in enum:
        rep.err(where, f"{field} inválido: {val!r} (use {'|'.join(sorted(enum))})")
    return val


def validate_chunk(path: Path, category: str, base_data, terms_by_axis, rep: Report, seen_ids, hash_index):
    where = str(path)
    try:
        fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except (YamlError, UnicodeDecodeError) as e:
        rep.err(where, f"frontmatter ilegível: {e}")
        return
    cfg = base_data["config"]

    # núcleo
    cid = _req(fm, "chunk_id", where, rep)
    if cid:
        m = CHUNK_ID_RE.match(str(cid))
        if not m:
            rep.err(where, f"chunk_id fora do padrão <categoria>-NNNN: {cid}")
        else:
            if m.group(1) != category:
                rep.err(where, f"prefixo do chunk_id ({m.group(1)}) difere da pasta ({category})")
        if cid in seen_ids:
            rep.err(where, f"chunk_id duplicado: {cid} (também em {seen_ids[cid]})")
        seen_ids[cid] = path.name
    _req(fm, "source_file", where, rep)
    src = _req(fm, "source", where, rep)
    mapping_sources = {
        str(s.get("source")) for s in (base_data["mapping"].get("sources") or []) if isinstance(s, dict)
    }
    if src and mapping_sources and str(src) not in mapping_sources:
        rep.err(where, f"source '{src}' não consta em _meta/source_mapping.yaml")
    if src and not mapping_sources:
        rep.warn(where, "source_mapping.yaml sem fontes registradas")

    pc = _req(fm, "primary_category", where, rep)
    if pc and str(pc) != category:
        rep.err(where, f"primary_category ({pc}) difere da pasta ({category})")
    if category not in (cfg.get("categories") or []):
        rep.err(where, f"categoria '{category}' não declarada em base_config.yaml")

    for f in ("chunk_index", "total_chunks"):
        v = _req(fm, f, where, rep)
        if v is not None and not isinstance(v, int):
            rep.err(where, f"{f} deve ser inteiro (veio {v!r})")
    di = _req(fm, "date_ingested", where, rep)
    if di and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(di)):
        rep.err(where, f"date_ingested deve ser YYYY-MM-DD (veio {di!r})")

    ch = _req(fm, "content_hash", where, rep)
    if ch:
        real = content_hash(body)
        if str(ch) != real:
            rep.err(where, f"content_hash divergente: frontmatter={ch} recalculado={real}")
        hash_index[str(ch)].append(path.name)

    # tags
    tags = fm.get("tags")
    chunk_tag_ids = []
    if not isinstance(tags, dict):
        rep.err(where, "bloco tags ausente ou malformado")
    else:
        for axis in cfg.get("axes") or []:
            vals = tags.get(axis)
            if not vals:
                rep.err(where, f"eixo de tags ausente/vazio: {axis}")
                continue
            if not isinstance(vals, list):
                rep.err(where, f"tags.{axis} deve ser lista")
                continue
            for v in vals:
                v = str(v)
                chunk_tag_ids.append(v)
                term = terms_by_axis.get(axis, {}).get(v)
                if term is None:
                    rep.err(where, f"tag fora do vocabulário: {axis}:{v}")
                elif term.get("status") == "deprecado":
                    rep.err(where, f"tag deprecada: {axis}:{v} (use '{term.get('replaced_by')}')")
                elif term.get("status") == "candidato":
                    rep.warn(where, f"tag candidata em uso: {axis}:{v} (promova ou remova)")

    # contexto
    if cfg.get("require_context", True) and not fm.get("context"):
        rep.err(where, "campo 'context' ausente (50-100 tokens situando o chunk)")

    # proveniência
    dk = _req(fm, "data_kind", where, rep, DATA_KIND)
    if str(dk) == "modelado":
        if not fm.get("derivation_method"):
            rep.err(where, "data_kind=modelado exige derivation_method")
        if not fm.get("valid_until"):
            rep.err(where, "data_kind=modelado exige valid_until")
    _req(fm, "attributed_to", where, rep)
    _req(fm, "evidence_locator", where, rep)
    _req(fm, "extraction_quality", where, rep, EXTRACTION_QUALITY)
    me = fm.get("metodo_extracao")
    if me is not None:
        if str(me) not in METODO_EXTRACAO:
            rep.err(where, f"metodo_extracao inválido: {me!r}")
        elif str(me) == "estimado_eixo":
            de = str(fm.get("dupla_extracao") or "")
            if not de.startswith("concordante"):
                rep.err(where, 'estimado_eixo exige dupla_extracao: "concordante v1=<x> v2=<y> delta=<z>%" '
                               "(sem isso, o chunk pertence à quarentena)")

    # temporal
    pub = _req(fm, "published", where, rep)
    if pub and not DATE_RE.match(str(pub)):
        rep.err(where, f"published fora do formato YYYY[-MM]: {pub!r}")
    cov = fm.get("covers")
    if cov and not COVERS_RE.match(str(cov)):
        rep.err(where, f"covers fora do formato YYYY[-YYYY]: {cov!r}")
    vu = fm.get("valid_until")
    if vu and not DATE_RE.match(str(vu)):
        rep.err(where, f"valid_until fora do formato YYYY-MM: {vu!r}")
    _req(fm, "status", where, rep, STATUS)
    need_vu = set(map(str, cfg.get("require_valid_until_for") or []))
    if need_vu.intersection(chunk_tag_ids) and not vu:
        rep.err(where, f"tags {sorted(need_vu.intersection(chunk_tag_ids))} exigem valid_until")

    # licença
    ab = _req(fm, "access_basis", where, rep, ACCESS_BASIS)
    if ab and str(ab) != "publico":
        if not fm.get("licensor"):
            rep.err(where, "fonte licenciada exige licensor")
        _req(fm, "permitted_use", where, rep, PERMITTED_USE)
        tdm = _req(fm, "tdm_ai_clause", where, rep, TDM_AI)
        if str(tdm) == "consent_required" and not fm.get("consent_ref"):
            rep.err(where, "tdm_ai_clause=consent_required exige consent_ref (registro do consentimento)")
        if not fm.get("review_date"):
            rep.err(where, "fonte paga exige review_date")
    vb = fm.get("verbatim", None)
    if vb is None:
        rep.err(where, "campo obrigatório ausente: verbatim")
    elif vb is True:
        if not isinstance(fm.get("verbatim_len"), int) or fm.get("verbatim_len", 0) <= 0:
            rep.err(where, "verbatim=true exige verbatim_len (nº de frases, inteiro > 0)")
        if not fm.get("attribution"):
            rep.err(where, "verbatim=true exige attribution")
    if fm.get("contains_personal_data", None) is None:
        rep.err(where, "campo obrigatório ausente: contains_personal_data")

    # corpo
    tiny = int(cfg.get("tiny_body_chars") or 200)
    if len(body.strip()) < tiny:
        rep.warn(where, f"corpo com menos de {tiny} caracteres (extração falhou?)")


def validate_corpus(base_data, rep: Report, only_file: Path | None = None):
    root = base_data["root"]
    corpus = root / "corpus"
    if not corpus.is_dir():
        rep.err(str(corpus), "diretório corpus/ ausente")
        return Counter()
    terms_by_axis = validate_taxonomy(base_data, rep)
    seen_ids: dict = {}
    hash_index = defaultdict(list)
    counts = Counter()
    files = []
    for catdir in sorted(p for p in corpus.iterdir() if p.is_dir()):
        if catdir.name.startswith("_"):
            continue
        for f in sorted(catdir.glob("*.md")):
            files.append((f, catdir.name))
    if only_file:
        only = only_file.resolve()
        files = [(f, c) for f, c in files if f.resolve() == only]
        if not files:
            rep.err(str(only_file), "arquivo não está em corpus/<categoria>/ (quarentena não é validada)")
    for f, cat in files:
        counts[cat] += 1
        validate_chunk(f, cat, base_data, terms_by_axis, rep, seen_ids, hash_index)
    for h, names in hash_index.items():
        if len(names) > 1:
            rep.warn("dedup", f"content_hash {h} repetido em: {', '.join(names)}")
    # termos ativos sem uso (só no corpus completo)
    if not only_file:
        used = set()
        for f, _ in files:
            try:
                fm, _b = split_frontmatter(f.read_text(encoding="utf-8"))
                for vals in (fm.get("tags") or {}).values():
                    if isinstance(vals, list):
                        used.update(map(str, vals))
            except YamlError:
                pass
        for axis, terms in terms_by_axis.items():
            for tid, t in terms.items():
                if t.get("status") == "ativo" and tid not in used:
                    rep.warn(f"taxonomy.yaml:{axis}:{tid}", "termo ativo sem nenhum chunk (taxonomia inflada?)")
    return counts


# ---------------------------------------------------------------- tabular


def _check_cell(col, raw, where, row_n, rep, cfg):
    name = col.get("name")
    required = bool(col.get("required"))
    if raw is None or str(raw).strip() == "":
        if required:
            rep.err(where, f"linha {row_n}: coluna obrigatória vazia: {name}")
        return
    val = str(raw).strip()
    ctype = col.get("type", "string")
    if ctype == "number":
        try:
            num = float(val.replace(",", "."))
        except ValueError:
            rep.err(where, f"linha {row_n}: {name} não é número: {val!r}")
            return
        if col.get("min") is not None and num < float(col["min"]):
            rep.err(where, f"linha {row_n}: {name}={num} abaixo do mínimo {col['min']}")
        if col.get("max") is not None and num > float(col["max"]):
            rep.err(where, f"linha {row_n}: {name}={num} acima do máximo {col['max']}")
    elif ctype == "date":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            rep.err(where, f"linha {row_n}: {name} deve ser YYYY-MM-DD: {val!r}")
    ef = col.get("enum_from")
    if ef:
        allowed = set(map(str, (cfg.get("lists") or {}).get(ef) or []))
        if not allowed:
            rep.err(where, f"enum_from '{ef}' não existe em base_config.yaml:lists")
        elif val not in allowed:
            rep.err(where, f"linha {row_n}: {name}={val!r} fora da lista controlada '{ef}'")


def validate_tabular(base_data, rep: Report):
    root = base_data["root"]
    dict_path = root / "tabular" / "dictionary.yaml"
    canon = root / "tabular" / "canonical"
    if not dict_path.exists():
        rep.err(str(dict_path), "dictionary.yaml ausente (contrato do schema canônico)")
        return
    dic = load_yaml_file(dict_path)
    # multi-tabela: `tables:` lista entradas {table, grain, columns, lineage} e o CSV
    # chamado <table>.csv valida contra a sua; sem `tables:`, modo single-table clássico.
    tables = dic.get("tables")
    by_name = None
    if tables:
        by_name = {str(t.get("table")): t for t in tables if isinstance(t, dict)}
    if not canon.is_dir() or not list(canon.glob("*.csv")):
        rep.info(str(canon), "nenhuma tabela canônica ainda (base sem ingestão tabular)")
        return
    for csv_path in sorted(canon.glob("*.csv")):
        where = str(csv_path)
        if by_name is not None:
            entry = by_name.get(csv_path.stem)
            if entry is None:
                rep.err(where, f"CSV sem tabela correspondente em dictionary.yaml:tables: {csv_path.stem}")
                continue
            cols = (entry.get("columns") or []) + (entry.get("lineage") or [])
        else:
            cols = (dic.get("columns") or []) + (dic.get("lineage") or [])
        colnames = [c.get("name") for c in cols]
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            for c in cols:
                if c.get("required") and c.get("name") not in header:
                    rep.err(where, f"coluna obrigatória ausente do header: {c.get('name')}")
            extra = [h for h in header if h not in colnames]
            if extra:
                rep.warn(where, f"colunas fora do dicionário: {extra}")
            n_err_before = len(rep.errors)
            for i, row in enumerate(reader, start=2):
                for c in cols:
                    if c.get("name") in header:
                        _check_cell(c, row.get(c.get("name")), where, i, rep, base_data["config"])
                if len(rep.errors) - n_err_before > 40:
                    rep.err(where, "…mais erros omitidos (corrija e rode de novo)")
                    break


# ------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="Gate estrito da base rag-ai")
    ap.add_argument("--base", required=True)
    ap.add_argument("--strict", action="store_true", help="exit 1 em qualquer issue")
    ap.add_argument("--tabular", action="store_true", help="valida também as tabelas canônicas")
    ap.add_argument("--file", help="valida um único chunk (modo hook)")
    ap.add_argument("--errors-only", action="store_true",
                    help="com --strict, só ERROS bloqueiam (avisos não); uso típico: hook por arquivo")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    base = Path(args.base).expanduser().resolve()
    try:
        base_data = load_base(base)
    except (FileNotFoundError, YamlError) as e:
        print(f"[FATAL] não foi possível carregar a base: {e}")
        sys.exit(2)
    if base_data["format"] != "tagfirst":
        print(f"[FATAL] base em formato '{base_data['format']}': este gate é tag-first. "
              f"Use: python3 scripts/validate_okf.py --bundle {base} --profile ragai --strict")
        sys.exit(2)

    rep = Report()
    counts = validate_corpus(base_data, rep, Path(args.file) if args.file else None)
    if args.tabular:
        validate_tabular(base_data, rep)

    for line in rep.errors + rep.warnings + rep.infos:
        print(line)
    total = sum(counts.values())
    if not args.quiet:
        cats = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nenhum chunk"
        print(f"\n[RESUMO] chunks validados: {total} ({cats})")
        print(f"[RESUMO] erros: {len(rep.errors)} · avisos: {len(rep.warnings)}")
    issues = len(rep.errors) + (0 if args.errors_only else len(rep.warnings))
    if rep.errors:
        print("[FAIL] a base contém erros" + (" (gate --strict: exit 1)" if args.strict else ""))
    elif rep.warnings:
        print("[WARN] sem erros, com avisos" + (" (gate --strict: exit 1)" if args.strict else ""))
    else:
        print("[OK] base íntegra")
    sys.exit(1 if (args.strict and issues) else 0)


if __name__ == "__main__":
    main()
