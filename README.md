# CÓRTEX — Cérebro de Gestão da Transportadora

Portal centralizado de inteligência (operacional, financeira, estratégica) com IA local
(Gemma) e agentes especialistas por área. Frota mista (própria + agregados), FTL.
**Base de dados única: PostgreSQL** (+ TimescaleDB para séries temporais, + pgvector para RAG).

## Onde está o quê
- `CLAUDE.md` ............ contexto-mestre lido por todo agente. **Comece aqui.**
- `docs/ARQUITETURA.md` .. stack PostgreSQL-only, TimescaleDB, modelo de dados, tempo real.
- `docs/SEGURANCA.md` .... zero-trust, RBAC+RLS, LGPD, acesso externo, go-live.
- `docs/INTEGRACOES.md` .. Central de Integrações: arquitetura de plugins, interface de conector.
- `docs/GUIA_CLAUDE_CODE.md` passo a passo de arranque no Claude Code + prompts por fase.
- `sql/schema.sql` ....... schema consolidado (referência); `sql/blocks/` aplicado por migrations.
- `migrations/` .......... Alembic (env.py + versions 0001..0006, head = schema completo).
- `pyproject.toml` ....... deps de backend + alembic (raiz).
- `.claude/agents/` ...... 14 agentes (orquestrador + 13 áreas, inclui integrações).
- `.claude/skills/` ...... 16 skills com código de referência.
- `config/parametros.yaml` parâmetros de negócio (CKM, jornada, metas, telemetria...).
- `.env.example` ......... segredos (copie p/ .env, NUNCA versione).
- `docker-compose.yml` ... infra local (imagem TimescaleDB + Ollama + Cloudflared).

## Áreas cobertas
Financeiro/DRE · Comercial · Operacional/CKM · Programação de cargas · Torre de Controle ·
Torre de Segurança · Telemetria avançada · Frota · Jornada (Lei 13.103) · Suprimentos/agregados ·
Gestão (metas/KPIs/OKRs/atas) · Previsões e projeções · Central de Integrações (hub de APIs).

## Padrão de dashboards
Toda tela segue `.claude/skills/dashboard-builder` — anatomia, design system e o spec de cada
torre/área. Tempo real via WebSocket (LISTEN/NOTIFY); analítico via views materializadas.

## Começar a desenvolver
Siga `docs/GUIA_CLAUDE_CODE.md` (ou rode `bash scripts/bootstrap.sh`).
Roadmap em CLAUDE.md §10. Fase 1 = auth + RBAC + RLS + audit + financeiro.
