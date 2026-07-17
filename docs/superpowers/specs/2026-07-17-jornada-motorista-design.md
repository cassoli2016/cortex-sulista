# Módulo Jornada do Motorista (Lei 13.103/2015) — Design

**Data:** 2026-07-17
**Roadmap:** Fase 4 do CLAUDE.md (Jornada: compliance Lei 13.103 + alertas preventivos).
**Escopo aprovado pelo usuário:** painel torre + ficha por motorista (completo), bottom-up
sobre o que o ERP AVA já calcula.

## 1. Contexto e fonte de dados

O banco acessado é a **réplica read-only do AVA** (`pg_is_in_recovery=true`, túnel SSH
`127.0.0.1:15432`). Não há migrations nem schema `jor_*` projetado — usamos **live-compute
sobre a réplica + `@cached`**, no mesmo padrão da DRE por Cliente e das Consultas de
Veículo/Cliente.

Descoberta-chave: o AVA **já roda um módulo de jornada completo e vivo** (atualizado em tempo
quase real). Não reconstruímos jornada a partir de GPS — lemos o que o ERP já calculou.

| Tabela (schema `public`) | Conteúdo | Uso no módulo |
|---|---|---|
| `jornadamotoristacalculo` | horas/dia por motorista: direção, jornada, espera, abastecimento, extras (até/acima 2h/4h · sáb/dom/feriado), adicional noturno. Chave: `cnpjcpfcodigo` (CPF) + `dtcalculo`. | KPIs de horas e extras (painel + ficha) |
| `jornada_registrodirecaodescanso` | ciclos direção × descanso. `tempodirecao + tempodirecaodisponivel = 19800 s = 5h30`; `tempodescansodisponivel = 1800 s = 30 min`. `situacao` 2 = ciclo aberto, 1 = fechado. | Regra de direção contínua (núcleo) + timeline da ficha |
| `jornadamotorista` | timeline de eventos (dtinicio/dtfim, `tipo`, `tipojornada`, veículo, lat/long). 900k linhas. | Interjornada (lacunas) + timeline da ficha |
| `jornada_erro` | ocorrências classificadas pelo ERP (`erro` 1–6, `acao`, `origem`). Sem texto. | "Ocorrências do ERP" (secundário, rótulo best-effort) |
| `cadastro` | `razaosocial` (nome). Chave `codigo`. | Nome do motorista |
| `cadastro_continua` | CNH: `dtvencimentocarteirahabilitacao`, `categoriacarteirahabilitacao`, `ufcarteirahabilitacao`. Chave `cnpjcpfcodigo`. | CNH (vencida/vencendo) |

## 2. PII (regra inviolável)

`cnpjcpfcodigo` é o **CPF do motorista = PII**. Nunca sai no payload da API nem aparece na
tela. Sempre: **nome resolvido** + CPF mascarado via `_mask_doc` (padrão já existente). O CPF
cru nunca é logado nem reproduzido. Segue a política de segurança da organização.

## 3. Regras de compliance (Lei 13.103/2015)

Computadas a partir do dado que entendemos por completo — não dos códigos enum do ERP:

| Regra | Limite legal | Cálculo (fonte) |
|---|---|---|
| Direção contínua | ≤ 5h30 antes de parada de 30 min | ciclo de `registrodirecaodescanso` com `tempodirecao > 19800 s` (ou `tempodirecaodisponivel` zerado) |
| Parada obrigatória | 30 min após 5h30 | ciclo fechado com `tempodescanso < 1800 s` |
| Jornada diária | base 8h + até 2h extra (4h com acordo) | `quantidadehorasemjornada` de `jornadamotoristacalculo` acima do teto parametrizado |
| Interjornada | ≥ 11h de descanso entre jornadas | lacuna entre o `dtfim` da última atividade do dia e o `dtinicio` da primeira do dia seguinte (`jornadamotorista`) |
| Descanso semanal | 35h | **não rastreado** — `jornada_registrofolga` está vazia; exibido como "não rastreado" (não inventamos violação). |
| CNH | válida | `dtvencimentocarteirahabilitacao` < hoje (vencida) ou < hoje+30d (vencendo) |

Os limites (5h30, 30min, teto de jornada, janela de CNH) ficam em **parâmetros**
(`config/jornada_params.yaml` ou constantes no módulo) para calibração sem tocar código.

`jornada_erro` entra como painel secundário "Ocorrências registradas pelo ERP" agrupado por
código, com rótulos best-effort da Lei 13.103 e o **código numérico visível** — a decodificação
definitiva dos códigos 1–6 fica como item de validação com o usuário (conhece a tela do ERP).

