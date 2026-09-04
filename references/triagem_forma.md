# Passo 0: triagem de forma (tag-first, OKF, os dois, ou nenhum)

Antes de criar qualquer base, a skill decide **a forma** do conhecimento. Não é cerimônia: escolher errado custa a base inteira (schema, gate, hooks, taxonomia). Escolher certo custa cinco perguntas.

## Regra de entrada: decisão registrada não se reabre

Se `_meta/base_config.yaml` (tag-first) ou `.ragai/base_config.yaml` (OKF) já tem `format:`, **siga o formato registrado** e não rode a triagem de novo. Re-triagem só sob gatilho medido do fluxo D (ex.: bundle OKF que passou a precisar de planilha consultável; base tag-first que virou material leve de distribuição) e via operação estrutural (proposta → aprovação → PR), nunca porque a conversa reabriu o assunto.

## As cinco perguntas (só o que muda a decisão)

| # | Pergunta | O que ela decide |
|---|---|---|
| Q1 | Há unidades que exigem **auditabilidade mecânica**: número que não pode ser alucinado, forecast que expira, fonte paga/licenciada (GWI, eMarketer, Kantar)? | governança por unidade (licença, `valid_until`, proveniência medido-vs-modelado) |
| Q2 | Há **planilhas** que precisam ser consultadas por número (planos de mídia, orçamentos, séries)? | metade tabular com SQL; OKF não tem lar para isso |
| Q3 | O requisito dominante é **distribuir/compartilhar** entre pessoas, times ou ferramentas, ou há **escrita concorrente** por equipe? | interop e multiusuário são forças do OKF (git merge/PR) |
| Q4 | **Tamanho e churn**: quantos documentos/páginas hoje e em 12 meses; muda toda semana ou é estável? | limiares de escala e leitura integral |
| Q5 | Quem é o **dono** da base? | sem dono claro = fora de escopo (já era) |

Respostas objetivas (sim/não/parcial, um número) bastam. Se o usuário não sabe responder Q1 ou Q2, a resposta operacional é "não, por enquanto": a forma leve pode subir para tag-first depois; o contrário desperdiça governança.

## Tabela de decisão

| Sinais | Forma | Registro |
|---|---|---|
| Q1 sim **ou** Q2 sim (qualquer unidade governada), Q3 não | **tag-first** | `format: tagfirst` em `_meta/base_config.yaml` |
| Q1 não, Q2 não, Q3 sim; corpus estável, curado, até ~100 documentos | **OKF** (bundle nativo) | `format: okf` em `.ragai/base_config.yaml` + `okf_version: "0.2"` no `index.md` raiz + 1ª entrada do `log.md` |
| Q1 ou Q2 sim **e** Q3 sim | **tag-first na origem + export OKF** (fluxo F) | `format: tagfirst` + bloco `okf_export:` no config |
| Q1 não, Q2 não, Q3 não (notas, rascunhos, uso pessoal) | **nenhum dos dois**: "peso demais"; pasta + git resolve | não cria base |
| Q4 acima de ~1.000 documentos heterogêneos com churn semanal, ou recall por conceito que aliases não resolvem | **vector store: mostrar a trilha** (`audit_eval.md` §4); começar tag-first ou OKF e **medir** antes de subir | `format:` conforme Q1-Q3 + nota "degrau 4 provável" no log |

**Desempate (teste operacional):** pergunte do corpo de conhecimento: *"ele exige auditabilidade mecânica por unidade (proveniência medido-vs-modelado, validade temporal, licença governada, números reproduzíveis por query registrada)?"* Sim → tag-first. Não, e o requisito dominante é distribuir hoje, ou é conhecimento leve, ou precisa de escrita concorrente → OKF. Os dois → tag-first na origem, OKF como camada de export (composição de mão única: o tag-first serializa sobre OKF; o OKF não adota tag-first).

## Limiares publicados que sustentam a tabela

Marcação epistemológica: **fato** = lido na fonte citada; **inferência** = leitura da skill sobre os fatos. Nenhum limiar abaixo é do Google (o spec OKF não publica guia de tamanho); são de terceiros e da Anthropic.

