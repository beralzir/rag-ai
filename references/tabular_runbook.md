# Runbook de ingestão: tabular (Excel/CSV heterogêneo)

Fluxo C da skill. Princípio: **planilha é banco de dados mal formatado, não documento**. Nunca chunkear; normalizar na ingestão e consultar por SQL/script. Caso típico: planos de mídia de fornecedores diferentes (layouts distintos) → tabela canônica única.

## Estrutura na base

```
tabular/
├── raw/                      # arquivos brutos, retidos para sempre (reprocesso/auditoria)
├── mappings/                 # mapping_<fornecedor>.yaml (de-para aprovado)
├── canonical/                # tabelas canônicas (CSV; Parquet quando o volume pedir)
└── dictionary.yaml           # dicionário de dados: o contrato do schema canônico
```

## Dicionário de dados (o contrato)

```yaml
# tabular/dictionary.yaml: exemplo para planos de mídia
table: planos_midia
grain: "uma linha = um investimento de um veículo numa praça num período"
columns:
  - name: grupo
    type: string
    required: true
    enum_from: grupos            # lista controlada em base_config.yaml (ex.: groupm, publicis, dentsu)
  - name: veiculo
    type: string
    required: true
  - name: praca
    type: string
    required: true
    enum_from: pracas
  - name: periodo_inicio
    type: date
    required: true
  - name: periodo_fim
    type: date
    required: true
  - name: investimento
    type: number
    required: true
    min: 0
    note: "sempre líquido, BRL; conversões declaradas no mapping"
  - name: formato
    type: string
    required: false
lineage:
  - name: fonte_arquivo        # colunas de linhagem: obrigatórias em toda tabela canônica
    type: string
    required: true
  - name: lote
    type: string
    required: true
  - name: linha_origem
    type: string
    required: true             # ex.: "Plan!B14" (aba!célula da primeira célula da linha)
```

Semântica mora AQUI (bruto vs líquido, moeda, granularidade), nunca improvisada na consulta.

**Vários grãos, várias tabelas:** quando a base tem mais de um tipo de dado tabular (ex.: PIs pendentes, controle de faturamento e linhas de plano são grãos DIFERENTES), não force uma tabela só. Use o formato multi-tabela: `tables:` como lista de entradas `{table, grain, columns, lineage}`, e cada CSV canônico se chama `<table>.csv` (o gate casa pelo nome e reprova CSV sem tabela declarada).

## Fluxo

1. **Staging**: arquivo bruto para `tabular/raw/` (retido). Fonte nova sem licença checada → `security_licensing.md` primeiro.
2. **De-para (única etapa com LLM)**: leia headers + 5-10 linhas de amostra de cada aba; proponha o mapeamento coluna-origem → coluna-canônica, com transformações explícitas (unpivot de meses em colunas, split de células compostas, conversão de moeda/percentual, tratamento de subtotais: EXCLUIR linhas de subtotal, nunca somar junto). Apresente ao usuário como YAML legível.
3. **Aprovação humana**: o usuário aprova/edita; salve `mapping_<fornecedor>.yaml`. Lotes futuros do mesmo fornecedor reusam SEM nova proposta (mudou o layout → nova versão do mapping, changelog).
4. **Conversão por script estável**: escreva (uma vez) `scripts/convert_<fornecedor>.py` na base usando pandas/openpyxl, que aplica o mapping e emite CSV no schema do dicionário + colunas de linhagem. Sem LLM no caminho crítico: lote novo = rodar script.
5. **Scrub LGPD**: colunas de contato (nome/e-mail/telefone) são removidas na conversão; registre no log que houve scrub.
6. **Validação declarativa**: `python3 scripts/validate_base.py --base <base> --tabular --strict` valida o CSV contra `dictionary.yaml` (tipos, required, enum, min/max) com relatório AGREGADO de erros; lote reprovado → `tabular/_quarentena/` + relatório.
7. **Gravação canônica**: append no CSV canônico (nunca reescrever linhas validadas); manifest do lote com contagem de linhas, hash do arquivo bruto, mapping usado, scrub aplicado.
8. **Consulta (regra permanente)**: número que vai para estudo/plano sai de consulta executada (DuckDB local `SELECT praca, SUM(investimento)...` ou pandas), e a **query fica registrada junto do resultado** na saída. Se a resposta não veio de query, não é resposta desta base.

## Erros comuns a bloquear

- Somar subtotal com linhas-filhas (dupla contagem) → mapping deve excluir subtotais explicitamente.
- Meses como colunas ("Jan", "Fev"…) ingeridos como colunas → unpivot para linhas com `periodo_*`.
- Moedas/percentuais como texto ("R$ 1.234,56", "12%") → conversão declarada no mapping.
- Célula mesclada de cabeçalho → resolver na conversão, nunca deixar o modelo "interpretar" na consulta.
- Tipos do Excel: datas como serial number, números como texto → validar tipos no gate.
- Marcador textual dentro de coluna de data (ex.: um status digitado onde ia a data) → na canônica a data fica vazia; o marcador permanece nas colunas de texto e a linhagem aponta a célula original.
