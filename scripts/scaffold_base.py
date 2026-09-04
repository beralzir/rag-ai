#!/usr/bin/env python3
"""scaffold_base: cria uma base de conhecimento da skill rag-ai, em um de dois formatos.

  --format tagfirst (default)  base tag-first 2.0: corpus/, tabular/, _meta/, staging/, hooks
                               append-only e gate estrito (validate_base.py).
  --format okf                 Knowledge Bundle Open Knowledge Format v0.2: concepts por
                               diretório, index.md/log.md reservados, references/, metadados
                               em .ragai/, hooks e gate OKF (validate_okf.py, perfil ragai).

Nos dois casos: configs em YAML restrito, scripts operacionais copiados para dentro da base
(autossuficiência), hooks de proteção e `permissions.deny` de rede em `.claude/`, CLAUDE.md
da base. Recusa destino não-vazio (append-only começa aqui).

Uso:
  python3 scaffold_base.py --path <destino> --name "Minha Base" \
      --categories "midia-digital,consumo,macro" \
      [--format tagfirst|okf] [--axes "topic,industry,geography"] [--no-tabular]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_SCRIPTS))
from ragai_lib import SKILL_VERSION  # noqa: E402

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SCRIPTS_BY_FORMAT = {
    "tagfirst": ("ragai_lib.py", "validate_base.py", "update_index.py", "corpus_tokens.py", "query_lexical.py"),
    "okf": ("ragai_lib.py", "okf_lib.py", "validate_okf.py", "update_index.py", "corpus_tokens.py", "query_lexical.py"),
}


def die(msg: str):
    print(f"[FATAL] {msg}")
    sys.exit(2)


def w(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  + {path}")


# ------------------------------------------------------------ compartilhado


def taxonomy_template(axes: list) -> str:
    axes_inline = "[" + ", ".join(axes) + "]"
    lines = ["# Taxonomia da base (fonte única de termos válidos)", f"axes: {axes_inline}", ""]
    for ax in axes:
        lines += [
            f"{ax}:",
            f"  # - id: exemplo-{ax}",
            '  #   label_pt: "exemplo"',
            '  #   label_en: "example"',
            "  #   aliases: []",
            '  #   scope_note: "quando usar; quando NÃO usar"',
            "  #   status: ativo",
            "",
        ]
    return "\n".join(lines)


SOURCE_MAPPING_TEMPLATE = """# Fonte única de roteamento: toda fonte ingerida tem entrada aqui
sources:
#  - source: "Nome Canônico do Documento"
#    source_file: "arquivo_original.pdf"
#    category: slug-da-categoria
#    access_basis: publico          # assinatura | compra | publico
#    licensor: ""
#    tags:
#      topic: []
"""

GOLDEN_SET_TEMPLATE = """# Golden set: perguntas de avaliação

20-30 perguntas estratégicas reais; formato em references/audit_eval.md da skill rag-ai.

## Rodadas
| data | score | notas |
| --- | --- | --- |
"""

READ_ALL_BLOCK = """# leitura integral (corpus_tokens.py): limite de tokens e fator chars/token (3.2 é conservador para PT-BR)
read_all:
  max_tokens: 150000
  chars_per_token: 3.2
