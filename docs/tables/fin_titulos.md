---
type: Table
title: fin_titulos
description: Títulos a receber/pagar — base do fluxo de caixa e do aging de recebíveis. RLS por filial. Dado financeiro sensível.
resource: sql/schema.sql
tags: [financeiro, caixa, rls, sensivel]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fin_titulos (
    id          serial PRIMARY KEY,
    tipo        text NOT NULL CHECK (tipo IN ('receber','pagar')),
    cliente_id  int REFERENCES com_clientes(id),
    fornecedor_id int REFERENCES sup_fornecedores(id),
    valor       numeric(14,2) NOT NULL,
    emissao     date NOT NULL,
    vencimento  date NOT NULL,
    baixa       date,
    status      text NOT NULL DEFAULT 'aberto', -- aberto|pago|atrasado|cancelado
    cte_id      text,
    filial_id   int REFERENCES filiais(id)
);
CREATE INDEX ix_titulos_venc ON fin_titulos (vencimento, status);
CREATE INDEX ix_titulos_tipo ON fin_titulos (tipo, status);
```

# Notes

- **RLS habilitada** (`p_titulos_filial`) por `filial_id`.
- `tipo` ∈ {`receber`,`pagar`}; `status` ∈ {`aberto`,`pago`,`atrasado`,`cancelado`}.
- Dado financeiro sensível — não roteia para a Claude API.
- Base da view [vw_fluxo_caixa](../views/vw_fluxo_caixa.md); `baixa` marca a liquidação.
- Liga a [com_clientes](com_clientes.md) e [sup_fornecedores](sup_fornecedores.md).
