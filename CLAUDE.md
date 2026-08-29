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
| `jornada` | Jornada do motorista (Lei 13.103/2015). UMA tela, lendo a apuração da **RasterJOR** coletada pelo próprio CÓRTEX. A apuração do ERP continua no banco e continua alimentando a FOLHA — o que saiu do painel foi a leitura dela | `jor_jornadas`, `jor_inconformidades`, `jor_motoristas`, `jor_ausencias`, `jor_carga` (banco local) |
| `suprimentos` | Agregados, fornecedores, contratos, make-vs-buy | `sup_agregados`, `sup_fornecedores`, `sup_contratos` |
| `telemetria` | Dados da plataforma Gobrax por API com token: premiação por nota × km, consumo × abastecimento, condução e hodômetro/rastro | `api/gobrax/`, `data/premiacao/` |
| `antt` | Piso mínimo de frete da compra e situação do RNTRC dos transportadores contratados | `config/antt_coeficientes.yaml`, `config/antt_eixos.yaml`, `programacaoembarque` (AVA) |
| `gestao` | Atas de reunião e planos de ação (5W2H) com responsável, prazo e acompanhamento. Metas/OKR ainda não implementados | `ges_reunioes`, `ges_participantes`, `ges_acoes`, `ges_andamentos` (banco local) |
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

**Gráfico: ECharts nas telas convertidas, SVG à mão no resto.**
Restam **39 gráficos SVG escritos à mão** no `index.html`, e eles continuam
assim porque carregam as regras que esta seção documenta (mês parcial
hachurado, rótulo direto, semáforo discreto, anti-colisão, teclado) e
reescrevê-los em bloco seria semanas para perder cada uma. A conversão é feita
por TELA, quando há motivo, e cada regra é reimplementada e testada na chegada.

**ECharts 5 (Apache 2.0) entrou em 27/08/2026**, vendorizado em
`api/static/vendor/echarts.min.js` com a licença ao lado. Nasceu como escolha
para o que o SVG à mão não faz — **zoom/pan em série longa, drill-down,
exportação, gantt, mapa** — e hoje também é o padrão das telas já convertidas:
Produtividade de Veículos, Jornada (4 gráficos) e **Visão Geral (3)**.

Três regras para usá-lo, todas com teste em `tests/frontend/test_echarts_e2e.py`:

1. **Carga SOB DEMANDA** (`carregarECharts()`), e ela memoiza: são 990 KB, uma
   vez por sessão, e **uma carga serve todos os gráficos da tela**. Quem não
   desenha continua sem pagar — é isso que o teste vigia hoje.
   **A Visão Geral BAIXA a biblioteca desde 29/08/2026**, e a regra anterior
   dizia o contrário. Duas lições ficaram: a tela de entrada é onde esse custo
   pesa mais (é a primeira de todo mundo, embora o navegador cacheie depois do
   primeiro deploy); e o teste que a protegia **passou por vacuidade** depois
   da conversão, porque o dublê devolvia payload vazio e os gráficos saíam
   antes de chegar ao carregador. Teste de "não faz X" precisa provar que
   chegaria a fazer X.
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
entrega menos que os gráficos da casa já fazem. uPlot (MIT, 49 KB) fica como opção
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
**RECUSA NÃO É 5xx — o proxy engole a mensagem (lição que custou uma manhã):**
- "O envio está DESLIGADO", "o limite do dia acabou", "a Gobrax não respondeu": em
  todos, o CÓRTEX funcionou e está dizendo NÃO, com um motivo que a pessoa precisa
  LER. Isso é **4xx** (`HTTP_RECUSA = 409` em `api/main.py`). 502 significa "meu
  gateway está ruim", que é outra coisa.
- **Não é preciosismo de vocabulário: o Cloudflare TROCA o corpo das respostas 5xx
  da origem pela página de erro dele.** Medido nesta bancada — `curl` num 401
  atravessa o túnel intacto (mesmo `content-type: application/json`, mesmo
  `content-length`); o 502 chegava à tela sem JSON nenhum. O usuário via "erro
  interno da API" por horas enquanto o backend respondia, corretamente, "o envio
  está DESLIGADO em Gestão › WhatsApp" — e a trilha registrava a recusa. A
  mensagem existia e nunca cruzou o túnel.
- **O diagnóstico enganava porque tudo parecia certo:** API de pé, rota testada,
  trilha gravando. O que faltava olhar era o CÓDIGO DE STATUS, não o código.
- Regra: 5xx só para falha NOSSA de verdade (exceção não tratada). Tudo que o
  usuário precisa ler usa 4xx.
- **Na tela, use `respostaJSON(r)`** — o padrão da casa, que lê como TEXTO antes e
  distingue "sessão expirou / página de login", "o proxy respondeu no lugar da
  API" e "erro interno". Um `try{await r.json()}catch{}` improvisado dá a mesma
  frase para os três, que têm consertos diferentes. Já existia
  `tests/frontend/test_resposta_json.py` cobrando isso, e o card do WhatsApp não
  seguia.

**Rota `async def` com I/O bloqueante para o SERVIDOR INTEIRO (lição do 502 no envio):**
- O FastAPI roda rota `def` num threadpool e rota `async def` **no próprio event
  loop**. Toda rota que recebe corpo nasce `async def` (precisa de `await
  req.json()`) — e aí um `urllib`, `psycopg` ou `smtplib` dentro dela trava o loop,
  isto é, o CÓRTEX inteiro, pelo tempo da chamada. Ninguém é atendido: nem outra
  tela, nem a recarga da Torre, nem o `/api/health`.
