# -*- coding: utf-8 -*-
"""A aba "Onde atacar": alavancas medidas.

Quase todos os guards aqui nasceram de um número ABSURDO que eu construí e
quase mandei para a tela. Número absurdo passa despercebido num painel; num
comitê de diretoria, não — e a primeira vez que passar, a tela inteira perde a
confiança de quem lê.
"""
from __future__ import annotations

import pytest

from api import dre_alavancas as al


def _dre(linhas: dict, meses: list[str], detalhe: dict | None = None):
    """Um payload de DRE no formato que `calcular` consome."""
    fora = []
    for rot, vals in linhas.items():
        fora.append({"rotulo": rot, "nivel": 0, "tipo": "linha",
                     "meses": dict(zip(meses, vals)),
                     "detalhe": [{"agrupador": a, "meses": dict(zip(meses, v))}
                                 for a, v in (detalhe or {}).items()]
                     if rot == "CSP" else []})
    return {"meses": meses, "linhas": fora}


MESES = ["2026-0%d" % i for i in range(1, 9)]


@pytest.fixture
def cena(monkeypatch):
    linhas = {
        "RECEITA LIQUIDA": [8000000.0] * 4 + [9500000.0] * 4,
        "RESULTADO DO EXERCICIO": [-500000.0] * 8,
        "RESULTADO FINANCEIRO": [-600000.0] * 4 + [-800000.0] * 4,
        "RECEITA BRUTA": [10000000.0] * 4 + [11800000.0] * 4,
        "CSP": [-8000000.0] * 8,
    }
    monkeypatch.setattr(al.queries, "get_dre",
                        lambda de, ate: _dre(linhas, MESES))
    monkeypatch.setattr(al.queries, "get_make_vs_buy", lambda de, ate: {
        "resumo": {"km_proprio_medido": 1_831_228.0,
                   "ckm_cheio": 24.52, "ckm_marginal": 12.94,
                   "rs_km_agregado": 6.66,
                   "componentes_km": {"combustivel": 3.63, "manutencao": 2.35,
                                      "pneus": 0.86, "outros_var": 1.36,
                                      "motoristas": 4.74, "fixo": 10.77,
                                      "depreciacao": 0.81}}})
    monkeypatch.setattr(al.queries, "get_analise_km",
                        lambda f, de, ate: {"kpis": {"retorno_vazio": 0.178}})
    monkeypatch.setattr(al.db, "query", lambda *a, **k: [{"n": 81}])
    return al.calcular("2026-01", "2026-08")


def _alav(d, chave):
    return next((a for a in d["alavancas"] if a["chave"] == chave), None)


# ------------------------------------------------------- a aritmética

def test_variavel_e_SO_o_que_varia_com_o_km(cena):
    """A primeira versão somava TODOS os componentes do CKM — inclusive
    motoristas, fixo e depreciação — e chamava o resultado de "variável". Dava
    R$ 24,52/km, que é o custo CHEIO, e a alavanca aparecia valendo R$ 4
    MILHÕES por mês. O certo é 3,63+2,35+0,86+1,36 = R$ 8,20/km."""
    a = _alav(cena, "make_vs_buy")
    assert "R$ 8,20/km" in a["o_que_e"], a["o_que_e"]
    assert "24,52" not in a["o_que_e"]
    # (8,20 − 6,66) × 228.903 km/mês ≈ R$ 352 mil, não 4 milhões
    assert 300_000 < a["valor_mes"] < 400_000, a["valor_mes"]


def test_ociosidade_NAO_multiplica_por_km_que_nao_existem(cena):
    """A primeira versão fazia `fixo_por_km × km_que_faltam` e chegava a
    R$ 4,85 milhões/mês. Aquele dinheiro não existe para ser economizado: o
    número honesto é o custo fixo que a frota JÁ carrega hoje."""
    a = _alav(cena, "ociosidade")
    # (24,52 − 12,94) × 228.903 ≈ R$ 2,65 mi — o fixo que os 81 cavalos custam
    assert 2_500_000 < a["valor_mes"] < 2_800_000, a["valor_mes"]


