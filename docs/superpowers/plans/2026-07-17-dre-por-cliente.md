# DRE por Cliente (v1: até Margem de Contribuição) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produzir a DRE por cliente custeada bottom-up (por viagem/CT-e), espelhando o plano de contas da DRE oficial, reconciliando linha a linha contra `get_dre`, até a linha MARGEM DE CONTRIBUIÇÃO.

**Architecture:** Live-compute + snapshots. Subpacote `api/dre_cliente/` isola lógica pura (custeio, reconciliação, km-vazio, params) da camada de banco (`sql.py`) e IO (`snapshot.py`). Poucas queries pesadas no AVA + derivação em Python. Reconciliação por *plug* (NAO_ALOCADO) contra a DRE oficial como total de controle.

**Tech Stack:** Python 3.12, FastAPI, psycopg3 (pool em `api/db.py`), PyYAML, pytest (via `uv run --with pytest`), SPA vanilla JS (`api/static/index.html`).

## Global Constraints

- Banco AVA é **réplica read-only** (PG 9.3.25). Nenhum DDL/escrita no banco de origem. Toda persistência é local (`data/`, `config/`).
- SQL em **LATIN-1**: nunca usar `—`, `→`, `≥`, `×` dentro de strings SQL (usar `-`, `>=`, `x`).
- Somas de razão: sempre `coalesce(l.valorcredito,0) - coalesce(l.valordebito,0)`; excluir `historico = 18`.
- Viagem canônica: `programacaoembarque` com `dtcancelamento IS NULL AND semaforo = 1`. `tipo = 3` = deslocamento vazio; km da viagem = `kmfretecompra`.
- Cliente = `agrupamentocliente` (grupo econômico) via `coleta.cnpjcpfcodigopagadorfrete` → `agrupamentocliente_cnpjcpfcodigo`; heurística p/ viagens sem coleta reusa `HEUR_SEMCLI_SQL`.
- Tipo de operação = `veiculo.utilizacaoveiculo` (FROTA/LOCACAO/AGR/TER); AGR/TER não recebem combustível/manutenção/pneus/fixo — só repasse.
- Joins por (grupo,empresa) → `SET LOCAL enable_mergejoin = off`.
- Antes de gravar qualquer `.py`, o executor roda `python -c "import ast, pathlib; ast.parse(pathlib.Path('<arquivo>').read_text())"`.
- Params de negócio nunca hardcoded → `config/dre_cliente_params.yaml`.
- DRE oficial de referência = `api.queries.get_dre` (já bate com `docs/dre_ia_analise.xlsx`); a nova saída deve usar a MESMA ordem/nomenclatura de linhas até MARGEM DE CONTRIBUIÇÃO.

---

## File Structure

- Create `config/dre_cliente_params.yaml` — params versionados.
- Create `api/dre_cliente/__init__.py` — API pública `get_dre_cliente(comp_de, comp_ate, filial)`.
- Create `api/dre_cliente/params.py` — carga/validação de params.
- Create `api/dre_cliente/modelo.py` — linhas da DRE por cliente (espelho até MC) + de-para linha→método.
- Create `api/dre_cliente/custeio.py` — funções puras de custeio/rateio por viagem.
- Create `api/dre_cliente/vazio.py` — atribuição de km vazio ao cliente originador.
- Create `api/dre_cliente/reconciliacao.py` — plug NAO_ALOCADO + VARIACAO_ABSORCAO + asserção de balanço.
- Create `api/dre_cliente/agregacao.py` — cliente × linha + indicadores + ranking MC%.
- Create `api/dre_cliente/sql.py` — constantes SQL + fetch (camada de banco).
- Create `api/dre_cliente/snapshot.py` — leitura/escrita de `data/dre_cliente/<YYYY-MM>.json`.
- Modify `api/main.py` — endpoint `GET /api/financeiro/dre-cliente`.
- Modify `api/static/index.html` — vista "DRE por Cliente".
- Create `tests/dre_cliente/` — testes pytest da lógica pura.
- Create `docs/fase4-validacao.md` — reconciliação vs xlsx (preenchido com túnel no ar).

