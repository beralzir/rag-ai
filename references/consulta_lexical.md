# Consulta lexical registrada (`rg` / `pdfgrep`)

Modo de consulta de primeira classe da skill, ao lado do corte por tags e da leitura integral. A ideia é a do próprio Claude Code: **o modelo dirige `grep`**, e o comando executado **é** a query registrada que acompanha o número ou a citação. Evidência: em documentos financeiros com texto + tabela, BM25 supera dense retrieval e expansão de query pouco ajuda em consulta numérica (arXiv 2604.01733); agente com `rga`/`pdfgrep` atingiu ~94% da fidelidade de um RAG e venceu no FinanceBench (Amazon, AAAI 2026); Boris Cherny: "glob e grep dirigidos pelo modelo venceram tudo" (Pragmatic Engineer, 2026-03). Custo: zero índice, zero staleness.

## Quando usar

- Qualquer **número, cifra, percentual, nome próprio, data, identificador** ("quanto foi o investimento em CTV segundo o relatório X?").
- "**Onde diz que…**": localizar a unidade e a linha exata para citar.
- Primeiro modo em corpus **numérico/financeiro** (planos de mídia, relatórios de mercado): tags acham o subconjunto, lexical acha o valor.
- Cross-check antes de citar: o número que você vai escrever aparece literalmente na unidade? Se não, é inferência sua, e deve ser dita como tal.

Não substitui: SQL/pandas para número da metade tabular (continua obrigatório, com a query transcrita); leitura integral para síntese global (`leitura_integral.md`).

## Protocolo (4 passos)

1. **Expanda o termo** em PT e EN, com e sem acento, e nos formatos numéricos possíveis. Fonte da expansão: `labels`/`aliases` da taxonomia (`_meta/taxonomy.yaml` ou `.ragai/taxonomy.yaml`), ou o `index.md` do bundle. `scripts/query_lexical.py --base . --term <id> [--no-accents]` faz isso e imprime o comando exato. Exemplos de alternation: `ctv|TV conectada|Connected TV|smart tv`; `1\.234,56|1,234\.56|1 234`; `12 ?%`.
2. **Rode e registre o comando.** Sobre a base: `rg -n -i -e '<alt>' --glob '*.md' corpus/` (tag-first) ou `rg -n -i -e '<alt>' --glob '*.md' .` (bundle; `rg` pula dotdirs, logo `.ragai/` fica fora). Sobre o bruto em staging: `pdfgrep -n -i -e '<alt>' staging/<arquivo>.pdf` (`-n` dá a **página**). `rg` não faz folding de acento: a expansão é sua (`--no-accents` no script gera as classes).
3. **Leia os hits em contexto** (`-C 3`) antes de responder. Hit no frontmatter (tag, `context`) localiza a unidade; hit no corpo sustenta a afirmação.
4. **Responda com a query registrada**: o comando exato + as linhas de hit, colados no bloco de resposta, e o localizador de cada afirmação.

## Localizadores

| Onde | Formato | Exemplo |
|---|---|---|
| chunk tag-first | `chunk_id:L<n>` | `midia-digital-0007:L14` |
| concept OKF | `<concept-id>#L<n>` | `midia/ctv-0001#L13` |
| PDF em staging (com `pdfgrep`) | `arquivo.pdf#p.N` | `estudo_2026.pdf#p.41` |
| PDF sem `pdfgrep` | texto canônico do staging com marcador de página (`pdftotext -layout` separa páginas por form feed; conte-os) ou declare **"sem localizador de página"** | `estudo_2026.txt#p.~41` |

`pdfgrep` e `rga` **não são dependências**: quando ausentes, o script só sugere o comando e você usa o texto canônico já gerado na Fase 1 do runbook. Nunca invente página.

## Regras

- **Nenhum número sem hit.** Zero hits → não há número. Busca legítima sem resultado → registre em `_meta/search_misses.md` (ou `.ragai/search_misses.md`): data, consulta, o que esperava. É insumo do golden set e gatilho de aliases.
- **O comando é parte da resposta**, não bastidor. Sem ele, o número é memória do modelo, e memória do modelo não é fonte.
- `valid_until`/`stale_after` vencido entra com aviso explícito, como em qualquer modo.
- Citação literal de fonte licenciada continua sob o teto por entregável (`security_licensing.md`); lexical facilita achar, não libera reproduzir.
- Deny de rede continua valendo durante a consulta: `rg` é local.

## Exemplo de bloco de resposta

```
Investimento em CTV 2026: R$ 1,2 bi (Instituto Exemplo, medido, publicado 2026-03).
[QUERY] cd ~/bases/midia && rg -n -i -e 'ctv|TV conectada|Connected TV' --glob '*.md' corpus/
midia-digital-0007 · corpus/midia-digital/midia-digital-0007.md:16 · … investimento em CTV somou R$ 1,2 bilhão em 2026 …
Localizador: midia-digital-0007:L16 (evidence_locator p. 41).
```
