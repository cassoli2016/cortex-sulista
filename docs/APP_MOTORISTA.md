# App do Motorista — escopo inicial

> Rascunho de escopo, branch `feat/app-motorista`, worktree `cortex-motorista`.
> **Nada aqui foi implementado.** Este documento é o acordo do que se vai
> construir, na ordem, e — mais importante — do que NÃO se vai construir e por
> quê. Ele muda a cada rodada de ajuste com quem opera.
> Data do rascunho: 05/09/2026 · base: `main` em v0.255.0.

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

O caminho é o mesmo que `cliop` abriu, porque ele já foi discutido e tem guard:
uma coluna em `usuarios` (`motorista_codigo`, casando com `cadastro.codigo` do
ERP), **NULL como estado normal e SEGURO**, e um `escopo()` que **levanta**
quando não há vínculo — nunca devolve `None`, que alguém adiante trataria como
"sem filtro". Nenhuma consulta deste módulo se monta sem um código de motorista.

Um usuário com `motorista_codigo` **não escolhe** de quem quer ver. Se mandar
um código na requisição, o servidor ignora — igual ao `cliop`.

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

**O vínculo não é só uma coluna, é um cadastro que alguém mantém.** Ele casa
`usuarios.motorista_codigo` com `cadastro.codigo`, e quem entra pelo telefone só
vira usuário quando o telefone bate com UM motorista ativo. Motorista que sai da
casa (ou agregado que troca de transportadora) tem de perder o acesso — e isso
não acontece sozinho: **é regra de desligamento**, e entra na tela de
administração da fase 1, com a data do último frete à vista de quem administra.

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

O app é **PWA**: a casa já tem `manifest.json`, `sw.js` e Web Push
(`api/push.py`, VAPID) funcionando. Manifest e service worker **próprios** para
esta página — o da casa aponta para o `index.html`.

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
- **Chat.** A casa já tem WhatsApp; um segundo canal de conversa é um canal que
  ninguém lê e uma expectativa de resposta que ninguém atende.
- **Qualquer número de dinheiro da empresa** — frete, custo, CKM, resultado.
- **Escrita no ERP.**
- **Aprovação de nada.** O motorista relata; quem decide é a casa.
