# Design — Premiação de Motoristas (tela `prem`, Fase 1)

> Data: 2026-07-27 · Origem: brainstorming com o usuário · Status: **aprovado** para
> desenvolvimento. Base: MVP da Transjordano (`/Users/cristiancassoli/MVP_Transjordano`),
> adaptado ao Cortex Sulista.

## Contexto levantado antes do desenho

1. **O MVP Transjordano** é um app React/Vite com 4 telas (Ranking da Premiação com
   parâmetros editáveis, Relatório de Motoristas, Relatório de Pagamento, Comparativo
   mensal), alimentado por snapshots mensais (`premiacao-AAAA-MM.json`) coletados da
   **API Gobrax v3** por `scripts/coletar_medias.py`. O Cortex reimplementa o mesmo
   conteúdo como UMA tela no padrão da casa (vanilla JS, tokens Sulista) — não se
   importa código React nem o design system Gobrax.
2. **A Sulista é cliente Gobrax: `customerId = 1`** (TRANSPORTADORA SULISTA S/A,
   confirmado no `/customers` e pelo usuário). Medido em 2026-07-27:
   **9 veículos na telemetria, ~3 com motorista vinculado, 86 motoristas cadastrados**;
   vínculos criados em 24–27/07 — é um **piloto recém-iniciado**, não a frota inteira
   (a Sulista tem ~374 veículos próprios). O `analysis` já responde: 2 motoristas com
   nota (80 e 74), média e km em julho.
3. **Os vínculos motorista↔veículo mudam ao vivo** (mudaram entre duas chamadas no
   mesmo dia). O `analysis` casa motorista↔veículo pela telemetria quando recebe TODOS
   os veículos do cliente — a média não depende do vínculo estar atualizado.
4. **Produção roda no Windows** (`29Q4L94`): a autenticação do cliente Gobrax existente
   (`Endpoints_v3/gobrax_auth.py`) lê a senha do Keychain do macOS — não portável.
   O fluxo em si é portável: login Ory Kratos (2 chamadas) + JWT de `/user/{email}`.

### Decisões do usuário (brainstorming)

- **Fonte = API Gobrax v3** (como o MVP), customer 1.
- **Regra = a mesma do MVP (litros economizados)**, com **parâmetros próprios da
  Sulista, editáveis na tela** — a gestão calibra sem deploy.

## 1. Regra de premiação (Fase 1)

```
litros_meta         = km_rodado / meta            # litros que a meta previa
litros_consumidos   = km_rodado / media           # litros pela média atingida
litros_economizados = max(0, litros_meta - litros_consumidos)
premio              = litros_economizados × preco_litro × pct_premiacao
elegivel            = km_rodado >= km_minimo
```

- Só há prêmio com `media > meta` e motorista **elegível** (km mínimo). Não elegível
  aparece **atenuado com badge**, nunca escondido (padrão da revisão de telas).
- **Sem arredondamento intermediário**: a conta corre em float e só o prêmio final
  arredonda a 2 casas. Exemplo canônico: km 5.000 · meta 1,90 · média 2,10 ·
  R$ 6/l · 20% → **R$ 300,75** (o doc do MVP mostra 300,60 porque arredonda o valor
  economizado para R$ 1.503 antes do percentual — não reproduzir esse arredondamento).
- **Parâmetros** (arquivo `data/premiacao_params.json`, editáveis pela tela):

| Parâmetro | Default inicial | Observação |
|---|---|---|
| `meta` (km/l) | 2,0 | calibrar com a gestão; ao lado do campo a tela mostra a média da frota no mês (km total ÷ litros totais, ponderada) como referência |
| `preco_litro` (R$/l) | 4,93 | ao lado do campo a tela mostra o preço médio real do diesel interno do período (ctaplus) como referência |
| `pct_premiacao` | 0,20 | 20% do valor economizado |
| `km_minimo` | 500 | elegibilidade; 0 desliga o corte |

- Campos numéricos da tela usam `type="text" inputmode="decimal"` + `numBR()` — nunca
  `type="number"` (que descarta a vírgula) nem `parseFloat` cru.

## 2. Arquitetura e módulos

Novo subpacote **`api/premiacao/`** (padrão `api/dre_cliente/`; nada em `queries.py`):

- **`gobrax.py`** — cliente mínimo da API v3 com **stdlib** (`urllib.request` — o venv
  não tem `requests`/`httpx`; import de `requests` já derrubou a app uma vez):
  - Login Kratos: `POST https://v3.gobrax.com.br/safekratos/self-service/login/api`
    (flow → action → session) com `GOBRAX_EMAIL`/`GOBRAX_SENHA` do `.env`.
  - Token = base64 do objeto `session` (expira ~24h, cacheado em memória; renova em 401).
  - Headers obrigatórios no gateway `https://gateway-v3-waf.gobrax.com.br`:
    `Authorization: Bearer <token>` + `Credentials: <jwt de GET /user/{email}>` +
    `OriginVersion: WEB 3.1` (sem os três, retorna 500).
  - **`:` literal na query** (o gateway rejeita `%3A`) — `urlencode(params, safe=":,")`.
