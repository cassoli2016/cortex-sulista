---
type: Service
title: Topologia de infra local (docker-compose)
description: Topologia PostgreSQL-only do CÓRTEX — postgres (TimescaleDB), redis, ollama, api, web, integrations-worker e cloudflared, com variáveis de ambiente do .env.
resource: docker-compose.yml, .env.example
tags: [infra, docker, timescaledb, ollama, cloudflared, servico]
timestamp: 2026-07-11
---

# Definition

Infra local de referência (PostgreSQL-only). Serviços do `docker-compose.yml`:

| Serviço | Imagem / comando | Função |
|---|---|---|
| `postgres` | `timescale/timescaledb-ha:pg16` | Postgres 16 + TimescaleDB + pgvector; volume `pgdata` |
| `redis` | `redis:7-alpine` | cache/fila (refresh tokens, event bus Redis Streams, pub/sub) |
| `ollama` | `ollama/ollama:latest` | IA local (Gemma); volume `ollama`; GPU opcional via `deploy.resources` |
| `api` | build `./api` | FastAPI (RBAC, audit, orquestração) |
| `web` | build `./web` | Next.js |
| `integrations-worker` | build `./api` → `python -m integrations.worker` | scheduler de polling + consumidor do event bus |
| `cloudflared` | `cloudflare/cloudflared:latest` → `tunnel ... run --token ${CLOUDFLARE_TUNNEL_TOKEN}` | túnel de saída zero-trust (sem porta aberta) |

Volumes: `pgdata`, `ollama`. Todos `restart: unless-stopped`.

Variáveis de ambiente (`.env.example`, valores reais **nunca** versionados):

```
APP_ENV, APP_SECRET, JWT_TTL_MIN=15
POSTGRES_HOST=postgres, POSTGRES_DB=cortex, POSTGRES_USER=cortex_app, POSTGRES_PASSWORD
POSTGRES_INGEST_USER=cortex_ingest, POSTGRES_INGEST_PASSWORD   # role insert-only p/ telemetria
REDIS_URL=redis://redis:6379/0
OLLAMA_URL=http://ollama:11434, MODELO_LOCAL=gemma2:9b
ANTHROPIC_API_KEY   # opcional, SÓ p/ tarefa pesada SEM dado sensível
CLOUDFLARE_TUNNEL_TOKEN
```

# Notes

- **Role de ingestão separada** (`cortex_ingest`, insert-only) distinta da role de leitura analítica — hardening da §8 do [modelo_seguranca](../concepts/modelo_seguranca.md).
- Um único Postgres é a fonte da verdade; TimescaleDB cobre telemetria de alta cadência sem outro banco.
- `cloudflared` implementa a borda descrita em [cloudflare_edge](../services/cloudflare_edge.md); a app não abre porta pública.
- O `integrations-worker` é o [integrations_worker](integrations_worker.md); usa o [event_bus](event_bus.md) (Redis Streams).
- `ANTHROPIC_API_KEY` opcional: só para tarefa pesada sem dado sensível — roteamento de PII para externo é bloqueado (ver [gemma_gateway](gemma_gateway.md)).
- Observabilidade (Prometheus/Grafana/Loki) sobe junto — ver [observabilidade](observabilidade.md).
- Passo a passo de subida em [setup_dev](../runbooks/setup_dev.md).
