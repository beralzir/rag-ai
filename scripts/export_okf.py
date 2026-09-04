#!/usr/bin/env python3
"""export_okf: serializa uma base tag-first como Knowledge Bundle OKF v0.2 (fluxo F da skill rag-ai).

O OKF é camada de INTERCÂMBIO: a governança tag-first (gate falha-fechada, hooks, quarentena,
deny de rede) mora na base de origem e NÃO viaja. O que viaja é verificabilidade passiva:
`content_hash` (8 hex) + `content_sha256` por concept, `sources[]`, `generated`/`verified`,
histórico git. O bundle declara isso em references/AVISO_GOVERNANCA.md e no index.md da raiz.

Mapeamento (perfil versionado em references/okf_mapping_profile.md, profile_version 1):
  chunk_id                        -> Concept ID `<primary_category>/<chunk_id>` (arquivo)
  primary_category + data_kind    -> type (base_config.yaml: okf_export.type_map)
  1º heading `# ` do corpo         -> title (senão "<chunk_id>: <source>")
  context                         -> description
  valid_until (YYYY-MM[-DD])      -> stale_after (último dia do mês)
  date_ingested                   -> generated {by: rag-ai/<versão>, at}
  status: validated               -> verified [{by: rag-ai-validate_base/<versão>, at: <export>}]
  status                          -> status (validated→stable, not_validated→draft, archived→deprecated); original em ragai_status
  tags (mapa eixo→lista)          -> tags ["eixo:termo", ...]; mapa original em ragai_tags
  source/source_file/attributed_to/published/evidence_locator -> sources[0] (resource = URN; o bruto licenciado não viaja)
  demais chaves                   -> chaves extras, verbatim (OKF tolera)
Corpo do chunk: byte-idêntico (content_hash é sobre o corpo; nada é injetado).

Uso:
  python3 export_okf.py --base <base-tagfirst> --out <dir-bundle>
                        [--include-tabular] [--allow-internal] [--force] [--title "..."]
Exit: 0 bundle escrito e validado; 1 bundle escrito mas reprovado no gate (fica no lugar para inspeção); 2 pré-check falhou.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_SCRIPTS))
from ragai_lib import SKILL_VERSION, YamlError, content_hash, content_sha256, load_base, load_yaml_file, split_frontmatter  # noqa: E402
from okf_lib import OKF_VERSION, F, append_log, frontmatter_block, update_bundle_indexes  # noqa: E402

PROFILE_VERSION = 1
DEFAULT_TYPE_MAP = {"medido": "chunk", "modelado": "chunk-modelado", "framework": "chunk-framework",
                    "terceiro": "chunk-terceiro", "default": "chunk"}
STATUS_MAP = {"validated": "stable", "not_validated": "draft", "archived": "deprecated"}
NOTICE_BODY = """# Aviso de governança deste bundle

Este Knowledge Bundle foi **exportado de uma base tag-first** pela skill rag-ai. Leia antes de confiar:

- **O enforcement ativo não viaja.** Na origem, cada unidade passou por gate falha-fechada (frontmatter validado,
  vocabulário controlado, licença por unidade, `content_hash`), hooks append-only e `permissions.deny` de rede.
  Nada disso está no formato: quem recebe precisa **revalidar** (`validate_okf.py --bundle . --strict --profile ragai`).
- **O que viaja é verificabilidade passiva:** `content_hash` (8 hex) e `content_sha256` por concept permitem detectar
  adulteração; `sources[]`, `generated` e `verified` carregam proveniência; o histórico git da origem carrega atribuição.
- **`verified` aqui é sempre machine-confirmed** (gate da origem), nunca revisão humana. Não promova o tier sem revisar.
- **Licença por unidade continua valendo:** os campos `access_basis`, `licensor`, `permitted_use`, `tdm_ai_clause`
  e afins viajam como chaves extras e obrigam quem redistribui. Unidades `permitted_use: internal_only` só entram
  com `--allow-internal` explícito (registrado em log.md).
- **Metade tabular:** sem `--include-tabular`, planilhas canônicas ficam de fora; com a flag, o CSV vai para
  `references/tabular/` com o `dictionary.yaml` ao lado e um concept `type: table` por tabela. Número continua
  saindo só de consulta executada, nunca de memória.
- **Este bundle é snapshot.** A origem evolui por ingestão append-only; re-exporte para atualizar (o `log.md`
  registra o commit de origem).
