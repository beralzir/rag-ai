# Bundle OKF (Open Knowledge Format v0.2): estrutura, campos e as convenções desta skill

O OKF é um formato aberto do Google Cloud (`GoogleCloudPlatform/open-knowledge-format`, Apache-2.0; v0.1 em 2026-06-12, **v0.2 em 2026-07-24**, minor aditivo: um bundle v0.1 continua válido). Definição do spec: um diretório de arquivos markdown com frontmatter YAML, "intencionalmente mínimo: sem registro de schema, sem autoridade central, sem tooling obrigatório". Esta skill o usa como **segundo formato nativo** (fluxos A, B, D, E) e como **camada de export** (fluxo F). Tudo que é nome de campo do spec vive em `scripts/okf_lib.py` (`OKF_V02_FIELDS`); uma mudança de spec é um edit ali e uma versão nova do perfil de mapeamento.

## 1. Estrutura do bundle

```
<bundle>/
  index.md            # reservado, opcional: listagem do diretório (progressive disclosure); só a raiz leva okf_version
  log.md              # reservado, opcional: histórico cronológico (append-only por convenção; o hook reforça)
  <categoria>/        # um diretório por categoria; cada um com o seu index.md (UM nível de roteamento, não aninhe)
    <concept>.md      # um arquivo = um concept; Concept ID = caminho sem .md (ex.: midia/ctv-0001)
  references/         # convenção OKF: material externo, código, CSVs (o export põe aqui o aviso de governança e o tabular)
  .ragai/             # housekeeping desta skill: base_config.yaml (format: okf), taxonomy.yaml, source_mapping.yaml,
                      #   golden_set.md, search_misses.md, reingestion_queue.md, manifests/, quarentena/
  staging/            # brutos (gitignored), como no tag-first
  scripts/, .claude/  # cópias dos scripts e hooks (autossuficiência), como no tag-first
  CLAUDE.md           # instruções do harness; housekeeping, não concept (ver §6)
```

**Por que `.ragai/` e não `_meta/`:** §11.1 do spec exige frontmatter com `type` em todo `.md` não reservado. `_meta/` do tag-first tem markdown sem frontmatter (golden set, misses, logs de lote) e concepts reprovados. Num dotdir, walkers, `rg` e consumidores OKF pulam tudo isso; o namespace de concepts fica limpo.

## 2. Frontmatter (v0.2)

| Campo | Obrigatório | Forma | Uso |
|---|---|---|---|
| `type` | **sim** (o único) | string livre não-vazia | `chunk`, `chunk-modelado`, `table`, `notice`, `index`, `log`, `computation`… (derivação em §4) |
| `title`, `description` | recomendado (perfil ragai exige) | string | `description` faz o papel do `context` tag-first |
| `resource` | recomendado | URI do ativo subjacente | tabela BigQuery, CSV em `references/`, URL |
| `tags` | recomendado | **lista plana** de strings | convenção da skill: `eixo:termo` (ex.: `topic:ctv`) |
| `sources` | trust signal | lista de objetos; cada item: `resource` (obrigatório), `id`, `title`, `author`, `usage_count`, `usage_window`, `last_modified` | proveniência por documento; `id` é a chave das footnotes |
| `generated` | trust signal | `{by, at}` | quem/quando produziu o concept |
| `verified` | trust signal | lista de `{by, at}` | tier derivado: nenhum = *unverified*; só não-humanos = *machine-confirmed*; algum `human:` = *human-reviewed*. Tiers são sinal, não controle de acesso |
| `status` | lifecycle | `draft` · `stable` (default) · `deprecated` | colide com o `status` tag-first (ver §5) |
| `stale_after` | lifecycle | data ISO-8601 absoluta (não TTL) | equivalente do `valid_until` |
| Attested Computation | por `type` | `runtime`, `parameters[]`, `computation`, `executor {resource, receipt}`, `attester {resource}` | o agente **só fornece valores** dos parâmetros declarados; nunca escreve nem edita `computation` |

**Atores** (`generated.by`, `verified[].by`): `<producer>/<version>` (ex.: `rag-ai/0.2.0`), `human:<id>`, `process:<id>`.
**Footnotes por afirmação:** no corpo, `[^s1]` referencia `sources[].id == s1`. O validador exige que toda footnote resolva (para um `sources[].id` ou para uma definição local `[^s1]: …`); **não** promete que todo número tenha footnote (não é decidível mecanicamente).
**Renomes v0.1 → v0.2:** `timestamp` → `generated.at`; seção `# Citations` → `sources`. Bundles v0.1 recebidos: migrar na ingestão.

