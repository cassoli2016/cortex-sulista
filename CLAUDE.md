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

### Onde o dado é ESCRITO (estado real, 27/08/2026)

São **dois** PostgreSQL, e confundi-los custa caro:

| | Quem é | Como se fala com ele |
|---|---|---|
| **AVA (ERP)** | réplica do ERP legado, de terceiro, **somente leitura**, remota | `api/db.py` · variáveis `POSTGRES_*` |
| **CÓRTEX** | o banco da casa, onde o sistema **escreve**, local, schema `cortex` | `api/pglocal.py` · variáveis `CORTEX_PG_*` |

Toda escrita do CÓRTEX (usuários e RBAC, orçamento, extrato, antecipações,
previsão, contrapartida, RNTRC, correio, push) vive no segundo. Os dez bancos
SQLite de `data/` foram migrados para lá em 27/08/2026; os arquivos `.db`
continuam no disco como desfazer e a Saúde do Servidor os marca como migrados.

**Ao criar módulo novo que escreve:** use `api/pglocal.py`, nunca abra SQLite.
A tabela leva o **prefixo do módulo** (`fin_*`, `ext_*`, `orc_*`…) e o DDL vira
uma migration numerada em `sql/cortex/`, aplicada por
`scripts/migrar_schema.py`. O módulo expõe `ESQUEMA` para o teste redirecionar,
e o teste usa a fixture `esquema_pg` (schema por teste). Plano, decisões e as
armadilhas encontradas: **`docs/MIGRACAO_POSTGRES.md`**.

Continuam FORA do banco, de propósito: cache reconstruível
(`data/telemetria.db`, `data/pneus/`, `data/premiacao/`, `data/dre_cliente/`) e
segredo em arquivo com permissão 0600 (`data/credenciais.json`, os `.pfx` e
`data/certificados/senhas.json`).

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
| `telemetria` | Dados da plataforma Gobrax por API com token: premiação por nota × km, consumo × abastecimento, condução e hodômetro/rastro | `api/gobrax/`, `data/premiacao/` |
| `antt` | Piso mínimo de frete da compra e situação do RNTRC dos transportadores contratados | `config/antt_coeficientes.yaml`, `config/antt_eixos.yaml`, `programacaoembarque` (AVA) |
| `gestao` | Metas, KPIs, OKRs, atas de reunião, planos de ação | `ges_metas`, `ges_okr`, `ges_atas`, `ges_acoes` |
| `integracoes` | Central de integração com APIs de fornecedores (hub de conectores) | `int_conectores`, `int_sync_state`, `int_raw_events`, `int_dead_letter` |
| `whatsapp` | Envio de mensagens por WhatsApp via Z-API e os MODELOS de texto reusáveis pelas áreas (aba de Gestão, só admin) | `api/whatsapp/`, `zap_envios`, `zap_modelos` |
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
Piso minimo ANTT            = (km × CCD) + CC        (tabela vigente NA DATA DA VIAGEM)
Retorno vazio obrigatorio   = 0,92 × CCD × km        (só conteinerizada; sem CC)
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

**Gráfico: SVG à mão por padrão, ECharts quando a interação for o ponto.**
São 43 gráficos SVG escritos à mão no `index.html` — e continuam sendo, porque
carregam as regras que esta seção documenta (mês parcial hachurado, rótulo
direto, semáforo discreto, anti-colisão, teclado) e reescrevê-los seria semanas
para perder cada uma.

**ECharts 5 (Apache 2.0) entrou em 27/08/2026**, vendorizado em
`api/static/vendor/echarts.min.js` com a licença ao lado, e é a escolha quando
o painel precisar de **zoom/pan em série longa, drill-down, exportação, gantt
ou mapa** — coisas que o SVG à mão não faz. Primeiro uso: o gráfico mensal da
Produtividade de Veículos.

Três regras para usá-lo, todas com teste em `tests/frontend/test_echarts_e2e.py`:

1. **Carga SOB DEMANDA** (`carregarECharts()`): são 990 KB, e as 62 telas que
   não usam biblioteca não pagam por ele. Há teste que falha se a Visão Geral
   baixar o arquivo.
2. **Vendorizado, NUNCA CDN.** O painel roda atrás do túnel e hoje não depende
   de host externo em tempo de execução; trocar isso por conveniência seria
   comprar um ponto de falha.
3. **A biblioteca não dispensa as regras da casa.** Mês parcial continua
   hachurado (`decal`), linha em eixo secundário continua com rótulo direto, e
   eixo continua com a unidade FINAL. Falha ao carregar é DITA no cartão —
   cartão vazio faria parecer "sem viagem no período".

**Não usadas, e por quê:** amCharts 5 — o CÓRTEX é atrás de login, então a
licença seria a Single App a US$ 650 perpétua/assento, e a versão grátis proíbe
esconder o logo, que apareceria no mural do corredor. **ApexCharts — cuidado:
parece livre e não é.** Deixou de ser MIT e hoje cobra de organização com mais
de US$ 2 milhões de receita anual, incluindo ferramenta interna. Chart.js (MIT)
entrega menos que os 43 gráficos já fazem. uPlot (MIT, 49 KB) fica como opção
se algum dia o problema for só série temporal longa.

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

**Coluna zerada com KPI cheio = join quebrado (lição de Agregados e Terceiros):**
- A coluna "Acertos" mostrava `0` e `R$ 0` nos 30 transportadores enquanto o KPI
  somava **794 acertos / R$ 22,9 mi**. Causa: `acertoviagemagregado.cnpjcpfcodigo` é
  **NULL em 100% das linhas** neste ERP — o vínculo é **`cnpjcpfcodigoveiculo`**
  (casa em 74 de 75 códigos). Regra: quando o total existe e o detalhe é todo zero,
  o problema é o join, não o negócio — conferir no banco se a coluna do `ON` tem dado.
- Filtrar `semaforo = 1` também em tabelas satélites (havia 1 acerto cancelado no total).
- **Total do KPI ≠ soma da coluna quando a tabela é top-N.** O hint diz quanto o
  recorte explica: "30 de 102 transportadores · 774 dos 793 acertos".

