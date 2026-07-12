---
type: Service
title: Tempo real das torres (LISTEN/NOTIFY → WebSocket)
description: Pipeline de tempo real que leva ingestão do Postgres às torres ao vivo via WebSocket, sem polling pesado.
resource: docs/ARQUITETURA.md §5, §2
tags: [tempo-real, websocket, redis, torres, servico]
timestamp: 2026-07-11
---

# Definition

Ingestão grava no Postgres → trigger emite `NOTIFY` (ou publica no Redis pub/sub) → backend
repassa por **WebSocket** para o painel da torre. O histórico permanece nas hypertables.

# Notes

- Sem polling pesado; o dado ao vivo não é materializado (ex.: view [vw_viagens_ativas](../views/vw_viagens_ativas.md) é regular).
- Alimenta Torre de Controle ([tc_posicoes](../tables/tc_posicoes.md), [tc_ocorrencias](../tables/tc_ocorrencias.md)) e Torre de Segurança ([ts_eventos](../tables/ts_eventos.md)).
