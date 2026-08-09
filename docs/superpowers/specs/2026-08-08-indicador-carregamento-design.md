# Indicador de carregamento nas telas

Data: 2026-08-08

## Problema

O painel parece travar. Ao abrir uma tela ou aplicar um filtro, a única
resposta visual é o conteúdo esmaecer para 55% de opacidade e parar de aceitar
cliques (`index.html:94`):

```css
.content.loading{opacity:.55;pointer-events:none}
```

Nada se move. Numa consulta ao AVA (PostgreSQL 9.3, via túnel SSH) que leva 10,
20 ou 40 segundos, o usuário não distingue "consultando" de "morreu". Na
primeira visita a uma tela é pior: os miolos (gráficos SVG, tabelas) estão
vazios, então a tela é uma moldura pálida e imóvel.

O problema é maior nas ações internas. Das 78 chamadas de API do arquivo, só 41
são carga de tela e passam pelo esmaecer. As outras ~37 — drill-down da DRE,
ficha de veículo/cliente, série mensal da premiação, exportação de planilha,
modais — não têm feedback nenhum. Você clica e não acontece nada por segundos.

## Solução

Uma barra de progresso animada no topo da área de conteúdo, alimentada por um
interceptador de `fetch`, com contador de tempo decorrido para esperas longas.

O `.content.loading` atual permanece intocado — o esmaecer continua sendo o
comportamento correto para a carga de tela e já está testado em produção.

### Decisão central: interceptar o `fetch`, não editar as chamadas

O arquivo **já tem** um wrapper de `window.fetch` (`index.html:10107`), que
devolve o usuário ao login quando qualquer chamada responde 401. O contador
entra dentro dele, num `try/finally`:

```js
const _fetch0 = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const u = String(typeof input==='string' ? input : (input && input.url) || '');
  const conta = u.startsWith('/api/') && !_cargaFundo(init);
  if (conta) CARGA.inicia();
  try{
    const r = await _fetch0(input, init);
    if (r.status===401 && u.startsWith('/api/') && !u.startsWith('/api/auth/')) { … }
    return r;
  } finally { if (conta) CARGA.termina(); }
};
```

Criar um segundo wrapper seria errado por dois motivos. Empilharia dois
interceptadores sobre a mesma função; e, pior, `_fetch0` passaria a apontar para
o wrapper novo — as chamadas de boot e login usam `_fetch0` **de propósito**,
para escapar do tratamento de 401, e passariam a acender a barra antes de haver
sessão.

`conta` é falso em dois casos, e só nesses dois: a URL não começa com `/api/`,
ou o `init` traz o header `X-Carga-Fundo`.

| | Editar as 78 chamadas | Interceptar o `fetch` |
|---|---|---|
| Cobertura | o que for lembrado | 78 fetches, hoje e no futuro |
| Vazamento do contador | alto risco | impossível por construção |
| Tamanho do diff | ~78 pontos | 1 ponto + CSS |

O risco de vazamento é concreto, não teórico. Os loaders de hoje seguem este
padrão:

```js
finally{ if(seq===loadSeq){ btn.disabled=false; content.classList.remove('loading'); } }
```

O `remove` está **dentro** do `if(seq===...)`. Isso funciona porque `classList`
é um flag idempotente: uma resposta obsoleta que não executa o `remove` não
causa dano, porque a resposta vigente vai executar o dela. Um contador de
referências no mesmo lugar se comportaria de outro jeito — toda resposta
obsoleta (trocar de filtro duas vezes rápido, algo corriqueiro) deixaria o
contador acima de zero e a barra girando para sempre. É o bug clássico de
spinner eterno.

O `.finally()` de uma Promise sempre executa, independente de guarda de corrida,
de `catch` vazio ou de erro de rede. Por isso o contador vive no interceptador,
não nos loaders.

### Núcleo: contador de cargas simultâneas

Cargas concorrentes são normais (a tela + a série de um gráfico, por exemplo),
então um booleano não serve.