**Competência aberta e coluna constante (lições de Make vs Buy):**
- **Competência do mês corrente NÃO é queda de custo.** O CKM cheio caía de R$ 26 para
  R$ 15 em jul/26 porque o rateio de fixos entra incompleto. O trecho até o mês aberto
  vira **pontilhado (2 4)** com ponto vazado e faixa cinza "competência aberta" atrás —
  padrão para toda série mensal que dependa de lançamento contábil.
- **Coluna que repete o mesmo valor em todas as linhas sai da tabela.** "CKM marginal"
  trazia R$ 12,60 nas 25 rotas (é a média global — o razão é consolidado, não há CKM por
  rota) e passava a impressão de cálculo por rota. Virou referência no hint; a coluna de
  spread, que era só uma subtração dessa constante, ficou.
- **Veredito que a própria tela sabe que é frágil diz isso no título.** 45% do CKM cheio
  é fixo+depreciação rateado só sobre o km da FROTA PRÓPRIA, embora o mesmo fixo sustente
  a gestão dos agregados: o "não expandir frota própria" ganha "— mas revise o rateio
  antes de decidir" quando fixo/CKM cheio > 35%. Decisão de mudar o rateio é do usuário.

**Média que junta populações diferentes (lição de Veículos):**
- "Idade média 11,2 anos" somava três coisas incomparáveis: os **987 veículos de
  TERCEIRO** (que a Sulista não possui), os cavalos e as carretas. Separado: frota
  própria de **tração 6,9 anos**, implemento **12,9**, locação 3,4, frota 13,6.
  Antes de mostrar uma média, checar se a população é homogênea — se não for, o KPI
  vira o subconjunto que interessa e a quebra vai para a tabela.
- **Top-N em tabela sem contador vira total falso.** `LIMIT 20/15/20` faziam o hint
  dizer "1.373 veículos" quando os ativos eram 1.414. Todo hint de tabela cortada diz
  "20 de 35 tipos · 1.373 de 1.414 veículos".
- **Filtro novo só entra se mudar a leitura.** O grupo tração/implemento/apoio entrou
  porque sem ele a idade média não decide renovação; e ele valeu para TODAS as queries
  da tela (KPI e tabela de utilização usavam `FROM veiculo v` cru e escapariam).

**Ficha de item (lições da Consulta de Veículo):**
- **Rótulo de KPI muda com a natureza do item.** "Faturamento" na ficha de um veículo de
  AGREGADO parecia o que o agregado recebeu, quando é a receita que a Sulista cobrou do
  cliente. Virou "Receita gerada", e para AGR/TER entra o KPI que faltava — "Pago ao
  transportador" (`valorfretecompra`) com o % da receita.
- **Janela fixa numa ficha gera contradição entre telas.** Os 30 dias fixos davam 9% de
  retorno vazio numa placa que a Análise de KM (90 dias) mostrava com 33,5% — os dois
  certos. A ficha ganhou seletor 30/60/90/180 e todo rótulo carrega a janela ativa
  (`JAN`), além do ⓘ avisando que lá o agrupamento é por EMISSÃO e aqui por CHEGADA.
- **Data vinda de `to_char(...,'YYYY-MM-DD HH24:MI')` precisa de `fmtDT()` na exibição** —
  a ficha mostrava `2026-07-25 02:15` no meio de um app todo em pt-BR.
- **GOTCHA de tooltip:** `title="..."` escrito DIRETO no HTML quebra se o texto tiver
  aspa dupla (`"Ano médio"` fechava o atributo e engolia o resto da tag). Usar aspas
  curvas `“ ”`. Nos KPIs isso não acontece — `kpi()` passa por `esc(h)`.
- **NUNCA rodar correção de aspas em massa sobre o arquivo inteiro.** Um script que
  varria todo o `index.html` trocando aspas internas de `title="..."` também pegou
  ocorrências dentro de TEMPLATE STRINGS de JS (`kpiLink`, `statChip`, DRE, Custos
  Extras, Régua) e converteu a aspa DELIMITADORA: virou
  `title="…“><div class=”label">`, jogando valor e subtítulo para fora do card em
  toda a Visão Geral. **`node --check` NÃO pega** (aspa curva é caractere válido dentro
  de string) e o smoke também não (conta KPIs, não valida estrutura). Corrigir sempre
  por substituição literal de trecho conhecido, um a um.
- **Verificação estrutural** (`scripts/verificar_estrutura.py`): percorre as 31 telas e falha
  se houver atributo cujo NOME contenha aspa, `.val` fora de `.kpi` ou aspa curva em
  `class`/`style`. Rodar junto com o smoke depois de qualquer mexida ampla no HTML.

**Alerta impossível é cadastro, não operação (lição da Manutenção Preventiva):**
- **Desvio maior que um ciclo inteiro do próprio indicador = dado furado.** A tela
  mostrava `-454.436 km` "vencida" num intervalo de 50.000 (9×): o marcador da próxima
  troca parou em 77.534 enquanto o odômetro está em 531.970 — plano nunca atualizado.
  Era o ÚNICO item vencido da tela, ou seja o KPI de vencidas era 100% falso positivo.
- **O erro no sentido oposto é pior porque é invisível:** marcador 204.258 km À FRENTE
  (+4,1×) faz o veículo nunca disparar alerta e sair do controle sem aparecer em lista
  nenhuma. Regra: `|falta| > intervalo` → sai de vencida/próxima e vai para um card
  "Planos a corrigir no cadastro", com odômetro → alvo e o desvio em múltiplos.
- **Mostrar a evidência ao lado do número acusado.** Coluna `Odômetro → alvo`
  (`531.970 → 77.534`) prova o diagnóstico sem precisar de explicação.
- **Chip igual para 2 e para 29 dias não prioriza.** 36 carretas todas "próxima" em
  âmbar: a cor do prazo passou a graduar (≤7 vermelho, ≤15 âmbar) e entrou o KPI
  "Vence em até 7 dias" — 9 de 36, o que realmente vira agendamento nesta semana.
