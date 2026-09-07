# App do Motorista — escopo inicial

> Escopo e acordo do app, branch `feat/app-motorista`, worktree
> `cortex-motorista`. Diz o que se vai construir, na ordem, e — mais
> importante — o que NÃO se vai construir e por quê. Muda a cada rodada de
> ajuste com quem opera.
> Rascunho 05/09/2026 · **núcleo da fase 1 construído em 06/09/2026** (§0) ·
> **cinco telas + acesso mestre entregues em 07/09/2026 na v1.1.0** (§0-ter) ·
> **canal com o RH em 07/09/2026 na v1.2.0** (§0-quater) ·
> base: `main` em v0.255.0.

---

## 0-ter. A rodada de 07/09/2026 (v1.1.0) — o que entrou, e o que se mediu

Pedido de quem opera, textual: **multas do motorista, indicadores da Gobrax que
ele precisa melhorar e como melhorar, ocorrências registradas para ele,
produtividade dos últimos 30 dias e jornada** — mais um acesso de administração
que abra o app de qualquer motorista, para validar as informações.

### As cinco fontes, e a cobertura MEDIDA antes de construir

Medido em 07/09/2026 contra o banco vivo, sobre os **80 vínculos ativos**:

| Tela | Fonte | Casamento | Cobertura |
|---|---|---|---|
| Multas | `smt_infracoes` × viagem da placa no instante | placa + janela da viagem | 156 infrações → **39 dos 80** |
| Condução | Gobrax `driversOverview` + `vehicle-performance` | nome normalizado | 73/80 no cadastro · 60/80 na performance de agosto |
| Registros | `cadastro_vinculo_motoristaocorrencia` (AVA) | `cnpjcpfcodigo` | **44 dos 80** em 12 meses |
| 30 dias | `programacaoembarque` | `motorista` | **68 dos 80** com viagem |
| Jornada | `jor_jornadas` (RasterJOR) | dígitos do CPF | **70 dos 80** |

### As sete decisões que custaram medição

1. **A multa é HIPÓTESE, e a tela diz.** `smt_infracoes.motorista_nome` existe e
   é inútil: 2 de 212 traziam nome de gente, o resto vinha "AGREGADO", "NIC",
   "RECURSO" — estados do processo de indicação. O vínculo real sai do
   cruzamento que a coleta já fazia contra o AVA, e ele agora grava o motorista
   (`smt_infracao_viagem.motorista_codigo`, migration 0062). "A viagem estava
   com o Fulano" **não é** "o Fulano cometeu a infração".
2. **Ponto de CNH só conta na penalidade.** Somar a pontuação das notificações
   junto inflou o primeiro motorista medido de 4 para 47 pontos — a notificação
   é a autuação, estágio em que ainda cabe defesa.
3. **Não existe indicador por motorista na Gobrax.** Foi medido, não suposto: o
   `driversOverview` devolve `ID`, `Name`, `DocumentNumber`, `TotalKM` e
   `Score`, e nada mais. Os 14 indicadores são do VEÍCULO, e o payload carrega
   quantas pessoas dividiram o volante no mês.
4. **O conselho sai do QUARTO PIOR, não da mediana.** Pela mediana, metade da
   frota é cobrada em cada indicador por construção — com catorze indicadores,
   todo mundo recebe três conselhos todo mês e a tela vira ruído. E pega
   diferença que não é diferença: freio motor 0,0% contra mediana de 0,93% da
   frota vira "melhore o freio motor" sem que haja o que melhorar.
5. **"Demérito" não é dito ao premiado.** 40 dos 54 tipos de ocorrência ainda
   estão com a PROPOSTA automática de classificação; só 14 foram decididos por
   uma pessoa. O que se destaca é o mérito, e só quando um humano classificou.
   O texto livre da ocorrência (`observacao`, `reclamacao`) não sai.
6. **A jornada não promete saldo do dia.** A fonte é a apuração FECHADA por
   dia. Um app que somasse as horas de ontem para dizer "faltam 2h10"
   inventaria o saldo de hoje a partir de dado que não é de hoje — e o
   motorista pararia, ou não, com base nisso. Quem responde "posso dirigir
   agora?" é o equipamento na cabine.
7. **A produtividade se compara com ELE MESMO.** A referência óbvia seria a
   média da frota, e ela está proibida: o leitor não é gestor, é a pessoa
   medida. O km vem de `kmfretecompra` (100% de cobertura), não de
   `jor_jornadas.km`, que traz `NULL` e absurdo (155 km contra 179 h de direção
   no mesmo motorista).

### O acesso mestre