```
cargaInicia()   n: 0→1   arma timer de 150ms  → mostra a barra se ainda houver carga
                         arma timer de 3s     → mostra o contador, tique de 1s
cargaInicia()   n: 1→2   nada muda (já visível)
cargaTermina()  n: 2→1   barra continua
cargaTermina()  n: 1→0   esconde barra e contador, cancela timers, zera o t0
```

O tempo é medido a partir da **primeira** carga do lote (`t0` gravado quando `n`
sai de 0), não da última. Medir da última faria o contador voltar a zero no meio
de uma espera longa, que é exatamente quando ele importa.

### Limiares

| Tempo | Comportamento | Motivo |
|---|---|---|
| 0–150 ms | nada | resposta de cache não faz a tela piscar |
| 150 ms | barra desliza | |
| 3 s | contador aparece, atualiza a cada 1 s | prova de vida na espera longa |

Texto do contador: `consultando o banco… 12s`.

### Aparência

A barra ocupa a borda inferior da topbar, que já existe
(`.topbar{border-bottom:1px solid var(--n200)}`, `index.html:80`). A linha
divisória "acende" durante o carregamento. Posicionamento absoluto: **zero
deslocamento de layout**.

```
┌─────────────────────────────────────────────┐
│  DRE Gerencial                   ↻ Atualizar│  ← topbar
│  Sulista Transportes                        │
├▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░─┤  ← 3px, sobre a borda
│  ┌─────────────────────────┐                │
│  │ consultando o banco… 12s │               │  ← só aos 3s
│  └─────────────────────────┘                │
```

```css
.topbar    { position:relative }              /* no mobile já é sticky */
#loadbar   { position:absolute; left:0; right:0; bottom:-1px; height:3px;
             overflow:hidden; background:var(--orange-100) }
#loadbar i { position:absolute; top:0; bottom:0; width:35%;
             background:var(--orange-500);
             animation:loadslide 1.15s cubic-bezier(.4,0,.2,1) infinite }
@keyframes loadslide { 0%{left:-35%} 100%{left:100%} }
```