- **Coluna sempre vazia é coluna a preencher ou remover:** "Tipo" das carretas estava
  em branco nas 36 linhas; virou carroceria + o prazo aplicado (`SIDER · 180d`), que é
  o que explica por que umas têm 240 dias.
- **Horizonte fixo esconde planejamento:** os 30 dias das carretas eram fixos; com
  seletor 15/30/60/90 a agenda do mês seguinte aparece (22 → 36 → 59 → 76 carretas).

**Denominador errado transforma cadastro em crise (lição da Comunicação Rastreadora):**
- **664 de 836 rastreadores "sem sinal" (79%) não era falha de rastreamento.** A quebra:
  341 veículos de TERCEIRO (não integram posição com a Sulista) + 312 implementos
  (carreta não emite; campo herdado do cadastro) + **11 que de fato deveriam comunicar**.
  O KPI virou **cobertura da frota que DEVE comunicar** — com motor, próprio ou agregado:
  86,7% (156 de 180). Antes de anunciar um problema, checar se o denominador só contém
  quem pode cumprir a regra.
- **Número grande sempre acompanhado da quebra que o desarma** — card "Rastreador
  cadastrado sem sinal" por tipo × com-motor, com a leitura de cada linha em texto.
- **Estado que indica risco vai para o topo e ganha cor, não fica em coluna cinza.**
  Ignição LIGADA sem comunicar é rastreador arrancado/jammer/perda de energia: 5 casos
  estavam afogados no meio de 15 linhas ordenadas por dias. Passaram a ordenar primeiro,
  com linha vermelha e chip.
- **Categoria "ausência" não pertence a uma distribuição de recência**: a linha "sem
  posição registrada" (1.242) dominava a tabela de faixas; saiu para um banner abaixo.
- Concordância: `${n} ${n===1?'dia':'dias'}` — a tela mostrava "1 dias".

**Régua de saneamento não basta: valide a FAIXA FÍSICA (lição do Combustível):**
- `_CTA_KM_SANO` (0 < distância < 3000) descarta o odômetro resetado (valores como
  −950.223 km) mas **aceita leitura pequena espúria**: um Iveco Stralis aparecia com
  **0,23 km/l** (13.318 litros para 3.065 km). Caminhão faz 0,8–6,0 km/l — fora disso é
  a LEITURA que está furada. Fora da faixa o valor vira `n/d` com o número bruto no
  tooltip, e o KPI conta quantas placas ficaram assim.
- **O número que decide pode não existir na tela.** O prêmio do posto externo
  (R$ 6,27/l comercial × R$ 4,93/l interno = **R$ 1,33/l sobre 732 mil litros =
  R$ 978 mil no trimestre**) não estava em lugar nenhum. Ao criar um KPI desses, dizer
  no ⓘ que é **teto teórico, não meta** — caminhão em viagem precisa abastecer na
  estrada; o uso é acompanhar o mix e o prêmio.
- Categoria em branco vira rótulo explícito ("(não informado no cartão)"), nunca célula
  vazia.

**Campo nunca preenchido e código sem domínio (lições da Manutenção):**
- **"Mão de obra R$ 0" com 747 OSs** lia-se como oficina de graça. O campo tem **0 de
  747** preenchidos: o KPI mostra **"não informado"** e diz a cobertura. Peças idem —
  R$ 31.554 com "informado em 112 de 747 OSs (15%) · 1,9% do valor total". Mesma regra
  do CRM, agora com a cobertura sempre explícita.
- Na tabela, `R$ 0` repetido em 30 linhas vira travessão com tooltip: o custo existe e
  está no Total, o que falta é a separação.
- **Código de domínio não traduzido não vira rótulo inventado.** A coluna Tipo mostrava
  `1`/`2` crus; não existe tabela de domínio na réplica e as observações das OSs não
  separam preventiva de corretiva, então virou "Tipo (cód.)" com tooltip explicando —
  **não** foi criado o KPI preventiva × corretiva, que dependeria de adivinhar.
- **Antes de "corrigir" tabela curta, contar as linhas no DOM:** a de Manutenção parecia
  ter 9 linhas no screenshot e tinha 30 — `.tabroll` já rolava internamente.

**Quando a tela inteira está sobre campo vazio (lição das Multas):**
- **96 multas somando R$ 381** — valor lançado em **3 de 96** (3%), pontos em 2, condutor
  em 10, pagas em 0. Nenhum total daquela tela era o que aparentava. Cada KPI passou a
  dizer a cobertura ("informado em 3 de 96 multas — NÃO é o custo do período").
- **Não inventar estimativa para tapar buraco:** o catálogo `infracaotransito` também
  tem valor zerado justamente nas duas infrações mais frequentes, então **não** foi
  criada estimativa de custo. Dizer que não dá para medir é a resposta certa.
- **Gráfico deve plotar o campo CONFIÁVEL.** "Multas por mês" usava o valor: abr e jul
  apareciam vazios como se não houvesse multa. Passou a plotar a contagem (com o valor
  no tooltip) — e o eixo deixou de ser `unitOf()` de dinheiro, virando contagem inteira.
- **Ligar causa e consequência no alerta:** 86 de 96 multas sem condutor identificado e
  22 autuações por "não indicar condutor" (a 2ª infração mais comum) são o mesmo
  problema; o alerta cita as duas juntas.

**Dois gráficos do mesmo dado e página quilométrica (lições do Painel de Custos):**
- **Rosca de participação + barras por agrupador mostravam exatamente a mesma coisa**,
  lado a lado. A rosca virou **Concentração do custo** — top 3 / 5 / 10 em % acumulado
  (66,5% / 78,7% / 93%) — que responde outra pergunta: onde negociar tem efeito.
- **Top 100 sem rolagem interna fez a página ter 8.602px.** Com `.tabroll` caiu para
  2.697px. Toda lista longa rola dentro do card.
- Data crua com `T` (`2026-07-17T09:38:00`) passa por `fmtDT()`.
- **Filtro em memória sobre linhas cacheadas:** a consulta é pesada, então o cache ficou
  em `_custos_rows(dt_de, dt_ate)` e os filtros de origem e filial são aplicados depois,
  em Python — filtro novo sem multiplicar chave de cache nem repetir a query.
