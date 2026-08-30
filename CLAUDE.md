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
SQLite de `data/` foram migrados para lá em 27/08/2026 e os `.db` continuam no
disco como desfazer.

**ARQUIVADOS em 30/08/2026**, e não apagados: os 9 `.db` (3,3 MB com os
sidecars WAL/SHM) saíram de `data/` para
`data/arquivo/sqlite-migrados-2026-08-30/`, com um LEIA-ME dizendo o que são e
como voltar. O gatilho foi a restauração do backup passar (seção 5.1) — o
caminho de volta virou o dump, provado, e não um SQLite de agosto que ninguém
restauraria por cima de um Postgres com dias de escrita.

Vale guardar por que o prazo foi amarrado a algo VERIFICÁVEL em vez de a uma
data: "desfazer" sem gatilho vira lixo, e lixo que ninguém ousa apagar porque
ninguém sabe se ainda serve.

**A linha some da Saúde sozinha** — a varredura é da pasta, então zero
arquivos é zero linha. E o código do sensor FICA, porque ele é o que faz o
rollback funcionar: devolver um `.db` para `data/` o traz de volta ao cartão
na hora, e como CONHECIDO (`info`), não como banco não declarado — volta
deliberada não é alarme. Remover o sensor tornaria a volta invisível.

**Na Saúde eles NÃO são nove linhas, são UMA** — e essa é a lição. O cartão
listava 9 bases e 8 delas só diziam "migrada · arquivo mantido como desfazer":
89% de linhas que nunca mudam ensinam a pular o cartão, e junto com ele a
única que decide algo (o cache da Gobrax, onde corrupção é falha silenciosa).
É a mesma família do alarme que acende sem haver problema. Hoje a tabela lista
só o que está VIVO e os migrados viram uma linha com os três números que
sustentam a decisão de apagar — quantos, quanto ocupam, desde quando parados —
que **some sozinha quando o último for apagado**.

**E essa linha é um SENSOR, não um enfeite.** Fica âmbar em dois casos:
`.db` migrado **escrito de novo** (código voltou a gravar em SQLite e esse
dado NÃO está no Postgres) e **`.db` que ninguém declarou** — a varredura é do
DIRETÓRIO, não de uma lista, justamente para pegar o arquivo que apareceu sem
passar por lá. Uma lista fixa só enxerga o que já se sabia.

**Ao criar módulo novo que escreve:** use `api/pglocal.py`, nunca abra SQLite.
`tests/test_saude_bases_locais.py` quebra se `sqlite3.connect` aparecer fora
de `api/gobrax/armazenamento.py` (o cache) e de `api/servidor.py` (que só o
confere, em modo leitura) — a regra não depende de alguém reparar na tela.
A tabela leva o **prefixo do módulo** (`fin_*`, `ext_*`, `orc_*`…) e o DDL vira
uma migration numerada em `sql/cortex/`, aplicada por
`scripts/migrar_schema.py`. O módulo expõe `ESQUEMA` para o teste redirecionar,
e o teste usa a fixture `esquema_pg` (schema por teste). Plano, decisões e as
armadilhas encontradas: **`docs/MIGRACAO_POSTGRES.md`**.

Continuam FORA do banco, de propósito: cache reconstruível
(`data/telemetria.db`, `data/pneus/`, `data/premiacao/`, `data/dre_cliente/`) e
segredo em arquivo (`data/credenciais.json`, `data/email_config.json`,
`data/whatsapp_config.json`, os `.pfx` e `data/certificados/senhas.json`).

**"Permissão 0600" era FICÇÃO NESTE SERVIDOR, e ficou anos escrita aqui.**
`os.chmod` no NTFS só liga o atributo somente-leitura; quem decide acesso é a
**ACL**, e ela continuava sendo a herdada da pasta. Os cinco lugares que
gravam segredo agora chamam `api/segredo_arquivo.proteger()`, e a Saúde tem um
cartão que **MEDE** a ACL em vez de afirmar a proteção. Três lições ficaram:
- **O teste que deveria pegar isso estava VERMELHO e ninguém reparava**, porque
  media `st_mode` numa plataforma onde `st_mode` não quer dizer nada. Teste que
  mede a coisa errada é pior que teste ausente: ocupa o lugar do que faria falta.
- **O achado real era melhor do que o temido e pior do que parecia:** os
  arquivos ESTÃO restritos — por **herança da pasta do usuário**, não porque o
  código pediu. Proteção por acidente sobrevive até o projeto mudar de lugar, e
  ninguém saberia.
- **Duas versões minhas quase criaram problema maior que o consertado.** A régua
  "qualquer SID que não seja o dono é intruso" acendeu vermelho em 24
  certificados cujo "intruso" era a conta que opera o painel (os `.pfx` são
  gravados pela API, que roda como SISTEMA, então o dono é o SYSTEM) — 24 falsos
  positivos são um alarme que nasce ignorado. E a `proteger` que reconstruía a
  ACL teria trancado essa mesma conta, que **não é administradora**, para fora
  dos certificados no próximo upload. O que vale: exposição é **grupo AMPLO**
  (Usuários, Todos, Usuários autenticados, Usuários do Domínio por RID), a
  remoção é **cirúrgica e idempotente**, e sem conseguir LER a ACL não se
  escreve nada.

---

## 3. Módulos do portal

Cada módulo é unidade de RBAC (papel × módulo × escopo de linha via RLS).

| Módulo | Conteúdo | Tabelas/views-chave |
|---|---|---|
| `financeiro` | Caixa, recebimentos, pagamentos, adiantamentos, DRE, análises financeiras, projeções | `fin_titulos`, `fin_adiantamentos`, `fin_lancamentos`, `fin_dre`, `vw_fluxo_caixa`, `vw_dre_mensal` |
| `comercial` | Clientes, fretes, RKM, concentração, churn | `com_clientes`, `com_fretes`, `vw_rkm_cliente` |
| `crm` | Funil comercial: contas (ligadas ao grupo econômico do AVA), contatos, oportunidades por LANE com piso ANTT, atividades, histórico e contratos. A base do Avacorp (leitura de `gestaocomercial`/`pipelineprojetos`) segue viva numa sub-aba | `crm_contas`, `crm_contatos`, `crm_oportunidades`, `crm_lanes`, `crm_atividades`, `crm_interacoes`, `crm_contratos` (banco local) |
| `operacional` | Cargas, viagens, rotas, CKM | `op_viagens`, `op_cargas`, `op_rotas`, `vw_ckm_viagem` |
| `programacao` | Programação de cargas e alocação/gestão de veículos | `prog_cargas`, `prog_alocacao`, `prog_disponibilidade` |
| `torre_controle` | Monitoramento operacional em tempo real: posição, status, ETA, ocorrências | `tc_posicoes` (hypertable), `tc_ocorrencias`, `vw_viagens_ativas` |
| `torre_seguranca` | Segurança em tempo real: eventos de risco, score, sinistralidade, alertas | `ts_eventos` (hypertable), `ts_scores`, `vw_sinistralidade` |
| `telemetria` | Telemetria avançada (CAN/J1939) com insights: consumo, ECO, falhas, DTCs | `tel_sinais` (hypertable), `tel_dtc`, `vw_consumo_veiculo` |
| `frota` | Ativos, disponibilidade, manutenção, pneus, depreciação | `fro_veiculos`, `fro_manutencao`, `fro_pneus` |
| `jornada` | Jornada do motorista (Lei 13.103/2015). UMA tela, lendo a apuração da **RasterJOR** coletada pelo próprio CÓRTEX. A apuração do ERP continua no banco e continua alimentando a FOLHA — o que saiu do painel foi a leitura dela | `jor_jornadas`, `jor_inconformidades`, `jor_motoristas`, `jor_ausencias`, `jor_carga` (banco local) |
| `suprimentos` | Agregados, fornecedores, contratos, make-vs-buy | `sup_agregados`, `sup_fornecedores`, `sup_contratos` |
| `telemetria` | Dados da plataforma Gobrax por API com token: premiação por nota × km, consumo × abastecimento, os **14 indicadores de condução**, hodômetro/rastro e o **monitor de veículo sem comunicar** | `api/gobrax/`, `data/premiacao/` |
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

**PAINEL DE BI CABE EM UMA TELA (regra do usuário, 30/08/2026):**
Painel é visual e se lê **sem rolar**. O que não couber vai para **sub-aba**
(`.subtabs` + `abaTrocar(grupo, qual)`), nunca para o fim da rolagem.
- Painel que rola é painel que ninguém lê inteiro. Esta casa já produziu página
  de **16.000px** (CRM) e de **8.602px** (Custos), e o que ficava embaixo era
  tão decisório quanto o topo.
- **Aba, não tela nova**: RBAC, filtros e estado são os mesmos, e duas telas
  dividiriam um estado que é um só.
- **A aba que tem GRÁFICO nasce aberta.** O ECharts mede o contêiner uma vez,
  no `init`, e medida feita sob `hidden` vale zero para sempre — o gráfico sai
  com os eixos certos e quase todos os rótulos do eixo X suprimidos, sem erro
  nenhum aparecer. O `ResizeObserver` do `echartsRegistrar` cobre a volta;
  começar visível dispensa a correção.
