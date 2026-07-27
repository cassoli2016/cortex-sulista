# Design — Orçamento base 1º semestre + provisão de caixa no Fluxo

> Data: 2026-07-27 · Origem: brainstorming com o usuário · Status: **aprovado** para
> desenvolvimento. Estende o módulo Orçamento (spec 2026-07-26) e a tela Fluxo de
> Caixa. Não altera o método espelho existente.

## Decisões do usuário (brainstorming)

- **Derivação = nível do 1º semestre × sazonalidade histórica.** A média flat do
  semestre superestimaria o fim do ano (dezembro cai ~40% e o 1S não contém essa
  queda); o espelho 12m já existe e continua disponível.
- **Provisão no Fluxo de Caixa com defasagem real DSO/DPO.** Orçamento é competência;
  o caixa da Sulista recebe em ~49 dias (DSO) e paga em ~79 (DPO), medidos ao vivo
  pelo próprio fluxo. Sem a defasagem seria DRE re-plotada, não provisão de caixa.

## 1. Novo método de derivação: "Semestre × sazonalidade"

### Regra (módulo puro, `api/orcamento/derivacao.py`)

Nova função `derivar_semestre(historico, meses_base, indices, mapa_linha, fator)`:

```
nivel_conta      = soma(valores da conta nos 6 meses_base) / 6
valor_conta_mes  = nivel_conta × indice_linha(conta)[mes] × (1 + fator)
```

- `meses_base` = os **últimos 6 meses fechados** (`meses_fechados(hoje, 6)`;
  hoje: jan–jun/26). Base incompleta (mês sem lançamento algum) **bloqueia** a
  geração com a lista dos meses faltantes — mesmo comportamento do espelho
  (`meses_faltando`).
- `origem = "semestre"` (valor NOVO no domínio) para conta com movimento na base;
  conta sem movimento algum → `origem = "sem_base"`, 12×0. Não há corte de
  recorrência nem mediana neste método: a média semestral já dilui a conta
  esporádica (soma ÷ 6), e a forma vem da linha, não da conta.
- `meses_com_dado` = nº de meses da base com movimento (0–6).

### Índice sazonal por linha da DRE (`indices`)

Calculado no serviço a partir de **24 meses fechados** (`HIST_CONTA_SQL` na janela
+ rollup conta→linha), passado PURO para a derivação:

```
media_cal[linha][m]  = média dos valores da linha no mês-calendário m na janela (2 amostras)
media_geral[linha]   = média dos 24 valores mensais da linha
indice[linha][m]     = media_cal[m] / media_geral, renormalizado para média 1
```

Guardas (linha vira **flat** — índice 1 nos 12 meses — e é marcada em
`linhas_flat` na resposta da geração):

- `|media_geral| < 1e-9` (linha sem massa);
- qualquer índice fora de **[0, 3]** (sinal oscilante ou pico que faria o
  orçamento trocar de sinal/explodir num mês — forma sem sentido econômico);
- menos de 24 meses de dados na janela para a linha.

A conta herda o índice da **sua linha** (folha do `DRE_MODELO`, com ajustes
locais aplicados — mesmo rollup de sempre). Conta sem linha já fica fora do
baseline (regra existente).

### Persistência e API

- `orc_versao` ganha coluna **`metodo`** (`'espelho'` default | `'semestre'`) —
  migração PRAGMA + `ALTER TABLE` como a de `meses_base`. `meses_base` gravado =
  os 6 meses → o motor de **meses circulares existente já faz** o acompanhamento
  ignorar jan–jun e comparar ago–dez de verdade (julho, fora da base, compara
  como parcial).
- `POST /api/controladoria/orcamento/gerar` aceita `"metodo"` (default
  `"espelho"`; valor fora do domínio → 422). **Regerar usa o método GRAVADO na
  versão** — o form da tela mostra o método da versão carregada, e o botão
  Regerar não muda método (mudar método = gerar versão nova).
- Rótulo sugerido pela tela ao escolher o método: "Orçamento {ano} — base
  {1S|2S}{aa}" (ex.: "Orçamento 2026 — base 1S26"), editável como hoje.
- Resposta da geração inclui `metodo`, `linhas_flat` (rótulos de linha que
  caíram no índice flat) e o já existente (`meses_circulares` etc.).

### Tela (aba Montagem)

- Select **Método**: "Mês espelho (12 meses)" | "Semestre × sazonalidade
  (últimos 6 meses)". O banner explicativo do card troca conforme o método.
- Grade: badge da origem `semestre` = **"base 1S26"** (texto calculado dos
  `meses_base` da versão; title explica nível × sazonalidade). A marca
  **"base fraca"** passa a ser: `origem == 'mediana'` OU `'sem_base'` OU
  (`'semestre'` E `meses_com_dado < 3`) — hoje o front marca tudo que não é
  espelho, o que carimbaria o método novo inteiro.