Cor: `--orange-500`. A regra da paleta está escrita no próprio arquivo
(`index.html:24-26`) — `--brand` (#FFD31C) só em superfície escura por causa do
contraste de 1,44:1 no branco; o accent da UI clara é o laranja. A barra fica
sobre a topbar branca. Esta decisão não abre a frente de cor/marca que está
adiada.

O contador é um cartão ancorado abaixo da barra, com `role="status"` e
`aria-live="polite"` — o leitor de tela anuncia sem interromper o que está
sendo lido.

No mobile a topbar já é `position:sticky;top:0;z-index:40`
(`index.html:303`), então a barra acompanha o scroll sem código adicional. O
cartão do contador recua de `left:24px` para `left:14px`, acompanhando o padding
da topbar mobile.

### Movimento reduzido

Com `prefers-reduced-motion: reduce`, a barra vira faixa cheia com pulsação
lenta de opacidade (2 s), sem deslizamento lateral. Continua comunicando
atividade sem disparar enjoo em quem configurou a preferência.

### O que não aciona a barra

Sem estas exclusões a barra vira ruído permanente e perde o significado.

| Caso | Tratamento |
|---|---|
| Tela **Saúde do servidor**, auto-refresh de 5 s (`index.html:2964`) | `loadSrv(fundo)` — o tique automático envia o header `X-Carga-Fundo`; o clique em Atualizar continua acusando |
| **Torre**, auto-refresh de 120 s (`index.html:2961`) | mesmo tratamento, em `loadTorre(fundo)` |
| **Painéis de TV** (tvfat/tvope), auto-refresh de 60 s | `body.tvmode #loadbar{display:none}` — é telão, ninguém está esperando resposta |
| **Clima** (open-meteo, `index.html:5740,5786`) | fora de `/api/`, o interceptador já ignora |
| **Impressão** | `@media print` esconde barra e contador |

A distinção entre automático e clicado vem de um header no `init`, não do
endpoint. Isso importa porque `loadSrv()` é a mesma função nos dois casos:
filtrar por endpoint mataria também o feedback do clique manual. São 2 funções a
receber o parâmetro.

## Fora de escopo

- **Skeleton de tabelas e gráficos.** A barra foi escolhida justamente para não
  abrir essa frente. Os `skelKpis()` existentes ficam como estão, nas telas onde
  já estão.
- **`.content.loading`.** Continua com o esmaecer de 55% e o bloqueio de clique.
- **Backend.** Nenhuma mudança.

## Verificação

Playwright já está instalado no `.venv` e o Node 24 traz `node --test` embutido,
então não há infra a criar. A verificação é em três camadas:

**1. Núcleo, com `node --test`.** O contador sai para `api/static/carga.js`,
sem tocar em DOM nem em `fetch` — recebe relógio, timers e as funções de
exibição por injeção. Com o tempo virando uma variável, os limiares de 150 ms e
3 s são testados de forma determinística, em vez de esperar o relógio a cada
asserção. Cobre o refcount, que é onde mora o bug de barra eterna.

O arquivo novo é servido de graça: `app.mount("/static", StaticFiles(...))`
(`api/main.py:76`) já expõe o diretório inteiro. Nenhuma rota nova.

**2. Integração, com Playwright.** Contra o `index.html` real, com um
`http.server` servindo `api/` e todas as rotas `/api/**` interceptadas com
atraso controlado — sem banco, sem túnel, sem AVA. Cobre CSS, DOM, o wrapper de
fetch e as exclusões, incluindo a contraprova (a mesma rota, sem o header, tem
de acender).

**3. Roteiro manual, rodando local.** O que nenhum dos dois alcança:

- trocar de filtro duas vezes em sequência rápida (resposta obsoleta — o teste
  de vazamento do contador)
- abrir a DRE e confirmar que o contador aparece aos 3 s e conta de 1 em 1
- abrir e fechar um drill-down
- derrubar a API e confirmar que a barra some mesmo com erro no `catch`
- ficar 1 minuto na tela de Saúde do servidor e confirmar que nada pisca
- repetir no mobile, com scroll (a barra tem que acompanhar a topbar sticky)
- carga rápida (dado em cache) não pode fazer a barra piscar

## Arquivos

**Criar:**

- `api/static/carga.js` — núcleo do contador, sem DOM, testável em Node
- `tests/frontend/carga.test.js` — testes do núcleo com timers falsos
- `tests/frontend/test_barra_e2e.py` — integração com Playwright
- `CHANGELOG.md` — registro por versão (ver "Versão e documentação")

**Modificar** `api/static/index.html`, em quatro pontos:

1. bloco de estilo: `#loadbar`, `#loadtempo`, keyframes, `@media print`,
   `prefers-reduced-motion`, regra do `tvmode`, ajuste mobile
2. markup da topbar: `<div id="loadbar">` e `<div id="loadtempo">`
3. `<script src="/static/carga.js">` antes do script principal
4. o wrapper de `fetch` existente (`index.html:10107`) ganha o `try/finally`, e
   `loadSrv()`/`loadTorre()` ganham o parâmetro `fundo`

## Versão e documentação

Esta entrega inaugura o versionamento do projeto, que ficou em `0.1.0` desde o
commit inicial. O estado atual em produção vira **1.0.0**; este trabalho,
**1.1.0** — recurso novo, retrocompatível.

- `pyproject.toml` é a **fonte única** da versão. `api/main.py` a lê com
  `tomllib` e a expõe em `GET /api/versao`; o rodapé da sidebar mostra `v1.1.0`.
  Duas fontes divergentes seriam piores que nenhuma: o painel diria uma coisa e
  o repositório, outra.
- A versão na tela existe por um motivo concreto: o deploy é por AutoDeploy no
  Windows, e hoje não há como saber, olhando o painel, qual build está no ar.
- `CHANGELOG.md` na raiz, em português, seções Adicionado/Alterado/Corrigido.
  O histórico anterior a 1.0.0 fica nos commits — não será reconstruído.
- `CLAUDE.md` (seção 5) recebe as lições deste trabalho, no mesmo padrão das
  demais telas.