def test_imposto_nao_entra_como_alavanca(monkeypatch):
    """Imposto cresce COM a receita. Deixá-lo na lista mandaria atacar o
    efeito de estar vendendo mais."""
    linhas = {"RECEITA LIQUIDA": [8000000.0] * 4 + [9500000.0] * 4,
              "RESULTADO DO EXERCICIO": [-500000.0] * 8,
              "RECEITA BRUTA": [10000000.0] * 8,
              "CSP": [-8000000.0] * 8}
    # OS IMPOSTOS CRESCEM MAIS QUE A RECEITA de propósito. Na primeira versão
    # deste teste eles cresciam na mesma proporção — e aí quem os excluía era
    # a regra do EXCESSO, não a do nome. O sabote que desligava o filtro de
    # nome passava verde. Aqui só a regra do nome pode salvar.
    #   receita: 32,0 mi -> 38,0 mi (+18,75%)
    #   impostos: 3,2 mi -> 4,4 mi (+37,5%) — excesso claro
    det = {"IMPOSTOS FEDERAIS": [-800000.0] * 4 + [-1100000.0] * 4,
           "CONTRIBUICAO PREVIDENCIARIA": [-300000.0] * 4 + [-450000.0] * 4}
    monkeypatch.setattr(al.queries, "get_dre", lambda de, ate: _dre(linhas, MESES, det))
    monkeypatch.setattr(al.queries, "get_make_vs_buy",
                        lambda de, ate: {"resumo": {}})
    monkeypatch.setattr(al.queries, "get_analise_km",
                        lambda f, de, ate: {"kpis": {}})
    monkeypatch.setattr(al.db, "query", lambda *a, **k: [{"n": 0}])
    d = al.calcular("2026-01", "2026-08")
    assert not [a for a in d["alavancas"] if "IMPOSTO" in a["titulo"].upper()]
    assert not [a for a in d["alavancas"] if "CONTRIBUIC" in a["titulo"].upper()]


def test_custo_que_cresce_COM_a_receita_nao_e_alavanca(monkeypatch):
    """Só entra o EXCESSO sobre o crescimento da receita. Um custo que subiu
    exatamente na proporção da receita não é problema — é volume."""
    linhas = {"RECEITA LIQUIDA": [8000000.0] * 4 + [9600000.0] * 4,  # +20%
              "RESULTADO DO EXERCICIO": [-500000.0] * 8,
              "RECEITA BRUTA": [10000000.0] * 8, "CSP": [-8000000.0] * 8}
    # o frete subiu os MESMOS 20%: não é alavanca
    det = {"CV - FRETE AGREGADOS": [-1000000.0] * 4 + [-1200000.0] * 4}
    monkeypatch.setattr(al.queries, "get_dre", lambda de, ate: _dre(linhas, MESES, det))
    monkeypatch.setattr(al.queries, "get_make_vs_buy", lambda de, ate: {"resumo": {}})
    monkeypatch.setattr(al.queries, "get_analise_km", lambda f, de, ate: {"kpis": {}})
    monkeypatch.setattr(al.db, "query", lambda *a, **k: [{"n": 0}])
    assert not [a for a in al.calcular("2026-01", "2026-08")["alavancas"]
                if "FRETE" in a["titulo"]]


# --------------------------------------------------------- a honestidade

def test_o_que_precisa_de_confirmacao_vem_MARCADO(cena):
    """A comparação próprio × agregado depende de saber se o R$/km do agregado
    inclui o combustível adiantado. Apresentar isso como certo seria o jeito
    mais rápido de queimar a confiança na tela inteira."""
    a = _alav(cena, "make_vs_buy")
    assert a["certeza"] == "confirmar"
    assert "combustível" in a["o_que_fazer"]
    # e o resto NÃO é marcado à toa
    assert _alav(cena, "financeiro")["certeza"] == "medido"


def test_toda_alavanca_diz_a_FONTE(cena):
    """Número sem origem rastreável não entra em decisão — regra da casa."""
    for a in cena["alavancas"]:
        assert a["fonte"], a["titulo"]
        assert a["valor_mes"] is not None


def test_a_ordem_e_por_dinheiro(cena):
    vals = [a["valor_mes"] for a in cena["alavancas"]]
    assert vals == sorted(vals, reverse=True)


