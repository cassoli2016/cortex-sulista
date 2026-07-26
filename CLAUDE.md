# CÓRTEX — Cérebro de Gestão da Transportadora

> Portal centralizado de inteligência operacional, financeira e estratégica.
> Base única de conhecimento + IA local (Gemma) + agentes especialistas por área.
> Operação de **frota mista (própria + agregados)**, modalidade predominante **lotação (FTL)**.
> **Base de dados única: PostgreSQL** (com TimescaleDB para séries temporais e pgvector para RAG).

Este arquivo é o contexto-mestre lido por qualquer agente de IA (Claude Code, Gemma local
ou orquestrador) antes de atuar. Regras de negócio, modelo de dados, convenções, padrões de
dashboard e limites de segurança estão aqui ou linkados daqui.

---

## 1. Propósito

Transformar dados dispersos (operação, telemetria, financeiro, fiscal, RH) em **decisão rápida**.
Toda resposta cita a fonte e o cálculo/consulta que a originou. Nenhum número sem origem
rastreável entra em decisão.

---

## 2. Stack (PostgreSQL-only)

| Camada | Tecnologia |
|---|---|
| Borda/acesso | Cloudflare Tunnel + Access (zero-trust, MFA, sem porta aberta) |
| Frontend | Next.js (App Router, RBAC no roteador) + camada de dashboards |
| API/app | FastAPI + Pydantic (RBAC, audit, orquestração LangGraph) |
| **Dados** | **PostgreSQL 16** + **TimescaleDB** (telemetria/séries) + **pgvector** (RAG) |
| Tempo real | Postgres LISTEN/NOTIFY + Redis pub/sub → WebSocket (torres) |
| Cache/fila | Redis |
| IA local | Ollama (Gemma) atrás de gateway; Claude API só p/ tarefa pesada sem dado sensível |
| Observabilidade | Prometheus + Grafana + Loki |

Um único Postgres é a fonte da verdade. TimescaleDB resolve telemetria de alta cadência
(hypertables, retenção, downsampling) sem trazer outro banco. Detalhes: `docs/ARQUITETURA.md`.

---

## 3. Módulos do portal

Cada módulo é unidade de RBAC (papel × módulo × escopo de linha via RLS).

| Módulo | Conteúdo | Tabelas/views-chave |
|---|---|---|
| `financeiro` | Caixa, recebimentos, pagamentos, adiantamentos, DRE, análises financeiras, projeções | `fin_titulos`, `fin_adiantamentos`, `fin_lancamentos`, `fin_dre`, `vw_fluxo_caixa`, `vw_dre_mensal` |
| `comercial` | Clientes, fretes, RKM, concentração, churn | `com_clientes`, `com_fretes`, `vw_rkm_cliente` |
| `operacional` | Cargas, viagens, rotas, CKM | `op_viagens`, `op_cargas`, `op_rotas`, `vw_ckm_viagem` |
| `programacao` | Programação de cargas e alocação/gestão de veículos | `prog_cargas`, `prog_alocacao`, `prog_disponibilidade` |
| `torre_controle` | Monitoramento operacional em tempo real: posição, status, ETA, ocorrências | `tc_posicoes` (hypertable), `tc_ocorrencias`, `vw_viagens_ativas` |
| `torre_seguranca` | Segurança em tempo real: eventos de risco, score, sinistralidade, alertas | `ts_eventos` (hypertable), `ts_scores`, `vw_sinistralidade` |
| `telemetria` | Telemetria avançada (CAN/J1939) com insights: consumo, ECO, falhas, DTCs | `tel_sinais` (hypertable), `tel_dtc`, `vw_consumo_veiculo` |
| `frota` | Ativos, disponibilidade, manutenção, pneus, depreciação | `fro_veiculos`, `fro_manutencao`, `fro_pneus` |
| `jornada` | Jornada do motorista (Lei 13.103/2015): direção/descanso/intervalo, compliance | `jor_eventos` (hypertable), `jor_jornadas`, `vw_compliance_jornada` |
| `suprimentos` | Agregados, fornecedores, contratos, make-vs-buy | `sup_agregados`, `sup_fornecedores`, `sup_contratos` |
| `gestao` | Metas, KPIs, OKRs, atas de reunião, planos de ação | `ges_metas`, `ges_okr`, `ges_atas`, `ges_acoes` |
| `integracoes` | Central de integração com APIs de fornecedores (hub de conectores) | `int_conectores`, `int_sync_state`, `int_raw_events`, `int_dead_letter` |
| `analytics` | Painel CEO consolidado, previsões e projeções | views materializadas + skill previsao-projecao |
| `copiloto` | Interface conversacional (Gemma + agentes) | — |

