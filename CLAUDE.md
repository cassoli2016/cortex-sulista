# CÓRTEX — Cérebro de Gestão da Transportadora Sulista

> Portal de inteligência operacional, financeira e estratégica. Frota mista
> (própria + agregados), modalidade predominante lotação (FTL).
> Toda resposta numérica cita a fonte (tabela/query) e o recorte. Nenhum número
> sem origem rastreável entra em decisão.

Este arquivo é o contexto-mestre de qualquer agente de IA que atue no repo.
Ele descreve o estado REAL do sistema e as regras duráveis da casa. A história
completa de cada regra — o que aconteceu, o que foi medido, por que é assim —
vive em **`docs/LICOES.md`** (o arquivo de crônicas). Quando uma regra daqui
parecer arbitrária, a lição está lá.

---

## 1. A árvore de produção (LER ANTES DE QUALQUER COISA)

**A API de produção roda DESTA pasta e deste `.venv`.** O AutoDeploy (tarefa
do Windows, a cada 2 min) puxa `origin/main` contra a ÁRVORE DE TRABALHO e
reinicia a API. Consequências, todas já vividas (crônicas em `docs/LICOES.md`):

- **Commit sem push TRAVA o deploy de todo mundo** (`DIVERGENCIA: local=…`).
  Commit e push andam juntos, no mesmo minuto. Sem perguntar.
- **Arquivo editado sem commit** bloqueia o pull (`Your local changes…`).
  Editar durante a sessão derruba rota no ar.
- **Rebase no meio** deixa marcador de conflito que o `uv sync` do AutoDeploy
  pode importar. `git fetch` ANTES de rebasear, sempre. NUNCA `push --force`.
  **NÃO resolva conflito com `uv run python`**: se o conflito estiver no
  `pyproject.toml` (e ele SEMPRE está, porque toda entrega bumpa a versão), o
  `uv` se recusa a rodar — "TOML parse error… `<<<<<<< HEAD`" — o script de
  resolução não executa, e o `git add` + `--continue` seguintes commitam o
  marcador sem reclamar. Use o `python3` do sistema para resolver, e depois
  `git grep -n '^<<<<<<< HEAD' HEAD` para provar que o COMMIT (não a árvore)
  está limpo. Visto em 02/09/2026, pego antes do push.
- **Topo de versão não regride.** Se a outra sessão publicar uma versão MAIOR
  enquanto você trabalha, renumere a sua para um patch acima da dela
  (0.214.1 → 0.215.1), nunca deixe o topo do `versoes.yaml` cair.
- **O que vai demorar não fica aqui** (suíte de 35 min, módulo grande):
  worktree própria — ver memória `worktree-por-frente`. A suíte completa nesta
  árvore colide com o AutoDeploy por construção (ele desinstala o playwright
  no meio; medido em 31/08: 296 erros por isso, zero regressão real).
- **Duas sessões na mesma árvore se atropelam**: quem empurra primeiro fica com
  o número de versão menor; buraco na sequência é mais barato que topo
  regredindo. Conflito em arquivo compartilhado se resolve LENDO os dois lados,
  nunca com `--ours`.
- `uv sync` sem `--group test` **desinstala** pytest e playwright (correto em
  produção). Local: `uv sync --group test`, ou rode por overlay efêmero
  `uv run --no-sync --with pytest --with playwright==<versão do uv.lock> …`,
  que não toca o venv e é imune à corrida com o AutoDeploy.

---

## 2. Stack real

| Camada | O que é DE VERDADE |
|---|---|
| Borda | Cloudflare Tunnel + Access (zero-trust; o Cloudflare TROCA o corpo de respostas 5xx — ver regra de erro na seção 6) |
| Frontend | **Página única `api/static/index.html`** servida pelo FastAPI — router por hash, RBAC via `auth.TELAS`. Não há `web/`, não há build |
| API | FastAPI + Pydantic, uvicorn, porta 8010 (`scripts/run_api.ps1`) |
| Dados | **Dois PostgreSQL** (abaixo). Sem TimescaleDB, sem pgvector, sem Redis em uso |
| IA | Ollama local (`gemma4`) em `api/copiloto.py`; fallback modelos `:free` do OpenRouter se houver chave. Sem agentes em runtime — o Copiloto é chat sobre snapshot de KPIs escalares |
| Vendor | ECharts 5.6.1 e Leaflet vendorizados em `api/static/vendor/` — **nunca CDN** |
| Observabilidade | Tela Saúde do Servidor (`api/servidor.py`) — psutil, integrações, bases, ACL de segredos |
| Deploy | AutoDeploy do Windows (seção 1) + tarefas agendadas (`scripts/instalar_tarefa_*.ps1`) |

**Atenção ao legado aspiracional:** `docs/ARQUITETURA.md`, `sql/schema.sql`,
`sql/blocks/`, `migrations/versions/`, `docker-compose.yml` e `alembic.ini`
descrevem a arquitetura PLANEJADA original (Next.js, LangGraph, TimescaleDB,
Redis, Prometheus…) — **nunca implementada**. Não usar como referência do
estado atual; as tabelas `fin_*`, `op_*`, `tc_*`, `tel_*` etc. desse schema não
existem no banco vivo.

### Os dois bancos (confundi-los custa caro)

| | Quem é | Como se fala |
|---|---|---|
| **AVA (ERP)** | réplica do ERP legado, **PostgreSQL 9.3, somente leitura**, remota | `api/db.py` · `POSTGRES_*` |
| **CÓRTEX** | o banco da casa, **PostgreSQL 16, onde se escreve**, local, schema `cortex` | `api/pglocal.py` · `CORTEX_PG_*` |

- O AVA é 9.3: **sem `FILTER (WHERE …)`** — agregado condicional é `CASE WHEN`.
  O erro aponta para o meio do agregado, não para a versão.
- `api/db.py` pede `client_encoding` UTF8 (o padrão do libpq no Windows derruba
  a consulta inteira num travessão — `UntranslatableCharacter`).
- **Tabela do ERP não tem contrato de tipo nem chave.** `sulista.agrupadorgerencial`
  (o mapa conta → linha da DRE, mantido à mão pela Contabilidade) foi recriada
  em 02/09/2026 com `grupo` em `varchar` — era `integer` — e as CINCO telas que
  dependem dela (`dre`, `cont`, `orc`, previsão, `custos`) morreram no
  `operator does not exist: character varying = integer`; na mesma leva uma
  conta ganhou DUAS classificações e o `LEFT JOIN` dobrou o lançamento. Toda
  leitura passa por `api/agrupador_gerencial.left_join()` (cast na entrada +
  agregação por `(grupo, reduzido)`); `scripts/conferir_agrupador.py` mede o
  cadastro e os DOIS caminhos do resultado (mapa × estrutural do plano), a
  **Saúde do Servidor** traz a mesma medição num cartão (TTL 300 s), e
  `tests/test_agrupador_gerencial.py` proíbe o join cru. **Dublê tem o tipo que
  nós escrevemos, não o que o ERP grava** — schema de terceiro só se confere no
  banco vivo.

### Módulo novo que escreve

**`api/pglocal.py` TEM POOL** (desde 06/09/2026): `auth.sessao_atual()` roda em
toda requisição autenticada e abrir conexão era 99,7% do custo dela
(24,70 ms → 0,40 ms; 165 ms → 10,5 ms com 60 simultâneas). O `SET search_path`
é refeito A CADA RETIRADA — é ele que impede schema de teste e de produção de
se misturarem numa conexão reusada. **`diagnostico()` fica FORA do pool de
propósito**: a Saúde responde "o banco aceita conexão AGORA?", e pelo pool ela
diria "conectado" com o `max_connections` esgotado. Guard:
`tests/test_pglocal_pool.py`.

Use `api/pglocal.py`, nunca abra SQLite (`tests/test_saude_bases_locais.py`
quebra se `sqlite3.connect` aparecer fora do cache da Gobrax e do conferidor da
Saúde). Tabela com **prefixo do módulo** (`ext_*`, `orc_*`, `crm_*`…); DDL em
migration numerada em `sql/cortex/` aplicada por `scripts/migrar_schema.py`;
o módulo expõe `ESQUEMA` e o teste usa a fixture `esquema_pg`. Detalhes e
armadilhas: `docs/MIGRACAO_POSTGRES.md`.

### O que fica FORA do banco, de propósito

Cache reconstruível (`data/telemetria.db`, `data/pneus/`, `data/premiacao/`,
`data/dre_cliente/`) e segredo em arquivo (`data/credenciais.json`,
`data/email_config.json`, `data/whatsapp_config.json`, os `.pfx`,
`data/certificados/senhas.json`). **Todo lugar que grava segredo chama
`api/segredo_arquivo.proteger()`** — no NTFS quem manda é a ACL (`os.chmod` é
ficção), a remoção de acesso é cirúrgica (só grupo AMPLO sai) e a Saúde **MEDE**
a ACL em vez de afirmar a proteção.

---

## 3. Telas e módulos

**O registro canônico das telas é `api/auth.py`** (`TELAS`, `ROTA_TELAS`,
`VIEW_GROUP` no `index.html`). Hoje: **87 telas em `auth.TELAS`** + 3 fora
(`srv`, `gestao`, `jornf`, que não estão em `TELAS`). Duas das 83 — `sup` e
`apps` — são de TODO usuário logado (`TELAS_TODO_LOGADO`): entram por sessão
além do perfil. Organizadas assim:

| Grupo | Telas | Fonte principal |
|---|---|---|
| Início | home, cop (Copiloto) | snapshot de KPIs |
| Financeiro | fluxo, receber, cob, banc, extb, lanc, antec, antport, rec, fluxcon, pagar | AVA + locais `ext_*`, `ant_*`, `prev_*` |
| Operação | milkrun, agr, mvb, km, prog, torre, jorn, cex, sac, port, pedagio, poli | AVA + `jor_*`, `ped_*`, `tt_*`, posições Gobrax+ERP |
| Comercial | com, clif, crm, drecli | AVA + `crm_*` (banco local) |
| Controladoria | dre, bal, cont, qual, orc, fech, fat | AVA + `orc_*`, `prev_*` |
| Suprimentos | oc, custos, pecas | AVA (`ordemcompra` × vínculo de NF × `aprovador`, estado em `api/suprimentos_oc.py`; preço de peça pela mediana do produto em `api/suprimentos_pecas.py`) |
| Frota | comb, man (+ sub-abas Compras da OS e Recompra de peça), veic, mprev, comrast, veicf, mul, pneus | AVA + `smt_*` (Smartec) + `data/pneus/` + `api/manutencao_compras.py` |
| Telemetria | prem, telcon, telcond, telhod | Gobrax (`api/gobrax/`) + `prem_*` |
| Recursos Humanos | rh, hc, folha, folhaind, cnh, ferias, people, he, freq | AVA (folha/Globus) + ponto (`FRQ_*`) |
| ANTT | anpiso, anrntrc | `config/antt_coeficientes.yaml`, `config/antt_cargas.yaml`, `rntrc_*` |
| Business Intelligence | prodveic, tvfat, tvope, tvdir | AVA (tvdir lê a mesma /api/visao-geral da home) |
| Gestão | gesacao, gesata, gesrit | `ges_*` (banco local) |
| TMS | ctecp, dfe | a frente FISCAL: documento eletrônico direto com a SEFAZ. Emite (`api/contrapartida/`) e recolhe (`api/sefaz/`, `dfe_*`) com o mesmo certificado A1 — quando ele vence, as duas param no mesmo dia |
| Suporte | sup, supfila | `sup_*` no banco local + espelho opcional no GitHub |
| Administração | doc, aud, integ | `index.html` (doc); `aud_*` + `audit_log` (auditoria de uso, `api/auditoria.py`); `integ` junta o cofre de credenciais com os cartões da Saúde (`api/integracoes.py`) |

