# Design — Módulo DRE por Cliente (v1: até Margem de Contribuição)

> Data: 2026-07-17 · Origem: `spec-margem-por-cliente.md` (interpretado e aterrissado na
> realidade do projeto) · Status: **aprovado** para desenvolvimento.

## Contexto que muda o spec literal

1. **Fonte de dados = ERP legado AVA** (`sulista`, PostgreSQL 9.3.25), acesso **read-only por
   túnel SSH** (`127.0.0.1:15432`), e é **réplica** (`pg_is_in_recovery=true`). Não é o schema
   `cortex`/TimescaleDB dos docs — esse não existe. **Impossível criar schema/tabela/migrations
   no banco de origem.**
2. A "ferramenta" é o app **Cortex Sulista**: FastAPI (`api/`) + SPA única
   (`api/static/index.html`), que lê o AVA ao vivo e **calcula tudo em Python/SQL com cache**.
   Não há camada analítica persistida hoje.
3. **Fase 0 do spec já está ~80% pronta e documentada:** DRE oficial (`get_dre`) já bate com
   `docs/dre_ia_analise.xlsx`; plano de contas = `sulista.agrupadorgerencial` + `planoconta.estrutural`;
   viagem/km canônico = `programacaoembarque`; cliente = `agrupamentocliente`; combustível =
   `ctaplus_abastecimentos`; manutenção = `ordemservico`.

## Decisões travadas (brainstorming)

- **Arquitetura:** live-compute + snapshots (não Postgres persistido / não ETL). A "camada
  analítica" do spec vira **motor de cálculo em Python + snapshots por mês fechado + params
  versionados em arquivo**.
- **Escopo v1:** cascata **até Margem de Contribuição**. CF por dia-veículo → Margem Direta do
  Cliente fica para **v2**.
- **Impostos/deduções e créditos tributários no v1:** por **% efetivo paramétrico** (não cálculo
  fiscal por CT-e/UF), calibrado para reconciliar com o razão.

## 1. Arquitetura e módulos

- Novo módulo **`api/dre_cliente.py`** (não tocar `queries.py`, já com ~3.158 linhas).
- Padrão de execução do projeto: **poucas queries pesadas no AVA + derivação em Python** (evita o
  merge-join catastrófico do PG 9.3). Regras herdadas: sempre `coalesce(credito,0)-coalesce(debito,0)`;
  excluir `historico=18` (apuração); SQL em **LATIN-1** (sem `—`/`→`/`≥`); joins por PKs completas;
  `SET LOCAL enable_mergejoin = off` quando o join for por (grupo,empresa).
- Endpoint **`GET /api/financeiro/dre-cliente?comp_de&comp_ate&filial`** em `api/main.py`.
- Nova vista SPA **"DRE por Cliente"** no grupo Financeiro (padrões do front: `qsView`/`LOADEDQS`,
  loaders `loadX/renderX`, `rep()` com assert, `ast.parse` antes de gravar `.py`).
- **Snapshots**: `data/dre_cliente/<YYYY-MM>.json` para meses fechados (idempotência + histórico +
  reload rápido). Mês aberto e **últimos 2 meses** sempre recalculados ao vivo.
- **Params versionados**: `config/dre_cliente_params.yaml` (alíquotas efetivas por imposto, % de
  créditos por natureza de custo, base de rateio intra-viagem, janela rolling da taxa R$/km).

## 2. Modelo de reconciliação (o coração)

A DRE oficial (`get_dre`) é o **total de controle** por linha × mês. Para cada linha L:

```
Σ_clientes(valor descido de L) + NAO_ALOCADO[L] + VARIACAO_ABSORCAO[L] = valor_DRE[L]
```

- `NAO_ALOCADO[L]` = **plug** contra o total oficial → reconcilia **por construção**. Métrica de
  qualidade = quão pequeno ele é (% de cobertura por linha).
- `VARIACAO_ABSORCAO[L]` = só nas linhas por **taxa** (manutenção/pneus): real do razão − absorvido.
- Linhas diretas (repasse agregado/terceiro): meta NAO_ALOCADO ≈ 0; desvio vira gap explicado.

## 3. Motor de custeio por linha — v1