- **Medido, não suposto:** com a Z-API demorando 3 s, o `/api/health` levou **5,7 s**.
  Em produção o envio chega a 30 s por destinatário (10 s de `/status` + 20 s de
  `/send-text`) e `enviar_varios` repete isso EM SÉRIE — um disparo para cinco
  clientes deixava o painel fora do ar por minutos.
- **O sintoma não parece o que é:** o Cloudflare Tunnel, sem resposta da origem,
  devolve **502 Bad Gateway em HTML**. A tela não consegue lê-lo como JSON e acusa
  "erro interno da API". Quem investiga vai procurar defeito na rota — que está
  correta. Ao ver 502/504 sem JSON com a API de pé, suspeite do event loop antes
  do código da rota.
- A regra: em rota `async def`, **tudo que faz I/O passa por `sem_travar()`**
  (`api/main.py`). Já aplicado no envio de WhatsApp e de e-mail, na coleta da
  Gobrax ("leva mais de dois minutos"), no download da ANTT (~158 MB), no
  cancelamento na SEFAZ e no teste da agenda de relatórios.
- **O `TestClient` NÃO pega isso** — ele serializa as chamadas e um loop travado
  passa despercebido. `tests/test_rotas_nao_travam.py` sobe o uvicorn de verdade e
  mede o `/api/health` durante um envio lento; sem o conserto ele acusa 3,8 s.

- **Recarregar a tela depois de agir NÃO pode ficar no `try` da ação.** O
  `await whatsCarregar()` estava dentro do bloco do envio: uma falha ao
  repintar a trilha sobrescrevia "enviada para 1 número" por "não foi possível
  falar com a API" — com a mensagem JÁ ENVIADA. Quem lê isso reenvia, e o
  cliente recebe duas vezes. Confirmação de ação irreversível não pode depender
  do sucesso do que vem depois dela.
- **`await r.json()` solto transforma erro do SERVIDOR em erro de REDE.** 500
  volta em texto puro; o `json()` estoura e cai no mesmo `catch` do `fetch`,
  fazendo a tela acusar rede para um servidor que respondeu — e mandando
  procurar no lugar errado. Ler o JSON num `try` próprio e mostrar o status
  HTTP separa os dois. Do lado do servidor, a rota que age para fora ganha
  `try/except` geral: toda saída é JSON, com o TIPO da exceção (nunca
  `str(exc)`, que na Z-API carrega a URL, e a URL é a credencial).
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

**Grupo, playground e o que só se descobre OLHANDO a API (lições da Z-API):**
- **O formato documentado não era o formato real.** O id de grupo desta conta é
  `120363421141267015-group` — não `@g.us` nem `<criador>-<timestamp>`. Reconhecer
  só os documentados fazia o grupo real cair na porta do TELEFONE e sair recusado
  com "DDD 12 não existe", mandando conferir DDD onde não há DDD nenhum.
- **E o sufixo é OBRIGATÓRIO.** Guardar só os dígitos, que é o mais limpo, devolve
  `HTTP 400: Phone is wrong`. O canônico é o que a API aceita, não o que é bonito.
  Os dois fatos saíram de um `GET /group-metadata` de leitura, sem enviar nada —
  **quando a dúvida for sobre formato, teste com um endpoint que não escreve.**
- **Grupo conta como UM destinatário no freio**, porque para o WhatsApp é uma
  conversa só. Mandar para um grupo de 40 pessoas não é o mesmo risco que mandar
  para 40 números novos — é o oposto. Mas `normalizar()` continua sendo só
  telefone: quem aceita os dois é `destino()`, que devolve o TIPO junto, porque
  quase toda decisão a jusante depende de saber qual é qual (formatar na tela,
  contar no freio, gravar na trilha).
- **Grupo é testado ANTES de telefone**: um id de 18 dígitos passaria pela porta
  do telefone como "número com dígitos demais" e sairia com a mensagem errada.
- **Playground de API de fornecedor: sem URL livre, nunca.** Um campo "digite o
  caminho" daria acesso a `/send-text` sem limite diário, sem janela e sem
  trilha — o jeito de perder o número embrulhado como ferramenta de diagnóstico.
  A tela manda um ID do catálogo e os parâmetros; o SERVIDOR monta o caminho. Os
  endpoints de envio ficam listados e BLOQUEADOS, apontando para o formulário
  certo; os que mudam estado (reiniciar, desconectar, limpar fila) pedem
  confirmação com o texto do que vai acontecer e entram na auditoria ANTES de
  acontecer.
- **Parâmetro que entra em segmento de URL é validado**: `../send-text` alcançaria
  endpoint fora do catálogo, inclusive o de envio.
- **`_chamar` precisava saber que resposta pode ser LISTA no topo.** O `/groups`
  responde um array; enfiá-lo num dict vazio transformava a resposta certa em
  "nenhum grupo", sem erro nenhum aparecer.

**Mensagem que carrega número do painel (lições do resumo de faturamento):**
- **O CÓRTEX tem TRÊS recortes de receita na mesma resposta** da Visão Geral, e eles
  não são o mesmo número: `faturamento_mes` (faturas emitidas, R$ 11,28 mi),
  `realizado_acumulado` (a régua da META, R$ 10,73 mi) e `receita_mes_cte`. Misturar
  o numerador de uma régua com o denominador de outra dá 96% de atingimento onde o
  real é 91,3% — e a mensagem sai para a diretoria dizendo que a meta está quase
  batida quando falta um milhão. O par que fecha é `realizado_acumulado /
  meta_acumulada`, e o `atingimento_mes` é lido PRONTO em vez de recalculado.