def test_o_que_ja_esta_bom_aparece_como_NAO_E_AQUI(cena):
    """Lista de problemas que inclui não-problemas dilui a atenção — e quem
    não vê o "não é aqui" gasta energia no lugar errado."""
    titulos = {x["titulo"] for x in cena["nao_e"]}
    assert "Retorno vazio" in titulos
    assert "Receita" in titulos
    # e o retorno vazio NÃO aparece como alavanca
    assert not [a for a in cena["alavancas"] if "vazio" in a["titulo"].lower()]


def test_o_retorno_vazio_ACIMA_do_limite_sai_do_nao_e_aqui(monkeypatch, cena):
    """O texto do "não é aqui" tem um `%` literal que já quebrou uma vez: o
    bloco inteiro caía no except e o retorno vazio simplesmente não aparecia,
    sem erro na tela."""
    monkeypatch.setattr(al.queries, "get_analise_km",
                        lambda f, de, ate: {"kpis": {"retorno_vazio": 0.31}})
    d = al.calcular("2026-01", "2026-08")
    assert "Retorno vazio" not in {x["titulo"] for x in d["nao_e"]}


def test_a_distancia_ate_o_zero_e_a_media_do_periodo(cena):
    assert cena["falta_por_mes"] == pytest.approx(500000.0)


def test_resultado_positivo_nao_inventa_distancia(monkeypatch):
    linhas = {"RECEITA LIQUIDA": [8000000.0] * 8,
              "RESULTADO DO EXERCICIO": [300000.0] * 8,
              "RECEITA BRUTA": [10000000.0] * 8, "CSP": [-7000000.0] * 8}
    monkeypatch.setattr(al.queries, "get_dre", lambda de, ate: _dre(linhas, MESES))
    monkeypatch.setattr(al.queries, "get_make_vs_buy", lambda de, ate: {"resumo": {}})
    monkeypatch.setattr(al.queries, "get_analise_km", lambda f, de, ate: {"kpis": {}})
    monkeypatch.setattr(al.db, "query", lambda *a, **k: [{"n": 0}])
    assert al.calcular("2026-01", "2026-08")["falta_por_mes"] == 0.0


# ------------------------------------------------------------- a tela

def test_a_tela_declara_que_em_jogo_nao_e_economia():
    """Somar os cartões e prometer o total seria vender o que não existe. A
    tela precisa dizer isso ANTES dos números, não num rodapé."""
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert "loadDreAtk" in html
    assert "não é “economia garantida”" in html
    assert 'id="dre-atk-naoe-card"' in html
    # a lista rola DENTRO do bloco: com dado real são 1.559px e a régua é 900
    assert 'id="dre-atk-lista" class="tabroll"' in html


def test_a_rota_esta_no_rbac():
    from api import auth

    assert dict(auth.ROTA_TELAS)["/api/dre/alavancas"] == frozenset(
        {"dre", "dreexc"})


# ============================================================ o panorama
#
# O panorama conta a conta é a parte cirúrgica da aba: o que atacar, o que
# manter e o que nem olhar ainda. O erro que ele quase cometeu — e que estes
# guards existem para impedir que volte — foi medir TUDO com a mesma régua.


def _dre_contas(receita: list[float], contas: list[dict], meses=None):
    """DRE com detalhe até a conta, no formato que `panorama` consome."""
    meses = meses or MESES
    return {
        "meses": meses,
        "linhas": [
            {"rotulo": "RECEITA LIQUIDA", "nivel": 0,
             "meses": dict(zip(meses, receita)), "detalhe": []},
            {"rotulo": "CSP", "nivel": 0,
             "meses": dict(zip(meses, [0.0] * len(meses))),
             "detalhe": [{"agrupador": c.get("agrupador", "CV - X"),
                          "meses": dict(zip(meses, c["vals"])),
                          "contas": [{"grupo": c.get("grupo", "1"),
                                      "reduzido": c["reduzido"],
                                      "conta": c["conta"],
                                      "estrutural": c["estrutural"],
                                      "meses": dict(zip(meses, c["vals"]))}]}
                         for c in contas]},
        ],
    }


def _pano(monkeypatch, receita, contas, meses=None):
    monkeypatch.setattr(al.queries, "get_dre",
                        lambda de, ate: _dre_contas(receita, contas, meses))
    return al.panorama("2026-01", "2026-08")


