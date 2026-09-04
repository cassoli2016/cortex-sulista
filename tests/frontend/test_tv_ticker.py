# -*- coding: utf-8 -*-
"""O rodapé do painel de TV de operações: ele precisa ANDAR, sempre.

Estes guards nasceram de um defeito relatado como "o rodapé está estático", e
a causa só apareceu MEDINDO NO NAVEGADOR — o CSS e o JS estavam certos ao ler.

O QUE ESTAVA ACONTECENDO. A folha tem uma regra global de acessibilidade:

    @media (prefers-reduced-motion: reduce){ *{animation-duration:.001ms
    !important} }

e o `!important` VENCE o `style.animationDuration` que o JS escreve no
elemento. Medido em 04/09/2026 com `emulate_media(reduced_motion="reduce")`:
duração "1e-06s", transform "none", zero movimento. É a lição da casa de novo
— a regra existe, está certa, e só o navegador diz quem ganhou.

E congelar ESTE elemento não é "menos movimento": o conteúdo media 14.653px
numa caixa de 1.874px, então 87% da informação ficava inalcançável. TV de
operação roda em Windows de quiosque, onde desligar animações é ajuste comum.

A correção não foi devolver `!important` e atropelar a preferência de quem
configurou a máquina: foi trocar rolagem contínua por TROCA DISCRETA de item,
que é a acomodação que a preferência pede. Um item por vez, sem deslizar.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _corpo(url: str, quieto: bool = False) -> dict:
    if "/api/auth/me" in url:
        return ADMIN
    if "/api/operacao/torre" in url and "estradas" not in url:
        if quieto:
            return {"kpis": {}, "posicoes": [], "transito": []}
        return {"kpis": {},
                "posicoes": [{"frota": "F%03d" % i, "placa": "ABC%04d" % i,
                              "velocidade": 95 + i} for i in range(3)],
                "transito": [{"placa": "XYZ%04d" % i,
                              "destino": "SAO PAULO SP",
                              "atrasada": i % 2 == 0,
                              "previsao_chegada": "2026-09-04T14:30:00"}
                             for i in range(8)]}
    if "/api/operacao/programacao" in url:
        return {"kpis": {"cnh_vencida_rodando": 0 if quieto else 2,
                         "sem_retorno": 0 if quieto else 5}}
    if "/api/operacao/seguranca" in url:
        return {"kpis": {"cercas_24h": 0 if quieto else 7}}
    if "/api/operacao/analise-km" in url:
        if quieto:
            return {"kpis": {}}
        return {"kpis": {"km_total": 1000000, "km_carregado": 800000,
                         "km_vazio": 200000}}
    if "/api/visao-geral" in url:
        return {"kpis": {}, "fluxo": [], "mes": {}}
    return {"resumo": {}, "kpis": {}}


def _abre(pg, base, quieto: bool = False):
    def rota(r):
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(_corpo(r.request.url, quieto)))
    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1920, "height": 1080})
    pg.goto(base + "/static/index.html#tvope")
    pg.wait_for_timeout(2500)
    return pg


def _texto(pg) -> str:
    return pg.evaluate(
        "() => (document.getElementById('tvope-ticker').textContent||'')"
        ".trim()")


def _transform(pg) -> str:
    return pg.evaluate("() => getComputedStyle(document.getElementById"
                       "('tvope-ticker')).transform")


def test_o_rodape_anda_no_modo_normal(pagina):
    """Rolagem contínua: o transform tem de MUDAR entre duas leituras."""
    pg, base = pagina
    _abre(pg, base)
    t1 = _transform(pg)
    pg.wait_for_timeout(1200)
    t2 = _transform(pg)
    assert t1 != t2, "o rodapé não está rolando (transform parado em %s)" % t1
    assert "anda" in pg.evaluate(
        "() => document.getElementById('tvope-ticker').className")


def test_com_reduced_motion_o_rodape_TROCA_de_item(pagina):
    """O guard central.

    Com a animação congelada pelo `!important`, rolar é impossível — então o
    rodapé passa a TROCAR o item. Se algum dia alguém voltar a depender da
    animação aqui, este teste fica vermelho e diz por quê.
    """
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base)

    x1 = _texto(pg)
    assert x1, "o rodapé ficou vazio com reduced-motion"
    pg.wait_for_timeout(8000)
    x2 = _texto(pg)
    assert x1 != x2, (
        "o rodapé congelou com reduced-motion: continua em %r" % x1[:60])


def test_com_reduced_motion_o_item_CABE_na_caixa(pagina):
    """Não adianta trocar de item se o item nasce fora da tela.

    Era o tamanho do defeito: 14.653px de conteúdo numa caixa de 1.874px.
    """
    pg, base = pagina
    pg.emulate_media(reduced_motion="reduce")
    _abre(pg, base)
    m = pg.evaluate("""() => {
      const el = document.getElementById('tvope-ticker');
      return {dentro: Math.round(el.getBoundingClientRect().width),
              caixa: Math.round(el.parentElement.getBoundingClientRect().width),
              classe: el.className}; }""")
    assert m["dentro"] <= m["caixa"], (
        "o item mede %dpx numa caixa de %dpx" % (m["dentro"], m["caixa"]))
    # a classe da rolagem fica FORA: com ela o elemento carrega um transform
    # congelado e o texto sai deslocado para fora da caixa
    assert "anda" not in m["classe"]


def test_operacao_sem_ocorrencia_DIZ_isso(pagina):
    """Barra escura vazia na parede parece rodapé quebrado.

    Ausência de ocorrência é boa notícia e merece ser dita.
    """
    pg, base = pagina
    _abre(pg, base, quieto=True)
    texto = _texto(pg)
    assert texto, "o rodapé ficou vazio em vez de dizer que não há ocorrência"
    assert "ocorrência" in texto.lower()


def test_o_rodape_nunca_publica_NaN(pagina):
    """Com o KPI de km ausente, `undefined/1000` virava NaN e a parede
    publicava "NaN mil km carregado · NaN% vazio" para a operação inteira."""
    pg, base = pagina
    _abre(pg, base, quieto=True)
    assert "NaN" not in _texto(pg)
