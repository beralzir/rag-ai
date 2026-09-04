#!/usr/bin/env python3
"""validate_okf: gate de bundles Open Knowledge Format (OKF v0.2), skill rag-ai.

Dois perfis:
  base   conformance do spec (§11: frontmatter parseável, `type` não-vazio, reservados bem
         formados) como ERRO; o resto (campos recomendados, trust signals, links) como AVISO.
         É o piso para bundles de terceiros.
  ragai  perfil estrito da skill: trust signals malformados viram ERRO; exige `sources`,
         `generated`, `description`, `content_hash` recomputado, `stale_after` para tipos de
         forecast, categoria e vocabulário quando o bundle declara. Default quando existe
         `.ragai/base_config.yaml`.

Uso:
  python3 validate_okf.py --bundle <dir> [--strict] [--profile base|ragai]
                          [--file <concept.md>] [--errors-only] [--quiet]

Exit: 0 ok (ou modo relatório); 1 com --strict e issues; 2 falha de infraestrutura.
Não promete: cobertura de footnote em números (não é decidível mecanicamente; o que se
checa é que todo concept tem fonte e que toda footnote existente resolve).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ragai_lib import YamlError, content_hash  # noqa: E402
from okf_lib import (  # noqa: E402
    ACTOR_RE, ATTESTED_KEYS, F, FOOTNOTE_DEF_RE, FOOTNOTE_REF_RE, HOUSEKEEPING_FILES, ISO_DATE_RE, LINK_RE,
    LOG_HEADING_RE, OKF_VERSION, RESERVED_FILES, STATUS_VALUES, TAGFIRST_STATUS_BEGIN,
    concept_id, is_skipped, iter_concepts, iter_reserved, load_bundle_config, parse_iso_date,
    read_concept,
)

DEFAULTS = {
    "require_sources": True,
    "sources_optional_types": ["notice", "index", "log"],
    "require_stale_after_for": ["forecast", "chunk-modelado"],
    "attested_types": ["computation"],
}
TERM_STATUS_WARN = {"candidato"}
TERM_STATUS_ERR = {"deprecado"}


class Report:
    def __init__(self):
        self.errors: list = []
        self.warnings: list = []
        self.infos: list = []

    def err(self, where, msg):
        self.errors.append(f"[ERRO] {where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"[AVISO] {where}: {msg}")

    def info(self, where, msg):
        self.infos.append(f"[INFO] {where}: {msg}")


class Gate:
    def __init__(self, bundle: Path, rep: Report, profile: str, cfg: dict):
        self.bundle = bundle
        self.rep = rep
        self.profile = profile
        self.cfg = cfg
        okf_cfg = cfg.get("okf") if isinstance(cfg.get("okf"), dict) else {}
        self.opt = dict(DEFAULTS)
        self.opt.update({k: v for k, v in okf_cfg.items() if v is not None})
        self.categories = [str(c) for c in (cfg.get("categories") or [])]
        self.require_desc = bool(cfg.get("require_context", True))
        self.tiny = int(cfg.get("tiny_body_chars", 200) or 0)
        self.terms = self._load_terms()
        self.today = date.today()

    # severidade por perfil: (base, ragai) em {"err", "warn", None}
    def flag(self, where, msg, base="warn", ragai="err"):
        level = ragai if self.profile == "ragai" else base
        if level == "err":
            self.rep.err(where, msg)
        elif level == "warn":
            self.rep.warn(where, msg)

    def _load_terms(self) -> dict:
        tax_path = self.bundle / ".ragai" / "taxonomy.yaml"
        if not tax_path.exists():
            return {}
        try:
            from ragai_lib import load_yaml_file
            tax = load_yaml_file(tax_path) or {}
        except YamlError:
            return {}
        terms = {}
        for ax in (tax.get("axes") or []):
            for t in (tax.get(ax) or []):
                if isinstance(t, dict) and t.get("id"):
                    terms[str(t["id"])] = str(t.get("status") or "ativo")
        return terms

    # ------------------------------------------------------------ concept
    def check_concept(self, path: Path, cid: str, seen_hash: dict):
        where = cid
        try:
            fm, body = read_concept(path)
        except (YamlError, UnicodeDecodeError) as e:
            self.rep.err(where, f"frontmatter ilegível (§11.1): {e}")
            return
        if not isinstance(fm, dict):
            self.rep.err(where, "frontmatter não é um mapa (§11.1)")
            return
        typ = fm.get(F["type"])
        if not isinstance(typ, str) or not typ.strip():
            self.rep.err(where, f"`{F['type']}` ausente ou vazio (§11.2, único campo obrigatório)")
            typ = ""
        if F["version_key"] in fm:
            self.rep.err(where, f"`{F['version_key']}` só é permitido no index.md da raiz")
        for rec in (F["title"], F["description"]):
            if not fm.get(rec):
                lvl = "err" if (rec == F["description"] and self.require_desc) else "warn"
                self.flag(where, f"campo recomendado `{rec}` ausente", base="warn", ragai=lvl)
        st = fm.get(F["status"])
        if st is not None and st not in STATUS_VALUES:
            self.flag(where, f"`{F['status']}` inválido: {st!r} (use {', '.join(STATUS_VALUES)})")
        sa = fm.get(F["stale_after"])
        if sa is not None:
            d = parse_iso_date(sa)
            if d is None:
                self.flag(where, f"`{F['stale_after']}` não é data ISO-8601: {sa!r}")
            elif d < self.today:
                self.rep.warn(where, f"`{F['stale_after']}` vencido em {d.isoformat()} (concept possivelmente obsoleto)")
        elif self.profile == "ragai" and typ in (self.opt.get("require_stale_after_for") or []):
            self.rep.err(where, f"`{F['stale_after']}` obrigatório para type `{typ}` (forecast/modelado expira)")
        source_ids = self._check_sources(where, fm, typ)
        self._check_trust(where, fm)
        self._check_footnotes(where, body, source_ids)
        self._check_links(where, body)
        tags = fm.get(F["tags"])
        if tags is not None and (not isinstance(tags, list) or any(not isinstance(t, (str, int)) for t in tags)):
            self.flag(where, f"`{F['tags']}` deve ser lista de strings")
        elif isinstance(tags, list) and self.profile == "ragai" and self.terms:
            self._check_vocab(where, tags)
        self._check_attested(where, fm, typ)
        if self.profile == "ragai":
            ch = fm.get("content_hash")
            real = content_hash(body)
            if not ch:
                self.rep.err(where, "`content_hash` ausente (perfil ragai exige verificabilidade passiva)")
            elif str(ch) != real:
                self.rep.err(where, f"content_hash divergente: frontmatter={ch} recomputado={real}")
            else:
                seen_hash.setdefault(real, []).append(cid)
            if self.categories and "/" in cid and cid.split("/", 1)[0] not in self.categories + ["references"]:
                self.rep.err(where, f"diretório `{cid.split('/', 1)[0]}` não está em categories do base_config.yaml")
            elif self.categories and "/" not in cid:
                self.rep.warn(where, "concept na raiz do bundle, fora das categorias declaradas")
            if self.tiny and len(body.strip()) < self.tiny:
                self.rep.warn(where, f"corpo com {len(body.strip())} chars (< tiny_body_chars={self.tiny})")

    def _check_sources(self, where, fm, typ) -> set:
        ids = set()
        src = fm.get(F["sources"])
        if src is None:
            if self.profile == "ragai" and self.opt.get("require_sources") and typ not in (self.opt.get("sources_optional_types") or []):
                self.rep.err(where, f"`{F['sources']}` obrigatório (perfil ragai; isente por type em okf.sources_optional_types)")
            return ids
        if not isinstance(src, list):
            self.flag(where, f"`{F['sources']}` deve ser lista de objetos")
            return ids
        if not src and self.profile == "ragai" and self.opt.get("require_sources") and typ not in (self.opt.get("sources_optional_types") or []):
            self.rep.err(where, f"`{F['sources']}` vazio (perfil ragai)")
        for i, s in enumerate(src):
            if not isinstance(s, dict):
                self.flag(where, f"sources[{i}] não é objeto")
                continue
            if not s.get(F["src_resource"]):
                self.flag(where, f"sources[{i}] sem `{F['src_resource']}` (campo obrigatório do item)")
            if s.get(F["src_id"]) is not None:
                ids.add(str(s[F["src_id"]]))
            lm = s.get(F["src_last_modified"])
            if lm is not None and parse_iso_date(lm) is None:
                self.rep.warn(where, f"sources[{i}].{F['src_last_modified']} não é ISO-8601: {lm!r}")
        return ids

    def _check_trust(self, where, fm):
        gen = fm.get(F["generated"])
        if gen is None:
            if self.profile == "ragai":
                self.rep.err(where, f"`{F['generated']}` ausente (perfil ragai exige by/at)")
        elif not isinstance(gen, dict) or not gen.get(F["gen_by"]) or not gen.get(F["gen_at"]):
            self.flag(where, f"`{F['generated']}` deve ser objeto com `{F['gen_by']}` e `{F['gen_at']}`")
        else:
            self._check_actor(where, f"{F['generated']}.{F['gen_by']}", gen.get(F["gen_by"]))
            self._check_iso(where, f"{F['generated']}.{F['gen_at']}", gen.get(F["gen_at"]))
        ver = fm.get(F["verified"])
        if ver is not None:
            if not isinstance(ver, list):
                self.flag(where, f"`{F['verified']}` deve ser lista de objetos")
            else:
                for i, v in enumerate(ver):
                    if not isinstance(v, dict) or not v.get(F["ver_by"]) or not v.get(F["ver_at"]):
                        self.flag(where, f"verified[{i}] deve ter `{F['ver_by']}` e `{F['ver_at']}`")
                        continue
                    self._check_actor(where, f"verified[{i}].{F['ver_by']}", v.get(F["ver_by"]))
                    self._check_iso(where, f"verified[{i}].{F['ver_at']}", v.get(F["ver_at"]))

    def _check_actor(self, where, field, value):
        if not ACTOR_RE.match(str(value)):
            self.flag(where, f"{field} fora da convenção de ator (`<producer>/<version>`, `human:<id>`, `process:<id>`): {value!r}")

    def _check_iso(self, where, field, value):
        if not ISO_DATE_RE.match(str(value)):
            self.flag(where, f"{field} não é ISO-8601: {value!r}")

    def _check_footnotes(self, where, body, source_ids):
        defs = set(FOOTNOTE_DEF_RE.findall(body))
        for ref in sorted(set(FOOTNOTE_REF_RE.findall(body))):
            if ref not in source_ids and ref not in defs:
                self.flag(where, f"footnote [^{ref}] não resolve para sources[].id nem para definição local")

    def _check_links(self, where, body):
        for target in sorted(set(LINK_RE.findall(body))):
            if target.startswith("/"):
                resolved = self.bundle / target.lstrip("/")
            else:
                resolved = (self.bundle / where).parent / target
            try:
                resolved = resolved.resolve()
            except OSError:
                pass
            if not resolved.exists():
                self.rep.warn(where, f"link não resolve dentro do bundle: {target} (consumidores toleram; corrija mesmo assim)")

    def _check_vocab(self, where, tags):
        for t in tags:
            term = str(t).split(":", 1)[-1]
            st = self.terms.get(term)
            if st is None:
                self.rep.err(where, f"tag `{t}` fora do vocabulário de .ragai/taxonomy.yaml")
            elif st in TERM_STATUS_ERR:
                self.rep.err(where, f"tag `{t}` usa termo deprecado")
            elif st in TERM_STATUS_WARN:
                self.rep.warn(where, f"tag `{t}` usa termo candidato (promova a ativo com chunk-proof)")

    def _check_attested(self, where, fm, typ):
        present = [k for k in ATTESTED_KEYS if k in fm]
        if not present and typ not in (self.opt.get("attested_types") or []):
            return
        for req in (F["runtime"], F["computation"]):
            if not fm.get(req):
                self.flag(where, f"Attested Computation sem `{req}`")
        ex = fm.get(F["executor"])
        if not isinstance(ex, dict) or not ex.get(F["exec_resource"]) or not ex.get(F["exec_receipt"]):
            self.flag(where, f"Attested Computation: `{F['executor']}` precisa de `{F['exec_resource']}` e `{F['exec_receipt']}`")
        params = fm.get(F["parameters"])
        if params is not None and not isinstance(params, list):
            self.flag(where, f"`{F['parameters']}` deve ser lista")

    # ----------------------------------------------------------- reservados
    def check_reserved(self):
        root_index = self.bundle / "index.md"
        if not root_index.exists():
            self.rep.warn(".", "index.md da raiz ausente (progressive disclosure fica sem ponto de entrada)")
        else:
            text = root_index.read_text(encoding="utf-8", errors="replace")
            if TAGFIRST_STATUS_BEGIN in text and self.profile == "ragai":
                self.rep.err("index.md", "índice-mestre tag-first (marcadores rag-ai:status) vazou para o bundle")
            fm = self._reserved_fm(root_index, "index.md")
            if fm is not None:
                ver = fm.get(F["version_key"])
                if ver is None:
                    self.flag("index.md", f"raiz sem `{F['version_key']}` (recomendado pinar a versão)", base="warn", ragai="err")
                elif str(ver) != OKF_VERSION:
                    self.rep.warn("index.md", f"`{F['version_key']}` = {ver!r}; esta ferramenta implementa {OKF_VERSION}")
        for p, rel in iter_reserved(self.bundle):
            if p == root_index:
                continue
            fm = self._reserved_fm(p, str(rel))
            if fm is not None and F["version_key"] in fm:
                self.rep.err(str(rel), f"`{F['version_key']}` só é permitido no index.md da raiz")
            if p.name == "log.md":
                self._check_log(p, str(rel))

    def _reserved_fm(self, path: Path, where: str):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.lstrip("﻿").startswith("---"):
            return {}
        try:
            fm, _ = read_concept(path)
            return fm if isinstance(fm, dict) else {}
        except YamlError as e:
            self.rep.warn(where, f"frontmatter do arquivo reservado ilegível: {e}")
            return None

    def _check_log(self, path: Path, where: str):
        last = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("## "):
                continue
            m = LOG_HEADING_RE.match(line)
            if not m:
                self.rep.warn(where, f"entrada de log sem data ISO e ator (`## <data> · <ator>`): {line[:60]!r}")
                continue
            d = m.group(1)
            if last and d < last:
                self.rep.warn(where, f"entradas de log fora de ordem cronológica ({d} após {last})")
            last = d

    # ------------------------------------------------------------- bundle
    def run(self, only_file: Path | None = None) -> int:
        seen_hash: dict = {}
        if only_file is not None:
            if only_file.name in RESERVED_FILES:
                self.rep.info(str(only_file.name), "arquivo reservado, sem validação por arquivo (rode o bundle inteiro)")
                return 0
            if is_skipped(only_file.relative_to(self.bundle)) or (
                only_file.name in HOUSEKEEPING_FILES and only_file.parent == self.bundle
            ):
                self.rep.info(str(only_file), "fora do namespace de concepts (housekeeping), ignorado")
                return 0
            self.check_concept(only_file, concept_id(self.bundle, only_file), seen_hash)
            return 1
        concepts = list(iter_concepts(self.bundle))
        lower_seen: dict = {}
        for p, cid in concepts:
            self.check_concept(p, cid, seen_hash)
            lower_seen.setdefault(cid.lower(), []).append(cid)
        for k, ids in lower_seen.items():
            if len(ids) > 1:
                self.rep.warn(ids[0], f"concept IDs colidem sem diferenciar maiúsculas: {ids}")
        for h, ids in seen_hash.items():
            if len(ids) > 1:
                self.rep.warn(ids[0], f"content_hash {h} repetido em {ids} (duplicata?)")
        self.check_reserved()
        return len(concepts)


def main():
    ap = argparse.ArgumentParser(description="Gate de bundle OKF v0.2 (skill rag-ai)")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--strict", action="store_true", help="exit 1 em qualquer issue")
    ap.add_argument("--profile", choices=["base", "ragai"], help="default: ragai se existir .ragai/base_config.yaml, senão base")
    ap.add_argument("--file", help="valida um único concept (modo hook)")
    ap.add_argument("--errors-only", action="store_true", help="com --strict, só ERROS bloqueiam")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    bundle = Path(args.bundle).expanduser().resolve()
    if not bundle.is_dir():
        print(f"[FATAL] bundle não encontrado: {bundle}")
        sys.exit(2)
    try:
        cfg = load_bundle_config(bundle)
    except YamlError as e:
        print(f"[FATAL] .ragai/base_config.yaml ilegível: {e}")
        sys.exit(2)
    profile = args.profile or ("ragai" if (bundle / ".ragai" / "base_config.yaml").exists() else "base")
    only = None
    if args.file:
        only = Path(args.file).expanduser().resolve()
        if not only.exists() or bundle not in only.parents:
            print(f"[FATAL] --file precisa existir dentro do bundle: {only}")
            sys.exit(2)
    rep = Report()
    n = Gate(bundle, rep, profile, cfg).run(only)
    for line in rep.errors + rep.warnings + rep.infos:
        print(line)
    if not args.quiet:
        print(f"\n[RESUMO] perfil: {profile} · concepts validados: {n}")
        print(f"[RESUMO] erros: {len(rep.errors)} · avisos: {len(rep.warnings)}")
    issues = len(rep.errors) + (0 if args.errors_only else len(rep.warnings))
    if rep.errors:
        print("[FAIL] o bundle contém erros" + (" (gate --strict: exit 1)" if args.strict else ""))
    elif rep.warnings:
        print("[WARN] sem erros, com avisos" + (" (gate --strict: exit 1)" if args.strict else ""))
    else:
        print("[OK] bundle conforme")
    sys.exit(1 if (args.strict and issues) else 0)


if __name__ == "__main__":
    main()
