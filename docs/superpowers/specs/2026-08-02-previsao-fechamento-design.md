# Previsão de Fechamento do Mês — Design

**Data:** 2026-08-02 · **Status:** aprovado em conversa (3 seções) · **Tela:** `fech` — "Fechamento do Mês" (Controladoria)

## 1. Contexto e objetivo

Prever o **resultado do mês** (DRE gerencial completa, cascata `DRE_MODELO`) antes de o mês fechar,
mesclando lançamentos contábeis, emissão de documentos fiscais, viagens/contratos de transporte,
ordens de compra, contas a pagar, abastecimentos e folha — para o gestor **controlar o resultado
durante o mês**, não descobri-lo depois.

Decisões de escopo tomadas com o usuário (2026-08-02):

1. **Alvo:** DRE gerencial completa, linha a linha (não só síntese, não caixa).
2. **Premissas:** automática + **ajustes manuais** por linha (padrão `valor_efetivo` do orçamento).
3. **Escopo temporal:** **mês corrente (M)** + **mês em fechamento (M-1)** enquanto o razão consolida.
4. **Abordagem:** **motor híbrido por linha** — cada linha da DRE usa a estratégia que a natureza
   do dado dela pede (aprovada contra as alternativas "extrapolação contábil pura" e "estatístico puro").

**Relação com o Orçamento:** a spec `2026-07-26-orcamento-design.md` reservou "Fase 2 = forecast".
Este módulo **é** essa fase para o horizonte intra-mês (fechamento de M e consolidação de M-1).
Rolling forecast de meses futuros permanece território do orçamento (fora de escopo aqui).

## 2. Fatos medidos que fundamentam o design (sondagem no AVA, 2026-08-02)

Latência de escrituração (`lancamento.dtinc`, date, nunca nulo — permite medir e reconstruir):

- No fim do próprio mês só **51–72%** do valor está escriturado (jun/26: 71,9%; média jan–jun: 59,6%).
  Intra-mês, ~50% da competência já decorrida está visível. O mês "fecha" em **D+5 (~97%)** e
  estabiliza em **D+10**; meses passados sofreram restatement até D+30+ (maio/26: +R$ 10,2 mi após 15/06).
- **Por linha** (jun/26, % escriturado até 30/06): receitas 3 fontes ~100 · impostos ~100 ·
  CV-manutenção 99,6 · CF-desp. ADM 97,4 · CF-locação 100 · CV-combustível 80 (98% em D+5) ·
  CV-frete terceiros 60 (fecha só D+10) · CV-frete agregados 47 (99,8% D+10) · CV-pedágio 38 (D+5) ·
  financeiras 26–57 (D+5) · **folha 10–24 (entra em BLOCO em D+3–5)**.

Drivers operacionais:

- **CT-e é D+0** (filtros canônicos: grupo=1, empresa=1, unidade=1, numero<1000000, situacaocte=3,
  tipo IN (1,4), sem cancelamento). NFS-e pequena e esparsa (~R$ 0,4 mi/mês, 20 dias de emissão).
  **`sulista.faturamentokmm` está MORTA desde 2023-05-31** — manter na soma (custa zero) mas
  documentar como descontinuada.
- **Meta diária** (`sulista.metafaturamento_agrupamentoclientedia` tipo=1) já carregada para o mês
  inteiro (ago/26: R$ 12.483.890,14 em 26 dias; domingos sem meta — a meta acumulada modela o calendário).
- **`programacaoembarque`** atualiza intra-dia (última inclusão 02/08 09:33) com `valorfrete` e
  `valorfretecompra`; **não há carteira futura** (0 viagens com `dtsaida` futura) — a projeção do
  restante do mês é estatística, não por backlog.
- **Acertos de agregados**: lag médio de 6,1 dias após a chegada; 31% do valor emitido em julho era
  de viagens de junho → `valorfretecompra` da viagem é a proxy antecipada do custo.
- **`sulista.ctaplus_abastecimentos`**: carga diária à meia-noite (dado até D-1).
- **Contas a pagar**: 99,7% do valor que vence em agosto já estava emitido antes do dia 1
  (R$ 6,29 mi) — carteira conhecida. OC aprovada não recebida é imaterial (~R$ 357 mil).
- Impostos efetivos calibrados sobre a RB (jan–jun/26, `config/dre_cliente_params.yaml`):
  federais 7,78% · estaduais 9,83% · municipais 0,13% · previdenciária 0,85% — estáveis mês a mês.

## 3. Arquitetura