As tabelas locais vivem em `sql/cortex/` (39 migrations): auth/usuários/fotos,
push, correio, previsão, antecipações, extrato, orçamento, contrapartida,
WhatsApp (`zap_*`), gestão (`ges_*`), jornada RasterJOR (`jor_*`), premiação,
favoritos, TomTom (`tt_*`), CRM (`crm_*`), notificações, Smartec (`smt_*`),
pedágio (`ped_*`), suporte (`sup_*`).

**A unidade de RBAC é a TELA** (perfil × tela via `perfis`/`perfil_telas`,
`sql/cortex/0011_auth.sql`). Não há RLS.

**TELA NOVA TEM ONZE REGISTROS, NÃO UM**: `view-x` no HTML + `VIEWS` +
`auth.TELAS` + `ROTA_TELAS` + `VIEW_GROUP` + drawer do celular + `ICONS` +
índice de busca + `docs/manual.yaml` + **`semFilterbar()`** + **a lista do
`#meta`**. Essa classe de defeito não tem sintoma, só ausência (ícone que some,
tela fora do celular) — **rodar a suíte COMPLETA para tela nova**; os guards
moram em arquivos que não falam do assunto.
- **As duas últimas entraram em 07/09/2026, e a lição é sobre a própria
  lista.** `integ` e `apps` nasceram depois dela e ficaram de fora das duas:
  a barra de filtros aparecia inteira em telas cujas rotas não recebem
  parâmetro NENHUM (dava para preencher filial e data, clicar em "Aplicar
  filtros" e nada mudar — campo que aceita valor e não muda nada é pior que
  campo nenhum, porque quem filtra acredita no resultado), e o carimbo
  "Atualizado HH:MM" do cabeçalho ficava em **"carregando…" para sempre**, que
  se lê como tela travada. Nenhum dos dois tem alarme: o guard que existe
  (`tests/frontend/test_registro_de_tela.py`) confere DUAS telas nomeadas à
  mão, `poli` e `ctecp`, e não varre — lista escrita à mão de novo. **Quem
  esconde a filterbar decide o `#meta` também**, e por lados opostos: tela que
  responde "e agora?" CARIMBA a hora da leitura (`integ`); tela de registro
  estático ESCONDE, porque carimbar sugere um frescor que não existe (`apps`).
- **Tela de todo usuário logado** (`sup`) entra em `TELAS_TODO_LOGADO`
  (`auth.py`): fora do perfil, dentro dos favoritos, da busca e do menu;
  `podeVer` a libera pela sessão. A rota dela vai em `_ROTAS_SEM_TELA`.
- **SUB-ABA não é tela** e não se registra em lugar nenhum (herda RBAC, ícone e
  menu da tela que a contém). A pergunta que separa: o roteador abre por hash?
- **Ao aposentar uma tela, a substituta HERDA o id** (`jorn`, `crm`, `mul`) —
  é RBAC: id novo faria a tela sumir do menu de quem já tinha acesso. Só herda
  quem substitui MESMO.
- **APLICATIVO NÃO É TELA, e tem registro próprio.** Aplicativo é página
  PRÓPRIA servida fora do painel, com endereço e público próprios (`/r`,
  `/motorista`); tela mora no `index.html` e vem por hash. Todo aplicativo entra
  em `api/aplicativos.APLICATIVOS`, que é a fonte única da tela `apps` — e
  `tests/test_aplicativos.py` cobra pelo DISCO: `api/static/*.html` que não seja
  o painel e não esteja no registro reprova a suíte nomeando o arquivo.
  Aplicativo fora do menu não dá erro nenhum, por isso a ausência tem alarme
  próprio. O endereço e o QR saem da origem de QUEM PEDIU (o CÓRTEX responde
  pelo túnel, pelo ngrok e por `127.0.0.1`).
- **O ESTADO de uma integração tem DUAS metades, e a tela `integ` é a junção.**
  `api/credenciais.py` diz se está CONFIGURADA (e o que falta); os cartões de
  `api/servidor.py` dizem se está CHEGANDO DADO. Uma integração configurada
  pode estar parada há cinco dias, e enquanto as metades viviam em duas telas
  isso eram dois verdes em lugares diferentes. `api/integracoes.py` casa as
  duas por fornecedor e o semáforo vale o **PIOR** dos dois lados. Duas coisas
  que NÃO são alarme: "não configurada" (recurso que a empresa não contratou) e
  fornecedor consultado sob demanda (TomTom, QualP — não há última coleta para
  envelhecer). Integração nova é obrigada a declarar como o dado dela chega
  (`tests/test_integracoes.py`), e renomear um cartão da Saúde derruba a suíte
  com o nome antigo no erro.
- **A tela é um cartão por fornecedor, e o ajuste é no modal do cartão** (desde
  07/09/2026; a aba Gestão › Integrações foi aposentada e ficou só com os
  interruptores fiscais do CT-e). **São DUAS rotas, e a separação é o que
  segura a tela aberta**: `/api/integracoes` é de RBAC normal e publica de cada
  campo só `_campo_publico()` — existe, é obrigatório, está preenchido, é
  segredo —, nunca `valor` nem `mascarado`, nem para campo NÃO-segredo (a URL
  base volta com valor em `credenciais.status()`, que é da rota de admin). O
  formulário vem de `/api/gestao/credenciais`, que sempre foi admin. Fundir as
  duas obrigaria a tela inteira a virar de administrador, e a razão de ela
  existir separada da Gestão — quem opera descobrir que a coleta parou sem
  depender de alguém — iria junto. O resumo se monta por **lista de
  permissão**, escolhendo chave por chave: copiar-e-apagar faz o campo novo do
  catálogo nascer VISÍVEL, e essa falha não tem sintoma. Guards:
  `test_o_detalhe_do_modal_NAO_tem_chave_de_valor_em_lugar_nenhum` (estrutural,
  roda mesmo com o cofre vazio, ao contrário do que compara com valor real) e
  `tests/frontend/test_integracoes_tela_e2e.py`.
- **SMTP e Z-API não se editam ali** (`aba` no panorama): eles moram nas abas
  E-mail e WhatsApp da Gestão junto com o resto do envio, e o modal leva até
  lá. Repetir o campo em dois lugares é o que fazia salvar num e conferir no
  outro.
- **O RITUAL SEMANAL (`gesrit`) É A TERCEIRA PERNA DA GESTÃO**, e o que o
  separa de mais uma tela de formulário são três decisões:
  1. **O realizado vem da FONTE, não do gerente, onde a casa já mede.**
     `api/gestao/ritual.FONTES` é o registro (34 hoje) de escalares que o
     CÓRTEX já calcula; indicador que aponta para uma fonte RECUSA digitação,
     dizendo o motivo. É isso que faz a reunião discutir o desvio em vez de
     conferir de onde veio o número. **Chave de fonte errada NÃO levanta erro**
     — `ler_fonte` captura e devolve `None`, e o indicador fica vazio para
     sempre. Aconteceu ao escrever o módulo (três fontes da Operação nasceram
     mudas: `get_analise_km` pede janela de data e foi chamada sem argumento),
     e por isso o guard EXECUTA todas as fontes em vez de conferir a grafia.
  2. **A janela da fonte é decisão, não detalhe.** As de Operação usam MÊS
     CORRENTE e não ano: retorno vazio acumulado de doze meses não se move de
     uma semana para a outra, e indicador que não pode mudar dentro do ciclo
     não é indicador de ritual semanal — é papel de parede.
  3. **Compromisso é uma `ges_acoes`**, com prazo na próxima reunião, criável
     pelo gerente dentro do ritual (`acao_nova`). Tabela paralela de
     compromissos faria o plano da reunião de resultados e o da semanal
     viverem em dois lugares — o PPT paralelo, só que dentro do banco.
- **As rotas do ritual NÃO ficam sob `/api/gestao`, e é deliberado**: aquele
  prefixo é checado como ADMIN no middleware ANTES do mapeamento de telas, e
  quem preenche o ritual é GERENTE. Sob `/api/gestao` a tela nasceria inútil
  para o público dela. Vale para toda tela nova de Gestão que não seja de
  administrador. (De passagem: é por isso que as entradas de
  `/api/gestao/acoes` em `ROTA_TELAS` são letra morta para não-admin.)
- **As regras do jogo do ritual são do SERVIDOR, não do cartaz**: desvio em
  amarelo/vermelho sem ação impede `fechar()` (409 com a lista do que falta), e
  o teto de três prioridades é ÍNDICE ÚNICO PARCIAL no banco — regra de negócio
  que só existe no Python é regra que a próxima rota esquece. `forcar=True`
  existe porque regra sem escape vira regra contornada por fora (alguém aponta
  verde no vermelho para poder fechar, e aí o painel mente); forçar fica
  gravado em `observacoes` com autor e data.
- **O MÓDULO DE FREQUÊNCIA DO GLOBUS É DO ADMINISTRATIVO, e o denominador é
  92 — não 195.** Motorista não bate ponto (a jornada dele é a Lei 13.103, em
  `jorn`): os 81 motoristas têm ZERO digitação. Percentual sobre o quadro
  mente por um fator de dois, e `frequencia.publico()` é a fonte única dessa
  contagem. Três coisas medidas em 09/09/2026 que mudam o que a tela pode
  afirmar: **a importação do AFD é MANUAL** (mediana de 3 dias entre
  execuções, máximo de 18, uma única pessoa executando), então o mês em curso
  não é parcial — é INDETERMINADO, e todo alarme mede mês FECHADO; o campo
  `ABSENTEISMOCORR` do próprio Globus está `'N'` em TODAS as 33 ocorrências,
  FALTAS inclusive, então relatório nativo de absenteísmo sai zerado e quem
  separa falta de trabalho é o `CODOCORR`; e **saldo de banco de horas que não
  se move não é jornada, é cadastro** — o corte é a razão `movimento de 6
  meses ÷ |saldo|` (< 0,10, com |saldo| ≥ 100 h), medida sobre a distribuição
  real, que tem degrau nesse ponto. Sem o corte, um único saldo congelado de
  −823,5 h desloca o saldo líquido da casa em 23%, calado.
  Guards: `tests/rh/test_frequencia.py`.
