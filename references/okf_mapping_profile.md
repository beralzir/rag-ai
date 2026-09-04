# Perfil de mapeamento tag-first ↔ OKF v0.2

`profile_version: 1` (gravado em cada concept exportado como `ragai_profile_version` e no `index.md` raiz em `ragai.profile_version`). Implementado em `scripts/export_okf.py`; a leitura de volta (import) segue a mesma tabela em sentido inverso. Toda mudança nesta tabela sobe a versão e entra no changelog do fim.

## Regras gerais

- **Corpo do chunk viaja byte-idêntico.** `content_hash` é sobre o corpo; nada é injetado (nem footnotes). Atribuição por concept via `sources[0]`, coerente com "um fato, um chunk, um hash".
- **Toda chave tag-first sem equivalente viaja verbatim** como chave extra (o OKF tolera chaves desconhecidas). Só `status` e `tags` são renomeadas, por colisão.
- **Perda declarada, nunca silenciosa.** A coluna "Perda" diz o que não volta no round-trip; o `log.md` do bundle registra o que ficou de fora (unidades `internal_only`, metade tabular).

## Tabela de-para

| tag-first | OKF v0.2 | Direção | Perda / observação |
|---|---|---|---|
| `chunk_id` + `primary_category` | Concept ID `<primary_category>/<chunk_id>` (caminho do arquivo); `chunk_id` continua como chave extra | ↔ | nenhuma |
| `primary_category` + `data_kind` | `type` (via `okf_export.type_map`: `"<cat>/<kind>"`, `"<kind>"`, `"default"`; built-in `medido→chunk`, `modelado→chunk-modelado`, `framework→chunk-framework`, `terceiro→chunk-terceiro`); `type` já presente no chunk manda | → | derivada, não inversível sozinha (`data_kind` viaja como extra) |
| 1º heading `# ` do corpo, senão `"<chunk_id>: <source>"` | `title` | → | nenhuma |
| `context` | `description` (+ `context` como extra) | ↔ | nenhuma |
| `tags` (mapa eixo→lista) | `tags` lista `eixo:termo`; mapa original em `ragai_tags` | ↔ | nenhuma (mapa preservado) |
| `source`, `source_file`, `attributed_to`, `published`, `evidence_locator` | `sources[0] = {id: slug(source), resource: "urn:ragai:source:<slug>", title: source, author: attributed_to (se ≠ nenhum), last_modified: published (último dia do mês), locator: evidence_locator, file: source_file}` | → | `resource` é URN: o bruto licenciado **não** viaja; `on_behalf_of` fica só como extra |
| `date_ingested` | `generated: {by: "rag-ai/<SKILL_VERSION>", at: date_ingested}` | → | nenhuma |
| `status: validated` (gate da origem verde) | `verified: [{by: "rag-ai-validate_base/<versão>", at: <data do export>}]` (tier *machine-confirmed*) | → | `not_validated`/`archived` não geram `verified`; nunca vira *human-reviewed* |
| `status` | `status`: `validated→stable`, `not_validated→draft`, `archived→deprecated`; original em `ragai_status` | ↔ | nenhuma (original preservado) |
| `valid_until` (YYYY-MM, YYYY-MM-DD ou YYYY) | `stale_after` (YYYY-MM-DD; mês → último dia; ano → 12-31); `valid_until` continua como extra | ↔ | precisão de dia só existe no OKF |
| `content_hash` (8 hex) | `content_hash` (extra) + `content_sha256` (hash completo do mesmo corpo normalizado) | ↔ | nenhuma; o sha256 completo reforça a detecção de adulteração |
| `data_kind`, `derivation_method`, `extraction_quality`, `metodo_extracao`, `dupla_extracao`, `covers`, `chunk_index`, `total_chunks` | chaves extras, mesmo nome | → | OKF não tem semântica para elas; consumidores ignoram |
| licença: `access_basis`, `licensor`, `permitted_use`, `tdm_ai_clause`, `consent_ref`, `verbatim`, `verbatim_len`, `attribution`, `contains_personal_data`, `review_date` | chaves extras, mesmo nome; `index.md` raiz recebe `ragai.contains_licensed_units: true` quando alguma unidade não é `publico` | → | **sem enforcement no receptor** (aviso obrigatório); `permitted_use: internal_only` fica **fora** do export salvo `--allow-internal` |
| tabela canônica (`tabular/canonical/<t>.csv` + `dictionary.yaml`) | com `--include-tabular`: `references/tabular/<t>.csv` + `references/tabular/dictionary.yaml`; concept `tabular/<t>.md` com `type: table`, `resource: /references/tabular/<t>.csv`, `csv_sha256`, `rows`, corpo `# Schema` (colunas + lineage + grain) | → | consultabilidade SQL não viaja como serviço; número continua só por query sobre o CSV |
| query do golden set / query registrada (SQL) | Attested Computation (`type: computation`, `runtime`, `computation`, `parameters[]`, `executor`) | → | **passo futuro** (perfil v2): não emitido nesta versão |
| `_meta/manifests/*` (manifest JSON + log de lote) | entrada em `log.md` (`## <data> · rag-ai/<versão>`) com contagens, unidades omitidas, commit de origem | → | o JSON de rollback não viaja (fica na origem) |
| índice-mestre `index.md` (`rag-ai:status`) | `index.md` raiz OKF + `index.md` por categoria (`rag-ai:listing`) | → | nunca copiado; formatos distintos |

## Round-trip (import do próprio export)

Regra: importar um bundle exportado por esta skill deve **recuperar todo campo governado** (licença, `data_kind`, `valid_until`, `status` original, `tags` por eixo) ou **sinalizar a perda**. Como tudo viaja como chave extra com o nome original, o de-para inverso é: `ragai_status → status`, `ragai_tags → tags`, ignorar `type`/`title`/`sources`/`generated`/`verified`/`stale_after`/`content_sha256`/`ragai_profile_version` (derivados). O corpo é o mesmo, logo o `content_hash` confere sem recálculo.

Bundle OKF **de terceiros** (não exportado daqui) não tem os extras: entra como `data_kind: terceiro`, licença a preencher, `status: not_validated`, tags reconciliadas. Ver `ingestion_runbook.md`.

## Verificação (fluxo D sobre um export)

1. `validate_okf.py --bundle <out> --strict --profile ragai` (o export já roda ao final e imprime o comando).
2. Recomputar `content_hash` de cada concept e comparar com o chunk de origem (o export imprime `N/N hashes reconferidos`).
3. Origem mudou desde o export? Compare `ragai.origin_commit` do `index.md` raiz com `git rev-parse HEAD` da base; divergência = re-exportar (snapshot defasado é achado médio; concept adulterado no bundle é crítico).

## Changelog

- **v1 (2026-09-04):** primeira versão. Corpo byte-idêntico; `status`/`tags` preservados em `ragai_*`; `verified` machine-confirmed; `internal_only` fora por default; tabular como `type: table` + CSV em `references/`; Attested Computation adiado.
