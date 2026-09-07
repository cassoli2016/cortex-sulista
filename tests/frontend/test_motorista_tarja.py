# -*- coding: utf-8 -*-
"""A tarja de leitura velha NO APP DO MOTORISTA — no navegador.

O app é uma PÁGINA PRÓPRIA (`motorista.html`, 16 KB), e não uma tela do
`index.html`: o leitor está em 4G de rodovia e os 2,5 MB do painel são uma tela
branca para ele. A consequência é que o gancho do `fetch` que desenha a tarja
para as trinta telas da casa **não alcança esta página** — ela tem o próprio
`pedir()`.

E é exatamente por isso que este arquivo existe. A regra da casa (v0.258.0) é
que a tarja vem do CABEÇALHO `X-Leitura-Velha`, não do corpo, porque enquanto
cada tela desenhava a sua uma delas lia um campo que nunca existiu e dizia
"0 min atrás" para sempre — defeito que só aparece no dia ruim, que é o dia em
que ninguém confere o texto da tarja. Uma segunda página desenhando a própria
tarja é uma segunda chance de repetir isso, e o guard tem de ser de NAVEGADOR:
ler o texto-fonte provaria que o código existe, não que ele aparece.

O que se prova aqui é o mesmo que a casa prova para o painel: a tarja APARECE,
diz a IDADE, e SOME quando o número volta a ser bom (tarja grudada é pior que
tarja nenhuma — some a confiança na tela inteira).
"""
from __future__ import annotations

import json

#: O que `/api/motorista/eu` devolve. `secoes` decide quais abas a barra de
#: baixo desenha — item que não existe para o agregado não aparece vazio.
EU = {"nome": "João da Silva", "telefone": "5547999990001", "mestre": False,
      "secoes": {"viagem": True, "produtividade": True, "desempenho": True,
                 "multas": True, "ocorrencias": True, "jornada": False}}

VIAGEM = {"viagem": {
    "numero": "178010", "placa": "NYP3J22", "carretas": ["JOK3011"],
    "cliente": "INDUSTRIA EXEMPLO", "origem": "JOINVILLE/SC",
    "destino": "CURITIBA/PR", "saida": "2026-09-06 06:10",
    "previsao_chegada": "2026-09-06 14:00", "vazio": False}}

#: O que o `JSONResponse` da casa carimba quando serve a última leitura boa.
VELHA = {"X-Leitura-Velha": "1",
         "X-Leitura-Em": "2026-09-06 04:47:00",
         "X-Leitura-Idade": "7380"}          # 2h03


def _rota(estado):
    def rota(route):
        u = route.request.url
        if "/api/motorista/eu" in u:
            corpo, extra = EU, {}
        elif "/api/motorista/viagem" in u:
            corpo = dict(VIAGEM)
            extra = dict(VELHA) if estado["velha"] else {}
            if estado["velha"]:
                # O CORPO TAMBEM VEM CARIMBADO — é o `cached` que carimba, e o
                # header é derivado dele. O dublê copia o real inteiro: dublê
                # mais pobre que o original esconde o caminho que interessa,
                # que aqui é justamente "a página ignora o corpo e lê o header".
                corpo.update(leitura_velha=True,
                             leitura_em=VELHA["X-Leitura-Em"],
                             leitura_idade_seg=int(VELHA["X-Leitura-Idade"]))
        else:
            corpo, extra = {}, {}
        route.fulfill(status=200, content_type="application/json",
                      headers=extra, body=json.dumps(corpo))
    return rota


def _abrir(pg, base_url, estado):
    pg.route("**/api/**", _rota(estado))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    return erros


def test_a_tarja_APARECE_e_diz_a_idade(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, {"velha": True})
    pg.wait_for_selector("#tarja-velha:not([hidden])", timeout=15000)
    txt = pg.text_content("#tarja-velha")
    assert "2h" in txt, (
        "não disse a IDADE — é exatamente aqui que a tarja antiga da casa "
        "mentia, dizendo '0 min atrás' para sempre: %r" % txt)
    assert not erros, erros


def test_a_tarja_SOME_quando_o_numero_volta_a_ser_bom(pagina):
    pg, base_url = pagina
    estado = {"velha": True}
    _abrir(pg, base_url, estado)
    pg.wait_for_selector("#tarja-velha:not([hidden])", timeout=15000)

    estado["velha"] = False
    # A aba guarda o que ja carregou (`cache`): sem apagar a entrada, o clique
    # repintaria a MESMA resposta e a tarja nunca teria chance de sumir.
    pg.evaluate("void (delete cache.viagem, abrirAba('viagem'))")
    pg.wait_for_selector("#tarja-velha", state="hidden", timeout=15000)


def test_a_pagina_le_o_CABECALHO_e_nao_o_corpo(pagina):
    """O guard que separa "funciona" de "funciona pelo motivo certo".

    O corpo vem carimbado e o header NÃO: se a página estivesse lendo o corpo —
    que é como ela nasceu, antes da v0.258.0 —, a tarja apareceria e o teste de
    cima passaria com a implementação errada. Aqui ela tem de ficar ESCONDIDA.
    """
    pg, base_url = pagina

    def rota(route):
        u = route.request.url
        if "/api/motorista/eu" in u:
            corpo = EU
        elif "/api/motorista/viagem" in u:
            corpo = {**VIAGEM, "leitura_velha": True,
                     "leitura_em": VELHA["X-Leitura-Em"],
                     "leitura_idade_seg": 7380}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))   # sem os headers

    pg.route("**/api/**", rota)
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    pg.wait_for_timeout(300)
    assert pg.is_hidden("#tarja-velha"), (
        "a tarja saiu do CORPO — a casa carimba o header, e é dele que toda "
        "tela lê; ler o corpo é repetir o defeito que a v0.258.0 consertou")


def test_a_idade_vem_do_SERVIDOR_e_nao_do_relogio_do_aparelho(pagina):
    """O relógio é do motorista e pode estar errado (ou ajustado à mão). Se a
    página calculasse a diferença contra `Date.now()`, um celular meia hora
    adiantado diria "30 min atrás" sobre um dado que acabou de chegar — e um
    atrasado esconderia dado velho de verdade."""
    pg, base_url = pagina
    # `X-Leitura-Em` no FUTURO e idade real de 2h: quem usa o relógio local
    # calcularia um negativo (ou zero); quem usa o header diz 2h.
    estado = {"velha": True}
    VELHA["X-Leitura-Em"] = "2099-01-01 00:00:00"
    try:
        _abrir(pg, base_url, estado)
        pg.wait_for_selector("#tarja-velha:not([hidden])", timeout=15000)
        assert "2h" in pg.text_content("#tarja-velha")
    finally:
        VELHA["X-Leitura-Em"] = "2026-09-06 04:47:00"