- **O dia do resumo é o último COM MOVIMENTO, não o último da série** — os
  posteriores ainda não aconteceram, e um deles é o dia corrente pela manhã, que
  sairia como "faturamos R$ 0".
- **Dia em curso é DITO por escrito.** Às 11h o dia tinha 20% da meta: certo e
  desastroso. No painel isso é a hachura de "parcial"; num WhatsApp não há hachura,
  então a marca vai no próprio atingimento, que é onde a pessoa está olhando.
- **Preencher número à mão é onde o erro passa.** Nove valores copiados todo dia,
  um dígito a menos no acumulado, e a mensagem anuncia um décimo do faturamento. O
  contexto declara um `provedor` e a tela ganha "Preencher com os números de hoje";
  o botão diz QUANTOS campos preencheu, porque variável que o provedor não conhece
  fica em branco e ninguém repara.
- **Um teste amarra o catálogo ao provedor**: as variáveis declaradas têm de ser
  exatamente as entregues. Uma faltando só apareceria na hora de mandar, como
  "variável sem preencher".
- **Modelo que vai para poucos leva sub-limite baixo.** O resumo de faturamento vai
  para um punhado de pessoas da casa; o teto de 10 não atrapalha o uso real e
  transforma um disparo acidental em massa numa recusa, em vez de numa lista de
  clientes recebendo o faturamento da empresa.

**Regra por modelo: o que pode variar e o que é teto (lições das regras de envio):**
- **Sub-limite de modelo NUNCA CRIA COTA.** O teto de destinatários é do NÚMERO e
  vale para tudo somado; o do modelo só APERTA (`min` dos dois, e as duas
  contagens são feitas no envio). O WhatsApp não sabe o que é um modelo — vê uma
  linha telefônica falando com N desconhecidos por dia. Dez modelos com 60 cada
  não são 600 disparos permitidos: são 600 motivos para perder a conta.
- **`None` significa HERDA, nunca zero.** Sem isso, cada modelo carregaria uma
  cópia congelada da configuração do dia em que nasceu, e mudar a regra geral
  deixaria de valer para quem já existe. Vale para todo campo de regra opcional.
- **Assinatura tem TRÊS estados** — `None` herda, texto substitui, string VAZIA
  manda sem assinatura (aviso interno para motorista não leva assinatura
  comercial). A tela precisa distinguir os três no payload: mandar `''` para "não
  mexi" apagaria a assinatura sem ninguém pedir. Daí o checkbox separado do campo.
- **Janela do modelo PODE ampliar a geral**, e essa é a única regra que afrouxa:
  alerta de ocorrência às 3h é legítimo para um motorista e é reclamação certa
  para um cliente. Quem edita decide, e a tela AVISA ao ampliar — porque no
  formulário os dois campos perigosos (limite acima do teto, janela maior)
  parecem inofensivos enquanto se digita.
- **A recusa diz QUAL limite barrou.** "Limite atingido" sem qualificar, quando
  foi o sub-limite do modelo, manda esperar à toa — o número ainda tem cota.
- **Janela pela metade é recusada:** informar só uma ponta deixaria metade
  herdada e metade própria, e ninguém consegue prever isso lendo a tela.
- **Número preferido do modelo é SUGESTÃO**, sobreponível por quem envia — uma
  preferência que não desse para sobrepor viraria uma trava escondida.
- **Lista de colunas do SELECT num lugar só** (`_COLUNAS`): estava repetida em
  `listar()` e `obter()`, e acrescentar campo em uma e esquecer da outra faria o
  ENVIO (que usa `obter`) trabalhar com regra pela metade.

**Dois números de WhatsApp: o que se duplica e o que NÃO se duplica:**
- **O freio é POR NÚMERO.** O limite conta destinatários distintos porque é esse o
  gatilho de banimento que a Z-API documenta — e a reputação é de cada linha
  telefônica. Contador compartilhado erra nas duas direções: 60 envios pelo
  principal bloqueariam o reserva, que não fez nada; e ignorar a separação
  deixaria passar o dobro do limite achando que é um número só. Daí a coluna
  `instancia` em `zap_envios` e o índice `(instancia, telefone, ts)`, que é a
  consulta feita A CADA mensagem.
- **"Já falou hoje" é do PAR (aparelho, cliente).** O cliente ter conversado com o
  número principal não abre conversa nenhuma no reserva — para ele, o reserva é um
  desconhecido, que é exatamente o caso que o freio existe para conter.
- **NÃO existe troca automática.** Se o sistema disparasse pelo reserva sozinho
  quando o principal cai, queimaria o segundo número também — e ter reserva é
  justamente para não ficar sem nenhum. A escolha é de quem envia; a tela mostra o
  estado dos dois. Pedir o reserva sem ele estar configurado RECUSA, em vez de cair
  na principal: mandar pelo número errado sem avisar é pior que não mandar.
- **`_sanitizar` varre os DOIS pares, sempre**, não só o da vez: com dois conjuntos
  de credenciais o mesmo texto passa por caminhos diferentes, e limpar só um é a
  brecha que ninguém revisaria. São seis substituições de string.
- **Cache de estado por instância.** Com um dicionário só, perguntar pelo reserva
  devolveria o do principal durante os 60 s de TTL — e a tela mostraria um aparelho
  no lugar do outro, que aqui leva a mandar pelo número errado.
- **Toda mensagem de erro diz DE QUAL número fala.** "A Z-API recusou as
  credenciais" sem isso manda conferir o par errado; "Limite diário atingido" sem
  isso faz parecer que o sistema inteiro travou quando o outro aparelho está livre.
