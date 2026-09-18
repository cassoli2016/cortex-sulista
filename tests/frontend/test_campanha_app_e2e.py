# -*- coding: utf-8 -*-
"""O aplicativo da campanha no navegador.

O que só se prova aqui:

- **a capa não mostra número nenhum.** Ela circula por QR em grupo de WhatsApp,
  e o que circula junto tem de ser só o convite — nem categoria, nem contagem,
  nem nome;
- quem não concorre lê O QUE FALTA antes do resto: é a única parte da tela
  sobre a qual ele ainda pode fazer alguma coisa;
- a tela não rola para o lado num celular de 390px.
"""
from __future__ import annotations

import json

CAMPANHA = {"nome": "Programa de Desempenho", "premio": "Moto elétrica",
            "onde": "Matriz — Piraquara/PR", "sorteio_em": "2026-12-20",
            "ate_ciclo": "2026-12", "cat_elite": 90.0}

MINHA = {
    "tem_dado": True, "fora_do_escopo": False, "campanha": CAMPANHA,
    "ciclo": "2026-11", "rotulo": "16/10 a 15/11 de 2026",
    "encerramento": False, "faltam_ciclos": 1,
    "grupo": "AGREGADO", "grupo_rotulo": "agregados",
    "nota": 93.6, "categoria": "ELITE", "posicao": 3, "de": 42,
    "concorre": True, "motivo": "", "faltas": [],
    "pilares": [
        {"chave": "gobrax", "rotulo": "Condução", "peso": 50.0, "nota": 92.0,
         "entrou": True},
        {"chave": "conduta", "rotulo": "Comportamento", "peso": 30.0,
         "nota": 100.0, "entrou": True},
        {"chave": "gr", "rotulo": "Gerenciamento de risco", "peso": 20.0,
         "nota": 88.0, "entrou": True}],
    "no_grupo": {"participantes": 127, "concorrendo": 42,
                 "por_categoria": {"ELITE": 1, "OURO": 1, "PRATA": 12,
                                   "BRONZE": 29, "PENDENTE": 84}},
    "fonte": "Programa de desempenho · ciclo em curso",
}


def _abrir(pg, base_url, minha=None, status=200):
    def rota(route):
        u = route.request.url
        if "/api/motorista/campanha" in u:
            if status != 200:
                return route.fulfill(status=status,
                                     content_type="application/json",
                                     body=json.dumps({"erro": "recusa",
                                                      "mensagem": "Faça login."}))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(minha or MINHA))
        route.fulfill(status=200, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 390, "height": 780})
    # O ENDERECO DE VERDADE E' `/campanha`, servido pelo FastAPI; aqui o
    # servidor da bancada publica a pasta `api/`, entao a pagina abre pelo
    # arquivo. O guard de que `/campanha` responde 200 e' outro, e roda com o
    # app de verdade (`tests/test_aplicativos.py`).
    pg.goto("%s/static/campanha.html" % base_url)
    pg.wait_for_timeout(600)
    return erros


def test_sem_sessao_a_CAPA_nao_mostra_numero_nenhum(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, status=401)
    assert not erros, erros
    assert pg.is_visible("#tela-capa") and not pg.is_visible("#tela-campanha")
    texto = pg.inner_text("#tela-capa")
    for proibido in ("ELITE", "93,6", "127", "42", "Moto"):
        assert proibido not in texto, proibido
    assert "Programa de Desempenho" in texto
    assert pg.is_visible("#b-pedir"), "a capa oferece a entrada"


def test_com_sessao_a_CATEGORIA_vem_primeiro_e_a_posicao_junto(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    primeiro = pg.inner_text("#conteudo .card:first-child")
    assert "ELITE" in primeiro and "93,6" in primeiro
    assert "3º entre os 42" in primeiro
    assert "você está concorrendo" in primeiro


def test_quem_NAO_concorre_le_o_que_falta_ANTES_do_resto(pagina):
    pg, base_url = pagina
    fora = {**MINHA, "concorre": False, "posicao": None, "categoria": "PENDENTE",
            "nota": 96.4,
            "pilares": [{**MINHA["pilares"][0], "nota": None, "entrou": False},
                        *MINHA["pilares"][1:]],
            "faltas": ["sem leitura da telemetria no ciclo — a nota de condução "
                       "vale metade do regulamento, e sem ela não dá para "
                       "concorrer"]}
    _abrir(pg, base_url, minha=fora)
    # `inner_text` devolve o texto RENDERIZADO, e os títulos desta página são
    # maiúsculos por CSS — comparar sem caso evita um guard que quebra no dia
    # em que alguém mexe no `text-transform` sem mexer no conteúdo.
    cards = [x.lower() for x in pg.eval_on_selector_all(
        "#conteudo .card", "els => els.map(e => e.innerText)")]
    assert "não está concorrendo" in cards[0]
    assert "para concorrer, falta" in cards[1], "o que falta vem antes da nota"
    assert "telemetria" in cards[1] and "faltam 1 ciclo" in cards[1]
    assert "sem categoria" in cards[0]


def test_o_pilar_que_nao_entrou_e_DITO_e_nao_vira_zero(pagina):
    pg, base_url = pagina
    fora = {**MINHA, "pilares": [{**MINHA["pilares"][0], "nota": None,
                                  "entrou": False}, *MINHA["pilares"][1:]]}
    _abrir(pg, base_url, minha=fora)
    texto = pg.inner_text("#conteudo")
    assert "sem leitura" in texto
    assert "Condução" in texto and "peso 50%" in texto


def test_o_painel_do_grupo_nao_tem_NOME_de_ninguem(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    texto = pg.inner_text("#conteudo")
    assert "42 de 127 estão concorrendo" in texto
    assert "competem separados" in texto
    assert "Elite" in texto and "Bronze" in texto


def test_o_premio_e_o_prazo_aparecem(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    texto = pg.inner_text("#conteudo")
    assert "Moto elétrica" in texto and "20/12/2026" in texto
    assert "2026-12" in texto


def test_sem_campanha_a_tela_DIZ_e_nao_fica_vazia(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url, minha={"tem_dado": False, "fora_do_escopo": True,
                                "motivo": "Não há campanha em andamento agora.",
                                "fonte": "Programa de desempenho"})
    assert "Não há campanha em andamento" in pg.inner_text("#conteudo")


def test_a_tela_nao_rola_para_o_lado(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    sobra = pg.evaluate("() => document.documentElement.scrollWidth"
                        " - document.documentElement.clientWidth")
    assert sobra == 0, f"a campanha empurra {sobra}px para o lado"
