# Guia de Arranque — CÓRTEX no Claude Code

Tudo que você precisa para começar a desenvolver. Os arquivos `CLAUDE.md`,
`.claude/agents/` e `.claude/skills/` são lidos automaticamente pelo Claude Code ao abrir
o projeto na raiz — todo o contexto e as ferramentas já entram em jogo.

---

## 1. Preparar o repositório

```bash
unzip cortex.zip && cd cortex
cp .env.example .env          # preencha os segredos depois
```

`.gitignore` já vem no pacote (não versiona `.env`, `__pycache__`, `node_modules`, etc.).
Inicialize o git e faça o primeiro commit:

```bash
git init && git add . && git commit -m "chore: bootstrap CÓRTEX"
```

Atalho: `bash scripts/bootstrap.sh` faz git + estrutura + infra + migrations de uma vez.

## 2. Subir a infra e aplicar o schema

```bash
docker compose up -d postgres redis ollama   # postgres = imagem TimescaleDB
ollama pull gemma2:9b

uv sync                       # instala deps (pyproject na raiz)
uv run alembic upgrade head   # cria todo o schema (governança → views)
```

Confira: `uv run alembic current` deve mostrar `0006 (head)`.
O schema completo está em `sql/schema.sql` (referência) e é aplicado pelas 6 migrations.

## 3. Instalar e abrir o Claude Code

```bash
npm install -g @anthropic-ai/claude-code   # requer Node LTS recente
claude                                      # na raiz do projeto
```

Doc oficial (instalação/uso podem mudar): https://docs.claude.com/en/docs/claude-code/overview

Primeiro prompt, para confirmar que o contexto carregou:

```
Leia CLAUDE.md, docs/ARQUITETURA.md e docs/INTEGRACOES.md. Liste os agentes em
.claude/agents e as skills em .claude/skills. Resuma o projeto em uma frase e me diga
qual é a Fase 1 do roadmap.
```

## 4. Desenvolvimento por fases (prompts prontos)

Trabalhe sempre em **plan mode** primeiro (Shift+Tab) e revise o plano antes do código.
Peça commits pequenos a cada peça funcionando.

**Fase 1 — Fundação (auth + RBAC + RLS + audit + financeiro)**
```
O schema já está aplicado (migrations 0001-0006). Implemente api/ com FastAPI:
- auth JWT (login, refresh em Redis, MFA-ready);
- RBAC por módulo lendo papel_modulo;
- middleware que seta "SET app.user_filiais" por requisição (ativa o RLS);
- middleware de audit_log em toda escrita.
Use as regras de docs/SEGURANCA.md. Plan mode primeiro, depois código com testes.
```
```
Implemente o módulo financeiro: endpoints de recebimentos e fluxo de caixa usando a skill
fluxo-de-caixa e a view vw_fluxo_caixa. Inclua a análise de DRE com a skill dre-analise
sobre vw_dre_mensal. Testes inclusos.
```

**Fase 2 — Operacional + Programação**
```
Implemente o módulo operacional (CKM, resultado por viagem) usando as skills calculo-ckm,
analise-rota e make-vs-buy sobre vw_ckm_viagem/vw_resultado_viagem. Depois a programação de
cargas com a skill programacao-cargas, respeitando jornada (skill jornada-motorista).
```

**Fase 3 — Telemetria + Torres**
```
Implemente a ingestão de telemetria nas hypertables (tel_sinais, tc_posicoes, ts_eventos),
o canal de tempo real (LISTEN/NOTIFY + WebSocket) e os dashboards Torre de Controle e Torre
de Segurança seguindo a skill dashboard-builder. Insights via skill telemetria-insights.
```

**Fase 4 — Central de Integrações**
```
Implemente integrations/ conforme docs/INTEGRACOES.md e a skill connector-builder:
base.py (BaseConnector + CanonicalEvent + register), registry, worker com event bus Redis
Streams, normalizers para os tipos canônicos, e UM conector de exemplo end-to-end.
As tabelas int_* já existem.
```

**Fase 5 — IA local + copiloto**
```
Implemente o gateway de IA (Ollama/Gemma), o guardrail de PII, o RAG sobre kb_documentos
(pgvector) e o orquestrador LangGraph roteando para os agentes. Exponha o endpoint do copiloto.
```

**Fase 6 — Gestão + Preditivo**
```
Implemente o módulo gestão (metas/OKR com skill metas-okr, atas com skill ata-reuniao) e o
painel CEO consolidado. Previsões com a skill previsao-projecao.
```

## 5. Boas práticas durante o dev

- **Mantenha o CLAUDE.md vivo**: toda decisão nova de arquitetura entra nele.
- **Use os subagentes**: "use o agente `financeiro`/`telemetria`/`integracoes`..." quando o
  contexto for específico de uma área.
- **Parâmetros, não números mágicos**: tudo que é de negócio vive em `config/parametros.yaml`.
- **Nada exposto antes do checklist de go-live** (`docs/SEGURANCA.md`): túnel Cloudflare,
  MFA, RLS testada com cada papel, HMAC nos webhooks, dead-letter monitorada.

## 6. Estrutura do projeto

```
cortex/
├── CLAUDE.md                  contexto-mestre
├── README.md
├── pyproject.toml             deps backend + alembic
├── docker-compose.yml         postgres(timescale)+redis+ollama+workers+cloudflared
├── alembic.ini
├── .env.example
├── .claude/
│   ├── agents/                14 agentes
│   └── skills/                15 skills
├── config/parametros.yaml
├── docs/                      ARQUITETURA · SEGURANCA · INTEGRACOES · este guia
├── migrations/                env.py + versions/0001..0006
├── sql/
│   ├── schema.sql             schema consolidado (referência)
│   └── blocks/                blocos aplicados pelas migrations
├── api/                       (você implementa — FastAPI)
├── web/                       (você implementa — Next.js)
└── integrations/connectors/   (você implementa — conectores)
```
