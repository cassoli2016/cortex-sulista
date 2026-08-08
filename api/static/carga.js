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
