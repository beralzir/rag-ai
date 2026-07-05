# Taxonomia 2.0: template e processos

A taxonomia vive em `_meta/taxonomy.yaml` e é a **fonte única** de termos válidos. O gate rejeita qualquer tag fora dela (lição de origem: uma tag fora do vocabulário ficou invisível ao retrieval até existir o gate).

## Estrutura (YAML restrito)

```yaml
# _meta/taxonomy.yaml
axes: [topic, industry, geography]   # deve casar com base_config.yaml

topic:
  - id: media-consumption            # ASCII, sem acento, kebab-case; é o valor usado em tags:
    label_pt: "consumo de mídia"
    label_en: "media consumption"
    aliases: [consumo de midia, "media habits", "consumo midiatico"]
    scope_note: "hábitos e tempo gasto por meio; NÃO usar para investimento (ver media-investment)"
    status: ativo                     # candidato | ativo | deprecado
  - id: programmatic
    label_pt: "mídia programática"
    label_en: "programmatic"
    aliases: [programatica, "programmatic advertising", rtb]
    scope_note: "compra automatizada de mídia"
    status: ativo
  # - id: exemplo-deprecado
  #   status: deprecado
  #   replaced_by: novo-termo        # obrigatório quando deprecado

industry:
  - id: advertising
    label_pt: "publicidade"
    label_en: "advertising"
    aliases: [propaganda, ads]
    scope_note: "mercado publicitário como vertical"
    status: ativo

geography:
  - id: brazil
    label_pt: "brasil"
    label_en: "brazil"
    aliases: [br, brasileiro]
    scope_note: "dados com recorte Brasil"
    status: ativo
```

## Regras que o gate impõe

1. `id` único em TODA a taxonomia (não só no eixo) e em ASCII kebab-case.
2. Um `label_pt` e um `label_en` por termo (um rótulo preferido por idioma, estilo SKOS).
3. Alias não pode ser ambíguo: o mesmo alias em dois termos é erro.
4. `status: deprecado` exige `replaced_by` apontando para termo ativo; chunk novo com termo deprecado é erro (o antigo permanece válido no histórico).
5. Todo termo tem `scope_note` (é o que evita eixos vazando uns nos outros com o tempo).

## Como adicionar um termo (chunk-proof)

1. Mostre 1+ chunks reais que precisam do termo e por que nenhum termo ativo cobre (cheque também os aliases).
2. Teste de eixo: o conceito pertence a exatamente um eixo? Se cabe em dois, o desenho está errado (refine a scope_note ou o termo).
3. Adicione com `status: candidato` enquanto a proposta está em discussão; **promova a `ativo` ANTES de escrever qualquer chunk que o use** (chunk com tag candidata gera aviso e o gate de lote estrito bloqueia; `candidato` é estado de proposta, não de uso).
4. Registre em `_meta/TAXONOMY_CHANGELOG.md`: data, termo, justificativa, chunks-prova.
5. Rode `validate_base.py --strict`.

## Como renomear/aposentar um termo

Nunca renomeie in-place e nunca delete. Crie o termo novo, marque o antigo como `deprecado` + `replaced_by`, registre no changelog. Migração dos chunks antigos é operação estrutural (proposta → aprovação → PR), com manifest próprio.

## Como usar na consulta (agente)

- Busca por conceito: comece pelo `id` da tag (grep no frontmatter), depois expanda corpo com `label_pt` + `label_en` + `aliases` nos DOIS idiomas.
- Registro de miss: quando uma busca legítima não encontra nada, anote em `_meta/search_misses.md` (data, consulta, o que esperava). É insumo do golden set e gatilho de aliases novos.

## Como adicionar uma categoria (pasta física)

Categoria é só "home" físico, não instrumento de busca. Nova categoria exige: 20+ chunks projetados que não caibam bem nas atuais; entrada em `base_config.yaml`; changelog; PR. Na dúvida, não crie: use tags.