- **Corpus pequeno e curado favorece o padrão wiki/OKF**: guias de 2026 convergem em "< ~100 documentos bem delimitados = wiki; 100-1.000 = qualquer um; > 1.000 = RAG vetorial" (MindStudio, "LLM Wiki vs RAG", 2026-04, atualizado 2026-07) [fato]. Karpathy: o `index.md` funciona "em escala moderada (~100 fontes, centenas de páginas)" antes de precisar de busca embutida (gist "LLM Wiki", 2026-04-04) [fato].
- **Um nível de roteamento basta**: "um segundo nível de roteamento mais profundo nunca ajuda e às vezes quebra a acurácia" (arXiv 2607.17598, 2026-07) [fato]. Por isso tag-first mantém índice-mestre + tags, e o bundle OKF mantém `index.md` por diretório sem aninhar índices [inferência].
- **Leitura integral quando cabe**: Anthropic, "Contextual Retrieval" (2024-09): abaixo de ~200k tokens (~500 páginas), coloque a base inteira no prompt em vez de RAG [fato]; janela de 1M tokens sem prêmio de preço em Opus/Sonnet 4.6 desde 2026-03 [fato]. Contra-evidência: RAG vetorial com contexto de 1M ainda perde para LazyGraphRAG em perguntas globais (BenchmarkQED, Microsoft) [fato]; logo, leitura integral resolve síntese em corpus pequeno, não substitui estrutura em corpus grande [inferência]. Detalhe operacional em `leitura_integral.md`.
- **Lexical vence em número e identificador**: em documentos financeiros com texto + tabela, "BM25 supera dense retrieval de última geração"; expansão de query "traz benefício limitado para consultas numéricas precisas" (arXiv 2604.01733, 2026-04) [fato]. Anthropic: BM25 vence em "identificadores únicos ou termos técnicos" [fato]. Agente com `rga`/`pdfgrep` atingiu ~94% da fidelidade de um RAG e **venceu** o RAG no FinanceBench (Amazon, AAAI 2026, arXiv 2602.23368) [fato]. O próprio Claude Code padronizou em glob + grep dirigidos pelo modelo (entrevista Boris Cherny, Pragmatic Engineer, 2026-03) [fato]. Detalhe em `consulta_lexical.md`.
- **Grafos e embeddings ficam como degrau**: GraphRAG/LightRAG/HippoRAG/RAPTOR exigem extração por LLM + índice vetorial ou grafo [fato]; ganham em agregação multi-fato e perdem "detalhe fino" (WildGraphBench, arXiv 2602.02053) [fato]. Camada compilada tipo LLM-wiki (páginas de tema + lint) é o degrau intermediário documentado em `audit_eval.md`, não ponto de partida [inferência].

## OKF: o que a análise de julho de 2026 dizia, e o que mudou

A comparação interna "OKF × tag-first" (2026-07-05) foi feita contra o **OKF v0.1**. O **v0.2 (2026-07-24)** acrescentou trust signals: `sources[]` (proveniência por documento, footnotes por afirmação), `generated`/`verified` (tier de confiança derivado), `stale_after` (validade absoluta), `status` (`draft|stable|deprecated`) e Attested Computation (número que o agente não pode editar, só parametrizar).

**Envelheceu:** "OKF só tem `timestamp`, sem proveniência nem validade temporal". Falso no v0.2.

**Continua verdadeiro:** o OKF não tem gate falha-fechada (conformance é sintática: frontmatter parseável + `type` + reservados bem formados; consumidores **devem tolerar** campo faltando, tipo desconhecido, link quebrado), não tem vocabulário controlado, não tem licença/TDM por unidade, não tem metade tabular consultável por SQL, não tem invariante anti-injection, não tem controle de acesso. É por isso que Q1 e Q2 mandam para tag-first: não é preferência, é ausência de lar para o campo.

## Roteiro anti-capitulação

Quando o usuário insiste em OKF para material governado ("é mais simples", "só dessa vez", "a gente paga a eMarketer mas quero em OKF"):

1. Nomeie o campo sem lar: "`tdm_ai_clause`, `consent_ref` e `permitted_use` não têm onde ser exigidos num bundle OKF; o validador de conformance aceita o bundle sem eles. `stale_after` existe, mas nenhum consumidor OKF é obrigado a respeitar."
2. Nomeie a consequência: "o teto de citação por entregável da eMarketer e o consentimento por escrito da GWI ficam sem enforcement; quem receber o bundle vai superestimar a garantia."
3. Ofereça o caminho que resolve o pedido real: **tag-first na origem + export OKF** (fluxo F). O compartilhamento acontece; a governança fica onde funciona; o bundle sai com o aviso de que o enforcement ativo não viaja.
4. Na segunda insistência, repita 1-3 sem ceder. Reverificar a licença é válido; trocar de formato para escapar de um campo obrigatório, não (regra default 5 da skill).