"""


def write_meta_docs(meta: Path, today: str):
    w(meta / "TAXONOMY_CHANGELOG.md",
      f"# Changelog da taxonomia\n\n- {today} · base criada; taxonomia inicial vazia (termos entram com chunk-proof).\n")
    w(meta / "golden_set.md", GOLDEN_SET_TEMPLATE)
    w(meta / "reingestion_queue.md", "# Fila de reingestão (PDFs sem texto extraível, re-OCR pendente)\n")
    w(meta / "search_misses.md", "# Misses de busca (consulta legítima que não achou nada)\n\n| data | consulta | esperava |\n| --- | --- | --- |\n")


def copy_scripts(base: Path, fmt: str):
    (base / "scripts").mkdir(exist_ok=True)
    for s in SCRIPTS_BY_FORMAT[fmt]:
        src = SKILL_SCRIPTS / s
        if not src.exists():
            die(f"script da skill não encontrado: {src}")
        shutil.copy2(src, base / "scripts" / s)
        print(f"  + {base / 'scripts' / s} (cópia; base autossuficiente)")


def write_settings(base: Path):
    settings = {
        # rede em deny por default: documento de terceiro é input não confiável
        # (afrouxe conscientemente quando a sessão não for de ingestão)
        "permissions": {"deny": ["WebFetch", "WebSearch"]},
        "hooks": {
            "PreToolUse": [{
                "matcher": "Edit|Write",
                "hooks": [{"type": "command",
                           "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/protect_corpus.py\""}],
            }],
            "PostToolUse": [{
                "matcher": "Edit|Write",
                "hooks": [{"type": "command",
                           "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/validate_on_write.py\""}],
            }],
        }
    }
    settings_path = base / ".claude" / "settings.json"
    if settings_path.exists():
        settings_path = base / ".claude" / "settings.rag-ai-sugerido.json"
        print("  ! .claude/settings.json já existia; hooks sugeridos gravados ao lado")
    w(settings_path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")


def run_update_index(base: Path):
    r = subprocess.run([sys.executable, str(base / "scripts" / "update_index.py"), "--base", str(base)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("update_index.py falhou logo após o scaffold:\n" + (r.stdout or "") + (r.stderr or ""))
    print("  " + (r.stdout or "").strip())


# ------------------------------------------------------------- tag-first

HOOK_PROTECT_TAGFIRST = '''#!/usr/bin/env python3
"""PreToolUse: append-only físico. Bloqueia Edit/Write em chunk/tabela já existente."""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
fp = (data.get("tool_input") or {}).get("file_path") or ""
if not fp:
    sys.exit(0)
p = Path(fp).expanduser().resolve()
protected = [BASE / "corpus", BASE / "tabular" / "canonical", BASE / "_meta" / "manifests"]
inside = any(str(p).startswith(str(root) + "/") or p == root for root in protected)
in_quarantine = "_quarentena" in p.parts
if inside and not in_quarantine and p.exists():
    print(
        f"[rag-ai] append-only: {p.name} ja e conteudo validado. "
        "Correcao = mover para _quarentena/ (com nota no log) ou operacao estrutural via PR "
        "(pausando este hook conscientemente). Criacao de arquivo NOVO segue permitida.",
        file=sys.stderr,
    )
    sys.exit(2)
sys.exit(0)
'''

HOOK_VALIDATE_TAGFIRST = '''#!/usr/bin/env python3
"""PostToolUse: gate automático. Valida o chunk recém-escrito; erro volta ao agente."""
import json, subprocess, sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
fp = (data.get("tool_input") or {}).get("file_path") or ""
if not fp:
    sys.exit(0)
p = Path(fp).expanduser().resolve()
corpus = BASE / "corpus"
if not str(p).startswith(str(corpus) + "/") or p.suffix != ".md" or "_quarentena" in p.parts:
    sys.exit(0)
r = subprocess.run(
    [sys.executable, str(BASE / "scripts" / "validate_base.py"),
     "--base", str(BASE), "--file", str(p), "--strict", "--errors-only", "--quiet"],
    capture_output=True, text=True,
)
if r.returncode != 0:
    print("[rag-ai] gate reprovou o chunk recem-escrito:\\n" + (r.stdout or "") + (r.stderr or ""),
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
'''


def scaffold_tagfirst(args, base: Path, axes: list, cats: list, today: str):
    for cat in cats:
        (base / "corpus" / cat).mkdir(parents=True, exist_ok=True)
    (base / "corpus" / "_quarentena").mkdir(parents=True, exist_ok=True)
    (base / "staging").mkdir(parents=True, exist_ok=True)
    (base / "_meta" / "manifests").mkdir(parents=True, exist_ok=True)
    if not args.no_tabular:
        for d in ("raw", "mappings", "canonical", "_quarentena"):
            (base / "tabular" / d).mkdir(parents=True, exist_ok=True)

    axes_inline = "[" + ", ".join(axes) + "]"
    cats_inline = "[" + ", ".join(cats) + "]"
    w(base / "_meta" / "base_config.yaml", f"""# Config da base (YAML restrito; ver skill rag-ai)