- **A BATIDA NASCE NO PONTO CERTIFICADO, NÃO NO GLOBUS** (`api/pontocertificado/`,
  09/09/2026). O ERP lê o MESMO fornecedor, mas só pelo AFD — formato da
  Portaria 671, que não tem coordenada por desenho — e por importação MANUAL
  (mediana de 3 dias entre execuções, máximo de 18, uma única pessoa). Pela
  API a batida chega em **12 s**, com GPS, local e cerca: medido no mesmo dia,
  o ERP enxergava até 06/09 e o fornecedor já tinha a batida das 20h42.
  Seis armadilhas, todas vistas no corpo real: **`FlagForaCerca` é `false` em
  100% das marcações**, inclusive nas que o próprio fornecedor rotula
  "FORA DE CERCA" — quem responde é o TEXTO de `DescricaoLocal`, e ler o
  booleano daria "nenhuma fora" para sempre; **sem GPS o fornecedor rotula
  "FORA DE CERCA"**, e isso é ausência (44% das batidas), não infração — daí
  os TRÊS estados; a data vem em `/Date(epoch±hhmm)/` do .NET e o offset NÃO
  se soma ao epoch; **o cursor não aceita zero** (`ultIdImportado=0` devolve
  VAZIO, não o histórico — a primeira carga é por período); a página tem teto
  de 1.000; e a senha viaja no CORPO, então todo erro passa por `_limpar()`.
  Cerca `Tipo` 2 é POLÍGONO com `Raio` "0" e uma linha por vértice — tratá-la
  como círculo de raio zero reprova a unidade inteira. Guards:
  `tests/pontocertificado/`.
- **O SALDO DE `FRQ_BANCOHORAS` NÃO É PASSIVO — É UM ACUMULADOR QUE NINGUÉM
  ZERA.** A casa FECHA o semestre e paga como `H.E 50%` (picos em ago/2025,
  fev/2026 e ago/2026, contra ~400 h dos meses comuns), e **esse pagamento não
  baixa o saldo no ERP**: em 24 meses foram pagas 27.516 h (R$ 573.134) e o
  evento `DEBITO BANCO DE HORAS` movimentou 156,4 h — 0,6%. Nos três
  fechamentos o saldo subiu 42 h, caiu 144 h e subiu 245 h. **O erro está na
  BAIXA, não no crédito**: seis pessoas que partiram do zero receberam 944,8 h
  em dinheiro e o banco lançou 950,7 h de crédito contra 85,8 h de débito —
  razão pagamento/saldo de **1,00** em quatro delas. `meses_compensar = 0`, e
  o fechamento não gera o débito.
  A tela publicou isso como "Passivo — R$ 123 mil" em 09/09/2026, e **quem
  pegou foi quem opera, lendo a tela e perguntando "o banco não zera a cada 6
  meses?"**. A lição de método é a que dói: eu validei o número contra si
  mesmo — a série batia, o cálculo batia — e não contra a realidade que ele
  afirma descrever. **Número coerente não é número verdadeiro.** Agora o saldo
  não viaja sozinho: `confronto()` põe as duas contabilidades na mesma linha do
  tempo, e o custo em reais carrega `ressalva_custo`. Guards:
  `tests/rh/test_frequencia_confronto.py`.
  **O PERÍODO DE COMPENSAÇÃO É DE SEIS MESES** (quem opera, 11/09/2026 — a CLT
  admite até doze com acordo coletivo, e a casa pratica seis), então a janela
  aberta em ago/2026 fecha em **fev/2027**. Isso também não está no ERP, e as
  duas pontas são constantes escritas à mão: `FECHAMENTO_CONHECIDO` e
  `PERIODO_COMPENSACAO_MESES`. **Constante escrita à mão envelhece CALADA** — e
  aqui o envelhecimento reconstrói o defeito original: passado fev/2027 sem que
  alguém atualize a data, `saldo_desde_fechamento()` segue somando desde
  ago/2026, o semestre já pago volta para dentro do número, e a tela mostra o
  mesmo cartão de sempre. Por isso `janela_do_fechamento()` viaja no payload e
  a tela ABRE COM FAIXA DE AVISO quando a janela vence. Guards:
  `tests/rh/test_frequencia_desde_fechamento.py` (cada constante sabotada em
  separado).
- **A COLETA DO PONTO É POR CURSOR, DE 10 EM 10 MINUTOS, E O WEBHOOK FICOU DE
  FORA POR DECISÃO** (quem opera, 11/09/2026). A API do fornecedor expõe
  `WebhookSubscription`, e quem reencontrar isso vai propor a troca achando que
  é um avanço óbvio — não é: dez minutos de atraso não incomodam ninguém aqui,
  e o push traz porta aberta, segredo de assinatura e uma fila que só falha
  quando já falhou. O cursor é idempotente e se recupera sozinho.
  E **a prova de que a tarefa agendada existe é o DADO que ela produz**, nunca
  `Get-ScheduledTask`: sem elevação ele não enxerga tarefa registrada como
  SISTEMA e responde "não existe" sem erro nenhum — em 09/09/2026 eu li esse
  silêncio como resposta, disse que a tarefa não tinha sido criada e pedi que a
  instalassem de novo, quando ela já estava rodando havia horas. Dois segundos
  de consulta ao cursor (`pc_cursor.ultima_coleta_em`) respondem de verdade.
- **A COORDENADA DA BATIDA ENTRA E NÃO FICA** (`api/pontocertificado/coleta.py`,
  `sql/cortex/0077_*.sql`). A cerca precisa responder "caiu na unidade?", e
  para isso bastam o VEREDITO e a DISTÂNCIA — um escalar. A coordenada crua
  responderia por onde a pessoa andou, a que horas, em que dias, e isso é
  histórico de deslocamento de trabalhador que a empresa não precisa manter
  para operar a cerca. Então `pc_marcacao` guarda `situacao` e `distancia_m`,
  e **não tem coluna de latitude, longitude, CPF ou PIS** — a matrícula
  identifica as mesmas 77 pessoas e casa com a chapa do ERP. Não se perde o
  que originou a frente: com a distância ainda se recalibra raio. O guard é
  ESTRUTURAL e lê o `information_schema`, não o texto do SQL — guard que lê
  texto-fonte protege contra apagar, não contra acrescentar a coluna.
- Integração é **módulo por fornecedor** em `api/<fornecedor>/` (gobrax,
  smartec, tomtom, whatsapp, monkey, jornada/RasterJOR, pedagio/QualP) — não
  existe hub genérico de conectores.

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

**Os três CKM que o código publica** (`api/queries.py`) — usar os nomes certos:
- `ckm_marginal` = (var + motorista) / km **carregado** — já absorveu o vazio;
- `ckm_cheio` = (var + motorista + fixo + depreciação) / km carregado;
- `ckm_bruto_marginal` = (var + motorista) / km **total rodado**.

O resultado de lane/viagem usa `valor − CKM_bruto × km_total` — o vazio entra
UMA vez, no multiplicador de km (o par errado desconta o vazio duas vezes; a
crônica do CRM em `docs/LICOES.md` mostra o estrago medido).

**Frota mista:** curto prazo compara agregado contra CKM marginal; longo prazo
(comprar veículo) contra CKM cheio. **Não existe CKM por rota** — o razão é
consolidado; CKM em tabela vira rodapé/referência, nunca coluna repetida.

**Jornada (Lei 13.103/2015):** direção contínua máx. 5h30 antes de parada de
30 min; interjornada 11h; intrajornada 1h; descanso semanal 35h.

**Piso ANTT:** nunca gravado (depende da tabela vigente NA DATA); pedágio NÃO
entra no piso; lane sem eixos/tipo de carga tem piso `n/d` com motivo, nunca
R$ 0.

**Três recortes de receita convivem** e não são o mesmo número: faturas
emitidas × frete das viagens (CT-e) × régua da meta (`realizado_acumulado`).
O atingimento é `realizado_acumulado ÷ meta_acumulada`, lido PRONTO do payload
— nunca misturar numerador de uma régua com denominador de outra.

---

## 5. Padrão de dashboards (LER ANTES DE CRIAR QUALQUER PAINEL)

Anatomia top-down: 1) linha de status (3–6 KPIs com meta e tendência);
2) série temporal principal; 3) decomposição por dimensão; 4) tabela acionável;
5) alertas. Todo painel tem fonte + timestamp; nenhum gráfico sem rótulo
direto; todo número-chave traz comparação.

### Uma tela, sub-abas e a régua

- **Painel de BI cabe em UMA tela** (900px sem rolar; TV 1050px e SEM aba —
  ninguém clica numa TV). O que não couber vai para sub-aba (`.subtabs` +
  `abaTrocar`), nunca para o fim da rolagem. `scripts/medir_paineis.py` é o
  juiz: mede CADA aba e vale a mais alta.
- **Nem para o LADO**: a régua também mede largura (`scrollWidth − clientWidth`
  por aba, zero sempre). Grade de cards é `minmax(0,1fr)` — `1fr` cru é
  `minmax(auto,1fr)` e a trilha não encolhe abaixo do min-content de uma
  tabela `nowrap`; o card da direita nasce FORA da tela sem erro nenhum (GR e
  Margem por cliente, 01/09/2026). Duas tabelas largas lado a lado não cabem
  em tela nenhuma: cada uma vira sub-aba (memória `grid-1fr-empurra-a-pagina`).
- **A aba com GRÁFICO nasce aberta** (ECharts e Leaflet medem o contêiner UMA
  vez; medida sob `hidden` vale zero para sempre — o sintoma é mudo: eixos
  certos, rótulos suprimidos). O `ResizeObserver` do `echartsRegistrar` cobre a
  volta; `mapasRemedir()` no `abaTrocar` cobre os mapas (com rAF duplo).
- Aba leva **contador** (`abaContador` — recebe o id do `<span class="aban">`,
  NUNCA o do botão, que apagaria o rótulo). Contadores são automáticos
  (`abaContadoresAuto`); zero fica em branco.
- Aba que só renderiza ao abrir declara `data-ao-abrir`.
- Tabela longa rola DENTRO do card (`.tabroll`), nunca na página.
- Todo painel com mais de uma aba ganha **"Girar"** (`abaAutoMontar` monta em
  toda `.subtabs[data-abas]`); clique manual REARMA o relógio; não gira com a
  aba do navegador escondida. **Tela cheia** em todo painel (`body.painelfull`);
  o estado vem do navegador (`fullscreenElement`), nunca de variável própria.

### Gráfico: ECharts, e SÓ ECharts

Única exceção: o gauge de meta dos painéis de TV (2 `path` à mão). Regras:

1. **Carga SOB DEMANDA** (`carregarECharts()`, memoizada — 990 KB, uma vez por
   sessão). Gráfico novo sai dos construtores da casa —
   `ecOpcoes`/`ecBarras`/`ecLinha`/`ecDesenhar` (+ `ecEixoValor`, `ecUnidade`,
   `ecDecal`, `ecTooltip`, `ecFalha`) — nunca de `option` escrita à mão: é
   neles que moram paleta, unidade final do eixo, hachura do parcial e a
   mensagem de falha.
2. **Vendorizado, NUNCA CDN** (`api/static/vendor/`) — sem host externo em
   runtime, e é o que permite testar offline.
3. A biblioteca não dispensa as regras da casa: mês parcial hachurado
   (`decal`), linha em eixo secundário com rótulo direto, eixo com unidade
   FINAL, falha DITA no cartão.
