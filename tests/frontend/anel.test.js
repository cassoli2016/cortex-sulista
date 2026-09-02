/* O anel do CÓRTEX: geometria determinística, paleta da marca sem amarelo,
   e o desenho que não depende de DOM (contexto dublê). */
const test = require('node:test');
const assert = require('node:assert');
const anel = require('../../api/static/anel.js');

const cfg = anel.padrao(200);

test('mesma entrada, mesmo raio (o quadro é reproduzível)', () => {
  const a = anel.raio(3, 0.7, 1.25, cfg), b = anel.raio(3, 0.7, 1.25, cfg);
  assert.strictEqual(a, b);
  assert.ok(Math.abs(a - 1) < 0.3, `raio relativo perto de 1: ${a}`);
});

test('o anel se move com o tempo e cada linha tem fase própria', () => {
  assert.notStrictEqual(anel.raio(3, 0.7, 0, cfg), anel.raio(3, 0.7, 2, cfg));
  assert.notStrictEqual(anel.raio(3, 0.7, 0, cfg), anel.raio(4, 0.7, 0, cfg));
});

test('linha fechada: pontos+1 vértices, o último volta ao primeiro ângulo', () => {
  const ps = anel.pontos(0, 0, cfg);
  assert.strictEqual(ps.length, cfg.pontos + 1);
  assert.ok(Math.abs(ps[0][0] - ps[ps.length - 1][0]) < 1e-6);
  assert.ok(Math.abs(ps[0][1] - ps[ps.length - 1][1]) < 1e-6);
});

test('quente no topo, frio na base, e NUNCA amarelo (a marca não tem)', () => {
  const topo = anel.cor(-Math.PI / 2), base = anel.cor(Math.PI / 2);
  assert.ok(topo[0] > topo[2], 'topo é quente (mais vermelho que azul)');
  assert.ok(base[2] > base[0], 'base é fria (mais azul que vermelho)');
  for (let k = 0; k <= 360; k += 3) {
    const [r, g, b] = anel.cor((k / 180) * Math.PI);
    const amarelo = r > 200 && g > 170 && b < 120;
    assert.ok(!amarelo, `amarelo em ${k}°: rgb(${r},${g},${b})`);
  }
});

test('o anel pequeno é mais leve que o grande', () => {
  const p = anel.padrao(36), g = anel.padrao(220);
  assert.ok(p.linhas < g.linhas && p.pontos < g.pontos);
  assert.ok(p.alfa > g.alfa, 'menos linhas pedem traço mais opaco');
});

test('desenha um quadro num contexto dublê, sem DOM', () => {
  const chamadas = { stroke: 0, clear: 0, comp: null };
  const ctx = {
    clearRect: () => { chamadas.clear++; }, save() {}, restore() {}, translate() {},
    beginPath() {}, moveTo() {}, lineTo() {}, stroke: () => { chamadas.stroke++; },
    set globalCompositeOperation(v) { chamadas.comp = v; }, get globalCompositeOperation() { return chamadas.comp; },
  };
  anel.quadro(ctx, 200, 200, 0.5, cfg);
  assert.strictEqual(chamadas.clear, 1);
  assert.ok(chamadas.stroke >= cfg.linhas * 10, `segmentos traçados: ${chamadas.stroke}`);
  assert.strictEqual(chamadas.comp, 'lighter');
  anel.quadro(ctx, 200, 200, 0.5, Object.assign({}, cfg, { brilho: () => false }));
  assert.strictEqual(chamadas.comp, 'source-over');
});