"""


def die(msg: str):
    print(f"[FATAL] {msg}")
    sys.exit(2)


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    return s or "fonte"


def stale_after_from(valid_until) -> str | None:
    if valid_until is None:
        return None
    s = str(valid_until)
    m = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), m.group(2), m.group(3)
    if d:
        return s
    if mo:
        return f"{y}-{mo}-{calendar.monthrange(y, int(mo))[1]:02d}"
    return f"{y}-12-31"


def derive_type(fm: dict, type_map: dict) -> str:
    if fm.get("type"):
        return str(fm["type"])
    cat, kind = str(fm.get("primary_category") or ""), str(fm.get("data_kind") or "")
    for key in (f"{cat}/{kind}", kind, "default"):
        if key in type_map and type_map[key]:
            return str(type_map[key])
    return DEFAULT_TYPE_MAP.get(kind) or DEFAULT_TYPE_MAP["default"]


def first_heading(body: str) -> str | None:
    m = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    return m.group(1).strip() if m else None


def map_chunk(fm: dict, body: str, type_map: dict, export_date: str) -> dict:
    out = {}
    out[F["type"]] = derive_type(fm, type_map)
    out[F["title"]] = first_heading(body) or f"{fm.get('chunk_id')}: {fm.get('source')}"
    if fm.get("context"):
        out[F["description"]] = str(fm["context"])
    tags = fm.get("tags")
    flat = []
    if isinstance(tags, dict):
        for axis, terms in tags.items():
            for t in (terms or []) if isinstance(terms, list) else [terms]:
                flat.append(f"{axis}:{t}")
    out[F["tags"]] = flat
    src = {F["src_id"]: slug(fm.get("source") or fm.get("source_file") or "fonte"),
           F["src_resource"]: f"urn:ragai:source:{slug(fm.get('source') or fm.get('source_file') or 'fonte')}",
           F["src_title"]: str(fm.get("source") or "")}
    if fm.get("attributed_to") and str(fm["attributed_to"]).lower() != "nenhum":
        src[F["src_author"]] = str(fm["attributed_to"])
    if fm.get("published"):
        pub = stale_after_from(fm["published"])
        if pub:
            src[F["src_last_modified"]] = pub
    if fm.get("evidence_locator"):
        src["locator"] = str(fm["evidence_locator"])
    if fm.get("source_file"):
        src["file"] = str(fm["source_file"])
    out[F["sources"]] = [src]
    out[F["generated"]] = {F["gen_by"]: f"rag-ai/{SKILL_VERSION}", F["gen_at"]: str(fm.get("date_ingested") or export_date)}
    st = str(fm.get("status") or "not_validated")
    if st == "validated":
        out[F["verified"]] = [{F["ver_by"]: f"rag-ai-validate_base/{SKILL_VERSION}", F["ver_at"]: export_date}]
    out[F["status"]] = STATUS_MAP.get(st, "draft")
    sa = stale_after_from(fm.get("valid_until"))
    if sa:
        out[F["stale_after"]] = sa
    for k, v in fm.items():
        if k in ("status", "tags", "type"):
            continue
        out[k] = v
    out["ragai_status"] = st
    if isinstance(tags, dict):
        out["ragai_tags"] = tags
    out["content_sha256"] = content_sha256(body)
    out["ragai_profile_version"] = PROFILE_VERSION
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def export_tabular(base: Path, out: Path, export_date: str, log: list) -> list:
    canon = base / "tabular" / "canonical"
    dict_path = base / "tabular" / "dictionary.yaml"
    csvs = sorted(canon.glob("*.csv")) if canon.is_dir() else []
    if not csvs:
        log.append("tabular: nenhuma tabela canônica na origem")
        return []
    if not dict_path.exists():
        die("--include-tabular sem tabular/dictionary.yaml na origem")
    dic = load_yaml_file(dict_path) or {}
    by_name = None
    if dic.get("tables"):
        by_name = {str(t.get("table")): t for t in dic["tables"] if isinstance(t, dict)}
    ref_dir = out / "references" / "tabular"
    ref_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dict_path, ref_dir / "dictionary.yaml")
    written = []
    for c in csvs:
        shutil.copy2(c, ref_dir / c.name)
        entry = (by_name or {}).get(c.stem, dic) if by_name is not None else dic
        if by_name is not None and c.stem not in by_name:
            log.append(f"tabular: {c.name} sem entrada em dictionary.yaml:tables (copiado sem concept)")
            continue
        cols = (entry.get("columns") or []) + (entry.get("lineage") or [])
        with c.open(newline="", encoding="utf-8") as fh:
            rows = max(0, sum(1 for _ in csv.reader(fh)) - 1)
        body_lines = [f"# {c.stem}", "", f"Tabela canônica tidy exportada da base tag-first ({rows} linha(s)). "
                      "Consulte o CSV com SQL/pandas e registre a query junto do número; este concept descreve o schema, não os dados.",
                      "", "# Schema", "", "| coluna | tipo | obrigatória |", "| --- | --- | --- |"]
        for col in cols:
            if isinstance(col, dict):
                body_lines.append(f"| {col.get('name')} | {col.get('type') or ''} | {'sim' if col.get('required') else 'não'} |")
        if entry.get("grain"):
            body_lines += ["", f"**Grain:** {entry['grain']}"]
        body = "\n".join(body_lines) + "\n"
        fm = {
            F["type"]: "table",
            F["title"]: c.stem,
            F["description"]: f"Schema da tabela canônica {c.stem} ({rows} linhas); dados em /references/tabular/{c.name}",
            F["resource"]: f"/references/tabular/{c.name}",
            F["tags"]: ["tabular"],
            F["sources"]: [{F["src_id"]: "dictionary", F["src_resource"]: "/references/tabular/dictionary.yaml",
                            F["src_title"]: "dictionary.yaml (contrato do schema canônico)"}],
            F["generated"]: {F["gen_by"]: f"rag-ai/{SKILL_VERSION}", F["gen_at"]: export_date},
            F["status"]: "stable",
            "csv_sha256": sha256_file(c),
            "rows": rows,
            "content_hash": content_hash(body),
            "content_sha256": content_sha256(body),
        }
        target = out / "tabular" / f"{c.stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(frontmatter_block(fm) + body, encoding="utf-8")
        written.append(target)
    log.append(f"tabular: {len(written)} concept(s) type: table + CSV/dicionário em references/tabular/")
    return written


def main():
    ap = argparse.ArgumentParser(description="Exporta base tag-first como Knowledge Bundle OKF v0.2")
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--include-tabular", action="store_true")
    ap.add_argument("--allow-internal", action="store_true", help="inclui unidades permitted_use: internal_only (registrado no log)")
    ap.add_argument("--force", action="store_true", help="exporta mesmo com o gate de origem reprovado (registrado no log)")
    ap.add_argument("--title")
    args = ap.parse_args()

    base = Path(args.base).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    try:
        data = load_base(base)
    except (FileNotFoundError, YamlError) as e:
        die(f"não foi possível carregar a base: {e}")
    if data["format"] != "tagfirst":
        die(f"a base já é '{data['format']}'; export_okf.py serializa bases tag-first")
    if out.exists() and any(out.iterdir()):
        die(f"--out não está vazio: {out} (esta ferramenta não sobrescreve nada)")
    cfg = data["config"]
    export_cfg = cfg.get("okf_export") if isinstance(cfg.get("okf_export"), dict) else {}
    type_map = dict(DEFAULT_TYPE_MAP)
    if isinstance(export_cfg.get("type_map"), dict):
        type_map.update({str(k): v for k, v in export_cfg["type_map"].items()})
    export_date = date.today().isoformat()
    log_lines = []

    gate = [sys.executable, str(SKILL_SCRIPTS / "validate_base.py"), "--base", str(base), "--strict", "--errors-only", "--quiet"]
    r = subprocess.run(gate, capture_output=True, text=True)
    print("[PRÉ-CHECK] " + " ".join(gate[1:]))
    if r.returncode != 0:
        print((r.stdout or "").rstrip())
        if not args.force:
            die("gate da base de origem reprovou; corrija ou quarentene antes de exportar (--force registra a exceção no log)")
        log_lines.append("ATENÇÃO: exportado com --force apesar do gate de origem reprovado")
    else:
        print("[PRÉ-CHECK] gate de origem verde")

    g = subprocess.run(["git", "-C", str(base), "rev-parse", "HEAD"], capture_output=True, text=True)
    origin_commit = g.stdout.strip() if g.returncode == 0 and g.stdout.strip() else "unknown (sem git)"

    corpus = base / "corpus"
    cats_present = []
    exported, skipped, hashes = [], [], {}
    for catdir in sorted(p for p in corpus.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for f in sorted(catdir.glob("*.md")):
            try:
                fm, body = split_frontmatter(f.read_text(encoding="utf-8"))
            except YamlError as e:
                die(f"chunk ilegível na origem (o gate deveria ter pego): {f}: {e}")
            cid = str(fm.get("chunk_id") or f.stem)
            if str(fm.get("permitted_use") or "") == "internal_only" and not args.allow_internal:
                skipped.append(f"{catdir.name}/{cid}")
                continue
            okf_fm = map_chunk(fm, body, type_map, export_date)
            target = out / catdir.name / f"{cid}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(frontmatter_block(okf_fm) + body, encoding="utf-8")
            exported.append(target)
            hashes[target] = str(fm.get("content_hash") or "")
            if catdir.name not in cats_present:
                cats_present.append(catdir.name)
    if not exported:
        die("nenhum chunk exportável (corpus vazio ou tudo internal_only)")

    tabular_written = []
    if args.include_tabular:
        tabular_written = export_tabular(base, out, export_date, log_lines)
        if tabular_written:
            cats_present.append("tabular")
    else:
        log_lines.append("tabular: metade tabular OMITIDA (use --include-tabular)")

    notice_fm = {F["type"]: "notice", F["title"]: "Aviso de governança (leia antes de confiar)",
                 F["description"]: "O enforcement ativo da origem tag-first não viaja; o que viaja é verificabilidade passiva por hash e proveniência.",
                 F["generated"]: {F["gen_by"]: f"rag-ai/{SKILL_VERSION}", F["gen_at"]: export_date},
                 F["status"]: "stable", "content_hash": content_hash(NOTICE_BODY), "content_sha256": content_sha256(NOTICE_BODY)}
    (out / "references").mkdir(parents=True, exist_ok=True)
    (out / "references" / "AVISO_GOVERNANCA.md").write_text(frontmatter_block(notice_fm) + NOTICE_BODY, encoding="utf-8")

    title = args.title or export_cfg.get("bundle_title") or f"{cfg.get('name') or base.name} (export OKF)"
    root_fm = {
        F["type"]: "index",
        F["title"]: str(title),
        F["description"]: "Knowledge Bundle exportado de uma base tag-first pela skill rag-ai. O enforcement ativo da origem "
                          "(gate, hooks, deny de rede) NÃO viaja; viaja verificabilidade passiva (content_hash/content_sha256, "
                          "sources, generated/verified). Leia /references/AVISO_GOVERNANCA.md e revalide com validate_okf.py.",
        F["version_key"]: OKF_VERSION,
        "ragai": {"profile": "ragai", "profile_version": PROFILE_VERSION, "skill_version": SKILL_VERSION,
                  "exported_at": export_date, "origin_commit": origin_commit, "source_base": str(cfg.get("name") or base.name),
                  "categories": cats_present, "contains_licensed_units": any(
                      str(split_frontmatter(p.read_text(encoding="utf-8"))[0].get("access_basis") or "publico") != "publico"
                      for p in exported)},
    }
    (out / "index.md").write_text(frontmatter_block(root_fm) + f"\n# {title}\n\nSnapshot exportado em {export_date} "
                                  f"(origem: commit `{origin_commit}`). Leia [o aviso de governança](/references/AVISO_GOVERNANCA.md).\n\n",
                                  encoding="utf-8")
    meta = out / ".ragai"
    meta.mkdir(exist_ok=True)
    (meta / "base_config.yaml").write_text(
        f"""# Housekeeping do bundle exportado (consumidores OKF ignoram este diretório)
