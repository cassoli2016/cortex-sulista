# -*- coding: utf-8 -*-
"""Relatório de permissões na Gestão, no navegador (15/09/2026).

O que se prova aqui é o que quem revisa acessos VÊ e LEVA:
1. cada pessoa com as telas que abre, agrupadas, e a exceção (tela liberada
   na ficha da pessoa) destacada da que vem do perfil;
2. o que um ajuste tirou — tela e aba — escrito, não escondido;
3. buscar pelo NOME de uma tela responde "quem abre esta tela?";
4. a exportação leva exatamente o que está filtrado, nos dois formatos, e o
   CSV abre certo no Excel em português (BOM, `;`).
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador", "telas": [], "id": 3}

_USR = {"perfil_admin": 0, "ativo": 1, "deve_trocar_senha": 0, "bloqueado_ate": None,
        "criado_em": "2026-09-01 10:00:00", "ultimo_login": None, "telefone": None,
        "telefone_fmt": "", "cargo": None, "setor": None, "ramal": None,
        "cliente_cnpj_raiz": None, "foto_em": None, "pagina_inicial": None, "acessos": []}
TODOS = [{"chave": k, "origem": "todo_logado"} for k in ("apps", "radar", "sup")]
TELAS = [
    {"chave": "fluxo", "rotulo": "Fluxo de Caixa", "grupo": "Financeiro"},
    {"chave": "dre", "rotulo": "DRE Gerencial", "grupo": "Controladoria"},
    {"chave": "cop", "rotulo": "Copiloto", "grupo": "Início"},
    {"chave": "folha", "rotulo": "Folha de Pagamento", "grupo": "Recursos Humanos"},
    {"chave": "apps", "rotulo": "Aplicativos", "grupo": "Início"},
    {"chave": "radar", "rotulo": "Radar do Transporte", "grupo": "Início"},
    {"chave": "sup", "rotulo": "Suporte", "grupo": "Suporte"},
    {"chave": "gestao", "rotulo": "Gestão", "grupo": "Sistema"},
    {"chave": "srv", "rotulo": "Saúde do Servidor", "grupo": "Sistema"},
]
PERMISSOES = {
    "usuarios": [
        {"id": 3, "nome": "Chefe Souza", "email": "chefe@exemplo.test", "ativo": True,
         "perfil": "Administrador", "admin": True, "ultimo_login": None, "pagina_inicial": None,
         "telas": [{"chave": k, "origem": "administrador"} for k in ("fluxo", "dre", "cop", "folha")]
                  + TODOS + [{"chave": "gestao", "origem": "administrador"},
                             {"chave": "srv", "origem": "administrador"}],
         "tiradas": [], "abas_tiradas": [], "ajustes_ignorados": 1},
        {"id": 7, "nome": "Beto Lima", "email": "beto@exemplo.test", "ativo": True,
         "perfil": "Operação", "admin": False, "ultimo_login": None, "pagina_inicial": None,
         "telas": [{"chave": "fluxo", "origem": "perfil"}, {"chave": "cop", "origem": "liberada"}] + TODOS,
         "tiradas": ["dre"], "abas_tiradas": [], "ajustes_ignorados": 0},
        {"id": 9, "nome": "Caio Antigo", "email": "caio@exemplo.test", "ativo": False,
         "perfil": "Operação", "admin": False, "ultimo_login": None, "pagina_inicial": None,
         "telas": [{"chave": "fluxo", "origem": "perfil"}, {"chave": "dre", "origem": "perfil"}] + TODOS,
         "tiradas": [], "abas_tiradas": ["dre.pano"], "ajustes_ignorados": 0},
    ],
    "telas": TELAS,
    "abas": [{"chave": "dre.pano", "tela": "dre", "tela_rotulo": "DRE Gerencial",
              "grupo": "Controladoria", "rotulo": "Conta a conta"}],
    "gerado_em": "2026-09-15 10:00:00",
}
GESTAO = {
    "/api/gestao/usuarios": {"usuarios": [
        {**_USR, "id": 3, "nome": "Chefe Souza", "email": "chefe@exemplo.test",
         "perfil_id": 1, "perfil": "Administrador", "perfil_admin": 1}]},
    "/api/gestao/perfis": {"perfis": [
        {"id": 1, "nome": "Administrador", "descricao": "", "admin": 1,
         "telas": ["fluxo"], "usuarios": 1}]},
    "/api/gestao/telas": {"telas": TELAS[:4]},
    "/api/gestao/config": {},
    "/api/gestao/acessos/catalogo": {"abas": [], "sem_menu": []},
    "/api/gestao/permissoes": PERMISSOES,
}


def _abrir(pg, base):
    pedidos: list[str] = []

    def rota(route):
        u = route.request.url
        caminho = "/" + u.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        pedidos.append(caminho)
        corpo = ADMIN if caminho == "/api/auth/me" else GESTAO.get(caminho, {})
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base}/static/index.html#gestao")
    pg.wait_for_selector("#ges-usr tr", timeout=20000)
    pg.click("#gtab-permissoes")
    pg.wait_for_selector("#ges-perm tr[data-id]", timeout=10000)
    return pedidos, erros


def _linhas(pg):
    return pg.eval_on_selector_all(
        "#ges-perm tr[data-id]", "els => els.map(e => ({id: e.dataset.id, texto: e.innerText,"
        " classe: e.className}))")


def test_a_aba_abre_so_quando_pedida_e_mostra_os_ativos(pagina):
    pg, base = pagina
    pedidos, erros = _abrir(pg, base)
    assert pedidos.count("/api/gestao/permissoes") == 1
    ids = [l["id"] for l in _linhas(pg)]
    assert ids == ["3", "7"], "o inativo não entra no padrão (só ativos): %r" % ids
    assert not erros, erros


def test_a_excecao_da_pessoa_se_destaca_e_o_que_foi_tirado_esta_escrito(pagina):
    pg, base = pagina
    _abrir(pg, base)
    beto = pg.inner_text('#ges-perm tr[data-id="7"]')
    assert "Fluxo de Caixa" in beto and "Copiloto" in beto
    assert "+ liberadas: Copiloto" in beto
    assert "− telas tiradas: DRE Gerencial" in beto
    lib = pg.eval_on_selector_all('#ges-perm tr[data-id="7"] .ges-perm-t.lib',
                                  "els => els.map(e => e.textContent)")
    assert lib == ["Copiloto"], lib
    # a regra de CSS VALE: a liberada tem cor diferente da que vem do perfil
    cores = pg.evaluate("""() => {
        const r = document.querySelector('#ges-perm tr[data-id="7"]');
        const lib = r.querySelector('.ges-perm-t.lib'), per = r.querySelector('.ges-perm-t:not(.lib)');
        return [getComputedStyle(lib).color, getComputedStyle(per).color]; }""")
    assert cores[0] != cores[1], cores
    chefe = pg.inner_text('#ges-perm tr[data-id="3"]')
    assert "acesso total" in chefe and "ignorado(s) enquanto for administrador" in chefe


def test_inativos_aparecem_quando_pedidos_com_a_aba_tirada(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.select_option("#ges-perm-status", "todos")
    ls = _linhas(pg)
    assert [l["id"] for l in ls] == ["3", "7", "9"]
    caio = next(l for l in ls if l["id"] == "9")
    assert "ges-perm-inativo" in caio["classe"]
    assert "− abas tiradas: DRE Gerencial › Conta a conta" in caio["texto"]


def test_buscar_uma_tela_responde_quem_a_abre(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.fill("#ges-perm-busca", "folha de pag")
    assert [l["id"] for l in _linhas(pg)] == ["3"], "só o administrador abre a Folha"
    assert "quem abre: Folha de Pagamento" in pg.inner_text("#ges-perm-hint")
    pg.fill("#ges-perm-busca", "copiloto")
    assert {l["id"] for l in _linhas(pg)} == {"3", "7"}
    assert pg.eval_on_selector_all("#ges-perm .ges-perm-t.hit", "els => els.map(e => e.textContent)") == ["Copiloto"]
    pg.fill("#ges-perm-busca", "BETO")
    assert [l["id"] for l in _linhas(pg)] == ["7"], "acento e caixa não atrapalham a busca por nome"


def _baixar(pg, botao):
    with pg.expect_download() as dl:
        pg.click(botao)
    caminho = dl.value.path()
    return dl.value.suggested_filename, open(caminho, "rb").read().decode("utf-8")


def test_exportar_lista_leva_o_que_esta_filtrado_e_abre_no_excel(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.fill("#ges-perm-busca", "beto")
    nome, txt = _baixar(pg, "text=Exportar lista (CSV)")
    assert nome.startswith("permissoes-") and nome.endswith(".csv")
    assert txt.startswith("﻿"), "sem BOM o Excel pt-BR quebra os acentos"
    linhas = txt.lstrip("﻿").split("\r\n")
    assert linhas[0] == ("Usuário;E-mail;Perfil;Administrador;Situação;Grupo;Tela;Chave;"
                         "Acessa;Origem;Abas tiradas")
    assert all(l.startswith("Beto Lima;") for l in linhas[1:]), "exportou gente fora do filtro"
    assert ("Beto Lima;beto@exemplo.test;Operação;não;ativo;Início;Copiloto;cop;sim;"
            "Liberada na ficha da pessoa;") in linhas
    assert ("Beto Lima;beto@exemplo.test;Operação;não;ativo;Controladoria;DRE Gerencial;dre;"
            "não;Tirada na ficha da pessoa;") in linhas
    assert len(linhas) == 1 + 5 + 1, "5 telas que abre (2 + 3 de todo logado) e 1 tirada"


def test_exportar_matriz_uma_coluna_por_tela(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.select_option("#ges-perm-status", "todos")
    nome, txt = _baixar(pg, "text=Exportar matriz (CSV)")
    assert nome.startswith("permissoes-matriz-")
    linhas = txt.lstrip("﻿").split("\r\n")
    cab = linhas[0].split(";")
    assert cab[:5] == ["Usuário", "E-mail", "Perfil", "Administrador", "Situação"]
    assert len(cab) == 5 + len(TELAS)
    col = cab.index("Controladoria · DRE Gerencial")
    por_nome = {l.split(";")[0]: l.split(";") for l in linhas[1:]}
    assert set(por_nome) == {"Chefe Souza", "Beto Lima", "Caio Antigo"}
    assert por_nome["Beto Lima"][col] == "tirada"
    assert por_nome["Caio Antigo"][col] == "perfil"
    assert por_nome["Chefe Souza"][col] == "admin"
    assert por_nome["Beto Lima"][cab.index("Início · Copiloto")] == "liberada"