format: tagfirst
name: "{args.name}"
created: "{today}"
created_by: "skill rag-ai v{SKILL_VERSION}"
axes: {axes_inline}
categories: {cats_inline}
require_context: true
# tags que exigem valid_until no chunk (ex.: [forecast])
require_valid_until_for: []
tiny_body_chars: 200
# listas controladas para a metade tabular (enum_from do dictionary.yaml)
lists:
{READ_ALL_BLOCK}# export para OKF (export_okf.py): como derivar `type` do data_kind (chaves: "<categoria>/<data_kind>", "<data_kind>", "default")
okf_export:
  type_map:
    default: chunk
    modelado: chunk-modelado
""")
    w(base / "_meta" / "taxonomy.yaml", taxonomy_template(axes))
    w(base / "_meta" / "source_mapping.yaml", SOURCE_MAPPING_TEMPLATE)
    write_meta_docs(base / "_meta", today)

    if not args.no_tabular:
        w(base / "tabular" / "dictionary.yaml", """# Dicionário de dados: o contrato do schema canônico (edite para o seu domínio)
table: dados_canonicos
grain: "uma linha = uma observação"
columns:
#  - name: exemplo
#    type: string            # string | number | date
#    required: true
#    enum_from: nome-da-lista   # opcional; lista em base_config.yaml:lists
lineage:
  - name: fonte_arquivo
    type: string
    required: true
  - name: lote
    type: string
    required: true
  - name: linha_origem
    type: string
    required: true
""")

    # CLAUDE.md (não BASE.md): o Claude Code autocarrega este arquivo quando a
    # base é aberta como raiz do projeto; é assim que os fatos entram na sessão.
    w(base / "CLAUDE.md", f"""# {args.name}

Base de conhecimento **tag-first 2.0** (criada pela skill rag-ai v{SKILL_VERSION} em {today}). Fatos permanentes:

- **Formato:** `tagfirst` (registrado em `_meta/base_config.yaml`; a decisão de forma não se reabre sem gatilho medido).
- **Eixos de tags:** {", ".join(axes)} · vocabulário único em `_meta/taxonomy.yaml` (tag fora dele não passa no gate).
- **Categorias (home físico apenas):** {", ".join(cats)} · descoberta é por TAGS, não por pasta.
- **Duas metades:** chunks narrativos em `corpus/`; dados tabulares em `tabular/canonical/` (planilha nunca vira chunk).
- **Append-only:** chunk validado não se edita (hooks bloqueiam); correção = quarentena ou operação estrutural via PR.
- **Números:** só de consulta executada (SQL/pandas para tabular; `scripts/query_lexical.py` ou `rg` para texto), com a query registrada junto do resultado.
- **Ingestão:** só pelo runbook da skill rag-ai, com pedido explícito do usuário (registrado como `authorized_by` no manifest), staging seguro, gate estrito e manifest por lote.
- **Consulta:** corte por tags no frontmatter → expandir em PT+EN via labels/aliases da taxonomia → ler e citar `chunk_id`; número tabular só via SQL/pandas com a query na resposta; `valid_until` vencido entra com aviso; busca sem resultado → registrar em `_meta/search_misses.md`. Pergunta de síntese global: `python3 scripts/corpus_tokens.py --base .` decide se cabe leitura integral.
- **Gate:** `python3 scripts/validate_base.py --base . --strict` · Índice: `python3 scripts/update_index.py --base .`
- **Estado vivo:** contagens em `index.md`; manifests em `_meta/manifests/`; pendências em `_meta/reingestion_queue.md`.
""")

    w(base / "index.md", f"""# {args.name}: índice mestre

<!-- rag-ai:status:begin -->
<!-- rag-ai:status:end -->

## Categorias (escopo e fontes-chave)

