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
`VIEW_GROUP` no `index.html`). Hoje: 72 telas em RBAC + 4 fora
(`srv`, `gestao`, `jornf`, e `sup`, que é de TODO usuário logado —
`TELAS_TODO_LOGADO`), organizadas assim:

| Grupo | Telas | Fonte principal |
|---|---|---|
| Início | home, cop (Copiloto) | snapshot de KPIs |
| Financeiro | fluxo, receber, cob, banc, extb, lanc, antec, antport, rec, fluxcon, pagar | AVA + locais `ext_*`, `ant_*`, `prev_*` |
| Operação | milkrun, agr, mvb, km, prog, torre, jorn, cex, sac, port, pedagio, poli | AVA + `jor_*`, `ped_*`, `tt_*`, posições Gobrax+ERP |
| Comercial | com, clif, crm, drecli | AVA + `crm_*` (banco local) |
| Controladoria | dre, bal, cont, qual, orc, fech, ctecp | AVA + `orc_*`, `prev_*`, contrapartida |
| Suprimentos | oc, custos, pecas | AVA (`ordemcompra` × vínculo de NF × `aprovador`, estado em `api/suprimentos_oc.py`; preço de peça pela mediana do produto em `api/suprimentos_pecas.py`) |
| Frota | comb, man (+ sub-abas Compras da OS e Recompra de peça), veic, mprev, comrast, veicf, mul, pneus | AVA + `smt_*` (Smartec) + `data/pneus/` + `api/manutencao_compras.py` |
| Telemetria | prem, telcon, telcond, telhod | Gobrax (`api/gobrax/`) + `prem_*` |
| Recursos Humanos | rh, hc, folha, folhaind, cnh, ferias, people, he | AVA (folha/Globus) |
| ANTT | anpiso, anrntrc | `config/antt_coeficientes.yaml`, `config/antt_cargas.yaml`, `rntrc_*` |
| Business Intelligence | prodveic, tvfat, tvope, tvdir | AVA (tvdir lê a mesma /api/visao-geral da home) |
| Gestão | gesacao, gesata | `ges_*` (banco local) |
| Suporte | sup, supfila | `sup_*` no banco local + espelho opcional no GitHub |
| Administração | doc, aud | `index.html` (doc); `aud_*` + `audit_log` (auditoria de uso, `api/auditoria.py`) |

As tabelas locais vivem em `sql/cortex/` (39 migrations): auth/usuários/fotos,
push, correio, previsão, antecipações, extrato, orçamento, contrapartida,
WhatsApp (`zap_*`), gestão (`ges_*`), jornada RasterJOR (`jor_*`), premiação,
favoritos, TomTom (`tt_*`), CRM (`crm_*`), notificações, Smartec (`smt_*`),
pedágio (`ped_*`), suporte (`sup_*`).

**A unidade de RBAC é a TELA** (perfil × tela via `perfis`/`perfil_telas`,
`sql/cortex/0011_auth.sql`). Não há RLS.

**TELA NOVA TEM SEIS REGISTROS, NÃO UM**: `view-x` no HTML + `VIEWS` +
`auth.TELAS` + `ROTA_TELAS` + `VIEW_GROUP` + drawer do celular + `ICONS` +
índice de busca + `docs/manual.yaml`. Essa classe de defeito não tem sintoma,
só ausência (ícone que some, tela fora do celular) — **rodar a suíte COMPLETA
para tela nova**; os guards moram em arquivos que não falam do assunto.
- **Tela de todo usuário logado** (`sup`) entra em `TELAS_TODO_LOGADO`
  (`auth.py`): fora do perfil, dentro dos favoritos, da busca e do menu;
  `podeVer` a libera pela sessão. A rota dela vai em `_ROTAS_SEM_TELA`.
- **SUB-ABA não é tela** e não se registra em lugar nenhum (herda RBAC, ícone e
  menu da tela que a contém). A pergunta que separa: o roteador abre por hash?
- **Ao aposentar uma tela, a substituta HERDA o id** (`jorn`, `crm`, `mul`) —
  é RBAC: id novo faria a tela sumir do menu de quem já tinha acesso. Só herda
  quem substitui MESMO.
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
  LEITURA BOA carimbada (`leitura_velha`, `leitura_em`, idade) quando a
  consulta falha, e a tela é OBRIGADA a mostrar a tarja — número velho servido
  calado é pior que tela vazia, porque ninguém desconfia dele. É opt-in
  (`get_visao_geral`: 2 h), devolve CÓPIA (quem recebe não corrompe o cache) e
  passado o prazo vira erro.
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
- **JOIN com tabela de vigência/histórico multiplica linhas e o total inflado é
  PLAUSÍVEL** — tabela com `dtvigencia`/`versao`/`_hist` entra por
  `DISTINCT ON (chave) … ORDER BY chave, data DESC NULLS LAST`, nunca join
  direto; `max(a)`+`max(b)` são máximos independentes; conferir a contagem dos
  dois lados de CADA join novo (o total mudou de ordem de grandeza? é o join).
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
- **Em rota `async def`, todo I/O bloqueante passa por `sem_travar()`**
  (`api/main.py`) — senão trava o servidor INTEIRO pelo tempo da chamada.
  O `TestClient` não pega; `tests/test_rotas_nao_travam.py` sobe uvicorn real.
- **Serialização converte no LIMITE do módulo** (`float()`, `.isoformat()`);
  o `JSONResponse` da casa é a rede (Decimal/date estouram DEPOIS do
  `try/except` da rota, em `render()` — 500 em `text/plain` sem pista).
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
  agendador do Windows).

### Cortes, testes e conferências

- **Corte por marcador**: o fim é DERIVADO por busca a partir do início
  (regex `^(?:async function|function|const|let|var|class)\s+(\w+)`), nunca
  string escolhida a olho; depois de todo corte, comparar as declarações contra
  o **HEAD do git** e exigir `sumiram: nenhuma`. O `git diff --stat` denuncia
  antes de qualquer teste. Editar o `index.html` por fatia: memória
  `editar-index-html-por-fatia`.
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
- **Verde que nunca ficaria vermelho não conferiu nada** — sabotar o alvo e ver
  o teste falhar leva trinta segundos; campo ausente em conferidor vira ACHADO,
  não silêncio.
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
  pedágio já estava no ERP.
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

**O `1.0.0` é DECLARADO, não derivado** — os três critérios (restauração de
backup provada por `scripts/testar_restauracao.py`; reconciliação com o ERP em
`docs/RECONCILIACAO.md` + `scripts/conferir_numeros.py`, hoje sem divergência;
as três receitas conferidas entre si) **estão cumpridos desde 30/08/2026**.
Virar 1.0.0 é decisão de quem opera.

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
