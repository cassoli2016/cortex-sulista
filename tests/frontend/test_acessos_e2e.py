"""Acessos por usuário na TELA, contra o index.html real (13/09/2026).

Quem decide o acesso é o servidor (`tests/test_acessos_rotas.py`); aqui se
prova o que a pessoa VÊ: a página inicial dela, o aviso quando o endereço
pede uma tela que ela não abre (antes: outra tela aparecia e o endereço
continuava mentindo), o menu sem grupo vazio, a aba tirada que não abre por
atalho nenhum, e a ficha de Acessos da Gestão mandando a lista completa.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

RADAR = json.loads((Path(__file__).parent / "radar_payload.json").read_text(encoding="utf-8"))

#: Uma pessoa de perfil comum: só o Fluxo de Caixa, fora as telas de todo logado.
COMUM = {**USUARIO, "admin": False, "perfil": "Operação", "telas": ["fluxo"]}

_USR = {"perfil_admin": 0, "ativo": 1, "deve_trocar_senha": 0, "bloqueado_ate": None,
        "criado_em": "2026-09-01 10:00:00", "ultimo_login": None, "telefone": None,
        "telefone_fmt": "", "cargo": None, "setor": None, "ramal": None,
        "cliente_cnpj_raiz": None, "foto_em": None, "pagina_inicial": None}
GESTAO = {
    "/api/gestao/usuarios": {"usuarios": [
        {**_USR, "id": 3, "nome": "Chefe Souza", "email": "chefe@exemplo.test",
         "perfil_id": 1, "perfil": "Administrador", "perfil_admin": 1,
         "acessos": [{"chave": "dre", "efeito": "tirar"}]},
        {**_USR, "id": 7, "nome": "Beto Lima", "email": "beto@exemplo.test",
         "perfil_id": 2, "perfil": "Operação",
         "acessos": [{"chave": "cop", "efeito": "liberar"}]},
    ]},
    "/api/gestao/perfis": {"perfis": [
        {"id": 1, "nome": "Administrador", "descricao": "", "admin": 1,
         "telas": ["fluxo", "dre", "cop", "dreexc"], "usuarios": 1},
        {"id": 2, "nome": "Operação", "descricao": "", "admin": 0,
         "telas": ["fluxo", "dre"], "usuarios": 1},
    ]},
    "/api/gestao/telas": {"telas": [
        {"chave": "fluxo", "rotulo": "Fluxo de Caixa", "grupo": "Financeiro"},
        {"chave": "dre", "rotulo": "DRE Gerencial", "grupo": "Controladoria"},
        {"chave": "dreexc", "rotulo": "Excluir lançamentos da DRE", "grupo": "Controladoria"},
        {"chave": "cop", "rotulo": "Copiloto", "grupo": "Início"},
        # uma tela que o Beto NÃO abre (fora do perfil e sem ajuste): sem ela
        # na lista, "oferecer só o que a pessoa abre" e "oferecer tudo" dão o
        # mesmo resultado, e o guard da página inicial passava sabotado
        {"chave": "folha", "rotulo": "Folha de Pagamento", "grupo": "Recursos Humanos"},
    ]},
    "/api/gestao/config": {},
    "/api/gestao/acessos/catalogo": {
        "abas": [{"chave": "dre.pano", "tela": "dre", "tela_rotulo": "DRE Gerencial",
                  "grupo": "Controladoria", "rotulo": "Panorama"}],
        "paginas_de_todos": ["apps", "radar", "sup"], "paginas_de_admin": ["gestao", "srv"],
        "sem_menu": ["desrh", "dreexc"]},
}


def _abrir(pg, base, quem=COMUM, hash_="", gravadas=None, espera="#kpis-radar .kpi"):
    def rota(route):
        u = route.request.url
        caminho = "/" + u.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        if route.request.method == "POST" and gravadas is not None:
            try:
                gravadas.append((caminho, route.request.post_data_json))
            except Exception:  # noqa: BLE001
                gravadas.append((caminho, None))
            corpo = {"ok": True}
        elif caminho == "/api/auth/me":
            corpo = quem
        elif caminho.startswith("/api/radar"):
            corpo = RADAR
        else:
            corpo = GESTAO.get(caminho, {})
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base}/static/index.html{hash_}")
    if espera:
        pg.wait_for_selector(espera, timeout=20000)
    return erros


def _ativa(pg) -> str:
    return pg.evaluate("() => (document.querySelector('.view.on')||{}).id || ''")


# ───────────────────────────────────────────────────── página inicial ──────

def test_sem_endereco_abre_a_pagina_inicial_DA_PESSOA(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, quem={**COMUM, "pagina_inicial": "apps"}, espera="#view-apps.on")
    assert _ativa(pg) == "view-apps"
    assert not erros, erros


def test_pagina_inicial_sem_acesso_cai_no_radar(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, quem={**COMUM, "pagina_inicial": "dre"})
    assert _ativa(pg) == "view-radar"
    assert not erros, erros


# ─────────────────────────────────────────────── endereço sem acesso ───────

def test_endereco_de_tela_sem_acesso_AVISA_e_corrige_o_endereco(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, hash_="#dre")
    assert _ativa(pg) == "view-radar"
    assert pg.evaluate("location.hash") == "#radar", "o endereço não pode seguir dizendo #dre"
    aviso = pg.locator("#avisoAcesso")
    assert aviso.is_visible()
    assert pg.evaluate("VIEWS.dre") in aviso.inner_text()
    assert not erros, erros


def test_tela_permitida_nao_avisa_nada(pagina):
    pg, base = pagina
    _abrir(pg, base, hash_="#radar")
    assert pg.locator("#avisoAcesso").count() == 0


# ────────────────────────────────────────────────────────────── menu ───────

def test_grupo_sem_nenhuma_tela_da_pessoa_SOME_do_menu(pagina):
    """A lista escrita à mão tinha 10 dos 15 grupos: Telemetria, ANTT,
    Gestão, TMS e WMS mostravam o título vazio."""
    pg, base = pagina
    _abrir(pg, base)
    for grupo in ("grpTel", "grpAntt", "grpGes", "grpTms", "grpWms", "grpAdm", "grpCtr"):
        assert pg.locator("#" + grupo).is_hidden(), f"{grupo} aparece sem nenhuma tela"
    assert pg.locator("#grpFin").is_visible(), "o grupo da tela que ela TEM continua"


# ────────────────────────────────────────────────────────────── abas ───────
# O mecanismo é o mesmo para qualquer barra de abas; as do Radar servem de
# alvo porque a tela abre sem ERP. (As abas bloqueáveis de verdade são as de
# `acessos.ABAS`, com rota própria — a tela só as esconde.)

def test_aba_tirada_some_e_a_selecao_pula_para_a_proxima(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, quem={**COMUM, "abas_ocultas": [["radar", "trc"], ["radar", "diesel"]]})
    assert pg.locator("#tabradar-trc").is_hidden() and pg.locator("#tabradar-diesel").is_hidden()
    assert pg.get_attribute("#tabradar-reforma", "aria-selected") == "true"
    assert pg.locator("#aba-radar-trc").is_hidden()
    assert not erros, erros


def test_aba_tirada_nao_abre_por_atalho_nem_pelo_giro(pagina):
    pg, base = pagina
    _abrir(pg, base, quem={**COMUM, "abas_ocultas": [["radar", "diesel"]]})
    pg.evaluate("() => abaTrocar('radar', 'diesel')")
    assert pg.locator("#aba-radar-diesel").is_hidden(), "abriu por atalho"
    assert pg.get_attribute("#tabradar-trc", "aria-selected") == "true"
    vistas = []
    for _ in range(4):
        pg.evaluate("() => abaProxima('radar')")
        vistas.append(pg.evaluate(
            "() => document.querySelector('.subtabs[data-abas=\"radar\"] button[aria-selected=\"true\"]').dataset.aba"))
    assert "diesel" not in vistas and vistas[:3] == ["reforma", "antt", "trc"]


def test_sem_aba_tirada_todas_seguem_visiveis(pagina):
    pg, base = pagina
    _abrir(pg, base)
    for aba in ("trc", "diesel", "reforma", "antt"):
        assert pg.locator("#tabradar-" + aba).is_visible()


# ─────────────────────────────────────────────── Gestão › Usuários ─────────

def _gestao(pg, base, gravadas=None):
    return _abrir(pg, base, quem=USUARIO, hash_="#gestao", gravadas=gravadas, espera="#ges-usr tr")


def test_a_lista_resume_os_ajustes_e_avisa_que_admin_nao_os_aplica(pagina):
    pg, base = pagina
    _gestao(pg, base)
    linhas = pg.inner_text("#ges-usr")
    assert "+1 tela" in linhas
    assert "ajustes não se aplicam: admin" in linhas


def test_a_ficha_de_acessos_manda_a_lista_COMPLETA(pagina):
    pg, base = pagina
    gravadas = []
    _gestao(pg, base, gravadas)
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Acessos')")
    pg.wait_for_selector(".ga-tela-sel", timeout=5000)
    assert pg.input_value('.ga-tela-sel[data-chave="cop"]') == "liberar", "o ajuste guardado vem marcado"
    pg.select_option('.ga-tela-sel[data-chave="dre"]', "tirar")
    pg.check('.ga-aba-cx[value="dre.pano"]')
    assert "1 liberada" in pg.inner_text("#ga-resumo")
    pg.click("#modalBox button:has-text('Salvar acessos')")
    pg.wait_for_timeout(400)
    enviados = [c for u, c in gravadas if u == "/api/gestao/usuarios/7"]
    assert enviados, "o POST dos acessos não saiu"
    assert set(enviados[0]) == {"acessos"}, "a ficha não mexe em nenhum outro campo"
    assert sorted((a["chave"], a["efeito"]) for a in enviados[0]["acessos"]) == [
        ("cop", "liberar"), ("dre", "tirar"), ("dre.pano", "tirar")]


def test_a_ficha_de_um_admin_diz_que_os_ajustes_nao_se_aplicam(pagina):
    pg, base = pagina
    _gestao(pg, base)
    pg.click("#ges-usr tr:has-text('Chefe Souza') button:has-text('Acessos')")
    pg.wait_for_selector("#ga-resumo", timeout=5000)
    assert "não se aplicam" in pg.inner_text("#modalBox")
    assert "tudo" in pg.inner_text("#ga-resumo")


def test_a_pagina_inicial_so_oferece_o_que_a_pessoa_abre(pagina):
    pg, base = pagina
    _gestao(pg, base)
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Editar')")
    pg.wait_for_selector("#gu-pagina option", state="attached", timeout=5000)
    valores = set(pg.eval_on_selector_all("#gu-pagina option", "os => os.map(o => o.value)"))
    assert {"", "apps", "sup", "fluxo", "dre", "cop"} <= valores, valores
    assert not ({"dreexc", "gestao", "srv"} & valores), "permissão sem tela e área de admin"
    assert "folha" not in valores, "a Folha não está no perfil nem foi liberada"
    pg.select_option("#gu-perfil", "1")   # vira administrador: Gestão, Saúde e tudo o mais entram
    valores = set(pg.eval_on_selector_all("#gu-pagina option", "os => os.map(o => o.value)"))
    assert {"gestao", "srv", "folha"} <= valores


def test_a_pagina_inicial_so_vai_no_envio_quando_MUDA(pagina):
    pg, base = pagina
    gravadas = []
    _gestao(pg, base, gravadas)
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Editar')")
    pg.wait_for_selector("#gu-ramal", timeout=5000)
    pg.fill("#gu-ramal", "115")
    pg.click("#modalBox button:has-text('Salvar')")
    pg.wait_for_timeout(400)
    primeiro = [c for u, c in gravadas if u == "/api/gestao/usuarios/7"][-1]
    assert "pagina_inicial" not in primeiro

    pg.wait_for_selector("#ges-usr tr", timeout=5000)
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Editar')")
    pg.wait_for_selector("#gu-pagina option", state="attached", timeout=5000)
    pg.select_option("#gu-pagina", "dre")
    pg.click("#modalBox button:has-text('Salvar')")
    pg.wait_for_timeout(400)
    segundo = [c for u, c in gravadas if u == "/api/gestao/usuarios/7"][-1]
    assert segundo["pagina_inicial"] == "dre"