Um segredo da casa no cofre (`MOTORISTA_CODIGO_MESTRE`) abre uma sessão NORMAL
na conta de quem for escolhido — mesmas rotas, mesmo escopo vindo da sessão —
marcada `mestre`, com prazo de 8 h e **tarja vermelha obrigatória** na tela.
**Não é um perfil de administração dentro do app: não existe rota que devolva a
operação de vários motoristas de uma vez.** A única lista é de id e nome, para
escolher, e ela não abre sessão nenhuma. Seis contenções, escritas em
`api/motorista/mestre.py`; "não configurado" é `info` na Saúde, nunca vermelho.

**O que falta para usar:** pôr o código no cofre (Gestão → credenciais, chave
`MOTORISTA_CODIGO_MESTRE`, mínimo 16 caracteres). Sem ele o acesso não existe e
a Saúde do Servidor diz exatamente isso.

---

## 0. O que já está construído (06/09/2026, branch `feat/app-motorista`)

O núcleo da fase 1: **entrar** e **minha viagem**. Nada foi entregue ao `main`
e a migration NÃO foi aplicada em produção — de propósito, porque o escopo
ainda está em ajuste e migration aplicada trava o conteúdo do arquivo.

| | |
|---|---|
| `sql/cortex/0057_motorista.sql` | `mot_vinculos` (quem é motorista no app), `mot_codigos` (só o SHA-256), `mot_sessoes` (linha viva, com "visto por último") |
| `api/motorista/__init__.py` | o CONTRATO do módulo — o que sai, o que não sai, e por que a identidade é separada |
| `api/motorista/sessao.py` | cookie `cortex_mot`, JWT com `tipo`, 30 dias deslizantes, `exigir()` que levanta |
| `api/motorista/entrada.py` | código de 6 dígitos no WhatsApp, resposta uniforme, quatro contenções |
| `api/motorista/viagem.py` | a viagem em curso, com a rede de última leitura boa na janela da casa (2 h) |
| `api/static/motorista.html` | **16 KB**, uma coluna, sem vendor, sem webfont, claro e escuro |
| `scripts/vincular_motoristas.py` | cadastra e desliga vínculos, em ondas (`--limite`), sem escrever nada sem `--aplicar` |
| Saúde do Servidor + snapshot do Copiloto | no mesmo commit, como manda a casa |
| `tests/motorista/` | 41 testes; 5 guards **provados por sabotagem** (sem eles o teste fica vermelho) |

**Provado ponta a ponta contra o ERP de verdade**: pedir código → confirmar →
cookie → a viagem em curso de um motorista real (Cruzeiro/SP → Sete Lagoas/MG,
placa + carreta, saída e previsão), com o WhatsApp dublado — nada saiu da
máquina.

### 0-bis. O código de entrada sai pelo número PRINCIPAL (decidido em 06/09/2026)

A pergunta estava em aberto: principal (o que fala com clientes) ou reserva?
Três razões fecharam nele, e a primeira é a única que não é opinião.

**1. A capacidade não é o problema — e a premissa contrária estava errada.**
Este documento dizia que "cadastrar 300 motoristas de uma vez não cabe" no teto
de 60 destinatários distintos por dia. Isso foi escrito olhando o TETO e nunca o
CONSUMO. Medido em `zap_envios` (28 dias):

| | destinatários distintos/dia |
|---|---|
| mediana | **2** |
| pior dia | 3 |
| teto | 60 |

Sobram ~58 vagas por dia. O gargalo de onboarding é de dias de calendário
(~300 ÷ 58 ≈ 6 dias), e mesmo isso é teórico — ninguém instala um app inteiro no
mesmo dia. A reserva resolveria um aperto que não existe.

**2. A reserva existe para NÃO ser gasta.** `api/whatsapp/cliente.py` diz isso
ao recusar troca automática: disparar pela reserva quando a principal cai
"queimaria o segundo número também, que é justamente o que não se pode perder".
Um fluxo automático, recorrente e crescente — todo login de todo motorista, para
sempre — é o que gasta reputação. Pôr o app ali transforma o pneu step em pneu
de rodagem.

**3. O código precisa CHEGAR e ser ACREDITADO.** O motorista já recebe recado da
torre pelo número principal: o código chega numa conversa que ele reconhece.
Vindo de um número desconhecido, "seu código é 123456" tem a forma exata de um
golpe — e código ignorado é login que não acontece, que é o único jeito de este
app falhar por inteiro.

`MOTORISTA_ZAP_INSTANCIA` continua existindo como escape: se um dia o app
sozinho responder por parcela grande do envio diário, trocar é uma linha de
`.env`. O que se decidiu é o PADRÃO, não uma amarra.

### O que falta para alguém usar de verdade

1. **Aplicar a migration 0057** em produção (`scripts/migrar_schema.py`). Até
   lá o app recusa todo mundo, e a Saúde do Servidor diz exatamente isso.
