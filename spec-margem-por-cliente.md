# Spec — Módulo de Margem por Cliente (DRE gerencial de transportadora)

> Uso: cole como prompt inicial no Claude Code (dentro do repo, com acesso ao banco), ou como input do `/speckit-specify`. Executar as fases em ordem e **parar para aprovação ao fim da Fase 0 e da Fase 1**.
>
> **Modelo de referência:** a DRE mensal consolidada da empresa (arquivo `dre_ia_analise.xlsx`, aba `Resumo`). A DRE por cliente deve usar **o mesmo plano de contas, mesma nomenclatura e mesma ordem de linhas** — o consolidado dos clientes precisa reconciliar linha a linha com essa DRE.

## Objetivo

Pipeline mensal automático que produz a DRE por cliente custeada de baixo pra cima (por viagem/CT-e), **sem rateio por faturamento**, espelhando o plano de contas da DRE oficial, com ranking por margem de contribuição por dia-veículo (frota própria) e por MC% (agregados/terceiros).

## Restrições gerais

- Conexão ao banco exclusivamente via variável de ambiente (`DATABASE_URL`). Nunca hardcodar credenciais em código, spec ou commit.
- Não inventar schema: descobrir primeiro (Fase 0), propor mapeamento, só então criar a camada analítica.
- Camada analítica em schema separado (ex.: `dre_gerencial`), sem alterar tabelas transacionais.
- Cálculo idempotente: rodar duas vezes o mesmo período fechado produz o mesmo resultado.
- Parâmetros de negócio em tabela versionada com vigência, nunca constantes no código.

---

## Formato de saída — DRE por cliente (espelho da DRE oficial)

```
RECEITA BRUTA
(−) DEDUÇÕES DA RECEITA
      IMPOSTOS FEDERAIS · IMPOSTOS ESTADUAIS · IMPOSTOS MUNICIPAIS
      CONTRIBUIÇÃO PREVIDENCIÁRIA S/ RB · ANULAÇÕES · DESCONTOS
= RECEITA LÍQUIDA
(−) CUSTO VARIÁVEL (mesma abertura da DRE: COMBUSTÍVEL, FRETE AGREGADOS,
      FRETE TERCEIROS, DIÁRIAS DE MOTORISTAS, MANUTENÇÃO, SINISTROS VEÍCULOS,
      PNEUS, PEDÁGIO, SEGURO DE CARGA, CARGA E DESCARGA, MOTORISTAS PX, OUTROS CV)
(+) CRÉDITOS TRIBUTÁRIOS (sobre os custos geradores de crédito do cliente)
= MARGEM DE CONTRIBUIÇÃO
(−) CUSTO FIXO DO ATIVO (linhas CF alocáveis por dia-veículo — ver de-para)
= MARGEM DIRETA DO CLIENTE
```

Indicadores por cliente/mês: `dias_veiculo`, `km_carregado`, `km_vazio`, `%km_vazio`, `MC%`, **`MC por dia-veículo`**, nº de viagens, mix próprio × agregado × terceiro.

As linhas que **não descem** (fixo de estrutura, overhead, indenizações, financeiro, não operacional) permanecem apenas no consolidado, garantindo a ponte: `Σ margem direta dos clientes − fixos de estrutura = LUCRO BRUTO da DRE oficial` (± variação de absorção, ver abaixo).

## De-para: linha da DRE → método de descida para cliente