---

## 4. Regras de negócio essenciais (glossário canônico)

Todo agente e toda query usa EXATAMENTE estas fórmulas.

```
RKM (receita/km)            = receita_frete / km_carregado
CKM bruto                   = custo_operacional_total / km_total
CKM produtivo               = custo_operacional_total / km_carregado
Retorno vazio (%)           = (km_total - km_carregado) / km_total      # alerta > 20% FTL
Margem de contribuição/km   = RKM - CKM_variavel
Resultado da viagem         = (RKM * km_carregado) - (CKM_var * km_total) - fixo_rateado
Spread make-vs-buy          = CKM_proprio - rkm_pago_agregado
```

**Frota mista:** curto prazo compara agregado contra **CKM marginal** (var + motorista);
longo prazo (comprar veículo) compara contra **CKM cheio** (com fixo + depreciação).

**Jornada (Lei 13.103/2015):** direção contínua máx. 5h30 antes de parada de 30 min;
descanso interjornada 11h; intervalo intrajornada 1h; descanso semanal 35h. Violação = alerta.

**Fiscal/logística:** CT-e e NF-e são fontes primárias de receita/carga. Atenção a GRIS,
ad valorem, ICMS por UF e piso mínimo ANTT.

---

## 5. Padrão de Dashboards e Painéis (LER ANTES DE CRIAR QUALQUER PAINEL)

Toda construção de painel segue a skill `dashboard-builder` e este padrão:

**Anatomia de um painel (top-down, leitura em camadas):**
1. **Linha de status** (topo): 3–6 KPIs-chave com valor, meta e seta de tendência. Semáforo.
2. **Visão temporal**: série principal do painel (tendência) com comparação vs meta/período.
3. **Decomposição**: quebra do número-chave por dimensão (rota, cliente, veículo, motorista).
4. **Tabela acionável**: linhas ordenadas por prioridade/risco, com ação sugerida.
5. **Alertas**: ocorrências que exigem ação agora.

**Design system (valores reais implementados — tokens em `api/static/index.html`):**
- **Marca:** amarelo Sulista `#FFD31C` = `--brand`, usado SÓ em superfície escura (trilho
  do nav ativo na sidebar/bottomnav navy, logo) — contraste ruim no branco (1,44:1), NÃO é
  accent de UI clara. **Accent geral da UI clara:** laranja `#E85D10` = `--orange-500` (foco,
  drawer ativo, destaque de gráfico contratado).
- **Semáforo:** ok verde `#1E7F4F` (`--green`), warn âmbar `#B97709` (`--yellow`), alerta
  vermelho `#C03221` (`--red`). Painéis de TV (fundo escuro) usam o conjunto brilhante
  `#4ADE80`/`#FBBF24`/`#F87171`. Não introduzir outros tons de estado.
- **Neutros:** ink `#14181D` (`--n900`), secundário `#6B7580` (`--n500`, ajustado p/ AA 4,5:1).
- **Navy dos gráficos:** família `--navy-*` (700/500/400/100), derivada em JS via `CC.navyX`.
- **Fonte:** **Saira** (`--font`, condensada/técnica — combina com painel operacional; via
  Google Fonts) + **IBM Plex Mono** (`--mono`) nos dados/tabelas numéricas. (A spec original
  dizia Inter; a implementação escolheu Saira e ela ficou — mais característica que o default.)

**Padrões por torre/área (especificação em `dashboard-builder`):**
- **Torre de Controle:** mapa ao vivo + viagens ativas + ETA/atraso + ocorrências abertas.
- **Torre de Segurança:** score de risco por motorista/veículo + eventos críticos + sinistralidade + heatmap de risco.
- **Telemetria avançada:** consumo (km/l) vs alvo, uso de ECO/embalo, DTCs ativos, ranking de eficiência, insight em linguagem natural gerado pelo agente.
- **Programação de cargas:** quadro (kanban/gantt) de cargas × veículos, gargalos, ociosidade.
- **Jornada:** semáforo de compliance por motorista, horas dirigidas vs limite, próximas violações previstas.
- **Financeiro/DRE:** fluxo de caixa projetado, DRE em cascata, aging de recebíveis.
- **Metas/KPIs/OKRs:** progresso de cada OKR (key result × atual × meta × prazo), farol.