2. **Cadastrar os primeiros vínculos** (`scripts/vincular_motoristas.py
   --aplicar --limite N`), em ondas por causa do teto de 60 destinatários/dia
   do WhatsApp — ver §6.
3. **A tela de administração no painel** (vincular, desligar, ver quem entrou).
   Hoje isso é script; script é suficiente para a piloto, não para a operação.
4. ~~Decidir a instância do WhatsApp~~ — **decidido em 06/09/2026: o número
   PRINCIPAL** (§0-bis).
5. Versão e bloco em `docs/versoes.yaml` — ficam para a entrega ao `main`, com
   o número combinado com as outras worktrees (são nove).

---

## 0-quater. O canal com o RH (v1.2.0) — e a regra do §10 que ele contraria

**Este documento põe CHAT na lista do que fica de fora** (§10), com uma razão
que continua boa: *"a casa já tem WhatsApp; um segundo canal de conversa é um
canal que ninguém lê e uma expectativa de resposta que ninguém atende"*.

Quem opera pediu o canal assim mesmo, em 07/09/2026. A razão do §10 não foi
ignorada — foi ENDEREÇADA no desenho, e é isso que faz a decisão ser diferente
de simplesmente desobedecer:

> **isto não é conversa, é FILA COM ASSUNTO, DONO E ESTADO** — a mesma forma
> dos chamados do Suporte (`sup_chamados`), que já funciona na casa há tempo.

| O que o §10 temia | O que impede aqui |
|---|---|
| "ninguém lê" | a caixa do RH ordena do MAIS PARADO, e **"paradas há 3+ dias" é o primeiro KPI da tela** — e vai também para a Saúde do Servidor |
| "expectativa que ninguém atende" | assunto de LISTA FECHADA + `status` + `atribuido_id`: "aberta há N dias" é número, não sensação |

**O §10 continua valendo para o que ele de fato proíbe.** Não há caixa de texto
sem assunto, não há conversa sem dono, não há mensagem que não caiba numa fila
com fim. Se um dia a fila estiver cheia e velha, a Saúde vai dizer — e aí a
decisão de manter ou desligar se toma com o número na mesa, que é a única forma
de ela ser diferente da que o §10 tomou no escuro.

### O que foi construído

| | |
|---|---|
| `sql/cortex/0063_motorista_rh.sql` | `mot_assuntos` (a lista fechada, em TABELA — o RH acrescenta assunto sem esperar entrega), `mot_conversas`, `mot_mensagens` (append-only) |
| `api/motorista/conversas.py` | os dois lados no mesmo módulo; o escopo do motorista entra na cláusula `WHERE`, junto do id |
| tela `rhmot` (painel) | a caixa do RH, com os seis registros de sempre |
| aba **RH** no app | assuntos com texto de ajuda, pedidos, comunicados e a confirmação de leitura |
| `tests/motorista/test_conversas.py` + `tests/frontend/test_rhmot_e2e.py` | 30 guards; 7 provados por sabotagem |

### As decisões que não se negociam depois

1. **O ESCOPO ENTRA NA CLÁUSULA, NÃO NUM `if`.** Esta é a primeira coisa do
   app em que o navegador manda um IDENTIFICADOR DE LINHA — até aqui todo
   escopo saía da sessão e não havia o que forjar. O `motorista_codigo` da
   sessão vai no `WHERE` junto do id; um `if` conferindo o dono depois da
   busca é a linha que alguém apaga, e o sintoma é ler a conversa de outra
   pessoa.
2. **A recusa é a MESMA para "não existe" e "não é sua"** — distinguir as duas
   transformaria a rota num contador de conversas alheias.
3. **O aviso do WhatsApp não leva conteúdo nem assunto, e NÃO abre a janela de
   horário.** `entrada.py` abre a janela de propósito (código de entrada é
   resposta a quem está esperando às 03:40); aqui é o contrário — resposta do
   RH é mensagem de empresa, que é o que a janela existe para conter.
4. ~~**Comunicado em massa não existe.**~~ **Existe desde a v1.3.0, e como o
   OUTRO OBJETO que esta linha já nomeava — um MURAL, sem fila e sem
   resposta** (`api/motorista/mural.py`, migration 0064). O que continua
   valendo é a razão: publicar não abre conversa nenhuma, e há guard
   (`test_publicar_NAO_cria_conversa_nenhuma`) provando isso — 300 linhas na
   caixa destruiriam a ordem por mais parado e o "paradas há 3+ dias", que
   são os dois números que fazem dela uma fila.

   O público é FOTOGRAFADO na publicação (uma linha por destinatário, no ato):
   quem entra depois não deve ciência do que é anterior, e a fração não muda
   de denominador sozinha a cada admissão. "Abriu" e "confirmou" são campos
   diferentes — são duas conversas diferentes com a pessoa.

   **O aviso em massa por WhatsApp continua fora**, e é a mesma conta: 60
   destinatários distintos por dia contra ~300 motoristas são cinco dias de
   ondas gastando o número que fala com clientes, e no quinto dia o comunicado
   já não é notícia. Quem avisa é a marca no app.