- Aviso pós-geração mostra as `linhas_flat` quando houver ("N linha(s) sem
  forma sazonal confiável — ficaram flat").

## 2. Provisão orçamentária no Fluxo de Caixa

### Conversão competência → caixa (`api/orcamento/caixa.py`, PURO)

```
provisao_caixa(valores_mensais, dso_dias, dpo_dias) -> list[{mes, entradas, saidas, geracao}]
```

- `valores_mensais` = por mês do orçamento (valor EFETIVO, coalesce ajuste):
  `entradas[mes]` = soma dos valores **positivos** por conta; `saidas[mes]` =
  soma dos **negativos** (o sinal do lançamento já separa receita de custo —
  mesma álgebra validada da cascata).
- Deslocamento fracionário por natureza: `x = dias / 30.44`; `k = floor(x)`,
  `f = x − k` → o valor do mês M cai `(1−f)` em `M+k` e `f` em `M+k+1`.
  Ex.: DSO 49d → x=1,61 → 39% em M+1 e 61% em M+2. Entradas usam DSO,
  saídas usam DPO. Valores que caem além de dezembro **saem do horizonte**
  (aparecem no total do tooltip como "transborda para {ano+1}").
- `geracao[mes] = entradas_caixa[mes] + saidas_caixa[mes]` (saídas são
  negativas).
- DSO/DPO vêm da medição viva que o fluxo já faz (`dso_3m`/`dpo_3m`);
  medição indisponível → **fallback fixo DSO 49 / DPO 79** (valores medidos em
  jul/26), com a origem declarada na resposta (`dso_fonte: "medido"|"padrao"`).

### Integração no `get_fluxo`

- Lê do `orcamento.db` a **versão mais recente do ano corrente**
  (`listar_versoes(ano)[0]`); calcula a provisão dos meses **≥ mês corrente**.
- Resposta ganha `provisao_orc`: `{versao: {id, rotulo, metodo}, dso, dpo,
  dso_fonte, meses: [{mes, entradas, saidas, geracao}]}`. Sem versão do ano, ou
  qualquer falha na leitura → campo ausente (try/except; o fluxo NUNCA quebra
  por causa do orçamento).
- SQLite é leitura local — custo desprezível; sem cache novo.

### Tela do Fluxo

- **Série "provisão orçamentária"** no gráfico principal: linha tracejada
  laranja (`--orange-500`) da `geracao` mensal, visível por padrão, nos meses
  futuros até onde o orçamento alcança (dezembro). Mesma ordem de grandeza das
  demais séries — não repete o footgun de escala do cenário especulativo.
- Tooltip da série: entradas orçadas, saídas orçadas, geração e o aviso de
  transbordo quando houver.
- ⓘ do card: "Provisão da versão '{rotulo}' do orçamento · competência
  deslocada por DSO {d}d / DPO {d}d ({medido|padrão}) · simplificação: impostos
  e folha têm prazos próprios, não modelados". Sem versão → a série simplesmente
  não aparece (sem banner de erro).

## 3. Erros e casos de borda

| Situação | Comportamento |
|---|---|
| Base de 6 meses incompleta | Bloqueia geração com a lista dos meses (como no espelho) |
| Linha sem 24m de histórico / índice fora de [0,3] / massa ~0 | Índice flat + rótulo em `linhas_flat` |
| Conta sem movimento no semestre | `sem_base`, 12×0 |
| `metodo` inválido no POST | 422 |
| Regerar versão `semestre` | Usa o método GRAVADO e re-deriva com a base semestral ATUAL (rolante, como o espelho re-deriva com a janela atual); `meses_base`/circulares atualizam juntos; ajustes preservados (motor existente) |
| Fluxo sem versão do ano corrente | Sem série, sem erro |
| DSO/DPO não mensuráveis | Fallback 49/79 declarado (`dso_fonte: "padrao"`) |
| Valor deslocado além de dezembro | Fora da série, declarado no tooltip |

## 4. Testes

- **Derivação semestral (pura):** nível = soma/6; aplicação do índice por linha;
  fator; conta sem movimento → sem_base; exemplo recomputável à mão (conta com
  6 meses de 100 e índice dez 0,6 → dez orça 60).
- **Índices (puros, sobre séries sintéticas):** normalização (média 1); guarda
  de sinal/faixa → flat; janela incompleta → flat.
- **caixa.py (puro):** split 39/61 com DSO 49; DPO 79 → 40/60 entre M+2 e M+3;
  transbordo de dezembro; entradas/saídas separadas por sinal; dso=0 → tudo no
  próprio mês.
- **Serviço/endpoints:** metodo inválido 422; regerar usa método gravado;
  versão espelho continua gerando byte-igual (regressão); get_fluxo com e sem
  versão do ano.
- Suíte atual (193) verde; smoke + estrutural 33/33.

## Critérios de aceite

1. Gerar "Orçamento 2026 — base 1S26": numa conta recorrente, o valor de um mês
   confere à mão (nível × índice × fator), e dezembro < média nas linhas com
   queda sazonal histórica.
2. Regerar a versão semestral preserva ajuste manual e mantém o método.
3. Grade mostra badge "base 1S26"; gerar pelo método espelho segue idêntico ao
   comportamento atual.
4. Fluxo de Caixa exibe a série tracejada: receita orçada de agosto vira entrada
   ~set/out (39%/61%), com DSO/DPO e procedência no ⓘ.
5. Sem versão do ano corrente, o fluxo carrega normalmente sem a série.
6. Acompanhamento da versão semestral: jan–jun circulares (fora do acumulado);
   julho e os demais meses comparam à medida que FECHAM (o acumulado só usa mês
   fechado — julho entra em agosto).
7. `pytest`, smoke e validador estrutural passam.

## Fora do escopo

- Prazos de caixa por natureza (impostos, folha) — Fase 2 da provisão.
- Workflow de aprovação de versões; orçamento 2027.
- Alterar o método espelho ou as versões existentes.
- Sazonalidade por conta individual (a forma é por linha da DRE).
