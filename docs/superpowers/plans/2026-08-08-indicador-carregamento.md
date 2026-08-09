# Indicador de Carregamento nas Telas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar retorno visual de carregamento em todas as telas e ações do painel, para que uma consulta lenta ao AVA se leia como "carregando" e não como "travou".

**Architecture:** Uma barra animada sobre a borda inferior da topbar, acionada por um contador de cargas simultâneas que vive dentro do wrapper de `window.fetch` **já existente** no arquivo. O núcleo do contador sai para `api/static/carga.js`, sem dependência de DOM, para poder ser testado com `node --test`. Aos 3 segundos entra um contador de tempo decorrido.

**Tech Stack:** HTML/CSS/JS puro (o painel é um arquivo único servido pelo FastAPI, sem build). Testes: `node --test` (embutido no Node 24, nada a instalar) e Playwright (já presente no `.venv`).

## Global Constraints

- **Cor:** `--orange-500` (#E85D10). `--brand` (#FFD31C) é proibido em superfície clara — contraste 1,44:1. Regra em `index.html:24-26` e no CLAUDE.md seção 5.
- **Texto do contador:** exatamente `consultando o banco… ` + segundos + `s`. Reticências em caractere único `…`, não três pontos.
- **Limiares:** barra aos **150 ms**, contador aos **3000 ms**, tique de **1000 ms**. Tempo medido desde a **primeira** carga do lote.
- **Edição do `index.html` sempre por substituição literal de trecho conhecido.** Nunca regex ampla, nunca correção de aspas em massa — o CLAUDE.md (seção 5) documenta que isso já derrubou a Visão Geral inteira, e que `node --check` não pega.
- **Após qualquer mexida no `index.html`:** `uv run python scratchpad/estrutura.py` e `node --check` sobre o bloco de script.
- **Não usar `CC`** (paleta em JS) em nenhuma estrutura de topo — TDZ mata o script no boot. As cores deste trabalho são todas CSS.
- Nenhuma dependência nova.
- **Toda entrega bumpa a versão e atualiza a documentação** (Task 5). O projeto ficou em `0.1.0` desde o commit inicial; esta é a entrega que inaugura o versionamento: o estado atual em produção vira **1.0.0** e este trabalho, **1.1.0** (recurso novo, retrocompatível).

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `api/static/carga.js` **(criar)** | Núcleo do contador: refcount, limiares, timers. Sem DOM, sem `fetch` — recebe tudo por injeção, para ser testável em Node. Servido automaticamente por `app.mount("/static", StaticFiles(...))` (`api/main.py:76`) — nenhuma rota nova. |
| `tests/frontend/carga.test.js` **(criar)** | Testes do núcleo com timers falsos. `node --test`. |
| `tests/frontend/test_barra_e2e.py` **(criar)** | Teste de integração com Playwright: CSS, DOM, wrapper de fetch e exclusões, contra o `index.html` real. |
| `api/static/index.html` **(modificar)** | CSS da barra, markup na topbar, `<script src>`, ligação no wrapper de fetch existente, parâmetro `fundo` em `loadSrv`/`loadTorre`, versão no rodapé da sidebar. |
| `CHANGELOG.md` **(criar)** | Registro por versão, em português. Começa em 1.0.0 (estado atual); não reconstrói histórico anterior. |
| `pyproject.toml` **(modificar)** | Fonte única da versão. |
| `api/main.py` **(modificar)** | `VERSAO` lida do `pyproject.toml` + rota `GET /api/versao`. |
| `CLAUDE.md` **(modificar)** | Lições deste trabalho na seção 5, no padrão das demais telas. |

---

### Task 1: Núcleo do contador (`carga.js`) com testes em Node

Esta é a task que carrega o risco real. O bug a prevenir é a barra eterna: um contador que não volta a zero. Por isso ela vem primeiro e é a única com teste automatizado do comportamento.

**Files:**
- Create: `api/static/carga.js`
- Test: `tests/frontend/carga.test.js`

**Interfaces:**
- Consumes: nada.
- Produces: global `criarCarga(dep)` → `{ inicia(), termina(), ativas() }`.
  `dep` = `{ agora, arma, desarma, repete, cessa, mostraBarra, mostraTempo }`.
  `agora()` → ms. `arma(fn, ms)` → id. `desarma(id)`. `repete(fn, ms)` → id. `cessa(id)`.
  `mostraBarra(visivel: boolean)`. `mostraTempo(visivel: boolean, segundos: number)`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/frontend/carga.test.js`:

```js
/* Testes do núcleo do indicador de carregamento. Timers falsos: o tempo é
   uma variável, não o relógio — senão o teste dos limiares de 150ms/3s
   levaria segundos e piscaria conforme a carga da máquina. */
const test = require('node:test');
const assert = require('node:assert');
const { criarCarga } = require('../../api/static/carga.js');

function bancada() {
  let t = 0, id = 0;
  const tarefas = new Map();            // id -> {quando, fn, intervalo}
  const barra = { visivel: false };
  const tempo = { visivel: false, seg: null };

  const c = criarCarga({
    agora: () => t,
    arma: (fn, ms) => { const i = ++id; tarefas.set(i, { quando: t + ms, fn, intervalo: 0 }); return i; },
    desarma: (i) => tarefas.delete(i),
    repete: (fn, ms) => { const i = ++id; tarefas.set(i, { quando: t + ms, fn, intervalo: ms }); return i; },
    cessa: (i) => tarefas.delete(i),
    mostraBarra: (v) => { barra.visivel = v; },
    mostraTempo: (v, s) => { tempo.visivel = v; tempo.seg = v ? s : null; },
  });

  function avanca(ms) {
    const alvo = t + ms;
    for (;;) {
      let escolhidoId = null, escolhido = null;
      for (const [i, tar] of tarefas) {
        if (tar.quando <= alvo && (escolhido === null || tar.quando < escolhido.quando)) {
          escolhido = tar; escolhidoId = i;
        }
      }
      if (escolhido === null) break;
      t = escolhido.quando;
      if (escolhido.intervalo) escolhido.quando = t + escolhido.intervalo;
      else tarefas.delete(escolhidoId);
      escolhido.fn();
    }
    t = alvo;
  }

  return { c, barra, tempo, avanca, pendentes: () => tarefas.size };
}

test('não mostra nada antes de 150ms', () => {
  const b = bancada();
  b.c.inicia();
  b.avanca(149);
  assert.equal(b.barra.visivel, false);
});

test('mostra a barra aos 150ms', () => {
  const b = bancada();
  b.c.inicia();
  b.avanca(150);
  assert.equal(b.barra.visivel, true);
});

test('carga que termina em 100ms nunca mostra a barra', () => {
  const b = bancada();
  b.c.inicia();
  b.avanca(100);
  b.c.termina();
  b.avanca(5000);
  assert.equal(b.barra.visivel, false);
  assert.equal(b.tempo.visivel, false);
});

test('com duas cargas, terminar a primeira não esconde a barra', () => {
  const b = bancada();
  b.c.inicia();
  b.c.inicia();
  b.avanca(200);
  assert.equal(b.barra.visivel, true);
  b.c.termina();
  assert.equal(b.barra.visivel, true);
  assert.equal(b.c.ativas(), 1);
  b.c.termina();
  assert.equal(b.barra.visivel, false);
});

test('termina() a mais não deixa o contador negativo', () => {
  const b = bancada();
  b.c.termina();
  b.c.termina();
  assert.equal(b.c.ativas(), 0);
  b.c.inicia();
  b.avanca(150);
  assert.equal(b.barra.visivel, true);   // ainda funciona depois do excesso
});

test('contador de tempo aparece aos 3s e segue tiquetaqueando', () => {
  const b = bancada();
  b.c.inicia();
  b.avanca(2999);
  assert.equal(b.tempo.visivel, false);
  b.avanca(1);
  assert.equal(b.tempo.visivel, true);
  assert.equal(b.tempo.seg, 3);
  b.avanca(9000);
  assert.equal(b.tempo.seg, 12);
});

test('o tempo conta desde a PRIMEIRA carga do lote', () => {
  const b = bancada();
  b.c.inicia();          // t=0
  b.avanca(2000);
  b.c.inicia();          // t=2000, não pode reiniciar a contagem
  b.avanca(3000);        // t=5000
  assert.equal(b.tempo.seg, 5);
});

test('ao zerar, não sobra timer pendente', () => {
  const b = bancada();
  b.c.inicia();
  b.avanca(5000);
  assert.equal(b.pendentes() > 0, true);   // o tique está de pé
  b.c.termina();
  assert.equal(b.pendentes(), 0);
  assert.equal(b.barra.visivel, false);
  assert.equal(b.tempo.visivel, false);
});
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
mkdir -p tests/frontend
node --test "tests/frontend/*.test.js"
```

Esperado: FAIL — `Cannot find module '../../api/static/carga.js'`.

- [ ] **Step 3: Escrever o núcleo**

Criar `api/static/carga.js`:

```js
/* Núcleo do indicador de carregamento do painel.

   Vive fora do index.html e sem tocar em DOM nem em fetch: recebe relógio,
   timers e as duas funções de exibição por injeção. É o que permite testar os
   limiares com o tempo controlado (tests/frontend/carga.test.js) em vez de
   esperar 3 segundos de relógio real a cada asserção.

   Carregado como <script> clássico no navegador (define window.criarCarga) e
   como CommonJS no teste (module.exports). */
(function (raiz) {
  'use strict';

  var ATRASO_BARRA = 150;    // ms de espera antes de mostrar a barra: resposta
                             // de cache não pode fazer a tela piscar
  var ATRASO_TEMPO = 3000;   // ms até o contador de segundos aparecer
  var TIQUE = 1000;

  function criarCarga(dep) {
    var n = 0;               // cargas em voo AGORA
    var t0 = 0;              // início da PRIMEIRA carga do lote
    var tBarra = null, tTempo = null, tique = null;

    function decorrido() {
      return Math.round((dep.agora() - t0) / 1000);
    }

    function inicia() {
      n++;
      if (n > 1) return;     // lote já em andamento: nada a rearmar
      t0 = dep.agora();
      tBarra = dep.arma(function () {
        tBarra = null;
        dep.mostraBarra(true);
      }, ATRASO_BARRA);
      tTempo = dep.arma(function () {
        tTempo = null;
        dep.mostraTempo(true, decorrido());
        tique = dep.repete(function () { dep.mostraTempo(true, decorrido()); }, TIQUE);
      }, ATRASO_TEMPO);
    }

    function termina() {
      if (n === 0) return;   // termina() a mais (código futuro, chamada dupla)
                             // não pode empurrar o contador para negativo: se
                             // empurrasse, o próximo inicia() nunca voltaria a
                             // 1 e a barra jamais apareceria de novo
      n--;
      if (n > 0) return;
      if (tBarra !== null) { dep.desarma(tBarra); tBarra = null; }
      if (tTempo !== null) { dep.desarma(tTempo); tTempo = null; }
      if (tique !== null) { dep.cessa(tique); tique = null; }
      t0 = 0;
      dep.mostraBarra(false);
      dep.mostraTempo(false, 0);
    }

    return { inicia: inicia, termina: termina, ativas: function () { return n; } };
  }

  raiz.criarCarga = criarCarga;
  if (typeof module !== 'undefined' && module.exports) module.exports = { criarCarga: criarCarga };
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
node --test "tests/frontend/*.test.js"
```

Esperado: `# pass 8` / `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add api/static/carga.js tests/frontend/carga.test.js
git commit -m "feat(carga): nucleo do indicador de carregamento com refcount e limiares"
```

---

### Task 2: CSS e markup da barra

Sem comportamento ainda — ao fim desta task a barra existe, está escondida, e pode ser inspecionada tirando o `hidden` no DevTools.

**Files:**
- Modify: `api/static/index.html` (CSS antes de `</style>`; markup na topbar; lista do `@media print`)

**Interfaces:**
- Consumes: nada.
- Produces: `#loadbar` e `#loadtempo` no DOM, ambos com atributo `hidden` inicial. A Task 3 os controla trocando a propriedade `.hidden`.

- [ ] **Step 1: Adicionar a barra e o contador à lista do `@media print`**

Substituir (está em `index.html:743-744`, dentro de `@media print`):

```
  #sidebar,.filterbar,.btn-filtros,.bottomnav,.drawer,#btnRefresh,
  .cop-bar,.cop-chips,.avwrap,.banner{display:none !important}
```

por:

```
  #sidebar,.filterbar,.btn-filtros,.bottomnav,.drawer,#btnRefresh,
  .cop-bar,.cop-chips,.avwrap,.banner,#loadbar,#loadtempo{display:none !important}
```

- [ ] **Step 2: Adicionar o CSS**

Localizar o fim do bloco `@media (display-mode: standalone){...}` seguido de `</style>` (fim do CSS, por volta da linha 771-775). Inserir o bloco abaixo **imediatamente antes** de `</style>`:

```css
/* ---- indicador de carregamento ----
   Mora sobre a borda inferior da topbar: durante a carga a linha divisória que
   já existe "acende". Absoluto de propósito — nada no layout se desloca, e a
   topbar do mobile já é sticky (z-index 40), então a barra acompanha o scroll
   de graça.

   POSIÇÃO DESTE BLOCO NÃO É ACIDENTE: o @media prefers-reduced-motion lá de
   cima zera animation-iteration-count em TODO elemento com !important. Sem a
   regra explícita aqui embaixo, a barra pararia no fim do keyframe
   (left:100%, fora da tela) e ficaria INVISÍVEL justamente para quem pediu
   menos movimento. */
.topbar{position:relative}
#loadbar{position:absolute;left:0;right:0;bottom:-1px;height:3px;z-index:41;
  overflow:hidden;background:var(--orange-100)}
#loadbar[hidden]{display:none}
#loadbar i{position:absolute;top:0;bottom:0;width:35%;background:var(--orange-500);
  animation:loadslide 1.15s cubic-bezier(.4,0,.2,1) infinite}
@keyframes loadslide{0%{left:-35%}100%{left:100%}}
#loadtempo{position:absolute;left:24px;top:100%;margin-top:6px;z-index:41;
  background:var(--n0);border:1px solid var(--n200);border-radius:var(--radius-md);
  box-shadow:var(--shadow);padding:4px 10px;font-size:12px;color:var(--n600);
  white-space:nowrap}
#loadtempo[hidden]{display:none}
@media(max-width:880px){#loadtempo{left:14px}}
/* painel de TV recarrega sozinho a cada 60s e ninguém está esperando resposta */
body.tvmode #loadbar,body.tvmode #loadtempo{display:none}
@media (prefers-reduced-motion: reduce){
  #loadbar i{left:0;width:100%;
    animation:loadpulse 2s ease-in-out infinite !important;
    animation-duration:2s !important;
    animation-iteration-count:infinite !important}
}
@keyframes loadpulse{0%,100%{opacity:.35}50%{opacity:1}}
```

- [ ] **Step 3: Adicionar o markup na topbar**

Substituir (em `index.html:891-892`):

```
  <main>
    <div class="topbar">
      <div>
```

por:

```
  <main>
    <div class="topbar">
      <div id="loadbar" hidden><i></i></div>
      <div id="loadtempo" role="status" aria-live="polite" hidden></div>
      <div>
```

`role="status"` + `aria-live="polite"` fazem o leitor de tela anunciar o tempo sem
interromper a leitura em curso. `hidden` nos dois: o estado inicial é invisível.

- [ ] **Step 4: Verificar que nada estrutural quebrou**

```bash
uv run python scratchpad/estrutura.py
```

Esperado: saída sem erros, código de saída 0.

- [ ] **Step 5: Conferir a barra a olho**

```bash
uv run uvicorn api.main:app --port 8010
```

Abrir `http://127.0.0.1:8010/`, no DevTools remover o atributo `hidden` de `#loadbar`.
Esperado: faixa laranja de 3px sobre a borda da topbar, com um segmento deslizando da
esquerda para a direita em loop. Nada no layout se moveu.

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html
git commit -m "feat(carga): barra e contador na topbar (CSS e markup)"
```

---

### Task 3: Ligar no wrapper de fetch e excluir as recargas automáticas

**Files:**
- Modify: `api/static/index.html` — `<script src>` antes da linha 2526; wrapper em `10106-10113`; `loadTorre` em `8573`; `loadSrv` em `10421`; router em `2961` e `2964`

**Interfaces:**
- Consumes: `criarCarga(dep)` da Task 1; `#loadbar`/`#loadtempo` da Task 2.
- Produces: global `CARGA` (`{inicia, termina, ativas}`) e `_cargaFundo(init)`. `loadSrv(fundo)` e `loadTorre(fundo)` passam a aceitar um booleano.

- [ ] **Step 1: Carregar o `carga.js` antes do script principal**

Substituir `<script>` na linha 2526 (é a **primeira** ocorrência de `<script` no arquivo — confirmar com `grep -n "<script" api/static/index.html`) por:

```html
<script src="/static/carga.js"></script>
<script>
```

- [ ] **Step 2: Estender o wrapper de fetch que já existe**

O arquivo **já tem** um wrapper de `window.fetch` (`index.html:10107`), que devolve o
usuário ao login em 401. Não criar um segundo: além de empilhar dois interceptadores,
`_fetch0` passaria a ser o novo wrapper, e as chamadas de boot/login que usam `_fetch0`
de propósito (para escapar do tratamento de 401) passariam a acender a barra antes
mesmo de haver sessão.

Substituir o trecho:

```js
/* ---------------- Autenticação, sessão e permissões ---------------- */
const _fetch0 = window.fetch.bind(window);
window.fetch = async (input, init) => {       // 401 em qualquer chamada => volta ao login
  const r = await _fetch0(input, init);
  const u = String(typeof input==='string' ? input : (input && input.url) || '');
  if (r.status===401 && u.startsWith('/api/') && !u.startsWith('/api/auth/')) { USER=null; pararTimers(); mostrarLogin('login'); }
  return r;
};
```

por:

```js
/* ---------------- Autenticação, sessão e carregamento ---------------- */
/* O contador de cargas vive AQUI, no wrapper de fetch, e não dentro dos
   loaders. Os loaders soltam o `content.loading` dentro de `if(seq===...)`:
   funciona para um flag idempotente, mas um contador no mesmo lugar vazaria a
   cada resposta obsoleta (trocar de filtro duas vezes rápido, coisa de todo
   dia) e a barra ficaria girando para sempre. O finally abaixo roda em
   qualquer desfecho, inclusive erro de rede. */
const CARGA = criarCarga({
  agora:   () => Date.now(),
  arma:    (fn,ms) => setTimeout(fn,ms),
  desarma: (i) => clearTimeout(i),
  repete:  (fn,ms) => setInterval(fn,ms),
  cessa:   (i) => clearInterval(i),
  mostraBarra: (v) => { const e=document.getElementById('loadbar'); if(e) e.hidden = !v; },
  mostraTempo: (v,s) => {
    const e=document.getElementById('loadtempo'); if(!e) return;
    if(v) e.textContent = 'consultando o banco… '+s+'s';
    e.hidden = !v;
  },
});
/* Recarga automática não acende a barra: a tela de Saúde recarrega a cada 5s e
   a barra piscaria o dia inteiro, virando ruído. Quem marca é o timer, não a
   URL — assim o clique em "Atualizar" dessas mesmas telas continua acusando. */
function _cargaFundo(init){
  const h = init && init.headers;
  if(!h) return false;
  if(typeof h.get === 'function') return !!h.get('X-Carga-Fundo');
  return !!(h['X-Carga-Fundo'] || h['x-carga-fundo']);
}
const _fetch0 = window.fetch.bind(window);
window.fetch = async (input, init) => {       // 401 em qualquer chamada => volta ao login
  const u = String(typeof input==='string' ? input : (input && input.url) || '');
  const conta = u.startsWith('/api/') && !_cargaFundo(init);
  if (conta) CARGA.inicia();
  try{
    const r = await _fetch0(input, init);
    if (r.status===401 && u.startsWith('/api/') && !u.startsWith('/api/auth/')) { USER=null; pararTimers(); mostrarLogin('login'); }
    return r;
  } finally { if (conta) CARGA.termina(); }
};
```

- [ ] **Step 3: Silenciar a recarga automática da Torre**

Substituir as 6 primeiras linhas de `loadTorre` (`index.html:8573-8578`):

```js
async function loadTorre(){
  skelKpis('kpis-torre',4);
  const seq = ++torreSeq;
  const btn=document.getElementById('btnRefresh');
  btn.disabled=true;
  document.getElementById('content').classList.add('loading');
  try{
    const q=qsView('torre');
    const r=await fetch('/api/operacao/torre?'+q,{cache:'no-store'});
```

por:

```js
async function loadTorre(fundo){
  if(!fundo) skelKpis('kpis-torre',4);
  const seq = ++torreSeq;
  const btn=document.getElementById('btnRefresh');
  // o tique de 120s não esmaece a tela nem desabilita o botão: a torre fica
  // aberta o dia todo e piscava a cada 2 minutos
  if(!fundo){ btn.disabled=true; document.getElementById('content').classList.add('loading'); }
  try{
    const q=qsView('torre');
    const opt={cache:'no-store'}; if(fundo) opt.headers={'X-Carga-Fundo':'1'};
    const r=await fetch('/api/operacao/torre?'+q, opt);
```

E substituir o `finally` de `loadTorre` (`index.html:8586`):

```js
  finally{ if(seq===torreSeq){ btn.disabled=false; document.getElementById('content').classList.remove('loading'); } }
```

por:

```js
  finally{ if(seq===torreSeq && !fundo){ btn.disabled=false; document.getElementById('content').classList.remove('loading'); } }
```

- [ ] **Step 4: Silenciar a recarga automática da Saúde do servidor**

Substituir em `loadSrv` (`index.html:10421-10427`):

```js
async function loadSrv(){
  if(!USER || !USER.admin) return;
  const seq=++srvSeq;
  const primeira = !DATASRV;
  if(primeira) document.getElementById('content').classList.add('loading');
  try{
    const r=await fetch('/api/gestao/servidor',{cache:'no-store'});
```

por:

```js
async function loadSrv(fundo){
  if(!USER || !USER.admin) return;
  const seq=++srvSeq;
  const primeira = !DATASRV;
  if(primeira) document.getElementById('content').classList.add('loading');
  try{
    const opt={cache:'no-store'}; if(fundo) opt.headers={'X-Carga-Fundo':'1'};
    const r=await fetch('/api/gestao/servidor', opt);
```

- [ ] **Step 5: Marcar as chamadas dos timers como de fundo**

Substituir (`index.html:2961`):

```js
  if(torre){ torreTimer=setInterval(()=>{ if(currentView()==='torre') loadTorre(); }, 120000); }
```

por:

```js
  if(torre){ torreTimer=setInterval(()=>{ if(currentView()==='torre') loadTorre(true); }, 120000); }
```

Substituir (`index.html:2964`):

```js
  if(v==='srv'){ srvTimer=setInterval(()=>{ if(currentView()==='srv') loadSrv(); }, 5000); }
```

por:

```js
  if(v==='srv'){ srvTimer=setInterval(()=>{ if(currentView()==='srv') loadSrv(true); }, 5000); }
```

As demais chamadas de `loadSrv`/`loadTorre` são via `LOADMAP` (`index.html:2996`) e via
o mapa `M` de `reloadCurrent` (`index.html:4731-4734`), ambas sem argumento — `fundo`
chega `undefined`, que é falso. Confirmar com
`grep -n "loadSrv(\|loadTorre(" api/static/index.html`: devem existir exatamente as
chamadas citadas aqui, mais as duas declarações.

- [ ] **Step 6: Validar sintaxe e estrutura**

```bash
uv run python scratchpad/estrutura.py
node --check api/static/carga.js
```

Esperado: ambos sem saída de erro, código 0.

Para validar o JS embutido no HTML, extrair o bloco principal e conferir:

```bash
uv run python -c "
import re, subprocess, sys, pathlib
h = pathlib.Path('api/static/index.html').read_text(encoding='utf-8')
blocos = re.findall(r'<script>(.*?)</script>', h, re.S)
alvo = max(blocos, key=len)
pathlib.Path('/tmp/bloco.js').write_text(alvo, encoding='utf-8')
print('bloco extraido:', len(alvo), 'chars')
"
node --check /tmp/bloco.js
```

Esperado: `bloco extraido: ...` e o `node --check` sem erro.

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html
git commit -m "feat(carga): barra ligada ao wrapper de fetch, com recarga automatica muda"
```

---

### Task 4: Teste de integração com Playwright

O teste roda contra o `index.html` real, com todas as rotas de API interceptadas — sem
banco, sem túnel, sem AVA. Determinístico e rápido.

**Files:**
- Create: `tests/frontend/test_barra_e2e.py`

**Interfaces:**
- Consumes: `#loadbar`, `#loadtempo`, `CARGA` do index.html.
- Produces: nada (folha).

- [ ] **Step 1: Escrever o teste**

Criar `tests/frontend/test_barra_e2e.py`:

```python
"""Integracao da barra de carregamento contra o index.html real.

Nao sobe a API nem toca no AVA: um http.server serve api/ como raiz (para
/static/index.html e /static/carga.js resolverem) e o Playwright intercepta
TODA rota /api/**, respondendo com atraso controlado. Assim os limiares de
150ms e 3s sao testados sem depender do banco.

A visibilidade da barra e observada por um MutationObserver injetado antes do
documento: checar `#loadbar` por polling seria uma corrida perdida contra uma
transicao de 150ms.
"""
from __future__ import annotations

import functools
import http.server
import json
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[2]
DIR_API = RAIZ / "api"

USUARIO = {
    "nome": "Teste", "email": "teste@sulista.local", "perfil": "admin",
    "admin": True, "telas": [],
}

# grava cada transicao do atributo hidden de #loadbar em window.__barraLog
ESPIA = """
window.__barraLog = [];
(function liga(){
  if (!document.documentElement) { document.addEventListener('readystatechange', liga, {once:true}); return; }
  new MutationObserver(function(ms){
    for (var i=0;i<ms.length;i++){
      var t = ms[i].target;
      if (t && t.id === 'loadbar') window.__barraLog.push(!t.hidden);
    }
  }).observe(document.documentElement, {subtree:true, attributes:true, attributeFilter:['hidden']});
})();
"""


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def pagina(base_url):
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pg = navegador.new_page()
        pg.add_init_script(ESPIA)
        yield pg, base_url
        navegador.close()


def _mockar(pg, atraso_ms: int):
    """Toda rota /api/** responde {} depois de `atraso_ms`; /auth/me devolve sessao.

    O atraso e time.sleep e nao page.wait_for_timeout: chamar um metodo de
    espera da propria page de DENTRO de um route handler da API sincrona do
    Playwright e reentrante e trava.
    """
    def rota(route):
        if "/api/auth/me" in route.request.url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(USUARIO))
            return
        if atraso_ms:
            time.sleep(atraso_ms / 1000)
        route.fulfill(status=200, content_type="application/json", body="{}")
    pg.route("**/api/**", rota)


def _estabilizar(pg):
    """Espera o boot terminar e zera o espia.

    Sem isto os testes de 'nao acende' mediriam a rajada de chamadas do boot em
    vez da chamada sob teste, e falhariam de forma intermitente conforme o
    encavalamento.
    """
    pg.wait_for_function("typeof CARGA !== 'undefined' && CARGA.ativas() === 0", timeout=30000)
    pg.wait_for_timeout(400)
    pg.evaluate("window.__barraLog = []")


def test_carga_rapida_nao_pisca_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 30)
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("fetch('/api/financeiro/overview')")   # 30ms, abaixo dos 150
    pg.wait_for_timeout(1000)
    assert pg.evaluate("window.__barraLog") == [], "barra apareceu numa carga de 30ms"


def test_carga_lenta_mostra_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 800)
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_selector("#loadbar:not([hidden])", timeout=5000)
    assert True  # o wait_for_selector acima e a asserção


def test_barra_some_ao_terminar(pagina):
    pg, base = pagina
    _mockar(pg, 800)
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_selector("#loadbar:not([hidden])", timeout=5000)
    # state="hidden" e obrigatorio: wait_for_selector espera VISIBILIDADE por
    # padrao, e "#loadbar[hidden]" tem display:none -- a condicao seria
    # impossivel de satisfazer e o teste so daria timeout.
    pg.wait_for_selector("#loadbar", state="hidden", timeout=30000)
    assert pg.evaluate("CARGA.ativas()") == 0


def test_erro_de_rede_tambem_apaga_a_barra(pagina):
    """O caso que mais gera spinner eterno na vida real: a Promise rejeita e o
    finally e a unica coisa que ainda roda."""
    pg, base = pagina
    # ORDEM IMPORTA: no Playwright a rota registrada POR ULTIMO e avaliada
    # primeiro. O catch-all vai antes; o mock da sessao depois, para vencer.
    pg.route("**/api/**", lambda r: r.abort())
    pg.route("**/api/auth/me", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_timeout(3000)
    assert pg.evaluate("CARGA.ativas()") == 0, "contador vazou quando o fetch falhou"
    assert pg.is_hidden("#loadbar")


def test_contador_de_tempo_aparece_aos_3s(pagina):
    pg, base = pagina
    _mockar(pg, 6000)
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_selector("#loadtempo:not([hidden])", timeout=8000)
    texto = pg.inner_text("#loadtempo")
    assert texto.startswith("consultando o banco… "), texto
    assert texto.endswith("s"), texto


def test_recarga_de_fundo_nao_acende_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 800)          # bem acima dos 150ms: se contasse, acenderia
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("fetch('/api/gestao/servidor',{headers:{'X-Carga-Fundo':'1'}})")
    pg.wait_for_timeout(2000)
    assert pg.evaluate("window.__barraLog") == [], "chamada de fundo acendeu a barra"


def test_clique_manual_na_mesma_rota_acende_a_barra(pagina):
    """Contraprova do teste acima: sem o header, a MESMA rota tem de acender.
    Sem esta, um bug que desligasse a barra por completo passaria despercebido."""
    pg, base = pagina
    _mockar(pg, 800)
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("fetch('/api/gestao/servidor')")
    pg.wait_for_selector("#loadbar:not([hidden])", timeout=5000)
    assert pg.evaluate("window.__barraLog")[0] is True


def test_chamada_externa_nao_acende_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 800)
    pg.route("**open-meteo**", lambda r: (time.sleep(0.8), r.fulfill(
        status=200, content_type="application/json", body="{}")))
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("fetch('https://api.open-meteo.com/v1/forecast?latitude=-27&longitude=-48')")
    pg.wait_for_timeout(2000)
    assert pg.evaluate("window.__barraLog") == [], "fetch externo acendeu a barra"
```

- [ ] **Step 2: Rodar e confirmar que passam**

```bash
uv run python -m playwright install chromium   # só na primeira vez
uv run pytest tests/frontend/test_barra_e2e.py -v
```

Esperado: 8 passed.

Se `test_carga_rapida_nao_pisca_a_barra` falhar com a barra aparecendo, o culpado é o
`ATRASO_BARRA` em `carga.js` — conferir se ficou em 150.

- [ ] **Step 3: Rodar a suíte inteira, para provar que nada mais quebrou**

```bash
uv run pytest -q
uv run python scratchpad/estrutura.py
node --test "tests/frontend/*.test.js"
```

Esperado: a suíte Python no mesmo estado de antes desta branch (rodar
`git stash && uv run pytest -q` para comparar, se houver falha preexistente), estrutural
sem erro, 8 testes de Node passando.

- [ ] **Step 4: Conferência manual no navegador**

Com `uv run uvicorn api.main:app --port 8010` e o túnel do ERP no ar:

| Caso | Esperado |
|---|---|
| Abrir a DRE | barra desliza; passados 3 s aparece `consultando o banco… Ns` |
| Trocar o filtro de competência **duas vezes rápido** | ao fim das duas, a barra some (sem vazamento) |
| Abrir e fechar um drill-down da DRE | barra durante a consulta, some ao terminar |
| Derrubar a API (Ctrl+C) e clicar em Atualizar | banner de erro **e** barra sumindo |
| Ficar 1 min na Saúde do servidor | nada pisca; clicar em Atualizar acende a barra |
| Torre aberta por 3 min | não pisca a cada 2 min |
| Painel de TV | sem barra |
| DevTools → mobile, rolar a página | barra acompanha a topbar |
| SO com "reduzir movimento" ligado | barra visível pulsando, sem deslizar |

- [ ] **Step 5: Commit**

```bash
git add tests/frontend/test_barra_e2e.py
git commit -m "test(carga): integracao da barra com rotas mockadas (Playwright)"
```

---

---

### Task 5: Versão e documentação

Fecha a entrega. Inaugura o versionamento do projeto e registra as lições no CLAUDE.md,
como toda tela mexida já faz.

**Files:**
- Create: `CHANGELOG.md`
- Modify: `pyproject.toml:3`, `api/main.py`, `api/static/index.html:888`, `CLAUDE.md`
- Test: `tests/frontend/test_versao.py`

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `api.main.VERSAO` (str) e `GET /api/versao` → `{"versao": "1.1.0"}`.

- [ ] **Step 1: Escrever o teste do endpoint, que falha**

Criar `tests/frontend/test_versao.py`:

```python
"""A versao exposta pela API tem de ser a MESMA do pyproject.toml.

Duas fontes divergentes e pior que nenhuma: o rodape do painel diria uma coisa
e o repositorio, outra, e a checagem de deploy passaria a mentir.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import VERSAO, app

RAIZ = Path(__file__).resolve().parents[2]


def test_versao_bate_com_o_pyproject():
    dados = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert VERSAO == dados["project"]["version"]


def test_versao_nao_ficou_no_placeholder_inicial():
    assert VERSAO != "0.1.0", "bump esquecido: 0.1.0 e o valor do commit inicial"


def test_endpoint_devolve_a_versao():
    cliente = TestClient(app)
    r = cliente.get("/api/versao")
    assert r.status_code in (200, 401)      # 401 se a rota exigir sessao
    if r.status_code == 200:
        assert r.json()["versao"] == VERSAO
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
uv run pytest tests/frontend/test_versao.py -v
```

Esperado: FAIL — `ImportError: cannot import name 'VERSAO' from 'api.main'`.

- [ ] **Step 3: Bumpar o `pyproject.toml`**

Substituir em `pyproject.toml:3`:

```toml
version = "0.1.0"
```

por:

```toml
version = "1.1.0"
```

- [ ] **Step 4: Expor a versão na API**

Em `api/main.py`, acrescentar `tomllib` à lista de imports da stdlib (junto de
`logging` e `re`, em ordem alfabética: `import logging`, `import re`, `import tomllib`).

Depois, logo abaixo de `log = logging.getLogger("cortex.financeiro")`, inserir:

```python
def _versao() -> str:
    """Fonte única: o pyproject.toml. Ler dele evita o número duplicado em dois
    lugares, que a primeira pressa faria divergir."""
    try:
        alvo = Path(__file__).resolve().parent.parent / "pyproject.toml"
        return tomllib.loads(alvo.read_text(encoding="utf-8"))["project"]["version"]
    except Exception:  # noqa: BLE001
        return "dev"


VERSAO = _versao()
```

E, imediatamente antes de `@app.get("/api/health")`, inserir a rota:

```python
@app.get("/api/versao")
def versao() -> JSONResponse:
    # exige sessão (não está em auth._PUBLICAS): serve para confirmar, dentro do
    # painel, qual build o AutoDeploy colocou no ar
    return JSONResponse({"versao": VERSAO})
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

```bash
uv run pytest tests/frontend/test_versao.py -v
```

Esperado: 3 passed.

- [ ] **Step 6: Mostrar a versão no rodapé da sidebar**

Substituir em `index.html:888`:

```html
    <div class="side-foot">CÓRTEX · Sulista</div>
```

por:

```html
    <div class="side-foot">CÓRTEX · Sulista<br><span id="appVersao"></span></div>
```

E em `entrar()` (`index.html:10196-10197`), substituir:

```js
function entrar(){
  document.getElementById('loginOverlay').classList.add('oculto');
```

por:

```js
function entrar(){
  document.getElementById('loginOverlay').classList.add('oculto');
  // versão do build no rodapé: é como se confirma, olhando a tela, que o
  // AutoDeploy do Windows realmente subiu o que se esperava
  fetch('/api/versao',{cache:'no-store'}).then(r=>r.json()).then(d=>{
    const e=document.getElementById('appVersao'); if(e && d.versao) e.textContent='v'+d.versao;
  }).catch(()=>{});
```

- [ ] **Step 7: Criar o CHANGELOG**

Criar `CHANGELOG.md` na raiz:

```markdown
# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [1.1.0] — 2026-08-08

### Adicionado
- Indicador de carregamento em todas as telas e ações: barra animada sobre a
  borda da topbar, acionada pelo wrapper de `fetch`, cobrindo as 41 cargas de
  tela e as ~37 ações internas (drill-down, ficha, exportação, modais).
- Contador de tempo decorrido a partir de 3 s (`consultando o banco… 12s`), para
  que consulta longa ao AVA não se leia como travamento.
- Versão do build visível no rodapé da sidebar e em `GET /api/versao`.
- `CHANGELOG.md` e versionamento SemVer no `pyproject.toml`.

### Alterado
- Torre de Controle e Saúde do Servidor: a recarga automática (120 s e 5 s)
  deixou de esmaecer a tela e de desabilitar o botão Atualizar. O clique manual
  continua acusando carregamento.

## [1.0.0] — 2026-08-08

Marco do estado em produção. O `pyproject.toml` esteve em `0.1.0` desde o commit
inicial; o histórico anterior a esta versão está nos commits, não aqui.

Painel em uso com ~45 telas sobre o ERP AVA (PostgreSQL 9.3, leitura via túnel
SSH) e a folha no GLOBUS (Oracle): financeiro e fluxo de caixa, DRE gerencial e
por cliente, comercial, operação e torre de controle, frota, jornada,
suprimentos, RH e folha, orçamento, premiação de motoristas, extrato bancário,
previsão de fechamento do mês, painéis de TV, copiloto e administração com RBAC.
```

- [ ] **Step 8: Registrar as lições no CLAUDE.md**

Em `CLAUDE.md`, seção 5, inserir o bloco abaixo imediatamente antes de
`**GOTCHA de JS (derrubou o painel inteiro uma vez):**`:

```markdown
**Feedback de carregamento (lição do indicador de carga):**
- **Esmaecer não é feedback.** `.content.loading{opacity:.55}` era a única resposta
  a um clique: numa consulta de 40 s ao AVA ninguém distingue "consultando" de
  "morreu". A barra animada sobre a borda da topbar resolve sem deslocar layout.
- **Contador vive no wrapper de `fetch`, nunca nos loaders.** Os loaders soltam o
  `content.loading` dentro de `if(seq===...)`: correto para flag idempotente,
  fatal para contador — toda resposta obsoleta (trocar filtro duas vezes rápido)
  vazaria e a barra giraria para sempre. O `finally` da Promise roda sempre,
  inclusive em erro de rede.
- **Já existe um wrapper de `window.fetch`** (401 → login). Estender esse, nunca
  criar um segundo: `_fetch0` é usado de propósito no boot/login para escapar do
  tratamento de 401, e um wrapper novo o sequestraria.
- **150 ms antes de aparecer.** Sem esse atraso, resposta de cache faz a tela
  piscar — pior que não ter indicador.
- **Recarga automática não acende a barra.** Saúde (5 s) e Torre (120 s) marcam
  `X-Carga-Fundo` no timer, não na URL: assim o clique manual nas mesmas telas
  continua acusando. Painel de TV é escondido por CSS.
- **GOTCHA do `prefers-reduced-motion`:** o bloco global do arquivo zera
  `animation-iteration-count` com `!important` em `*`. Uma animação infinita nova
  para no fim do keyframe — a barra ficaria em `left:100%`, fora da tela, e
  INVISÍVEL justo para quem pediu menos movimento. Regra explícita com
  especificidade maior é obrigatória.
- **Playwright já está no `.venv`**: `tests/frontend/test_barra_e2e.py` roda
  contra o `index.html` real com `page.route` mockando `/api/**` com atraso
  controlado — testa a UI sem banco, sem túnel. Cuidado: no Playwright a rota
  registrada POR ÚLTIMO é avaliada primeiro.
```

- [ ] **Step 9: Rodar tudo**

```bash
uv run pytest -q
node --test "tests/frontend/*.test.js"
uv run python scratchpad/estrutura.py
```

Esperado: suíte Python passando (incluindo os 3 de versão e os 8 de Playwright),
8 testes de Node, estrutural sem erro.

- [ ] **Step 10: Conferir a versão na tela**

```bash
uv run uvicorn api.main:app --port 8010
```

Abrir `http://127.0.0.1:8010/`, logar. Esperado: rodapé da sidebar mostra
`CÓRTEX · Sulista` e, abaixo, `v1.1.0`.

- [ ] **Step 11: Commit**

```bash
git add CHANGELOG.md pyproject.toml api/main.py api/static/index.html CLAUDE.md tests/frontend/test_versao.py
git commit -m "chore: versao 1.1.0, CHANGELOG e versao visivel no painel"
```

---

## Notas de execução

- **Ordem obrigatória.** Task 3 depende de `criarCarga` (Task 1) e dos elementos (Task 2).
  Task 4 depende das três. Task 5 fecha a entrega e deve ser a última — o CHANGELOG
  descreve o que as anteriores entregaram.
- **Não reordenar os passos de edição do `index.html`.** Cada substituição é literal e
  casa com o arquivo no estado deixado pelo passo anterior.
- Se `grep -n "<script" api/static/index.html` devolver a primeira ocorrência em linha
  diferente de 2526, o arquivo mudou desde o planejamento — reconferir os trechos antes
  de substituir, não confiar nos números de linha.