5. **A caixa do RH não devolve o `motorista_codigo`** (é o CPF para pessoa
   física). Só id opaco e nome, como no acesso mestre e na escolha da entrada.
6. **Anexo e foto ficam para depois, de propósito.** Foto de documento é metade
   do valor deste canal e é também upload, limite, tipo, ACL e retenção — o
   `sup_anexos` já mostrou que isso é um módulo, não um campo. O que não se faz
   é meia implementação de upload num canal que trata de documento de
   trabalhador.
7. **A tela `rhmot` fica SÓ no perfil de Recursos Humanos**, e a Diretoria não
   entra. A caixa mostra o que trabalhador escreveu sobre férias, benefício e
   saúde: a lista de quem enxerga precisa ser a menor possível, e tela nova
   acaba dentro do perfil amplo por inércia.

### O código mestre passou a se gerar no CÓRTEX

Gestão → Integrações → *App do motorista — acesso da administração* → **gerar**.
O código sai forte (≈140 bits, sem O/0/l/I/1 porque é lido de uma tela e
digitado noutra), vai para o cofre no mesmo instante e é mostrado UMA vez. A
alternativa era digitar 24 caracteres aleatórios num `.env` de produção — o que
dá um de dois finais: ou ninguém configura, ou alguém escolhe algo memorizável.

---

## 1. Para quem é, e onde a pessoa vai abrir isto

O leitor é o **motorista**, no celular dele, com a mão suja, na cabine, num 4G
de beira de rodovia, muitas vezes com a tela no sol. Não é gente da casa, não
tem crachá, não vai lembrar de senha e não vai abrir chamado quando algo não
funcionar — vai ligar para a torre, que é exatamente o custo que este app
existe para tirar.

Três consequências que valem mais que qualquer lista de funcionalidade:

1. **Tudo tem de caber num polegar.** Alvo de toque grande, uma coluna, sem
   tabela larga, sem gráfico. A régua de painel da casa (`medir_paineis.py`)
   não serve aqui: ela mede desktop de 900px. Este app precisa de régua
   própria, de celular.
2. **Tem de abrir rápido e funcionar mal conectado.** O `index.html` da casa
   tem 2,5 MB. Servir isso para um motorista em 4G de rodovia é entregar uma
   tela branca. Ver a decisão da seção 3.
3. **Toda ação do motorista é uma AFIRMAÇÃO sobre o mundo físico** ("cheguei",
   "carreguei", "quebrei"). Ela tem hora e lugar, e vale exatamente o que a
   evidência que vier junto valer. Ver seção 6.

---

## 1-bis. O que já se mediu (05/09/2026, banco vivo)

Duas das perguntas em aberto foram medidas antes de escrever o resto, porque
elas mudam o escopo — não a implementação.

**Quantos são, e quem são** (`programacaoembarque`, motorista pelo `tipofrota`
predominante dele nos últimos 90 dias):

| | motoristas | viagens 90d |
|---|---|---|
| **agregado** (`tipofrota=3`) | **162** | 9.399 |
| **próprio** (`tipofrota=1`) | 79 | 4.334 |
| terceiro (`tipofrota=2`) | 58 | 276 |

606 motoristas distintos em 12 meses; **299 nos últimos 90 dias**, 237 nos
últimos 30. Esse é o universo real de instalação: ~300, não 600.

**A leitura que reescreve o escopo: a maioria não é empregado.** Dois terços
dos motoristas ativos e dois terços das viagens são de AGREGADO. Um app
desenhado como ferramenta de RH — jornada, premiação, documentos — atende 79
pessoas e um terço da operação. O motorista agregado não recebe ordem da casa:
ele precisa de um motivo PRÓPRIO para instalar (a viagem dele, o documento
dele, o problema dele resolvido sem telefonema), e a casa precisa **pedir**, não
mandar. Os 58 de terceiro (0,28 viagem/dia cada) não são público de app: são
eventuais, e forçá-los a instalar é fricção pura.

**Telefone celular** (`cadastro.celular`, validado pelo validador único da casa,
`api/whatsapp/numeros.py`): **285 de 299 ativos em 90 dias = 95,3%**, todos
distintos. Em 12 meses, 585 de 606 (96,5%), com **5 números repetidos** entre
motoristas diferentes.