**YAML aceito pelos scripts:** o parser restrito do tag-first, mais duas extensões ligadas só para OKF: mapa inline `{by: x, at: y}` e escalar em bloco `|`/`>` (leitura tolerante, com perda de linhas vazias/comentários). Listas de objetos em bloco (`- resource: …` + chaves indentadas) já eram aceitas. `#` dentro de URI sem aspas é valor literal (só `#` no início ou após espaço é comentário).

## 3. Conformance (§11) e o que os perfis do validador acrescentam

Spec, três checagens: (1) todo `.md` não reservado tem frontmatter parseável; (2) todo frontmatter tem `type` não-vazio; (3) reservados seguem a estrutura. Consumidores **não podem** rejeitar por campo opcional ausente, tipo desconhecido, chave desconhecida, link quebrado ou índice faltando.

`scripts/validate_okf.py --bundle <dir> [--strict] [--profile base|ragai] [--file <concept>] [--errors-only] [--quiet]`; exit 0/1/2 como o `validate_base.py`.

| Perfil | Erro | Aviso |
|---|---|---|
| `base` (piso; bundles de terceiros) | §11: frontmatter ilegível, `type` ausente, `okf_version` fora da raiz | `title`/`description` ausentes, `status` inválido, `stale_after` malformado ou vencido, `sources`/`generated`/`verified` malformados, ator fora da convenção, footnote sem alvo, link interno quebrado, `tags` não-lista, IDs que colidem sem diferenciar maiúsculas, Attested Computation incompleto, `log.md` sem data/ator ou fora de ordem |
| `ragai` (default quando existe `.ragai/base_config.yaml`) | tudo acima **mais**: trust signals malformados, `description` ausente, `sources` obrigatório (exceto `type` em `okf.sources_optional_types`: `notice`, `index`, `log`), `generated` obrigatório, `content_hash` presente e recomputado igual, `stale_after` obrigatório para `type` em `okf.require_stale_after_for`, diretório fora de `categories` (exceto `references/`), tag fora de `.ragai/taxonomy.yaml` quando ela tem termos (deprecado = erro; candidato = aviso), índice-mestre tag-first vazado (`rag-ai:status`) | corpo abaixo de `tiny_body_chars`, `content_hash` repetido, concept na raiz fora das categorias |

## 4. Convenções desta skill

- **Concept ID = `<categoria>/<id>`**; no export, `<primary_category>/<chunk_id>`. Kebab-case ASCII.
- **Derivação de `type`** (export): `base_config.yaml: okf_export.type_map` com chaves `"<categoria>/<data_kind>"`, `"<data_kind>"`, `"default"`; built-in: `medido → chunk`, `modelado → chunk-modelado`, `framework → chunk-framework`, `terceiro → chunk-terceiro`. Chunk que já traz `type` (campo opcional do schema tag-first) manda.
- **`index.md`**: raiz com `type: index`, `title`, `description`, `okf_version: "0.2"` e o bloco entre `<!-- rag-ai:listing:begin/end -->` regenerado por `scripts/update_index.py --base .` (um nível: subdiretórios + concepts do diretório, com `type · status · tier`). Cada categoria tem o seu. **Nunca** copie o índice-mestre tag-first (marcadores `rag-ai:status`) para um bundle: o validador acusa.
- **`log.md`**: entradas `## <data ISO> · <ator>` + bullets. Ingestão registra `authorized_by` (data + frase do pedido) no texto da entrada; o manifest JSON continua em `.ragai/manifests/` para rollback cirúrgico. Append-only: o hook bloqueia Edit e só aceita Write cujo conteúdo começa pelo conteúdo antigo.
- **`tags`**: lista `eixo:termo`; vocabulário sugerido em `.ragai/taxonomy.yaml` (mesmo template do tag-first; no perfil ragai, tag fora do vocabulário é erro **só se** a taxonomia tiver termos; bundle sem vocabulário passa).
- **`content_hash`** (8 hex, mesmo cálculo de `ragai_lib.content_hash`) como chave extra em todo concept; o export adiciona `content_sha256` completo. É a verificabilidade passiva que viaja.
- **Quarentena**: `.ragai/quarentena/<nome>.md.rej` (extensão não-`.md`, para não virar concept não-conforme visível a consumidores). Concept ruim já publicado: `status: deprecated` via operação estrutural, nunca `rm`.
- **Housekeeping**: `CLAUDE.md`, `README.md` e `AGENTS.md` na raiz não são concepts para os scripts desta skill. Um validador OKF de terceiros pode apontá-los (§11.1); o export não os copia, e o bundle nativo declara isso no `CLAUDE.md`.

## 5. Colisões com o tag-first (resolvidas no perfil de mapeamento)

