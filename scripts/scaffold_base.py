#!/usr/bin/env python3
"""scaffold_base: cria uma base de conhecimento tag-first 2.0 (skill rag-ai).

Gera a estrutura completa (corpus, tabular, _meta, staging), os configs em
YAML restrito, copia os scripts operacionais para dentro da base
(autossuficiência) e instala os hooks de proteção append-only no `.claude/`
da base. Recusa destino não-vazio (append-only começa aqui).

Uso:
  python3 scaffold_base.py --path <destino> --name "Minha Base" \
      --categories "midia-digital,consumo,macro" \
      [--axes "topic,industry,geography"] [--no-tabular]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent
SKILL_VERSION = "0.1.0"
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def die(msg: str):
    print(f"[FATAL] {msg}")
    sys.exit(2)


def w(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  + {path}")


def main():
    ap = argparse.ArgumentParser(description="Scaffold de base tag-first 2.0")
    ap.add_argument("--path", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--categories", required=True, help="slugs separados por vírgula")
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
    if base.exists() and any(base.iterdir()):
        die(f"destino não está vazio: {base} (esta ferramenta não sobrescreve nada)")

    today = date.today().isoformat()
    print(f"[scaffold] criando base '{args.name}' em {base}")

    # -------------------------------------------------- estrutura física
    for cat in cats:
        (base / "corpus" / cat).mkdir(parents=True, exist_ok=True)
    (base / "corpus" / "_quarentena").mkdir(parents=True, exist_ok=True)
    (base / "staging").mkdir(parents=True, exist_ok=True)
    (base / "_meta" / "manifests").mkdir(parents=True, exist_ok=True)
    if not args.no_tabular:
        for d in ("raw", "mappings", "canonical", "_quarentena"):
            (base / "tabular" / d).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- configs
    axes_inline = "[" + ", ".join(axes) + "]"
    cats_inline = "[" + ", ".join(cats) + "]"
    w(base / "_meta" / "base_config.yaml", f"""# Config da base (YAML restrito; ver skill rag-ai)
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
""")

    tax_lines = [f"# Taxonomia da base (fonte única de termos válidos)", f"axes: {axes_inline}", ""]
    for ax in axes:
        tax_lines.append(f"{ax}:")
        tax_lines.append(f"  # - id: exemplo-{ax}")
        tax_lines.append('  #   label_pt: "exemplo"')
        tax_lines.append('  #   label_en: "example"')
        tax_lines.append("  #   aliases: []")
        tax_lines.append('  #   scope_note: "quando usar; quando NÃO usar"')
        tax_lines.append("  #   status: ativo")
        tax_lines.append("")
    w(base / "_meta" / "taxonomy.yaml", "\n".join(tax_lines))

    w(base / "_meta" / "source_mapping.yaml", """# Fonte única de roteamento: toda fonte ingerida tem entrada aqui
sources:
#  - source: "Nome Canônico do Documento"
#    source_file: "arquivo_original.pdf"
#    category: slug-da-categoria
#    access_basis: publico          # assinatura | compra | publico
#    licensor: ""
#    tags:
#      topic: []
""")

    w(base / "_meta" / "TAXONOMY_CHANGELOG.md",
      f"# Changelog da taxonomia\n\n- {today} · base criada; taxonomia inicial vazia (termos entram com chunk-proof).\n")
    w(base / "_meta" / "golden_set.md", """# Golden set: perguntas de avaliação

20-30 perguntas estratégicas reais; formato em references/audit_eval.md da skill rag-ai.

## Rodadas
| data | score | notas |
| --- | --- | --- |
""")
    w(base / "_meta" / "reingestion_queue.md", "# Fila de reingestão (PDFs sem texto extraível, re-OCR pendente)\n")
    w(base / "_meta" / "search_misses.md", "# Misses de busca (consulta legítima que não achou nada)\n\n| data | consulta | esperava |\n| --- | --- | --- |\n")

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

    # ------------------------------------------------------------ docs
    # CLAUDE.md (não BASE.md): o Claude Code autocarrega este arquivo quando a
    # base é aberta como raiz do projeto; é assim que os fatos entram na sessão.
    w(base / "CLAUDE.md", f"""# {args.name}

Base de conhecimento **tag-first 2.0** (criada pela skill rag-ai v{SKILL_VERSION} em {today}). Fatos permanentes:

- **Eixos de tags:** {", ".join(axes)} · vocabulário único em `_meta/taxonomy.yaml` (tag fora dele não passa no gate).
- **Categorias (home físico apenas):** {", ".join(cats)} · descoberta é por TAGS, não por pasta.
- **Duas metades:** chunks narrativos em `corpus/`; dados tabulares em `tabular/canonical/` (planilha nunca vira chunk).
- **Append-only:** chunk validado não se edita (hooks bloqueiam); correção = quarentena ou operação estrutural via PR.
- **Números:** só de consulta executada (SQL/pandas), com a query registrada junto do resultado.
- **Ingestão:** só pelo runbook da skill rag-ai, com pedido explícito do usuário (registrado como `authorized_by` no manifest), staging seguro, gate estrito e manifest por lote.
- **Consulta:** corte por tags no frontmatter → expandir em PT+EN via labels/aliases da taxonomia → ler e citar `chunk_id`; número tabular só via SQL/pandas com a query na resposta; `valid_until` vencido entra com aviso; busca sem resultado → registrar em `_meta/search_misses.md`.
- **Gate:** `python3 scripts/validate_base.py --base . --strict` · Índice: `python3 scripts/update_index.py --base .`
- **Estado vivo:** contagens em `index.md`; manifests em `_meta/manifests/`; pendências em `_meta/reingestion_queue.md`.
""")

    w(base / "index.md", f"""# {args.name}: índice mestre

<!-- rag-ai:status:begin -->
_Rode `python3 scripts/update_index.py --base .` após cada ingestão._
<!-- rag-ai:status:end -->

## Categorias (escopo e fontes-chave)

{chr(10).join(f"### {c}" + chr(10) + "**Escopo:** (preencher)" + chr(10) for c in cats)}
""")

    w(base / ".gitignore", "staging/\n.DS_Store\n")

    # -------------------------------------------------- scripts na base
    (base / "scripts").mkdir(exist_ok=True)
    for s in ("ragai_lib.py", "validate_base.py", "update_index.py"):
        src = SKILL_SCRIPTS / s
        if not src.exists():
            die(f"script da skill não encontrado: {src}")
        shutil.copy2(src, base / "scripts" / s)
        print(f"  + {base / 'scripts' / s} (cópia; base autossuficiente)")

    # ------------------------------------------------------------ hooks
    hooks_dir = base / ".claude" / "hooks"
    w(hooks_dir / "protect_corpus.py", '''#!/usr/bin/env python3
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
''')

    w(hooks_dir / "validate_on_write.py", '''#!/usr/bin/env python3
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
''')

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

    print(f"""
[OK] base criada. Próximos passos:
  1. Preencha _meta/taxonomy.yaml (termos com chunk-proof; labels PT/EN + aliases).
  2. Revise _meta/base_config.yaml (require_valid_until_for, lists).
  3. Prove o gate: python3 scripts/validate_base.py --base {base} --strict
  4. git init + commit inicial (mudanças estruturais futuras via PR).

[ATENÇÃO] Abra a base como RAIZ do projeto no Claude Code: hooks e permissions.deny
de .claude/settings.json NÃO se aplicam se a base estiver aninhada noutro projeto.
Append-only via hook cobre as ferramentas Edit/Write; nunca crie/mova chunk via Bash.
""")


if __name__ == "__main__":
    main()
