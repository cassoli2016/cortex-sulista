---
type: Concept
title: Plano de contas de referência (config/plano_contas.yaml)
description: Plano de contas da transportadora usado pela skill analista-contabil; grupo casa com fin_dre.grupo. Inclui roteamento automático por fornecedor e por tipo canônico das integrações.
resource: config/plano_contas.yaml
tags: [contabil, dre, plano-de-contas, financeiro, rateio]
timestamp: 2026-07-11
---

# Definition

Plano de contas de referência (transportadora) usado pela skill `analista-contabil`. O `grupo` casa com [fin_dre](../tables/fin_dre.md)`.grupo`: `receita | custo_var | custo_motorista | fixo | adm | fin`.

```yaml
contas:
  "3.1.1": {desc: "Receita de fretes (CT-e)",        grupo: receita}
  "3.1.9": {desc: "Outras receitas operacionais",    grupo: receita}
  "4.1.1": {desc: "Combustível (diesel)",            grupo: custo_var}
  "4.1.2": {desc: "Arla 32",                         grupo: custo_var}
  "4.1.3": {desc: "Pedágio",                         grupo: custo_var}
  "4.1.4": {desc: "Manutenção (peças + serviços)",   grupo: custo_var}
  "4.1.5": {desc: "Pneus e recapagem",               grupo: custo_var}
  "4.1.6": {desc: "Frete de terceiros / agregados",  grupo: custo_var}
  "4.2.1": {desc: "Salários de motoristas",          grupo: custo_motorista}
  "4.2.2": {desc: "Encargos sobre motoristas",       grupo: custo_motorista}
  "4.2.3": {desc: "Diárias / pernoite",              grupo: custo_motorista}
  "4.3.1": {desc: "Depreciação de frota",            grupo: fixo}
  "4.3.2": {desc: "Seguros (casco/RCTR-C/RCF-DC)",   grupo: fixo}
  "4.3.3": {desc: "Licenciamento / ANTT / IPVA",     grupo: fixo}
  "4.3.4": {desc: "Telemetria / rastreamento",       grupo: fixo}
  "5.1.1": {desc: "Pessoal administrativo",          grupo: adm}
  "5.1.2": {desc: "Ocupação (aluguel/utilidades)",   grupo: adm}
  "5.1.3": {desc: "TI / software",                   grupo: adm}
  "5.2.1": {desc: "Juros e encargos",                grupo: fin}
  "5.2.2": {desc: "Tarifas bancárias",               grupo: fin}
  "5.3.1": {desc: "Receitas financeiras",            grupo: fin}
  "9.9.9": {desc: "A CLASSIFICAR (transitória)",     grupo: adm}

# Roteamento automático por tipo de fornecedor (sup_fornecedores.tipo)
por_fornecedor:
  posto:    "4.1.1"
  oficina:  "4.1.4"
  agregado: "4.1.6"

# Roteamento por tipo canônico das integrações
por_tipo_canonico:
  abastecimento: "4.1.1"
  pedagio:       "4.1.3"
  doc_fiscal:    "3.1.1"
  titulo_financeiro: "5.2.1"

rateio:
  direcionador_padrao: km   # km | receita | viagens
  confianca_minima_auto: 0.7  # abaixo disso vai para revisão humana
```

# Notes

- `9.9.9 A CLASSIFICAR` é a conta transitória para lançamentos ainda não classificados.
- `por_fornecedor` roteia a conta a partir de [sup_fornecedores](../tables/sup_fornecedores.md)`.tipo` (posto→4.1.1, oficina→4.1.4, agregado→4.1.6).
- `por_tipo_canonico` liga os eventos canônicos das integrações à conta contábil (ver [canonical_event](../apis/canonical_event.md) e [normalizer](../services/normalizer.md)).
- `rateio.confianca_minima_auto: 0.7` — classificações automáticas abaixo de 0.7 de confiança vão para revisão humana antes de gravar em [fin_lancamentos](../tables/fin_lancamentos.md).
- Base da DRE gerencial: os grupos alimentam [fin_dre](../tables/fin_dre.md) e a view [vw_dre_mensal](../views/vw_dre_mensal.md).
