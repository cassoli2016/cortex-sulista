# -*- coding: utf-8 -*-
"""A TARJA DA LEITURA VELHA, no navegador.

POR QUE ESTE ARQUIVO EXISTE. Em 06/09/2026 o ERP degradou entre 04:41 e 04:51
e a aplicação parou de carregar. A Visão Geral sobreviveu — serviu a leitura de
259 s antes, carimbada — e o resto do portal mostrou "banco inacessível",
porque `velha_ate` era opt-in e só duas consultas tinham aderido.

A rede foi então estendida a trinta consultas. E a regra da casa é que a rede
NÃO vem sozinha: quem serve número velho é obrigado a dizer, porque número
velho servido calado é pior que tela vazia — ninguém desconfia dele.

O QUE SÓ SE PROVA AQUI, e é por isso que este teste é de navegador e não de
texto-fonte:

1. **A tarja aparece de fato.** As duas tarjas anteriores eram desenhadas à mão
   por duas telas, e uma das duas lia o campo com o nome errado
   (`leitura_idade_s` em vez de `leitura_idade_seg`): ela existia, era chamada,
   passava em qualquer leitura de código — e dizia "0 min atrás" em toda
   ocorrência. Defeito que só aparece no dia ruim, que é o dia em que ninguém
   está conferindo o texto da tarja.
2. **Ela SOME quando o número volta a ser bom.** Tarja grudada é pior que tarja
   nenhuma: some a confiança na tela inteira.
3. **A página não estoura no boot.** O `index.html` é um script só, e o gancho
   novo mexe no `window.fetch` — o lugar por onde passa tudo. Um erro ali não
   quebra uma tela, quebra o app (a armadilha do TDZ).
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

USER = {**USUARIO, "admin": True, "telas": []}

# Cabeçalhos que o `JSONResponse` da casa carimba quando `cached(velha_ate=)`
# serve a última leitura boa. São eles — e não o corpo — que a tela lê: custa
# uma leitura de header, não um segundo parse de uma tabela de mil linhas.
VELHA = {"X-Leitura-Velha": "1",
         "X-Leitura-Em": "2026-09-06 04:47:00",
         "X-Leitura-Idade": "259"}

VISAO = {"kpis": {}, "alertas": [], "meta": {}}


def _rota(estado):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo, extra = USER, {}
        elif "/api/visao-geral" in u:
            corpo = dict(VISAO)
            extra = dict(VELHA) if estado["velha"] else {}
            if estado["velha"]:
                # o corpo TAMBÉM vem carimbado (é o `cached` que carimba);
                # a tela lê o header, mas o dublê tem de copiar o real
                corpo.update(leitura_velha=True,
                             leitura_em=VELHA["X-Leitura-Em"],
                             leitura_idade_seg=int(VELHA["X-Leitura-Idade"]))
        else:
            corpo, extra = {}, {}
        route.fulfill(status=200, content_type="application/json",
                      headers=extra, body=json.dumps(corpo))
    return rota


def _abrir(pg, base_url, estado, hash_="#home"):
    pg.route("**/api/**", _rota(estado))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("%s/static/index.html%s" % (base_url, hash_))
    pg.wait_for_selector("#view-home.on", timeout=15000)
    return erros


def test_a_tarja_APARECE_quando_o_erp_nao_respondeu(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, {"velha": True})
    pg.wait_for_selector("#tarja-velha", timeout=15000)
    txt = pg.text_content("#tarja-velha")
    assert "04:47" in txt, "não disse a HORA da leitura: %r" % txt
    assert "4 min" in txt, (
        "não disse a IDADE — é exatamente aqui que a tarja antiga mentia, "
        "dizendo '0 min atrás' para sempre: %r" % txt)
    assert not erros, erros


def test_a_tarja_SOME_quando_o_numero_volta_a_ser_bom(pagina):
    """Tarja grudada é pior que tarja nenhuma: some a confiança na tela toda."""
    pg, base_url = pagina
    estado = {"velha": True}
    _abrir(pg, base_url, estado)
    pg.wait_for_selector("#tarja-velha", timeout=15000)
    estado["velha"] = False
    pg.evaluate("void reloadCurrent()")
    pg.wait_for_selector("#tarja-velha", state="detached", timeout=15000)


def test_trocar_de_tela_nao_carrega_a_tarja_da_anterior(pagina):
    """A tarja fala da tela que está na frente. Levada junto, ela acusaria de
    velha uma tela que acabou de ler o banco."""
    pg, base_url = pagina
    estado = {"velha": True}
    _abrir(pg, base_url, estado)
    pg.wait_for_selector("#tarja-velha", timeout=15000)
    estado["velha"] = False
    pg.evaluate("location.hash = '#qual'")
    pg.wait_for_selector("#tarja-velha", state="detached", timeout=15000)


def test_a_tarja_e_ANUNCIADA_sem_atropelar_quem_le(pagina):
    """`role=status` e não `alert`: o leitor de tela espera a frase em curso
    terminar em vez de interromper quem está lendo os números."""
    pg, base_url = pagina
    _abrir(pg, base_url, {"velha": True})
    pg.wait_for_selector("#tarja-velha", timeout=15000)
    assert pg.get_attribute("#tarja-velha", "role") == "status"


def test_leitura_BOA_nao_desenha_tarja_nenhuma(pagina):
    """O caso normal, e o que faz os outros valerem: se a tarja aparecesse
    sempre, ela não significaria nada."""
    pg, base_url = pagina
    erros = _abrir(pg, base_url, {"velha": False})
    pg.wait_for_timeout(600)
    assert pg.query_selector("#tarja-velha") is None
    assert not erros, erros