- **`coleta.py`** — coleta um mês do customer 1:
  1. `GET /vehicles?customers=1&operation=true` → veículos (id, placa, modelo) +
     `currentDriver` (vínculo atual).
  2. `GET /drivers?customers=1` → `documentNumber` (CPF) — **mascarado com
     `_mask_doc` ANTES de gravar**; o CPF cru nunca toca o disco nem o payload.
  3. `GET /web/v2/performance/drivers/analysis?drivers=...&vehicles=<TODOS>` em
     lotes de 10 com pausa (0,3 s) — passa todos os veículos do cliente (média por
     telemetria, independe do vínculo do momento).
  - Grava `data/premiacao/premiacao-AAAA-MM.json` (shape do MVP: `source`,
    `customerId`, `month`, `periodStart/End`, `coletado_em`, `drivers[{driverId,
    driverName, documento_mascarado, vehicles[{plate,model}], nota, media, km,
    indicators{scores,percentages,extra}}]`) + `data/premiacao/index.json`.
  - Placas exibidas = vínculo atual do `/vehicles` (limitação aceita na Fase 1: placa
    pode divergir se o motorista trocou de veículo no mês; a média não é afetada).
  - Mês corrente: `periodEnd` = agora; snapshot marcado `parcial: true`.
- **`calculo.py`** — **PURO** (sem rede/arquivo): aplica a regra da §1 a uma lista de
  motoristas + params; devolve linhas com litros/prêmio/elegibilidade e os KPIs.
- **`params.py`** — lê/grava `data/premiacao_params.json` com validação
  (meta > 0, preço > 0, 0 ≤ pct ≤ 1, km_minimo ≥ 0).

### Endpoints (`api/main.py`)

| Rota | Método | Comportamento |
|---|---|---|
| `/api/frota/premiacao?mes=AAAA-MM` | GET | Lê o snapshot do mês + aplica `calculo` com os params atuais. **Mês corrente**: se o snapshot tem >1h (ou não existe), recoleta antes (lock `threading.Lock` — coletas concorrentes esperam). Mês fechado: serve o snapshot; se não existe, coleta uma vez. |
| `/api/frota/premiacao/atualizar` | POST | Força recoleta do mês pedido (mesmo lock). |
| `/api/frota/premiacao/params` | POST | Grava os parâmetros (validação → 422). |

- Registrar em `ROTA_TELAS` (tela `prem`) — prefixo `/api/frota/premiacao` não colide
  com as rotas existentes de frota.
- Respostas incluem `coletado_em`, `parcial` e `params` vigentes.

### Erros e casos de borda

| Situação | Comportamento |
|---|---|
| `GOBRAX_EMAIL`/`GOBRAX_SENHA` ausentes no `.env` | GET responde `configurado: false`; a tela instrui como configurar (padrão Copiloto/OpenRouter). Nomes de variável apenas — **valores nunca aparecem em tela, log ou conversa**. |
| API Gobrax fora / login falhou | Serve o **snapshot antigo** com banner "coletado em <data> — não foi possível atualizar"; sem snapshot algum → 503 com mensagem. |
| Motorista sem média no mês (`consumptionAverage` 0/None) | Fora do ranking, contado no hint ("X de Y motoristas com média"). |
| `media` ≤ `meta` | Prêmio R$ 0 — linha aparece normalmente (desempenho abaixo da meta é informação). |
| `km < km_minimo` | Linha atenuada + badge "não elegível". |
| Mês corrente | KPI/tabela rotulados **parcial**; comparativo desenha o mês com hachura. |
| Coleta concorrente (2 usuários abrem a tela) | Lock: a 2ª espera a 1ª e reusa o resultado. |

## 3. Tela `prem` — "Premiação de Motoristas"

Grupo **Frota** (após Combustível), link na sidebar **e na gaveta mobile**; `NAV_KW`:
premiação, prêmio, bônus, motorista, economia, km/l, telemetria, gobrax. Filterbar
global escondida (`semFilterbar`) — a tela tem seletor de mês próprio.

1. **Barra de contexto**: seletor de mês (do `index.json`, mais recente primeiro) +
   botão "Atualizar dados" (POST atualizar, rótulo vira "Coletando…") + `coletado_em`.
