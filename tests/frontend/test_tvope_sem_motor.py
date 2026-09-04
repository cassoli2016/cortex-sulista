# -*- coding: utf-8 -*-
"""A TV de operações só mostra veículo COM MOTOR.

Implemento entra nas posições e enche o mapa de carreta parada em pátio:
medido em 04/09/2026, **89 de 278 posições (quase um terço) eram de veículos
sem motor**. E o rodapé lê a mesma lista para alertar excesso de velocidade —
carreta rebocada reporta a velocidade do cavalo que a puxa.

DE ONDE VEM O "SEM MOTOR", e por que NÃO é o número de frota. A regra proposta
era "frota que começa com S, G ou B". Medida contra `veiculo.possuimotor`, o
campo do próprio ERP:

    frota S/G/B    COM motor = 114      SEM motor = 326
    outro prefixo  COM motor = 536      SEM motor = 472

Ou seja: pegaria 326 dos 798 implementos (41%) e levaria 114 cavalos junto —
71 deles só porque a PLACA foi copiada no campo de frota e começa com essas
letras (o campo tem 46% de cobertura real, e é por isso que a casa manda
identificar veículo pela PLACA). `possuimotor` já é o que a Comunicação
Veículos × Rastreadora usa.

A tela `torre` continua vendo a frota inteira: quem procura uma carreta
específica precisa dela. O corte é só na parede.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# 3 com motor, 2 sem, 1 fora do cadastro (com_motor nulo)
POSICOES = [
    {"placa": "AAA1A11", "frota": "1001", "rotulo": "1001 · AAA1A11", "lat": -23.5, "lng": -46.6,
     "velocidade": 80, "com_motor": True, "recente": True,
     "posicao_em": "2026-09-04 09:00", "utilizacao": "PROPRIO"},
    {"placa": "BBB2B22", "frota": "1002", "rotulo": "1002 · BBB2B22", "lat": -23.6, "lng": -46.7,
     "velocidade": 95, "com_motor": True, "recente": True,
     "posicao_em": "2026-09-04 09:00", "utilizacao": "PROPRIO"},
    {"placa": "CCC3C33", "frota": "1003", "rotulo": "1003 · CCC3C33", "lat": -23.7, "lng": -46.8,
     "velocidade": 10, "com_motor": True, "recente": True,
     "posicao_em": "2026-09-04 09:00", "utilizacao": "AGREGADO"},
    # os dois que TEM de sumir da parede
    {"placa": "SSS4S44", "frota": "S3037", "rotulo": "S3037 · SSS4S44", "lat": -23.8, "lng": -46.9,
     "velocidade": 97, "com_motor": False, "recente": True,
     "posicao_em": "2026-09-04 09:00", "utilizacao": "PROPRIO"},
    {"placa": "GGG5G55", "frota": "G2010", "rotulo": "G2010 · GGG5G55", "lat": -23.9, "lng": -47.0,
     "velocidade": 0, "com_motor": False, "recente": True,
     "posicao_em": "2026-09-04 09:00", "utilizacao": "PROPRIO"},
    # fora do cadastro: FICA. Sumir com o desconhecido é pior que mostrá-lo.
    {"placa": "ZZZ9Z99", "frota": None, "rotulo": "ZZZ9Z99", "lat": -24.0, "lng": -47.1,
     "velocidade": 5, "com_motor": None, "recente": True,
     "posicao_em": "2026-09-04 09:00", "utilizacao": "TERCEIRO"},
]


def _corpo(url: str) -> dict:
    if "/api/auth/me" in url:
        return ADMIN
    if "/api/operacao/torre" in url and "estradas" not in url:
        return {"kpis": {}, "posicoes": POSICOES, "transito": []}
    if "/api/operacao/programacao" in url:
        return {"kpis": {"cnh_vencida_rodando": 0, "sem_retorno": 0}}
    if "/api/operacao/seguranca" in url:
        return {"kpis": {"cercas_24h": 0}}
    if "/api/operacao/analise-km" in url:
        return {"kpis": {}}
    if "/api/visao-geral" in url:
        return {"kpis": {}, "fluxo": [], "mes": {}}
    return {"resumo": {}, "kpis": {}}


def _abre(pg, base):
    def rota(r):
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(_corpo(r.request.url)))
    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1920, "height": 1080})
    pg.goto(base + "/static/index.html#tvope")
    pg.wait_for_timeout(2500)
    return pg


def _marcadores(pg):
    """Quantos veiculos o MAPA recebeu. innerText nao serve: marcador de
    Leaflet nao e texto, e afirmar ausencia numa superficie onde nada aparece
    e falso verde."""
    return pg.evaluate(
        "() => (typeof tvLayer !== 'undefined' && tvLayer)"
        " ? tvLayer.getLayers().length : -1")


def test_o_mapa_recebe_so_quem_tem_motor(pagina):
    """O guard central, com CONTROLE POSITIVO.

    Da amostra de 6 posicoes, 3 tem motor, 2 nao e 1 esta fora do cadastro.
    O mapa tem de receber 4 — as 3 com motor mais a desconhecida. Exigir o
    numero exato e o que impede o teste de passar por o mapa estar vazio.
    """
    pg, base = pagina
    _abre(pg, base)
    n = _marcadores(pg)
    assert n != -1, "o mapa nao foi montado; o guard mediria uma tela vazia"
    assert n == 4, (
        "o mapa recebeu %d veiculos; esperado 4 (3 com motor + 1 sem "
        "cadastro), com as 2 carretas fora" % n)


def test_o_alerta_de_excesso_ignora_quem_nao_tem_motor(pagina):
    """Carreta rebocada reporta a velocidade do cavalo. A da amostra esta a
    97 km/h e nao pode virar alerta de excesso — nao ha motorista ali.

    E o cavalo a 95 CONTINUA alertado: e o controle positivo deste teste.
    """
    pg, base = pagina
    _abre(pg, base)
    rodape = pg.evaluate(
        "() => (document.getElementById('tvope-ticker').textContent||'')")
    assert "S3037" not in rodape and "SSS4S44" not in rodape, (
        "carreta a 97 km/h virou alerta de excesso: %r" % rodape[:120])
    assert "1002" in rodape, (
        "o filtro levou junto o veiculo COM motor em excesso: %r"
        % rodape[:120])


def test_veiculo_fora_do_cadastro_permanece(pagina):
    """`com_motor` nulo e desconhecido, nao e 'sem motor'. Sumir com o que
    nao se sabe esconde justamente o cadastro furado que precisa aparecer.

    Coberto pelo numero 4 do teste do mapa: 3 com motor + 1 desconhecido.
    Aqui a verificacao e direta, para a falha dizer QUAL regra caiu.
    """
    pg, base = pagina
    _abre(pg, base)
    n = _marcadores(pg)
    assert n >= 4, (
        "o desconhecido foi tratado como sem motor e sumiu (mapa com %d)" % n)