- O campo `celular` já carrega DDI+DDD (13 dígitos em 524 dos 606). Concatenar
  `dddcelular` com ele **quebra o número** — dá 0,2% de válidos. Quem for ler
  isto lê `celular` sozinho, pelo `numeros.normalizar()`, e não inventa
  concatenação.
- **Os 5 repetidos são um requisito, não um detalhe**: telefone compartilhado
  significa que o mesmo canal serve duas identidades. O login por código tem de
  perguntar QUEM é quando o número casar com mais de um motorista, e o vínculo
  fica no aparelho, não no número.

Cobertura de 95,3% resolve a pergunta do login: **dá para entrar por telefone.**

---

## 2. A terceira pergunta de acesso

O RBAC da casa respondia UMA pergunta: **que tela você abre** (perfil × tela,
`sql/cortex/0011_auth.sql`). O portal do cliente (`cliop`, 05/09/2026)
introduziu a segunda: **quais linhas são suas**, via `usuarios.cliente_cnpj_raiz`.

Este app traz a terceira, e ela é a mais estreita das três: **qual motorista
você é**. Não é "as linhas da minha empresa" — é "as linhas de UMA pessoa", e
essa pessoa é PII inteira (CPF, CNH, jornada, salário indireto via premiação).

**ESTE RASCUNHO DIZIA "uma coluna em `usuarios`", COPIANDO O `cliop`. NA
IMPLEMENTAÇÃO (06/09/2026) A DECISÃO MUDOU**, e a razão vale mais que a
mudança. O usuário do `cliop` é gente que loga no PAINEL: tem e-mail, tem
senha, e o perfil dele decide telas. O motorista não abre o painel — abre
`motorista.html`, não tem tela nenhuma e entra por código no WhatsApp. Pô-lo em
`usuarios` custaria três coisas:

1. ~300 contas de painel cujo único obstáculo contra abrir o CÓRTEX inteiro
   seria um perfil com zero telas;
2. e-mail sintético para 485 dos 606 motoristas (só 121 têm e-mail) —
   identidade inventada por nós, que ninguém confere, no lugar onde a
   identidade segura tudo;
3. `/api/auth/esqueci-senha` é público e trabalha por e-mail: motorista em
   `usuarios` herdaria esse caminho de graça.

**O motorista vive em `mot_vinculos`**, com cookie próprio (`cortex_mot`,
`path=/api/motorista` — o navegador nem o envia ao painel), sessão própria
(`mot_sessoes`) e porteiro próprio (`sessao.exigir()`, que LEVANTA — nunca
devolve `None`, que alguém adiante trataria como "sem filtro"). O preço é uma
segunda autenticação para manter; o que se compra é que **nenhuma sessão de
motorista alcança rota nenhuma do painel**.

O que NÃO mudou do `cliop` é o que importa: o escopo vem da SESSÃO, nunca do
pedido. `viagem.minha(sessao)` não tem parâmetro de motorista, e há teste que
falha se alguém acrescentar um.

### Como o motorista entra (medido; falta só confirmar a escolha)

Três caminhos, com o que cada um custa:

| | Como funciona | O que ganha | O que custa |
|---|---|---|---|
| **a. CPF + senha** | reusa `usuarios`, argon2, senha provisória, `senha_reset` | zero código novo de auth; já tem guard e trilha | é a pior UX possível para este leitor; ~N motoristas × esquecimento = fila no RH |
| **b. Telefone + código por WhatsApp** (recomendado) | Z-API já está no ar; código de 6 dígitos, sessão longa presa ao aparelho | o motorista já tem WhatsApp e já recebe recado da torre por ele; nada para decorar; **cobertura medida: 95,3%** (§1-bis) | OTP tem freio e trilha próprios para escrever; telefone repetido exige escolher quem é |
| **c. Link assinado por motorista** | como o link do rastreio (`api/rastreio/`) | zero fricção | **reprovado**: link encaminhado = identidade de outra pessoa, e aqui a carga é PII de terceiro, não posição de carga |

A recomendação é **(b) com (a) de retaguarda**: quem não tiver telefone
cadastrado entra por CPF+senha, e o RH corrige o cadastro depois. Com 95,3% de
cobertura, a retaguarda atende ~14 pessoas — é exceção, não segundo caminho.

**O vínculo não é só uma linha, é um cadastro que alguém mantém.** Ele casa
`mot_vinculos.motorista_codigo` com `cadastro.codigo` do ERP, e quem entra pelo
telefone só entra quando o número bate com um motorista VINCULADO e ativo —
ter dirigido para a empresa não basta. Motorista que sai da casa (ou agregado
que troca de transportadora) tem de perder o acesso, e isso **não acontece
sozinho**: é regra de desligamento, com gente responsável. Hoje o cadastro e o
desligamento saem por `scripts/vincular_motoristas.py`; a tela de administração
é o próximo passo (§0).

