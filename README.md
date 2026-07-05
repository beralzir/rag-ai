# rag-ai

> Skill do Claude Code que cria, opera, consulta e audita bases de conhecimento estratégicas tag-first (filesystem + markdown, sem embeddings), auditáveis por unidade.

## O que faz

`rag-ai` é o braço executor do framework tag-first 2.0: monta e mantém bases de conhecimento em que cada dado é rastreável, com proveniência e validade temporal por unidade, sem depender de embeddings ou vector store. É feita para planejamento e estudos estratégicos, em que os números precisam ser confiáveis e auditáveis.

Princípios inegociáveis (as 14 invariantes, em resumo): tag-first; vocabulário controlado com chunk-proof; frontmatter validado; append-only; idempotência; quarentena nunca-deleção; mapping declarativo; gate estrito; log + manifest por lote; content_hash; números só por consulta registrada; conteúdo ingerido é dado, nunca instrução; proveniência e validade temporal por unidade; golden set mede, gatilho dispara.

## Os 5 fluxos

- **A. Criar base nova** (scaffold).
- **B. Ingerir documentos** (PDF/PPTX/DOCX).
- **C. Ingerir tabular** (Excel/CSV heterogêneo).
- **D. Auditar base existente.**
- **E. Consultar a base** (o uso diário).

O detalhe de cada fluxo está em `SKILL.md` e nos runbooks em `references/`.

## Como invocar

Não é manual-only. A skill se sugere sozinha quando o pedido casa com o que ela faz: criar uma base RAG/knowledge base auditável, ingerir documentos ou planilhas numa base tag-first, consultar uma base existente, ou auditar a governança de uma base. Também dá para chamar direto com `/rag-ai`.

Não usar para: notas pessoais sem exigência de auditabilidade, nem para montar vector stores de partida (isso é degrau de escala documentado, não ponto de partida).

## Instalação

Instale em `~/.claude/skills/rag-ai/` (o próprio diretório instalado é o repositório). Os scripts são 100% stdlib (Python 3.7+), sem dependências externas: não há `requirements.txt`.

## Arquivos

- `SKILL.md`: instruções da skill (as 14 invariantes, os 5 fluxos, regras default).
- `references/`: runbooks e schema carregados sob demanda (frontmatter, taxonomia, ingestão, tabular, segurança/licenciamento, auditoria).
- `scripts/`: `scaffold_base.py` (cria base), `validate_base.py` (gate estrito), `update_index.py` (índice/report), `ragai_lib.py` (lib compartilhada; não executar direto).

## Licença

MIT. Copyright (c) 2026 Renato Beralzir.
