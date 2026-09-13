# -*- coding: utf-8 -*-
"""As cinco telas do WMS contra o index.html REAL, com a API dublada.

O que se cobra:
1. cada tela abre, desenha o que o servidor mandou e não derruba o script
   (erro de console reprova — tela nova mal registrada morre calada);
2. a CONFERÊNCIA É CEGA também na tela: o modal de conferência não mostra a
   quantidade da nota, e fechar manda conferir → fechar, nessa ordem;
3. sem armazém cadastrado a tela diz ONDE começar;
4. com payload CHEIO — e no teto, não no dia de hoje — nenhuma aba passa da
   régua de uma tela: a régua com dublê vazio mede só o esqueleto.

O dublê de tamanho sai do teto do que o servidor ENTREGA (a lista de saldo
corta em 800, o kardex em 400, a doca em 500), não de um número redondo.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ARM = {"id": 1, "codigo": "JVE1", "nome": "Armazém Joinville",
       "docas": [{"id": 9, "codigo": "DOCA1"}], "expedicao": [{"id": 10, "codigo": "EXP1"}],
       "avaria": [{"id": 11, "codigo": "AVARIA"}]}
DEP = {"cnpj": "84693183000168", "razao_social": "SCHULZ S/A", "nome_fantasia": "SCHULZ - JOINVILLE/SC"}
CATALOGO = {"armazens": [ARM], "depositantes": [DEP],
            "tipos": [{"chave": "porta_palete", "rotulo": "Porta-palete"}, {"chave": "doca", "rotulo": "Doca"}],
            "tipos_guarda": ["porta_palete", "picking", "blocado"],
            "motivos_bloqueio": ["avaria", "quarentena"]}


def _saldo(n):
    return [{"produto_id": i, "endereco_id": 100 + i, "lote": f"L{i}", "validade": "2026-10-01",
             "qtd": 10.0, "reservado": 2.0 if i % 3 == 0 else 0.0, "disponivel": 8.0,
             "endereco": f"A-{i:02d}-01-01", "endereco_tipo": "porta_palete", "bloqueado": i == 1,
             "motivo_bloqueio": "quarentena" if i == 1 else "", "produto": f"961.{i:04d}-0",
             "descricao": "RACK METALICO ZF-BRASIL - AA01298655", "unidade": "PC",
             "depositante_cnpj": DEP["cnpj"], "depositante": DEP["razao_social"],
             "nome_fantasia": DEP["nome_fantasia"], "dias_validade": 19, "idade_h": 30.0,
             "primeira_entrada": "2026-09-11T08:00:00-03:00",
             "sugestao": {"id": 7, "codigo": "B-01-01-01", "motivo": "endereço vazio"}}
            for i in range(1, n + 1)]


def _painel():
    return {"armazem_id": 1,
            "kpis": {"ocupacao_pct": 62.5, "enderecos_ocupados": 50, "enderecos_guarda": 80,
                     "doca_posicoes": 3, "doca_24h": 1, "doca_idade_max_h": 30.5,
                     "ped_em_separacao": 2, "tarefas_pendentes": 7, "ped_a_liberar": 1,
                     "ped_expedidos_hoje": 4, "ped_aguardando_expedicao": 1, "ped_atrasados": 1},
            "alertas": [{"nivel": "alerta", "n": 1, "texto": "pedido(s) atrasado(s)", "tela": "wmsexp"},
                        {"nivel": "atencao", "n": 5, "texto": "validade em 30 dias", "tela": "wmsest"}],
            "serie": [{"dia": f"2026-08-{d:02d}", "recebimentos": d % 4, "expedicoes": d % 3}
                      for d in range(14, 32)] + [{"dia": f"2026-09-{d:02d}", "recebimentos": 1, "expedicoes": 2}
                                                 for d in range(1, 13)],
            "ruas": [{"rua": r, "ativos": 40, "ocupados": 25, "bloqueados": 1} for r in "ABCDEFGH"],
            "depositantes": [{**DEP, "cnpj": f"{i:014d}", "posicoes": 30 - i, "produtos": 4, "enderecos": 20 - i}
                             for i in range(8)],
            "depositantes_total": 23}


REC_ABERTO = {"id": 1, "status": "aberto", "origem": "erp", "nf_numero": 374282, "nf_serie": "1",
              "doca": "DOCA1", "depositante_cnpj": DEP["cnpj"], "razao_social": DEP["razao_social"],
              "nome_fantasia": DEP["nome_fantasia"], "itens": 3, "conferidos": 1, "aberto_ha_h": 2.5,
              "qtd_nf": None, "itens_divergentes": None}
REC_FIM = {**REC_ABERTO, "id": 2, "status": "conferido", "qtd_nf": 17.0, "qtd_conferida": 16.0,
           "qtd_avaria": 0.0, "itens_divergentes": 1, "conferido_em": "2026-09-12T09:00:00-03:00"}
DETALHE_ABERTO = {**REC_ABERTO, "cego": True, "doca": "DOCA1",
                  "itens": [{"id": 11, "seq": 1, "produto_id": 1, "qtd_nf": None, "qtd_conferida": None,
                             "qtd_avaria": 0.0, "lote": "", "validade": None, "codigo": "961.0301-0",
                             "descricao": "RACK METALICO", "unidade": "PC", "controla_lote": False,
                             "controla_validade": False}],
                  "resumo": {"itens": 1, "conferidos": 0}}
DETALHE_FECHADO = {**DETALHE_ABERTO, "status": "conferido", "cego": False,
                   "itens": [{**DETALHE_ABERTO["itens"][0], "qtd_nf": 6.0, "qtd_conferida": 5.0,
                              "divergencia": -1.0}],
                   "resumo": {"itens": 1, "conferidos": 1, "divergentes": 1, "falta": 1.0, "sobra": 0.0,
                              "avaria": 0.0}}


def _pedidos(n):
    sits = ["aberto", "em_separacao", "separado"]
    return [{"id": i, "status": "liberado" if i % 3 else "aberto", "situacao": sits[i % 3],
             "origem": "manual", "numero": f"PV-{i}", "destinatario": "METALSIDER LTDA",
             "previsto_para": "2026-09-13", "atrasado": i == 2, "itens": 3, "tarefas_pendentes": i % 2,
             "tarefas_separadas": 1, "depositante_cnpj": DEP["cnpj"], "razao_social": DEP["razao_social"],
             "nome_fantasia": DEP["nome_fantasia"], "corte": 0} for i in range(1, n + 1)] + [
        {"id": 900, "status": "expedido", "situacao": "expedido", "numero": "PV-900", "placa": "ABC1D23",
         "motorista": "", "expedido_em": "2026-09-12T10:00:00-03:00", "corte": 1.0, "itens": 1,
         "depositante_cnpj": DEP["cnpj"], "razao_social": DEP["razao_social"], "nome_fantasia": ""}]


def _corpo(url, metodo, cheio, sem_armazem, posts, post_data):
    if "/api/auth/me" in url:
        return {**USUARIO, "admin": True}
    if metodo == "POST":
        # só os POSTs do WMS: o painel manda um batimento de sessão
        # (`/api/auth/atividade`) que não tem nada a ver com a conferência
        if "/api/wms/" in url:
            posts.append((url.split("/api/wms/")[-1], json.loads(post_data or "{}")))
        if url.endswith("/fechar"):
            return DETALHE_FECHADO
        return DETALHE_ABERTO
    if "/api/wms/catalogo" in url:
        return {**CATALOGO, "armazens": []} if sem_armazem else CATALOGO
    if "/api/wms/painel" in url:
        return _painel()
    if "/api/wms/recebimento/doca" in url:
        linhas = _saldo(500 if cheio else 2)
        return {"doca": linhas, "total": len(linhas), "idade_max_h": 30.0}
    if "/api/wms/recebimento/1" in url:
        return DETALHE_ABERTO
    if "/api/wms/recebimento" in url:
        abertos = [dict(REC_ABERTO, id=i) for i in range(1, (300 if cheio else 1) + 1)]
        return {"recebimentos": abertos + [REC_FIM],
                "resumo": {"a_conferir": len(abertos), "conferidos_hoje": 1, "abertos_24h": 0,
                           "divergentes_30d": 1, "conferidos_30d": 4}}
    if "/api/wms/estoque/saldo" in url:
        linhas = _saldo(800 if cheio else 3)
        return {"saldo": linhas, "total": len(linhas), "mostrando": len(linhas),
                "resumo": {"posicoes": len(linhas), "produtos": len(linhas), "enderecos": len(linhas),
                           "vencidos": 0, "vencendo_30d": 3, "em_bloqueado": 1, "reservadas": 1}}
    if "/api/wms/estoque/kardex" in url:
        movs = [{"id": i, "criado_em": "2026-09-12T08:00:00-03:00", "usuario": "ana@sulista",
                 "tipo": "entrada", "doc_tipo": "recebimento", "doc_id": 1, "qtd": 5.0, "lote": "",
                 "motivo": "", "endereco": "DOCA1", "produto": "961.0301-0", "descricao": "RACK"}
                for i in range(400 if cheio else 2)]
        return {"movimentos": movs, "total": 1200 if cheio else 2, "mostrando": len(movs), "dias": 30}
    if "/api/wms/estoque/bloqueios" in url:
        return {"enderecos": [{"id": 5, "codigo": "A-01-01-01", "tipo": "porta_palete", "motivo_bloqueio": "quarentena",
                               "bloqueado_em": "2026-09-12T08:00:00-03:00", "bloqueado_por": "ana", "itens": 1,
                               "inventario_id": None}], "total": 1}
    if "/api/wms/estoque/inventarios" in url:
        return {"inventarios": [{"id": 3, "descricao": "rua A", "status": "aberto", "enderecos": 40, "contados": 12,
                                 "acuracia": None, "criado_em": "2026-09-12T07:00:00-03:00"}]}
    if "/api/wms/expedicao/pedidos" in url:
        ped = _pedidos(300 if cheio else 3)
        return {"pedidos": ped, "resumo": {"a_liberar": 1, "em_separacao": 1, "aguardando_expedicao": 1,
                                           "expedidos_hoje": 1, "atrasados": 1}}
    if "/api/wms/expedicao/tarefas" in url:
        tar = [{"id": i, "pedido_id": 1, "qtd": 2.0, "lote": "L1", "validade": "2026-10-01",
                "endereco": f"A-{i:02d}-01-01", "bloqueado": False, "codigo": "961.0301-0",
                "descricao": "RACK", "unidade": "PC", "pedido_numero": "PV-1",
                "razao_social": DEP["razao_social"], "nome_fantasia": DEP["nome_fantasia"]}
               for i in range(1, (600 if cheio else 2) + 1)]
        return {"tarefas": tar, "total": len(tar), "pedidos": 1}
    if "/api/wms/cadastro/armazens" in url:
        return {"armazens": [{**ARM, "filial_erp": 19, "cidade": "JOINVILLE", "uf": "SC", "ativo": True,
                              "enderecos_guarda": 320, "docas": 2, "areas_expedicao": 1, "areas_avaria": 1}]}
    if "/api/wms/cadastro/depositantes" in url:
        return {"depositantes": [{**DEP, "cidade": "JOINVILLE", "uf": "SC", "origem": "erp", "ativo": True,
                                  "produtos": 12, "posicoes": 40}]}
    if "/api/wms/cadastro/enderecos" in url:
        ends = [{"id": i, "codigo": f"A-{i:02d}-01-01", "tipo": "porta_palete", "situacao": "livre", "itens": 0,
                 "capacidade_paletes": 1, "ativo": True} for i in range(1, (1500 if cheio else 3) + 1)]
        return {"enderecos": ends, "total": len(ends), "mostrando": len(ends),
                "resumo": {"porta_palete": {"ativos": len(ends)}, "doca": {"ativos": 2}, "expedicao": {"ativos": 1}},
                "tipos": CATALOGO["tipos"]}
    if "/api/wms/cadastro/produtos" in url or "/api/wms/produtos" in url:
        prods = [{"id": i, "codigo": f"961.{i:04d}-0", "descricao": "RACK", "unidade": "PC", "ativo": True,
                  "origem": "erp", "saldo": 10.0, "disponivel": 8.0, "controla_lote": False,
                  "controla_validade": False, "depositante_cnpj": DEP["cnpj"], "razao_social": DEP["razao_social"],
                  "nome_fantasia": DEP["nome_fantasia"], "ean": ""} for i in range(1, (500 if cheio else 3) + 1)]
        return {"produtos": prods, "total": len(prods), "mostrando": len(prods)}
    return {}


# O harness serve só `/static`; o service worker mora na RAIZ (`/sw.js`) e o
# registro dele dá 404 aqui — e só aqui. É o único erro de console tolerado, e
# nominalmente: filtro genérico ("404") esconderia um script da tela faltando.
SW_404 = "A bad HTTP response code (404) was received when fetching the script."


def _abrir(pagina, tela, cheio=False, sem_armazem=False):
    pg, base = pagina
    erros: list[str] = []
    posts: list[tuple[str, dict]] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text)
          if m.type == "error" and m.text != SW_404 else None)

    def rota(route):
        r = route.request
        corpo = _corpo(r.url, r.method, cheio, sem_armazem, posts, r.post_data)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#{tela}")
    pg.wait_for_function("() => window.USER !== null", timeout=20000)
    return pg, erros, posts


@pytest.mark.parametrize("tela,alvo,texto", [
    ("wmspan", "#wmspan-kpis", "Ocupação"),
    ("wmsrec", "#wmsrec-abertos", "NF 374282"),
    ("wmsest", "#wmsest-saldo", "A-01-01-01"),
    ("wmsexp", "#wmsexp-ped", "PV-1"),
    ("wmscad", "#wmscad-arm", "JVE1"),
])
def test_cada_tela_abre_e_desenha_sem_erro(pagina, tela, alvo, texto):
    pg, erros, _ = _abrir(pagina, tela)
    pg.wait_for_function(f"() => (document.querySelector('{alvo}')||{{}}).innerText?.includes('{texto}')",
                         timeout=15000)
    assert pg.evaluate("location.hash") == "#" + tela
    assert pg.is_visible(f"#view-{tela}")
    assert not [e for e in erros if "favicon" not in e], erros


def test_o_grupo_WMS_esta_no_menu_com_as_cinco_telas(pagina):
    pg, _, _ = _abrir(pagina, "wmspan")
    itens = pg.eval_on_selector_all("#subsWms a.sub", "els => els.map(e => e.dataset.view)")
    assert sorted(itens) == ["wmscad", "wmsest", "wmsexp", "wmspan", "wmsrec"]
    assert pg.get_attribute("#grpWms", "aria-expanded") == "true", "o acordeão não abriu no grupo da tela"


def test_a_conferencia_e_cega_na_tela_e_fechar_confere_antes(pagina):
    pg, erros, posts = _abrir(pagina, "wmsrec")
    pg.wait_for_selector("#wmsrec-abertos button", timeout=15000)
    pg.click("#wmsrec-abertos button")
    pg.wait_for_selector("#modalBox .wc-q", timeout=10000)
    assert "Conferência cega" in pg.inner_text("#modalBox")
    # `innerText` devolve o texto JÁ transformado pelo CSS (o `th` é caixa alta)
    colunas = [c.lower() for c in pg.eval_on_selector_all(
        "#modalBox thead th", "els => els.map(e => e.innerText.trim())")]
    assert "contado" in colunas and not any("nota" in c for c in colunas), colunas
    # nenhum campo da conferência chega preenchido com o número da nota
    assert pg.eval_on_selector_all("#modalBox .wc-q", "els => els.map(e => e.value)") == [""]
    pg.fill("#modalBox .wc-q", "5")
    pg.click("#modalBox button.btn")
    pg.wait_for_function("() => (document.getElementById('modalBox')||{}).innerText?.includes('divergente')",
                         timeout=10000)
    caminhos = [p[0] for p in posts]
    assert caminhos[:2] == ["recebimento/1/conferir", "recebimento/1/fechar"], caminhos
    assert posts[0][1]["itens"][0]["qtd_conferida"] == "5"
    assert not erros, erros


def test_sem_armazem_a_tela_diz_onde_comecar(pagina):
    pg, _, _ = _abrir(pagina, "wmsrec", sem_armazem=True)
    pg.wait_for_function("() => (document.getElementById('wmsrec-hint')||{}).innerText?.includes('Cadastros do Armazém')",
                         timeout=15000)
    assert pg.get_attribute("#wmsrec-hint a", "href") == "#wmscad"


@pytest.mark.parametrize("tela", ["wmspan", "wmsrec", "wmsest", "wmsexp", "wmscad"])
def test_payload_no_teto_nao_passa_da_regua(pagina, tela):
    """Mede CADA aba com o teto do que o servidor entrega. Cobra também que o
    dublê CHEGOU na tela — aba vazia cabe em qualquer régua."""
    pg, _, _ = _abrir(pagina, tela, cheio=True)
    pg.wait_for_function(f"() => document.querySelectorAll('#view-{tela} tbody tr').length > 5", timeout=20000)
    alt = ("() => { const c = document.getElementById('content'); return Math.round(c.scrollHeight); }")
    abas = pg.evaluate(f"() => Array.from(document.querySelectorAll('#view-{tela} .subtabs button'))"
                       ".map(b => b.dataset.aba)")
    alturas = {"(sem aba)": pg.evaluate(alt)}
    for a in abas:
        pg.evaluate(f"() => abaTrocar('{tela}', '{a}')")
        pg.wait_for_timeout(150)
        alturas[a] = pg.evaluate(alt)
        linhas = pg.evaluate(f"() => document.querySelectorAll('#aba-{tela}-{a} tbody tr').length")
        assert linhas > 0, f"a aba {a} ficou vazia — o dublê não chegou"
    assert max(alturas.values()) <= 900, alturas
    larg = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert larg <= 0, f"rolagem horizontal de {larg}px"
