"""Aplicativo novo vai DIRETO para o menu — e este arquivo e que garante isso.

O pedido de quem opera foi: *"todos os aplicativos que criarmos devem ir direto
para esse menu"*. "Direto" nao se consegue com disciplina. A propria casa tem a
regra de que TELA NOVA TEM SEIS REGISTROS justamente porque alguem sempre
esquece um -- e a tela esquecida nao da erro, so nao aparece. Ausencia nao tem
sintoma.

Entao a promessa e mecanica, e mora aqui: **todo `api/static/*.html` que nao
seja o painel tem de estar em `api/aplicativos.APLICATIVOS`**. Publicar
`api/static/frota.html` e esquecer o registro deixa a suite VERMELHA nomeando o
arquivo -- em vez de deixar o aplicativo invisivel e ninguem descobrir por
meses.

O caminho e o DISCO, nao o codigo: aplicativo e pagina propria, e pagina propria
e arquivo. Um teste que lesse as rotas do `main.py` acharia o mesmo hoje e
deixaria passar o dia em que alguem servir a pagina de outro jeito.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import aplicativos
from api import main

RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "api" / "static"

# TestClient FORA de `with`: sem lifespan. Estas rotas sao publicas e nao tocam
# banco; o `_startup_auth` aplicaria migration no schema de PRODUCAO.
cliente = TestClient(main.app)


def _paginas_no_disco() -> set[str]:
    return {p.name for p in STATIC.glob("*.html")} - {aplicativos.PAINEL}


# ------------------------------------------------- a promessa: nada fica fora

def test_toda_pagina_de_aplicativo_esta_no_registro():
    """O guard que sustenta o "vai direto para o menu"."""
    fora = _paginas_no_disco() - aplicativos.arquivos_registrados()
    assert not fora, (
        f"aplicativo(s) sem registro: {sorted(fora)}. Toda pagina propria entra "
        "em api/aplicativos.APLICATIVOS -- e so assim ela aparece na tela "
        "`apps`. Se o arquivo NAO for um aplicativo, ele nao devia estar em "
        "api/static/ solto.")


def test_o_registro_nao_aponta_para_arquivo_que_nao_existe():
    """O outro lado: registro que sobrou depois de o arquivo sair vira cartao
    com link morto na tela de quem procura o endereco."""
    sumidos = aplicativos.arquivos_registrados() - {p.name for p in STATIC.glob("*.html")}
    assert not sumidos, f"registro aponta para arquivo inexistente: {sorted(sumidos)}"


def test_o_painel_nao_e_aplicativo():
    """`index.html` e a casa, nao um app: listado ali, viraria um cartao
    apontando para a propria tela em que a pessoa ja esta."""
    assert aplicativos.PAINEL not in aplicativos.arquivos_registrados()


# ------------------------------------------------------- o registro se sustenta

@pytest.mark.parametrize("app", aplicativos.APLICATIVOS, ids=lambda a: a["id"])
def test_cada_aplicativo_tem_o_que_o_cartao_precisa(app):
    """Cartao sem "para quem" ou sem "como entra" nao ajuda ninguem: quem abre
    esta tela quer saber se manda o link para o cliente ou para o motorista."""
    for campo in ("id", "nome", "arquivo", "rota", "publico", "entrada", "descricao"):
        assert app.get(campo), f"{app.get('id')}: campo '{campo}' vazio"
    assert app["rota"].startswith("/"), "a rota e um caminho, nao um endereco completo"
    assert not app["rota"].startswith("/api/"), "aplicativo e pagina, nao endpoint"


def test_os_ids_nao_se_repetem():
    ids = [a["id"] for a in aplicativos.APLICATIVOS]
    assert len(ids) == len(set(ids)), f"id repetido: {ids}"


@pytest.mark.parametrize("app", aplicativos.APLICATIVOS, ids=lambda a: a["id"])
def test_toda_rota_de_aplicativo_responde(app):
    """Cartao com endereco que nao abre e pior que cartao nenhum -- a pessoa
    manda o link para um cliente e descobre pelo cliente."""
    for rota in aplicativos.rotas(app):
        r = cliente.get(rota)
        assert r.status_code == 200, f"{app['id']}: {rota} devolveu {r.status_code}"
        assert r.content, f"{app['id']}: {rota} respondeu vazio"


# ---------------------------------------------------------------- o que a tela le

def test_o_endereco_sai_com_a_origem_de_quem_pediu():
    """O CORTEX responde por mais de um caminho ao mesmo tempo (o tunel
    Cloudflare, o ngrok ao lado dele, o 127.0.0.1 da bancada). Endereco fixo
    faria a pessoa copiar um link que nao e o dela."""
    lista = aplicativos.listar("https://cortex.exemplo.com.br")
    assert lista, "o registro esta vazio"
    for a in lista:
        assert a["url"].startswith("https://cortex.exemplo.com.br/"), a["url"]
        assert a["url"].endswith(a["rota"]), a["url"]


def test_sem_base_nao_inventa_endereco():
    """Sem saber de onde veio o pedido, a tela mostra o caminho relativo -- e
    NAO um dominio chutado, que e o jeito de entregar link quebrado."""
    for a in aplicativos.listar():
        assert a["url"] == a["rota"]
        assert a["qr"] is None, "QR de caminho relativo nao serve para escanear"


def test_o_qr_e_svg_embutido_e_nao_imagem_de_fora():
    """A casa nao busca imagem de host nenhum em runtime (por isso o ECharts e
    o Leaflet sao vendorizados). O QR segue a mesma regra."""
    svg = aplicativos.qr_svg("https://cortex.exemplo.com.br/motorista")
    if svg is None:
        pytest.skip("segno nao instalado nesta instalacao")
    assert svg.lstrip().startswith("<svg"), svg[:60]
    assert "http" not in svg.split(">")[0], "o proprio SVG nao pode buscar nada fora"


def test_sem_a_biblioteca_o_aplicativo_continua_no_menu(monkeypatch):
    """Aplicativo que some do menu porque faltou uma biblioteca de DESENHO
    seria pior que aplicativo sem QR."""
    import builtins
    real = builtins.__import__

    def sem_segno(nome, *a, **kw):
        if nome == "segno":
            raise ImportError("segno ausente")
        return real(nome, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", sem_segno)
    lista = aplicativos.listar("https://cortex.exemplo.com.br")
    assert len(lista) == len(aplicativos.APLICATIVOS)
    assert all(a["qr"] is None for a in lista)
    assert all(a["url"] for a in lista), "o endereco continua, que e o essencial"


# ------------------------------------------------------- a tela existe mesmo

def test_a_tela_apps_esta_registrada_no_acesso():
    """De todo usuario logado, como o Suporte: e um diretorio de links, e os
    aplicativos tem autenticacao propria."""
    from api import auth
    assert "apps" in auth.TELAS_TODO_LOGADO
    assert "apps" in auth.TELAS_FORA_DO_RBAC
    assert auth.rota_sem_tela("/api/aplicativos"), (
        "a rota precisa estar em _ROTAS_SEM_TELA: o middleware e fail-closed e "
        "barraria /api/* nao mapeada para quem nao e administrador")


def test_a_rota_da_lista_exige_sessao():
    """Diretorio de links nao e segredo, mas tambem nao e pagina publica: quem
    nao entrou nao precisa saber o que a casa tem no ar."""
    assert cliente.get("/api/aplicativos").status_code == 401


# ------------------------------------------ o atalho na tela de inicio do celular
#
# O DEFEITO, relatado por quem opera em 10/09/2026: o rastreio adicionado a
# tela de inicio saia SEM A LOGO DA SULISTA. A pagina declarava so o `favicon`.
#
# Sao DOIS mecanismos e nenhum cai no outro: sem `apple-touch-icon` o Safari
# poe uma CAPTURA DA PAGINA no lugar do icone, e sem `manifest` o Chrome
# estica o favicon de 32px. Nos dois casos o atalho perde a marca -- e no
# rastreio quem ve isso e o cliente que espera a carga.
#
# Nada disso levanta erro: a pagina funciona, o icone e que nao existe. Por
# isso o guard sai do REGISTRO, e nao de uma lista escrita a mao aqui: o
# aplicativo que entrar amanha ja nasce cobrado.

def _cabeca(app) -> str:
    html = (STATIC / app["arquivo"]).read_text(encoding="utf-8")
    return html[:html.index("</head>")] if "</head>" in html else html


@pytest.mark.parametrize("app", aplicativos.APLICATIVOS, ids=lambda a: a["id"])
def test_o_aplicativo_tem_icone_para_a_tela_de_inicio(app):
    """As duas declaracoes, porque sao dois sistemas operacionais."""
    cab = _cabeca(app)
    assert 'rel="apple-touch-icon"' in cab, (
        f"{app['id']}: sem apple-touch-icon o iPhone usa uma captura da tela "
        f"como icone")
    assert 'rel="manifest"' in cab, (
        f"{app['id']}: sem manifesto o Android estica o favicon de 32px")


@pytest.mark.parametrize("app", aplicativos.APLICATIVOS, ids=lambda a: a["id"])
def test_o_manifesto_do_aplicativo_e_PROPRIO_e_abre_nele_mesmo(app):
    """Reusar o manifesto do painel poria o atalho para abrir em `/` com o
    nome "Cortex" -- o cliente do rastreio cairia numa tela de login, e o
    motorista tambem, porque ele nao tem conta no painel."""
    import json
    import re
    cab = _cabeca(app)
    m = re.search(r'rel="manifest"\s+href="([^"]+)"', cab)
    assert m, f"{app['id']}: manifesto sem href"
    href = m.group(1)
    assert href != "/static/manifest.json", (
        f"{app['id']}: esta usando o manifesto do PAINEL, que abre em `/`")
    arq = STATIC / href.removeprefix("/static/")
    assert arq.exists(), f"{app['id']}: manifesto declarado e inexistente: {href}"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    assert dados.get("start_url") == app["rota"], (
        f"{app['id']}: o atalho abriria em {dados.get('start_url')!r} e a rota "
        f"do aplicativo e {app['rota']!r}")
    # o start_url tem de caber no scope, senao o navegador RECUSA o manifesto
    # inteiro -- e a recusa e silenciosa, que e como este defeito voltaria
    assert dados.get("start_url", "").startswith(dados.get("scope", "\0")), (
        f"{app['id']}: start_url fora do scope — o navegador ignora o manifesto")


@pytest.mark.parametrize("app", aplicativos.APLICATIVOS, ids=lambda a: a["id"])
def test_todo_icone_declarado_EXISTE_no_disco(app):
    """A varredura sai do arquivo e confere o DISCO. Icone que aponta para
    nada nao levanta erro nenhum: o celular so mostra um quadrado cinza."""
    import json
    import re
    cab = _cabeca(app)
    alvos = set(re.findall(r'rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', cab))
    href = re.search(r'rel="manifest"\s+href="([^"]+)"', cab).group(1)
    manif = json.loads((STATIC / href.removeprefix("/static/")).read_text(encoding="utf-8"))
    alvos |= {i["src"] for i in manif.get("icons", [])}
    assert alvos, "nenhum icone declarado — a varredura passaria por vacuidade"
    for src in sorted(alvos):
        assert (STATIC / src.removeprefix("/static/")).exists(), (
            f"{app['id']}: icone declarado e inexistente: {src}")


@pytest.mark.parametrize("app", aplicativos.APLICATIVOS, ids=lambda a: a["id"])
def test_o_manifesto_do_aplicativo_e_SERVIDO(app):
    """Declarar nao e servir. O manifesto mora sob `/static`, que e publico —
    mas o rastreio e a unica pagina da casa aberta a quem nao tem conta, e um
    manifesto atras de sessao seria ignorado em silencio no celular do
    cliente."""
    import re
    href = re.search(r'rel="manifest"\s+href="([^"]+)"', _cabeca(app)).group(1)
    c = TestClient(main.app)
    r = c.get(href)
    assert r.status_code == 200, f"{app['id']}: manifesto responde {r.status_code}"
    assert r.json().get("icons"), f"{app['id']}: manifesto servido sem icones"
