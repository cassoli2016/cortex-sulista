# -*- coding: utf-8 -*-
"""O rodapé dos painéis de TV: ele ROLA, sempre, e não pode travar.

A queixa "o rodapé está estático" chegou TRÊS vezes (04/09 duas, 16/09 nas
TVs de Coletas e Entregas e de Produtividade), e a lição é a das três juntas.

A folha tem uma regra global de acessibilidade:

    @media (prefers-reduced-motion: reduce){ *{animation-duration:.001ms
    !important} }

e o `!important` VENCE qualquer duração de animação que o JS escreva — a
faixa em `@keyframes` congela. Windows com "efeitos de animação" desligados
liga essa preferência sem que ninguém na sala saiba.

A primeira saída mostrava um item por vez (com um aviso só, `(i+1) % 1`
devolve sempre o mesmo). A segunda saltava uma PÁGINA a cada 9 s e não se
movia quando tudo cabia — e na parede isso também se lê como faixa parada.

O desenho de agora: o JS move a faixa quadro a quadro (`transform` inline,
que o `!important` de `animation-duration` não alcança), nos DOIS modos, com
a sequência repetida até encher a faixa. Por isso os guards medem MOVIMENTO
CONTÍNUO — passo pequeno entre amostras próximas — e não só "o transform
mudou", que um salto de página também satisfaria.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

MUITOS, POUCOS, NENHUM = "muitos", "poucos", "nenhum"


def _corpo(url: str, modo: str) -> dict:
    if "/api/auth/me" in url:
        return ADMIN
    if "/api/operacao/torre" in url and "estradas" not in url:
        if modo == MUITOS:
            return {"kpis": {},
                    "posicoes": [{"frota": "F%03d" % i,
                                  "placa": "ABC%04d" % i,
                                  "velocidade": 95 + i} for i in range(4)],
                    "transito": [{"placa": "XYZ%04d" % i,
                                  "destino": "SAO PAULO SP",
                                  "atrasada": i % 2 == 0,
                                  "previsao_chegada": "2026-09-04T14:30:00"}
                                 for i in range(10)]}
        if modo == POUCOS:
            return {"kpis": {}, "posicoes": [],
                    "transito": [{"placa": "XYZ0001", "destino": "SP",
                                  "atrasada": True}]}
        return {"kpis": {}, "posicoes": [], "transito": []}
    if "/api/operacao/programacao" in url:
        return {"kpis": {"cnh_vencida_rodando": 2 if modo == MUITOS else 0,
                         "sem_retorno": 5 if modo == MUITOS else 0}}
    if "/api/operacao/seguranca" in url:
        return {"kpis": {"cercas_24h": 7 if modo == MUITOS else 0}}
    if "/api/operacao/analise-km" in url:
        if modo == MUITOS:
            return {"kpis": {"km_total": 1000000, "km_carregado": 800000,
                             "km_vazio": 200000}}
        return {"kpis": {}}
    if "/api/visao-geral" in url:
        return {"kpis": {}, "fluxo": [], "mes": {}}
    return {"resumo": {}, "kpis": {}}


def _abre(pg, base, modo: str = MUITOS):
    def rota(r):
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(_corpo(r.request.url, modo)))
    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1920, "height": 1080})
    pg.goto(base + "/static/index.html#tvope")
    pg.wait_for_timeout(2500)
    return pg


def _estado(pg):
    return pg.evaluate("""() => {
      const el = document.getElementById('tvope-ticker');
      const caixa = el.parentElement;
      return {
        texto: (el.textContent||'').trim(),
        classe: el.className,
        transform: el.style.transform,
        dentro: Math.round(el.getBoundingClientRect().width),
        caixa: Math.round(caixa.getBoundingClientRect().width),
        centrado: getComputedStyle(caixa).justifyContent
      }; }""")


AMOSTRAS = """async (id) => {
  const el = document.getElementById(id); const xs = [];
  for (let i = 0; i < 6; i++) {
    xs.push(new DOMMatrix(getComputedStyle(el).transform).m41);
    await new Promise(r => setTimeout(r, 250));
  }
  return {xs, caixa: el.parentElement.clientWidth, dentro: el.scrollWidth}; }"""


def _rola_continuo(a):
    """Anda a cada amostra, para a esquerda (ou dá a volta), e em passos
    pequenos: um salto de página daria um passo do tamanho da faixa."""
    xs, caixa = a["xs"], a["caixa"]
    passos = [xs[i] - xs[i + 1] for i in range(len(xs) - 1)]
    andou = [p for p in passos if p > 0]
    assert len(andou) >= len(passos) - 1, ("a faixa não rolou", xs)
    assert max(andou) < caixa / 4, ("a faixa SALTOU em vez de rolar", xs, caixa)


# --------------------------------------------------------------------------
# rolagem contínua, nos dois modos
# --------------------------------------------------------------------------
def test_no_modo_normal_o_rodape_ROLA(pagina):
    pg, base = pagina
    _abre(pg, base)
    _rola_continuo(pg.evaluate(AMOSTRAS, "tvope-ticker"))


def test_com_reduced_motion_o_rodape_ROLA_do_mesmo_jeito(pagina):
    """O guard central: é exatamente a máquina da sala."""
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base, MUITOS)
    a = pg.evaluate(AMOSTRAS, "tvope-ticker")
    assert a["dentro"] > a["caixa"], a
    _rola_continuo(a)


def test_aviso_CURTO_tambem_anda_e_enche_a_faixa(pagina):
    """A queixa de 16/09: cabendo tudo, a faixa ficava parada e centrada.
    Agora a sequência se repete até cobrir a faixa — sem vão escuro — e anda."""
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base, POUCOS)
    a = pg.evaluate(AMOSTRAS, "tvope-ticker")
    assert _estado(pg)["texto"], "a faixa ficou vazia com um aviso só"
    assert a["dentro"] >= 2 * a["caixa"], ("a faixa não encheu", a)
    _rola_continuo(a)


def test_recarga_com_o_mesmo_conteudo_nao_volta_ao_inicio(pagina):
    """O painel recarrega a cada 60 s: remontar do zero faria quem lê nunca
    chegar ao fim."""
    pg, base = pagina
    _abre(pg, base, MUITOS)
    pg.wait_for_timeout(1500)
    antes, depois = pg.evaluate("""async () => {
      const id = 'tvope-ticker', st = _tvTickers[id];
      const itens = st.assinatura.split('');
      const x0 = st.x;
      tvTicker(id, itens);
      tvTicker(id, itens.concat(['aviso novo']));
      await new Promise(r => setTimeout(r, 100));
      return [x0, _tvTickers[id].x]; }""")
    assert antes > 50, antes
    assert depois >= antes, (antes, depois)


def test_painel_escondido_mede_quando_aparece(pagina):
    """Montado com o painel fora da tela (largura zero), a faixa não pode
    medir zero e congelar: ela mede no primeiro quadro em que houver largura."""
    pg, base = pagina
    _abre(pg, base, MUITOS)
    pg.evaluate("""() => { const v = document.getElementById('view-tvope');
      v.style.display = 'none'; tvTicker('tvope-ticker', ['a', 'b', 'c', 'outro aviso']); }""")
    pg.wait_for_timeout(300)
    pg.evaluate("() => { document.getElementById('view-tvope').style.display = ''; }")
    pg.wait_for_timeout(300)
    _rola_continuo(pg.evaluate(AMOSTRAS, "tvope-ticker"))


# --------------------------------------------------------------------------
# operação tranquila
# --------------------------------------------------------------------------
def test_operacao_sem_ocorrencia_DIZ_isso(pagina):
    """Faixa preta vazia na parede parece rodapé quebrado."""
    pg, base = pagina
    _abre(pg, base, NENHUM)
    a = _estado(pg)
    assert a["texto"], "ficou vazio em vez de dizer que não há ocorrência"
    assert "ocorrência" in a["texto"].lower()
    assert a["centrado"] == "center"


def test_o_rodape_nunca_publica_NaN(pagina):
    """Com o KPI de km ausente, `undefined/1000` virava NaN e a parede
    publicava "NaN mil km carregado · NaN% vazio"."""
    pg, base = pagina
    _abre(pg, base, NENHUM)
    assert "NaN" not in _estado(pg)["texto"]
