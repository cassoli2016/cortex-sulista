---
type: Table
title: op_viagens
description: Viagens (FTL) — tabela central da operação; base de RKM, CKM, retorno vazio e resultado por viagem. RLS por filial.
resource: sql/schema.sql
tags: [operacional, viagem, ckm, rkm, rls]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE op_viagens (
    id              serial PRIMARY KEY,
    cliente_id      int REFERENCES com_clientes(id),
    veiculo_id      int REFERENCES fro_veiculos(id),
    motorista_id    int REFERENCES rh_motoristas(id),
    rota_id         int REFERENCES op_rotas(id),
    km_carregado    numeric(10,1) NOT NULL DEFAULT 0,
    km_total        numeric(10,1) NOT NULL DEFAULT 0,
    receita_frete   numeric(14,2) NOT NULL DEFAULT 0,
    custo_variavel  numeric(14,2),             -- custo variável TOTAL apurado da viagem
    custo_fixo_rateado numeric(14,2),          -- fixo rateado p/ a viagem
    cte_id          text,
    modo            text NOT NULL DEFAULT 'proprio' CHECK (modo IN ('proprio','agregado')),
    status          text NOT NULL DEFAULT 'planejada', -- planejada|ativa|concluida|cancelada
    filial_id       int REFERENCES filiais(id),
    inicio          timestamptz,
    fim             timestamptz
);
CREATE INDEX ix_viagens_status ON op_viagens (status);
CREATE INDEX ix_viagens_cliente ON op_viagens (cliente_id, inicio);
```

# Notes

- **RLS habilitada** (`p_viagens_filial`) por `filial_id`.
- `modo` ∈ {`proprio`,`agregado`}; `status` ∈ {`planejada`,`ativa`,`concluida`,`cancelada`}.
- `custo_variavel`/`custo_fixo_rateado` preenchidos pelo ETL (custeio simplificado).
- Base das views [vw_rkm_cliente](../views/vw_rkm_cliente.md), [vw_ckm_viagem](../views/vw_ckm_viagem.md), [vw_resultado_viagem](../views/vw_resultado_viagem.md), [vw_viagens_ativas](../views/vw_viagens_ativas.md).
- Métricas derivadas: [rkm](../metrics/rkm.md), [ckm_bruto](../metrics/ckm_bruto.md), [ckm_produtivo](../metrics/ckm_produtivo.md), [retorno_vazio](../metrics/retorno_vazio.md), [resultado_viagem](../metrics/resultado_viagem.md).
- `cte_id` referencia o CT-e (fonte fiscal de receita).