- **A aba leva contador** (`abaContador`): aba vazia e aba com 24 veículos
  parados pedem coisas diferentes de quem olha, e obrigar o clique para
  descobrir isso desfaz metade do ganho. **Zero fica em branco**, não em "0".
- Tabela longa continua rolando **dentro do card** (`.tabroll`), não na página.
- Já aplicado: Premiação (Premiação × Configuração) e Produtividade de Veículos
  (Visão geral × Por veículo × Ociosidade).

**CSS INSERIDO POR VIZINHANÇA CAI DENTRO DO BLOCO ERRADO (custou 4 versões):**
As regras da estrela de favorito, do botão de tema, do de tela cheia, da barra
de sub-abas, do contador e do seletor de giro foram parar **dentro de
`@media(max-width:880px)`** — porque a inserção foi ancorada num seletor
vizinho (`.dfreq`, `#btnFav`) sem conferir a PROFUNDIDADE DE CHAVES do ponto.
No desktop, que é onde o painel é usado, esses controles ficaram **sem estilo
nenhum** da 0.152.0 à 0.156.0.
- **Nada existente pegava:** `node --check` valida JavaScript e não CSS;
  `verificar_estrutura.py` olha atributo e aspa; e o auditor de tema roda a
  1500px mas mede **cor** — elemento sem estilo tem cor padrão com contraste
  ótimo. O defeito era invisível para todas as conferências que havia.
- **Ancorar por vizinhança em CSS não diz em que bloco se está.** Antes de
  inserir, conte `{` menos `}` desde o `<style>` até o ponto: tem de dar zero.
- O guarda que ficou **pergunta ao NAVEGADOR**, na largura de desktop, se a
  regra chegou (`.subtabs` tem `display:flex`? o botão tem `cursor:pointer`?).
  Ler o texto do CSS não responde isso.

**Rotação e tela cheia (pedido do usuário, 30/08/2026):**
- Todo painel com mais de uma aba ganha o controle **"Girar"** (`abaAutoMontar`
  monta em toda `.subtabs[data-abas]`, então painel novo já nasce com ele). Um
  controle só, com "não girar" DENTRO dele — interruptor separado do intervalo
  cria o estado "ligado com intervalo nenhum", que ninguém prevê lendo a tela.
  **Clique manual REARMA o relógio**: um clique dado a dois segundos do giro
  tiraria a pessoa da aba antes de ela ler qualquer coisa. Não gira com a aba
  do navegador escondida, e a escolha é **por painel**.
- **Tela cheia em todo painel** (`body.painelfull`), separada da `tvfull` das
  duas telas de TV — aquela esconde o cursor e reflui em `vw`, e herdar isso
  num painel onde ainda há alguém clicando seria erro. O **estado vem do
  navegador** (`fullscreenElement` + evento `fullscreenchange`), nunca de
  variável nossa: sair com Esc é atendido pelo navegador sozinho, e uma
  variável paralela deixaria a tela achando que está cheia, sem moldura e sem
  jeito de voltar. A saída é um botão FLUTUANTE, porque o que entrou vive na
  barra de topo, que some junto.

**Gráfico: ECharts, e SÓ ECharts. A conversão acabou em 30/08/2026.**
Não existe mais gráfico desenhado à mão no painel. Gráfico novo nasce em
ECharts, sem decisão a tomar. A única exceção é o **gauge de meta do dia dos
painéis de TV** — um arco de 2 `path`, numa tela sem hover, onde a biblioteca
não acrescenta nada. `grep '<svg viewBox='` no `index.html` acha ele e o
helper de ícones (`IC`), e mais nada.

**O LEVANTAMENTO ERROU O TAMANHO DO TRABALHO, e vale saber por quê.** O lote
foi definido por um grep de `<svg id="chart…">` e deu 39. Mas esse grep NÃO
enxerga gráfico montado como STRING e injetado com `innerHTML`, que não tem
contêiner no HTML estático — eram mais três (saldo por dia do Extrato, saldo
dia a dia do Fluxo consolidado, ações por mês da Gestão), descobertos só
porque `colPath` continuava tendo chamador depois de "terminar". **Contar
trabalho por marcador no HTML subestima; o que fecha a conta é não sobrar
chamador dos helpers antigos.**

`colPath`/`colRect` saíram junto com o último deles.

**A conversão levou quatro dias e foi feita por TELA, nunca em bloco** — e essa
foi a decisão certa, porque cada gráfico carregava uma regra que só aparece
lendo o código dele (o rótulo do retorno vazio que sai AO LADO da barra porque
acima cairia dentro da vermelha; a prioridade do último rótulo no eixo do
fluxo; o realizado que NÃO desenha barra no mês não fechado). Reescrever tudo
de uma vez teria perdido cada uma em silêncio.

**O que a conversão custou, e vale saber antes da próxima:**
- **Recorte por marcador errou 3 vezes num dia** e apagou 20 rotas alheias, o
  `loadHc` e o `loadMvb`. A defesa que funciona é comparar a lista de funções
  antes e depois de todo corte e exigir `sumiram: nenhuma` — está na seção de
  corte por marcador, e foi ela que pegou os três.
- **Teste amarrado à IMPLEMENTAÇÃO quebra sem haver defeito, e isso aconteceu
  de duas formas.** (1) Afirmando sobre o TEXTO-FONTE: dois testes do eixo do
  fluxo caíram só porque o espaçamento do laço mudou. (2) Afirmando sobre a
  MARCAÇÃO do renderizador antigo: os testes de hachura procuravam
  `stroke-dasharray` (Extrato) e o id `gaHx` (Gestão), e a hachura não tinha
  sumido — só virou `<pattern>` do ECharts. Todos viraram teste de
  comportamento: o último rótulo aparece e o vizinho da esquerda sai; **N
  barras hachuradas, com N vindo do próprio payload** e menor que o total,
  senão a marca deixaria de distinguir.
- **E um desses testes cobrou de volta uma regra que eu tinha perdido:** o
  gráfico da Gestão saiu da conversão sem o rodapé "mês corrente hachurado ·
  parcial". A hachura sem legenda é um enigma — quem olha não sabe se aquilo é
  outra categoria. O `assert "parcial" in ...` pegou.
- **Dublê otimista faz teste passar por vacuidade** — ver a regra 1 abaixo.

**ECharts 5.6.1 (Apache 2.0) entrou em 27/08/2026**, vendorizado em
`api/static/vendor/echarts.min.js` com a licença ao lado. Nasceu como escolha
para o que o SVG à mão não fazia — **zoom/pan em série longa, drill-down,
exportação, gantt, mapa** — e virou o padrão de tudo.

**Os construtores da casa ficam em `ecOpcoes`/`ecBarras`/`ecLinha`/`ecDesenhar`**
(+ `ecEixoValor`, `ecUnidade`, `ecDecal`, `ecTooltip`, `ecFalha`). Gráfico novo
sai deles, não de `option` escrito na mão: é neles que moram a paleta, a
unidade final do eixo, a hachura do parcial e a mensagem de falha.

Quatro regras para usá-lo, com teste em `tests/frontend/test_echarts_e2e.py` e
`test_echarts_largura_zero.py`:

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
4. **Contêiner de largura ZERO não se conserta sozinho — e o sintoma é mudo.**
   O SVG tinha `viewBox` e escalava ao aparecer; o ECharts **mede uma vez, no
   `init`**, e uma medida de zero vale para sempre. Um gráfico desenhado com a
   view em `display:none` não dá erro nem cartão vazio: ele aparece com os
   eixos certos e os **rótulos do eixo X quase todos suprimidos** pelo
   `hideOverlap`, o que faz uma série de cinco pontos parecer ter um (medido:
   cinco dias de combustível mostrando só `02/08`). O conserto é um
   `ResizeObserver` no **`echartsRegistrar`** — ali, e não no `ecDesenhar`,
   para valer também para quem chama `init` na mão. Ele cobre os três casos de
   uma vez: view que aparece, sidebar que recolhe, janela que muda.

**Não usadas, e por quê:** amCharts 5 — o CÓRTEX é atrás de login, então a
licença seria a Single App a US$ 650 perpétua/assento, e a versão grátis proíbe
esconder o logo, que apareceria no mural do corredor. **ApexCharts — cuidado:
parece livre e não é.** Deixou de ser MIT e hoje cobra de organização com mais
de US$ 2 milhões de receita anual, incluindo ferramenta interna. Chart.js (MIT)
entrega menos que os gráficos da casa já fazem. uPlot (MIT, 49 KB) fica como opção
se algum dia o problema for só série temporal longa.

**TEMA CLARO E ESCURO (pedido do usuário, 30/08/2026):**
O painel tem **três** estados, não dois: escolha explícita carimba
`data-theme` na raiz; o padrão — seguir o sistema — **não carimba nada**, e aí
só o `prefers-color-scheme` decide. Isso obriga a estrutura do CSS:
- a paleta CLARA completa mora no `:root` puro;
- `@media (prefers-color-scheme: dark)` redefine **só tokens**, guardado por
  `:not([data-theme="light"])`, para a escolha clara vencer um sistema escuro;
