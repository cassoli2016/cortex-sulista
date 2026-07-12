---
type: Service
title: Observabilidade (Prometheus + Grafana + Loki)
description: Stack de métricas, dashboards e logs/alertas da plataforma.
resource: docs/ARQUITETURA.md §2, §7
tags: [observabilidade, prometheus, grafana, loki, servico]
timestamp: 2026-07-11
---

# Definition

- **Prometheus** — coleta de métricas.
- **Grafana** — dashboards e alertas.
- **Loki** — agregação de logs.

# Notes

- Sobe no `docker compose` local junto de postgres, redis, ollama, api, web, gateway, cloudflared.
- Complementa a trilha de auditoria de negócio em [audit_log](../tables/audit_log.md) e o log de tráfego de integrações em [int_webhook_log](../tables/int_webhook_log.md).