**Padrões de componente (implementados na Visão Geral — reusar, não reinventar):**
- **Bandas de KPI (`.kband` + `.kpis.k4`)**: KPIs agrupados por TEMA, com rótulo da banda,
  em grade de **nº de colunas fixo**. A contagem de cards por banda é **múltiplo de 4**
  (4 → 2 → 1 nas quebras) — o `auto-fit` deixava o último card sozinho numa linha.
- **Chip de tendência (`trendChip(atual, ant, {invert})`)**: seta ▲/▼/— + variação %.
  Comparação sempre em **janela equivalente** (mês até hoje × mesmos dias do mês anterior);
  `invert:true` para CUSTO (cair é bom); variação < 1,5% = "estável". A classe é a
  **leitura** (`good`/`bad`/`warn`), não a direção — a cor sai sempre do semáforo.
  `statChip(cls, texto, titulo, icone)` para estado sem percentual.
- **ⓘ de procedência (`.ihelp` dentro do `<h2>`)**: todo card diz no hover a tabela/regra
  de origem. Obrigatório onde há recortes parecidos (as 3 receitas: faturas emitidas ×
  frete das viagens × CT-e+KMM+NFS-e da meta).
- **Período incompleto nunca é barra cheia**: mês corrente com hachura + rótulo "parcial",
  e a média de referência é calculada só sobre meses FECHADOS.
- **Semáforo em gráfico é DISCRETO** (≥95% / 70–94% / <70%), nunca degradê contínuo —
  tom intermediário não existe no design system e não diz em que estado o dado está.
- **Gráfico em card de meia largura usa viewBox estreito** (640, classe `.chartwrap.narrow`):
  com 960 o SVG era reduzido a ~70% e a tipografia dos eixos ficava ilegível.
- **Parte-do-todo com uma categoria dominante não é donut**: barra horizontal empilhada
  ordenada (ver "Km rodado por modalidade" — AGREGADOS é ~80% do km).

**FILTROS — revalidar em toda tela revisada (regra permanente):**
Toda tela que passar por revisão tem os filtros conferidos contra o próprio contexto:
listar o que o `qsView()` da vista manda × o que a query realmente consome. **Filtro que
a query ignora sai; dimensão que a query aceita e é a pergunta natural da tela entra.**
- **Período por preset**: o grupo de emissão (`grpEmi`, compartilhado por com/oc/agr/comb/
  man/km/mul/rent) tem `fEmiPreset` — Este mês · Mês passado · Últimos 3 meses · Últimos 90
  dias · Ano corrente · Últimos 12 meses. O select preenche as datas; digitar data volta
  para "Personalizado". **As datas são compartilhadas entre essas telas**, então
  `emiPresetSync()` roda no router (troca de vista) e no fim do render — sem isso o rótulo
  do preset mentiria sobre o recorte.
- Datas sempre em **horário local** (`_iso()`): `toISOString()` em UTC−3 volta um dia.
- **Recorte parcial nunca é barra cheia**: se o filtro corta o primeiro/último mês, a barra
  sai hachurada e rotulada "parcial" (`comParcial()`), com o aviso repetido no tooltip.
- **Card que NÃO segue os filtros leva badge visível** (ex.: "Meta × realizado" é sempre o
  mês corrente). Enterrar isso no texto do hint faz o número parecer furado.

**Séries de escalas diferentes no mesmo eixo (lição do Fluxo de Caixa):**
- Uma projeção otimista de longo prazo **esmaga a série contratada**: o saldo projetado
  variava ~R$ 11 mi e o "realista" chegava a +R$ 118 mi, deixando a linha que decide caixa
  com **9% da altura**, colada no zero. Cenário especulativo entra por **toggle, desligado
  por padrão** — nunca compartilhando escala com o dado firme sem aviso.
- **Projeção fica irreal quando um lado da conta some**: os pagáveis LANÇADOS caem de
  R$ 5,7 mi para R$ 1,2 mi ao longo do horizonte, então a linha de cenário vira receita
  estimada contra custo inexistente. Marcar no gráfico o ponto em que isso começa
  (`fluxoExtrapola`: pagáveis < 40% da média dos 3 primeiros meses) e dizer no aviso.
- **Número estruturalmente negativo leva chip explicando**, não vermelho e silêncio:
  "Posição líquida (aberto)" é sempre negativa porque o a pagar carrega longo prazo sem
  a receita correspondente lançada — não é insolvência.