{chr(10).join(f"### {c}" + chr(10) + "**Escopo:** (preencher)" + chr(10) for c in cats)}
""")
    w(base / ".gitignore", "staging/\n.DS_Store\n__pycache__/\n*.pyc\n")
    copy_scripts(base, "tagfirst")
    hooks_dir = base / ".claude" / "hooks"
    w(hooks_dir / "protect_corpus.py", HOOK_PROTECT_TAGFIRST)
    w(hooks_dir / "validate_on_write.py", HOOK_VALIDATE_TAGFIRST)
    write_settings(base)
    run_update_index(base)

    print(f"""
[OK] base tag-first criada. Próximos passos:
  1. Preencha _meta/taxonomy.yaml (termos com chunk-proof; labels PT/EN + aliases).
  2. Revise _meta/base_config.yaml (require_valid_until_for, lists, read_all, okf_export).
  3. Prove o gate: python3 scripts/validate_base.py --base {base} --strict
  4. git init + commit inicial (mudanças estruturais futuras via PR).

[ATENÇÃO] Abra a base como RAIZ do projeto no Claude Code: hooks e permissions.deny
de .claude/settings.json NÃO se aplicam se a base estiver aninhada noutro projeto.
Append-only via hook cobre as ferramentas Edit/Write; nunca crie/mova chunk via Bash.
""")


# ------------------------------------------------------------------- OKF

HOOK_PROTECT_OKF = '''#!/usr/bin/env python3
"""PreToolUse (bundle OKF): concept `stable`/`deprecated` é append-only; `log.md` só cresce.

Concept com `status: draft` continua editável. Reservados `index.md` e `CLAUDE.md` são livres
(a defasagem do índice é pega por update_index.py --check).
"""
import json, re, sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tool = data.get("tool_name") or ""
ti = data.get("tool_input") or {}
fp = ti.get("file_path") or ""
if not fp:
    sys.exit(0)
p = Path(fp).expanduser().resolve()
try:
    rel = p.relative_to(BASE)
except ValueError:
    sys.exit(0)
parts = rel.parts
if p.suffix != ".md" or any(part.startswith(".") for part in parts[:-1]) or parts[0] in ("staging", "scripts"):
    sys.exit(0)
if p.name in ("CLAUDE.md", "index.md"):
    sys.exit(0)
if p.name == "log.md":
    if not p.exists():
        sys.exit(0)
    old = p.read_text(encoding="utf-8").rstrip("\\n")
    if tool == "Write" and str(ti.get("content") or "").startswith(old):
        sys.exit(0)
    print("[rag-ai] log.md e append-only: use Write mantendo o conteudo antigo intacto e acrescentando a nova entrada.",
          file=sys.stderr)
    sys.exit(2)
if p.exists():
    head = p.read_text(encoding="utf-8", errors="replace")[:4000]
    m = re.search(r"^status:\\s*(\\S+)", head, re.M)
    status = (m.group(1).strip("\\"'") if m else "stable")
    if status == "draft":
        sys.exit(0)
    print(
        f"[rag-ai] append-only: {rel} e concept `{status}`. Correcao = concept NOVO (id novo) apontando o antigo, "
        "ou operacao estrutural via PR (pausando este hook conscientemente); reprovado vai para .ragai/quarentena/.",
        file=sys.stderr,
    )
    sys.exit(2)
sys.exit(0)
'''

HOOK_VALIDATE_OKF = '''#!/usr/bin/env python3
"""PostToolUse (bundle OKF): gate automático. Valida o concept recém-escrito (perfil ragai)."""
import json, subprocess, sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
fp = (data.get("tool_input") or {}).get("file_path") or ""
if not fp:
    sys.exit(0)
p = Path(fp).expanduser().resolve()
try:
    rel = p.relative_to(BASE)
except ValueError:
    sys.exit(0)
parts = rel.parts
if p.suffix != ".md" or any(part.startswith(".") for part in parts[:-1]) or parts[0] in ("staging", "scripts"):
    sys.exit(0)
if p.name in ("index.md", "log.md", "CLAUDE.md"):
    sys.exit(0)
r = subprocess.run(
    [sys.executable, str(BASE / "scripts" / "validate_okf.py"),
     "--bundle", str(BASE), "--file", str(p), "--strict", "--errors-only", "--quiet", "--profile", "ragai"],
    capture_output=True, text=True,
)
if r.returncode != 0:
    print("[rag-ai] gate OKF reprovou o concept recem-escrito:\\n" + (r.stdout or "") + (r.stderr or ""),
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
'''


def scaffold_okf(args, base: Path, axes: list, cats: list, today: str):
    from okf_lib import OKF_VERSION, append_log, frontmatter_block
    if not args.no_tabular:
        print("  [INFO] bundle OKF não tem metade tabular; dados tabulares entram via export (--include-tabular) "
              "ou como concept `type: table` apontando um CSV em references/.")
    meta = base / ".ragai"
    for cat in cats:
        (base / cat).mkdir(parents=True, exist_ok=True)
    (base / "references").mkdir(parents=True, exist_ok=True)
    (base / "references" / ".gitkeep").write_text("", encoding="utf-8")
    (base / "staging").mkdir(parents=True, exist_ok=True)
    (meta / "manifests").mkdir(parents=True, exist_ok=True)
    (meta / "quarentena").mkdir(parents=True, exist_ok=True)

    axes_inline = "[" + ", ".join(axes) + "]"
    cats_inline = "[" + ", ".join(cats) + "]"
    w(meta / "base_config.yaml", f"""# Config do bundle OKF (YAML restrito; ver skill rag-ai). Diretório .ragai/ é housekeeping: consumidores OKF o ignoram.