- Rótulo do ERP com espaço duplo (`1 - FIL  MTZ`) é normalizado com `" ".join(x.split())`
  na exibição E no filtro, senão o valor selecionado não casa com o dado.

**Gráfico que não segue o filtro tem de dizer isso (lição de Ordens de Compra):**
- `OC_MENSAL_SQL` é fixo em 12 meses (`current_date - 11 months`) e o hint dizia
  "no período filtrado", com os KPIs em 90 dias logo acima. O hint passou a dizer
  exatamente o que o gráfico obedece: "últimos 12 meses · não segue o filtro de período
  (segue filial, criador e aprovador)". **Ao ver série e KPI discordando, checar qual
  dos dois ignora o filtro antes de suspeitar do dado.**
- **Subconjunto pede proporção:** "Aguardando entrega 227" e "Com entrega atrasada 186"
  lado a lado não diziam que o atraso é **82% da fila**.

**Rótulo que promete ordem e KPIs que não somam (lições de RH — Vagas):**
- O hint dizia "em andamento primeiro" e a lista abria com **21 finalizadas** antes das
  3 em entrevistas. Ordem passou a ser: em andamento → congeladas → resto, e dentro de
  cada grupo **a que espera há mais tempo primeiro**. Quando o rótulo descreve uma
  ordenação, conferir se o `sort` existe.
- **3 + 8 + 21 = 32 num total de 33.** Faltava a vaga cancelada, que não cabia em
  nenhum cartão. O KPI de total passou a dizer "1 em outro status".
- **Métrica que os dados permitem e ninguém calculou:** solicitação e fechamento
  estavam nas colunas, mas não havia time-to-fill. Virou "Tempo até preencher" —
  **mediana** (não média, que uma vaga longa distorce) de 11 dias sobre 21 finalizadas.
- Tempo decorrido revela o que a data sozinha esconde: vaga congelada **há 376 dias**.

**Painel de TV: sem tooltip, cada número tem de se explicar sozinho (lição dos Painéis TV):**
- **Dia futuro não é dia abaixo da meta.** O painel de faturamento desenhava 27 a 31
  com a meta cheia e o realizado zerado em vermelho — de longe parecia colapso do
  faturamento. Dia posterior a hoje agora sai só com a meta esmaecida, sem barra de
  realizado.
- **Verde só quando havia meta a bater.** "Último dia faturado R$ 4 mil" saía VERDE num
  domingo com meta zero. Sem meta no dia o cartão fica neutro e o rótulo diz
  "fim de semana, sem meta".
- **Disponibilidade tem de ser de TRAÇÃO.** "Frota disponível 289" somava 227 carretas
  paradas com os cavalos: dos 307 TRA+LOC ativos só **80 têm motor**. Virou "Tração
  disponível 74 · 5 em viagem · 1 oficina · de 80 com motor".
- Em TV não existe `.ihelp` — a explicação tem de caber no rótulo e no subtítulo.

**Máximo sem filtro de relevância (lição da Saúde do Servidor):**
- "Disco (mais cheio) 92,6%" em vermelho apontava para um volume **temporário do Docker
  de 2,3 GB**; o disco de dados real estava em 88,9%. Volume pequeno enche sozinho e
  sequestra qualquer KPI de máximo — o cartão passou a considerar só volumes ≥ 20 GB,
  nomear o volume escolhido e dizer quantos ficaram de fora.
- **Leitura de hardware implausível é omitida, não exibida:** `psutil.cpu_freq()`
  devolvia "4 MHz" num Apple Silicon. Abaixo de 100 MHz o valor some; acima de 1.000
  vira GHz.
- Esta tela mede a MÁQUINA ONDE A API RODA — fora do servidor, túnel e tarefas
  agendadas aparecem indisponíveis sem que haja falha. O ⓘ diz isso.

**Orçamento (módulo novo, 2026-07-26):**
- **Escrita fica no banco local do CÓRTEX**, porque o AVA é réplica
  somente-leitura. Nasceu em SQLite e migrou para o PostgreSQL em 27/08/2026,
  junto com os outros nove — ver "Onde o dado é ESCRITO", na seção 2.
- **`valor_efetivo = coalesce(valor_ajustado, valor_baseline)`** — regerar o baseline
  nunca apaga ajuste manual. Mesmo princípio do `ajustes_contabeis.json`.
- **Derivação por mês espelho, não média.** Dezembro cai ~40% na Sulista e há queda
  estrutural de 18% a/a: média achata a sazonalidade e ignora a tendência.
- **Corte de recorrência em 75% dos meses da base.** 41 das 355 contas aparecem em 1 ou
  2 meses; espelhar isso é ruído com cara de número. Abaixo do corte → mediana **só nos
  meses cujo espelho teve movimento** + marca "base fraca". NUNCA espalhar a mediana nos
  12 meses: isso anualiza a conta esporádica em ~12x (as 91 contas abaixo do corte
  somavam R$ 43,7 mi de baseline contra R$ 3,9 mi de histórico — pego só na revisão
  final, reconciliando contra a DRE real).
- **Mês do ano orçado que está DENTRO da base é comparação circular.** Orçar 2026 em
  julho põe jan–jun/26 na base: o espelho desses meses é o próprio mês e o desvio mede
  só o fator (-5% vira -5,26% em toda linha de imposto). A versão grava `meses_base`;
  o acompanhamento exclui esses meses do acumulado e o gráfico os esmaece.
- **Desvio orçamentário tem cor invertida em custo.** Custo abaixo do orçado é
  FAVORÁVEL (verde), receita abaixo é desfavorável (vermelho). A flag `favoravel` vem do
  efeito no resultado, nunca do sinal.
- Conta que não chega a nenhuma linha da DRE (`contas_sem_linha` — sem agrupador, ou com
  agrupador que o `DRE_MODELO` não reconhece) fica **fora** do orçamento e volta como
  pendência com link para a Contabilidade — orçar o que não soma em linha nenhuma faria
  o total não fechar.
