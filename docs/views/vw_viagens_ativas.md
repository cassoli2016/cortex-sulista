---
type: Table
title: vw_viagens_ativas
description: View (não materializada) — viagens ativas com a última posição/ETA via LATERAL sobre tc_posicoes. Torre de Controle.
resource: sql/schema.sql
tags: [torre_controle, view, tempo-real]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE VIEW vw_viagens_ativas AS
SELECT v.id AS viagem_id, v.cliente_id, v.veiculo_id, v.status, v.fim AS previsao_fim,
       p.lat, p.lng, p.velocidade, p.eta, p.ts AS posicao_em
FROM op_viagens v
LEFT JOIN LATERAL (
    SELECT lat, lng, velocidade, eta, ts
    FROM tc_posicoes tp
    WHERE tp.viagem_id = v.id
    ORDER BY ts DESC LIMIT 1
) p ON true
WHERE v.status = 'ativa';
```

# Notes

- View **regular** (não materializada) — dado em tempo real, por isso não é materializada.
- `LEFT JOIN LATERAL` pega a última posição (`ts DESC LIMIT 1`) de cada viagem ativa.
- Fontes: [op_viagens](../tables/op_viagens.md), [tc_posicoes](../tables/tc_posicoes.md).