- **Dois filtros de janela temporal na mesma tela precisam dizer o que cada um recorta**
  (Vencimento = quais títulos entram; Horizonte = quantos meses projeta). E documentar as
  assimetrias reais: "A receber vencido" usa a data de referência e IGNORA o filtro de
  vencimento, enquanto "A receber (aberto)" respeita.

**Ranking e tabela analítica (lições da DRE por Cliente):**
- **Ordenar por percentual sem piso de materialidade mente**: o ranking abria por MC% e
  o 1º lugar era cliente com 1 viagem e R$ 2,8 mil de receita (85%), com TUPY (R$ 10,2 mi)
  no meio da lista. Padrão = valor absoluto (materialidade); **cabeçalho clicável** para
  reordenar; registro de baixo volume fica **atenuado com badge**, nunca escondido.
- **Tabela de DRE tem análise vertical**: cada linha também como **% da receita líquida**
  do próprio cliente — é assim que se compara estrutura de custo entre clientes.
- **Cobertura/reconciliação leva semáforo** (≥90 verde · 70–89 âmbar · <70 vermelho).
  Cobertura baixa em CUSTO FIXO significa margem direta PARCIAL; em preto neutro o número
  passa como se estivesse tudo certo.
- **Rótulo de scatter precisa de anti-colisão**: nomes empilhados (VOLVO/TWE,
  TUPY/FORVIA) viram borrão. Empurrar na vertical, ligar por linha-guia à bolha e usar
  halo branco (`paint-order:stroke`).

**Volume e qualidade do dado (lições do CRM):**
- **Tabela longa rola DENTRO do card** (`.tabroll`, cabeçalho sticky) + contador
  "X de Y" no hint. O CRM desenhava 200 leads + 150 projetos e a página passava de
  **16.000px**; com rolagem interna caiu para 1.700px.
- **Lista dominada por registros encerrados abre nos ATIVOS.** 135 de 150 projetos
  "Entregue" enterravam os 9 em andamento — chips de status com default nos ativos.
- **KPI que só pode dar zero por falta de preenchimento mostra "não informado"**, nunca
  `R$ 0` — e JAMAIS em verde. O ROB do pipeline lia R$ 0 em verde porque o ERP só
  preenche o campo nos projetos já entregues: parecia pipeline sem valor, era lacuna
  de cadastro. Mostrar junto o número que existe de verdade (ROB entregue).
- **Total que esconde composição vira composição.** "Potencial R$ 36,7 mi" com 82% dos
  leads frios não é pipeline; o KPI mostra a quebra por temperatura e um chip "79% frio".
- **Cobertura ruim de campo é informação, não sujeira para esconder**: "ROB previsto
  informado em 1 de 200 leads" no hint — é acionável para quem preenche.

**Unidade, zero e escopo do filtro (lições da Análise de KM):**
- **Rótulo de eixo nomeia a unidade FINAL, nunca composta.** `MIL KM ×1000` mandava o
  leitor multiplicar de cabeça e lia-se como mil quando valia **milhão** — vale
  `MILHÕES DE KM`. Se o rótulo precisa de aritmética, está errado.
- **Zero que é ausência de lançamento não é desempenho — é `n/d` em cinza.** Terceiro
  aparecia com "0% de retorno vazio" em VERDE (melhor da tabela): o ERP simplesmente
  não recebe o deslocamento vazio do terceiro (121 viagens vazias × 3.559 carregadas
  em 18 meses, ~3%, contra ~30% em frota/agregado/locação). Antes de pintar um zero
  de verde, conferir no banco se a série existe.
- **Todo KPI da tela obedece a TODOS os filtros da tela.** "Custo do vazio" era
  calculado sempre sobre frota+locação do período inteiro, ignorando filial e
  modalidade: com `Modalidade = Locação` o cabeçalho dizia 143.326 km vazios e a
  tabela logo abaixo dizia 95.632. Quando o filtro **exclui** a base do KPI
  (modalidade agregado/terceiro num KPI de diesel próprio), o KPI mostra `—` e
  explica — não repete o número de outro recorte.
- **Escopo agregado precisa estar no subtítulo.** "frota própria" somava TRA+LOC e não
  batia com nenhuma linha da tabela; virou "frota + locação".
- **Rótulo de série não pode nascer sobre a barra.** O % do retorno vazio acima do
  ponto caía dentro da barra empilhada; sai ao lado (`px ± barW/2 + 7`, âncora
  invertida no último mês). Linha sobre eixo secundário sem escala **exige** rótulo
  direto — sem ele o leitor não tem como ler valor nenhum.