| Linha (DRE Resumo) | Desce? | Método de alocação |
|---|---|---|
| RECEITA BRUTA | Sim | Direto por CT-e |
| IMPOSTOS FEDERAIS / ESTADUAIS / MUNICIPAIS | Sim | Calculado por CT-e com alíquota real da rota/UF e regime |
| CONTRIBUIÇÃO PREVIDENCIÁRIA S/ RB | Sim | % paramétrico sobre receita bruta do CT-e |
| ANULAÇÕES | Sim | CT-e anulado/cancelado vinculado ao cliente de origem |
| DESCONTOS | Sim | Direto por CT-e |
| CV - COMBUSTÍVEL | Sim | Abastecimento vinculado à viagem; fallback: km_total × consumo (telemetria → média 3m do veículo → média da categoria) × preço médio do estoque |
| CV - FRETE AGREGADOS | Sim | Direto por viagem (repasse do agregado) |
| CV - FRETE TERCEIROS | Sim | Direto por viagem |
| CV - DIÁRIAS DE MOTORISTAS | Sim | Direto por viagem |
| CV - MANUTENÇÃO | Sim | Taxa R$/km do veículo (rolling 12m) × km_total da viagem; diferença p/ o real do mês vira **variação de absorção** no consolidado |
| CV - PNEUS | Sim | Idem manutenção |
| CV - SINISTROS VEÍCULOS | Sim | Viagem do evento, com flag `evento_extraordinario` (visões com/sem sinistro) |
| CV - PEDÁGIO | Sim | Valor real da viagem; fallback tabela de rota |
| CV - SEGURO DE CARGA | Sim | Por CT-e (ad valorem sobre valor da mercadoria) |
| CV - CARGA E DESCARGA | Sim | Direto por viagem/CT-e |
| CV - MOTORISTAS PX | Sim | Direto por viagem |
| CV - OUTROS CUSTOS VARIÁVEIS | Parcial | Direto quando identificável à viagem; resíduo fica no consolidado como "não alocado" |
| CRÉDITOS TRIBUTÁRIOS | Sim | % paramétrico por natureza de custo gerador (combustível, pneus, manutenção, frete contratado…) aplicado sobre os custos descidos ao cliente; resíduo no consolidado |
| CF - FOLHA MOT | Sim | Dia-veículo alocado ao cliente |
| CF - RASTREAMENTO | Sim | Dia-veículo |
| CF - GERENCIAMENTO DE RISCO | Sim | Dia-veículo (mantida a classificação atual como CF) |
| CF - IPVA/LICENCIAMENTOS | Sim | Dia-veículo |
| CF - SEGURO DE VEÍCULOS | Sim | Dia-veículo |
| CF - SEGURO AMBIENTAL | Sim | Dia-veículo |
| CF - SEGURO PATRIMONIAL | Não | Consolidado (patrimônio, não ativo rodante) |
| CF - JUROS DE FINANCIAMENTOS | Sim | Dia-veículo do veículo financiado |
| CF - DEPRECIAÇÃO OPERACIONAL | Sim | Dia-veículo do veículo **próprio** |
| CF - LOCAÇÃO DE EQUIPAMENTOS | Sim | Dia-veículo do veículo **locado** (substitui depreciação+juros no custo/dia dele) |
| CF - PESSOAL OPERACIONAL | Não | Consolidado — fixo de estrutura, não rateia |
| CF - DESPESAS ADM (do CSP) | Não | Consolidado |
| OVERHEAD (ADM + FOLHA ADM) | Não | Consolidado |
| INDENIZAÇÕES (cíveis/trabalhistas) | Não | Consolidado |
| OUTRAS DESPESAS/RECEITAS OPERACIONAIS | Não | Consolidado |
| RESULTADO FINANCEIRO E NÃO OPERACIONAL | Não | Consolidado |

## Regras críticas

- **Km vazio:** todo trecho vazio (posicionamento e retorno) é atribuído ao cliente da viagem carregada que o originou; vazio de posicionamento pertence ao cliente da próxima carga. Documentar e testar a regra de desempate.
- **Viagem multi-cliente:** custos da viagem rateados entre CT-es por peso ou receita **dentro da viagem** (parametrizável). Único rateio permitido.
- **Tipo de operação por viagem** (`propria` | `agregado` | `terceiro`): agregado/terceiro não recebe combustível, manutenção, pneus nem custo fixo de ativo — só repasse, GR, seguro de carga e pedágio quando pago pela empresa. Dado o peso de FRETE AGREGADOS na DRE, **toda saída deve permitir corte por tipo de operação**; o ranking por dia-veículo vale só para frota própria, agregados ranqueiam por MC%.
- **Frota mista própria × locada:** o `custo_dia_fixo` de cada veículo usa depreciação+juros (próprio) **ou** locação (locado) — nunca ambos.
- **Grão:** viagem (1 veículo, 1 deslocamento, 1..N CT-es). Se não existir entidade viagem, derivar por veículo + janela temporal + rota e documentar a heurística.
- **Competência:** mês da data de término da viagem. CT-e cancelado sai (vai para ANULAÇÕES); complementar soma ao original.

---

## Fase 0 — Descoberta do schema (sem escrever código de cálculo)