**Tasks 1–9 são lógica pura, rodam SEM túnel. Tasks 10–14 exigem o túnel SSH no ar para validar.**

---

### Task 1: Params versionados

**Files:**
- Create: `config/dre_cliente_params.yaml`
- Create: `api/dre_cliente/params.py`
- Test: `tests/dre_cliente/test_params.py`

**Interfaces:**
- Produces: `carregar_params() -> Params` (dataclass) com campos: `deducoes_pct: dict[str,float]` (por imposto), `creditos_pct: dict[str,float]` (por natureza de custo gerador), `rateio_intra_viagem: str` ("peso"|"receita"), `taxa_km_janela_meses: int`, `preco_diesel_fallback: float`.

- [ ] **Step 1:** Escrever `config/dre_cliente_params.yaml` com chaves `deducoes_pct` (federais/estaduais/municipais/previdenciaria), `creditos_pct` (combustivel/pneus/manutencao/frete_contratado), `rateio_intra_viagem: peso`, `taxa_km_janela_meses: 12`, `preco_diesel_fallback: 6.00`. Valores iniciais são estimativas a calibrar na Task 14.
- [ ] **Step 2:** Escrever teste `test_carregar_params_le_yaml` que carrega e valida tipos e presença de chaves obrigatórias; e `test_params_soma_deducoes_positiva`.
- [ ] **Step 3:** Rodar `uv run --with pytest pytest tests/dre_cliente/test_params.py -v` → FAIL (módulo inexistente).
- [ ] **Step 4:** Implementar `params.py`: dataclass `Params` + `carregar_params(path=None)` lendo o YAML (default = `config/dre_cliente_params.yaml`), com validação de chaves (raise `ValueError` se faltar).
- [ ] **Step 5:** Rodar o teste → PASS.
- [ ] **Step 6:** Commit `feat(dre-cliente): params versionados de negócio`.

---

### Task 2: Modelo de linhas (espelho da DRE até MC)

**Files:**
- Create: `api/dre_cliente/modelo.py`
- Test: `tests/dre_cliente/test_modelo.py`

**Interfaces:**
- Consumes: `api.queries.DRE_MODELO` (ordem/nomenclatura oficiais).
- Produces: `LINHAS_CLIENTE: list[Linha]` (subconjunto até MARGEM DE CONTRIBUIÇÃO: Receita Bruta, Deduções e filhas, Receita Líquida, CV e filhas, Créditos Tributários, MARGEM DE CONTRIBUIÇÃO); `metodo_da_linha(rotulo) -> str` em {direto_viagem, direto_cte, taxa_km, deducao_pct, credito_pct, formula}.

- [ ] **Step 1:** Teste `test_linhas_incluem_ate_mc_e_param_ordem` (a lista termina em "MARGEM DE CONTRIBUICAO"; ordem = subsequência de `DRE_MODELO`); `test_metodo_por_linha` (CV agregados→direto_viagem; manutenção→taxa_km; deduções→deducao_pct; créditos→credito_pct).
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `modelo.py`: derivar `LINHAS_CLIENTE` de `DRE_MODELO` cortando após MC + acrescentar a linha "MARGEM DE CONTRIBUICAO" (formula = RECEITA LIQUIDA + CSP-parcial); mapa `metodo_da_linha`.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): modelo de linhas espelho ate MC`.

---

### Task 3: Atribuição de km vazio

**Files:**
- Create: `api/dre_cliente/vazio.py`
- Test: `tests/dre_cliente/test_vazio.py`

**Interfaces:**
- Produces: `atribuir_vazio(viagens: list[Viagem]) -> dict[viagem_id, cliente]` — associa cada trecho `tipo=3` ao cliente da **próxima viagem carregada do mesmo veículo** (fallback: anterior; desempate por menor Δt). `Viagem` = TypedDict com veiculo, dtsaida, dtchegada, tipo, cliente, km.

- [ ] **Step 1:** Testes: retorno vazio (vazio após carregada → cliente da carregada anterior quando não há próxima); posicionamento (vazio antes de carregada → cliente da próxima); dois vazios consecutivos; vazio sem nenhuma carregada no veículo → `None` (vai p/ NAO_ALOCADO).
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `atribuir_vazio`: ordenar viagens por (veículo, dtsaida); para cada vazio, achar a carregada mais próxima no tempo do mesmo veículo (preferir próxima; empate → menor |Δt|).
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): atribuicao de km vazio ao cliente originador`.