def _achar(d, nome):
    for lista in ("piorou", "melhorou", "oscila"):
        for x in d[lista]:
            if x["nome"] == nome:
                return lista, x
    return None, None


def test_receita_NAO_se_mede_como_percentual_da_receita(monkeypatch):
    """A régua circular dizia que a receita de agregados "melhorou R$ 432 mil".

    O que tinha mudado era o MIX: agregados foram de 81% para 85% do total
    porque a frota própria encolheu. Medida contra si mesma, em reais, esta
    conta CAIU — e é isso que quem decide precisa ver.
    """
    receita = [8_000_000.0] * 7 + [6_000_000.0]
    # a conta cai em reais, mas SOBE como fatia da receita
    conta = {"reduzido": "301", "conta": "RECEITA AGREGADOS",
             "estrutural": "3.1.1.01", "vals": [4_000_000.0] * 7 + [3_500_000.0]}
    d = _pano(monkeypatch, receita, [conta])
    lista, x = _achar(d, "RECEITA AGREGADOS")
    assert lista == "piorou", "receita que caiu R$ 500 mil não pode ser melhora"
    assert x["receita"] is True
    assert x["pct_ultimo"] is None, "receita não carrega régua de percentual"
    assert round(x["delta_rs"]) == -500_000


def test_custo_que_cresce_JUNTO_com_a_receita_nao_move_o_panorama(monkeypatch):
    """Dobrar o diesel porque dobrou o frete não é piora — é volume."""
    receita = [4_000_000.0] * 7 + [8_000_000.0]
    conta = {"reduzido": "401", "conta": "DIESEL", "estrutural": "4.1.1.01",
             "vals": [-1_000_000.0] * 7 + [-2_000_000.0]}
    d = _pano(monkeypatch, receita, [conta])
    lista, _ = _achar(d, "DIESEL")
    assert lista is None, "custo proporcional à receita apareceu como %s" % lista


def test_custo_que_piora_por_real_faturado_aparece(monkeypatch):
    receita = [4_000_000.0] * 8
    conta = {"reduzido": "401", "conta": "DIESEL", "estrutural": "4.1.1.01",
             "vals": [-1_000_000.0] * 7 + [-1_400_000.0]}
    d = _pano(monkeypatch, receita, [conta])
    lista, x = _achar(d, "DIESEL")
    assert lista == "piorou"
    # 25% -> 35% da receita, sobre R$ 4 mi do último mês = R$ 400 mil
    assert round(x["delta_rs"]) == -400_000
    assert round(x["pct_medio"], 4) == -0.25 and round(x["pct_ultimo"], 2) == -0.35


def test_conta_que_SO_OSCILA_sai_das_duas_listas(monkeypatch):
    """Provisão que entra e sai não é alvo: atacá-la é perseguir ruído."""
    receita = [4_000_000.0] * 8
    conta = {"reduzido": "409", "conta": "SINISTROS", "estrutural": "4.1.9.01",
             "vals": [0.0, -400_000.0, 0.0, -350_000.0,
                      0.0, -420_000.0, 0.0, -500_000.0]}
    d = _pano(monkeypatch, receita, [conta])
    lista, x = _achar(d, "SINISTROS")
    assert lista == "oscila", "conta instável entrou em %s" % lista
    assert x["cv"] > al.CV_INSTAVEL


def test_piso_de_materialidade_corta_o_percentual_gigante(monkeypatch):
    """Conta de R$ 900 que triplica é +200%, e não é decisão de ninguém."""
    receita = [4_000_000.0] * 8
    conta = {"reduzido": "499", "conta": "CAFEZINHO", "estrutural": "4.1.9.99",
             "vals": [-300.0] * 7 + [-900.0]}
    d = _pano(monkeypatch, receita, [conta])
    assert _achar(d, "CAFEZINHO") == (None, None)