1. Inventariar tabelas/colunas de: CT-e/faturamento, viagens/ordens, clientes, veículos (com flag próprio/locado/agregado), motoristas, abastecimentos, pedágios, manutenção/pneus, folha/diárias, contratos de agregados, telemetria/odômetro, **plano de contas/lançamentos contábeis** (origem das linhas da DRE Resumo).
2. Mapear cada linha da tabela de de-para acima para `tabela.coluna` de origem, com granularidade e qualidade (completo/parcial/ausente).
3. Identificar como a DRE oficial é gerada hoje (quais contas contábeis agregam em cada linha) — esse agrupador vira a tabela `plano_contas_dre`.
4. Listar gaps com fallback proposto.
5. **Entregar `docs/fase0-mapeamento.md` e aguardar aprovação.**

## Fase 1 — Camada analítica (migrations versionadas)

- `dim_cliente`, `dim_veiculo` (categoria; próprio/locado; ativo/inativo)
- `plano_contas_dre` — conta contábil → linha DRE → método de descida (`direto_cte` | `direto_viagem` | `taxa_km` | `dia_veiculo` | `credito_proporcional` | `nao_desce`)
- `fato_viagem` — veículo, motorista, tipo_operacao, datas, km carregado, km vazio atribuído, dias de alocação
- `fato_cte` — cliente, viagem_id, componentes de receita, deduções calculadas, receita líquida
- `custo_km_veiculo` (manutenção e pneus, rolling 12m) e `custo_dia_fixo_veiculo` (linhas CF alocáveis ÷ dias disponíveis)
- `param_negocio` com vigência (`valido_de`, `valido_ate`): alíquotas, % créditos por natureza, % contribuição previdenciária, preço diesel fallback, base de rateio intra-viagem

**Entregar DDL + diagrama e aguardar aprovação.**

## Fase 2 — Cálculo

- Job idempotente `calcular_dre_cliente(ano, mes)` → `dre_cliente_mensal` (uma linha por cliente × linha da DRE) + indicadores.
- `dre_viagem_detalhe`: memória de cálculo por viagem — cada número do cliente auditável até a viagem.
- Linhas de fechamento no consolidado: `NAO_ALOCADO` (por linha DRE) e `VARIACAO_ABSORCAO` (manutenção/pneus real − absorvido).

## Fase 3 — Saídas

- `vw_dre_cliente` no formato exato da DRE oficial (linhas na mesma ordem/nomenclatura, colunas = meses — mesmo layout da aba `Resumo`).
- `vw_ranking_clientes`: frota própria por MC/dia-veículo; agregados/terceiros por MC%; colunas de receita, MC%, margem direta, %km vazio, dias-veículo, viagens.
- Refresh no fechamento + recálculo retroativo de 2 meses (lançamentos tardios).
- Export/endpoint para o BI existente (identificar na Fase 0).

## Fase 4 — Validação (bloqueia o aceite)

1. **Reconciliação linha a linha:** para cada linha da DRE e cada mês, `Σ clientes + NAO_ALOCADO + VARIACAO_ABSORCAO = valor da DRE Resumo`. Tolerância zero em linhas de método direto; variação de absorção documentada nas linhas por taxa.
2. Σ dias-veículo alocados ≤ dias disponíveis da frota no mês.
3. Casos unitários: km vazio de retorno; vazio de posicionamento; viagem multi-CT-e; CT-e cancelado (ANULAÇÕES); complementar; viagem de agregado (sem custo de ativo); veículo locado (locação, sem depreciação); sinistro com flag; viagem cruzando virada de mês.
4. Rodar os meses já fechados de 2026 e comparar com o `dre_ia_analise.xlsx`; divergências explicadas linha a linha em `docs/fase4-validacao.md`.

## Critérios de aceite

- [ ] Fase 0 aprovada antes de qualquer DDL; Fase 1 aprovada antes do cálculo
- [ ] `vw_dre_cliente` com nomenclatura e ordem idênticas à aba `Resumo`
- [ ] Nenhum fixo de estrutura/overhead rateado por faturamento em nenhum ponto
- [ ] Km vazio atribuído a cliente e testado
- [ ] Créditos tributários descendo proporcionais aos custos geradores
- [ ] Ranking segmentado: própria (MC/dia-veículo) × agregado/terceiro (MC%)
- [ ] Reconciliação da Fase 4 passando nos meses históricos contra o xlsx
- [ ] Zero credenciais em código ou histórico do git