- **O que NÃO se duplica:** interruptor, janela de horário, assinatura e o VALOR do
  limite continuam únicos. O limite é um teto por aparelho, aplicado a cada um —
  dois números não são licença para dobrar o disparo, são dois riscos separados.
- **Reserva CADASTRADO e DESCONECTADO é o estado normal dele**, não um erro a
  consertar: ele espera parado até o dia em que for preciso. Salvar credencial
  não depende de parear nada — e a CONFIRMAÇÃO DE QUE SALVOU tem de vir separada
  do resultado do teste de conexão. Quando o "reserva não conectado" caía por
  cima do "salvo", a tela dizia que falhou justamente no caso que ela precisa
  aceitar, e quem lia tentava de novo achando que não gravou. Vale para qualquer
  formulário que salve e teste na mesma linha.
- Na Saúde, o reserva é DETALHE e não segunda linha de estado: reserva desconectado
  é o estado normal de um reserva (pareado e parado), e dar o mesmo peso faria a
  tela acusar problema onde não há.

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

**Estado que envelhece sozinho não se GRAVA, se calcula (lição da Gestão):**
- **Não existe status "atrasada" em `ges_acoes`.** Atraso é `prazo < hoje AND
  status IN (aberta, em_andamento)`, derivado a cada leitura. Status de atraso
  gravado precisa de alguém para virar, e no dia em que a rotina não roda a
  tela diz que está tudo em dia — a mesma armadilha do marcador de manutenção
  preventiva parado em 77.534 km com o odômetro em 531.970. O CHECK do banco
  recusa o valor, e há teste que quebra se alguém tentar.
- **A mesma regra vale para o que já aconteceu:** `concluida_em` é carimbado na
  transição para concluída e **volta a NULL ao reabrir**. Manter o carimbo
  antigo faria o tempo de ciclo medir a primeira conclusão de uma tarefa que
  seguiu aberta mais dois meses.
- **Prorrogar prazo deixa rastro automático.** Sem o contador, a ação adiada
  seis vezes é indistinguível da que nasceu ontem — e é justamente ela que
  precisa de atenção. Idem troca de responsável.
- **"Em andamento" há dois meses sem ninguém escrever nada não está em
  andamento, está esquecida.** O status diz o contrário com todas as letras;
  quem desmente é o último andamento (`parada_dias`), e ele tem cartão próprio.
- **Responsável é FK para `usuarios` COM alternativa de texto livre.** Só com o
  id dá para montar "minhas ações" e mandar a cobrança ao e-mail certo; mas
  contador externo e motorista não têm login, e recusá-los obrigaria a inventar
  usuário falso. CHECK garante "um ou outro, nunca nenhum", e o nome é gravado
  junto do id para sobreviver à exclusão do usuário.
- **Apagar a ata NÃO apaga as ações** (`ON DELETE SET NULL`): o compromisso
  assumido não deixa de existir porque alguém arrumou o registro da reunião. A
  confirmação na tela diz quantas ficarão órfãs, porque é a consequência que
  não se vê ao clicar.
- **Pauta, discussão e decisões são campos SEPARADOS.** É a diferença entre ata
  e transcrição: em texto corrido, três meses depois, duas pessoas leem a mesma
  ata e discordam sobre o que ficou combinado.

**Onde mora o dado do fornecedor não é onde o nome dele aparece (lição da RasterJOR):**
- Procurei jornada da Raster em `public`, no schema `rastreamento`, na tabela
  `rastreadora_retorno` (3 milhões de XML da Raster, vivos) — e a resposta
  estava em **`sulista.rasterjor_*`**, sete tabelas no schema DA CASA,
  alimentadas por rotina externa que consome a API do fornecedor. **Antes de
  concluir que um dado não existe, listar os schemas**: são 19 neste banco, e
  `information_schema.tables` sem filtro de schema teria achado na primeira
  tentativa.
- **A cadeia de rastreamento engana.** `ocorrenciarastreamento` grava
  `idrastreadora = 3` e o CNPJ da ONIXSAT, o que parece dizer que a jornada vem
  do OnixSat. **Isso é a TECNOLOGIA do equipamento, não o fornecedor do dado**:
  a Raster é hub e entrega mensagens de 132 placas agregando ONIXSAT, SASCAR,
  POSITRON e OMNILINK. Conclusão tirada de uma coluna de id sem olhar o payload
  estava errada, e só o XML de `getMensagens` desfez.
- **Duas apurações da mesma coisa não é duplicação, é o ponto.** O ERP monta
  jornada a partir dos macros; a RasterJOR entrega a jornada apurada por quem
  faz jornada. Quando divergirem, é a divergência que interessa — e ela só
  existe se cada uma for lida de onde nasce. A do ERP é a que alimenta a folha;
  a do fornecedor tem hora extra, repouso faltante e inconformidade nomeada.

**Integração de terceiro que o CÓRTEX não coleta é integração que ninguém vigia:**
- A carga da RasterJOR vivia numa rotina EXTERNA que escrevia em
  `sulista.rasterjor_*` no AVA. Ela parou em 15/04/2026 e ficou **136 dias**
  parada — o CÓRTEX não tinha como consertar nem como saber. A correção não foi
  monitorar melhor: foi **trazer a coleta para dentro**, gravando em `jor_*` no
  banco local, com `jor_carga` registrando toda passagem (inclusive a que
  falhou e a que não trouxe nada). Alarme só existe onde há trilha.
- **Sem credencial NÃO é falha, é instalação incompleta**: a Saúde marca `info`
  e diz qual campo falta. Marcar vermelho ali ensinaria a ignorar o vermelho.