---

### Task 4: Custeio — combustível (próprio)

**Files:**
- Create: `api/dre_cliente/custeio.py`
- Test: `tests/dre_cliente/test_custeio_combustivel.py`

**Interfaces:**
- Produces: `custear_combustivel(abastec_por_veiculo: dict[placa,float], km_por_viagem: list[(viagem_id, placa, km, is_proprio)]) -> dict[viagem_id, float]` — rateia o custo mensal de combustível de cada veículo próprio às suas viagens proporcional ao km (carregado+vazio); AGR/TER recebem 0.

- [ ] **Step 1:** Testes: rateio proporcional ao km entre 2 viagens do mesmo veículo; veículo AGR/TER → 0; veículo sem km → 0 (sem divisão por zero); soma dos rateios = custo do veículo (tolerância 1e-6).
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `custear_combustivel`.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): custeio de combustivel proprio por km`.

---

### Task 5: Custeio — manutenção/pneus (taxa R$/km + variância de absorção)

**Files:**
- Modify: `api/dre_cliente/custeio.py`
- Test: `tests/dre_cliente/test_custeio_taxa_km.py`

**Interfaces:**
- Produces: `custear_taxa_km(taxa_por_veiculo: dict[placa,float], km_por_viagem, real_do_razao: float) -> tuple[dict[viagem_id,float], float]` — retorna (absorvido por viagem, `variacao_absorcao = real_do_razao - Σ absorvido`).

- [ ] **Step 1:** Testes: absorvido = taxa × km; variância = real − Σ absorvido (positiva e negativa); AGR/TER → 0.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `custear_taxa_km`.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): custeio por taxa R$/km com variacao de absorcao`.

---

### Task 6: Custeio — deduções e créditos (% paramétrico)

**Files:**
- Modify: `api/dre_cliente/custeio.py`
- Test: `tests/dre_cliente/test_custeio_pct.py`

**Interfaces:**
- Produces: `custear_deducoes(receita_por_viagem: dict, pct: dict[str,float]) -> dict[imposto, dict[viagem_id,float]]`; `custear_creditos(custos_geradores_por_viagem: dict[natureza, dict[viagem_id,float]], pct: dict[str,float]) -> dict[viagem_id,float]` (valores negativos = redutores).

- [ ] **Step 1:** Testes: dedução = receita × pct por imposto; crédito = Σ (custo_gerador × pct) por natureza, sinal negativo; natureza sem pct → ignorada.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar as duas funções.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): deducoes e creditos por percentual parametrico`.

---

### Task 7: Custeio — diretos (receita, repasse AGR/TER, pedágio/diárias/etc.)

**Files:**
- Modify: `api/dre_cliente/custeio.py`
- Test: `tests/dre_cliente/test_custeio_diretos.py`

**Interfaces:**
- Produces: `custear_diretos(viagens) -> dict[linha, dict[viagem_id,float]]` — mapeia campos diretos da viagem/CT-e às linhas: Receita Bruta (`valorfrete`), CV Agregados/Terceiros (`valorfretecompra` quando AGR/TER), e demais campos diretos disponíveis (pedágio/diárias/carga-desc quando presentes; ausentes → não gera linha, resíduo vira NAO_ALOCADO na reconciliação).

- [ ] **Step 1:** Testes: receita = valorfrete por viagem; repasse só quando AGR/TER; campos ausentes não quebram.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `custear_diretos`.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): custeio de linhas diretas por viagem`.