## 4. Classificação de risco (semáforo)

Por motorista, no período:
- **Vermelho (crítico):** violação de direção contínua no período, OU CNH vencida.
- **Âmbar (atenção):** horas extras acima do teto, OU interjornada curta, OU CNH vencendo em 30 d.
- **Verde:** sem violações e CNH válida.

## 5. Superfícies

### 5.1 Painel de Jornada (view `jorn`, grupo Operação)
Segue o `dashboard-builder` (torre):
1. **Status (KPIs):** motoristas ativos no período · % em compliance · violações no período · CNHs vencidas/vencendo · horas extras acumuladas.
2. **Decomposição:** violações por tipo (barras) e por período.
3. **Tabela acionável (semáforo):** por motorista, ordenada por risco — nome (CPF mascarado), horas direção/jornada, violações por tipo, CNH, cor. Linha clicável → ficha.
4. **Alertas:** CNH vencendo em 30 d; motoristas com violação hoje.

Filtros: competência (de/até) + filial + busca por motorista. Fonte + timestamp no rodapé.

### 5.2 Ficha do motorista (view `jornf`, aberta ao clicar numa linha)
Análoga às Consultas de Veículo/Cliente:
- KPIs do período: direção, jornada, espera, extras (2h/4h), adicional noturno.
- Timeline de ciclos direção × descanso (`registrodirecaodescanso`), violações destacadas.
- Lista de ocorrências (`jornada_erro`) + CNH (vencimento, categoria, UF).

## 6. Backend

- `queries.get_jornada(comp_de, comp_ate, filial=None, busca=None)` → dict do painel
  (kpis, violacoes_por_tipo, motoristas[], alertas).
- `queries.get_motorista_jornada(motorista, comp_de, comp_ate)` → dict da ficha
  (`motorista` = CPF **recebido do backend**, resolvido internamente; a API aceita um
  identificador opaco, nunca expõe o CPF de volta).
- Endpoints: `GET /api/jornada/painel`, `GET /api/jornada/motorista`.
- SQL: `SET LOCAL enable_mergejoin = off` se algum join degenerar (gotcha do PG 9.3).
  LATIN-1: nunca usar `—`/`•` dentro do SQL (usar `-`); máscara é aplicada em Python.
- Cache: `@cached(ttl=...)` como as demais `get_*`.

## 7. Front

- Views `jorn` e `jornf` em `api/static/index.html`, no padrão loadX/renderX + gráficos SVG
  próprios (sem lib nova). Registrar em VIEWS/VIEW_GROUP/DATAMAP/LOADMAP + router + grupo
  Operação (sidebar e drawer). Filterbar escondida na ficha (busca própria).

## 8. RBAC (`api/auth.py`)

- Telas `jorn` e `jornf` em `TELAS` (grupo "Ope").
- `ROTA_TELAS`: `/api/jornada/motorista` **antes** de `/api/jornada/painel`? Não — prefixos
  distintos, sem colisão; registrar ambos mapeando para as telas certas.
- Adicionar as telas aos perfis-modelo pertinentes (Operação/Controladoria/CEO); seed com nova
  flag (`perfis_modelo_v3`), INSERT OR IGNORE não-destrutivo.

## 9. Testes

`tests/jornada/` — testes **puros** (sem banco) dos cálculos:
- direção contínua (5h30) → detecção de violação a partir de ciclos sintéticos;
- classificação de risco (verde/âmbar/vermelho) por combinação de sinais;
- CNH vencida/vencendo (limiar de 30 d);
- interjornada (lacuna < 11h) a partir de timeline sintética;
- máscara de CPF (reuso de `_mask_doc`).

## 10. Fora de escopo / limitações declaradas

- Descanso semanal 35h (folga vazia no AVA) — exibido como "não rastreado".
- Decodificação definitiva dos códigos `jornada_erro` 1–6 — validar com o usuário.
- Previsão de próxima violação ("descanso em risco ao vivo") — pode entrar numa v2, junto dos
  alertas diários (`api/alertas.py`).

## 11. Validação

Playwright com auth isolada (harness em scratchpad, padrão do projeto): login → painel `jorn`
→ clicar num motorista → ficha `jornf`, capturar screenshots + erros de console. Conferir
que nenhum CPF cru aparece no HTML nem no JSON. Deploy via AutoDeploy e verificação de commit
em produção.
