# Extrato Bancário — importação e validação de saldos/fluxo (design)

Data: 2026-08-01 · Status: aprovado pelo usuário (brainstorming em sessão)

## Objetivo

Nova tela **`extb` — "Extrato Bancário"** no grupo **Financeiro**: importar extratos
bancários (OFX e CSV) das contas da empresa e **validar, dia a dia e por conta, se o
saldo e o fluxo (créditos/débitos) que o painel/ERP mostram batem com o banco real**.

Uso previsto: **acompanhamento diário** — a tela é um farol permanente por conta e a
divergência entra nos alertas do digest das 07:00.

Fora de escopo (decidido): conciliação lançamento a lançamento contra o movimento do
ERP (evolução futura possível — o dado importado é o mesmo); ler apenas a tabela
`extratobancario` do AVA (só tem 1 conta importada, não cobre as ~8 contas ativas).

## Contexto verificado no banco (2026-08-01)

- `contacorrente_saldo` (AVA): posição por conta×dia com `valorsaldo`, `valordebito`,
  `valorcredito`, `saldoanterior` — o lado ERP da comparação já existe pronto.
- Contas ativas em 2026: Itaú 341, Bradesco 237, Santander 33, Caixa 104, BB 1,
  Sicredi 748, Safra 422, 482 + pseudo-contas de meios de pagamento (eFrete 759,
  PEDAGIO/PAMCARD 9999, REPOM 758). Pseudo-contas só entram se o usuário subir
  extrato delas.
- `extratobancario` (AVA) tem 1 conta única importada (28.903 linhas até 29/07/2026) —
  insuficiente, por isso o upload.
- O AVA é **réplica somente-leitura** → toda escrita vai para SQLite local.

## Arquitetura

Subpacote **`api/extrato/`** (padrão do `api/orcamento/`):

- `armazenamento.py` — SQLite `data/extrato.db` (WAL, conexão curta, commit
  automático; `CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version` para migração).
- `parser.py` — parsers OFX e CSV, sem dependência externa.
- `comparacao.py` — agregação conta×dia do extrato + cruzamento com
  `contacorrente_saldo`.
- `servico.py` — orquestra import (parse → dedup → grava → resultado) e monta a
  resposta do painel.

### Modelo de dados (SQLite)

| Tabela | Conteúdo |
|---|---|
| `conta` | Identificação da conta no arquivo (banco/agência/conta do OFX ou rótulo do CSV), rótulo amigável, chave ERP (`erp_banco`, `erp_agencia`, `erp_conta` — casa com `contacorrente_saldo`) e, para CSV, o mapeamento de colunas salvo (JSON). Única por identificação de arquivo. |
| `lancamento` | Uma transação do extrato: `conta_id`, `dt`, `valor` com sinal (crédito +, débito −), `tipo` C/D, `historico`, `numerodoc`, `fitid`, `importacao_id`. |
| `importacao` | Trilha de upload: arquivo, formato, conta, período coberto, linhas novas × duplicadas ignoradas × não parseadas, timestamp. |
| `saldo_extrato` | Saldo final informado pelo arquivo (LEDGERBAL do OFX) por conta×data — âncora do saldo derivado. |

**Dedup (idempotência de re-upload):** por `(conta_id, fitid)` quando o OFX traz
FITID; sem FITID (CSV), hash de `(conta_id, dt, valor, historico, seq_no_dia)`.
Subir o mesmo arquivo duas vezes não duplica nada e o resultado informa
"N duplicadas ignoradas".

**Desfazer:** apagar uma importação remove seus lançamentos (`importacao_id`).
Não há edição/exclusão de lançamento individual (decidido).

### Parsers

- **OFX 1.x (SGML) e 2.x (XML)** — formato dos internet bankings brasileiros.
  Extrai BANKACCTFROM (banco/agência/conta), STMTTRN (DTPOSTED, TRNAMT, TRNTYPE,
  FITID, MEMO, CHECKNUM) e LEDGERBAL. Encoding: tenta utf-8, fallback
  latin-1/cp1252 (comum em OFX de banco BR).
- **CSV genérico com mapeamento por conta**: no primeiro upload de uma conta CSV o
  backend devolve preview das primeiras linhas; o usuário aponta na tela qual coluna
  é data / valor (ou crédito+débito separados) / histórico / documento; o mapeamento
  fica salvo na `conta` e os próximos uploads são diretos. Valores em formato BR
  (`1.234,56`) com parse estrito (regra do `numBR`: regex antes de converter; ponto
  em grupos de 3 é milhar); datas `DD/MM/AAAA`. Linhas de cabeçalho/rodapé/saldo que
  não parseiam são ignoradas e contadas no resultado.

### Comparação (conta×dia)

Lado extrato: soma de créditos, soma de débitos, líquido e **saldo derivado**
(âncora = LEDGERBAL mais próximo + acumulado dos lançamentos; sem âncora, compara só
fluxo e marca saldo como "sem âncora"). Lado ERP: `valorcredito`, `valordebito`,
`valorsaldo` de `contacorrente_saldo`. Tolerância **R$ 0,01**.