- `:root[data-theme="dark"]` repete os mesmos tokens, para a escolha escura
  vencer um sistema claro. **Um teste exige que os dois blocos sejam
  idênticos** — são duas cópias, e cópias divergem.
- Regra de COMPONENTE dentro do bloco de mídia nunca vale no estado "sistema",
  e o sintoma é texto de um tema sobre o fundo do outro.
- O carimbo é feito por um script no `<head>`, **antes do primeiro pixel**: no
  fim do arquivo, quem escolheu escuro veria a tela clara piscar a cada carga.

**O que NÃO muda com o tema:** `--navy-800/900` (a barra lateral, que já era
escura nos dois), o `--brand` (é MARCA, não accent — no escuro ele finalmente
tem contraste, e promovê-lo mudaria a identidade entre temas) e os painéis de
TV, escuros de propósito. O **semáforo muda de TOM, não de significado**:
assume o conjunto brilhante que a TV já usava (`#4ADE80`/`#FBBF24`/`#F87171`),
porque `#1E7F4F` some no escuro.

**A paleta dos GRÁFICOS não acompanha sozinha.** `CC` lê os tokens uma vez e o
ECharts **copia** as cores para dentro da `option` no desenho. Sem
`ccAtualizar()` + `echartsRepintar()` (que refaz a `option` do `montar`
guardado em `_ecMontar`), trocar de tema deixa barra navy escura sobre card
escuro. Gráfico que chama `init` na mão sem passar por `ecDesenhar` só é
redimensionado — degradação visível, não erro escondido.

**`scripts/auditar_tema.py` é o que tornou isso viável.** São ~205 literais de
cor fora do `:root` e ~98 em `style=`; trocar todos às cegas quebraria o tema
claro, que estava certo. O auditor abre as 68 telas no navegador e mede o que
o usuário vê — contraste de cada texto contra o fundo REAL (subindo a árvore
até o primeiro ancestral opaco) e "ilha" de fundo do tema errado. Foram **21
achados**, não 205, e todos com endereço. Quatro lições:
- **A régua é ASSIMÉTRICA porque o design é.** No claro, controle com fundo
  escuro é o botão primário da casa — acusá-lo deu 146 achados de um padrão
  só, ou seja um relatório que ninguém leria. No escuro não existe padrão de
  controle claro: um `select` branco ali é literal esquecido.
- **Amostra de cor não é superfície.** A primeira versão acusava o quadradinho
  de 14px da legenda, que É o verde do semáforo.
- **Metade do tema passava por vacuidade:** o auditor rodava só com a
  preferência do navegador, então sabotar o `[data-theme="dark"]` não produzia
  achado nenhum. Daí o modo `--fixo`, que carimba a escolha e põe o sistema no
  oposto.
- **`--n500` era AA na teoria e reprovava na prática:** calibrado para
  exatamente 4,5:1 sobre BRANCO, margem zero, e quase nada no painel é branco
  puro (sobre `--n50` dava 4,37). Idem `--green-100` e `--red-100`. Token com
  margem zero é token que falha em uso.
- **`var(--ink, #1E2833)` parecia token e era literal disfarçado:** `--ink`
  nunca existiu no `:root`, então as cinco regras caíam no fallback — cor
  certa por acidente no claro, invisível no escuro. Fallback de variável
  inexistente é a forma mais silenciosa de hard-code.

**Design system (valores reais implementados — tokens em `api/static/index.html`):**
- **A MARCA DA SULISTA É `#942821` (vermelho tijolo) + `#1E172F` (quase-preto
  arroxeado), sobre branco. NÃO HÁ AMARELO.** Este documento afirmava "amarelo
  Sulista #FFD31C", o token `--brand` propagou a afirmação pelo painel inteiro,
  e **o usuário corrigiu em 30/08/2026**: não há amarelo na marca.
  A paleta real foi **medida nos arquivos de marca do próprio repositório** —
  favicon.png, icon-192, icon-512 e apple-touch-icon —, e os quatro concordam:
  62% dos pixels do símbolo são `#942821` e 37% são `#1E172F`.
  **O repositório guardava a resposta o tempo todo**; a rodada anterior
  concluiu que não porque olhou só o SVG (silhueta branca pura) e desistiu.
  Antes de dizer "não dá para saber", ler TODOS os arquivos que a casa versiona.