- **Recoletar é o caso NORMAL, não a exceção.** A API devolve o dia inteiro a
  cada chamada e o dia só fecha à noite: toda gravação é `ON CONFLICT … DO
  UPDATE` sobre chave natural. Idempotência aqui é requisito, não otimização.
- **A URL do fornecedor não tem valor padrão.** Adivinhar host no melhor caso
  dá 404 e no pior acerta o endpoint de outra empresa.

**`GROUP BY` não devolve o mês que não existe (a lição central desta rodada):**
- A série mensal da jornada saía de um `GROUP BY to_char(data,'YYYY-MM')`.
  Maio, junho e julho de 2026 **não têm uma linha** — a coleta ficou parada de
  15/04 a 27/08 —, então esses meses simplesmente não voltavam da consulta, o
  gráfico emendava **abril em agosto** e desenhava uma série contínua. Quem
  olha lê **queda de operação** onde houve **ausência de coleta**. É a mesma
  confusão que deixou a parada anterior passar quatro meses e meio sem alarme,
  agora escondida dentro de um gráfico bonito.
- A saída é o intervalo de meses ser **gerado**, não colhido: `_mensal_com_
  cobertura()` percorre de `de` a `ate` e marca `sem_coleta` no que faltou. No
  eixo o mês aparece rotulado "sem coleta", com a barra em cinza claro e a
  linha **aberta** (`null`, não zero) — barra zerada diria "ninguém dirigiu".
- **Cobertura parcial é o mesmo erro, mais discreto.** Outubro/25 tem 10 dias
  de dado e 1.206 jornadas contra 3.672 de setembro: parece despencar, mas
  **por dia coletado são 121 contra 122** — está plano. Todo mês carrega
  `dias`, `dias_possiveis`, `cobertura` e `jornadas_dia`, e o número
  comparável entre meses é o POR DIA.
- **O divisor da cobertura é o RECORTE, não o mês inteiro**: uma janela que
  começa dia 30 não torna janeiro parcial.
- **O corte de parcial é 90%, não 100%.** Mês fechado normal tem domingo e
  feriado sem jornada; exigir todos os dias hachuraria a série inteira e a
  hachura deixaria de significar alguma coisa.

**Recursos da MESMA API com limites diferentes quebram toda razão entre eles:**
- A taxa de inconformidade por jornada saiu **8,55 onde o real é 0,67** — dez
  vezes. Não houve erro de conta: o relatório de produtividade da RasterJOR
  aceita **uma consulta a cada 10 minutos** e as inconformidades não, então a
  coleta tinha **90 dias de numerador e 8 de denominador**. A divisão media a
  COLETA, não a operação.
- Regra: **toda razão entre dois recursos coletados separadamente é calculada
  só sobre a interseção** — aqui, os dias que têm jornada gravada (`EXISTS`
  contra `jor_jornadas`). E a tela DIZ quantos eventos ficaram fora da divisão;
  esconder isso faria a taxa parecer completa.
- É a mesma família do "664 de 836 rastreadores sem sinal": o denominador
  precisa conter só quem podia aparecer no numerador.

**O evento mais frequente do fornecedor pode não ser o problema:**
- `DIRECAO NOTURNA` é **35% de tudo** que a RasterJOR classifica como
  "unconformity" — e **não é violação de nada**: é trabalho noturno, que é
  legal e gera adicional. Somada ao resto, inflava a taxa por jornada em um
  terço, e o KPI de risco trabalhista passava a medir desenho de escala.
- A tela separa **tempo** (as quatro regras da Lei 13.103: direção
  ininterrupta, interjornada, refeição, excesso de jornada) de **marcação**
  (noturna, falha de posição). A classificação é NOSSA e está dita na coluna;
  o tipo cru continua na tabela, porque numa discussão trabalhista quem
  classifica jornada é o fornecedor.
- **Tipo novo do fornecedor entra como `tempo`**: errar para o lado de MOSTRAR
  o risco. Um tipo que ninguém viu ainda caindo num balde silencioso é o jeito
  de descobrir tarde.

**Limites de API que só aparecem chamando (RasterJOR):**
- **Janela máxima de 31 dias**, e a recusa chega de **duas formas na mesma
  API**: HTTP 400 com `{"detail": …}` nas inconformidades e HTTP **200** com
  `{"mensagem": …}` nas ausências. Quem tratar só o 400 acha que a segunda deu
  certo e trouxe zero. O cliente **fatia** a janela sozinho.