---

### Task 8: Reconciliação (plug + variância + balanço)

**Files:**
- Create: `api/dre_cliente/reconciliacao.py`
- Test: `tests/dre_cliente/test_reconciliacao.py`

**Interfaces:**
- Consumes: descidas por linha (Σ por cliente) + `variacao_absorcao` por linha (Task 5).
- Produces: `reconciliar(descido_por_linha: dict[linha,float], dre_oficial: dict[linha,float], variacao: dict[linha,float]) -> dict[linha, {descido, nao_alocado, variacao_absorcao, cobertura_pct}]` — garante `descido + nao_alocado + variacao = dre_oficial` por linha; `cobertura_pct = 1 - |nao_alocado|/|dre_oficial|`.

- [ ] **Step 1:** Testes: balanço exato por construção; linha direta com descido=oficial → nao_alocado=0, cobertura=1; variância entra no balanço; oficial=0 → cobertura tratada sem div/0.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `reconciliar` com `assert` de balanço (tolerância 1e-6).
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): reconciliacao por plug contra a DRE oficial`.

---

### Task 9: Agregação cliente × linha + indicadores + ranking

**Files:**
- Create: `api/dre_cliente/agregacao.py`
- Test: `tests/dre_cliente/test_agregacao.py`

**Interfaces:**
- Produces: `agregar(custos_por_viagem, viagem_cliente, viagem_meta) -> {clientes: [...], consolidado: {...}}` — por cliente × linha (R$), indicadores `km_carregado`, `km_vazio`, `pct_km_vazio`, `mc`, `mc_pct`, `viagens`, `mix` (proprio/agregado/terceiro), `dias_veiculo`; ranking por `mc_pct`.

- [ ] **Step 1:** Testes: agrega 2 viagens de 1 cliente; MC = receita líquida − CV + créditos; mc_pct = mc/receita_liquida; %km_vazio = vazio/(carregado+vazio); ranking ordenado por mc_pct desc.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar `agregar`.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(dre-cliente): agregacao por cliente e ranking MC%`.

---

### Task 10: Camada SQL (fetch do AVA) — requer túnel

**Files:**
- Create: `api/dre_cliente/sql.py`
- Test: manual via `scripts/db.sh` / smoke com túnel no ar.

**Interfaces:**
- Produces: `fetch_viagens(cur, de, ate, filial)`, `fetch_abastecimentos(cur, de, ate)`, `fetch_taxa_km(cur, ate, janela_meses)`, `fetch_dre_oficial(comp_de, comp_ate)` (reusa `queries.get_dre`).

- [ ] **Step 1:** Escrever as constantes SQL (LATIN-1, PKs completas, `enable_mergejoin off` onde couber) reusando padrões de `RENT_CLI_SQL`/`HEUR_SEMCLI_SQL`/`MVB_*`.
- [ ] **Step 2:** `ast.parse` do arquivo; `uv run python -c "from api.dre_cliente import sql"`.
- [ ] **Step 3:** Com túnel no ar: rodar cada query para 1 mês fechado e conferir formato/linhas (`scripts/db.sh file` ou script ad-hoc no scratchpad). Registrar contagens.
- [ ] **Step 4:** Commit `feat(dre-cliente): camada SQL de fetch do AVA`.

---

### Task 11: Orquestração + snapshot — requer túnel

**Files:**
- Create: `api/dre_cliente/snapshot.py`, `api/dre_cliente/__init__.py`
- Test: smoke com túnel.

**Interfaces:**
- Produces: `get_dre_cliente(comp_de, comp_ate, filial=None) -> dict` (cacheado com `@cached`); usa snapshot para meses fechados (exceto últimos 2), recalcula ao vivo o restante; grava snapshot dos meses fechados.