2. **Card Parâmetros da regra**: meta km/l, R$/l, % e km mínimo editáveis
   (`numBR`), com as referências reais ao lado (média da frota no mês; preço médio do
   diesel interno do período via dado já existente do Combustível). Salvar = POST
   params → re-render com os novos valores. ⓘ explica a fórmula.
3. **KPIs (4)**: Prêmio total do mês · Motoristas premiados/elegíveis · Litros
   economizados · Média da frota (km total ÷ litros totais) × meta. Mês corrente: sub "mês parcial".
4. **Card Ranking da premiação** (tabela, maior prêmio primeiro): motorista
   (nome + placas), nota, km, média, litros economizados, prêmio R$. Linha
   **expansível** (padrão forn-row/forn-det) com os indicadores de telemetria:
   scores por indicador (marcha lenta, piloto automático, faixa verde, freio motor,
   aproveitamento, pressão de pneus…) — cores pelo semáforo do design system.
5. **Card Comparativo mensal**: colunas média × meta por mês + linha/rótulo do prêmio
   total (histórico do `index.json`); mês parcial hachurado.
6. **Banner do piloto** (enquanto a cobertura for pequena): "A telemetria Gobrax cobre
   N veículos e M motoristas — a premiação vale para os vinculados, não para a frota
   inteira." (N/M vêm da coleta, não são fixos.)
7. ⓘ de procedência em todos os cards: "API Gobrax v3 · customer 1 · coletado em …".

### PII e segurança

- **CPF nunca cru**: mascarado com `_mask_doc` na gravação do snapshot (fica
  `***.***.XXX-XX`); nome do motorista aparece (tela interna, atrás de RBAC, mesmo
  critério da Torre de Controle/Jornada).
- Credenciais Gobrax **só** em variável de ambiente; o repositório e os snapshots não
  as contêm. Em produção, o usuário adiciona `GOBRAX_EMAIL`/`GOBRAX_SENHA` ao `.env`
  do Windows manualmente.
- O ERP AVA não é tocado por este módulo (exceto a consulta já existente do preço do
  diesel, read-only como sempre).

### RBAC

- `TELAS["prem"] = ("Premiação de Motoristas", "Frota")`; rota em `ROTA_TELAS`;
  perfis Frota/Diretoria; **migração seed `perfis_modelo_v18`** (padrão v17 do
  orçamento — sem ela a tela nasce invisível nos perfis já semeados).

## 4. Testes

- **`tests/premiacao/test_calculo.py`** (puro): fórmula (exemplo do MVP: km 5.000,
  meta 1,90, média 2,10, R$ 6/l, 20% → **R$ 300,75**); media ≤ meta → 0; km < mínimo
  → não elegível; media None → fora; KPIs agregados; arredondamento a 2 casas.
- **`tests/premiacao/test_params.py`**: round-trip do JSON; validação (pct > 1,
  meta ≤ 0 → erro); arquivo ausente → defaults.
- **`tests/premiacao/test_coleta.py`**: com cliente Gobrax **stubado** (fixtures dos
  shapes reais): montagem do snapshot, CPF mascarado (asserta que NENHUM CPF cru
  aparece no JSON serializado), lotes de 10, motorista sem média excluído do ranking
  mas contado.
- **`tests/premiacao/test_gobrax.py`**: montagem de headers/URLs (sem rede);
  `:` literal na query; renovação em 401 (stub).
- Suíte atual (132) continua passando; smoke + `estrutura.py` com `prem` incluída.

## Critérios de aceite (Fase 1)

1. Com credenciais no `.env`, abrir a tela coleta o mês corrente e mostra o ranking
   com prêmio calculado pela regra da §1.
2. Editar um parâmetro (ex.: % de 20 → 25) recalcula o ranking sem recoletar.
3. Exemplo canônico: km 5.000 · meta 1,90 · média 2,10 · R$ 6/l · 20% → R$ 300,75.
4. Motorista abaixo do km mínimo aparece atenuado com badge, não some.
5. Sem credenciais, a tela explica a configuração em vez de quebrar.
6. Gobrax fora do ar: snapshot antigo aparece com o aviso de quando foi coletado.
7. Nenhum CPF cru em snapshot, payload ou HTML (grep no JSON + Playwright).
8. `pytest`, smoke e validador estrutural passam; tela no menu e na gaveta mobile.

## Fora do escopo da Fase 1

- **Ajuste carregado/vazio da meta** (Fase 2 — o AVA tem km carregado/vazio por
  viagem, dado que a Transjordano ainda não tem; cruzar por placa/período).
- Exportação para a folha de pagamento / integração GLOBUS.
- Teto de prêmio, faixas de % por nota, gate de nota mínima.
- Metas por veículo/modelo (a meta é única e global na Fase 1).
- Histórico de vínculos (`exportDriverHistory`) para atribuição fina de placas.