4. **Contêiner de largura zero não se conserta sozinho** — guard em
   `tests/frontend/test_echarts_largura_zero.py`; o contêiner segue a convenção
   `width:100%;height:Npx` (o guard de abas procura por ela).
5. Tema: `CC` lê os tokens uma vez e o ECharts COPIA as cores — trocar de tema
   exige `ccAtualizar()` + `echartsRepintar()`. Gráfico fora de `ecDesenhar`
   só é redimensionado.

Bibliotecas avaliadas e recusadas (amCharts/ApexCharts por licença, Chart.js
por entregar menos): crônica em `docs/LICOES.md`.

### Tema claro/escuro (três estados, não dois)

Escolha explícita carimba `data-theme` na raiz (por script no `<head>`, antes
do primeiro pixel); o padrão — seguir o sistema — não carimba nada. Estrutura
obrigatória do CSS: paleta clara completa no `:root` puro;
`@media (prefers-color-scheme: dark)` redefine SÓ tokens, guardado por
`:not([data-theme="light"])`; `:root[data-theme="dark"]` repete os mesmos
tokens (um teste exige os dois blocos idênticos). Não mudam com o tema:
`--navy-800/900` (sidebar), `--brand` (é marca, não accent) e os painéis de TV.
O semáforo muda de TOM, não de significado (TV/escuro usam o conjunto
brilhante). Guard: `scripts/auditar_tema.py` (rodar também com `--fixo`) e
`scripts/auditar_superficies.py` — eles leem o que o NAVEGADOR renderiza
(CSSOM), não o texto do CSS.

### Design system (tokens em `api/static/index.html`)

- **Marca Sulista: `#942821` (vermelho tijolo) + `#1E172F` (quase-preto
  arroxeado). NÃO HÁ AMARELO** (medido nos ícones do próprio repo — memória
  `marca-sulista`). Sidebar usa `--brand-claro` `#E0705F` (o tijolo tem 1,92:1
  sobre o navy); `--brand-ink` `#1E172F` é tinta de título. E-mail usa o tom
  original sobre branco.
- Accent da UI clara: laranja `#E85D10` (`--orange-500`).
- Semáforo: `#1E7F4F` / `#B97709` / `#C03221`; TV e tema escuro usam
  `#4ADE80`/`#FBBF24`/`#F87171`. Não introduzir outros tons de estado;
  semáforo em gráfico é DISCRETO (≥95/70–94/<70), nunca degradê.
- Neutros: ink `#14181D` (`--n900`), secundário `--n500` (hoje `#636C76` —
  calibrado com margem sobre os fundos reais, não sobre branco puro).
- Fontes: **Saira** (`--font`) + **IBM Plex Mono** (`--mono`) nos dados.
- **Marca animada: o anel** (`api/static/anel.js`, canvas, sem CDN) — grande no
  login e pequeno na SIDEBAR, abaixo do nome CÓRTEX, girando SEMPRE. Saiu da
  topbar em 02/09/2026: lá ele acendia e apagava a cada consulta e virava um
  pisca, e marca que pisca vira indicador. Quem sinaliza consulta em voo é a
  barra do topo (`#loadbar`), sozinha. Paleta fixa da marca (tijolo → laranja
  no alto, azul na base; o teste de Node recusa amarelo);
  `prefers-reduced-motion` desenha um quadro só; escondido (menu recolhido no
  celular, painel de TV), o laço dorme. Não é indicador de estado: semáforo
  continua sendo o CSS.
- **Escala de espaçamento: 9/18/25px** e nada mais (`scripts/auditar_espacos.py`
  vigia; memória `escala-de-espacamento`).
- E-mail: **o CABEÇALHO é a faixa da marca** (`#942821`) com a logo do CÓRTEX
  e o título em branco; o CORPO segue claro. A regra antiga era "nenhuma área
  escura" e caiu em 03/09/2026 a pedido de quem é dono da marca — com o risco
  na mesa, não por descuido: Gmail e Outlook INVERTEM a paleta no tema escuro
  do aparelho e a faixa pode sair remendada. A mitigação é declarar o tema
  (`color-scheme: light only`) e repor a cor da faixa no `[data-ogsc]`. Tabela
  de largura fixa e estilo EM LINHA (Outlook usa o motor do Word), corpo em
  texto puro junto. **Imagem só EMBUTIDA** (`cid:`, e só a que o HTML
  referencia): remota é bloqueada por padrão e entrega quem abriu e quando —
  e o cabeçalho não depende dela (o nome vai em texto). A logo é um QUADRO do
  `anel.js`, nunca um desenho paralelo. Tinta sobre a faixa mede 4,5:1, com
  teste.


### Padrões de componente (reusar, não reinventar)

Bandas de KPI (`.kband` + `.kpis.k4`, cards múltiplos de 4 — a banda vai para
DENTRO da aba a que pertence); chip de tendência (`trendChip`, janela
equivalente, `invert` para custo, <1,5% = estável); `statChip` para estado sem
percentual; ⓘ de procedência (`.ihelp`) em todo card — é dele que a tela `#doc`
extrai a documentação; período incompleto hachurado + "parcial" (o mês cortado
pelo FILTRO também); média de referência só sobre meses fechados; gráfico de
meia largura usa viewBox estreito; parte-do-todo com categoria dominante é
barra empilhada, não donut.

### Regras de dado em tela (cada uma tem crônica em `docs/LICOES.md`)

- **Filtros**: todo KPI da tela obedece a TODOS os filtros; filtro que a query
  ignora sai; card que não segue os filtros leva badge visível; datas sempre em
  horário local (`_iso()` — `toISOString()` em UTC−3 volta um dia); presets de
  período compartilhados exigem `emiPresetSync()`.
- **Tela de painel não morre por dependência externa com dia ruim.** O ERP é
  réplica de produção de TERCEIRO: `cached(ttl, velha_ate=)` devolve a ÚLTIMA
  LEITURA BOA carimbada quando a consulta falha, e a tela é OBRIGADA a mostrar
  a tarja — número velho servido calado é pior que tela vazia, porque ninguém
  desconfia dele. Devolve CÓPIA (quem recebe não corrompe o cache) e passado o
  prazo (`queries.VELHA_ATE`, 2 h) vira erro.
  - **O critério de quem recebe a rede é a RESOLUÇÃO DA PRÓPRIA TELA**, não o
    grupo do menu: se a menor faixa que ela publica é um DIA ou uma
    COMPETÊNCIA, a leitura de duas horas atrás não muda nada do que está ali e
    a rede entra. Se a tela publica MINUTOS ou "agora" (torre, segurança,
    portaria, programação), a rede vira PERIGO — a tarja avisa, mas a decisão
    tomada sobre uma posição velha já foi tomada, e ali tela vazia é a resposta
    honesta. Guard em `tests/test_leitura_velha.py`, com a lista das que não
    podem receber.
  - **A tarja é UMA na casa e vem de CABEÇALHO HTTP** (`X-Leitura-Velha`,
    carimbado no `JSONResponse` de `api/main.py`), não do corpo: o gancho do
    `fetch` no `index.html` a desenha para qualquer rota, existente ou futura,
    sem que ninguém precise lembrar. Enquanto eram duas tarjas escritas à mão,
    uma delas lia `leitura_idade_s` — campo que nunca existiu — e dizia
    "0 min atrás" para sempre; defeito que só aparece no dia ruim, que é o dia
    em que ninguém confere o texto da tarja.
- **Duas telas que respondem "como está o caixa" com métodos diferentes vão se
  contradizer, e as duas vão estar CERTAS.** A casa tinha três projeções de
  caixa (`fluxcon`›Projeção só o lançado; `fluxcon`›Plano lançado+provisionado
  sem antecipar; `antec` antecipando mas só sobre o lançado). Em 09/09/2026 uma
  dizia "−R$ 11,1 mi em ago/27" e a outra "nenhum dia descoberto", e a tela
  chegava a mandar o usuário para OUTRA tela para dimensionar a operação. O
  conserto não é escolher uma: é achar a pergunta que nenhuma responde —
  aqui, "quanto antecipar". `api/financeiro/plano.py` roda o motor de
  antecipação POR CIMA da projeção de 12 meses. Crônica em `docs/LICOES.md`.
  - **ANTECIPAR É SAQUE**: o antecipado sai das entradas do MÊS DE ORIGEM.
    Sem isso o simulador antecipa o mesmo dinheiro doze vezes e fecha todos os
    meses — o erro mais caro possível, porque produz um painel VERDE. E o saque
    é BRUTO (`falta / (1 − deságio)`): o deságio sai de dentro da operação.
  - **Piso de caixa é MÓVEL** (5 dias da saída daquele mês, decisão de quem
    opera). Piso fixo envelhece. A projeção crua segue com piso ZERO: "quanto
    falta para não furar" e "quanto antecipar para operar" são perguntas
    diferentes.
  - **SATURAÇÃO antes de DESCOBERTO.** Enquanto sobra pilha o plano fecha todo
    mês e o painel fica verde; o alarme é o mês em que ele passa a precisar de
    100% do recebível elegível (jan/27, 8 de 12 meses). Esperar o descoberto é
    avisar depois que já não há remédio.
  - **Custo de antecipação se lê sobre CAPITAL MÉDIO** (Σ valor×prazo ÷ 365),
    nunca sobre o nominal somado: R$ 73,1 mi de saque em 12 meses são R$ 9,79
    mi de capital, porque o dinheiro gira 7,5×/ano. É a única régua em que o
    deságio (14,26% a.a.) e o rotativo (15,67% a.MÊS) se comparam.
  - **Taxa de fornecedor NÃO se escreve no código.** O `_lastro` usava 2,0%
    a.m. fixo enquanto o portal praticava 1,17% — 41% de custo a mais,
    publicado como se fosse medido. Custo por constante envelhece calado.
- **A régua com dublê mede o ESQUELETO.** `scripts/medir_paineis.py` roda com a
  API devolvendo `{}`: tabela vazia, avisos mudos. A aba Decidir passava com
  854px e ia a 1.303px com os doze meses reais; a aba "O dia" da Frequência
  passou com **381px** e media **1.060** com o dia real. Aba nova pede medição
  com payload CHEIO, no e2e.
  - **E payload CHEIO não é payload NO LIMITE** — as duas frentes tropeçaram
    nisto no MESMO dia (11/09/2026, `freq` e `cliop`). Medir o dia de hoje
    prova que hoje cabe; não prova que o mecanismo que faz caber está lá. Com
    4 cláusulas e 12 mercadorias, REMOVER a rolagem interna não mudava um
    pixel, e as duas sabotagens passaram verdes. O dublê do guard sai do
    **teto do CADASTRO**, não do maior dia já visto: 92 pessoas com ponto × 6
    batidas/dia × 9 cercas, contra um pico real de 83/306/8. A régua do
    conteúdo é `conteudo > 3 × altura da caixa` — abaixo disso o payload não
    exercita nada.
  - **Sabotar a EXISTÊNCIA do mecanismo não prova o AJUSTE dele.** Tirar
    `tabroll` da tabela acusa; o que estava em jogo era o `curta` (260px em
    vez de 430), e só sabotando o VALOR se descobre que o guard o mede. Vale
    para todo número que decide layout — `max-height`, teto de linhas, largura
    de trilha.
  - E **guard coberto pelo VIZINHO não está coberto**: se o que impede a
    vacuidade é outro teste do mesmo arquivo, ele morre no dia em que alguém
    mexer no vizinho. Cada guard de altura cobra, ele mesmo, que o dublê
    CHEGOU na tela — aba vazia cabe em qualquer régua.