- [ ] **Step 1:** Implementar `snapshot.py` (ler/gravar `data/dre_cliente/<YYYY-MM>.json`, atômico).
- [ ] **Step 2:** Implementar `__init__.py` juntando fetch → custeio → vazio → reconciliação → agregação; snapshot p/ meses fechados.
- [ ] **Step 3:** `ast.parse` + `uv run python -c "from api import dre_cliente"`.
- [ ] **Step 4:** Com túnel: rodar `get_dre_cliente('2026-01','2026-05')`, conferir reconciliação (asserts passam) e cobertura por linha.
- [ ] **Step 5:** Commit `feat(dre-cliente): orquestracao get_dre_cliente + snapshots`.

---

### Task 12: Endpoint — requer app rodando

**Files:**
- Modify: `api/main.py`
- Test: `curl` local.

- [ ] **Step 1:** Adicionar `GET /api/financeiro/dre-cliente` (params comp_de/comp_ate/filial) chamando `dre_cliente.get_dre_cliente`.
- [ ] **Step 2:** `uv run python -c "from api import main"`; subir `scripts/run_api.sh`; `curl 'http://127.0.0.1:8000/api/financeiro/dre-cliente?comp_de=2026-01&comp_ate=2026-05'`.
- [ ] **Step 3:** Commit `feat(dre-cliente): endpoint /api/financeiro/dre-cliente`.

---

### Task 13: Vista SPA "DRE por Cliente" — requer app rodando

**Files:**
- Modify: `api/static/index.html`
- Test: navegador.

- [ ] **Step 1:** Adicionar item de menu no grupo Financeiro + vista `drecli` (usar helper `rep()` com assert; seguir padrões `qsView`/`LOADEDQS`/`loadX`/`renderX`).
- [ ] **Step 2:** Tabela hierárquica no layout do `get_dre` (linhas oficiais até MC, colunas = meses) + seletor de cliente + colunas NAO_ALOCADO/VARIACAO_ABSORCAO + card ranking MC% + drill-down memória por viagem.
- [ ] **Step 3:** Validar no navegador (desktop) que carrega e reconcilia visualmente.
- [ ] **Step 4:** Commit `feat(dre-cliente): vista DRE por Cliente no front`.

---

### Task 14: Fase 4 — Validação (bloqueia aceite) — requer túnel

**Files:**
- Create: `docs/fase4-validacao.md`

- [ ] **Step 1:** Rodar meses fechados de 2026; para cada linha/mês conferir `Σ clientes + NAO_ALOCADO + VARIACAO_ABSORCAO = get_dre`. Registrar cobertura por linha.
- [ ] **Step 2:** Calibrar `config/dre_cliente_params.yaml` (deduções/créditos) p/ minimizar NAO_ALOCADO das linhas paramétricas; documentar.
- [ ] **Step 3:** Casos unitários (km vazio retorno/posicionamento; multi-CT-e; CT-e cancelado; complementar; agregado sem custo de ativo; virada de mês) descritos e conferidos.
- [ ] **Step 4:** Escrever `docs/fase4-validacao.md` com divergências explicadas linha a linha vs `dre_ia_analise.xlsx`.
- [ ] **Step 5:** Commit `docs(dre-cliente): validacao fase 4 (reconciliacao)`.

---

## Self-Review

- **Cobertura do spec:** Receita/deduções/RL/CV/créditos/MC → Tasks 4–9; km vazio → Task 3; reconciliação + NAO_ALOCADO + VARIACAO_ABSORCAO → Task 8; ranking MC% → Task 9; espelho de layout → Tasks 2/13; params versionados → Task 1; validação → Task 14. CF por dia-veículo/Margem Direta = **fora do escopo v1** (documentado no design).
- **Placeholders:** nenhum passo com "TBD/etc."; tasks 10–14 dependem do túnel e estão marcadas.
- **Consistência de tipos:** nomes de funções/campos usados nas tasks de agregação/reconciliação batem com os produzidos nas de custeio.