- **Limite de taxa entre chamadas**, que a recusa quantifica ("aguarde 30
  segundos"). O cliente espera e repete **uma vez**, com teto de 90 s — dormir
  os dez minutos que o relatório de produtividade pede seria pior que a
  recusa, então acima do teto ela sobe com o motivo. O preenchimento histórico
  é script separado, que espera de fora.
- **A API e a tabela do AVA chamam os mesmos campos por nomes diferentes**
  (`unconformity`/`date`/`start` contra `unconformity_type`/
  `unconformity_date`/`event_start`). O gravador só conhecia o vocabulário do
  AVA e o sintoma foi **425 lidos, 0 gravados** — sem erro nenhum, porque o
  campo ausente virava string vazia e a linha era pulada.

**Ao aposentar uma tela, a substituta HERDA o id — não ganha um novo:**
- A jornada tinha duas telas (a do ERP e a da RasterJOR) e virou uma. A da
  Raster assumiu o id `jorn`, que era da antiga, em vez de manter `jorraster`.
- A razão é RBAC, não estética: `jorn` já estava concedido aos perfis Operação
  e Diretoria por migration. Com um id novo, **a jornada sumiria do menu de
  todo mundo que não é administrador** até alguém escrever uma migration só
  para devolver o acesso que as pessoas já tinham. Favorito e link antigo
  também continuam abrindo.
- O corolário: só herda o id quem substitui MESMO. Se as duas telas fossem
  conviver, ids separados seriam obrigatórios.

**Duas telas do mesmo assunto com definições diferentes viram discussão:**
- Manter a apuração do ERP ao lado da do fornecedor fazia sentido enquanto a
  segunda era novidade a conferir contra a primeira. Depois disso, dois
  números parecidos e não iguais para "jornada do motorista" só produzem
  reunião sobre qual está certo.
- O que saiu foi a LEITURA pelo painel; o dado do ERP continua no banco e
  continua alimentando a folha. Aposentar a tela não é apagar a fonte — e
  dizer isso explicitamente evita o susto de quem depende dela.

**Segredo por e-mail: o que o torna aceitável (lições do boas-vindas):**
- Senha provisória por e-mail é o elo fraco e vale DIZER isso por escrito: o
  e-mail fica na caixa, é encaminhável e sobrevive a backup. O padrão forte
  seria link de primeiro acesso com validade curta. Quando a senha for mesmo o
  pedido, ela vem com quatro defesas — **gerada pelo sistema** (a escolhida por
  gente vira "Mudar@123" em toda a empresa, e aí o padrão conhecido é o elo
  fraco, não o e-mail), **troca obrigatória no primeiro acesso**, **fora da
  trilha e do log**, e o e-mail **dizendo que é provisória**.
- **A senha NÃO entra no `audit_log`.** Registra-se que o e-mail saiu, para
  quem e quando. Trilha com segredo dentro é pior que o e-mail: este perde
  valor quando a pessoa troca a senha, aquela fica para sempre e é lida por
  mais gente.
- **Senha lida de e-mail não tem O/0 nem l/1/I.** É o que faz alguém digitar
  errado e pedir outra — e cada pedido é mais uma senha circulando.
- **Devolver a senha para quem cadastrou só quando o e-mail FALHOU.** Se saiu,
  ela já está com quem vai usar; ecoá-la na resposta a poria também no
  navegador de quem cadastrou, sem necessidade nenhuma.
- **Ação que sai para fora não pode derrubar o cadastro.** O e-mail vai depois
  do commit; se falhar, o usuário continua criado e a tela AVISA — fechar o
  modal em silêncio deixaria alguém criado sem ninguém saber a senha.

**`setInterval` + guard de sequência = tela VAZIA quando o servidor fica lento:**
- A Saúde recarregava a cada 5 s e a resposta passou a levar 4,8 s. O
  `setInterval` dispara **com a requisição anterior em voo**, então quase toda
  resposta chegava depois de uma mais nova ter começado — e o guard
  `if(seq!==meuSeq) return`, que existe para descartar resposta obsoleta ao
  trocar de filtro, a descartava. `DATASRV` nunca era preenchido: **tela em
  branco para sempre, sem erro nenhum aparecer**.
- O sintoma não parece o que é. Não há exceção, não há banner, o endpoint
  responde 200 — e a tela está vazia. Quem investiga vai procurar defeito no
  render.
- Regra: **recarga automática é ENCADEADA**, não por intervalo fixo. Agendar o
  próximo ciclo só DEPOIS de o anterior terminar (`await` e então
  `setTimeout`) torna a tela imune: ela fica mais lenta quando o servidor está
  lento, nunca vazia. Vale para a Torre (120 s) tanto quanto para a Saúde.
- **E consertar só o front seria consertar metade.** 3,6 s dos 4,8 eram sete
  consultas ao agendador do Windows refeitas a cada 5 s, para descobrir uma
  coisa que muda quando alguém roda um instalador. Diagnóstico cujo custo é
  EXTERNO leva cache com TTL — o mesmo padrão do estado da Z-API. Com ele,
  `coletar()` caiu de 5,6 s para 0,95 s.

**E-MAIL DO CÓRTEX NÃO TEM ÁREA ESCURA** (regra dita duas vezes, quebrada duas):
- Fundo escuro em e-mail imprime mal, some no modo de leitura de vários
  clientes e briga com o tema escuro do aparelho — que já inverte tudo por
  conta própria, e é razão a mais para a mensagem não ter área escura PRÓPRIA.
- **A consequência que não é óbvia: o amarelo da marca sai junto.** `#FFD31C`
  tem 1,44:1 no branco e só era legível porque havia navy embaixo dele. Sem o
  fundo escuro, o accent é o **laranja** `#E85D10`, exatamente como no painel.
  A estrutura que o bloco de cor dava vem de um filete no topo e uma borda
  embaixo.
- **A regra é sobre MOLDURA, não sobre cor que carrega significado.** Semáforo
  (`#1E7F4F`/`#B97709`/`#C03221`) numa barra de dado fica: ali a cor é a
  informação, e clareá-la seria inventar tons de estado. A exceção é
  declarada no teste, não descoberta caso a caso.
- **Um layout só.** O boas-vindas nasceu escuro porque tinha HTML próprio
  enquanto a regra vivia em `correio/painel.py`. Todo e-mail passa por lá
  agora — é assim que a regra vale para o PRÓXIMO e-mail sem ninguém lembrar.
- E há teste varrendo todos os e-mails do sistema por fundo com luminância
  abaixo de 110. Regra sem teste volta: esta voltou.

**E-mail é lido no Outlook, que renderiza com o motor do Word:**
- `flex`, `grid`, `background-image`, `position` e `<style>` são ignorados
  CALADOS — o e-mail chega desmontado e ninguém fica sabendo. Tabela de largura
  fixa e estilo em linha, sempre, com teste recusando esses seletores.
- E o **corpo em texto puro não é formalidade**: é o que garante que dá para
  ENTRAR mesmo quando o HTML não renderiza.

**Alarme que acende sem haver problema ensina a ignorar o alarme:**
- A Saúde ficava VERMELHA por qualquer falha de coleta nas últimas 48 h. Mas
  recusa do fornecedor é resposta **normal** aqui: o relatório de produtividade
  só aceita uma consulta a cada 10 minutos, e dois cliques seguidos em "Coletar
  agora" já produzem uma. O cartão ficava vermelho por dois dias com a coleta
  funcionando perfeitamente.
- Vermelho significa **"não está chegando"**, e só isso: dado parado, ou a
  **última** passagem de algum recurso tendo falhado — e diz QUAL recurso,
  porque cada um tem causa e conserto diferentes. O histórico de recusas vai
  para o detalhe, que é onde ele é útil.
- É a mesma família do "sem credencial não é falha, é instalação incompleta".
  O que decide a cor é o estado AGORA, não a contagem de tropeços no caminho.

**Linha por dia NÃO é linha por jornada (o número central saiu 78% inflado):**
- A RasterJOR emite **uma linha por motorista por dia**, inclusive nos dias sem
  trabalho — todos os tempos zerados. São **15.565 de 34.548 linhas** em doze
  meses. Contadas como jornada, elas inflavam o KPI em 78% e **diluíam toda
  média na mesma proporção**: a jornada média saía 6h57 quando a real é 11h25.
- A assinatura é inequívoca e vale procurar em qualquer fonte diária: **88% dos
  domingos e 85% dos sábados** zerados, contra 24% a 36% dos dias úteis. Se o
  fim de semana some, a linha é do CALENDÁRIO, não do evento.
- O dia sem jornada não sumiu — virou o número ao lado, com a quebra que o
  desarma: 85% é folga de escala e 15% tem ausência lançada. Número grande sem
  a decomposição vira alarme falso.

**Faixa física também vale para TEMPO, não só para km:**
- 485 jornadas (2,6%) com **mais de 24 h num único dia**, a maior com 592 h —
  vinte e quatro dias dentro da linha de um dia. São jornadas abertas e nunca
  fechadas, e carregavam **15% de toda a hora extra do período**.
- Elas saem das médias E são contadas num aviso, porque são cadastro a corrigir
  e porque essas horas não vão bater com a folha enquanto ninguém as fechar.
  Tirar em silêncio esconderia o problema; deixar dentro faz a média mentir.
- O mesmo dado trouxe km de **10.520.569 num dia**. Régua: 1.500 km/dia.

**Ficha de pessoa: comparação e PII (lições da ficha do motorista):**
- **Ficha isolada não decide nada.** "5 h de hora extra por jornada" é muito?
  Só a média da FILIAL e a da FROTA, na mesma janela, respondem — e elas vão em
  chip ao lado do valor, não no rodapé.
- **A janela é a da tela principal**, não uma própria: janela fixa em ficha já
  produziu 9% de retorno vazio numa placa que outra tela mostrava com 33,5%,
  ambas certas.
- **CPF não entra na URL e não aparece inteiro.** Ele é a chave da consulta e
  viaja em memória; no hash ele iria para o histórico do navegador, para os
  favoritos e para qualquer print da barra de endereço. Quem identifica a
  pessoa na tela é o nome.
- **A ficha abre para quem saiu.** A coleta de cadastro traz os ATIVOS; recusar
  por falta de cadastro esconde justamente o histórico de quem saiu, que é
  quando alguém costuma precisar dele. Monta-se o cabeçalho do próprio
  movimento, dizendo que foi isso.

**`JSON.stringify` dentro de atributo HTML quebra a PÁGINA, não o link:**
- `onclick="f(' + JSON.stringify(nome) + ')"` fecha o atributo na primeira aspa
  do valor. O sintoma não é um link que não funciona: é **"Unexpected end of
  input" e a tela em branco**. Nome com apóstrofo (D'ÁVILA) quebra a variante
  com aspas simples pelo mesmo motivo.
- A saída que dispensa citação: `data-doc="..."` com `esc()` e
  `onclick="f(this.dataset.doc)"`.
- E o subtítulo do `kpi()` passa por `esc()`: chip mandado por ali sai como
  texto com as tags à mostra. O slot cru é o **sexto** parâmetro (`trend`).

**Renderizar com DADO REAL acha o que o teste com dublê não acha:**
- Três defeitos desta tela só apareceram ao abrir a página com o payload do
  banco, e nenhum deles falhava teste nenhum: a coluna "por jornada" repetindo
  um denominador que o KPI já tinha corrigido (3,05 contra 0,26); o km/h um
  quarto abaixo porque `km` é nulo em dois terços das jornadas; e "40 de 135
  motoristas atingidos" que era o **teto do `LIMIT`** e não a realidade — o
  real é **131 de 135**.
- Fixture é escrita por quem já sabe o que espera. O dado real traz o nulo em
  dois terços das linhas, o `LIMIT` batendo e o acento que quebra o console.
  Vale um script que suba um `http.server`, sirva o `index.html`, responda a
  rota com `get_...()` de verdade e imprima os KPIs — foi assim que os três
  saíram.
- **Corrigir o cartão e esquecer a tabela logo abaixo dele** é a forma mais
  fácil de deixar a tela se desmentindo. Ao consertar um denominador, procurar
  todos os lugares que dividem pela mesma coisa.

**`%` dentro de string de SQL vira placeholder do psycopg:**
- Um comentário `-- km é NULO em 65% das jornadas` dentro do `"""…"""` derruba
  a consulta com `incomplete placeholder: '%'`. A explicação vai em comentário
  **Python**, acima da constante — que é onde ela é lida de qualquer forma.

**ECharts na Jornada — o segundo uso, e o critério que o autorizou:**
- Entrou porque a **série diária tem centenas de pontos e precisa de zoom**,
  que é exatamente o critério da seção de gráficos. Os outros três gráficos da
  tela acompanham por coerência: meia tela com tooltip de biblioteca e meia
  com `<title>` de SVG seria pior que qualquer das duas.
- **Uma carga serve os quatro** (`carregarECharts()` memoiza), e há teste que
  falha se a Visão Geral baixar o arquivo.
- **Eixo de TEMPO, não de categoria, na série diária.** Com eixo categórico os
  dias sem coleta não existiriam e o gráfico poria 15/04 ao lado de 21/08,
  desenhando continuidade sobre quatro meses de buraco.
- **`connectNulls:false`** na linha mensal: o mês sem coleta ABRE a linha, que
  é a leitura certa — não há média de dia nenhum ali.

**UNIQUE sobre coluna nula não restringe nada (custou 55 mil linhas):**
- 56% das inconformidades da RasterJOR **não têm hora de início** — são fato do
  DIA, não intervalo. A primeira versão do carregador as descartava por exigir
  a hora na chave; a segunda quase as duplicou a cada recarga, porque no
  Postgres `NULL` é sempre distinto de `NULL` e o UNIQUE não pega.
- A saída foi separar as duas coisas: **`inicio` guarda a verdade (nulo quando
  é nulo) e `chave_evento` guarda o que serve para deduplicar**. Preencher
  `inicio` com meia-noite resolveria o UNIQUE inventando um horário que a fonte
  não deu — e horário inventado vira gráfico.
- **Tabela de origem sem chave acumula duplicata em silêncio**: eram 98.109
  linhas para 49.208 eventos, e a taxa de inconformidade por jornada saía 2,22
  quando o real é 0,85.

**Arredondar antes de dividir move o número de lado da fronteira:**
- `razao_parado_direcao` saía 1,52 onde o certo é 1,50, porque a conta era
  feita sobre horas já arredondadas a uma casa (5,0 ÷ 3,3) em vez dos minutos
  (300 ÷ 200). Num indicador cujo limiar de leitura é 1,00, isso decide se a
  frase é "passa mais tempo parado" ou não. Razão e percentual saem sempre da
  unidade de origem.

**Integração parada se disfarça de tela vazia (a lição mais cara desta rodada):**
- A carga da RasterJOR estava **parada há 136 dias** e ninguém notara, porque o
  sintoma é uma tela sem dado — que se lê como "ninguém rodou" em vez de "parou
  de chegar". `rasterjor_anomalies` estava parada havia **quinze meses**.
- **Janela ancorada no ÚLTIMO DADO, nunca em `current_date`.** Com a carga
  parada, `current_date - 90` devolve zero linha e a tela abre em branco,
  escondendo o problema justamente na página que o revelaria. Ancorar no
  máximo da coluna de data faz a tela mostrar os últimos 90 dias QUE EXISTEM,
  e a tarja diz de quando são.
- **O atraso anunciado conta só as fontes que AQUELA tela usa.** Sem separar,
  o pior atraso pegava os 459 dias de uma tabela que a tela nem lê e anunciava
  459 sobre números de 136. Alarme com o número errado ensina a ignorar o
  alarme.
- Quando a rotina de carga **não roda no CÓRTEX**, a Saúde não conserta: ela
  DENUNCIA, com o número de dias e dizendo que o conserto é externo.

**Código sem domínio: decodificar por evidência, ou não decodificar:**
- `jornada_registro.tipojornada` (AVA) tem 9 valores e nenhuma tabela de
  domínio. Decodifiquei somando o tempo por tipo dentro de cada jornada e
  comparando com as colunas NOMEADAS do cabeçalho, sobre 2.756 jornadas: tipos
  3, 4, 5 e 10 batem em 100%, e **direção é a SOMA dos tipos 2 e 6** (nenhum
  sozinho passa de 15%). Evidência assim vai escrita no módulo, senão o
  próximo "corrige" para outra coisa.
- Quando NÃO dá para decodificar, não se inventa: `journey_type` da RasterJOR
  vem como letra (N, D, A, F) sem domínio nem no `raw_api_data`, e a tela
  mostra a letra com a direção média, o tempo médio e o km de cada uma. Mesma
  regra da coluna "Tipo (cód.)" da Manutenção.
- **Regra montada sobre campo vazio conta o que não existe.** Uma versão do
  ciclo de direção contava "acima de 5h30 sem descanso de 30 min" e devolvia
  2.666 violações — mas `tempodescanso` daquela tabela vem ZERO em 64% das
  linhas: media preenchimento. **O sinal foi o número bater EXATAMENTE com o
  total acima de 5h30** — quando dois recortes que deveriam diferir dão o
  mesmo número, um dos dois não filtra nada.

**O AVA é PostgreSQL 9.3.** Sem `FILTER (WHERE …)`, que só chegou no 9.4 — todo
agregado condicional é `CASE WHEN`. O erro aponta para o meio do agregado
(`syntax error at or near "("`), não para a versão. O banco local do CÓRTEX é
16 e aceita `FILTER` normalmente.

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