def test_mes_sem_receita_sai_da_regua_em_vez_de_envenenar_a_media(monkeypatch):
    """Um mês com receita zero — competência que não fechou, empresa que não
    faturou — dividido, vira um percentual de milhões por cento. Ele não fica
    visível: some dentro da MÉDIA e devolve uma "melhora" de bilhões numa
    conta que não mudou um centavo. O mês sem denominador sai da régua.
    """
    receita = [4_000_000.0] * 3 + [0.0] + [4_000_000.0] * 4
    conta = {"reduzido": "401", "conta": "DIESEL", "estrutural": "4.1.1.01",
             "vals": [-1_000_000.0] * 8}
    d = _pano(monkeypatch, receita, [conta])
    lista, x = _achar(d, "DIESEL")
    assert lista is None, "conta que não mudou apareceu em %s" % lista
    for nome in ("piorou", "melhorou", "oscila"):
        for y in d[nome]:
            assert abs(y["delta_rs"]) < 1e12, "número absurdo na tela: %r" % y


def test_um_mes_so_nao_tem_o_que_comparar(monkeypatch):
    d = _pano(monkeypatch, [4_000_000.0], [
        {"reduzido": "401", "conta": "DIESEL", "estrutural": "4.1.1.01",
         "vals": [-1_000_000.0]}], meses=["2026-08"])
    assert d["erro"] and not d["piorou"] and not d["melhorou"]


def test_sem_receita_liquida_o_panorama_RECUSA(monkeypatch):
    """Sem denominador não há régua — e devolver lista vazia calada faria a
    tela dizer "está tudo bem" no dia em que ela parou de enxergar."""
    d = _pano(monkeypatch, [0.0] * 8, [
        {"reduzido": "401", "conta": "DIESEL", "estrutural": "4.1.1.01",
         "vals": [-1_000_000.0] * 8}])
    assert d["erro"]


def test_a_ordem_e_por_dinheiro_dos_dois_lados(monkeypatch):
    receita = [4_000_000.0] * 8
    contas = [
        {"reduzido": "401", "conta": "GRANDE", "estrutural": "4.1.1.01",
         "vals": [-1_000_000.0] * 7 + [-1_400_000.0]},
        {"reduzido": "402", "conta": "PEQUENA", "estrutural": "4.1.1.02",
         "vals": [-100_000.0] * 7 + [-150_000.0]},
    ]
    d = _pano(monkeypatch, receita, contas)
    assert [x["nome"] for x in d["piorou"]] == ["GRANDE", "PEQUENA"]


def test_a_tela_mostra_o_panorama_e_declara_as_DUAS_reguas():
    """Régua escondida vira verdade do sistema: quem lê precisa saber que
    custo e receita não foram medidos do mesmo jeito."""
    html = al.__file__  # só para o linter não reclamar do import
    del html
    import pathlib
    s = pathlib.Path("api/static/index.html").read_text(encoding="utf-8")
    assert 'id="dre-atk-pano"' in s, "o painel não tem onde renderizar"
    assert 'data-ao-abrir="loadDrePano"' in s, "a aba não chama o panorama"
    assert "/api/dre/panorama" in s
    bloco = s[s.index("async function loadDrePano"):]
    bloco = bloco[:bloco.index("async function loadDreAtk")]
    for pedaco in ("% da receita", "Piorou", "Melhorou", "Oscila"):
        assert pedaco in bloco, "a tela não diz %r" % pedaco


def test_deducao_de_receita_usa_a_regua_de_CUSTO(monkeypatch):
    """"(-) ICMS SOBRE RECEITA DE TRANSPORTE" também é estrutural 3.

    Medido em reais contra a própria média, ele aparecia como a quarta maior
    PIORA do mês (-R$ 75.390) por ter recolhido mais imposto sobre um
    faturamento maior — exatamente o efeito que a régua de percentual existe
    para separar. O que decide alguma coisa é quanto da receita a dedução
    leva, e por isso ela se mede como custo.
    """
    receita = [4_000_000.0] * 7 + [8_000_000.0]
    conta = {"reduzido": "302", "conta": "(-) ICMS SOBRE RECEITA",
             "estrutural": "3.1.1.09", "vals": [-400_000.0] * 7 + [-800_000.0]}
    d = _pano(monkeypatch, receita, [conta])
    lista, x = _achar(d, "(-) ICMS SOBRE RECEITA")
    assert lista is None, "imposto proporcional à receita apareceu em %s" % lista
