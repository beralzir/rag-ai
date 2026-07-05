# Auditoria e avaliação contínua (fluxo D)

"Está funcionando" é medição, não sensação. Dois instrumentos: o gate (integridade) e o golden set (qualidade de recuperação). A auditoria roda a cada ~5 ingestões ou trimestralmente, e sempre antes de decisão de escala.

## 1. Integridade (mecânica)

```bash
python3 scripts/validate_base.py --base <base> --strict     # corpus + taxonomia (+ --tabular p/ CSVs)
python3 scripts/update_index.py --base <base> --check       # contagens do index batem com o filesystem?
```

## 2. Saúde e cobertura (varreduras)

- **Vencidos**: chunks com `valid_until` no passado e `status: validated` → listar para revalidar ou arquivar.
- **Tags deprecadas em uso** em chunks novos; **aliases ambíguos**; **termos ativos com 0 chunks** (taxonomia inflada).
- **Licença**: fontes pagas sem `tdm_ai_clause`/`review_date`; `consent_required` sem `consent_ref`.
- **Autorização**: todo manifest em `_meta/manifests/` tem `authorized_by` (data + frase do pedido)? Manifest sem isso = ingestão sem trilha de autorização = falha média.
- **Drift de scripts**: `created_by` em `base_config.yaml` vs versão atual da skill; se a skill evoluiu, comparar `scripts/` da base com os da skill e propor atualização via PR.
- **Quarentenas**: itens acumulando em `corpus/_quarentena/`, `tabular/_quarentena/` e fila de reingestão → é o gatilho do degrau 3 (extração assistida por serviço).
- **Misses**: `_meta/search_misses.md` com padrões repetidos → aliases novos ou candidato a termo.

## 3. Golden set (qualidade de recuperação)

`_meta/golden_set.md`: 20-30 perguntas ESTRATÉGICAS reais (piso de arranque: 5-10 no começo; 20-30 é o alvo maduro), cada uma com resposta esperada e chunk_ids/queries que a sustentam.

```markdown
## P07
pergunta: "Qual a tendência de investimento em CTV no Brasil para 2026-2027 e quem mediu?"
espera_chunks: [ctv-streaming-0121, ctv-streaming-0134]
espera_query: nenhuma
resposta_esperada: "síntese com dado medido do Instituto X, valid_until 2027-06"
```

Rodada de avaliação (você como juiz, honesto):
1. Para cada pergunta, execute a recuperação como o agente faria (tags → grep bilíngue → leitura).
2. Marque: **recall** (achou os chunks esperados?), **precisão** (trouxe lixo junto?), **fidelidade** (a resposta usa só o que os chunks sustentam? números vieram de query?).
3. Score da rodada = % de perguntas plenamente atendidas. Registre no próprio arquivo (tabela de rodadas com data) e compare com a anterior.

## 4. Gatilhos de escala (decisão objetiva)

| Sinal medido | Degrau a considerar |
|---|---|
| Perguntas de síntese global falhando no golden set | 1 · catálogos e sumários por lote |
| Grep exigindo muitas iterações / latência incômoda | 2 · índice lexical local (FTS5, com folding de acentos) |
| Quarentena de extração/gráficos acumulando | 3 · re-OCR e extração de gráficos via serviço |
| Recall caindo em consultas por conceito que aliases não resolvem | 4 · busca híbrida (embeddings contextualizados + BM25 + reranker) |
| Virou produto multiusuário com equipe dev | 5 · framework de orquestração (decisão da equipe) |

Regra: sobe-se UM degrau por vez, preservando as 14 invariantes. Sem gatilho medido, não se sobe.

## 5. Relatório de auditoria (formato)

1. **Diagnóstico**: gate (saída citada), varreduras, score do golden set vs rodada anterior.
2. **Falhas por severidade**: crítica (corrompe confiança: hash divergente, licença violada) · média (degrada recuperação: aliases faltando, vencidos ativos) · cosmética.
3. **Riscos**: o que acontece se nada for feito.
4. **Correções priorizadas**: ação, esforço, responsável (script vs humano).
5. **Gatilho de escala**: atingido ou não, com o número que sustenta.