- **Mês parcial é o cortado pelo FILTRO, não só o corrente.** Um período de 90 dias
  começa no meio do mês: a primeira barra parecia despencar. A hachura marca os dois
  casos (`_corta(mes)` compara o mês com `dt_de`/`dt_ate`).

**Telas de consulta (busca própria, filterbar global escondida — ex.: Consulta de Cliente):**
- Campo de busca com **`<datalist>`** alimentado por endpoint LEVE e cacheado
  (`/api/comercial/clientes-lista`, ~34 grupos). Nunca reusar o endpoint do painel
  inteiro só para preencher sugestão. Rota nova mais específica entra ANTES da genérica
  em `ROTA_TELAS` (`/clientes-lista` antes de `/clientes`), senão o prefixo casa errado
  e barra quem só tem a tela de consulta.
- Consulta lenta (a ficha reusa a DRE por Cliente, ~2,5 s) **muda o rótulo do botão**
  para "Buscando…" e desabilita — o spinner global não basta.
- **Série temporal de graça**: quando a consulta já traz as linhas detalhadas em memória,
  agregar por mês em Python custa zero consulta e transforma uma tela só-de-tabela numa
  tela com tendência.

**GOTCHA de JS (derrubou o painel inteiro uma vez):** `const` de TOPO não pode ler `CC`
— o objeto só é criado lá pelo fim do arquivo e a leitura antecipada estoura
`ReferenceError` (TDZ) que mata o script no boot (login não some da tela). Cor de paleta
em estrutura de topo: resolver dentro de **função**, na hora de desenhar.

**Padrões de tela de conversa (Copiloto — reusar em qualquer chat futuro):**
- **Coluna de leitura travada** (`.cop-card>*{max-width:760px}`): o card ocupa a largura
  cheia (moldura igual às outras telas), o conteúdo centraliza. Bolha a 78% de um card de
  1400px dava linha de ~1100px.
- **Estado vazio é bloco centrado** (`.cop-card.vazio`), não hero no topo + chips no rodapé:
  um `flex:1` no meio abria ~600px de branco morto.
- **Conversa ancorada embaixo** com `.cop-msgs>*:first-child{margin-top:auto}` —
  `justify-content:flex-end` impede rolar até o topo quando o conteúdo passa da altura.
- **Ação de mensagem fica FORA da bolha**: o streaming reescreve o `innerHTML` de
  `#cop-last` a cada delta e apagaria qualquer coisa dentro dela. E **sempre visível**,
  nunca só em `:hover` — no celular não existe hover.
- **Procedência da IA**: a tela diz quais telas alimentam o snapshot, a hora dele e que só
  vão **KPIs escalares** (sem nome de cliente, placa, motorista, CNPJ). Fonte que falha
  aparece como chip âmbar — antes ia calada para o prompt.
- **Link para tela citada** sai de lista CURADA de expressões × view, filtrada por
  `podeVer()` (RBAC). Casar o texto direto contra `VIEWS` manda o gestor para a tela errada.

Regra: todo painel tem **fonte do dado + timestamp**; nenhum gráfico sem rótulo direto;
todo número-chave traz **comparação** (vs meta, vs período anterior).

---

## 6. Agentes disponíveis (`.claude/agents/`)

| Agente | Quando usar |
|---|---|
| `orquestrador` | Entrada. Classifica, roteia, consolida, cita fonte. |
| `financeiro` | Caixa, recebimentos, adiantamentos, DRE, projeções financeiras. |
| `comercial` | Clientes, pricing/RKM, concentração, churn. |
| `operacional` | Cargas, rotas, CKM, retorno vazio, resultado por viagem. |
| `programacao` | Programação de cargas e alocação de veículos. |
| `torre_controle` | Monitoramento operacional em tempo real, ETA, ocorrências. |
| `torre_seguranca` | Score de risco, eventos críticos, sinistralidade, alertas. |
| `telemetria` | Telemetria CAN/J1939, consumo, ECO, DTCs, insights de eficiência. |
| `frota` | Disponibilidade, manutenção (preditiva), pneus, depreciação. |
| `jornada` | Compliance de jornada (Lei 13.103), risco de violação. |
| `suprimentos` | Agregados, fornecedores, make-vs-buy. |
| `gestao` | Metas, KPIs, OKRs, atas de reunião e planos de ação. |
| `integracoes` | Central de integrações: saúde dos conectores, sync, dead-letter, novos fornecedores. |
| `analista_preditivo` | Previsões e projeções (caixa, demanda, manutenção, churn). |