- **`<input type="number">` DESCARTA a vírgula em vez de recusá-la.** Digitar `1234,56`
  produz `123456` — cem vezes o valor, sem erro nem aviso. Em campo de valor use
  `type="text"` + `inputmode="decimal"` + parse estrito (`numBR()` no `index.html`): valida
  por regex ANTES de converter, porque `parseFloat` aceita prefixo válido e ignora o resto
  (`1.234.56` viraria `1,234`). Ponto em grupos de exatamente 3 dígitos é milhar pt-BR
  (`1.234` = 1234), não decimal.

**Canal que pode ser DESLIGADO PELO FORNECEDOR (lições da Z-API / WhatsApp):**
- **O segredo vai dentro da URL, e isso muda o que pode ser logado.** Gobrax,
  Monkey e Prolog mandam token em cabeçalho — registrar a URL era inofensivo.
  A Z-API é `/instances/{id}/token/{token}/send-text`: a **URL é a credencial**.
  `str(exc)` de `urllib` traz a URL, e a mensagem de erro do envio vai para a
  tela, para o log E para a trilha no banco. Nada em `api/whatsapp/cliente.py`
  devolve exceção crua; tudo passa por `_sanitizar()`, com teste que reproduz o
  `URLError` com a URL dentro. **O id da instância também é segredo** — é metade
  da chave, apesar de "id" sugerir o contrário.
- **Aceitar não é entregar.** Com o celular pareado fora do ar, a Z-API responde
  **200 e enfileira até 1.000 mensagens**, disparando tudo quando o aparelho
  volta. Reportar "enviado" ali é mentira duas vezes: não foi, e vai chegar em
  lote no sábado à noite. O envio consulta o estado da conexão antes e recusa.
- **O limite de envio é a funcionalidade, não a configuração.** A documentação
  do próprio fornecedor diz que o gatilho nº 1 de banimento é a quantidade de
  **destinatários DISTINTOS** numa janela curta (relato de bloqueio a partir de
  10 números novos), e que **tópico financeiro — "boleto", "PIX", "cartão" —
  eleva o risco**. Ou seja: a régua de cobrança, que é o uso natural aqui, é
  justamente o padrão mais perigoso. Daí `ativo` nascer **desligado**, o teto
  diário nascer em 60 e a janela em 08:00–20:00. Perder o número não é "a
  integração caiu": é o WhatsApp comercial fora do ar, com as conversas dentro.
- **Continuar conversa aberta não gasta cota.** O freio conta destinatário
  NOVO do dia; responder quem já falou hoje é o caso de menor risco que existe,
  e bloqueá-lo faria a proteção atrapalhar só o uso legítimo.
- **Normalizar telefone é controle de acesso, não formatação.** O contador de
  destinatários distintos lê a trilha: se `(47) 99999-8888` e `5547999998888`
  virassem duas linhas, ele mediria formato de digitação, não pessoas. A trilha
  guarda **sempre o normalizado**; a tela reformata na exibição. O `separar()`
  deduplica pelo NÚMERO normalizado — deduplicar por dígitos crus deixava a
  mesma cliente receber duas vezes, e foi um teste que pegou.
- **Não "consertar" o nono dígito.** A tentação é acrescentar/remover o 9 de
  celular antigo. Quem resolve essa equivalência é o WhatsApp, e a Z-API
  documenta que valida a existência do número a cada envio — pedindo
  explicitamente que NÃO se cheque antes. Inventar o dígito manda para outro
  assinante.
- **`error` NEM SEMPRE É ERRO — leia o campo que o fornecedor usa como
  VERDADE.** O `GET /status` da Z-API responde, com a instância no ar,
  `{"connected": true, "error": "You are already connected."}`: o campo é
  DESCRITIVO (explica por que não há QR Code a ler). A regra "200 com `error`
  no corpo é falha" — certa para o `/send-text` — fazia o CÓRTEX ler
  CONECTADO como desconectado, e como a sétima recusa do envio consulta esse
  estado, **todo envio ficava barrado exatamente quando o WhatsApp estava
  funcionando**. Quem decide é `connected`; `error` só vale como motivo quando
  ele é falso. A regra genérica vale por endpoint, nunca por integração
  inteira.
- **Dublê de teste otimista demais testa um fornecedor que não existe.** O
  `http_falso` do WhatsApp devolvia `{"connected": true, "smartphoneConnected":
  true}` e OMITIA o `error` que a Z-API sempre manda — por isso a suíte inteira
  passava com a produção quebrada. Ao dublar resposta de fornecedor, copie o
  corpo REAL, campos "inúteis" inclusive: é neles que mora a surpresa.
- **Mensagem do fornecedor que vai para a tela precisa dizer o conserto.** "You
  are not connected." não diz nada a quem opera; virou "A instância não está
  pareada a um WhatsApp. Leia o QR Code no painel da Z-API." Traduzir só o que
  se conhece (`_STATUS_PT`) — inventar texto para mensagem nova esconderia
  justamente o caso que ninguém viu ainda.
- **Diagnóstico de integração cujo estado só existe na API do fornecedor precisa
  de cache.** A Saúde recarrega a cada 5 s; sem o TTL de 60 s em
  `cliente.estado()` seriam ~17 mil chamadas por dia à Z-API para desenhar um
  cartão. Gobrax e Monkey escapam disso porque medem posição gravada em disco.
- **Não existe "modo teste" mais frouxo.** No e-mail o teste vai para o próprio
  usuário logado e não aceita destinatário. Aqui não há telefone na sessão, então
  o teste precisa de um número — e por isso ele é o **mesmo** envio, com a mesma
  trilha, o mesmo limite e a mesma auditoria. Um caminho paralelo viraria o
  atalho para disparar sem as regras.

**Modelo de mensagem: o contexto é o que impede o texto de sair furado (lições dos modelos de WhatsApp):**
- **O CONTEXTO não é categoria de organização — é o conjunto de variáveis permitidas,
  validado NA GRAVAÇÃO.** Um modelo de cobrança conhece `{{titulo}}` e `{{vencimento}}`;
  a torre de controle não teria com que preencher isso. Sem a amarra, o mesmo texto
  disparado da tela errada chega ao cliente com buraco, e quem descobre é o cliente. A
  gravação é o único momento em que alguém está olhando.