Grão = **viagem** (`programacaoembarque`, `dtcancelamento IS NULL AND semaforo=1`); competência =
mês de término; cliente = `agrupamentocliente` (+ heurística p/ viagens sem coleta, já existente);
tipo de operação = `veiculo.utilizacaoveiculo` (FROTA/LOCACAO/AGR/TER).

| Linha DRE | Fonte / método v1 |
|---|---|
| Receita Bruta | `programacaoembarque.valorfrete` direto por viagem/cliente |
| Deduções (impostos) | % efetivo paramétrico sobre receita bruta do cliente (por imposto); plug em NAO_ALOCADO |
| CV Agregados/Terceiros | `valorfretecompra` direto (reconcilia com 4.1.1.08 do razão) |
| CV Combustível | custo por veículo próprio no mês (`ctaplus_abastecimentos`) rateado às viagens do veículo por km → cliente; AGR/TER não recebe (está no repasse) |
| CV Manutenção/Pneus | taxa R$/km (rolling 12m, `ordemservico`) × km viagem → absorvido; variância vs razão = VARIACAO_ABSORCAO |
| CV Pedágio / Seguro carga / Diárias / Carga-desc / Motoristas PX | direto por viagem/CT-e quando identificável; resíduo → NAO_ALOCADO |
| Créditos Tributários (redutores) | % paramétrico por natureza de custo gerador sobre os custos descidos; plug no consolidado |

Tudo abaixo de MC (custo fixo de ativo, folha op, overhead, indenizações, financeiro, não-operacional)
**não desce** no v1 — fica só no consolidado.

## 4. Km vazio

`tipo=3` (deslocamento vazio) atribuído ao cliente da viagem carregada que o originou. Regra de
desempate v1: **próxima viagem carregada do mesmo veículo** (documentada e testada). Alimenta
`%km_vazio` por cliente e o custo de combustível dos trechos vazios.

## 5. Saídas

- Vista **"DRE por Cliente"**: tabela hierárquica no **mesmo layout do `get_dre`** (linhas na
  ordem/nomenclatura oficiais, colunas = meses), cliente selecionável + colunas
  `NAO_ALOCADO`/`VARIACAO_ABSORCAO` de transparência.
- **Ranking** por MC% (v1) + indicadores por cliente/mês: `dias_veiculo`, `km_carregado`,
  `%km_vazio`, `MC%`, nº viagens, mix próprio×agregado×terceiro.
- **Memória de cálculo** por viagem (drill-down auditável) sob demanda.
- **Relação com `get_rentabilidade`:** coexistem. A nova é a versão bottom-up/reconciliável
  (autoritativa); a `rent` (CKM marginal misturado) pode ser aposentada **depois** de validada a
  nova. Nada é removido agora.

## 6. Validação (Fase 4 — bloqueia aceite)

Exige **túnel SSH no ar**. Reconciliação linha a linha vs `get_dre`/xlsx nos meses fechados de
2026; casos unitários (km vazio retorno/posicionamento; viagem multi-CT-e; CT-e cancelado →
ANULAÇÕES; complementar; viagem de agregado sem custo de ativo; virada de mês). Entregar
`docs/fase4-validacao.md`.

## Critérios de aceite (v1)

- [ ] `vw_dre_cliente` com nomenclatura/ordem idênticas ao `get_dre` (espelho da aba `Resumo`)
- [ ] Nenhum fixo de estrutura/overhead rateado por faturamento
- [ ] Km vazio atribuído a cliente e testado
- [ ] Créditos tributários descendo proporcionais aos custos geradores
- [ ] Ranking por MC% segmentado por tipo de operação
- [ ] Reconciliação: Σ clientes + NAO_ALOCADO + VARIACAO_ABSORCAO = DRE oficial, por linha/mês
- [ ] Cobertura (1 − NAO_ALOCADO/valor_DRE) reportada por linha; linhas diretas ~100%
- [ ] Zero credenciais em código ou histórico do git

## Fora do escopo v1 (v2)

Alocação de **CF por dia-veículo** (folha mot, IPVA, seguros, juros, depreciação próprio/locação)
→ **Margem Direta do Cliente** e ranking própria por MC/dia-veículo.