Estado por dia: `OK` · `DIVERGE` (com delta de crédito/débito/saldo) · `SO_EXTRATO`
(dia existe no extrato e não no ERP) · `SO_ERP`.

Farol por conta = último dia coberto pelo extrato: **verde** (bate), **vermelho**
(diverge), **âmbar** (conta sem mapeamento ERP), **cinza** (último upload > 7 dias —
"extrato desatualizado").

### Endpoints (main.py) e RBAC

- `GET /api/financeiro/extrato` — painel completo: KPIs, farol por conta, comparação
  dia a dia (parâmetros: conta, `dt_de`, `dt_ate`), lançamentos por dia expandido,
  importações recentes.
- `POST /api/financeiro/extrato/importar` — upload multipart (aceita múltiplos
  arquivos); responde resultado por arquivo (novas/duplicadas/não parseadas) ou
  pedido de mapeamento (conta nova / CSV sem mapa de colunas).
- `POST /api/financeiro/extrato/mapear` — grava vínculo conta-arquivo ↔ conta-ERP
  e/ou mapa de colunas CSV.
- `DELETE /api/financeiro/extrato/importacao/{id}` — desfazer.
- `GET /api/financeiro/extrato/contas-erp` — endpoint leve (cacheado) com as contas
  de `contacorrente_saldo` para o select do mapeamento.
- RBAC: tela `extb` em TELAS + rotas em ROTA_TELAS (específicas antes das genéricas)
  + perfil Financeiro; seed `perfis_modelo_v12`.
- Cache: `get_extrato` **sem** `@cached` longo (dado local muda a cada upload) —
  TTL curto (≤15s) ou invalidação após import.

## Tela (front `index.html`, vista `extb`)

Anatomia (padrão dashboard-builder):

1. **KPIs**: contas monitoradas · dias validados no período · dias divergentes ·
   maior diferença do período · último upload. Farol cinza no KPI de upload se a
   conta mais recente passar de 7 dias.
2. **Farol por conta** (tabela): banco/conta (rótulo), último dia com extrato,
   saldo extrato × saldo ERP no dia, delta com semáforo, dias sem extrato; conta sem
   mapeamento em âmbar com botão "mapear" (abre o modal).
3. **Comparação dia a dia** (filtros: conta + período `grpEmi`): créditos/débitos/
   saldo dos dois lados e delta por dia; **linha expansível** (`forn-row/forn-det`)
   abre os lançamentos do extrato do dia (data, valor, tipo, histórico, documento).
   `.tabroll` + contador "X de Y".
4. **Uploads recentes**: arquivo, período, novas × duplicadas, botão desfazer
   (confirmação antes).
5. **Upload**: botão + drag&drop; modal de mapeamento para conta nova (select do
   `/contas-erp`) e para colunas de CSV (preview + selects).

Padrões obrigatórios: ⓘ de procedência em todo card; entrada de valor nunca
`type=number` (texto + `inputmode=decimal` + `numBR`); datas locais `_iso()`;
`fmtDT()` na exibição; **sem `—` dentro de SQL** (LATIN-1); badge em card que não
segue os filtros; link na sidebar **e na gaveta mobile** (preferência permanente);
entradas em VIEWS/VIEW_GROUP/DATAMAP/LOADMAP/qsView; `rep()` com assert e
`ast.parse`/`node --check` antes de gravar patches.

## Alertas (api/alertas.py)

- "Extrato: conta X divergiu R$ Y em DD/MM" — último dia validado de cada conta.
- "Extrato: conta X sem atualização há N dias" — só contas já mapeadas.
Ambos entram no `build_alertas` (digest 07:00 + tela de alertas).

## Erros

- Arquivo ilegível/formato desconhecido → HTTP 422 com motivo claro (mostrado no
  toast/resultado do upload).
- OFX sem FITID → dedup por hash (transparente).
- Encoding: utf-8 → latin-1 fallback.
- CSV com linhas não parseáveis → ignoradas e contadas ("3 linhas não parseadas").
- Upload de conta não mapeada → resposta estruturada pedindo mapeamento (não é erro).

## Testes (`tests/extrato/`, puros, sem AVA)

- Parsers: fixtures OFX (1.x SGML e 2.x XML, latin-1 e utf-8) e CSV (layout BR)
  anonimizadas.
- Dedup: re-upload idempotente; CSV sem FITID.
- Comparação: dia OK, divergente (cada delta), SO_EXTRATO/SO_ERP, tolerância 0,01,
  saldo derivado com e sem âncora.
- Mapeamento CSV: aplicação do mapa de colunas salvo.
- Validação final no navegador (Playwright, harness do scratchpad com auth isolada)
  antes de commit/deploy (AutoDeploy: fetch origin/main fast-forward).

## Critério de sucesso

Subir o OFX de uma conta real e ver, para cada dia do período, verde quando
`contacorrente_saldo` bate ao centavo com o banco e vermelho com o delta quando não
bate — e a divergência aparecer no digest do dia seguinte.