- **A marca tem DUAS versões porque as duas superfícies são opostas.**
  `--brand` (#942821) rende **8,12:1 no branco** e apenas **1,92:1 sobre o navy
  da barra lateral**, onde sumiria — exatamente o inverso do amarelo que estava
  no lugar dele (1,44:1 no branco, 10,85:1 no navy). Por isso a sidebar usa
  `--brand-claro` (#E0705F, 5,4:1 sobre o navy): é a mesma marca, legível.
  `--brand-ink` (#1E172F) é o segundo tom, tinta de título.
  **O e-mail é onde a marca aparece no tom ORIGINAL**, porque lá a superfície é
  branca. Nenhum dos três é accent de UI.
- **Accent geral da UI clara:** laranja `#E85D10` = `--orange-500` (foco,
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

**CRM: a unidade é a LANE, e é isso que o distingue de um CRM genérico:**
- Em FTL ninguém vende "R$ 400 mil por mês": vende Joinville→Betim, carreta de
  6 eixos, 22 viagens, R$ 4.800 a viagem. **É na lane que existe km**, e
  portanto R$/km, piso mínimo da ANTT e margem contra o CKM. Oportunidade com
  valor global não responde "esse frete paga o piso?" — que é a pergunta que
  pode tornar o negócio ILEGAL, não só ruim.
- **A receita da oportunidade NÃO é gravada**: é a soma das lanes, calculada
  na leitura. Total desnormalizado passa a discordar das próprias linhas no dia
  em que alguém edita uma delas, e discorda em silêncio.
  `receita_mensal_manual` é a exceção declarada e só vale enquanto não houver
  lane nenhuma — e a tela DIZ qual dos dois está valendo (`origem_receita`),
  porque um número que muda de fonte sem avisar é um número em que ninguém
  confia.
- **Os dois R$/km saem lado a lado.** A diferença entre o do km carregado e o
  do km total É o custo do retorno vazio; só o primeiro faz a lane de 1.180 km
  de ida com 1.180 de volta vazia parecer tão boa quanto a que tem carga nos
  dois sentidos. A margem usa o TOTAL, que é o que consome diesel e motorista.
- **O piso da ANTT NUNCA é gravado**: depende da tabela vigente NA DATA, que
  muda duas vezes por ano. Congelado no dia da proposta, ele reprovaria depois
  um frete correto — ou, pior, aprovaria calado um que passou a estar abaixo do
  mínimo legal. E **ausência não é zero**: lane sem eixos ou sem tipo de carga
  tem piso `n/d` com o motivo, nunca "R$ 0,00".
- **O pedágio não entra no piso**, e isso é dito na tela: a Res. 5.867/2020
  remunera deslocamento e carga/descarga. Somá-lo ao valor antes de comparar
  aprovaria frete abaixo do mínimo legal com dinheiro que é do pedágio.
- **O CKM é UM SÓ para todas as lanes, e vai no rodapé — não vira coluna.** O
  razão é consolidado; não existe CKM por rota nesta casa. Uma coluna repetindo
  R$ 12,60 em vinte linhas passa a impressão de cálculo por rota, que foi
  exatamente o que a Make vs Buy teve de desfazer. O que varia por lane, e por
  isso merece coluna, é a MARGEM.
- **"Cliente ativo" é lido do faturamento, não de um campo.** Prospect (sem
  vínculo com o `agrupamentocliente`), ativa, parada há mais de 90 dias e sem
  histórico saem todas de `api/crm/ava.py` a cada leitura. Nenhum status
  comercial é gravado em lugar nenhum do módulo — a mesma regra do atraso de
  ação da Gestão e da vigência de contrato.
- **Prospect mostra `n/d`, jamais `R$ 0`.** Zero que é ausência de VÍNCULO não
  é desempenho: poria a conta no fim de um ranking de receita como se
  faturasse zero, e "cliente que não fatura" é leitura de negócio, não de
  cadastro. Mesma família do "0% de retorno vazio em verde" da Análise de KM.
- **O vínculo com o ERP é o GRUPO ECONÔMICO, nunca o CNPJ** — é a chave que a
  DRE por Cliente, a Consulta de Cliente e a meta de faturamento já usam. Casar
  por outra coisa criaria um quarto recorte de receita numa casa que já precisa
  explicar três. E o UNIQUE é PARCIAL (`WHERE ava_agrupamento IS NOT NULL`):
  sem o `WHERE`, `NULL` nunca colide com `NULL` e duas contas apontariam para o
  mesmo cliente, cada uma com metade das oportunidades.
- **Tarefa e interação são tabelas diferentes.** `crm_atividades` é o
  compromisso futuro, mutável; `crm_interacoes` é o que aconteceu, append-only
  (não há editar nem excluir, nem no módulo nem na rota). Numa tabela só,
  editar o registro de uma visita para virar "tarefa concluída" apaga a prova
  de que a visita houve — e é esse histórico que responde "há quanto tempo
  ninguém fala com este cliente".
- **Concluir tarefa de CONTATO registra a interação; concluir "montar
  proposta" não.** Quem acabou de ligar está com o resumo na cabeça e é a única
  hora em que vai escrever. Mas registrar uma tarefa que não é contato faria o
  "dias sem contato" mentir para BAIXO — justamente o número que serve para
  cobrar contato.
- **Valor de domínio em MINÚSCULA, sem exceção.** `escolha()` normaliza a
  entrada para minúscula, então `'IPCA'` no CHECK recusava o `'IPCA'` que a
  própria tela mandava. O rótulo bonito vive no dicionário de rótulos.
- **Formatar dinheiro em pt-BR troca DOIS separadores.** `f"{v:,.2f}".replace(",", ".")`
  produz `4.550.48` — dois pontos, nenhuma vírgula, e o número some da leitura.
  Precisa de marcador intermediário.
- **A base do Avacorp foi PRESERVADA, não migrada.** Ela virou sub-aba somente
  leitura e nada foi copiado dela: duas verdades sobre o mesmo lead seria o
  preço de uma importação que ninguém pediu. As duas metades da tela carregam
  em paralelo com `allSettled` — falha do AVA não pode derrubar as cinco abas
  que não dependem dele.
- **A tela herdou o id `crm`**, e por RBAC: o id já estava concedido ao perfil
  Comercial por migration, e um id novo faria o CRM sumir do menu de todo mundo
  que não é administrador. Mesma regra da jornada que herdou `jorn`.

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

**Ler 3 de 14 campos da MESMA resposta (lição dos indicadores da Gobrax):**
- `vehicle-performance` sempre devolveu **14 indicadores** e o CÓRTEX lia
  **3**. Os 11 descartados incluíam justamente os que a premiação precisava —
  `idle` (motor ligado parado) e `greenRange` (faixa verde). Não faltava
  integração nem endpoint: faltava **ler a resposta inteira**. Ao integrar
  fornecedor, despejar o corpo cru uma vez e olhar campo por campo custa
  minutos e evita reintegrar depois.
- **A premissa de custo estava errada por 20x, e era ela que travava tudo.** O
  módulo dizia "~17 s por chamada, varrer a frota seriam mais de 20 minutos", e
  por isso a coleta em lote nunca foi feita. Medido: **0,79 s por placa, 90 s a
  frota de 108**. Número de desempenho escrito em comentário **envelhece** —
  antes de descartar um caminho por ser caro, medir de novo.
- **Dispersão decide se um indicador serve para PREMIAR.** `idle` vai de 9,2%
  (p25) a 16,7% (p75) com cauda até 60,4% — separa. `greenRange` tem a metade
  central entre 93,8% e 98,8%: **cinco pontos**, quase todo mundo no mesmo
  lugar. Graduar prêmio ali daria a mesma nota para todos; ele entrou como
  **piso** (penaliza só quem está muito abaixo), não como gradação. É a mesma
  família da "coluna que repete o mesmo valor em todas as linhas". O cartão
  ordena os indicadores por amplitude interquartil justamente para essa
  decisão ser visível.
- **Nota do fornecedor não é régua até que se prove.** Seis dos 14 indicadores
  vieram com `score` **0 em 108 de 108 veículos**. Nota que zera a frota
  inteira não separa ninguém e não se explica a quem perdeu o prêmio. A régua
  é NOSSA (`api/premiacao/conducao.py`), linear entre alvo e teto, e é
  parâmetro da versão — a deles fica ao lado, e a tela **avisa** quando está
  zerada em todos, senão parece desempenho ruim generalizado.

**API que IGNORA a janela pedida (lição do monitor de comunicação):**
- `/api/v2/positions` devolve as **últimas 20 posições de cada veículo** e
  ignora `startDate`/`endDate` — janelas de 2 e de 7 dias devolveram
  exatamente os mesmos 1.960 pontos. Descoberto porque as duas chamadas
  levaram o mesmo tempo e trouxeram o mesmo total; se eu tivesse pedido só uma
  janela, teria concluído que a janela funcionava.
- A consequência é de PRODUTO, não técnica: dá para dizer "está calado há 38 h"
  de quem aparece, e **não dá** para dizer há quanto tempo sumiu quem não
  aparece. Esses saem num grupo próprio — "sem posição" — em vez de virar um
  número grande de horas que a fonte nunca afirmou. **Inventar o número seria
  afirmar o que a fonte não disse.**
- E o denominador, de novo: só entra quem **tem equipamento** (aparece no cache
  de `vehicle-statistics` da competência). Na estreia: 100 com equipamento, 95
  em dia, 5 a olhar. Com a frota inteira no denominador o mesmo fato viraria
  um percentual assustador e falso.

**Cadência diferente exige limiar diferente na Saúde:** os indicadores de
condução são uma chamada POR PLACA e rodam 1×/dia; estatística e odômetro são
uma chamada e rodam de 3 em 3 h. Metê-los na mesma lista faria o alarme (duas
janelas de 3 h) acender **todo dia** com tudo funcionando — daí
`COLECOES_DIARIAS` e o limiar de 30 h separados.

**IDENTIDADE DE VEÍCULO: a chave é a PLACA, o que se mostra são as duas.**
- O CÓRTEX estava dividido — custos, pneus e manutenção chaveavam por
  `numerofrota`; telemetria, premiação e tudo que vem da Gobrax, por `placa`.
  E várias consultas faziam `coalesce(numerofrota, placa)`, que é **o pior dos
  dois**: a chave muda de natureza conforme o cadastro esteja preenchido, e
  ninguém percebe olhando a tela.
- **Campo preenchido não é campo útil, e a diferença aqui é de 2x.**
  `numerofrota` está preenchido em 1.857 de 1.973 (94%) — mas em **947 deles o
  valor É A PRÓPRIA PLACA**, copiada no campo. A cobertura real é **46%**:
  99,8% da frota própria, 93,7% dos agregados e **4,2% dos terceiros** (45 de
  1.084). Faz sentido — a Sulista numera o que é dela; cadastro de terceiro vem
  de fora. **Antes de chamar um campo de "cobertura", conferir o que está
  dentro dele.**
- Daí `rotulo()` mostrar só a placa quando `frota == placa`: `AAW7D10 ·
  AAW7D10` além de absurdo faria metade da frota **parecer** ter número.
- **Um De-Para (`api/frota_identidade.py`), não `frota` em 132 consultas.** A
  varredura seria enorme, arriscada, e ainda deixaria de fora as telas
  alimentadas pela Gobrax, que só conhece placa. O mapa é ~1.900 linhas de dois
  campos, carregado uma vez por sessão e memoizado. Falha de carga degrada para
  a placa sozinha — que é o que a tela mostrava antes.
- **O detector de duplicidade diagnostica, e é ele que dá valor ao cartão.**
  Placa Mercosul troca o **5º** caractere (índice 4) de dígito por letra:
  `JOK3003` → `JOK3H03`. Errar o índice devolve a hipótese genérica justamente
  nos casos que tinham algo a dizer — 7 dos 10 repetidos são desse tipo. E o
  achado mais valioso é o que NÃO é Mercosul: `BBY2F64` × `BYY2F64` diferem
  numa letra, ou seja **uma das placas não existe** e tudo lançado nela some.
- Nada é desempatado em silêncio: o cartão MOSTRA com a evidência ao lado
  (as duas placas que dividem o número) e diz que a leitura é **hipótese, não
  veredito** — quem encerra cadastro é quem o mantém. Mesma regra do plano de
  manutenção com marcador furado.

**SERIALIZAÇÃO ESTOURA DEPOIS DO `try/except` DA ROTA** (custou um dia de
Premiação fora do ar, 30/08/2026):
- `prem_ocorrencia_classe.peso` é `numeric`, o psycopg devolve `Decimal` e o
  `json` não o serializa. O que torna isso traiçoeiro não é o tipo — é ONDE
  estoura: `JSONResponse` só serializa quando o Starlette chama `render()`,
  **depois** do `try/except`. A exceção escapa de todo o tratamento e o
  navegador recebe **500 em `text/plain`**, sem uma pista apontando para o
  campo, a tela ou o banco.
- **E a tela ainda mostrava os números da carga anterior ao lado do aviso**, o
  que fazia o defeito parecer problema de conexão. Ficou assim quase um dia.
- Duas defesas, e as duas ficam: converter no **limite do módulo**
  (`float(...)`, `.isoformat()`), que é o certo porque ali o tipo do banco
  para de importar; e o **`JSONResponse` da casa** em `api/main.py`, que é a
  rede embaixo — são ~200 rotas montando dicionário de linha de banco, e
  consertar uma a uma deixa passar a próxima, que é justamente a que ninguém
  vai conseguir diagnosticar.
- A rede **não é despejo**: tipo desconhecido continua estourando, com
  mensagem dizendo que o conserto é no módulo que LEU o dado.
- **Diagnóstico:** ao ver 500 em `text/plain` com a rota parecendo correta,
  suspeitar de serialização antes do código da rota. E chamar a função da rota
  direto num processo novo, lendo `r.body` — é o `render()` que estoura, então
  é ele que o teste tem de fazer.

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

**`versoes.yaml` quebrado derruba TELA, não só o changelog:**
- Uma nota de versão com aspas e barra invertida no meio do texto partiu o
  escalar YAML e **24 testes caíram de uma vez** — tudo que lê o arquivo, a
  tela de Documentação inclusive. O sintoma não aponta para o YAML: aponta
  para as telas.
- **`gerar_changelog.py` passou sem reclamar.** Ele não é validador; regenerar
  o CHANGELOG não prova que o YAML está são.
- Regra: depois de editar `versoes.yaml` à mão, **carregar o arquivo**
  (`yaml.safe_load`) e conferir a contagem de versões e o topo. São duas
  linhas e pegam na hora.
- E o motivo pelo qual isso aconteceu vale guardar: eu estava DOCUMENTANDO um
  erro de corte, e o texto sobre o marcador (`"
function "`) era exatamente
  o que o YAML não aceita. Texto técnico em nota de versão é onde mora esse
  risco — prefira descrever em palavras a colar o literal.

**Conferência que passa por VACUIDADE é pior que não ter conferência:**
- Ao ligar as três receitas ao conferidor (30/08/2026) li os campos de
  `get_overview()` — que é o painel **financeiro** e não tem nenhum deles.
  Todos vieram `None`, o atingimento comparou `"0,0%"` com `"0,0%"` e o bloco
  ficou **verde sem medir nada**. Os recortes vivem em `get_visao_geral()`.
- É a terceira vez que essa família aparece nesta casa: o dublê otimista do
  WhatsApp, o teste da Visão Geral que "não baixa a biblioteca", e agora esta.
  **Antes de confiar num verde, confirmar que ele chegaria a ficar vermelho** —
  sabotar o alvo e ver o teste falhar leva trinta segundos.
- A defesa que ficou: campo ausente vira **achado**, não silêncio. Vale para
  todo verificador — conferidor que se cala dá a sensação de que está tudo
  conferido, e a primeira versão deste já tinha perdido o bloco da DRE inteiro
  por ler um campo que não existia.

**CORTE POR MARCADOR: o fim é DERIVADO, e o que saiu é CONFERIDO** (errei 3x
num dia):
- Cortar de um marcador de início até um marcador de fim escolhido a olho já
  apagou, nesta casa: **20 rotas alheias** do `main.py` (entre
  `/jornada/painel` e `/jornada/raster` havia 450 linhas de outras vinte),
  o **`loadHc`** e o **`loadMvb`**.
- O último foi o mais instrutivo: o marcador de fim era `"
function "` e a
  função seguinte era `async function loadMvb` — que **não casa**. O corte
  passou por cima dela e foi parar na próxima. Marcador de fim escrito à mão
  erra silenciosamente; regex que cobre as duas formas
  (`^(?:async )?function `) acerta.
- **Duas defesas, e as duas são baratas:** (1) o fim vem de uma BUSCA a partir
  do início, nunca de uma string escolhida; (2) depois de todo corte grande,
  comparar as DECLARAÇÕES do arquivo contra as de antes e exigir
  `sumiram: nenhuma`. Foi essa conferência que pegou os três.
- **A conferência tem de olhar TODA declaração de topo, não só `function` —
  e esse foi o quarto erro, o único que a peneira antiga deixou passar.**
  A regex era `^(?:async )?function (\w+)`, e o que sumiu foram NOVE `const`
  (`fmtKm`, `fmtRsKm`, `TELCON_SIT`, `UT_LBL`, `utLbl`, `MOD_COR`, `fmtL`,
  `fmtKmL`, `compLabel`): eles moravam na CAUDA da região cortada, entre o
  `}` da função e a próxima `function`. Três cortes diferentes os comeram e os
  três disseram `sumiram: nenhuma`. A regex certa é
  `^(?:async function|function|const|let|var|class)\s+(\w+)`, e a comparação
  é contra o **HEAD do git**, não contra o estado de antes de cada corte —
  assim uma perda escapada num corte anterior ainda aparece.
- **E o sintoma não aponta para o corte.** A tela da ANTT abria com os cinco
  KPIs certos e a TABELA VAZIA, sem uma linha no console: o `ReferenceError`
  de `fmtKm` acontecia dentro do `try/catch` do loader e virava banner. Três
  suítes distantes (ANTT, multas, telemetria) caíram juntas, e nenhuma delas
  fala de gráfico. **Suíte inteira depois de mexida ampla, sempre** — foram
  esses 9 testes que denunciaram, não o `node --check`, que passa (o código
  continua sintaticamente válido), nem o render dos gráficos, que estava certo.
- O `git diff --stat` também denuncia: 479 linhas removidas quando se esperava
  30 é a pista mais óbvia que existe, e ela aparece antes de qualquer teste.

**TRÊS TELAS QUEBRADAS POR MESES POR UMA LINHA PERDIDA (30/08/2026):**
Um corte da conversão para ECharts (v0.144.0) levou `let leafletPromise=null,
torreMap=null, torreLayer=null;`. Ficaram sem funcionar o **mapa da Torre de
Controle**, a tabela da **DRE por Cliente** (`DRECLI_LINHAS`) e a composição do
**Make vs Buy** (`MVB_COMP_LBL`) — descobertos só quando o usuário reclamou do
mapa.
- **O sintoma é mudo.** `ensureLeaflet` LÊ `leafletPromise` na primeira linha;
  ler nome não declarado é `ReferenceError`, que estoura dentro do `try` de
  `torreMapa`, e o `catch` escreve a mensagem NO PRÓPRIO QUADRO DO MAPA. O
  resultado é um retângulo cinza com "leafletPromise is not defined" em letra
  miúda — que se lê como "hoje não carregou".
- **A assimetria que dificultou o rastreio:** das TRÊS variáveis perdidas na
  mesma linha, só uma deu erro. `torreMap` e `torreLayer` são apenas
  ATRIBUÍDOS, e atribuir a nome não declarado cria **global implícita** —
  funciona. Só a LEITURA estoura.
- **O Leaflet vinha de CDN (unpkg), e isso impedia o teste que teria pegado.**
  Sem ele carregar offline, nenhum teste podia provar que o mapa abre. Foi
  vendorizado (`/static/vendor/leaflet/`), como o ECharts e pela mesma regra —
  e o ganho de testabilidade veio junto com o de não depender de host externo.
- **ANALISADOR DE ESCOPO POR REGEX NÃO FECHA.** Tentei um varredor genérico
  ("todo identificador lido tem de estar declarado"): **1.939 achados**.
  Estreitado só para constantes em CAIXA ALTA, ainda **102** — siglas de
  comentário (API, ERP, CKM), hexadecimais de cor, palavras em português.
  Templates aninhados, `//` dentro de URL em string e destruturação derrubam
  qualquer heurística. **Relatório com falso positivo é relatório desligado**,
  e aí não sobra guarda nenhuma. O que ficou: uma LISTA dos nomes que já se
  perderam (estreita, não erra), o teste de comportamento do mapa, e a regra
  de comparar declarações contra o HEAD do git depois de todo corte — que é a
  que pega o caso geral, e cuja ausência criou este parágrafo.

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

**Dois armazéns do mesmo parâmetro concordam por coincidência (lição da Premiação):**
- A premiação guardava `valor_por_km`, `nota_minima` e `km_minimo` em DOIS
  lugares: `data/premiacao_params.json` (o antigo) e `prem_versoes` (o
  versionado por competência, de 0.146.0). Mesmas chaves, mesmos padrões — e o
  cálculo lia o arquivo. **A tela de configuração salvava, dizia "salvo", e o
  prêmio não mudava um centavo.** Enquanto ninguém editasse nada os dois
  concordavam e o defeito era invisível; o primeiro a mexer descobriria.
- Formulário que diz "salvo" e não altera nada é pior que formulário que falta:
  o segundo se percebe, o primeiro não. Ao encontrar dois armazéns da mesma
  coisa, um deles SAI — junto com a rota que escrevia nele. O antigo ficou só
  como fallback de LEITURA para quando o banco local estiver fora.
- **Parâmetro que decide pagamento é lido POR COMPETÊNCIA.** `serie()`
  recalculava todo mês passado com o valor de hoje: subir o valor por km em
  setembro reescreveria o prêmio de março, que já foi pago com outro. O
  snapshot guarda QUEM ganhou; a versão guarda COM QUE REGRA.

**Coleta vazia gravada como completa se esconde atrás da própria trava:**
- Cinco meses (fev–jun/26) apareciam com ZERO na premiação. A Gobrax tinha os
  cinco inteiros: em disco havia snapshots com `drivers: []` e `parcial:
  false`, escritos por um backfill de 27/07. E o snapshot vazio **bloqueava a
  recoleta**, porque a trava só olha se o arquivo existe — o mês estava
  "coletado".
- O guard existia PELA METADE: protegia quem já tinha snapshot bom e deixava
  passar o mês nunca coletado, que é exatamente o caso do backfill. Regra:
  coleta vazia nunca vira snapshot, **nem por cima de um bom, nem no lugar do
  que não existe**; e a tela DIZ que não veio nada, em vez de mostrar zero.
- Recoletar é remediar. A pergunta que vale é por que um vazio foi gravado
  como completo — o mesmo formato do marcador de manutenção parado em 77.534
  km e da RasterJOR 136 dias fora do ar.

**Duas séries de escalas diferentes, agora em barras agrupadas (Premiação):**
- "Prêmio total (R$)" e "Motoristas premiados" dividiam o eixo: R$ 14.864 e 43
  fazem a segunda barra ter **0,3% da altura** — um tracinho no zero em todos
  os meses. Premiados virou LINHA em eixo secundário, com rótulo direto.
- E o total **não é comparável entre meses**: ele sobe de R$ 402 para R$ 14.864
  principalmente porque a frota na Gobrax foi de **8 para 67 motoristas**. O
  card carrega o denominador e o prêmio POR MOTORISTA, e diz por escrito
  quanto da alta é cobertura. Mesma família da cobertura mensal da jornada.

**Sub-abas dentro de uma tela: quem tem gráfico abre visível.**
- A Premiação tinha seis cards de assuntos diferentes; os três de CONFIGURAÇÃO
  são mexidos uma vez por trimestre e ficavam entre o que se olha todo mês.
  Sub-aba (`.subtabs`), e não tela nova, porque o RBAC, o seletor de mês e o
  botão de coleta são os mesmos — duas telas dividiriam um estado que é um só.
- **A aba com GRÁFICO é a que nasce aberta.** O ECharts mede o contêiner uma
  vez, no `init`, e medida feita sob `hidden` vale zero para sempre. O
  `ResizeObserver` do `echartsRegistrar` cobre a volta, mas começar visível
  dispensa a correção. Aba de formulário e tabela pode começar escondida.

**"Certificado autoassinado" pode ser RAIZ FALTANDO — e mandou procurar
proxy onde não havia nenhum (30/08/2026):**
- `api.tomtom.com` recusava com `[SSL: CERTIFICATE_VERIFY_FAILED] self-signed
  certificate in certificate chain`. O certificado é **legítimo**, da
  IdenTrust/HydrantID. O que faltava era a RAIZ no armazém — e como toda raiz é
  autoassinada, o topo da cadeia aparece como "autoassinado não confiável".
- **`ssl.create_default_context()` neste servidor carrega 45 CAs.** Não são 45
  escolhidas: é o que o armazém do Windows tinha em CACHE. O Windows preenche
  esse armazém sob demanda, e um serviço rodando como SISTEMA, sem sessão
  interativa, pode nunca disparar a atualização. Com `certifi` são **118**.
- **Não era problema da TomTom.** Gobrax, Z-API, Monkey, Prolog, RasterJOR,
  ANTT e Ollama saem todos por `urllib`; os que funcionam funcionam porque a
  raiz deles CALHOU de estar entre as 45. Todos passaram a usar
  `api/tls.contexto()`, e a Saúde MOSTRA o número de raízes — é a primeira
  pergunta de qualquer erro de certificado.
- Levei três diagnósticos até imprimir o EMISSOR do certificado. A mensagem do
  Python aponta para a hipótese errada; o que resolve é olhar quem assinou.

**TomTom — o que foi MEDIDO, não lido na documentação (30/08/2026):**
- **`pt-BR` é RECUSADO** (HTTP 400, "Unsupported language parameter value"), e
  `pt` também. O único português aceito é **`pt-PT`**. O valor óbvio é o
  errado, então é constante nomeada (`cliente.IDIOMA`).
- **`travelMode=truck` FUNCIONA** nesta conta, e muda o número: Joinville →
  Curitiba deu 2h00 de carro e **2h16 de caminhão** nos mesmos 132,6 km. Usar a
  rota de carro como ETA de caminhão erraria 16 minutos numa viagem de duas
  horas — e ignoraria restrição de via, altura e peso.
- **O TETO EXISTE E APARECE DE DUAS FORMAS — nenhuma delas em cabeçalho.**
  Registrei primeiro que "o limite não é observável", olhando só os cabeçalhos.
  Estava incompleto: (1) **HTTP 429** quando se passa do RITMO, e ele é **por
  família de endpoint** — medido, o Routing recusa a partir de ~6 req/s e o
  Traffic aguenta ~14; com os 8 trabalhadores do fluxo, 15 de 47 chamadas de
  ETA se perderam. (2) **HTTP 403 `InsufficientFunds`** quando o recurso não
  está coberto pelo plano — o `reverseGeocode` responde isso enquanto geocode,
  POI e routing passam na mesma rodada. Ou seja há CRÉDITO por recurso, e ele
  só se descobre chamando.
- 30 chamadas EM SÉRIE não batem em limite nenhum: não é cota por volume, é
  ritmo — e por isso a defesa é `min(trabalhadores)` e uma retentativa, não
  menos dado.
- Tempo de resposta: **0,54 s** o fluxo, **0,89 s** a rota.
- **194 incidentes** na caixa Joinville–Curitiba, e **173 (89%) de UMA
  categoria** ("via fechada"), quase todos fechamento de rua com `delay: null`.
  Contar o total seria verdadeiro e inútil; anunciar "173 estradas fechadas"
  seria alarmante e errado. O recorte que decide é o que está EM RODOVIA.
- **A chave do mapa vai para o NAVEGADOR** (o Leaflet baixa os tiles direto), e
  a defesa é restringi-la por domínio — mas **chave restrita por domínio não
  funciona chamada pelo servidor**: volta 403, que se lê como "chave errada".
  Daí `TOMTOM_API_KEY_SERVIDOR`, opcional, e a Saúde avisando ANTES do 403.
- **A chave vai na URL**, como na Z-API: `_sanitizar` varre as duas chaves E
  mascara qualquer `key=` — inclusive uma que este processo não conheça, que é
  justamente o vazamento que ninguém previu.
- A TomTom mede **FLUXO, não pavimento**. Não há aqui estimativa de "condição
  da estrada" derivada de velocidade: seria afirmar o que a fonte não disse.

**A POSIÇÃO DO VEÍCULO: o ERP não era o plano B, era a maior cobertura**
(medido em 30/08/2026, pedido do usuário para usar o rastreamento do sistema
como reforço da Gobrax):
```
só na Gobrax ....   1 placa      nas duas ....  97
só no ERP ...... 177 placas      união ....... 275
```
- E o **frescor EMPATA**: nas 97 que aparecem nas duas, a idade mediana é 5 min
  na Gobrax e 4 min no ERP, com a Gobrax mais recente em 44% dos casos. São
  caminhos diferentes para o mesmo mundo — a Gobrax lê o equipamento dela; o
  ERP recebe do hub da Raster, que agrega ONIXSAT, SASCAR, POSITRON e OMNILINK.
- Por isso `api/posicoes.py` faz vencer a **leitura mais recente**, e não uma
  fonte fixa: precedência por Gobrax descartaria a posição mais nova em 56% das
  placas comuns **sem ganhar cobertura nenhuma**. `preferir="gobrax"` existe
  para quem quiser a precedência literal.
- **Toda posição diz de onde veio e que idade tem.** Com a Gobrax fora, o total
  quase não muda (o ERP cobre 274 de 275) — e é só a linha de procedência que
  denuncia. Sem ela, uma integração morre em silêncio.
- `gobrax/comunicacao.coletar` JOGA LAT/LON FORA de propósito (ele responde "há
  quanto tempo esta placa não comunica"). Reusá-lo para posição traria placa e
  hora sem coordenada — não é duplicação ter um leitor próprio.

**TomTom, condição da estrada — o ZOOM era um defeito de MEDIDA:**
- Primeira varredura da frota: 5 "problemas", sendo **4 falsos "via
  bloqueada"** — com os caminhões ANDANDO a 28–30 km/h numa via marcada como
  fechada. O que não fechava era isso: veículo em movimento em estrada fechada.
- A causa é o `zoom`, que define o TAMANHO DO TRECHO agregado. No mesmo ponto:
  `zoom 10` → trecho de **1.293 s (~21 min de estrada)**, 766 pontos, 30/38
  km/h, `roadClosure: true`; `zoom 14` → trecho de **112 s (~2 min)**, 45
  pontos, 27/27 km/h, `roadClosure: false`. Em zoom baixo a leitura HERDAVA um
  bloqueio que estava a dezenas de quilômetros.
- **E o zoom alto não esconde problema:** o congestionamento real (23 km/h onde
  o livre é 80) aparece IGUAL em todos os zooms. Depois da correção, a frota
  saiu de 7,2% para 2,9% com trânsito ruim, sem nenhum bloqueado falso.
- **A pergunta é a RAZÃO, não a velocidade**: 40 km/h é bom numa serra e
  péssimo numa reta. `confidence` abaixo de 0,5 vira **n/d**, nunca verde nem
  vermelho — a própria API está dizendo que não sabe.
- O recorte é **em viagem** (69 de 275): consultar a frota parada seria 4x o
  custo para perguntar sobre estrada que não existe.
- **O limite do plano NÃO É OBSERVÁVEL** (nenhum cabeçalho de cota nas três
  famílias de endpoint). Sem poder ver o teto, conta-se o GASTO: `tt_chamadas`,
  por dia e recurso, com o número na Saúde. E a cadência é **sob demanda com
  TTL de 10 min**, não tarefa agendada — agendada, o custo é constante mesmo no
  domingo em que ninguém abre a tela.
- **Fonte nova no snapshot do Copiloto não pode disparar coleta** (`so_cache`):
  seriam ~70 chamadas externas a cada abertura do chat. Mesma trava do `force`
  da premiação.

**Diárias: o campo que parece quantidade e vem ZERADO (30/08/2026):**
- A folha (`sulista.diariaspagas_globus`, no AVA) tem a coluna `referencia`,
  que em folha costuma ser a QUANTIDADE. Aqui ela é **0,00 em 4.833 de 4.833
  lançamentos**. Mesma família do "mão de obra R$ 0 com 747 OSs": campo que
  existe, parece número e não é. Consequência dita na tela: **dá para saber
  quanto se pagou, não quantas diárias foram**.
- A única fonte que tinha a diária POR DIA — `sulista.integracao_diarias_
  rasterjor`, com tipo (Meia R$ 52,64 / Inteira R$ 102,58) e cidade-base —
  **parou em 12/02/2026**. Seis meses e meio, o mesmo formato da RasterJOR que
  ficou 136 dias fora. A tela diz a DATA, não "faz tempo".
- **A competência da FOLHA não é a data do TRABALHO.** A mediana de R$/dia dá
  R$ 132 contra uma inteira de R$ 102,58, e deslocar um ou dois meses não
  conserta (R$ 137 e R$ 123) — não é defasagem limpa que dê para corrigir.
  Então a razão é **ordem de grandeza**, útil para comparar motoristas ENTRE SI
  na mesma janela, onde a distorção é a mesma para todos. Isso está no ⓘ.
- **O total sozinho engana:** caiu 80% (R$ 466 mil → R$ 91 mil) enquanto os
  motoristas com jornada caíam de 127 para 79. O que compara é por pessoa.
- **O achado que não depende de razão nenhuma é a reconciliação:** 24 pessoas
  com diária e ZERO dia de jornada (R$ 238.847), **todas com cargo de
  motorista** — carreteiro, truck, instrutor, não é escritório viajando. E 83
  com jornada e sem diária. São perguntas para quem opera, não veredito.
- **O cruzamento é em PYTHON**: a folha está no AVA e a jornada no Postgres
  local, então não há `JOIN`. A chave é o NOME normalizado (sem acento,
  maiúscula, espaço simples) porque matrícula e documento não conversam —
  120 dos 134 casam.

**Teste que recorta HTML por DESLOCAMENTO FIXO mente nas duas direções:**
- O helper de `test_abas_bi.py` pegava o corpo de uma aba do `<div class="aba">`
  até a próxima — e, quando a aba era a ÚLTIMA do grupo, caía num
  `resto[:20000]`: vinte mil caracteres adiante, **atravessando o `</section>`**
  e lendo a marcação das telas seguintes.
- Enquanto havia dois grupos de aba, passava por sorte. Com 31, o mesmo defeito
  produziu **falso positivo** (acusou o `antport` de pôr gráfico em aba
  escondida, sendo que ele não tem gráfico nenhum) **e falso negativo** (deixou
  passar o `drecli`, que tinha o problema de verdade). Uma causa, os dois erros.
- E o `orc` só apareceu depois: **consertar a MEDIÇÃO revelou duas violações
  reais**, enquanto calibrar o limiar teria escondido as duas.
- A regra: o fim de um recorte é DERIVADO de um limite real (aqui, o
  `</section>`), nunca de um número escolhido para "dar folga". Folga arbitrária
  não é margem de segurança — é a fronteira do que se mede indo parar em cima
  do vizinho. É a mesma família do corte por marcador que já comeu 20 rotas
  alheias neste arquivo.

**Conferência de CSS: leia o CSSOM, não o texto (30/08/2026):**
- Escrevi três versões de um guard contra "fundo claro sem versão escura", e as
  duas primeiras devolviam **ZERO com o defeito reposto de propósito**. Nenhuma
  dava erro. Só a sabotagem separou a que funciona.
- O que derrubou cada uma: (1) parser por regex sobre o `<style>` — falhava até
  num CSS sintético de cinco linhas, foi descartado em vez de dar falso verde;
  (2) `CSSRuleList` **não é iterável com `for...of`** no Chrome, e o `try/catch`
  de fora engolia — hoje é `Array.from` e um contador `lidas` faz a sonda gritar
  "não li regra nenhuma" em vez de reportar zero; (3) **`CSSStyleRule` também
  tem `cssRules`** desde o CSS aninhado — vazio, mas TRUTHY, então
  `if(r.cssRules) continue` pulava as 1.003 regras do arquivo.
- E o CSSOM **normaliza**: `background:#fff` volta como `rgb(255, 255, 255)`.
  Procurar hexadecimal na saída do navegador não acha nada.
- O efeito colateral é conveniente: regra com `var(--…)` deixa o longhand
  `backgroundColor` VAZIO, então quem usa token some da varredura sozinho —
  que é exatamente o certo.
- Vale para qualquer conferência de estilo: quem já separou `@media`, resolveu
  `@import` e sabe o que é seletor é o motor que renderiza. Reimplementar isso
  com regex é reimplementar um parser de CSS por engano.

**"Modo caminhão" não é perfil de caminhão (TomTom, 30/08/2026):**
- O ETA mandava só `travelMode=truck`. Medido nos quatro trechos reais da
  operação, o perfil COMPLETO (40 t, 6 eixos, 18,6 m, 4,40 m) dá **5 a 28
  minutos a mais**: Joinville→Curitiba +5, →São Paulo +20, Curitiba→Pouso
  Alegre +15, Joinville→Betim +28. O modo sozinho ajusta o ritmo; o perfil muda
  a ROTA — ponte, altura, peso por eixo.
- O limiar de "chegada apertada" da Torre é **15 minutos**. Um erro sistemático
  de 5 a 28 cai justamente no lado que faz a torre NÃO avisar.
- O perfil é FIXO, e isso é escolha declarada: num caminhão menor ele erra para
  a chegada MAIS TARDE, que é o erro seguro num painel de risco de atraso. A
  tela diz que usa a carreta padrão.
- **O contador de consumo media a COLETA, não o consumo.** Contava como chamada
  a viagem já VENCIDA (que sai sem perguntar nada, de propósito) e a sem
  coordenada no ERP; e somava "a TomTom recusou" com "o cadastro está
  incompleto" no mesmo `erros`. Eram 295 chamadas com 33 erros num dia em que
  boa parte nem tocou na API. Hoje `chamadas`, `erros_api` e `sem_cadastro` são
  três números, porque são três consertos em lugares diferentes.
- **O que a chave LIBERA, sondado um a um:** rota com perfil de veículo ✓,
  `calculateReachableRange` ✓ (isócrona — até onde o caminhão chega em N horas,
  polígono de 50 vértices), busca de POI por proximidade ✓ (posto a 199 m em
  Joinville), fluxo e incidentes ✓. **`reverseGeocode` NÃO**: devolve
  `403 InsufficientFunds` neste plano — o direto funciona, o reverso não.
  Alcance e POI ficam disponíveis e não construídos; a decisão é de produto.

**Regra que protege de um erro pode esconder o número que decide (Antecipação):**
- A tela só antecipava título JÁ LANÇADO num portal, provado pela planilha
  importada. A regra está certa — sem o arquivo o banco recusa na mesa —, mas
  ela respondia a pergunta errada: dos **R$ 16,6 mi** a receber em 90 dias,
  entravam **R$ 594 mil (3,6%)**, enquanto **R$ 8,2 mi eram de cliente COM
  convênio assinado** (TUPY, MWM-Tupy, Iochpe Maxion, Adient). Quem pergunta
  "quanto dá para antecipar" quer saber dos 8,2; o caminho dos que faltam é
  **pedir o arquivo**, não negociar convênio.
- **A classificação continua sendo feita nos dois modos; o que o seletor muda é
  se ela EXCLUI.** Contar "falta planilha" só no modo estrito faria o número
  sumir justamente no modo em que ele vira a próxima ação.
- Cada operação diz, **por cliente**, quantos documentos ainda não estão no
  portal e **quanto eles somam** — é o par que vira telefonema. Só a contagem
  não diz se vale a ligação.
- Convênio continua obrigatório nos DOIS modos: afrouxar as duas travas de uma
  vez trocaria um erro por outro.
- **Adicionar o cliente como elegível não bastava, e esse era o sintoma.** Os
  três já estavam em `ant_sacados` com `origem='manual'` e nada mudava na tela
  — a segunda trava, invisível no cadastro, era quem barrava.

**A REGRA DE UMA TELA, APLICADA ÀS 68 (30/08/2026) — e o que a medição ensinou:**
- 23 telas foram divididas em sub-abas de uma vez. As mais altas: Saúde 1.457px,
  Milk run 1.408, Torre 1.356, Fluxo de caixa 1.308. Hoje **nenhuma** das 68
  passa da régua, e `scripts/medir_paineis.py` é quem diz.
- **TER ABA NÃO É CUMPRIR A REGRA, e a primeira versão do medidor deixou
  passar.** Ele dava "JÁ TEM ABA" como aprovação — mas quem se lê é a aba
  ABERTA, e dividir 1.400px numa aba de 1.300 e outra de 100 não resolveu nada.
  O medidor clica em CADA aba e vale a mais alta.
- **O medidor cobrava 98px de um banner que só existe na bancada.** A API ali é
  dublada e devolve `{}`, então toda tela abre com o banner de erro; ele entrava
  na altura das 68 e mandava dividir tela que já cabia (a Torre "1.015" era
  903). Banner é estado de EXCEÇÃO, não o estado em que a tela é lida.
- **Painel de TV tem outra régua e NÃO leva aba.** Roda em tela cheia (não há
  barra de navegador a descontar) e sobretudo **ninguém clica numa TV** —
  dividir em aba um painel que ninguém opera esconde metade do que ele existe
  para mostrar. Pela mesma razão a tabela dele não é "solta": quem a limita é o
  RENDERIZADOR (`slice(0,10)`), e rolagem dentro do card seria inútil ali.
- **O LEAFLET TAMBÉM MEDE UMA VEZ**, e a aba escondida mede zero — a armadilha
  do ECharts, com sintoma pior: tiles cinza em volta de um pedacinho desenhado,
  sem erro nenhum. O `ResizeObserver` do `echartsRegistrar` **não alcança
  mapa**. Daí `mapasRemedir()` no `abaTrocar`, com rAF DUPLO — `hidden=false` só
  vira layout no quadro seguinte, e invalidar antes do reflow remede o zero.
- **O contador de aba é AUTOMÁTICO** (`abaContadoresAuto`, via
  `MutationObserver`): fiá-lo em cada loader seria escrever a mesma linha vinte
  vezes e esquecê-la na vigésima primeira. Ele conta as linhas que a tela
  desenhou e **ignora a linha de estado vazio** (`<td colspan>`) — contá-la
  faria toda aba vazia mostrar "1", que é pior que não ter contador.
- **O corte é ESTRUTURAL** (`scripts/dividir_em_abas.py`): os blocos de primeiro
  nível saem de contagem de `<div>`, nunca de string escolhida a olho. Três
  conferências rodam sempre — as declarações do arquivo inteiro, os `<h2>` e os
  `id=` da tela. **A do `id` é a que pega o erro que não dá erro:** card que some
  leva o id que o loader preenche, e a tela carrega calada, sem metade dos
  números.
- **`desfazer()` existe porque REBALANCEAR é o caso normal.** A primeira divisão
  quase nunca acerta a altura de cada aba; sem achatar antes, a segunda
  tentativa aninha aba dentro de aba, que é o jeito de perder um card sem
  ninguém ver.
- Quando não sobra costura para mais uma aba (5 telas ficaram entre 903 e
  935px), o que cede é a ALTURA DO GRÁFICO: 30 a 50px num gráfico de 250 não
  mudam a leitura dele, e obrigar um clique para ver o card vizinho da mesma
  pergunta mudaria.
- **O medidor dava CRÉDITO DE ALTURA para tela com mais `tabroll` que tabela.**
  A conta era `tabelas - tabroll` e ficava NEGATIVA quando um wrapper com
  `.tabroll` não envolvia tabela nenhuma; multiplicada por 400, virava desconto.
  Foi assim que `hc` (1.030px) e `orc` (966) passaram como "cabe" — e quem os
  encontrou foi o teste novo, que mede altura crua. `max(0, …)`.
- **A BANDA DE KPI VAI PARA DENTRO DA ABA A QUE ELA PERTENCE.** No Custo de
  Folha as duas bandas ficavam fora e custavam ~200px em TODA aba, inclusive
  nas que não leem nenhuma delas. E havia um segundo motivo, melhor: a banda da
  Estrutura ao lado dos números de Competência convidava a comparar dois
  recortes que diferem, de propósito, em R$ 4 milhões.
- **Sistema de aba PRÓPRIO numa tela é uma discordância esperando.** O Orçamento
  tinha o dele (`orcTab` + `ORC_ABA`), anterior ao `.subtabs`: o giro
  automático, o contador e o `mapasRemedir` não valiam ali, e ninguém repararia
  porque a tela *parecia* ter abas. Ele saiu. E `ORC_ABA` era uma variável
  PARALELA ao `hidden` do elemento — duas verdades sobre qual aba está aberta,
  com a cópia decidindo se `renderOrcMontagem()` rodava; hoje o estado é lido do
  DOM.
- **Aba que só renderiza ao abrir declara isso em `data-ao-abrir`**, e não num
  `if` dentro de cada tela. É o gancho genérico que substituiu o `if(aba===…)`
  que cada tela escrevia à mão.

**Folha: "proventos" NÃO é custo — 14% do total só CIRCULA (30/08/2026):**
- A tela somava `tipoeven='P'` e chamava de Custo de Folha. Medido em 12 meses:
  `ADIANTAMENTO DE SALARI` (P) R$ 3.460.109 contra `ADIANTAMENTO QUINZENAL`
  (D) R$ 3.463.158 — a MESMA quinzena, paga adiantada e descontada depois,
  batendo **centavo a centavo em 9 de 13 meses**. Somá-la é contar o salário
  duas vezes. Com `INSUFICIENCIA DE SALDO`, são R$ 4,0 mi, **14,2% do bruto**.
  O custo efetivo é R$ 24,2 mi, não R$ 28,2 mi.
- **O ENCARGO NÃO ESTÁ NA FICHA, só as bases.** FGTS é calculável (8% fixados
  em lei, iguais para todo regime) e entra com a alíquota DITA na tela. **INSS
  patronal não**: a alíquota depende do enquadramento e há eventos de SIMPLES
  na ficha (`BASE IRF S/ SAL SIMPL`), onde o patronal está no DAS. Estimar 20%
  somaria ~R$ 2,8 milhões inventados. A base aparece como base.
- **`.upper()` engoliu o 13º inteiro.** A classificação por natureza jogou
  R$ 3,25 mi em "Outros" — 13,4% do custo, terceiro maior balde — porque
  `_sem_acento` faz `.upper()` e o "o" de "13o" chega como "O", enquanto o
  padrão estava em minúscula. Depois do conserto, "Outros" caiu para **1,1%**.
  Categoria genérica grande é sintoma de classificador furado, não de dado
  variado.
- **"O custo caiu" não decide nada sem a quebra.** A decomposição separa
  `Δpessoas × médio_anterior` de `pessoas × Δmédio`: dos R$ 654 mil de queda
  (ago/25 → ago/26), **R$ 624 mil são gente a menos** (306 → 210) e só R$ 30
  mil são custo médio. Dimensionamento e composição salarial têm donos
  diferentes.
- A comparação prefere o MESMO MÊS do ano anterior: mês contra mês carregaria
  a sazonalidade do 13º, que é estrutural em novembro e dezembro.

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
   **FEITO em 30/08/2026**, e é repetível: `uv run --no-sync python
   scripts/testar_restauracao.py`. O dump de 3,6 MB voltou com as 48 tabelas,
   150.657 linhas, o migrador não achou migration pendente (a prova de que o
   schema restaurado é o que o CÓDIGO espera, e não um schema qualquer que
   carregou sem erro), a API subiu apontada para ele e os seis módulos leram
   pelos caminhos reais. O papel `cortex` ganhou `CREATEDB` para isso — não
   dá acesso a banco nenhum, só permite criar os próprios.
2. **Reconciliação com o ERP documentada** — a divergência de cada número que
   decide dinheiro conhecida, explicada e com dono, em vez de descoberta na
   reunião. **FEITO em 30/08/2026**: `docs/RECONCILIACAO.md` +
   `scripts/conferir_numeros.py`, com **24 conferências** e **nenhuma
   divergência** hoje. Não há linha esperando veredito nem dono — o documento
   não é lista de pendência, é o registro do que se confere e de onde já
   falhou. `tests/reconciliacao/` amarra as duas pontas: a lógica do
   comparador e a COBERTURA (remover uma checagem quebra o teste, senão o
   documento passaria a mentir em silêncio).
3. **As três telas de receita batendo entre si** — faturas emitidas × frete das
   viagens × CT-e+KMM+NFS-e da meta, com o ⓘ de cada uma dizendo por que
   diferem quando diferem. **FEITO em 30/08/2026**: os três são lidos e
   comparados no conferidor. Medido — faturas R$ 11,89 mi · CT-e R$ 11,00 mi ·
   régua da meta R$ 11,34 mi · DRE R$ 11,36 mi, todos dentro de ~8% entre si.
   E o par que fecha (`realizado_acumulado ÷ meta_acumulada`) é conferido
   contra o `atingimento_mes`, junto com o que a mensagem de WhatsApp mostra —
   que é onde o erro de 96% × 91,3% quase saiu para fora da empresa.

**Os três critérios estão cumpridos.** O `1.0.0` deixou de ser dependência
técnica e virou decisão de quem opera.

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
