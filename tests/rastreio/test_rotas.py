# -*- coding: utf-8 -*-
"""As rotas públicas do rastreio — e o que continua fechado ao lado delas.

Este arquivo guarda a única exceção ao fail-closed da casa. O risco de uma
exceção não é ela: é ela CRESCER. Alguém acrescenta `/api/rastreio/lista`
amanhã, o prefixo casa, e uma rota nova nasce aberta na internet sem ninguém
decidir isso.

Por isso aqui se cobra as duas metades: que as duas rotas do rastreio
respondam sem sessão, e que o resto do `/api/` continue devolvendo 401 na
mesma requisição anônima.
"""
from __future__ import annotations

import pytest

from api import auth


# --------------------------------------------------------------------------
# a lista de exceções
# --------------------------------------------------------------------------
def test_as_rotas_do_rastreio_sao_publicas():
    assert auth._rota_publica("/rastreio")
    assert auth._rota_publica("/rastreio/")
    assert auth._rota_publica("/api/rastreio/buscar")
    assert auth._rota_publica("/api/rastreio/carga")


def test_a_excecao_e_por_ROTA_e_nao_por_PREFIXO():
    """O guard central deste arquivo.

    Se a liberação fosse por prefixo, qualquer rota nova sob
    `/api/rastreio/` nasceria aberta na internet — inclusive uma que alguém
    criasse para depurar, com o registro cru do ERP dentro.
    """
    assert not auth._rota_publica("/api/rastreio/")
    assert not auth._rota_publica("/api/rastreio/tudo")
    assert not auth._rota_publica("/api/rastreio/buscar/interno")
    assert not auth._rota_publica("/api/rastreio")


def test_o_resto_do_api_continua_fechado():
    for rota in ("/api/visao-geral", "/api/dre/parecer", "/api/operacao/torre",
                 "/api/gestao/usuarios", "/api/pneus", "/api/auth/me"):
        assert not auth._rota_publica(rota), "%s ficou aberta" % rota


def test_a_lista_publica_do_rastreio_e_EXATAMENTE_esta():
    """Um teste sobre o TAMANHO da exceção. Ele fica vermelho quando alguém
    acrescenta uma rota — e é essa a intenção: a conversa acontece na revisão,
    não depois, na internet.

    Ele JÁ acendeu uma vez, quando o aviso por WhatsApp entrou: eram duas
    rotas de leitura e passaram a ser quatro, com duas que ESCREVEM. Cada uma
    dessas quatro tem o freio por IP, e as duas de escrita exigem o mesmo
    segundo fator da busca — quem quiser acrescentar a quinta lê
    `api/rastreio/assinatura.py` antes.
    """
    assert set(auth._PUBLICAS_RASTREIO) == {
        "/api/rastreio/buscar", "/api/rastreio/carga",
        "/api/rastreio/assinar", "/api/rastreio/cancelar",
        "/api/rastreio/zap"}


def test_cada_rota_publica_tem_a_sua_razao():
    """As cinco, e por que cada uma esta aberta. Este teste nao mede codigo —
    mede se quem acrescentar a sexta parou para escrever o motivo dela.

      buscar/carga   leitura, com segundo fator e freio por IP
      assinar        escreve, mesmo segundo fator, e manda a 1a mensagem
      cancelar       escreve, e sair tem de ser mais facil que entrar
      zap            webhook da Z-API; a UNICA acao possivel e descadastrar
    """
    razoes = {
        "/api/rastreio/buscar": "leitura com segundo fator",
        "/api/rastreio/carga": "leitura com segundo fator",
        "/api/rastreio/assinar": "escrita com segundo fator",
        "/api/rastreio/cancelar": "sair e mais facil que entrar",
        "/api/rastreio/zap": "webhook: so descadastra",
    }
    assert set(auth._PUBLICAS_RASTREIO) == set(razoes), (
        "rota publica nova sem razao escrita neste teste")


# --------------------------------------------------------------------------
# a página e o que ela carrega
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pagina() -> str:
    from pathlib import Path
    raiz = Path(auth.__file__).resolve().parent / "static" / "rastreio.html"
    return raiz.read_text(encoding="utf-8")


def test_a_pagina_publica_NAO_carrega_o_app_autenticado(pagina):
    """36 mil linhas de painel, o roteador por hash, o RBAC e o Leaflet não
    servem a quem só quer saber se a carga chegou — e seriam baixados no 4G do
    pátio de uma fábrica.

    O teste olha o que a página CARREGA, não o que ela menciona: a primeira
    versão procurava a string "index.html" e ficava vermelha por causa do
    comentário que explica justamente que ela não o carrega.
    """
    import re

    # SO AS TAGS DO DOCUMENTO: o que o navegador baixa ANTES de qualquer
    # clique. O Leaflet existe na página, mas dentro do JavaScript, e só é
    # buscado quando alguém abre uma carga — sao 413 KB que ninguem deve pagar
    # so por ter digitado o numero da nota.
    tags = re.findall(r"<(?:script|link)[^>]*(?:src|href)\s*=\s*"
                      r"[\"']([^\"']+)[\"']", pagina)
    for u in tags:
        assert "index.html" not in u, "a página carrega o app: %s" % u
        assert "leaflet" not in u.lower(), (
            "o Leaflet está sendo carregado de saída: %s" % u)
    assert any("anel.js" in u for u in tags)


def test_o_leaflet_e_carregado_SOB_DEMANDA(pagina):
    """Ele precisa existir — o mapa é parte da tela — mas só depois do clique.
    Se um dia virar tag no topo, o teste acima acende."""
    assert "carregarLeaflet" in pagina
    assert "/static/vendor/leaflet/leaflet.js" in pagina


def test_o_mapa_desenha_AREA_e_nao_alfinete(pagina):
    """O círculo é a peça honesta: a coordenada vem arredondada a ~11 km, e um
    alfinete prometeria precisão que ela não tem."""
    assert "L.circle" in pagina
    assert "raio_km" in pagina


def test_a_pagina_pede_os_DOIS_campos(pagina):
    assert 'id="doc"' in pagina and 'id="cnpj"' in pagina
    assert pagina.count("required") >= 2


def test_os_campos_sao_confortaveis_no_CELULAR(pagina):
    """`inputmode=numeric` abre o teclado numérico; `font-size:16px` impede o
    iOS de dar zoom sozinho ao focar — o zoom desloca a página e a pessoa
    perde o botão de vista."""
    assert pagina.count('inputmode="numeric"') >= 2
    assert "font-size:16px" in pagina
    assert "min-height:48px" in pagina


def test_a_pagina_declara_viewport_e_area_segura(pagina):
    assert "viewport-fit=cover" in pagina
    assert "env(safe-area-inset-bottom)" in pagina


def test_a_pagina_NAO_pede_indexacao(pagina):
    """Carga de cliente não entra em busca do Google."""
    assert 'name="robots"' in pagina and "noindex" in pagina


def test_a_pagina_tem_os_TRES_estados_de_tema(pagina):
    """A regra da casa: paleta clara no `:root` puro, o escuro do sistema
    guardado por `:not([data-theme="light"])`, e o `[data-theme="dark"]`
    repetindo os mesmos tokens."""
    assert "prefers-color-scheme: dark" in pagina
    assert ':root:not([data-theme="light"])' in pagina
    assert ':root[data-theme="dark"]' in pagina