- **Variável sem valor NÃO vira string vazia.** `renderizar()` estrito levanta; a
  alternativa silenciosa manda "Prezado , seu título vence em ." e o sistema reporta
  sucesso. A rede é DUPLA: `enviar_modelo` renderiza estrito, e `enviar` recusa qualquer
  texto que ainda tenha `{{...}}` — mesmo vindo de área que não usou modelo. Parece
  redundante e não é: quem monta mensagem é código de área, e a chamada errada de uma
  delas não pode virar mensagem no celular do cliente.
- **NUNCA `str.format()` nem f-string sobre texto que um usuário escreveu.**
  `"{0.__class__.__mro__}".format(x)` alcança atributo de objeto — aplicar `format` a
  template editável é dar ao autor um pedaço do interpretador. A substituição é por
  regex que só reconhece `{{nome_simples}}`; `{0}` e `{conta.saldo}` continuam texto.
- **A CHAVE (slug) existe além do id porque quem chama o modelo é outra área.** Pelo
  `id`, restaurar backup noutra ordem troca a mensagem; pelo NOME, renomear
  "Cobrança — 1º aviso" quebra a rotina em silêncio. Renomear não muda a chave; trocar a
  chave é mudança de contrato, e a tela diz isso.
- **Com modelo escolhido, a caixa de mensagem é PRÉVIA e não campo, e o POST manda a
  CHAVE e os VALORES — nunca o texto.** Quem monta a mensagem final é o servidor, a
  partir do modelo gravado. Aceitar texto pronto junto com a chave deixaria gravar "veio
  do modelo de cobrança" numa trilha em que o texto é outro qualquer, e a coluna `modelo`
  deixaria de ser prova. Para escrever livre existe "Sem modelo".
- **A prévia é do SERVIDOR, inclusive a do formulário de envio.** Reescrever a
  substituição em JavaScript é trivial — e cria duas regras que podem discordar, com a
  descoberta acontecendo depois de a mensagem chegar ao cliente.
- **Contexto sem tela que o dispare é DITO na tela** ("sem tela ainda"), não escondido:
  o catálogo é o contrato para quem for ligar a área, e um modelo pronto esperando
  consumidor não pode parecer em operação.
- **O teto do corpo é menor que o do WhatsApp (3.000 × 4.096)** porque o texto cresce
  duas vezes depois: `{{cliente}}` tem 13 caracteres e "TUPY FUNDIÇÕES DO BRASIL LTDA"
  tem 29, e a assinatura entra no envio. Validar só o corpo deixa passar o modelo que
  estoura depois de preenchido — o tamanho FINAL é conferido em `renderizar()`.
- Recusa por chamada errada de código (modelo inexistente, desligado, variável faltando)
  **não entra em `zap_envios`**: nada foi tentado contra número nenhum, e a trilha existe
  para responder "o que saiu para fora da empresa". Já a recusa da oitava regra entra —
  ali houve tentativa contra um número real.
- **GOTCHA de teste e2e:** `tr:nth-child(1)` sem `tbody` casa a linha do CABEÇALHO, e
  `inner_text` devolve o texto já em CAIXA ALTA quando o CSS tem `text-transform`.

**Campo opcional, foto e quem edita o quê (lições do cadastro de usuário):**
- **Campo AUSENTE e campo VAZIO são coisas diferentes no payload de edição.** A tela de
  Minha Conta manda dois campos; um `payload.get(campo, "")` comum leria os outros como
  string vazia e APAGARIA o cargo que o administrador preencheu — sem erro, sem aviso.
  Daí o sentinela `_AUSENTE` em `api/auth.py`: chave ausente = não mexe; chave vazia =
  limpa. Vale para toda edição parcial.
- **O que a própria pessoa edita é decisão, não conveniência de formulário.** Nome e
  e-mail assinam a trilha de auditoria (quem reescreve o próprio nome reescreve a
  assinatura do que já fez) e cargo/setor são estrutura da empresa, lida como informação
  conferida. `POST /api/auth/perfil` aceita SÓ telefone, ramal e foto — e a tela não
  oferece o resto, porque convidar a preencher o que vai ser ignorado é pior que não ter
  o campo.
- **Telefone é guardado NORMALIZADO, com o validador do WhatsApp** (`api/whatsapp/
  numeros.py`). Duas noções de "telefone válido" na casa dariam número que o cadastro
  aceita e o envio recusa — descoberto na hora em que a mensagem não chega. A tela
  reformata na exibição (`telefone_fmt` vem pronto do servidor).
- **A foto não mora na tabela do usuário.** `sessao_atual()` faz `SELECT u.*` a CADA
  requisição autenticada: uma coluna `bytea` ali poria os bytes da imagem em toda chamada
  de API, dezenas por tela, para desenhar um avatar de 34px que o navegador já tem em
  cache. Tabela `usuario_fotos` ao lado, com `ON DELETE CASCADE` (sem ele, excluir
  usuário passa a falhar por chave estrangeira — e só aparece no dia da exclusão).
- **A imagem é reduzida no CLIENTE e validada no SERVIDOR — as duas coisas.** O canvas
  faz o recorte quadrado central e o JPEG 256px (foto de celular de 6 MB não trafega
  inteira); `api/fotos.py` decide o que entra, porque a rota aceita o que mandarem nela.
  Três conferências: tipo pelos BYTES (mime do `data:` URL é escrito pelo remetente, e
  **SVG não entra — é XML com script**), teto de bytes, e **teto de DIMENSÃO**: um PNG de
  180 KB pode declarar 25000x25000 e estourar o navegador de quem abrir a lista. Ler
  largura/altura do cabeçalho de PNG/JPEG/WEBP custa 60 linhas; a alternativa era o
  Pillow, uma dependência C de produção inteira para conferir dois inteiros.
- **Fundo branco no canvas ANTES do `drawImage`**: PNG com transparência vira PRETO ao
  virar JPEG, e o recorte redondo mostraria um halo escuro em volta do rosto.