format: okf
okf_version: "{OKF_VERSION}"
name: "{title}"
exported_from: "{cfg.get('name') or base.name}"
exported_at: "{export_date}"
origin_commit: "{origin_commit}"
categories: [{", ".join(cats_present)}]
require_context: true
tiny_body_chars: 0
okf:
  require_sources: true
  sources_optional_types: [notice, index, log]
  require_stale_after_for: [chunk-modelado, forecast]
  attested_types: [computation]
""", encoding="utf-8")
    (out / ".gitignore").write_text(".DS_Store\n__pycache__/\n*.pyc\n", encoding="utf-8")
    update_bundle_indexes(out, title=str(title))
    entry = [f"export de '{cfg.get('name') or base.name}' (commit {origin_commit}) por export_okf.py, perfil de mapeamento v{PROFILE_VERSION}",
             f"{len(exported)} concept(s) exportado(s) em {len(cats_present)} categoria(s)",
             f"{len(skipped)} unidade(s) internal_only omitida(s)" + (f": {', '.join(skipped)}" if skipped else "")]
    if args.allow_internal:
        entry.append("ATENÇÃO: --allow-internal usado; unidades internal_only incluídas")
    entry += log_lines
    append_log(out, f"rag-ai/{SKILL_VERSION}", entry, when=export_date)

    print(f"[OK] {len(exported)} concept(s) escritos em {out} ({len(skipped)} internal_only omitidos)")
    ok = 0
    for p, src_hash in hashes.items():
        _, body = split_frontmatter(p.read_text(encoding="utf-8"))
        if content_hash(body) == src_hash:
            ok += 1
        else:
            print(f"[ERRO] hash divergiu no round-trip: {p.relative_to(out)}")
    print(f"[OK] {ok}/{len(hashes)} hashes reconferidos contra a base de origem")
    val = [sys.executable, str(SKILL_SCRIPTS / "validate_okf.py"), "--bundle", str(out), "--strict", "--profile", "ragai", "--quiet"]
    print("[VERIFICAÇÃO] " + " ".join(val[1:]))
    r = subprocess.run(val, capture_output=True, text=True)
    print((r.stdout or "").rstrip())
    if r.returncode != 0 or ok != len(hashes):
        print("[FAIL] bundle escrito mas reprovado; inspecione antes de distribuir")
        sys.exit(1)
    print("[OK] bundle OKF conforme (perfil ragai); enforcement ativo não viaja, veja references/AVISO_GOVERNANCA.md")


if __name__ == "__main__":
    main()
