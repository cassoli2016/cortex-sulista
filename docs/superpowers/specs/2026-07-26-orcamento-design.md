# Design — Módulo Orçamentário (Fase 1: derivar, ajustar e acompanhar)

> Data: 2026-07-26 · Origem: brainstorming com o usuário · Status: **aprovado** para
> desenvolvimento. Baseado na DRE Gerencial existente (`get_dre`).

## Contexto levantado antes do desenho

1. **Não existe orçamento formal na Sulista.** A decisão do usuário foi *derivar do
   histórico* e deixar a controladoria ajustar. Isso muda o faseamento: "acompanhar"
   não existe sozinho, porque não há o que comparar. Gerar a proposta entra na Fase 1.
2. **O banco do ERP AVA é somente-leitura** (usuário `consulta_sulista`, réplica). O
   orçamento é dado nosso e precisa de armazenamento local. Precedentes no projeto:
   `data/auth.db` (SQLite) e `data/ajustes_contabeis.json`.
3. **Já existe meta, mas só de faturamento**: `sulista.metafaturamento_agrupamentoclientedia`
   (por cliente/dia, `tipo=1`). Não cobre custo nem despesa, e não substitui o orçamento.
4. **A DRE Gerencial é chaveada em `grupo|reduzido`** → `sulista.agrupadorgerencial.descricao`
   → cascata `DRE_MODELO` (22 linhas). Não é o `estrutural`: o caminho `_DRE_GRUPO`
   (receita_bruta / custo_var / fixo…) é usado em outros pontos (ponto de equilíbrio),
   não na DRE. A mesma chave `grupo|reduzido` é a que a tela de Contabilidade já ajusta.

### Números que sustentam as decisões

Amostra medida sobre 11 meses fechados (ago/25–jun/26). A base de produção usará os
12 últimos meses fechados; o corte de recorrência é sempre relativo à janela usada.

| Medida | Valor |
|---|---|
| Contas com movimento (`grupo\|reduzido`) | **355** |
| Contas com movimento em **todos** os meses | **212 (60%)** |
| Contas com movimento em 1 ou 2 meses | **41** |
| Contas sem agrupador (caem em `CLASSIFICAR`) | **10** |
| Agrupadores distintos | 52 |

Sazonalidade e tendência (receita mensal, 24 meses):

- **Dezembro despenca ~40%**: dez/24 = R$ 10,3 mi e dez/25 = R$ 7,9 mi, contra médias de
  R$ 14,0 mi e R$ 13,5 mi. Sazonalidade real, não ruído.
- **Queda estrutural de 18% a/a**: ago/24–jul/25 = R$ 13,6 mi/mês; ago/25–jul/26 = R$ 11,2 mi.
- **Despesas têm picos de provisão**: R$ 0,05 mi (nov/25), R$ 3,28 mi (dez/25), R$ 0,20 mi
  (nov/24). Média simples nessas contas produz um número que nunca aconteceu.

Essas três observações são o motivo de o método ser **mês espelho + tendência**, e não média.

## Decisões travadas (brainstorming)

- **Faseamento:** Fase 1 = derivar + ajustar + acompanhar. Fase 2 = forecast (realizado +
  premissas para os meses restantes). Fase 3 = elaboração plena (premissas, drivers,
  cenários, versionamento com aprovação). Cada fase tem sua própria spec.
- **Granularidade:** por conta contábil, na chave `grupo|reduzido` da DRE. Alta
  granularidade é barata porque o baseline é **derivado** — ninguém digita 355 linhas,
  só ajusta o que discorda.
- **Método de derivação:** mês espelho + fator de tendência.
- **Primeiro uso sugerido:** orçar **ago–dez/2026** (espelho de ago–dez/2025, já fechado)
  para começar a acompanhar imediatamente, sem esperar o ciclo de 2027.

## 1. Arquitetura e módulos

- Novo módulo **`api/orcamento.py`**. Não tocar `queries.py`, que já passa de 5.000 linhas.
- Armazenamento **`data/orcamento.db`** (SQLite), seguindo o padrão do `auth.db`.
- Endpoints em `api/main.py` sob **`/api/controladoria/orcamento…`**, registrados em
  `ROTA_TELAS` (`api/auth.py`) com a chave de tela `orc`, antes de rotas de prefixo
  concorrente.
