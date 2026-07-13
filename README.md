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

## Rodar nesta máquina (Windows — produção local)
1. Túnel SSH ao ERP AVA. **Uma vez**, instale a chave (pede a senha só nesta vez):
   `powershell -ExecutionPolicy Bypass -File scripts\instalar_chave_erp.ps1`
   Depois o túnel roda **sem janela**, automático no logon, pela tarefa agendada
   "Cortex Sulista - Tunnel ERP". Para rodar em janela (debug):
   `powershell -ExecutionPolicy Bypass -File scripts\tunel_erp.ps1`
2. API (porta **8010**; a 3000 é do HS Sistema):
   `powershell -ExecutionPolicy Bypass -File scripts\run_api.ps1`
   — ou automático no logon pelas tarefas agendadas "Cortex Sulista - API" e
   "Cortex Sulista - Tunnel" (VBS em `scripts\win\`).
3. Acesso: local `http://127.0.0.1:8010` · internet `https://cortex.cassolitech.com.br`
   (Cloudflare Tunnel `cortex`, config em `%USERPROFILE%\.cloudflared\config-cortex.yml`).
4. Login obrigatório. O **primeiro administrador** só pode ser criado no acesso
   local (`127.0.0.1:8010`); usuários/perfis/permissões ficam na área **Gestão**
   (SQLite local `data/auth.db` — o ERP segue somente leitura).

## Deploy contínuo a partir do GitHub
Esta máquina espelha `origin/main`. Tarefas agendadas (todas no logon, ocultas):

| Tarefa | Função |
|---|---|
| `Cortex Sulista - API` | uvicorn em 127.0.0.1:8010 |
| `Cortex Sulista - Tunnel` | túnel Cloudflare (`cortex.cassolitech.com.br`) |
| `Cortex Sulista - Tunnel ERP` | túnel SSH ao ERP (por chave) |
| `Cortex Sulista - AutoDeploy` | a cada 2 min: `git fetch`; se há commit novo em `origin/main`, faz fast-forward, `uv sync` (se deps mudaram) e reinicia a API |

`scripts/autodeploy.ps1` só aplica **fast-forward** — se o histórico local divergir
do remoto, ele registra em `logs/autodeploy.log` e não força nada (não destrói
trabalho nem dados de runtime; `data/` e `.env` nunca são versionados).
Fluxo: faça o push para o GitHub e em até 2 min esta máquina reflete a mudança.
