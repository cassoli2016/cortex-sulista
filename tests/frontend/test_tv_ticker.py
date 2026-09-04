# -*- coding: utf-8 -*-
"""O rodapé do painel de TV de operações: ele não pode travar, nunca.

Estes guards nasceram de "o rodapé está estático" — e de uma SEGUNDA queixa,
depois da primeira correção, que é a lição mais cara das duas.

PRIMEIRO DEFEITO. A folha tem uma regra global de acessibilidade:

    @media (prefers-reduced-motion: reduce){ *{animation-duration:.001ms
    !important} }

e o `!important` VENCE o `style.animationDuration` que o JS escreve. Medido
com `emulate_media(reduced_motion="reduce")`: duração "1e-06s", transform
"none", zero movimento. O CSS e o JS estavam certos ao LER — só o navegador
disse quem ganhou. E congelar ali não é "menos movimento": o conteúdo media
14.653px numa caixa de 1.874px, então 87% da informação ficava fora da tela.

SEGUNDO DEFEITO — a correção errada. A primeira tentativa passou a mostrar UM
item por vez. Na parede isso travou de novo, por outro motivo: com poucos
avisos, `(i+1) % 1` devolve sempre o MESMO item; e um aviso curto encostado à
esquerda de uma faixa de 1.874px parece defeito, não rodapé.

O desenho certo usa a faixa INTEIRA e só se move quando há o que esconder:
salta uma PÁGINA por vez com `style.transform` — transform estático, que o
`!important` não alcança. Cabendo tudo, nada se mexe.
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


# --------------------------------------------------------------------------
# modo normal: rolagem contínua
# --------------------------------------------------------------------------
def test_no_modo_normal_o_rodape_ROLA(pagina):
    pg, base = pagina
    _abre(pg, base)
    t1 = pg.evaluate("() => getComputedStyle(document.getElementById"
                     "('tvope-ticker')).transform")
    pg.wait_for_timeout(1200)
    t2 = pg.evaluate("() => getComputedStyle(document.getElementById"
                     "('tvope-ticker')).transform")
    assert t1 != t2, "o rodapé não está rolando (parado em %s)" % t1
    assert "anda" in _estado(pg)["classe"]


# --------------------------------------------------------------------------
# reduced-motion: salto de página, e só quando há o que esconder
# --------------------------------------------------------------------------
def test_com_reduced_motion_e_conteudo_longo_o_rodape_PAGINA(pagina):
    """O guard central: sem animação possível, a faixa tem de SALTAR."""
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base, MUITOS)

    a = _estado(pg)
    assert a["dentro"] > a["caixa"], (
        "o cenário não tem conteúdo suficiente para exigir paginação "
        "(%dpx em %dpx) — o guard mediria uma tela que não existe"
        % (a["dentro"], a["caixa"]))
    assert "anda" not in a["classe"]

    pg.wait_for_timeout(11000)
    b = _estado(pg)
    assert b["transform"] != a["transform"], (
        "a faixa congelou com reduced-motion: transform parado em %r"
        % a["transform"])


def test_com_reduced_motion_e_conteudo_CURTO_nada_se_move(pagina):
    """A segunda queixa, virada guard.

    Cabendo tudo na faixa, não há o que esconder — mover seria movimento por
    movimento, contra a preferência de quem configurou a máquina. E a faixa
    fica CENTRADA: um aviso curto encostado à esquerda de um vão escuro é o
    que fez o rodapé parecer quebrado.
    """
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base, POUCOS)

    a = _estado(pg)
    assert a["texto"], "a faixa ficou vazia com um aviso só"
    assert a["dentro"] <= a["caixa"]
    assert a["centrado"] == "center", (
        "aviso curto encostado na esquerda (%s)" % a["centrado"])

    pg.wait_for_timeout(11000)
    b = _estado(pg)
    assert b["texto"] == a["texto"], "trocou o conteúdo sem ter o que esconder"


def test_um_aviso_so_nao_pode_parecer_travado(pagina):
    """`(i+1) % 1` devolve sempre o mesmo item: era exatamente assim que o
    desenho anterior travava. Com um aviso só, tudo tem de estar visível."""
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base, POUCOS)
    a = _estado(pg)
    assert a["dentro"] <= a["caixa"]
    assert a["transform"] in ("", "none"), (
        "faixa curta não pode carregar transform: %r" % a["transform"])


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