- Nova vista SPA **`#orc`** ("Orçamento") no grupo **Controladoria**, junto de DRE
  Gerencial, DRE por Cliente e Contabilidade. Entra também na gaveta mobile e no
  `NAV_KW` (sinônimos: orçamento, orçado, budget, previsto, desvio).
- Padrões do front obrigatórios: `qsView`/`LOADEDQS`, loaders `loadOrc`/`renderOrc`,
  `ast.parse` antes de gravar `.py`, `node --check` no `<script>`, `rep()` com assert.

## 2. Modelo de dados

```
orc_versao(id, ano, rotulo, status, fator_tendencia, criado_em, criado_por)
    status ∈ {rascunho, aprovado}

orc_linha(versao_id, conta, mes, valor_baseline, valor_ajustado,
          origem, meses_base, ajustado_em, ajustado_por)
    conta  = 'grupo|reduzido'          -- mesma chave dos ajustes contábeis
    mes    = 1..12
    origem ∈ {espelho, mediana, sem_base}
    PRIMARY KEY (versao_id, conta, mes)

orc_log(id, versao_id, conta, mes, valor_de, valor_para, quem, quando)
```

**Valor efetivo = `coalesce(valor_ajustado, valor_baseline)`.** Regerar o baseline
recalcula apenas `valor_baseline` e **preserva** `valor_ajustado` — mesmo princípio do
`ajustes_contabeis.json`. Sem isso, recalcular jogaria fora o trabalho da controladoria.

## 3. Derivação do baseline

Entrada: `ano` e `fator_tendencia` global (ex.: `-0.05`). **Fator por linha da DRE fica
fora da Fase 1** — quem quiser tratamento diferente por natureza ajusta as células.

1. **Base = últimos 12 meses fechados.** O mês corrente **nunca** entra: em jul/26 o
   custo variável aparece em R$ 3,4 mi contra R$ 6,5 mi normais, porque o mês está pela
   metade. Esse é o mesmo defeito corrigido em várias telas na revisão de 2026-07-26.
2. Para cada conta × mês-calendário: valor do **mesmo mês** na base × `(1 + fator)`.
3. **Regra de recorrência** (exigida pelos dados; o corte de 75% separa as 212 contas
   recorrentes das 41 esporádicas medidas na amostra):
   - conta com movimento em **≥ 9 dos 12 meses da base (75%)** → `origem = espelho`;
   - conta abaixo desse corte → `valor = mediana dos meses com movimento`, aplicada
     **somente nos meses-calendário cujo espelho teve movimento** (os demais ficam
     `0`/`sem_base`); `origem = mediana` e a linha nasce marcada **"base fraca —
     revisar"**. *(Revisado em 2026-07-27, decisão do usuário: a redação original
     gravava a mediana nos 12 meses e anualizava a conta esporádica em ~12× — as 91
     contas abaixo do corte somavam R$ 43,7 mi de baseline contra R$ 3,9 mi de
     histórico. Preservar QUANDO o gasto acontece também é a informação relevante
     em provisão e evento pontual.)*
   - conta sem nenhum movimento no mês espelho → `valor = 0`, `origem = sem_base`.
4. **Meses circulares** *(adicionado em 2026-07-27, revisão final)*: mês do ano
   orçado que está **dentro da própria base** (orçar 2026 em julho põe jan–jun/26 na
   base) tem como espelho o próprio mês — o "orçado" é o realizado lido de volta ×
   (1+fator) e o desvio mediria só o fator (−5% vira −5,26% em toda linha). A versão
   grava `meses_base` e o acompanhamento **exclui esses meses do acumulado**,
   mantendo-os no gráfico mensal esmaecidos e explicando no banner. Continua valendo
   o primeiro uso sugerido: orçar 2026 em julho acompanha de agosto em diante.
5. **Contas sem agrupador** não recebem baseline: vão para uma lista à parte com link
   para a tela de Contabilidade. Sem classificação elas não somam em linha nenhuma da
   DRE, e orçá-las produziria um total que não fecha com a cascata.

## 4. Rollup e reconciliação com a DRE

`conta (grupo|reduzido)` → `agrupador` (via `sulista.agrupadorgerencial`, **com os ajustes
locais de `ler_ajustes()` aplicados**) → `linha do DRE_MODELO`.

É exatamente o caminho que `get_dre` já percorre. Consequência desejada: reclassificar
uma conta na tela de Contabilidade move **orçado e realizado juntos**, sem abrir
divergência entre as duas telas.