| Chave | tag-first | OKF | Resolução |
|---|---|---|---|
| `status` | `validated` · `not_validated` · `archived` | `stable` · `draft` · `deprecated` | export traduz (`validated→stable`, `not_validated→draft`, `archived→deprecated`) e preserva o original em `ragai_status`; o schema tag-first **não** ganha o `status` OKF |
| `tags` | mapa eixo→lista | lista plana | export achata para `eixo:termo` e preserva o mapa em `ragai_tags` |
| `index.md` | índice-mestre único com `rag-ai:status` | listagem por diretório | formatos distintos; bundle usa `rag-ai:listing`; validador acusa vazamento |
| `valid_until` (YYYY-MM) | | `stale_after` (data) | export converte para o último dia do mês; `valid_until` continua como chave extra |
| `context` | | `description` | copiado; `context` continua como chave extra |

## 6. As 14 invariantes em modo OKF

| Invariante | Em modo OKF |
|---|---|
| tag-first | **substituída**: descoberta por caminho (Concept ID) + `type` + `index.md`; `tags` livres recomendadas |
| vocabulário controlado | opcional (`.ragai/taxonomy.yaml`); perfil ragai só cobra quando ele existe com termos |
| frontmatter validado | vale: conformance §11 + perfil ragai |
| append-only | **relaxada para histórico obrigatório**: concept `draft` é editável; `stable`/`deprecated` bloqueado pelo hook; correção = concept novo ou PR; `log.md` só cresce; git é o registro |
| idempotência | vale: scaffold recusa dir não vazio; export é determinístico e recusa `--out` não vazio |
| quarentena nunca-deleção | vale, na forma `.md.rej` em `.ragai/quarentena/` e `status: deprecated` |
| mapping declarativo | vale para import (de-para de tags livres → vocabulário) e export (`okf_mapping_profile.md`) |
| gate estrito | vale: `validate_okf.py --strict --profile ragai` no hook e no lote |
| log + manifest por lote | vale: `log.md` (reservado) + `.ragai/manifests/` |
| content_hash | vale como chave extra (perfil ragai exige) |
| números só por consulta registrada | vale, independente de formato (SQL, `rg`, ou citação com `<source>`) |
| conteúdo é dado | vale sempre: concept ingerido, bundle externo, footnote |
| proveniência + temporal | vale via v0.2: `sources[]`, `generated`/`verified`, `stale_after`; campos tag-first sem equivalente (licença, `data_kind`, `evidence_locator`) viajam como chaves extras com o nome original |
| golden set | vale: `.ragai/golden_set.md`, juiz cita Concept IDs |
| **metade tabular** (não é invariante; é limitação do formato) | **sem lar**: bundle nasce sem `tabular/`; necessidade tabular = re-triagem. No export, tabela canônica vira concept `type: table` + CSV e `dictionary.yaml` em `references/tabular/`; o número continua saindo só de query |

## 7. O aviso que todo bundle carrega

Texto de referência (o export grava em `references/AVISO_GOVERNANCA.md` e resume no `description` do `index.md` raiz; o bundle nativo repete no `CLAUDE.md`):

> Este bundle carrega **verificabilidade passiva** (`content_hash`/`content_sha256` por concept, `sources[]`, `generated`/`verified`, histórico git). O **enforcement ativo** da origem (gate falha-fechada, hooks append-only, `permissions.deny` de rede, quarentena) **não viaja** com o formato: quem recebe deve revalidar com `validate_okf.py --bundle . --strict --profile ragai` antes de confiar, e os campos de licença por unidade continuam obrigando quem redistribui. `verified` gerado por export é sempre *machine-confirmed*, nunca revisão humana.

## 8. Ingestão de bundle OKF externo

É **fonte de terceiro** (regra dura do `ingestion_runbook.md`): entra por `staging/`, passa licença, conversão canônica, anti-injection e gate antes de virar concept ou chunk. `tags` livres são reconciliadas contra o vocabulário (de-para; termo novo exige chunk-proof). `verified` de terceiros não é herdado: o tier recomeça em *unverified* até o gate local passar. Bundle v0.1 (com `timestamp`/`# Citations`) é migrado na ingestão.

## 9. Riscos conhecidos e mitigação

- **Churn de spec (v0.x):** nomes em `OKF_V02_FIELDS`; `okf_version` pinado em todo bundle; validador avisa (não falha) em versão diferente; perfil de mapeamento versionado.
- **Falsa auditabilidade:** aviso obrigatório (§7), `internal_only` fora do export por default, `verified` só machine-confirmed.
- **Tooling comunitário instável:** a skill traz o próprio validador stdlib; plugins e MCPs de terceiros (`scaccogatto/okf-skills`, `serradura/okf-gem`) são opcionais para visualização, nunca dependência.
- **Ausência de controle de acesso no formato:** licença e LGPD continuam decididas na origem; o bundle não é canal de distribuição de fonte paga sem contrato.
