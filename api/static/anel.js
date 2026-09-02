/* Anel do CÓRTEX — a marca animada.

   Dezenas de linhas finas fechadas em volta de um círculo, cada uma com o
   raio modulado por ondas que deslizam com o tempo; sobrepostas com brilho
   aditivo viram um anel de luz que "respira". Paleta da marca: tijolo
   (#942821) e laranja (#E85D10) no alto, navy/azul embaixo — sem amarelo
   (o teste em tests/frontend/anel.test.js confere a paleta ângulo a ângulo).

   Vive fora do index.html, como carga.js: a geometria é pura (sem DOM) e
   testável em Node (module.exports); o desenho recebe o canvas por injeção.
   Carregado como <script> clássico define window.cortexAnel.

   Custo: ~44 linhas × 180 pontos por quadro no anel grande (login) e
   16 × 72 no pequeno (topbar). Escondido, o laço dorme em setTimeout de
   120 ms em vez de rAF; com prefers-reduced-motion desenha UM quadro. */
(function (raiz) {
  'use strict';

  var PALETA = {
    tijolo: [148, 40, 33],     // #942821
    laranja: [232, 93, 16],    // #E85D10
    claro: [255, 196, 176],    // brilho quente do ápice (pêssego, não amarelo)
    azul: [96, 165, 250],      // luz fria da base
    navy: [30, 58, 138]        // #1E3A8A
  };

  /* Raio relativo da linha `i` no ângulo `a` (rad) e tempo `t` (s): 1 + soma
     de ondas de amplitude decrescente, com fase própria por linha.
     Determinístico: mesma entrada, mesmo número. */
  function raio(i, a, t, cfg) {
    var amp = cfg.amplitude, f = i * 0.37;
    var r = 1
      + amp * 0.55 * Math.sin(3 * a + t * 0.9 + f)
      + amp * 0.30 * Math.sin(7 * a - t * 1.4 + f * 2.1)
      + amp * 0.15 * Math.sin(13 * a + t * 2.2 - f * 0.7)
      + amp * 0.35 * Math.sin(2 * a - t * 0.5 + f * 1.3);
    // as linhas mais externas abrem um pouco mais: é a espessura da "borda"
    return r + (i / cfg.linhas) * cfg.espessura;
  }

  /* Cor no ângulo `a`: quente no topo (a = -90°), fria na base. Interpola por
     canais entre azul → tijolo → laranja, sem passar pelo amarelo. */
  function cor(a) {
    var s = (1 - Math.sin(a)) / 2;          // 1 no topo (sin(-90°) = -1), 0 na base
    var q = s < 0.5 ? mistura(PALETA.azul, PALETA.tijolo, s * 2)
                    : mistura(PALETA.tijolo, PALETA.laranja, (s - 0.5) * 2);
    if (s > 0.88) q = mistura(q, PALETA.claro, (s - 0.88) * 4);   // ápice
    if (s < 0.15) q = mistura(q, PALETA.azul, (0.15 - s) * 3);    // base
    return q;
  }

  function mistura(c1, c2, p) {
    p = Math.max(0, Math.min(1, p));
    return [Math.round(c1[0] + (c2[0] - c1[0]) * p),
            Math.round(c1[1] + (c2[1] - c1[1]) * p),
            Math.round(c1[2] + (c2[2] - c1[2]) * p)];
  }

  function pontos(i, t, cfg) {
    var out = [], n = cfg.pontos;
    for (var k = 0; k <= n; k++) {
      var a = -Math.PI / 2 + (k / n) * Math.PI * 2;
      var r = raio(i, a, t, cfg) * cfg.raio;
      out.push([Math.cos(a) * r, Math.sin(a) * r]);
    }
    return out;
  }

  function padrao(tamanho) {
    var pequeno = tamanho < 80;
    return {
      raio: tamanho * 0.34,
      linhas: pequeno ? 16 : 44,
      pontos: pequeno ? 72 : 180,
      amplitude: pequeno ? 0.06 : 0.045,
      espessura: pequeno ? 0.10 : 0.12,
      alfa: pequeno ? 0.55 : 0.16,
      largura: pequeno ? 1.1 : 0.9,
      brilho: true,              // true | false | função () => boolean (por quadro)
      velocidade: 1
    };
  }

  /* Desenha um quadro. `ctx` é um CanvasRenderingContext2D (ou dublê), `w`/`h`
     em px CSS. Pode ser chamado uma vez só (movimento reduzido) ou por rAF. */
  function quadro(ctx, w, h, t, cfg) {
    var brilho = typeof cfg.brilho === 'function' ? !!cfg.brilho() : !!cfg.brilho;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(w / 2, h / 2);
    ctx.globalCompositeOperation = brilho ? 'lighter' : 'source-over';
    ctx.lineWidth = cfg.largura;
    ctx.lineJoin = 'round';
    var seg = 12, passo = Math.max(1, Math.round((cfg.pontos + 1) / seg));
    for (var i = 0; i < cfg.linhas; i++) {
      var ps = pontos(i, t * cfg.velocidade, cfg);
      // cada linha é traçada em segmentos coloridos pelo ângulo: o gradiente
      // acompanha o círculo, não o eixo x/y
      for (var k = 0; k < ps.length - 1; k += passo) {
        var fim = Math.min(ps.length - 1, k + passo);
        var am = -Math.PI / 2 + ((k + fim) / 2 / cfg.pontos) * Math.PI * 2;
        var c = cor(am);
        ctx.strokeStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + cfg.alfa + ')';
        ctx.beginPath();
        ctx.moveTo(ps[k][0], ps[k][1]);
        for (var j = k + 1; j <= fim; j++) ctx.lineTo(ps[j][0], ps[j][1]);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  /* Liga o anel num <canvas>. Devolve {parar, desenhar, reduzido}. Respeita o
     tamanho CSS do canvas, o devicePixelRatio e `prefers-reduced-motion`
     (um quadro só). Escondido (hidden, display:none, fora do documento),
     dorme em vez de desenhar. */
  function ligar(canvas, opcoes) {
    if (!canvas || !canvas.getContext) return null;
    var ctx = canvas.getContext('2d');
    if (!ctx) return null;
    var w = 0, h = 0, cfg = null, rodando = false, raf = null, dorme = null;
    var reduzido = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    var t0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());

    function medir() {
      var cw = canvas.clientWidth || parseInt(canvas.getAttribute('width'), 10) || 100;
      var ch = canvas.clientHeight || parseInt(canvas.getAttribute('height'), 10) || cw;
      var dpr = Math.min(2, (typeof devicePixelRatio === 'number' ? devicePixelRatio : 1) || 1);
      if (cw !== w || ch !== h || !cfg) {
        w = cw; h = ch;
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cfg = Object.assign(padrao(Math.min(w, h)), opcoes || {});
      }
    }
    function visivel() {
      return canvas.isConnected !== false && !canvas.hidden && canvas.offsetParent !== null;
    }
    function desenhar(ts) {
      medir();
      quadro(ctx, w, h, ((ts || t0) - t0) / 1000, cfg);
    }
    function laco(ts) {
      raf = null;
      if (!rodando) return;
      if (!visivel()) { dorme = setTimeout(function () { dorme = null; raf = requestAnimationFrame(laco); }, 120); return; }
      desenhar(ts);
      raf = requestAnimationFrame(laco);
    }
    medir();
    if (reduzido) { desenhar(t0 + 1300); }
    else { rodando = true; raf = requestAnimationFrame(laco); }
    return {
      parar: function () {
        rodando = false;
        if (raf) { cancelAnimationFrame(raf); raf = null; }
        if (dorme) { clearTimeout(dorme); dorme = null; }
      },
      desenhar: desenhar,
      reduzido: reduzido
    };
  }

  var api = { raio: raio, cor: cor, pontos: pontos, quadro: quadro, ligar: ligar, padrao: padrao, PALETA: PALETA };
  raiz.cortexAnel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