---

## 3. Página própria (`motorista.html`), não uma tela no `index.html`

Vale escrever a razão, porque a regra da casa é "página única" e isto é uma
exceção deliberada, não um esquecimento:

- **Peso.** `index.html` são 2,5 MB antes do ECharts (990 KB). Nenhum motorista
  vai esperar isso, e o app é justamente para quem tem a pior conexão da
  empresa. `motorista.html` nasce com alvo de **< 150 KB**, sem ECharts, sem
  Leaflet, sem vendor.
- **Precedente na casa:** `rastreio.html` (30 KB) já é página estática própria,
  servida pelo mesmo FastAPI, com rota própria em `main.py`. O padrão existe e
  funciona.
- **RBAC.** A unidade de RBAC da casa é a TELA de um perfil. Este app não tem
  telas de perfil — tem um leitor só, com um escopo só. Enfiá-lo no `VIEWS`
  seria criar um perfil "motorista" que enxerga o menu da casa com 71 itens
  escondidos, e um dia um deles vaza.
- **O que continua no `index.html`:** a tela da CASA que administra isto —
  vincular usuário↔motorista, ver os apontamentos que chegaram, conciliar com
  o ERP. Essa é tela de perfil normal, com os seis registros de sempre.

**PWA fica para depois, de propósito.** A casa já tem `manifest.json`, `sw.js`
e Web Push (`api/push.py`, VAPID) funcionando, e o app vai querer os três — com
manifest e service worker PRÓPRIOS, porque os da casa apontam para o
`index.html`. Mas service worker é cache, e cache mal feito serve uma versão
velha do app para sempre, sem sintoma e sem jeito de o motorista limpar. Ele
entra quando houver o que instalar de verdade (fase 1 inteira), não junto do
primeiro login. Hoje a página é uma URL que se abre no navegador — o que basta
para a piloto.

---

## 4. O que a casa JÁ tem — e que este app NÃO refaz

Isto é metade do escopo. Cada linha abaixo é trabalho que já está no ar e que o
app **consome**, nunca reimplementa:

| Já existe | Onde | O que o app faz com isso |
|---|---|---|
| Jornada apurada (Lei 13.103) | RasterJOR → `jor_*`, `api/jornada/` | **LÊ e mostra.** O motorista já marca jornada no equipamento da Raster; um segundo apontamento daria dois números de jornada e um deles iria para a folha. Ver seção 6. |
| Posição do veículo | `api/posicoes.py` (Gobrax + ERP) | usa para conferir apontamento (seção 6), nunca para vigiar o motorista |
| Rastreio da carga | `api/rastreio/`, `/r` | o motorista pega o link da carga dele para mandar a quem está esperando |
| Premiação / score | Gobrax → `prem_*`, tela `prem` | mostra ao dono do score o que a casa já calcula |
| Multas e infrações | Smartec → `smt_*`, tela `mul` | mostra as do próprio motorista |
| Abastecimentos | `ctaplus_abastecimentos` (ERP) | histórico e km/l do próprio motorista |
| Push no celular | `api/push.py` (VAPID) | canal de aviso da torre |
| WhatsApp | `api/whatsapp/`, Z-API | OTP de login e aviso para quem não instalar o PWA |
| Ocorrências SAC 394/395/396/397 | `coleta_ocorrencia` (ERP) | é a régua contra a qual o apontamento do app se concilia |
| Viagem | `programacaoembarque` (ERP) | é a fonte de "qual é a minha viagem" |
| Chamado / suporte | `sup_*`, tela `sup` | destino do "avisar problema" |

**E a regra que já custou caro:** tela ou integração nova entra no snapshot do
Copiloto e na Saúde do Servidor **no mesmo commit**.

---

## 5. O escopo, em três fases

### Fase 1 — o mínimo que já vale a pena instalar

O critério: **o motorista tem motivo próprio para abrir**, e a torre para de
receber uma ligação. Nada aqui depende de o motorista lembrar de fazer nada.

Como dois terços do público é agregado (§1-bis), a fase 1 é dividida por quem
ela serve — e o **núcleo tem de valer para os dois**, senão o app nasce servindo
um terço da operação.

**Núcleo, para TODO motorista (próprio, agregado ou terceiro):**

1. **Entrar** — telefone + código (§2), sessão longa presa ao aparelho, sair
   pelo botão.
2. **Minha viagem** — a viagem corrente (`programacaoembarque` com `dtsaida` e
   sem `dtchegada`): cliente, origem, destino, placa do cavalo e da carreta, o
   que está previsto. Um cartão, sem tabela. É o motivo próprio do agregado
   para abrir: hoje ele liga para saber isso.