- **`?v=<carimbo>` na URL da foto**: troca de foto aparece na hora sem proibir o cache
  das outras. O ETag do servidor é a segunda linha, não a única.
- Avatar sem foto são as INICIAIS, não um ícone de imagem quebrada: a foto é opcional e
  "sem foto" é estado normal. Mesma regra da linha de cargo/telefone no menu, que some
  quando não há dado em vez de aparecer vazia.
- **GOTCHA de teste:** `let` de topo no `index.html` NÃO vira propriedade de `window` —
  `pg.wait_for_function("window.FOTOED && …")` espera para sempre. E `#avCargo` vive
  dentro do menu `display:none`: `is_visible` só responde depois do clique no avatar.

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

**Feedback de carregamento (lição do indicador de carga):**
- **Esmaecer não é feedback.** `.content.loading{opacity:.55}` era a única resposta
  a um clique: numa consulta de 40 s ao AVA ninguém distingue "consultando" de
  "morreu". A barra animada sobre a borda da topbar resolve sem deslocar layout
  (absoluta), e o contador aparece aos 3 s ("consultando o banco… 12s").
- **O contador de cargas vive no wrapper de `fetch`, nunca nos loaders.** Os
  loaders soltam o `content.loading` dentro de `if(seq===...)`: correto para flag
  idempotente, fatal para contador — toda resposta obsoleta (trocar filtro duas
  vezes rápido) vazaria e a barra giraria para sempre. O `finally` da Promise roda
  sempre, inclusive em erro de rede.
- **Já existe um wrapper de `window.fetch`** (401 → login). Estender esse, nunca
  criar um segundo: `_fetch0` é usado de propósito no boot/login para escapar do
  tratamento de 401, e um wrapper novo o sequestraria.
- **150 ms antes de aparecer.** Sem esse atraso, resposta de cache faz a tela
  piscar — pior que não ter indicador.
- **Recarga automática não acende a barra.** Saúde (5 s) e Torre (120 s) marcam
  `X-Carga-Fundo` **no timer, não na URL**: assim o clique manual nas mesmas telas
  continua acusando. Painel de TV é escondido por CSS.
- **GOTCHA do `prefers-reduced-motion`:** o bloco global do arquivo zera
  `animation-iteration-count` com `!important` em `*`. Uma animação infinita nova
  para no fim do keyframe — a barra ficaria em `left:100%`, fora da tela, e
  INVISÍVEL justo para quem pediu menos movimento. Regra própria com
  especificidade maior é obrigatória.

**Testar a UI com Playwright (já está no `.venv`, não precisa instalar):**
Um `http.server` serve `api/` e `page.route('**/api/**')` responde com atraso
controlado — testa a tela sem banco, sem túnel, sem AVA. Três armadilhas custaram
uma rodada cada:
- **`wait_for_selector` espera VISIBILIDADE.** `"#loadbar[hidden]"` é condição
  impossível (tem `display:none`); usar `state="hidden"`.
- **`evaluate("fetch(...)")` AGUARDA a Promise.** Os 800 ms passavam dentro do
  `evaluate` e a barra já tinha apagado quando o teste ia olhar. Usar `void fetch(...)`.
- **`setAttribute` dispara MutationObserver mesmo com valor igual**, então o log de
  visibilidade ganha um `False` por carga. A asserção correta é "nunca ficou
  visível", não "log vazio".
- **Estabilizar exige QUIETUDE de rede**, não um instante de `ativas()==0`: o boot
  tem fases (auth/me → entrar → router → tela) e o contador toca zero entre elas.
- No Playwright a rota registrada **por último** é avaliada primeiro — o catch-all
  vai antes do mock específico.

**Documentação que se extrai do painel (tela `#doc`):**
- **A procedência já está no HTML.** Os tooltips `.ihelp` de cada card dizem a
  tabela e a regra de origem; `api/documentacao.py` extrai isso do `index.html`.
  Documentação escrita à parte envelhece; essa acompanha a tela.
- **`view-fluxo` é `class="view on"`** (é a tela que abre). Regex presa a
  `class="view"` exato perdia o Fluxo de Caixa E colava os cards dele na Visão
  Geral — que aparecia com 7 cards em vez de 5. Sempre `class="view[^"]*"`.
- **`view-rent` existe no HTML e não está em `VIEWS`**: tela dormente, que o router
  não abre e o menu não mostra. Fica fora da documentação.
- Um teste falha se alguma view de `VIEWS` ficar sem grupo em `docs/manual.yaml` —
  é o que impede a documentação de esquecer tela nova.

**Botão de report → issue no GitHub (`api/reports/`, botão `#btnReport`):**
- **O repo do código é PÚBLICO.** Print do CÓRTEX carrega faturamento, cliente, placa e
  PII, então issue e anexo vão para `REPORT_REPO` — repositório **separado e privado**.
  Antes de mandar qualquer conteúdo de painel para fora, conferir a visibilidade do
  destino (`gh repo view <repo> --json visibility`).
- **`AuthMiddleware` é fail-closed:** rota `/api/*` fora de `ROTA_TELAS` devolve 403 para
  não-admin. Rota que vale para todo usuário logado entra em `auth._ROTAS_SEM_TELA`
  (é o caso de report e push) — senão o botão aparece para todos e funciona só para o
  administrador, e ninguém percebe.
- **Anexo em repo privado não renderiza inline.** O proxy de imagem do GitHub não
  autentica: `![](url)` vira quadrado quebrado. A issue traz **link clicável**.
- **Anexo sobe ANTES da issue.** Na ordem inversa, falha no meio produz issue sem anexo —
  o defeito que o usuário enxerga. Blob órfão no repo de reports não incomoda ninguém.
- **`getDisplayMedia` exige contexto seguro** (localhost ou HTTPS). Em HTTP puro por IP a
  API nem existe: o modal detecta e manda usar Print Screen + Ctrl+V.
- **O modal sai na própria foto** se não for escondido antes da captura — e as tracks
  precisam de `stop()` no `finally`, senão o navegador fica com o indicador de
  compartilhamento aceso.