format: okf
okf_version: "{OKF_VERSION}"
name: "{args.name}"
created: "{today}"
created_by: "skill rag-ai v{SKILL_VERSION}"
axes: {axes_inline}
categories: {cats_inline}
require_context: true
tiny_body_chars: 200
# perfil ragai do validate_okf.py
okf:
  require_sources: true
  sources_optional_types: [notice, index, log]
  require_stale_after_for: [forecast, chunk-modelado]
  attested_types: [computation]
{READ_ALL_BLOCK}""")
    w(meta / "taxonomy.yaml", taxonomy_template(axes))
    w(meta / "source_mapping.yaml", SOURCE_MAPPING_TEMPLATE)
    write_meta_docs(meta, today)

    root_fm = {
        "type": "index",
        "title": args.name,
        "description": f"Knowledge Bundle OKF v{OKF_VERSION} criado pela skill rag-ai. Consumidores: leia este index.md, "
                       "escolha concepts, siga os links. Governança ativa (gate, hooks, deny de rede) vive no harness "
                       "local desta base, não no formato; revalide com validate_okf.py antes de confiar.",
        "okf_version": OKF_VERSION,
        "ragai": {"profile": "ragai", "skill_version": SKILL_VERSION, "created": today},
    }
    w(base / "index.md", frontmatter_block(root_fm) + f"\n# {args.name}\n\nUm nível de roteamento: cada categoria abaixo tem o seu `index.md`.\n\n")
    for cat in cats:
        w(base / cat / "index.md", frontmatter_block({"type": "index", "title": cat, "description": "(preencher: escopo desta categoria)"})
          + f"\n# {cat}\n\n**Escopo:** (preencher)\n\n")
    append_log(base, f"rag-ai/{SKILL_VERSION}",
               [f"bundle criado por scaffold_base.py --format okf (categorias: {', '.join(cats)}; eixos: {', '.join(axes)})",
                "decisão de forma: OKF (registrada em .ragai/base_config.yaml: format); não reabrir sem gatilho medido"],
               when=today)

    w(base / "CLAUDE.md", f"""# {args.name}

Knowledge Bundle **Open Knowledge Format v{OKF_VERSION}** (criado pela skill rag-ai v{SKILL_VERSION} em {today}). Fatos permanentes:

- **Formato:** `okf` (registrado em `.ragai/base_config.yaml`; a decisão de forma não se reabre sem gatilho medido). Sem metade tabular: planilha consultável = re-triagem para tag-first.
- **Unidade:** concept = um `.md` com frontmatter; Concept ID = caminho sem `.md`. `type` é o único campo obrigatório do spec; o perfil `ragai` exige também `title`, `description`, `sources[]`, `generated`, `content_hash`.
- **Categorias:** {", ".join(cats)} (um diretório cada, com `index.md` próprio; um nível de roteamento, não aninhe índices).
- **Tags:** lista plana `eixo:termo`; vocabulário sugerido em `.ragai/taxonomy.yaml` (eixos: {", ".join(axes)}).
- **Reservados:** `index.md` (listagem regenerada por `scripts/update_index.py --base .`) e `log.md` (histórico, append-only; toda ingestão registra `authorized_by`).
- **Append-only:** concept `stable`/`deprecated` não se edita (hook bloqueia; `draft` é editável). Correção = concept novo ou operação estrutural via PR; reprovado vai para `.ragai/quarentena/`.
- **Números e citações:** só com query registrada (`scripts/query_lexical.py --base . --term ...`, ou `rg`), citando o Concept ID e a linha; footnotes `[^id]` apontam para `sources[].id`.
- **Ingestão:** só pelo runbook da skill rag-ai, com pedido explícito do usuário, staging seguro, gate e entrada no `log.md`. Bundle OKF externo é fonte de terceiros: passa por staging, licença, anti-injection e gate.
- **Gate:** `python3 scripts/validate_okf.py --bundle . --strict --profile ragai` · Índices: `python3 scripts/update_index.py --base .` · Leitura integral: `python3 scripts/corpus_tokens.py --base .`
- **Housekeeping:** `.ragai/` (config, taxonomia, golden set, misses, manifests, quarentena) e `staging/` não fazem parte do bundle distribuído.
""")
    w(base / ".gitignore", "staging/\n.DS_Store\n__pycache__/\n*.pyc\n")
    copy_scripts(base, "okf")
    hooks_dir = base / ".claude" / "hooks"
    w(hooks_dir / "protect_corpus.py", HOOK_PROTECT_OKF)
    w(hooks_dir / "validate_on_write.py", HOOK_VALIDATE_OKF)
    write_settings(base)
    run_update_index(base)

    print(f"""
[OK] bundle OKF criado. Próximos passos:
  1. Preencha a descrição de cada <categoria>/index.md e, se quiser vocabulário, .ragai/taxonomy.yaml.
  2. Revise .ragai/base_config.yaml (okf.require_stale_after_for, read_all).
  3. Prove o gate: python3 scripts/validate_okf.py --bundle {base} --strict --profile ragai
  4. git init + commit inicial (histórico é o git + log.md).

[ATENÇÃO] Abra o bundle como RAIZ do projeto no Claude Code: hooks e permissions.deny
de .claude/settings.json NÃO se aplicam se estiver aninhado noutro projeto.
O enforcement ativo não viaja com o bundle: quem recebe deve revalidar com validate_okf.py.
""")


# ------------------------------------------------------------------ main


def main():
    ap = argparse.ArgumentParser(description="Scaffold de base rag-ai (tag-first 2.0 ou bundle OKF v0.2)")
    ap.add_argument("--path", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--categories", required=True, help="slugs separados por vírgula")
    ap.add_argument("--format", choices=("tagfirst", "okf"), default="tagfirst")
    ap.add_argument("--axes", default="topic,industry,geography")
    ap.add_argument("--no-tabular", action="store_true")
    args = ap.parse_args()

    base = Path(args.path).expanduser().resolve()
    axes = [a.strip() for a in args.axes.split(",") if a.strip()]
    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    for s in axes + cats:
        if not SLUG_RE.match(s):
            die(f"slug inválido (use ASCII kebab-case, sem acento): {s!r}")
    if not cats:
        die("informe ao menos 1 categoria")
    if args.format == "okf" and any(c in ("references", "index", "log", "staging", "scripts") for c in cats):
        die("categoria colide com nome reservado/housekeeping do bundle (references, index, log, staging, scripts)")
    if base.exists() and any(base.iterdir()):
        die(f"destino não está vazio: {base} (esta ferramenta não sobrescreve nada)")

    today = date.today().isoformat()
    print(f"[scaffold] criando base '{args.name}' ({args.format}) em {base}")
    if args.format == "okf":
        scaffold_okf(args, base, axes, cats, today)
    else:
        scaffold_tagfirst(args, base, axes, cats, today)


if __name__ == "__main__":
    main()