3. **Avisar problema** — pane, atraso, acidente, carga recusada: um botão, uma
   foto, hora e GPS, e cai na fila da torre (`sup_*`). Substitui a ligação, e é
   o que a torre ganha do agregado também.
4. **O link da carga** — o motorista pega o link do rastreio da carga dele para
   mandar a quem está esperando na doca (`api/rastreio/` já pronto). Custa quase
   nada e tira uma ligação por viagem.

**Só para o motorista EMPREGADO (79 pessoas, `tipofrota=1`), e a tela diz isso:**

5. **Minha jornada, hoje** — o que a RasterJOR já apurou, traduzido para a única
   pergunta que ele faz: **"quanto ainda posso dirigir antes de parar?"** (5h30
   contínuas, intervalo de 30 min, interjornada 11h). Semáforo, não gráfico. Diz
   de quando é a leitura e **avisa quando está velha** — dado de jornada com 6
   horas de atraso não decide parada, e mentir sobre isso é pior que não mostrar.
6. **Meus documentos** — CNH e exames, com o vencimento e o aviso antes (a tela
   `cnh` já tem a fonte).

Item que não existe para o agregado **não aparece vazio** — some, e o app não
diz "sem dados" para quem nunca vai ter dado ali.

### Fase 2 — o motorista vira fonte de dado (o maior ganho, e o mais delicado)

7. **Meus apontamentos** — o motorista marca no celular: cheguei para carregar,
   saí carregado, cheguei para descarregar, terminei a descarga. Hoje isso
   chega por rádio/telefone e vira digitação na torre.
   - É o que alimenta **permanência × freetime** (o portal do cliente já mede
     isso e a cobertura é ~72%), o **ciclo da programação** e a cobrança de
     estadia.
   - **Não substitui o ERP** — ver seção 6, que é a regra inteira desta fase.
8. **Comprovante de entrega** — foto do canhoto no ato, com hora e GPS. O
   documento físico continua vindo; a foto é o que faz o financeiro faturar
   antes.
9. **Meu desempenho** — score, ranking e prêmio previsto (`prem_*`). Entra na
   fase 2 de propósito: número de premiação errado na mão do premiado é
   discussão de salário, então ele só sobe depois que a fase 1 provar o vínculo
   usuário↔motorista.

### Fase 3 — o que só faz sentido depois

10. **Abastecimento** — histórico e km/l próprio; comparação com a frota **só se
   a premiação já usar a mesma régua** (dois números de eficiência circulando
   entre motoristas é briga garantida).
11. **Checklist do veículo** — pré-viagem, com foto. Só depois de decidir se ele
    vira exigência (aí é processo, não app) ou fica opcional (aí ninguém faz).
12. **Recibos e adiantamento** — vale-pedágio, adiantamento de viagem, diária.
    Toca folha e caixa; entra por último e com o financeiro na mesa.
13. **Offline de verdade** — fila local de apontamentos que sobe quando volta o
    sinal. A fase 2 já grava com carimbo de hora do APARELHO e hora do
    SERVIDOR separados, justamente para isto ser possível depois.

---

## 6. As regras duras deste app (as que não se negociam depois)

**O AVA é somente leitura. O app NÃO escreve no ERP.** Todo apontamento do
motorista vai para tabela local (`mot_*`) no banco da casa, carrega
`origem='app'`, e a torre concilia com `coleta_ocorrencia`. O que a tela da casa
mostra é **os dois lados** — o que o app registrou e o que o ERP tem — e a
divergência é o achado, não um número escondido atrás do outro. Fundir os dois
numa coluna só é o jeito de descobrir daqui a seis meses que metade da operação
está sendo medida por um apontamento que ninguém validou.

**Jornada não se aponta duas vezes.** A RasterJOR é a fonte legal e é ela que
vai para a folha. O app **mostra** e **avisa**; não marca, não corrige, não
justifica. Se um dia precisar corrigir, a correção vira pedido para o RH, com
trilha — nunca escrita direta.

**Hora do aparelho não é hora.** O relógio do celular é do motorista e pode
estar errado (ou ajustado). Grava-se **as duas**: `em_aparelho` e `em_servidor`.
Quem decide estadia usa a do servidor; a do aparelho existe para explicar a
diferença quando ela aparecer.

**GPS é evidência, não permissão.** A posição vai junto do apontamento para
dizer *onde ele foi feito*, e é conferida contra a cerca do cliente
(`api/poligonos/`, que já existe) e contra a posição do veículo
(`api/posicoes.py`). **O app não rastreia o motorista em segundo plano** — nem
tecnicamente, nem por decisão. Coleta de posição só no ato de um apontamento, e
a tela diz isso na cara.