- **Falha de envio não pode limpar o formulário**: refazer o print custa dois cliques e
  um diálogo do navegador. Erro fica na linha `.m-err` com tudo preenchido.
- `uv run python scripts/verificar_report.py` diz por que o botão não aparece
  (chave ausente, repo errado, token sem permissão) sem imprimir o token.
- O buffer `REPERR` (10 últimos erros) é declarado com `var` + `function` no topo do
  script, hoisted de propósito: um erro durante a avaliação do arquivo encontraria um
  `const` em TDZ e viraria dois erros.

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
- **Lista de telas escrita à mão no prompt envelhece calada.** O prompt do sistema
  enumerava as telas do painel num texto fixo; cinco telas novas depois, o Copiloto
  dizia "não existe" sobre a ANTT e a Telemetria. A lista passou a ser montada de
  `api.auth.TELAS` — tela nova entra sozinha, e um teste garante que o prompt cita
  todas.
- **Snapshot sequencial com o banco fora trava o chat.** As 17 fontes esperavam cada
  uma o próprio timeout de conexão: **240 s medidos** antes da primeira palavra.
  Fail-fast na primeira falha de CONEXÃO (`_e_falha_de_banco`) — mas só nela: erro de
  uma query específica não pode fazer o snapshot desistir das outras 16 fontes.
- **Fonte nova no snapshot não pode disparar coleta.** A premiação tem um `force` que
  vai buscar na Gobrax; no snapshot ela é lida SEM `force`, senão abrir o chat viraria
  chamada de API externa a cada 10 minutos. Há teste para isso.
- **Cadeia de modelos `:free` apodrece sozinha** — modelo gratuito é desativado sem
  aviso. Dos preferidos fixos, só 2 de 5 ainda existiam no catálogo. O desempate do
  resto lê o porte do próprio id (`-550b-` → 550B), e um teste de manutenção compara
  os preferidos contra o catálogo real (faz skip sem chave/rede).

Regra: todo painel tem **fonte do dado + timestamp**; nenhum gráfico sem rótulo direto;
todo número-chave traz **comparação** (vs meta, vs período anterior).

---

## 5.1 Versão e documentação — OBRIGATÓRIO EM TODA ENTREGA

Nenhuma mudança fecha sem estes quatro passos. Não é etapa opcional do fim: entra
nos mesmos commits do código.

1. **Bumpar `pyproject.toml`** (SemVer). É a fonte ÚNICA do número. O projeto ficou
   em `0.1.0` do commit inicial até 08/08/2026; essa passa a ser a versão do estado
   em produção de então, e o versionamento vale de verdade a partir de `0.2.0`.
2. **Acrescentar o bloco em `docs/versoes.yaml`** — a versão do TOPO é sempre a
   corrente e tem de bater com o `pyproject.toml`. Campos `adicionado`, `alterado`,
   `corrigido`; escreva o que a pessoa que usa o painel percebe, não o refactor.
3. **Rodar `uv run python scripts/gerar_changelog.py`** para regerar o
   `CHANGELOG.md`. O arquivo é gerado — não editar à mão.
   `test_changelog_esta_em_dia_com_o_yaml` falha se divergirem.
4. **Conferir a tela `#doc`**: telas e cards saem do `index.html` sozinhos, mas
   grupo novo, tela nova ou termo novo de glossário entram em `docs/manual.yaml`.

**Rodar a suíte** (as ferramentas de teste ficam no grupo `test`, que o `uv sync`
puro NÃO instala — de propósito, para o AutoDeploy não carregar pytest e
playwright em produção):

```bash
uv sync --group test
uv run playwright install chromium   # só na primeira vez, e a cada bump do playwright
uv run pytest -q                     # 1.788
node --test "tests/frontend/*.test.js"  # 8 (núcleo do indicador de carga)
uv run python scripts/verificar_estrutura.py
```

Atenção: `uv sync` sem `--group test` **desinstala** pytest e playwright. É o
comportamento correto para produção; local, use sempre o `--group test`.

**Rótulo do sistema:** `CX-DD/MM/AAAA-vX.Y.Z` (ex.: `CX-08/08/2026-v0.2.0`), com a
data DA VERSÃO, não a de hoje. Aparece no rodapé da sidebar, no cabeçalho da tela
de Documentação e em `GET /api/versao` — é como se confirma, olhando o painel, o
que o AutoDeploy do Windows colocou no ar.

Quando MENOR/CORREÇÃO: recurso novo retrocompatível sobe o MENOR (0.2 → 0.3);
correção sem recurso sobe a CORREÇÃO (0.2.0 → 0.2.1).

**O MAIOR não tem regra automática, e é de propósito.** SemVer usa o MAIOR para
avisar o código de OUTRAS PESSOAS que algo quebrou — e aqui não há outras
pessoas: não existe API pública nem SDK, e o frontend sobe junto com o backend
no mesmo deploy. O gatilho nunca dispararia sozinho: são 157 versões em 19 dias
(0.1.0 em 08/08/2026 → 0.113 em 27/08), 113 de MENOR e 44 de correção, nenhuma
de MAIOR — nem quando os dez bancos locais migraram para o PostgreSQL, que é a
maior mudança de contrato de dado que o projeto já teve.

Então o **`1.0.0` é DECLARADO, não derivado**: quando o painel puder ser tratado
como fonte oficial. Três coisas, e as três são verificáveis:

1. **Restauração de backup testada de verdade** — não basta o dump existir e
   passar no `pg_restore -l`, que só prova que o arquivo está íntegro. É
   restaurar num banco vazio e conferir que o sistema sobe em cima dele.
2. **Reconciliação com o ERP documentada** — a divergência de cada número que
   decide dinheiro conhecida, explicada e com dono, em vez de descoberta na
   reunião.
3. **As três telas de receita batendo entre si** — faturas emitidas × frete das
   viagens × CT-e+KMM+NFS-e da meta, com o ⓘ de cada uma dizendo por que
   diferem quando diferem.

Até lá o `0.x` diz a verdade: está no ar e em uso, e ainda muda de forma toda
semana. Deixar o `1.` chegar por acidente — no dia em que alguém quebrar um
contrato — seria pior que não chegar.

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
