# Versões protegidas do Orçamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aprovar/reabrir versões (imutáveis quando aprovadas), exportar CSV pt-BR e arquivar snapshot automático antes de regerar — no módulo Orçamento do Cortex.

**Architecture:** Tudo sobre o motor existente: 2 colunas novas + 3 funções em `armazenamento.py`, guardas de imutabilidade no serviço, 3 endpoints (`aprovar`, `reabrir`, `exportar`), preferência por aprovada em `caixa.provisao_do_ano`, e UI na Montagem.

**Tech Stack:** Python/FastAPI/sqlite3/pytest; SPA vanilla-JS (`api/static/index.html`); CSV com stdlib (`io.StringIO` + formatação manual pt-BR — SEM lib nova).

## Global Constraints

- **Branch:** `feat/orcamento-versoes` a partir de `main`. SEM push/merge — decisão do usuário no fim.
- **Spec governa:** `docs/superpowers/specs/2026-07-27-orcamento-versoes-design.md`.
- Imutabilidade: `status != 'rascunho'` bloqueia `ajustar` e regerar com `ValueError` pt-BR → 422 nos endpoints. Aprovar arquivada → 422; reabrir arquivada → 422; inexistente → 404.
- Migração de `aprovado_em`/`aprovado_por` no padrão PRAGMA+ALTER de `meses_base`/`metodo` (arquivo `api/orcamento/armazenamento.py`).
- CSV: BOM UTF-8 (`﻿`), separador `;`, decimal vírgula (`f"{v:.2f}".replace(".", ",")`), header-bloco `chave;valor` + linha vazia + colunas `conta;nome;linha_dre;origem;meses_com_dado;jan..dez;total;ajustadas`; valores = `valor_efetivo`; `total` = soma dos 12; `ajustadas` = meses com `valor_ajustado` não-nulo separados por vírgula; nomes de conta best-effort (ERP fora → vazios, sem erro); filename `orcamento-{ano}-v{id}.csv`.
- Snapshot pré-regeração: `arquivar_copia` copia cabeçalho E linhas (baseline + valor_ajustado + ajustado_em/por) numa transação; rótulo `"{rotulo} (antes de regerar {DD/MM HH:MM})"`; `status='arquivada'`; resposta do regerar ganha `arquivada_id`.
- Fluxo: `provisao_do_ano` prefere aprovada mais recente; senão rascunho mais recente; arquivada nunca.
- Front: substituição literal + `node --check` a cada edição; ast.parse nos .py; esc() em dado da API; nada de const de topo lendo CC.
- Suíte atual: **224** — verde após cada task. `uv run --with pytest python -m pytest tests/ -q`.
- **Túnel AVA possivelmente FORA**: validações com Postgres real são best-effort; o export tem de funcionar sem ele (nomes vazios).
- Commits pt-BR SEM push. Relatório da task OBRIGATÓRIO (tasks anteriores esqueceram e a revisão cobrou).

---

### Task 1: Armazenamento — aprovar/reabrir/arquivar + imutabilidade

**Files:** Modify `api/orcamento/armazenamento.py`; Test `tests/orcamento/test_armazenamento.py` (append)

**Interfaces (Produces):**
- Migração: colunas `aprovado_em TEXT`, `aprovado_por TEXT` em `orc_versao` (init_db).
- `aprovar(path, versao_id, quem, agora=None) -> None` — KeyError se inexistente; ValueError se `status=='arquivada'`; grava status/aprovado_em ("%Y-%m-%d %H:%M")/aprovado_por. Aprovar já-aprovada é idempotente (regrava quem/quando).
- `reabrir(path, versao_id) -> None` — KeyError inexistente; ValueError se `arquivada`; status='rascunho', limpa aprovado_*.
- `arquivar_copia(path, versao_id, rotulo_novo) -> int` — INSERT..SELECT do cabeçalho (com status='arquivada' e rotulo_novo, preservando ano/fator/metodo/meses_base/criado_por; criado_em = agora) + INSERT..SELECT de TODAS as orc_linha (todas as colunas) para o id novo, numa única transação (`with _conn`); devolve o id novo. KeyError se inexistente.
- `ajustar(...)`: ANTES do update, lê o status da versão; `!= 'rascunho'` → `ValueError("Versão aprovada/arquivada é imutável — reabra antes de ajustar.")`.

- [ ] Steps: testes (aprovar grava quem/quando; reabrir limpa; arquivada não aprova/reabre; ajustar em aprovada → ValueError e em reaberta volta a funcionar; arquivar_copia copia baseline+ajuste fielmente e devolve id novo; migração em banco velho ganha as colunas) → falhar → implementar → suíte inteira → commit `"Orçamento: aprovar/reabrir/arquivar versões com imutabilidade no armazenamento"`.

---

### Task 2: Serviço + endpoints + preferência do Fluxo

**Files:** Modify `api/orcamento/servico.py`, `api/orcamento/caixa.py`, `api/main.py`; Test `tests/orcamento/test_servico.py`, `tests/orcamento/test_caixa.py` (append)

