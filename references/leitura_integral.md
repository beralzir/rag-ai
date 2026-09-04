# Leitura integral do corpus (gate por tokens)

Terceiro modo de consulta: quando o corpus **cabe** no contexto, ler tudo é mais fiel e mais barato do que montar estrutura para síntese. Anthropic ("Contextual Retrieval", 2024-09): abaixo de ~200k tokens (~500 páginas), inclua a base inteira no prompt em vez de RAG; desde 2026-03 a janela de 1M tokens não tem prêmio de preço em Opus/Sonnet 4.6. Prompt caching torna a releitura repetida barata (até 90% de redução de custo declarada pela Anthropic). Contra-evidência a respeitar: em corpus grande, contexto longo não substitui estrutura para perguntas globais (BenchmarkQED); por isso o gate.

## O gate

```bash
python3 scripts/corpus_tokens.py --base <dir> [--include cat1,cat2] [--exclude cat3] [--max-tokens N] [--json]
```

- Estima tokens com heurística stdlib: `chars / 3.2` (+25 tokens de envelope por arquivo). O fator 3.2 é **conservador para PT-BR** (acentos, frontmatter YAML e slugs tokenizam mais denso que prosa em inglês, onde a régua é ~4); superestimar é o erro barato. Ajuste em `base_config.yaml: read_all.chars_per_token`.
- Compara com `read_all.max_tokens` (default **150000**: 200k de orientação menos folga para system prompt, skill, pergunta e resposta). Janela de 1M é decisão deliberada no config, nunca "sensação de que cabe".
- Imprime chars e estimativa (dá para rederivar com outro fator), tabela por categoria, **ordem de leitura determinística** (categorias na ordem do config, chunks por sufixo numérico; no bundle, reservados e concepts por caminho) e o veredito `LEITURA_INTEGRAL: ok|excede` (exit 0/1).

## Quando usar

- Pergunta **global ou de síntese**: "o que a base diz, no geral, sobre X?", "quais temas se repetem nos planos de 2026?", "compare o que as fontes A e B dizem".
- Golden set falhando em perguntas de **síntese global** (é o sinal do degrau 1 em `audit_eval.md`; leitura integral vem **antes** de construir catálogos/sumários derivados).
- Corpus sob o gate e pergunta que exige cruzar muitas unidades.

## Quando NÃO usar

- Número, cifra, citação exata: **consulta lexical** (`consulta_lexical.md`) ou SQL na metade tabular. Ler tudo para achar um número é caro e menos verificável.
- Corpus **acima do gate**: diga que não cabe, use `--include` para um subconjunto por categoria, ou caia para tags + lexical. Nunca "leia o que der".
- Entregável externo com muita fonte licenciada: o teto de citação literal por entregável continua valendo sobre a saída; ler tudo não muda isso.

## Como fazer (protocolo)

1. Rode o gate; cole a linha `LEITURA_INTEGRAL: ok (N <= M)` na resposta: ela é a query registrada deste modo.
2. Leia os arquivos **na ordem impressa**, cada um envolvido assim (é a prática recomendada pela Anthropic para contexto longo; a ordem fixa também maximiza reuso de prefixo no cache):
   ```
   <document index="1"><source>corpus/consumo/consumo-0001.md</source><document_content>…</document_content></document>
   ```
   No bundle OKF, `source` = Concept ID.
3. **Cite primeiro, sintetize depois**: antes da resposta, liste as citações relevantes com `<source>` (chunk_id ou Concept ID); só então escreva a síntese, usando **apenas** o que as citações sustentam. Unidade com `valid_until`/`stale_after` vencido entra com o aviso.
4. Número que aparecer na síntese: confirme com lexical ou SQL antes de escrever (a leitura integral acha o tema; o número pede o comando).
5. Registre no fim da resposta: modo (leitura integral), estimativa de tokens, categorias incluídas/excluídas.

## Nota sobre cache

Prompt caching é comportamento da API, não algo que a skill controla: a ordem determinística e o envelope fixo tornam o prefixo estável entre perguntas da mesma sessão, o que é a condição para o cache reutilizar. Trate como prática, não como garantia; não prometa custo.

## Relação com os degraus de escala

Leitura integral é o **degrau zero** de síntese: barato, sem artefato derivado, sem manutenção. Só quando ela **estoura o gate** e o golden set continua falhando em síntese é que faz sentido a camada compilada tipo LLM-wiki (páginas de tema/entidade + lint), documentada como futuro em `audit_eval.md`. GraphRAG e embeddings continuam no degrau 4.