```
api/previsao/
  __init__.py       # get_previsao_fechamento(...) — fachada
  sql.py            # queries AVA (razão MTD por agrupador, drivers, curva dtinc)
  completude.py     # PURO: curva de escrituração por linha (D+N -> fração esperada)
  motor.py          # PURO: estratégias por linha, cascata, cenários, merge de ajustes
  servico.py        # orquestração: fetch paralelo -> motor -> comparáveis -> snapshot
  armazenamento.py  # SQLite data/previsao.db (ajustes, snapshots diários, log)
scripts/backtest_previsao.py   # offline: roda o motor "as-of" datas passadas via dtinc
```

Fluxo de uma chamada (`GET /api/controladoria/previsao?mes=YYYY-MM`):

1. **Fetch paralelo** (ThreadPoolExecutor, conexão própria por grupo, padrão `get_visao_geral`):
   (a) razão do mês por agrupador — mesma base da DRE (`historico<>18`, planoconta ativa,
   `sulista.agrupadorgerencial`, **`ler_ajustes()` aplicado**, filtro `dtlancamento <= hoje`) para
   **bater ao centavo com a tela DRE**; (b) realizado fiscal diário × meta (reuso `VG_DIARIO_SQL`);
   (c) viagens MTD (`valorfrete`/`valorfretecompra` por modalidade, semaforo=1, sem cancelamento);
   (d) abastecimentos MTD (`ctaplus`); (e) contas a pagar por vencimento no mês;
   (f) curva de completude por linha (cacheada, recálculo 1×/dia).
2. **Rollup** agrupador → linha via `DRE_MODELO`/`_dre_aloca` (mesmo matching NFKD da DRE);
   sobras na linha `NAO ALOCADO / CLASSIFICAR`, como na DRE.
3. **Motor puro** por linha → `{realizado_contabil, comprometido, projetado, previsto_base,
   previsto_otimista, previsto_pessimista, estrategia, premissas[], ajuste?}` + cascata (fórmulas
   do `DRE_MODELO` com o sinal credor-positivo preservado — senão o RESULTADO DO EXERCICIO não fecha).
4. **Comparáveis**: orçado do mês por linha (`orcamento.armazenamento.versao_vigente` — aprovada >
   rascunho, nunca arquivada; `init_db` antes de ler; guarda de **mês circular** vs `meses_base`),
   meta comercial (receita), M-1 realizado.
5. **Snapshot diário** best-effort no SQLite (1 por dia × mês × linha) → série de evolução da
   previsão + erro medido após o fechamento real.

Cache: `@cached(ttl=300)` na fachada. Nada de escrita no AVA (réplica read-only).

## 4. Motor — mês corrente (M)

`previsto = conhecido + projeção do restante`, por estratégia:

| Linha | Estratégia | Regras |
|---|---|---|
| RECEITA BRUTA | `driver_fiscal` | realizado 3 fontes MTD + meta_restante × ritmo, onde ritmo = real_acum/meta_acum. **Piso de estabilidade**: ritmo_efetivo = w × ritmo_observado + (1−w) × atingimento médio dos últimos 3 meses fechados, com w = min(1, dias_uteis_decorridos/3) |
| IMPOSTOS FED/EST/MUN/PREV | `pct_receita` | % efetiva calibrada × receita prevista (recalibrar por semestre, não por mês) |
| ANULACOES, DESCONTOS | `sazonal` | nível × índice sazonal por linha (reuso `orcamento.derivacao.indices_sazonais`, mesmas guardas) |
| CV – FRETE AGREGADOS / TERCEIROS | `frete_compra` | conhecido = max(razão MTD, `valorfretecompra` viagens MTD); projeção = ritmo da receita × razão histórica custo/receita da modalidade (média 3 meses fechados) |
| CV – COMBUSTIVEL | `razao_x_driver` | razão MTD ÷ completude esperada; validação cruzada com `ctaplus` MTD — divergência >10% vira aviso na tela |
| CV – PEDAGIO e demais CV | `razao_completude` | razão MTD ÷ completude esperada da própria linha |
| CF-FOLHA MOT, CF-PESSOAL OP, OVERHEAD-FOLHA ADM | `nivel` | base = mediana dos 3 últimos meses fechados; o orçado da linha aparece como referência na tela, nunca substitui a base; rescisão/dissídio = ajuste manual |
| CF/ADM tempestivos (manutenção, locação, desp. ADM) | `razao_runrate` | razão MTD extrapolado por dias úteis × forma sazonal |
| FINANC, INDENIZACOES, RESULT. NÃO OPER., esporádicas | `sazonal` | idem ANULACOES; linhas flat sinalizadas |
| NAO ALOCADO / CLASSIFICAR | `runrate` | média 3 meses fechados (transparência, nunca omitir) |

