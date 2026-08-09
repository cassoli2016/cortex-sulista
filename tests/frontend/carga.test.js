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