**Interfaces:**
- `servico.gerar(versao_id=...)`: se a versão não é `rascunho` → `ValueError("Versão aprovada/arquivada é imutável — reabra antes de regerar.")`; se é rascunho → chama `arm.arquivar_copia(path, versao_id, rotulo + " (antes de regerar DD/MM HH:MM)")` ANTES de re-derivar; resposta ganha `"arquivada_id"`.
- `caixa.provisao_do_ano`: dentre `listar_versoes(path, ano)`, escolhe a primeira com `status=='aprovado'`; senão a primeira com `status=='rascunho'` (ou sem campo status → trata como rascunho, compat com versões antigas); arquivada nunca. Resposta `versao` ganha `"status"`.
- `POST /api/controladoria/orcamento/aprovar` e `/reabrir` (body `{"versao_id": int}`; validação int>0 → 422; KeyError → 404; ValueError → 422; sucesso → `{"ok": true, "versao": {...}}` com a versão atualizada de `listar_versoes`). `quem` = nome da sessão como no gerar.
- `GET /api/controladoria/orcamento/exportar?versao_id=N` → `fastapi.Response(content=..., media_type="text/csv; charset=utf-8", headers={"Content-Disposition": ...})`; monta via `servico.exportar_csv(versao_id, path=None) -> tuple[str, str]` (conteúdo, filename) — nomes de conta com try/except → {}. Registrar a rota: o prefixo `/api/controladoria/orcamento` do ROTA_TELAS já cobre (conferir).
- Ordenação do seletor: `servico.obter()`/`serie()` não mudam; o `index` de versões da tela vem de `listar_versoes` via endpoint `/versoes` — ESTE ganha a ordenação: não-arquivadas primeiro (id desc), depois arquivadas (id desc), e cada item ganha `status`.

- [ ] Steps: testes (regerar aprovada → ValueError; regerar rascunho cria arquivada com cópia fiel e responde arquivada_id; provisao_do_ano prefere aprovada, ignora arquivada, compat sem status; exportar_csv: BOM, `;`, vírgula, total, ajustadas, 404/inexistente via KeyError, nomes vazios com db.query stubado a falhar) → falhar → implementar → `uv run python -c "from api import main"` → suíte inteira → commit `"Orçamento: endpoints aprovar/reabrir/exportar e snapshot pré-regeração"`.

---

### Task 3: Front — Montagem e seletor

**Files:** Modify `api/static/index.html`

Pontos (grep pelos nomes; padrão das telas existentes):
1. Seletor de versões (`fOrcVersao`, populado em loadOrc): rótulo ganha sufixo `" (aprovada)"` / `" (arquivo)"` conforme `x.status`; ordenação vem do backend.
2. Card "Gerar baseline" (renderOrcMontagem): quando a versão carregada é `aprovada` → badge verde no head do card "aprovada por {quem} em {fmtDT}", botão "Reabrir" (POST /reabrir + reload); quando `rascunho` → botão "Aprovar versão" (POST /aprovar + reload); quando `arquivada` → badge neutra "arquivo — somente leitura", sem botões de aprovação. Botão Regerar `disabled` com title quando não-rascunho.
3. Grade (renderOrcGrade): células `disabled` quando a versão não é rascunho (title: "versão aprovada/arquivada — somente leitura"; reabra para ajustar quando aprovada).
4. Botão "Exportar CSV" na barra do card (link `<a class="btn" href="/api/controladoria/orcamento/exportar?versao_id={id}" download>` — qualquer status).
5. Mensagem pós-regeração inclui "estado anterior arquivado como versão {arquivada_id}".
6. ⓘ do Fluxo: acrescentar "(aprovada)" ao rótulo quando `provisao_orc.versao.status === 'aprovado'`.

- [ ] Steps: implementar → node --check a cada edição → Playwright local (login teste; a tela do orçamento precisa do Postgres para o GET — se o túnel estiver fora, validar estados via fixtures page.evaluate como nas tasks anteriores, com screenshots) → estrutura.py 33 telas → suíte → commit `"Orçamento: UI de aprovação, export CSV e versões arquivadas"`.

---

### Task 4: Validação ponta a ponta + ACOMPANHAMENTO (pedido do usuário)

- [ ] Aceites 1-5 da spec um a um (túnel fora → fixtures + comandos exatos para depois, como nas tasks 6 anteriores).
- [ ] **Validar o ACOMPANHAMENTO da tela Orçamento** (pedido explícito do usuário nesta rodada): com o túnel DE PÉ (checar `nc -z 127.0.0.1 15432`; se voltar durante a task, priorize): abrir a aba Acompanhamento das versões existentes e conferir: (a) estado atual correto = jan–jun circulares → KPIs "—" neutros + banner explicando + "sem mês fechado fora da base"; (b) gráfico mensal com jan–jun esmaecidos e ago–dez só orçado; (c) hint da cascata coerente; (d) trocar "Até o mês" e ver o recorte mudar; (e) screenshot full-page para o usuário. Com o túnel FORA: validar a lógica pelo unitário (montar_comparativo com fixtures reproduzindo o estado de julho) + registrar o roteiro de 5 passos para o usuário validar em produção.
- [ ] Se achar defeito, corrigir e commitar; senão sem commit. Relatório com o veredito do acompanhamento em `.superpowers/sdd/<workspace>/task-4-report.md`.

---

## Self-review

- Spec coverage: §1→T1/T2/T3; §2→T2/T3; §3→T1/T2/T3; §4 erros→T1/T2; aceites→T4; acompanhamento (pedido extra do usuário)→T4.
- Sem placeholders: interfaces exatas nas tasks; corpos de teste seguem os padrões vizinhos (decisão consciente, consistente com os planos anteriores deste módulo).
- Tipos consistentes: `arquivar_copia -> int` consumido por `gerar` (arquivada_id); `status` flui listar_versoes → /versoes → seletor → badges.