**Nada de valor de frete, custo, CKM ou nome de outro motorista.** O leitor vê a
operação DELE. Ranking de premiação é a única coisa comparativa, e só porque a
premiação já é pública entre eles hoje.

**Recusa legível é 4xx** (`HTTP_RECUSA = 409`); 5xx só para falha nossa — o
Cloudflare troca o corpo de 5xx pela página dele e a mensagem nunca chega ao
motorista.

**Tudo que escreve entra no `audit_log`**, e a auditoria vem ANTES da ação
externa.

---

## 7. O que se constrói, em arquivos

```
api/motorista/            módulo novo
  __init__.py             o docstring com estas regras (é o contrato)
  escopo.py               vínculo usuário↔motorista; LEVANTA sem vínculo
  entrada.py              OTP por WhatsApp: envio, verificação, freio, trilha
  viagem.py               a viagem corrente + documentos (lê o AVA)
  jornada.py              leitura do jor_* com a pergunta "posso dirigir?"
  apontamento.py          fase 2 — grava mot_*, concilia, nunca escreve no ERP
api/static/motorista.html a página (< 150 KB, uma coluna, sem vendor)
api/static/motorista.webmanifest + motorista-sw.js
sql/cortex/00NN_motorista.sql   usuarios.motorista_codigo + mot_*
tests/motorista/          guards: escopo que levanta, OTP freado, PII fora
docs/APP_MOTORISTA.md     este arquivo
```

Na casa, no `index.html`: **uma tela nova de perfil** (administrar o vínculo e
conciliar apontamentos) — com os seis registros de sempre (`view-x`, `VIEWS`,
`auth.TELAS`, `ROTA_TELAS`, `VIEW_GROUP`, gaveta do celular, `ICONS`, índice de
busca, `docs/manual.yaml`) e a **suíte COMPLETA** rodando por causa disso.

**Coordenação com as outras 8 worktrees ativas:** número de migration
(`sql/cortex/00NN_`) e número de versão são recurso GLOBAL — worktree nenhuma
isola isso. Combinar ANTES de escrever o bloco.

---

## 8. Como se sabe que funcionou

Não é "o app está no ar". É:

- ligações de "cheguei/saí" para a torre **caem** (medir o volume ANTES);
- a cobertura de permanência sobe dos ~72% de hoje;
- o motorista **volta** sem ninguém mandar — se ele só abre quando o RH pede,
  o app é um formulário e não vale a manutenção.

Medir antes de subir a fase 1, senão não há contra o quê comparar.

---

## 9. As perguntas que decidem o resto (para quem opera)

~~1. Como o motorista entra?~~ e ~~2. Quantos são, e quantos agregados?~~ —
**medidas em 05/09/2026, §1-bis.** Login por telefone está de pé (95,3%), e o
público é majoritariamente agregado, o que já reescreveu a fase 1.

1. **Como se PEDE ao agregado que instale?** Ele não recebe ordem da casa. Vale
   condicionar a alguma coisa (prioridade na alocação? adiantamento mais
   rápido?), ou é convite puro? Esta é a pergunta que decide se o app tem
   usuário — o resto é software.
2. **Celular é do motorista, e o plano de dados também?** Decide se cabe exigir
   qualquer coisa, e o quanto o app pode pesar. (Assumido aqui: é do motorista,
   e o app tem de ser leve o bastante para isso não ser desculpa.)
3. **O apontamento do motorista vai VALER para cobrar estadia do cliente?** Se
   sim, a fase 2 precisa de validação humana antes de virar cobrança — é um
   fluxo a mais, não um campo a mais.
4. **A RasterJOR já tem app de motorista em uso pelos 79 empregados?** Se tiver,
   o motorista já carrega um app, e a jornada sai da fase 1 (fica só o aviso).
5. **Quem é o dono disto do lado da operação?** App de motorista sem alguém que
   cobre o uso vira ícone que ninguém abre.
6. **O que a torre gasta hoje com telefone?** Sem esse número medido ANTES, não
   há como provar que o app funcionou (§8).

---

## 10. O que fica FORA, de propósito

- **Rastreamento contínuo do motorista.** Não é para isso.
- ~~**Chat.**~~ **Revisto em 07/09/2026 (v1.2.0), e o argumento continua de
  pé.** O que entrou não foi chat: foi FILA COM ASSUNTO, DONO E ESTADO, com a
  fila parada medida na tela e na Saúde do Servidor. Ver §0-quater — inclusive
  o que continua proibido: caixa de texto sem assunto, conversa sem dono, e
  mensagem que não caiba numa fila com fim.
- **Qualquer número de dinheiro da empresa** — frete, custo, CKM, resultado.
- **Escrita no ERP.**
- **Aprovação de nada.** O motorista relata; quem decide é a casa.