Cada agente herda o RBAC do usuário e só acessa seu(s) módulo(s).

## 7. Skills disponíveis (`.claude/skills/`)

| Skill | Função |
|---|---|
| `dashboard-builder` | Padrão e especificação para criar painéis/dashboards de qualquer área. |
| `calculo-ckm` | CKM próprio desmembrado. |
| `fluxo-de-caixa` | Projeção de caixa com gaps. |
| `make-vs-buy` | Próprio vs agregado por rota. |
| `analise-rota` | Diagnóstico de rota (RKM, CKM, vazio, margem). |
| `scoring-cliente` | Score de cliente (rentabilidade, inadimplência, churn). |
| `telemetria-insights` | Telemetria avançada → insights (consumo, ECO, falhas). |
| `programacao-cargas` | Alocação de cargas a veículos, ociosidade, gargalos. |
| `jornada-motorista` | Cálculo de jornada e compliance Lei 13.103/2015. |
| `previsao-projecao` | Previsões/projeções (séries temporais, cenários). |
| `dre-analise` | DRE gerencial em cascata e análise de margem. |
| `analista-contabil` | Classifica lançamentos (conta/centro de custo/grupo DRE), rateio, competência e ajustes. |
| `metas-okr` | Estrutura e acompanha metas, KPIs e OKRs. |
| `ata-reuniao` | Ata estruturada com decisões e plano de ação (5W2H). |
| `connector-builder` | Cria conector de fornecedor novo na Central de Integrações (interface padrão). |
| `relatorio-pdf` | Relatório PDF no design system. |

---

## 7.1 Central de Integrações (hub de conectores)

Conecta o CÓRTEX às APIs de fornecedores (telemetria, combustível, pedágio, fiscal, bancos,
mapas, risco) e normaliza tudo para um **modelo canônico único** que alimenta os módulos.

Arquitetura de **plugins**: o núcleo é estável; integrar um fornecedor novo = implementar a
interface `Connector` (authenticate, fetch, handle_webhook, normalize, health_check) + registrar.
**Nenhuma alteração no core.** É o que mantém o sistema sempre pronto para a próxima demanda.

Resiliência embutida: retry com backoff, circuit breaker por conector, rate limit, idempotência
(`chave_idem`), dead-letter queue. Pull (polling incremental por cursor) e push (webhook com
HMAC) suportados. Event bus em Redis Streams; trilha bruta em `int_raw_events`.

Para adicionar fornecedor → skill `connector-builder`. Detalhe completo → `docs/INTEGRACOES.md`.

---

## 8. Segurança — regras que NENHUM agente viola

1. Agente herda o RBAC do usuário. Sem dado fora do escopo. Sem exceção.
2. Toda escrita exige confirmação humana explícita + entra no `audit_log`.
3. Dado sensível (financeiro, PII de motorista/cliente) **nunca** vai para a Claude API —
   só Gemma local. O orquestrador bloqueia roteamento externo se detectar PII.
4. Segredos vêm de cofre/variáveis de ambiente (`.env` nunca versionado).
5. Toda resposta numérica cita fonte (tabela/view/query) e timestamp.

Modelo completo: `docs/SEGURANCA.md`.

---

## 9. Como rodar (dev)

```bash
docker compose up -d postgres redis ollama   # postgres = imagem TimescaleDB
ollama pull gemma2:9b

# backend + migrations (pyproject e alembic na raiz)
uv sync
uv run alembic upgrade head            # aplica sql/blocks via migrations/versions
uv run uvicorn api.main:app --reload

# frontend
cd web && pnpm i && pnpm dev
```

Schema: `sql/schema.sql` é a referência consolidada; as migrations em `migrations/versions/`
executam os blocos de `sql/blocks/` de forma versionada.
Copie `.env.example` → `.env`. Nunca commite `.env`.

---

## 10. Roadmap de implementação

1. **Fundação:** auth + RBAC + RLS + audit + módulo financeiro (caixa/recebimentos/DRE).
2. **Operacional + Programação:** viagens/cargas + CKM + programação de cargas.
3. **Telemetria + Torres:** ingestão (TimescaleDB) + torre de controle + torre de segurança.
4. **Jornada:** compliance Lei 13.103 + alertas preventivos.
5. **Central de Integrações + IA local:** hub de conectores (telemetria/combustível/fiscal/
   bancos) + gateway Gemma + RAG + agentes + copiloto conversacional.
6. **Gestão + Preditivo:** metas/OKR/atas + previsões/projeções + painel CEO.
