# Janela base escolhível — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No método sazonal do Orçamento, o usuário escolhe a janela base (últimos 6, últimos 3 ou range personalizado de meses fechados); Regerar passa a manter a janela gravada.

**Architecture:** `derivar_semestre` já divide por `len(meses_base)` — zero mudança na derivação. Tudo acontece em `servico.gerar` (resolução/validação da janela + regerar pela janela gravada), no endpoint (params novos) e na Montagem (seletor Base).

**Tech Stack:** os de sempre (FastAPI/pytest/SPA vanilla).

## Global Constraints

- **Branch:** `feat/orcamento-janela-base` a partir de `main`. SEM push/merge.
- **Spec:** `docs/superpowers/specs/2026-07-28-orcamento-janela-base-design.md`.
- Janela: contígua, meses FECHADOS, 3..12 meses; ausente → últimos 6 (compat). Violações → ValueError pt-BR → 422. `base_*` com metodo espelho → 422; com versao_id → ignorados.
- **Regerar sazonal usa a janela GRAVADA** (`json.loads(versao.meses_base)`); sem meses_base gravado → últimos 6. Espelho intocado (regressão obrigatória).
- Front: rótulo do método vira "Média do período × sazonalidade" (value `semestre` intacto); seletor Base com 3 presets; front SEMPRE envia base_de/base_ate calculados; substituição literal + node --check; esc() em dado de API.
- Suíte atual: **256** verde após cada task. Relatório da task OBRIGATÓRIO no workspace SDD.
- Commits pt-BR SEM push.

---

### Task 1: Serviço + endpoint

**Files:** Modify `api/orcamento/servico.py`, `api/main.py`; Test `tests/orcamento/test_servico.py` (append)

**Interfaces (Produces):**
- `servico.janela_base(base_de: str | None, base_ate: str | None, hoje: date) -> list[str]` (módulo, testável): ausentes ambos → `meses_fechados(hoje, 6)`; um só presente → ValueError "informe base_de e base_ate juntos"; valida formato `^\d{4}-(0[1-9]|1[0-2])$`, `de<=ate`, `ate` ≤ último mês fechado ("a base só pode conter meses fechados"), 3 ≤ len ≤ 12 ("a base precisa de 3 a 12 meses"); devolve a lista contígua 'AAAA-MM'.
- `servico.gerar(..., base_de=None, base_ate=None)`:
  - metodo espelho + base_* → ValueError "a janela base é do método sazonal (Média do período × sazonalidade)".
  - metodo semestre, geração nova → `meses = janela_base(base_de, base_ate, hoje)`.
  - REGERAR (versao_id) semestre → ignora base_*/metodo do chamador; `meses = json.loads(versao['meses_base'])` (fallback últimos 6 se null); re-valida `meses_faltando`.
  - Nada mais muda (nível já é soma/len; meses_base gravado = a janela).
- Endpoint /gerar: lê `base_de`/`base_ate` do body (strings ou None; tipo não-string → 422 parametro_invalido); passa ao gerar; ValueError já vira 422 pelo fluxo existente (conferir se a mensagem chega — o código de erro pode continuar `sem_historico`/`versao_imutavel` conforme o caso; adicionar código `janela_invalida` quando a mensagem contiver "base" é opcional — NÃO obrigatório).

- [ ] Steps: testes primeiro —
  `test_janela_base_defaults_e_validacoes` (ausentes → 6 últimos; um só → erro; formato; de>ate; ate no mês corrente → erro; len 2 → erro; len 13 → erro; trimestre abr–jun ok),
  `test_gerar_com_janela_trimestral_nivel_e_circulares` (fake 3 meses de 300 → nível 100; meses_base gravado = os 3; meses_circulares só os da janela),
  `test_gerar_espelho_com_base_da_422` (ValueError),
  `test_regerar_semestre_mantem_janela_gravada` (gera com fev–abr via base_*; regera com hoje avançado E base_* diferentes no chamador → meses_base continua fev–abr),
  `test_espelho_intocado_regressao` (já existe — garantir que segue passando) →
  falhar → implementar → `uv run python -c "from api import main"` → suíte → commit.

---

### Task 2: Front — seletor Base na Montagem

**Files:** Modify `api/static/index.html`

- [ ] 1. Rótulo da option do método: "Média do período × sazonalidade" (value `semestre`).
- [ ] 2. Ao lado do select de método (visível só quando método sazonal; `display:none` no espelho, controlado no mesmo onchange que troca o banner): `<select id="fOrcBase">` com `u6` "Últimos 6 meses (semestre)" (default), `u3` "Últimos 3 meses (trimestre)", `custom` "Personalizado…". Quando `custom`: dois selects `fOrcBaseDe`/`fOrcBaseAte` com os últimos 18 meses fechados (value 'AAAA-MM', rótulo "mmm/aa"), default preenchendo os últimos 6.
- [ ] 3. Helper `_orcMesesFechados(n)` (client): lista dos n meses fechados até o anterior ao corrente (reusar a aritmética do `_orcRotuloBase6`; refatorar o rótulo para usar o helper).
- [ ] 4. `orcGerar` (geração nova, método sazonal): calcula `base_de/base_ate` do preset (u6→últimos 6; u3→últimos 3; custom→selects, com validação client de>ate → banner e aborta) e envia no body. Rótulo sugerido usa a faixa real da janela.
- [ ] 5. Hint do Regerar: "regerar mantém o método e a janela da versão".
- [ ] 6. node --check a cada edição; Playwright: fixtures dos 3 presets (conferir o body enviado interceptando fetch via page.route ou validando os helpers com page.evaluate) + tela real local (túnel de pé): gerar de verdade com "Últimos 3 meses", conferir badge "base abr–jun/26" e circulares 4-6 no acompanhamento (o card Orçamento do ano marca só abr–jun esmaecidos), screenshot; APAGAR a versão de teste do SQLite local ao final.
- [ ] 7. estrutura.py 33 telas; suíte; commit.

---

### Task 3: Validação + aceites

- [ ] Aceites 1-5 da spec (túnel deve estar de pé — validar de verdade; aceite 1 inclui conferir que com base trimestral jan–mar COMPARAM no acompanhamento: cascata orçado×realizado deixa de estar vazia).
- [ ] Estado final limpo: nenhuma versão de teste sobrando no SQLite local.
- [ ] Relatório com evidências; correções commitadas se houver defeito.

## Self-review

- Spec §1→T1 (janela_base+gerar); §2 regerar→T1; §3 API→T1; §4 tela→T2; §5 erros→T1; aceites→T3. derivacao intocada (já genérica) — verificado: divide por len(meses_base).
- Tipos: base_de/base_ate strings 'AAAA-MM' em todas as camadas; meses_base JSON list como hoje.