O realizado por conta reusa a base de `DRE_AG_SQL` numa variante por conta e sem
`LIMIT`, no mesmo intervalo de competência.

## 5. Telas

Uma vista `#orc` com duas abas, no padrão de abas que a tela de Gestão já usa.

### Aba 1 — Acompanhamento

- **Filtros:** ano/versão · acumulado (jan até o **último mês fechado**, nunca o corrente)
  ou mês isolado · agrupador.
- **KPIs (4):** Receita orçada × realizada · Custo orçado × realizado · Resultado orçado
  × realizado · Contas estouradas — definidas como **conta de custo ou despesa cujo
  realizado acumulado passou do orçado acumulado no mesmo intervalo**.
- **Semântica de desvio — requisito, não detalhe:** receita abaixo do orçado é
  desfavorável; custo abaixo do orçado é **favorável**. Usar `trendChip(..., {invert})` e
  a regra do `_cel(u,a)` da DRE: **cor pelo efeito no resultado, nunca pelo sinal**.
- **Card principal:** cascata `DRE_MODELO` com colunas `Orçado · Realizado · Desvio R$ ·
  Desvio %`, linha expansível até a conta, como a DRE Gerencial já faz.
- **Card evolução mensal:** orçado × realizado por mês. **Mês não fechado não desenha
  barra de realizado** — só o orçado esmaecido (defeito corrigido no painel de TV; aqui
  apareceria em todo ano em curso).
- **Card maiores desvios:** top 15 contas por desvio absoluto, com R$, % e agrupador.
- ⓘ de procedência em todos os cards e KPIs, no padrão da revisão.

### Aba 2 — Montagem

- **Gerar baseline:** escolhe ano e fator, **pré-visualiza antes de gravar**.
- **Grade editável** conta × 12 meses, filtrada por linha da DRE (355 linhas de uma vez
  não se lê). Baseline em cinza, ajuste manual em destaque, valor original no tooltip.
- **Marca "base fraca"** nas contas de origem `mediana`/`sem_base`.
- **Lista de contas sem agrupador** com link para a Contabilidade.
- Gravação por célula, otimista, com rollback visual se a API falhar.

## 6. Erros e casos de borda

| Situação | Comportamento |
|---|---|
| Mês corrente na base | Excluído sempre |
| Conta com < 9 meses | Mediana + marca "base fraca" |
| Conta sem movimento no espelho | 0 + `sem_base`, nunca silencioso |
| Conta sem agrupador | Fora do baseline, listada para classificar |
| Regerar baseline com ajustes | Preserva `valor_ajustado` |
| API falha ao salvar célula | Rollback visual + banner |
| Ano sem 12 meses fechados de base | Bloqueia geração e diz quantos meses faltam |

## 7. Testes

- **Unitários da derivação:** mês espelho, aplicação do fator, regra dos 9 meses,
  exclusão do mês corrente, mediana, `sem_base`.
- **Unitários do rollup:** conta → agrupador → linha, com e sem ajuste contábil local.
- **Reconciliação:** soma das contas de uma linha = valor da linha na cascata.
- **Preservação de ajuste:** regerar baseline não altera `valor_ajustado`.
- `pytest` (78 testes atuais devem continuar passando), smoke das telas e o validador
  estrutural `scratchpad/estrutura.py` incluindo `orc`.

## Critérios de aceite (Fase 1)

1. Gerar baseline de ago–dez/2026 e ver a cascata da DRE preenchida na coluna Orçado.
2. Total orçado de uma linha = soma das contas expandidas dessa linha.
3. Ajustar uma célula, regerar o baseline e o ajuste continuar lá.
4. Custo abaixo do orçado aparece em verde; receita abaixo, em vermelho.
5. Mês em curso não exibe barra de realizado no gráfico de evolução.
6. As 10 contas sem agrupador aparecem na lista de pendências, não no orçamento.
7. `pytest`, smoke e validador estrutural passam.

## Fora do escopo da Fase 1

- Forecast / reprojeção do ano (Fase 2).
- Premissas e drivers (km previsto, frota, inflação por natureza), cenários, workflow de
  aprovação com múltiplas versões comparáveis (Fase 3).
- Orçamento por filial ou por centro de custo.
- Importação de planilha — não há planilha; se aparecer uma, entra como aditivo.
- Rateio de orçamento por cliente ou por veículo.