Premissas de cada linha são **dados retornados** (lista de strings legíveis), não texto de UI.

## 5. Motor — mês em fechamento (M-1)

Por linha, com N = dias desde a virada do mês:

- `estimado = razão_parcial ÷ completude_esperada(linha, D+N)` (curva medida nos 6 meses
  fechados anteriores via `dtinc`, por linha).
- **Guarda de divisor**: completude esperada < 30% → usar a estratégia do mês corrente (nível/
  sazonal) em vez de dividir por quase-zero.
- **Trava de consolidação**: completude ≥ 97% → estimado = razão como está (linha "consolidada").
- A tela mostra **barra de consolidação** do mês ("razão de julho: 80% do esperado — faltam
  folha e fretes de terceiros") e o estimado converge para o real até D+10.
- Após D+10 e variação diária < 0,5%, o mês é tratado como fechado (a tela passa a apontar
  para a DRE oficial); restatements tardios continuam visíveis pela série de snapshots.

## 6. Cenários e calibração (backtest)

- Sempre **3 cenários** (regra da skill `previsao-projecao`): base = descrito acima;
  otimista/pessimista = base ± banda da linha.
- **Banda = erro histórico do próprio método naquele dia do mês**, medido pelo backtest
  (percentis 20/80 do erro por linha × dia útil; interpolação linear entre os dias calibrados
  5/10/15/20/25) — nunca ±X% arbitrário.
- `scripts/backtest_previsao.py`: usa `dtinc` para reconstruir o razão visível "as-of" os dias
  5/10/15/20/25 dos últimos 6 meses fechados, roda o motor e mede erro por linha × dia contra o
  valor final. Saídas: (a) tabela de calibração das bandas (versionada em `data/previsao_calibracao.json`);
  (b) relatório de precisão que é o **gate de aceite** antes do deploy; (c) evidência para escolher
  entre estratégias concorrentes. Limitação declarada: drivers operacionais (viagens/ctaplus) não têm
  "as-of" perfeito — o backtest desses usa a data do documento como aproximação e documenta isso.
- Exibição: base como número; banda como faixa no KPI e na tabela. **Nenhuma série especulativa
  divide escala com dado firme** (lição do Fluxo).

## 7. Ajustes manuais (SQLite `data/previsao.db`)

Padrão `auth.db`/`orcamento.db`: conexão curta, WAL, migração PRAGMA+ALTER, `init_db` idempotente.

```
prev_ajuste(mes TEXT 'YYYY-MM', linha TEXT, tipo TEXT 'delta'|'valor', valor REAL,
            motivo TEXT NOT NULL, autor TEXT, criado_em TEXT, PRIMARY KEY (mes, linha))
prev_snapshot(data TEXT 'YYYY-MM-DD', mes TEXT, linha TEXT, previsto_base REAL,
              previsto_otim REAL, previsto_pess REAL, realizado_contabil REAL,
              estrategia TEXT, PRIMARY KEY (data, mes, linha))
prev_log(id INTEGER PK, quando TEXT, autor TEXT, acao TEXT, detalhe TEXT)
```

- Efeito: `previsto_efetivo = previsto_calculado + delta` (ou `= valor` se tipo=valor); banda
  desloca junto. **Recalcular nunca apaga ajuste** (`coalesce`, princípio do orçamento).
- Ajuste é **por mês** — não migra para o mês seguinte; ajuste de mês já fechado vira aviso
  ("ajuste vencido") em vez de efeito.
- Motivo obrigatório; badge "ajustado" na linha; log de toda ação.
- Front: campo `type="text" + inputmode="decimal" + numBR()` (nunca `type="number"`).

## 8. API

- `GET /api/controladoria/previsao?mes=YYYY-MM` (default: mês corrente; aceita M-1) →
  `{mes, modo: 'corrente'|'fechando'|'fechado', dados_ate, consolidacao_pct, linhas[...],
  kpis{resultado_previsto, banda, orcado, desvio, breakeven, atingimento_receita},
  serie_snapshots[], avisos[], fontes[{nome, ok, atualizado_em}]}`
- `POST /api/controladoria/previsao/ajuste` `{mes, linha, tipo, valor, motivo}` (+ remoção com
  valor nulo); valida linha ∈ DRE_MODELO.
- RBAC: tela `fech` nos perfis Controladoria e Diretoria; rota registrada em `ROTA_TELAS` **antes**
  de prefixos genéricos; seed `perfis_modelo_vN` = próximo N vigente (conferir `auth.py` na implementação).

## 9. Tela (vista `fech`, grupo Controladoria, anatomia 5 camadas)

1. **KPIs**: resultado previsto (base + "entre X e Y"), vs orçado (cor pelo efeito no resultado,
   `invert` em custo), vs ponto de equilíbrio, atingimento de receita MTD, carimbo "dados até
   DD/MM · razão N% escriturado".
2. **Série**: evolução do previsto pelos dias do mês (snapshots) × linha do orçado; anotação
   quando a previsão muda materialmente.
3. **Cascata DRE**: colunas Realizado até hoje · Projetado · Previsto (base) · Banda · Orçado ·
   Desvio · % RL; badge de estratégia por linha; ⓘ de procedência com tabela/regra de origem;
   seletor M / M-1 (M-1 com barra de consolidação). Tabela rola no card (`.tabroll`) com contador.
4. **Maiores desvios**: top desvios previsto × orçado com leitura em texto (explicar o delta).
5. **Alertas**: os mesmos do digest, na tela.

Padrões obrigatórios: período incompleto nunca é barra cheia (hachura + "parcial"); semáforo
discreto; fonte + timestamp em todo card; entra na **gaveta mobile** e em `NAV_KW`.

## 10. Alertas e digest

`build_alertas` ganha: (a) "Resultado do mês em risco" — previsto base < orçado do mês (ou <
breakeven, o que for maior em severidade); (b) divergência combustível razão × ctaplus > 10%;
(c) ajuste manual vencido. Entram no digest diário das 07:00 e no painel de alertas existente.

## 11. Erros e degradação (nada derruba a tela)

- Banco/túnel fora → 503 `banco_inacessivel` (padrão dos endpoints).
- Orçamento sem versão do ano → coluna Orçado = "—" + aviso; previsão continua.
- Driver individual falho (ex.: ctaplus) → linha cai para o fallback declarado e a fonte aparece
  degradada (chip âmbar, padrão Copiloto); tudo em try/except por fonte.
- Snapshot/SQLite falho → best-effort, nunca quebra a resposta.
- SQL: PG 9.3 (sem FILTER/sintaxe moderna), strings **LATIN-1** (sem travessão/setas/unicode),
  agregação no banco, `SET LOCAL enable_mergejoin = off` em join (grupo,empresa), `%%` em LIKE.

## 12. Testes e validação (gate de aceite)

- **pytest puro** (sem banco): estratégias do motor uma a uma, cascata fecha (RESULTADO DO
  EXERCICIO = soma das partes), curva de completude, guarda de divisor <30%, trava 97%, blend dos
  3 primeiros dias úteis, merge de ajustes (recalcular preserva), cenários/bandas, mês circular.
- **Backtest com dado real** = gate: relatório de erro por linha × dia dos últimos 6 meses,
  revisado pelo usuário antes do deploy.
- Smoke Playwright da tela + `scratchpad/estrutura.py`; `ast.parse` antes de gravar `.py`;
  `node --check` no `<script>`; commit após entrega validada; deploy via AutoDeploy com verificação.

## 13. Fora de escopo v1 (extensões possíveis)

- Folha via GLOBUS/Oracle (razão entrega folha em D+5; nível estável; rescisões via ajuste manual).
- Previsão por filial (base contábil consolidada — `lancamento` sem filial).
- Rolling forecast de meses futuros (orçamento).
- Painel TV da previsão; previsão por cliente (a DRE por Cliente é a base natural de uma v2).

## 14. Riscos e limites declarados

- **Restatement tardio** é o limite físico: meses passados receberam 8–21% do valor após D+30.
  O snapshot diário torna isso visível; a tela nunca chama M-1 de "fechado" antes de D+10 estável.
- Primeiros 2–3 dias do mês: previsão de receita depende do blend (calendário distorce run-rate);
  a banda larga desses dias é honesta, não defeito.
- Estoque de contas a pagar vencidas (R$ 16 mi) pode virar desembolso do mês — afeta caixa, não
  competência; fica fora desta tela (é assunto do Fluxo).
- Duas classificações do razão coexistem (`DRE_MODELO` × `_DRE_GRUPO` do breakeven) — este módulo
  usa exclusivamente a primeira; o breakeven entra só como KPI de referência, com ⓘ dizendo a fonte.