- **Zero que é ausência de lançamento não é desempenho** — é `n/d` em cinza,
  jamais verde. KPI que só pode dar zero por falta de preenchimento mostra
  "não informado" com a cobertura ("informado em X de Y").
- **Campo que se preenche com atraso parece campo vazio em janela curta** —
  medir a cobertura CONTRA A IDADE do registro antes de concluir "vazio"
  (multas: 15% no mês 0 → 91% no mês 7).
- **Denominador só contém quem pode cumprir a regra** (rastreador: 79% "sem
  sinal" virou 86,7% de cobertura ao tirar terceiros e carretas).
- **Média de população heterogênea não decide nada** — separar (idade da frota:
  tração 6,9 anos × implemento 12,9).
- **Top-N leva contador** ("30 de 102 · 774 dos 793") — senão vira total falso.
- **Faixa física valida a leitura** (km/l de caminhão: 0,8–6,0; jornada > 24h;
  km > 1.500/dia): fora dela é `n/d` com o bruto no tooltip, e conta num aviso.
- **Rótulo de eixo nomeia a unidade FINAL** (`MILHÕES DE KM`, nunca
  `MIL KM ×1000`).
- **Repetição dentro do MESMO documento não é recorrência** — a mesma peça
  comprada duas vezes para o mesmo veículo na MESMA ordem de serviço é um
  reparo lançado em duas solicitações, não falha prematura (64 de 355 pares,
  quase todos com um dia). Piso de dias não separava isso: a distribuição por
  dias é lisa, sem degrau. Separar pelo DOCUMENTO, não pelo tempo.
- **Filtro heurístico se declara e se mostra dos dois lados** — a lista de
  consumíveis que tira parafuso e graxa da recompra é regex sobre a descrição,
  não campo do ERP. A tela mostra o número com e sem o filtro e pede validação
  de quem opera; heurística escondida vira verdade do sistema.
- **Régua de desvio é MEDIANA, e só existe com base** — média deixa o próprio
  outlier caber na faixa (um item a 70× move a média o bastante para se
  inocentar). Produto com menos de N compras na janela não é avaliado, e a tela
  DIZ a cobertura da régua em vez de chamar de "normal" o que não mediu.
  Desvio de preço num catálogo sem marca não é sobrepreço: é item A CONFERIR, e
  a economia sai em faixa (conservadora × teto), com a conservadora excluindo o
  código de spread alto, que é o que mistura peças diferentes.
- **Coluna constante sai da tabela** (vira referência no hint); coluna sempre
  vazia se preenche ou se remove.
- **Código sem tabela de domínio não vira rótulo inventado** — decodificar por
  evidência escrita no módulo, ou mostrar o código cru dizendo isso.
- **`|desvio| > 1 ciclo` do próprio indicador = cadastro furado**, não
  operação — sai dos KPIs e vai para "corrigir no cadastro" com a evidência.
- **Série mensal**: o intervalo de meses é GERADO, não colhido (`GROUP BY` não
  devolve o mês sem linha — abril emendaria em agosto); mês sem coleta rotulado,
  barra cinza, linha ABERTA (`connectNulls:false`); cobertura parcial mostra o
  número POR DIA; janela ancorada no ÚLTIMO DADO, nunca em `current_date`.
- **Empate em `ORDER BY` é SORTEIO, e sorteio estável por acidente passa em
  todo teste.** `DISTINCT ON (cliente) … ORDER BY dtinicio DESC` sobre um
  contrato que tem UMA LINHA POR MERCADORIA, todas com a mesma data, devolve
  uma ao acaso — e como o `valor_est` do SAC multiplica a hora excedente pelo
  valor contratado, o sorteio mexia em DINHEIRO. Três execuções seguidas deram
  o mesmo resultado: era a ordem FÍSICA da tabela, não regra, e um `VACUUM`
  bastava para virar. Desempate se escreve por inteiro, e a chave do
  `DISTINCT ON` inclui a dimensão que de fato distingue as linhas.
- **Duas telas que leem a MESMA fonte e cada uma inventa a própria política
  discordam POR CONSTRUÇÃO.** O `sac` sorteava a cláusula de freetime; a
  `cliop` recusava escolher e publicava uma faixa. Nenhuma errada, e
  incompatíveis. A regra vira MÓDULO (`api/freetime.py`) e as telas a executam.
  Quando ela precisa de dois sotaques (SQL no ERP, Python em casa), **o guard
  EXECUTA os dois lado a lado contra entrada REAL** — comparar as duas
  implementações por leitura aprova qualquer divergência de comportamento, e
  foi assim que se achou o Python colapsando espaço interno e o SQL não.
- **"Procurei por ali e não achei" não é "o dado não existe"** — e vira mentira
  duradoura quando escrito como comentário afirmativo no código. O vínculo
  coleta↔mercadoria não estava em `coleta_composicao` (11 linhas para 2.998
  coletas), e por isso ficou escrito que não havia vínculo confiável; estava em
  `coleta.mercadorias`, 100% preenchida em 17.269 coletas de 180 dias.
- **Aproximação de texto que decide DINHEIRO é decisão comercial declarada,
  nunca heurística escondida numa query.** Normalizar grafia (maiúscula,
  acento, espaço, plural) casa "ESPUMAS PARA BANCO" com "ESPUMA PARA BANCOS" e
  é aritmética. Casar "CONJUNTO PHEVUS" com "CONJUNTOS" muda o freetime de 3h
  para 6,5h em 163 cargas — isso é pergunta para quem negocia o contrato. A
  tela DIZ qual cláusula respondeu (própria / genérica / não há), que é como a
  pergunta chega a quem pode respondê-la; há guard proibindo `LIKE` ali.
- **Filtro cuja marca no SQL é um COMENTÁRIO precisa de recusa explícita.**
  `--{FILTRO_MERC}` perdido não quebra consulta nenhuma: ela roda, responde e
  ignora o filtro — a tela mostra "ESPUMA" no seletor e devolve a operação
  inteira. O montador levanta `AssertionError` sem o lugar do filtro, e uma
  varredura por `ast` cobra a marca de toda constante SQL do módulo (com
  `assert` contra resultado vazio).
- **JOIN com tabela de vigência/histórico multiplica linhas e o total inflado é
  PLAUSÍVEL** — tabela com `dtvigencia`/`versao`/`_hist` entra por
  `DISTINCT ON (chave) … ORDER BY chave, data DESC NULLS LAST`, nunca join
  direto; `max(a)`+`max(b)` são máximos independentes; conferir a contagem dos
  dois lados de CADA join novo (o total mudou de ordem de grandeza? é o join).
- **JOIN que só responde "sim ou não" vira EXISTS** — e a diferença é de ordem
  de grandeza, não de estilo. A consulta do Orçamento juntava
  `agrupadorgerencial` e só olhava `descricao IS NOT NULL`: 3 meses 0,9 s,
  9 meses 7,5 s, **24 meses estourando o `statement_timeout`**. O plano vira
  sozinho com o tamanho (na janela grande ele casava só por `grupo`, que tem
  meia dúzia de valores, e filtrava `reduzido` depois — produto cartesiano
  sobre 2,5 mi de linhas). **A defesa contra plano que vira não é achar um
  plano melhor, é escrever a consulta de forma que não exista plano ruim
  disponível**: `EXISTS` não pode multiplicar linha. Quem só precisa da
  resposta usa `agrupador_gerencial.existe()`; quem precisa do NOME continua em
  `left_join()`. Uma CTE pré-calculada era mais rápida na janela pequena e
  estourava igual na grande — velocidade em teste pequeno não é o critério.
- **Consulta lenta contra o ERP: medir com o servidor VAZIO antes de acusar a
  carga alheia.** 60,2 s três vezes com zero consultas ativas é defeito nosso;
  o mesmo número dentro da janela de degradação não é evidência de nada.
- **Coluna zerada com KPI cheio = join quebrado** (conferir se a coluna do `ON`
  tem dado).
- **Estado de fluxo vem do CAMPO de estado, nunca da ausência de data**
  (`aprovado`, não `dtaprovador IS NULL`): a suspensão grava a data de
  aprovação sem usuário, e cadastro antigo tem aprovado sem data. Uma
  expressão só para tela, Visão Geral e Copiloto (`api/suprimentos_oc.py`).
- **Data que o ERP preenche por default não é prazo** (previsão de entrega =
  dia da emissão em 80% das OCs): só conta quando difere da emissão; "vencida"
  crua era verdadeira no dia seguinte. Medir a distribuição do campo contra a
  data de origem antes de derivar atraso dele.
- **Duas séries de escalas muito diferentes não dividem eixo** — a menor vira
  linha em eixo secundário com rótulo direto; cenário especulativo entra por
  toggle desligado.
- **Ranking por percentual sem piso de materialidade mente** — padrão é valor
  absoluto, cabeçalho clicável, baixo volume atenuado com badge.
- **Razão entre recursos coletados separadamente só sobre a INTERSEÇÃO** (dias
  com ambos), e a tela diz quantos ficaram fora.
- **Razões e percentuais saem da unidade de ORIGEM** (minutos, centavos) —
  arredondar antes de dividir move o número de lado da fronteira.
- Painel de TV: sem tooltip — cada número se explica no rótulo; dia futuro só
  com meta esmaecida; verde só quando havia meta a bater.

---

## 6. Regras de engenharia

### API e erros

- **Recusa legível é 4xx** (`HTTP_RECUSA = 409` em `api/main.py`); 5xx só para
  falha NOSSA (o Cloudflare TROCA o corpo de 5xx pela página dele — a mensagem
  nunca chega). Na tela, **sempre `respostaJSON(r)`** — distingue sessão
  expirada, proxy respondendo no lugar da API e erro interno.
- **Reiniciar a API mata a ÁRVORE, não o dono do socket.** Com `--workers` o
  dono do socket é o SUPERVISOR; matá-lo deixa os filhos órfãos segurando a
  porta, e como o Windows aceita `SO_REUSEADDR` a instância nova sobe POR CIMA
  — medido em 06/09/2026: dois conjuntos completos servindo a 8010 e 23
  conexões no banco onde deviam ser 8, um a mais por deploy. O
  `scripts/autodeploy.ps1` para a árvore e CONFERE a porta livre antes de subir
  (dormir 800 ms não é conferir); se não liberar, desiste e tenta no ciclo
  seguinte. **Os lançadores `.vbs` derivam a raiz do próprio caminho** —
  `scripts/win/` e `data/win/` têm a mesma profundidade, então o mesmo arquivo
  serve nos dois. Guards: `tests/test_lancadores_windows.py` e o
  `test_script_da_tarefa_e_ascii_puro`, agora recursivo e cobrindo `.vbs`.
- **O `startup` roda em CADA worker do uvicorn** (medido: 4 a **6** vezes com
  `--workers 4`, porque o Windows respawna worker), e os pools são POR
  PROCESSO. Quem sobe relógio no `on_event("startup")` passa por
  `lider.sou_o_agendador()` — senão o aviso de carga manda WhatsApp REAL uma
  vez por worker; e quem dimensiona pool usa `processos.fatia_do_pool()` —
  senão 4×20 = 80 conexões contra o teto de 100 do banco local.
  `WEB_CONCURRENCY` é a fonte única (é a que o uvicorn já lê). Guard:
  `tests/test_lider_e_workers.py`.
- **Em rota `async def`, todo I/O bloqueante passa por `sem_travar()`**
  (`api/main.py`) — senão trava o servidor INTEIRO pelo tempo da chamada.
  O `TestClient` não pega; `tests/test_rotas_nao_travam.py` sobe uvicorn real.
- **Serialização converte no LIMITE do módulo** (`float()`, `.isoformat()`);
  o `JSONResponse` da casa é a rede (Decimal/date estouram DEPOIS do
  `try/except` da rota, em `render()` — 500 em `text/plain` sem pista).
- **`FileResponse` NÃO responde 304 — quem responde é o `StaticFiles`.**
  Emitir `ETag` não é implementar cache condicional: a página da raiz devolvia
  200 com 712 KB a cada F5 enquanto `/static/*` devolvia 304 no MESMO servidor.
  E **middleware de compressão recomprime a CADA requisição** — 206 ms por
  carregamento dos 2,5 MB do `index.html`, que num processo único vira fila
  para o sistema inteiro (`/api/health` 2,8× mais lento com 10 pessoas abrindo
  o painel; 20 juntas saturavam 95% de UM núcleo de 28). Página grande servida
  fora do `/static` passa por `api/main._servir()`: comprime UMA vez sob trava
  (chave = `(mtime, tamanho)` do ARQUIVO, não o boot do processo), ETag do
  CONTEÚDO (`git checkout` mexe no mtime sem mudar um byte) e 304 escrito à
  mão. Guard: `tests/test_pagina_do_painel.py`.
- Exceção para fora **nunca com `str(exc)` cru** em integração — na Z-API e na
  TomTom a URL É a credencial; tudo passa pelo `_sanitizar` do cliente. Log
  leva o TIPO da exceção.
- Rota nova entra em `ROTA_TELAS` (a mais específica ANTES da genérica — há
  conferência fácil: nenhum prefixo pode engolir outro) ou, se for para todo
  usuário logado, em `_ROTAS_SEM_TELA` — o middleware é fail-closed (rota
  `/api/*` não mapeada = 403 para não-admin).
- Confirmação de ação irreversível não depende do que vem depois (recarregar a
  tela fora do `try` da ação); `await r.json()` em `try` próprio (500 em texto
  viraria "erro de rede").

### Estado e edição

- **Estado que envelhece sozinho não se GRAVA, se calcula** (atraso, vigência,
  cliente ativo) — status gravado precisa de rotina para virar, e no dia em que
  ela não roda a tela mente.
- **Edição parcial: chave AUSENTE = não mexe; chave VAZIA = limpa** (sentinela
  `_AUSENTE`, `api/auth.py`).
- **`None` em campo de regra opcional significa HERDA, nunca zero.**
- **Total nunca desnormalizado** — calculado na leitura a partir das linhas
  (senão discorda das próprias linhas em silêncio no primeiro edit).
- **Um único validador de telefone na casa** (`api/whatsapp/numeros.py`),
  guardado NORMALIZADO; a tela reformata na exibição.
- **NUNCA `str.format()`/f-string sobre texto escrito por usuário** (alcança
  atributos de objeto) — substituição por regex de `{{nome_simples}}`.

### Frontend (index.html)

- **O menu é ALFABÉTICO**: miolo em ordem de dicionário (sem acento,
  minúsculo), Visão Geral e Copiloto no topo, Administração no fim — na barra
  lateral E na gaveta, grupos e itens. `tests/frontend/test_menu_alfabetico.py`
  cobra. Tela nova entra "no fim" por inércia; em três telas isso vira ordem de
  chegada.
- **A regra de CSS pode existir, estar certa e NÃO VALER** (memória
  `css-regra-que-perde-a-briga`): só o navegador diz quem venceu a
  especificidade. No login, `.lg-btn` (0,1,0) perdia para `button.btn` (0,2,1) e
  `.lg-lembrar` (0,1,0) para `.lg-body label` (0,1,1) — o padding escrito nunca
  valeu e a linha saía com estilo de rótulo de campo. Regra de componente dentro
  de um bloco estilizado nasce QUALIFICADA (`.lg-body button.lg-btn`); `!important`
  ali é remendo que não alcança tudo e ESCONDE a causa. Teste de estilo lê
  `getComputedStyle`, nunca o texto do CSS.
- **"Grande demais" quase nunca é altura** — medir o elemento e o vizinho antes
  de mexer no `padding`: o botão do login era MENOR que o campo (42,6 × 43,5 px);
  o que desequilibrava era `inline-flex` sem `justify-content` deixando o rótulo
  colado na esquerda de um bloco de largura inteira.
- **TDZ mata o script no boot**: `const` de topo não pode ler `CC` (criado no
  fim do arquivo) — cor de paleta se resolve dentro de função. O sintoma é o
  login que não some da tela.
- `JSON.stringify` dentro de atributo HTML quebra a PÁGINA — usar
  `data-*` + `esc()` + `this.dataset`.
- `<input type="number">` DESCARTA a vírgula (`1234,56` → `123456`): campo de
  valor é `type="text"` + `inputmode="decimal"` + `numBR()`.
- `%` dentro de string SQL vira placeholder do psycopg — comentário explicativo
  vai em Python, fora da constante.
- Identidade de veículo: **a chave é a PLACA**; `numerofrota` tem cobertura
  real de 46% (947 cadastros têm a placa copiada no campo). Rotular via
  `api/frota_identidade.py` (`rotulo()`), nunca `coalesce(numerofrota, placa)`.
- Recarga automática é **ENCADEADA** (agendar o próximo ciclo DEPOIS do
  anterior terminar), nunca `setInterval` — com guard de sequência, resposta
  lenta vira tela vazia para sempre.
- Diagnóstico cujo custo é externo leva **cache com TTL** (estado da Z-API,
  agendador do Windows) — e **o TTL NÃO tira a medição do caminho do pedido,
  só a repete menos.** Ele poupa a SEGUNDA leitura; a primeira alguém sempre
  paga, e o AutoDeploy reinicia a API a cada push. A Saúde levava **78 s** para
  abrir (47,7 s do mapa contábil + 6,9 s do agendador) e ficava EM BRANCO,
  porque o guard de sequência do front descarta a resposta que chega depois de
  a próxima ter começado. Medição cara serve o que TEM e mede numa thread
  (`_EmFundo`, `api/servidor.py`), com TRÊS estados que o cartão DIZ:
  fresco / **velho** (última leitura boa, com a idade à mostra) / **medindo**.
  UMA medição por chave — sem a trava, 12 pinturas viram 12 PowerShell —, falha
  NÃO apaga a leitura velha, e o cartão **não some** enquanto mede (ausência não
  tem sintoma). Medido: 78 s → 3,6 s frio, 1,0 s quente.
  Guards: `tests/test_saude_em_fundo.py`.

### Cortes, testes e conferências

- **Corte por marcador**: o fim é DERIVADO por busca a partir do início
  (regex `^(?:async function|function|const|let|var|class)\s+(\w+)`), nunca
  string escolhida a olho; depois de todo corte, comparar as declarações contra
  o **HEAD do git** e exigir `sumiram: nenhuma`. O `git diff --stat` denuncia
  antes de qualquer teste. Editar o `index.html` por fatia: memória
  `editar-index-html-por-fatia`.
- **Diferença entre dois estados não NOMEIA a causa** — para atribuir, varie um
  fator de cada vez. Os "44 ms do `check` do pool" eram 15 ms de check mais
  30 ms de `rollback` na devolução, e a metade maior era a que ninguém tinha
  olhado; só a tabela de quatro estados separou. E **custo pode ser freio**:
  tirar o rollback (`autocommit=True`) derrubou a Visão Geral de 1,9 s para o
  `statement_timeout` de 60 s, 5 vezes em 5. **A causa: `SET LOCAL` fora de
  transação é NO-OP** — o `queries.py` protege a consulta de OC com
  `SET LOCAL enable_mergejoin = off` (sem a dica o 9.3 faz merge join
  degenerado) e com `SET LOCAL statement_timeout = 12000`; com autocommit os
  dois evaporam antes da consulta. Ligar autocommit exige converter TODO
  `SET LOCAL` da casa antes; até lá o guard segura
  (`tests/test_pool_do_erp.py`). E a lição de método: minha primeira
  explicação — o custo do pool como freio acidental — era plausível, coerente
  com três observações e FALSA. Plausível não é evidência; a pergunta que
  resolveu foi "o que mais muda no SQL quando a transação deixa de existir?".
- **Contador acumulado NÃO é medição.** "802 milhões de linhas lidas em
  `jor_jornadas`" e "25 GB de arquivo temporário" são verdadeiros e não dizem
  o custo: cronometrados, a varredura completa custa 6,7 ms e o derrame de
  ordenação não muda o relógio (NVMe + banco de 434 MB inteiro na RAM). Índice
  novo, `work_mem` e `shared_buffers` foram MEDIDOS E RECUSADOS em 06/09/2026,
  junto com `--workers` (a fila que ele resolveria sumiu com o 304 da página) e
  com o plano de energia Alto Desempenho (171 ms × 165 ms do Equilibrado —
  trocado, medido e DEVOLVIDO ao original). Crônica em `docs/LICOES.md`.
- **Medição contra dependência externa vale UMA vez e só se REPETIDA.** Número
  isolado durante incidente é sintoma do incidente, não da consulta: a de OC da
  Visão Geral foi acusada de lenta com base em 200 s medidos dentro de uma
  janela ruim do ERP, e roda em **0,13 s** (mediana de 10) com o servidor são —
  no mesmo intervalo o `VG_MES_SQL` caiu de 8,5 s para 1,8 s sozinho. E
  comparação entre dois estados só vale se os dois forem medidos IGUAL.
- **Ao mudar uma REGRA, ache os guards dela pelo ASSUNTO, não pela pasta.**
  A faixa da marca no e-mail subiu com 8 testes quebrados: o guard atualizado
  estava em `tests/correio/`, e o outro da MESMA regra em
  `tests/test_boas_vindas.py`, na raiz. `grep -rl "<a regra>" tests/` custa dois
  segundos; guard não mora necessariamente ao lado do código que ele guarda.
- **SABOTAR O ISOLAMENTO ESCREVE EM PRODUÇÃO.** Desligar o `SET search_path`
  do `pglocal` para conferir o guard mandou a escrita da suíte para `cortex`:
  criou `caixa`/`t` e APAGOU 219 registros de `rntrc_transportador` (o
  `gravar_lote` da ANTT é `DELETE` + `INSERT`). Sabotagem que mexe em
  `search_path`, pool, DSN ou conexão roda contra banco DESCARTÁVEL; o guard de
  `tests/test_pglocal_pool.py` agora limpa e ACUSA o vazamento. Restaurado do
  backup — o que salvou foi o passo 5 do `testar_restauracao.py`, que compara
  volume POR TABELA.
- **Guard que lê TEXTO-FONTE protege contra apagar, não contra quebrar.** O
  `conferir_numeros.py` (prova do critério 2 do `1.0.0`) ficou 4 dias morto com
  `KeyError` enquanto o guard dele conferia que a linha continuava escrita — e
  com ele não rodavam a DRE nem as três receitas. O guard que executa é
  `tests/reconciliacao/test_conferidor_executa.py`.
- **Guard com lista escrita à mão precisa da LISTA conferida contra o disco.**
  O guard do EXISTS varria quatro módulos e não `api.agrupador_gerencial` — o
  que DEFINE `left_join()` e `existe()` — e por isso aprovou o
  `DOIS_CAMINHOS_SQL`, a única violação viva da casa, que custava 47 s onde o
  `EXISTS` custa 4,5 s. O docstring dele dizia "nasceu com ZERO violações":
  verdade sobre o que ele olhou. Lista errada não tem sintoma — a varredura sai
  do DISCO (por `ast`, sobre constantes de módulo) e leva um `assert` que
  reprova o resultado VAZIO, porque varredura que não acha nada passa por
  vacuidade. E **guard não varre o próprio módulo por inércia**, justamente o
  mais provável de conter a violação.
- **Verde que nunca ficaria vermelho não conferiu nada** — sabotar o alvo e ver
  o teste falhar leva trinta segundos; campo ausente em conferidor vira ACHADO,
  não silêncio.
  - **A SABOTAGEM também se confere.** Provar que o alvo mudou ANTES de ler o
    resultado: um script de edição cujo `assert` estourou deixa o arquivo
    intacto, o teste passa, e verde de sabotagem que não aconteceu é idêntico a
    verde de guard robusto. Aconteceu em 06/09/2026, e escondeu um guard que era
    verde-para-sempre (a regex casava com texto da própria fonte que ele
    varria).
  - **Dublê que se monta a partir da constante testada não testa a constante.**
    O teste do cartão de janelas do ERP fabricava a linha de log com
    `erp_janelas.RESGATE`; sabotar a constante sabotava junto o que o teste
    fabricava, e ele seguia verde. Entrada de teste que representa formato
    EXTERNO (linha de log, corpo de fornecedor, arquivo do ERP) é LITERAL
    copiado do real — nunca derivada do código que vai lê-la.
  - **E o espelho disso: string escrita à mão que descreve o CÓDIGO precisa ser
    conferida CONTRA o código.** A varredura de agendadores procurava a thread
    `aviso-carga`; ela se chama `rastreio-aviso`. A varredura passaria com a
    thread viva mandando WhatsApp — o defeito que ela existe para pegar,
    aprovado por ela. Lista de nomes/rotas/tabelas leva um guard que prova que
    cada item EXISTE na fonte.
  - **Em guard parametrizado, cada parâmetro é um guard e pede a PRÓPRIA
    sabotagem.** Foi assim que o `aviso-carga` passou: sabotei `push-digest`,
    vi vermelho e conclui que o teste funcionava. Sabotar um parâmetro prova o
    MECANISMO; não prova que os outros nomeiam alvo real. Vale em dobro quando
    o parâmetro aponta para módulo de outra frente, que é o que a gente tende a
    tratar como já conferido.
- **Teste que depende do relógio acusa a pessoa errada** — dublê com data
  acompanha o relógio que a página lê, nunca data fixa.
- **Dublê de fornecedor copia o corpo REAL**, campos "inúteis" inclusive
  (`error` descritivo da Z-API); dublê de custo tem a ordem de grandeza do
  real.
- **Renderizar com DADO REAL** acha o que fixture não acha (nulos em 2/3 das
  linhas, `LIMIT` batendo).
- Teste afirma COMPORTAMENTO, não implementação (nem texto-fonte, nem marcação
  do renderizador antigo).
- Recorte de HTML em teste termina num LIMITE REAL (`</section>`), nunca em
  deslocamento fixo.
- Playwright: `wait_for_selector` espera VISIBILIDADE (use `state="hidden"`);
  `evaluate("fetch(...)")` aguarda a Promise (use `void`); a rota registrada
  por último é avaliada primeiro; estabilizar exige quietude de rede.
- Depois de editar `docs/versoes.yaml` à mão: `yaml.safe_load` + conferir topo
  e contagem (o YAML quebrado derruba 24 testes que não apontam para ele).

---

## 7. Integrações (módulos por fornecedor)

Cada fornecedor é um módulo em `api/<fornecedor>/`: Gobrax (telemetria,
premiação, posições), Smartec (multas/infrações), TomTom (ETA, tráfego),
Z-API (WhatsApp), Monkey, RasterJOR (jornada), QualP (pedágio), e-mail/correio.
Regras duráveis — as crônicas (medições, formatos, tetos) estão em
`docs/LICOES.md`:

- **Tela ou integração nova entra no snapshot do Copiloto e na Saúde do
  Servidor NO MESMO COMMIT** (memória `copiloto-sempre-atualizado`). Fonte de
  snapshot **jamais dispara coleta externa** (`so_cache`/sem `force`).
- **Antes de dizer que uma integração/dado não existe**: listar os schemas do
  AVA (são 19), ler o CATÁLOGO de integrações do ERP (`integracao.*`), e ler
  TODOS os arquivos que a casa versiona. RasterJOR estava em
  `sulista.rasterjor_*`; a Smartec era o `tipointegracao` 32; a tarifa de
  pedágio já estava no ERP. **E perguntar do que o INSTRUMENTO é capaz:**
  `Get-ScheduledTask`/`schtasks /query` sem elevação listam só o que o usuário
  pode LER — calados. Eles diziam "quatro tarefas do CÓRTEX" enquanto cinco
  outras rodavam como SISTEMA (`Aviso de Cargas`, `3S coleta`, `WhatsApp
  agendado`, `Relatorios por e-mail`, `CTe Contrapartida`), e a ausência virou
  parágrafo de documentação que justificou um segundo relógio ao lado do
  primeiro. Censo de tarefa se faz pelo log de eventos
  (`Microsoft-Windows-TaskScheduler/Operational`) ou elevado. Crônica em
  `docs/LICOES.md` (07/09/2026).
- **Ler a resposta INTEIRA do fornecedor uma vez** (a Gobrax devolvia 14
  indicadores e o CÓRTEX lia 3); ler `description` de spec antes de inferir
  (o `Tipo` da Smartec só existia lá); premissa de custo escrita envelhece —
  medir de novo antes de descartar um caminho.
- **Coleta é idempotente** (`ON CONFLICT … DO UPDATE` sobre chave natural);
  coleta vazia NUNCA vira snapshot completo; API que só devolve o ABERTO exige
  `visto_em`/`sumiu_em` com fechamento ancorado no INÍCIO da coleta completa.
- **Ler o CORPO da resposta**: `error` descritivo não é erro (Z-API
  `connected` decide); "nenhum dado" pode chegar como HTTP 400 (Smartec) ou
  HTTP 200 com mensagem (RasterJOR); regra genérica vale por ENDPOINT.
- **Aviso automático tem TRÊS respostas** (manda / cala porque não há / recusa
  dizendo o motivo) e confere o FRESCOR da coleta antes do conteúdo — sem isso
  ele silencia justamente quando parou de enxergar.
- **Sem credencial não é falha, é instalação incompleta** (`info` na Saúde);
  alarme vermelho = "não está chegando AGORA", nunca contagem de tropeços;
  cadências diferentes têm limiares separados.
- **A RECOLHA NÃO DEPENDE DO ERP, e isso é REQUISITO** (decisão de quem
  opera, 07/09/2026): `api/sefaz/` é módulo do **TMS Córtex** e vai rodar
  independente do AVA. A fronteira é literal — `conciliacao.py` é o ÚNICO
  arquivo que lê o ERP, e é OPCIONAL: a rota o chama num `try`, e o cartão vira
  "—" (não sei) em vez de zero quando ele falha. Zero afirmaria "conferi e não
  há nenhum sem par", que ninguém conferiu.
  `tests/sefaz/test_independencia.py` cobra pelos DOIS lados: nenhum arquivo do
  núcleo importa `api.db` nem escreve SQL contra tabela do AVA, e a tela
  sobrevive ao ERP fora do ar. **O motivo é a cópia**: o reaproveitamento entre
  CÓRTEX e TMS Sulista é por CÓPIA, nunca import — e módulo que só funciona com
  o AVA por perto não se copia, se REESCREVE. Reescrevendo é onde as sete
  correções que a `erpbrasil.edoc` exigiu se perdem.
- **RECOLHA DE DFe NA SEFAZ** (`api/sefaz/`, tela `dfe` no grupo TMS): o
  serviço é gratuito e a casa NÃO paga intermediário — o NSDocs está cadastrado
  no ERP desde 05/2025 e nunca trouxe um documento. **83% das NF-e chegam
  COMPLETAS sem manifestação**, porque a Sulista é TRANSPORTADORA e a SEFAZ
  entrega o XML inteiro ao transportador indicado; só onde ela é DESTINATÁRIA
  vem resumo. E só sai documento em que o CNPJ é PARTE (destinatário,
  transportador, emitente, tomador) — o resto é fronteira legal, não
  configuração.
  **O NSU é um cursor de MÃO ÚNICA**: a SEFAZ trata reconsulta da mesma faixa
  como consumo indevido, então cada lote passa UMA VEZ e um lote mal processado
  não se recupera pelo `distNSU` (só `consNSU`, um por chamada). É por isso que
  documento VAZIO é recusado em três camadas — e `gzip.decompress(b"")` NÃO
  levanta, devolve `b""`.
  **A cadência é limitada pelo FREIO, não pelo relógio**: a SEFAZ pune consulta
  SEM RESULTADO (656, ~1 h), não consulta frequente. Com o freio no script, a
  tarefa roda de 20 em 20 min e gasta no máximo uma consulta infrutífera por
  hora — a passagem barrada nem abre conexão.
  E **NÃO somos o único consumidor**: a contabilidade lê a mesma caixa. Ler em
  paralelo é seguro; MANIFESTAR não é (o evento é do documento, e quem
  manifesta assume a ciência com prazo legal). Guards: `tests/sefaz/`.
  Detalhe técnico do laço: o NSU é o estado inteiro, é POR
  CNPJ (a Sulista tem dez caixas, uma por filial ativa) e é TEXTO de 15 dígitos
  — `int()` no meio do caminho e a varredura passa a achar que já leu o que não
  leu. Três regras que custam caro se erradas: o NSU se grava a CADA lote (uma
  queda no meio não pode recomeçar do zero, que é o padrão que o **656** pune);
  **o ponteiro só anda com DOCUMENTO na mão** — o `ultNSU` que vem dentro de uma
  REJEIÇÃO descreve o servidor, não o que consumimos, e gravá-lo pulou 1,1
  milhão de posições em silêncio; e resumo NUNCA sobrescreve documento completo
  (a SEFAZ manda `resNFe` antes da ciência e `procNFe` depois — a ordem inversa
  APAGA o XML da guarda de cinco anos). **Prazo que o fornecedor declara não se
  arredonda para cima**: o freio pós-656 é 65 min porque ela pede 60.
  **NÃO SOMOS O ÚNICO CONSUMIDOR** — a contabilidade já baixa a mesma caixa;
  ler em paralelo é seguro, MANIFESTAR não é (o evento é do documento, e quem
  manifesta assume a ciência com prazo legal). Guards: `tests/sefaz/`.
- **A RECOLHA TEM DUAS PORTAS, e a segunda existe por uma fronteira legal.**
  A SEFAZ só entrega documento em que o CNPJ é PARTE; a nota do cliente que a
  Sulista vai transportar, mandada antes de o frete existir, **nunca** vai
  chegar por lá. Ela chega por e-mail, em `xml@sulista.com.br`, e
  `api/sefaz/caixa_email.py` lê essa caixa pelo **Microsoft Graph** — não por
  IMAP, porque o domínio entrega no Exchange Online e a Microsoft desligou a
  autenticação básica de IMAP/POP lá (um leitor com usuário e senha responderia
  535 para sempre, e o 535 do M365 se lê como "senha errada"). Permissão de
  APLICAÇÃO `Mail.Read` + **`ApplicationAccessPolicy` limitando o aplicativo a
  essa caixa**: sem ela, o segredo abre TODAS as caixas do tenant. O módulo não
  marca como lida, não move e não apaga — "já processei" é estado NOSSO
  (`dfe_email_mensagem`), porque estado de coleta guardado no sistema do
  fornecedor some quando alguém arruma a caixa postal.
  As duas portas são TABELAS SEPARADAS (`dfe_documento` × `dfe_arquivo`) e uma
  lista só na LEITURA: lá a identidade é o cursor `(cnpj, nsu)`, aqui é o
  `sha256` do arquivo, e inventar NSU para o que veio de fora corromperia a
  varredura. Três regras que custam caro se erradas: **mensagem lida fica
  registrada mesmo sem render documento** (senão é reaberta para sempre); **o
  que a Saúde mede é a EXECUÇÃO da coleta, não a chegada de e-mail** (semana sem
  XML deixaria o cartão vermelho acusando uma rotina sã); e **"sem protocolo"
  não é "só resumo"** — são duas ausências do mesmo XML que pedem coisas
  diferentes de quem lê. Guards: `tests/sefaz/test_caixa_email.py`,
  `tests/frontend/test_dfe_duas_portas.py`.
- **`with suppress(ImportError)` em volta de binding é bomba-relógio.** A
  `erpbrasil.edoc` importa os bindings legados assim; sem o `six` os nomes
  `distDFeInt`/`retDistDFeInt` somem SEM erro e a falha reaparece como
  `NameError` no meio da consulta. `six` está em `[project.dependencies]` por
  isso, com guard — um `uv sync` que o deixe cair não quebra import nenhum.
- **TLS**: tudo sai por `api/tls.contexto()` (certifi, 118 raízes — o armazém
  do Windows em serviço SISTEMA fica incompleto e "self-signed in chain"
  significa RAIZ FALTANDO).
- **WhatsApp**: o freio conta destinatários DISTINTOS normalizados, POR
  instância; grupo conta como UM; não existe troca automática de número; o
  envio consulta o estado antes (aceitar ≠ entregar); sem "modo teste" frouxo.
- **Playground de fornecedor sem URL livre** — a tela manda ID do catálogo, o
  SERVIDOR monta o caminho; endpoints de envio listados e BLOQUEADOS; parâmetro
  que entra em segmento de URL é validado.
- Posição de veículo: `api/posicoes.py` funde Gobrax + ERP e **vence a leitura
  mais recente**; toda posição diz de onde veio e que idade tem.

---

## 8. Segurança

1. **O repo do código é PÚBLICO** (github.com/cassoli2016/cortex-sulista).
   Segredo, telefone/PII, print de painel e dado real de negócio NUNCA entram
   em commit, migration, seed ou issue pública. Issues/anexos de report vão
   para `REPORT_REPO` (privado) — conferir a visibilidade do destino ANTES
   (`gh repo view --json visibility`). Saída de depuração não se redireciona
   para arquivo na raiz (um `> '%s'` já publicou as contas bancárias da
   empresa; conferir `git status` antes de todo commit).
2. RBAC fail-closed no middleware (seção 6); `/api/gestao` é só admin; agente
   de IA herda o RBAC do usuário.
3. Toda escrita entra no `audit_log` — auditoria ANTES da ação externa.
   **Uso é outra pergunta e outra tabela** (`aud_sessoes`/`aud_telas`, tela
   `aud`): a trilha de ações é append-only e imutável; a sessão é linha VIVA,
   com "visto por último". Duração = `coalesce(fim, visto_em) − inicio`, nunca
   `now()` (391 logins × 11 logouts: ninguém sai pelo botão, e a aba esquecida
   viraria 14 h). "Aberta agora" é CALCULADO, não coluna. A coleta nunca
   levanta — e por isso a falha dela é MUDA e tem cartão na Saúde. Grava-se a
   CHAVE da tela (validada; vem do navegador) e o horário: **nunca** filtro,
   parâmetro ou conteúdo.
4. Segredos: cofre/`.env` (nunca versionado) e arquivos protegidos por
   `api/segredo_arquivo.proteger()` com a Saúde MEDINDO a ACL.
5. PII: CPF não entra em URL nem aparece inteiro; o snapshot do Copiloto leva
   só **KPIs escalares** (sem nome, placa, CNPJ) — e é isso, não um filtro
   mágico, que permite o fallback externo do chat.
6. Senha: hash argon2; provisória só gerada pelo sistema, com troca obrigatória,
   fora da trilha e do log (sem O/0/l/1/I).
   **"Esqueci minha senha" NÃO reusa a provisória**: pedir o link não pode tocar
   na conta, senão quem souber um e-mail derruba o acesso de quem quiser. É
   token de uso único com prazo (`senha_reset`, `sql/cortex/0038_*`), gravado
   em SHA-256, entregue no **fragmento** da URL (`#redefinir=`, que não chega
   ao servidor nem ao log do Cloudflare) e apagado da barra de endereço na
   leitura. Consumir invalida os outros links em aberto, faz `token_ver+1` e
   limpa o bloqueio por tentativas. **Formulário público responde IGUAL para
   e-mail que existe e que não existe** — mesmo texto, mesmo código, inclusive
   quando o envio falha (senão vira lista de quem trabalha aqui); usuário
   inativo cai no mesmo silêncio, e há freio de 3 pedidos/hora que também não
   se anuncia.
7. E-mail de segredo: devolver a senha na resposta só quando o ENVIO falhou;
   ação externa vai DEPOIS do commit e a falha AVISA sem derrubar o cadastro.

---

## 9. Rodar, testar e entregar

### Rodar local

```bash
uv sync --group test                  # SEM --group test ele DESINSTALA pytest/playwright
uv run playwright install chromium    # 1ª vez e a cada bump do playwright
uv run uvicorn api.main:app --reload  # API local (produção usa scripts/run_api.ps1, porta 8010)
```

### Testar

```bash
uv run pytest -q                          # ~2.787 testes (31/08/2026)
node --test "tests/frontend/*.test.js"    # núcleo do indicador de carga
uv run python scripts/verificar_estrutura.py
uv run python scripts/medir_paineis.py    # régua de altura das telas
uv run python scripts/auditar_tema.py     # + --fixo; e auditar_superficies.py
uv run python scripts/auditar_espacos.py  # escala 9/18/25
```

Suíte COMPLETA nesta árvore colide com o AutoDeploy (seção 1) — worktree, ou
overlay `uv run --no-sync --with pytest --with playwright==<lock> pytest …`.

### Entregar — OBRIGATÓRIO EM TODA ENTREGA

1. **Bumpar `pyproject.toml`** (SemVer; fonte única do número). Recurso novo
   retrocompatível sobe o MENOR; correção sobe a CORREÇÃO.
2. **Bloco em `docs/versoes.yaml`** (topo = corrente = pyproject; escrever o
   que a pessoa que USA percebe).
3. **`uv run python scripts/gerar_changelog.py`** (CHANGELOG.md é gerado —
   não editar à mão).
4. **Conferir a tela `#doc`**: grupo/tela/termo novo entra em
   `docs/manual.yaml` (um teste cobra toda view de `VIEWS` com grupo).

Commit + push no mesmo minuto (seção 1). Rótulo: `CX-DD/MM/AAAA-vX.Y.Z` (data
DA VERSÃO), no rodapé da sidebar e em `GET /api/versao` (autenticado).

**O `1.0.0` FOI DECLARADO em 06/09/2026**, por decisão de quem opera, com os
três critérios conferidos NA HORA — e não pela afirmação que estava escrita
aqui. Os verificadores são `scripts/testar_restauracao.py` (o backup restaura,
a API sobe apontada para a cópia e os módulos leem dela) e
`scripts/conferir_numeros.py` (os números batem entre si; as três receitas
conferidas uma contra a outra). `docs/RECONCILIACAO.md` guarda o estado.

**E a lição que o 1.0.0 quase carregou junto:** até 06/09 este parágrafo dizia
"cumpridos desde 30/08/2026" enquanto os DOIS verificadores morriam no meio —
um com `KeyError` desde 02/09 (levando junto a cascata da DRE e as três
receitas), o outro com `UnicodeEncodeError`. A afirmação sobreviveu aos
instrumentos. Por isso **os dois agora são EXECUTADOS pela suíte**
(`tests/reconciliacao/test_conferidor_executa.py`) e não apenas conferidos por
leitura de texto: critério cuja prova não roda não é critério, é frase.

---

## 10. Agentes e skills (`.claude/`)

Agentes de desenvolvimento em `.claude/agents/` (orquestrador, financeiro,
comercial, operacional, programacao, torre_controle, torre_seguranca,
telemetria, frota, jornada, suprimentos, gestao, integracoes,
analista_preditivo) e skills em `.claude/skills/` (dashboard-builder — LER
antes de criar painel —, calculo-ckm, fluxo-de-caixa, make-vs-buy,
analise-rota, scoring-cliente, telemetria-insights, programacao-cargas,
jornada-motorista, previsao-projecao, dre-analise, analista-contabil,
metas-okr, ata-reuniao, connector-builder, relatorio-pdf). São ferramentas de
DESENVOLVIMENTO — não há agente em runtime no painel.

---

## 11. Onde está o resto

| Documento | O que tem |
|---|---|
| `docs/LICOES.md` | **As crônicas completas** — toda lição citada aqui, com o que foi medido |
| `docs/MIGRACAO_POSTGRES.md` | A migração SQLite→Postgres: plano, decisões, armadilhas |
| `docs/RECONCILIACAO.md` | O que se confere contra o ERP e onde já divergiu |
| `docs/manual.yaml` | Grupos, resumos e glossário da tela `#doc` |
| `docs/versoes.yaml` → `CHANGELOG.md` | Histórico de versões (gerado) |
| `docs/ARQUITETURA.md`, `sql/schema.sql`, `sql/blocks/` | **Arquitetura PLANEJADA original — não é o estado atual** |
| Memória do agente (`memory/MEMORY.md`) | Deploy desta máquina, gotchas de bancada, estados de integração |
