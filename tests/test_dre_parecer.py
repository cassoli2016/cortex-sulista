# -*- coding: utf-8 -*-
"""A aba "Parecer": a causa do movimento, não o valor dele.

Todos os guards aqui nasceram de um defeito REAL, e três deles de defeitos que
fixture nenhuma teria achado — foi preciso rodar contra o razão de verdade:

  * o par espelhado agrupava TRÊS receitas irmãs por dividirem a conta
    3.1.1.01 e anunciava um "líquido" de R$ 1.004.805 que não significa nada;
  * "até onde o razão foi lançado" respondia dezembro, porque o ERP tem
    lançamento com data FUTURA (parcela programada);
  * a ressalva de provisão somava 13º e férias, que acumulam em vez de ciclar.

E o guard mais importante de todos é o da provisão: a análise que originou este
módulo somou o SALDO DO DIA de uma conta de custo como se fosse provisão, errou
R$ 12.328,13 e ainda desmentiu uma medição correta da casa por causa disso.
"""
from __future__ import annotations

import datetime

import pytest

from api import dre_parecer as pc


MESES = ["2026-0%d" % i for i in range(1, 9)]


# --------------------------------------------------------------------------
# recorrente x nao recorrente
# --------------------------------------------------------------------------
def _dre(contas: list[dict], resultado: list[float]):
    """Payload de DRE no formato que `recorrencia` consome.

    `contas` = [{"linha", "agrupador", "conta", "reduzido", "vals"}].
    """
    por_linha: dict = {}
    for c in contas:
        por_linha.setdefault(c["linha"], {}).setdefault(c["agrupador"], []) \
            .append(c)
    linhas = [{"rotulo": "RESULTADO DO EXERCICIO", "nivel": 0,
               "tipo": "formula", "meses": dict(zip(MESES, resultado)),
               "detalhe": []}]
    for rot, agr in por_linha.items():
        linhas.append({
            "rotulo": rot, "nivel": 1, "tipo": "pref",
            "meses": {}, "detalhe": [
                {"agrupador": a, "meses": {}, "contas": [
                    {"conta": c["conta"], "grupo": 1,
                     "reduzido": c["reduzido"], "estrutural": c.get("estr", ""),
                     "meses": dict(zip(MESES, c["vals"]))} for c in cs]}
                for a, cs in agr.items()]})
    return {"meses": MESES, "linhas": linhas}


def test_recorrente_tira_a_venda_de_ativo_e_publica_os_dois_numeros():
    """A linha não operacional inteira sai — e o publicado continua na resposta.

    Publicar só o recorrente esconderia o resultado que a contabilidade
    assina; publicar só o publicado é o erro de R$ 11,2 milhões da crônica.
    """
    venda = [400000.0] * 7 + [0.0]
    dre = _dre(
        [{"linha": "RESULTADO NAO OPERACIONAL", "agrupador": "RECEITA - VENDA",
          "conta": "RECEITA DE VENDA ATIVO IMOBILIZADO", "reduzido": 391101,
          "vals": venda}],
        resultado=[-500000.0] * 8)
    r = pc.recorrencia(dre)

    assert r["total_publicado"] == pytest.approx(-4000000.0)
    assert r["total_nao_recorrente"] == pytest.approx(2800000.0)
    assert r["total_recorrente"] == pytest.approx(-6800000.0)
    # o mês SEM venda mostra os dois iguais: é o mês em que a muleta sumiu
    assert r["publicado"]["2026-08"] == r["recorrente"]["2026-08"]
    assert r["media_recorrente"] == pytest.approx(-850000.0)


def test_recorrente_lista_o_que_tirou_com_motivo():
    """Heurística escondida vira verdade do sistema: ela tem de sair na resposta."""
    dre = _dre(
        [{"linha": "OUTRAS DESPESAS/RECEITAS OPERACIONAIS",
          "agrupador": "OUTRAS RECEITAS - X",
          "conta": "RECUPERACAO DE CUSTOS/DESPESAS", "reduzido": 425101,
          "vals": [0.0] * 4 + [145000.0] + [0.0] * 3}],
        resultado=[-100000.0] * 8)
    r = pc.recorrencia(dre)

    assert len(r["itens"]) == 1
    item = r["itens"][0]
    assert item["conta"] == "RECUPERACAO DE CUSTOS/DESPESAS"
    assert "Recuperacao De Custo" in item["motivo"]
    # o critério inteiro vai junto, para quem discorda poder discordar do QUÊ
    assert "RESULTADO NAO OPERACIONAL" in r["criterio"]
    assert "Venda De Sucata" in r["criterio"]


def test_conta_operacional_comum_nao_e_tirada():
    dre = _dre(
        [{"linha": "CUSTO VARIAVEL", "agrupador": "CV - COMBUSTIVEL",
          "conta": "DIESEL FROTA", "reduzido": 411101,
          "vals": [-1000000.0] * 8}],
        resultado=[-500000.0] * 8)
    r = pc.recorrencia(dre)
    assert r["itens"] == []
    assert r["total_recorrente"] == r["total_publicado"]


# --------------------------------------------------------------------------
# par espelhado — o guard que o dado real obrigou a existir
# --------------------------------------------------------------------------
def _item(nome, reduzido, estr, delta, valor):
    return {"nome": nome, "grupo": 1, "reduzido": reduzido, "estrutural": estr,
            "agrupador": "X", "linha": "Y", "delta_rs": delta,
            "valor_ultimo": valor}


def test_espelho_acha_as_duas_pontas_do_diesel():
    """Compra e recuperação na mesma conta do plano, com sinais opostos."""
    pan = {
        "piorou": [_item("DIESEL FROTA", 411101, "4.1.1.01.0001",
                         -484528.57, -2368825.0)],
        "melhorou": [_item("DIESEL AGREGADOS", 411108, "4.1.1.01.0008",
                           634079.38, 1868702.0)],
    }
    esp = pc.espelhos(pan)

    assert len(esp) == 1
    assert esp[0]["conta_do_plano"] == "4.1.1.01"
    assert esp[0]["liquido"] == pytest.approx(149550.81, abs=0.02)
    assert len(esp[0]["pontas"]) == 2


def test_espelho_NAO_agrupa_receitas_irmas():
    """O guard que o dado real obrigou a existir.

    Receita própria, municipal e de agregados dividem a conta 3.1.1.01 e caem
    em lados opostos do ranking — mas são três receitas diferentes, não duas
    pontas de um movimento. Sem o teste de SINAL DO SALDO, o módulo anunciava
    um "líquido" de R$ 1.004.805 que não quer dizer coisa nenhuma.
    """
    pan = {
        "piorou": [_item("RECEITA DE TRANSPORTE - FROTA PROPRIA", 311101,
                         "3.1.1.01.0001", -438563.98, 2091131.0)],
        "melhorou": [
            _item("RECEITA DE TRANSPORTE - AGREGADOS", 311102,
                  "3.1.1.01.0002", 1175371.03, 8299734.0),
            _item("RECEITA DE TRANSPORTE - MUNICIPAL", 311103,
                  "3.1.1.01.0003", 267998.06, 542167.0)],
    }
    assert pc.espelhos(pan) == []


def test_espelho_exige_lados_opostos_do_ranking():
    """Duas contas que pioraram juntas não são espelho, mesmo com sinais
    opostos de saldo: espelho é um movimento que se anula, não dois que somam."""
    pan = {
        "piorou": [
            _item("DIESEL FROTA", 411101, "4.1.1.01.0001", -100000.0, -900.0),
            _item("DIESEL AGREGADOS", 411108, "4.1.1.01.0008", -50000.0, 400.0)],
        "melhorou": [],
    }
    assert pc.espelhos(pan) == []


def test_conta_do_plano_corta_no_quarto_nivel():
    assert pc._conta_do_plano("4.1.1.01.0008") == "4.1.1.01"
    assert pc._conta_do_plano("4.1.1.01") == "4.1.1.01"
    assert pc._conta_do_plano("") == ""


# --------------------------------------------------------------------------
# a causa, pelo lancamento
# --------------------------------------------------------------------------
def _lanc(grupo, reduzido, seq, dia, hist, v, n, bruto, liquido, rn):
    return {"grupo": grupo, "reduzido": reduzido, "sequencia": seq,
            "dtlancamento": dia, "historicodescricao": hist, "v": v,
            "rn": rn, "n": n, "bruto": bruto, "liquido": liquido}


def _monkey_causas(monkeypatch, linhas):
    monkeypatch.setattr(pc.db, "query", lambda sql, params=None: linhas)
    monkeypatch.setattr(pc.dre_exclusoes, "chaves", lambda de, ate: [])
    monkeypatch.setattr(pc.dre_exclusoes, "filtro_sql", lambda a, n: "")
    monkeypatch.setattr(pc.dre_exclusoes, "filtro_params", lambda chs: {})


def test_causa_evento_unico_nao_e_tendencia(monkeypatch):
    """Um lançamento explicando 96% do mês é evento, e a tela precisa dizer
    isso: a decisão que um evento sustenta não é a que uma tendência sustenta."""
    dia = datetime.date(2026, 8, 12)
    _monkey_causas(monkeypatch, [
        _lanc(1, 411501, 900, dia, "REPARO GRANDE", -214800.0,
              n=40, bruto=223750.0, liquido=-223750.0, rn=1),
        _lanc(1, 411501, 901, dia, "OUTRO", -5000.0,
              n=40, bruto=223750.0, liquido=-223750.0, rn=2),
        _lanc(1, 411501, 902, dia, "OUTRO", -3950.0,
              n=40, bruto=223750.0, liquido=-223750.0, rn=3),
    ])
    c = pc.causas([(1, 411501)], "2026-08")["1|411501"]
    assert c["tipo"] == "evento único"
    assert "96%" in c["motivo"]
    assert c["lancamentos"] == 40


def test_causa_espalhada_e_a_operacao_inteira(monkeypatch):
    dia = datetime.date(2026, 8, 12)
    _monkey_causas(monkeypatch, [
        _lanc(1, 411801, i, dia, "FRETE", -20000.0,
              n=434, bruto=5729742.0, liquido=-5729742.0, rn=i)
        for i in (1, 2, 3)])
    c = pc.causas([(1, 411801)], "2026-08")["1|411801"]
    assert c["tipo"] == "espalhado"
    assert "434 lançamentos" in c["motivo"]


def test_causa_provisao_avisa_que_o_numero_e_estimativa(monkeypatch):
    """Provisão no ÚLTIMO DIA do mês vence a classificação por concentração:
    o que importa dizer sobre esse número é que parte dele ainda vai mudar."""
    _monkey_causas(monkeypatch, [
        _lanc(1, 411803, 11039540, datetime.date(2026, 8, 31),
              "VLR REF PROV PEDAGIO FAT 00000000000 - SEM PARAR", -255844.76,
              n=54, bruto=425712.0, liquido=-425712.0, rn=1),
        _lanc(1, 411803, 11035911, datetime.date(2026, 8, 31),
              "VLR REF VALE PEDAGIO VEICULO", -740.82,
              n=54, bruto=425712.0, liquido=-425712.0, rn=2),
        _lanc(1, 411803, 11036045, datetime.date(2026, 8, 30),
              "VLR REF VALE PEDAGIO VEICULO", -739.68,
              n=54, bruto=425712.0, liquido=-425712.0, rn=3),
    ])
    c = pc.causas([(1, 411803)], "2026-08")["1|411803"]
    assert c["tipo"] == "provisão"
    assert "estimativa" in c["motivo"]
    assert c["maiores"][0]["sequencia"] == 11039540


def test_provisao_so_vence_se_for_do_ultimo_dia(monkeypatch):
    """Lançamento com PROV no meio do mês não é a provisão de fechamento."""
    _monkey_causas(monkeypatch, [
        _lanc(1, 411803, 1, datetime.date(2026, 8, 15),
              "VLR REF PROV QUALQUER", -255844.76,
              n=3, bruto=257325.0, liquido=-257325.0, rn=1),
        _lanc(1, 411803, 2, datetime.date(2026, 8, 16), "X", -740.82,
              n=3, bruto=257325.0, liquido=-257325.0, rn=2),
        _lanc(1, 411803, 3, datetime.date(2026, 8, 17), "X", -739.68,
              n=3, bruto=257325.0, liquido=-257325.0, rn=3),
    ])
    c = pc.causas([(1, 411803)], "2026-08")["1|411803"]
    assert c["tipo"] == "evento único"


def test_causas_sem_alvo_nao_consulta_o_erp(monkeypatch):
    def _explode(*a, **k):
        raise AssertionError("não pode consultar o ERP sem alvo")
    monkeypatch.setattr(pc.db, "query", _explode)
    assert pc.causas([], "2026-08") == {}


# --------------------------------------------------------------------------
# provisao aberta — o guard central deste modulo
# --------------------------------------------------------------------------
def test_provisao_e_o_lancamento_nunca_o_saldo_do_dia(monkeypatch):
    """O erro que originou este módulo, virado guard.

    Na conta de custo, o dia 31/08 tinha a provisão de R$ 255.844,76 MAIS 53
    lançamentos diários de vale-pedágio. Somar o dia dava R$ 268.172,89 e
    inflava a ressalva em R$ 12.328,13. A provisão sai da CONTRAPARTIDA —
    conta de passivo — e é o lançamento, com sequência e histórico.
    """
    prov = [{"grupo": 1, "reduzido": 213104, "sequencia": 1,
             "dia": datetime.date(2026, 8, 31),
             "conta": "Provisao para Fornecedores",
             "historico": "VLR REF PROV PEDAGIO FAT 00000000000 - SEM PARAR",
             "valor": 368099.24}]
    ciclo_anterior = [{"grupo": 1, "reduzido": 213104, "n": 1,
                       "debito": 475888.87}]

    chamadas = {"n": 0}

    def _query(sql, params=None):
        chamadas["n"] += 1
        if "estrutural ~ '^2'" in sql and "BAIXA" not in sql:
            return prov
        if "BAIXA PROV" in sql:
            # 1a chamada = ciclo atual (sem baixa ainda); 2a = ciclo anterior
            return [] if chamadas["n"] == 2 else ciclo_anterior
        return [{"ultimo": datetime.date(2026, 9, 4)}]

    monkeypatch.setattr(pc.db, "query", _query)
    r = pc.provisoes("2026-08")

    assert r["total_aberto"] == pytest.approx(368099.24)
    aberta = r["abertas"][0]
    assert aberta["sequencia"] == 1
    assert aberta["reduzido"] == 213104
    assert "SEM PARAR" in aberta["historico"]
    # o valor NUNCA é o saldo do dia da conta de custo
    assert aberta["valor"] != pytest.approx(268172.89)


def test_provisao_que_nao_cicla_fica_fora_da_ressalva(monkeypatch):
    """13º e férias acumulam, não viram fatura no dia 4 — contá-las na ressalva
    inflaria o aviso com dinheiro que não vai mudar o resultado do mês."""
    prov = [
        {"grupo": 1, "reduzido": 213104, "sequencia": 1,
         "dia": datetime.date(2026, 8, 31), "conta": "Provisao Fornecedores",
         "historico": "VLR REF PROV PEDAGIO - SEM PARAR", "valor": 368099.24},
        {"grupo": 1, "reduzido": 215302, "sequencia": 29,
         "dia": datetime.date(2026, 8, 31), "conta": "Provisoes 13o Salario",
         "historico": "VLR REF PROVISAO 13 SALARIO - MOT", "valor": 62825.44},
    ]
    chamadas = {"n": 0}

    def _query(sql, params=None):
        chamadas["n"] += 1
        if "estrutural ~ '^2'" in sql and "BAIXA" not in sql:
            return prov
        if "BAIXA PROV" in sql:
            if chamadas["n"] == 2:      # ciclo atual: nada baixado ainda
                return []
            # ciclo anterior: SÓ a de fornecedores tem baixa
            return [{"grupo": 1, "reduzido": 213104, "n": 1,
                     "debito": 475888.87}]
        return [{"ultimo": datetime.date(2026, 9, 4)}]

    monkeypatch.setattr(pc.db, "query", _query)
    r = pc.provisoes("2026-08")

    assert len(r["itens"]) == 2                  # as duas aparecem
    assert len(r["abertas"]) == 1                # só uma entra na ressalva
    assert r["abertas"][0]["reduzido"] == 213104
    assert r["total_aberto"] == pytest.approx(368099.24)
    assert r["total"] == pytest.approx(430924.68)


def test_provisao_baixada_sai_da_ressalva(monkeypatch):
    prov = [{"grupo": 1, "reduzido": 213104, "sequencia": 1,
             "dia": datetime.date(2026, 7, 31), "conta": "Provisao Fornec.",
             "historico": "VLR REF PROV PEDAGIO", "valor": 475888.87}]
    baixa = [{"grupo": 1, "reduzido": 213104, "n": 1, "debito": 475888.87}]

    monkeypatch.setattr(pc.db, "query", lambda sql, params=None:
                        prov if ("estrutural ~ '^2'" in sql
                                 and "BAIXA" not in sql)
                        else (baixa if "BAIXA PROV" in sql
                              else [{"ultimo": datetime.date(2026, 9, 4)}]))
    r = pc.provisoes("2026-07")
    assert r["abertas"] == []
    assert r["total_aberto"] == 0.0


def test_erp_com_dia_ruim_nao_derruba_o_parecer(monkeypatch):
    """Painel não morre por dependência externa: a falha se DIZ."""
    def _explode(*a, **k):
        raise RuntimeError("connection timeout expired")
    monkeypatch.setattr(pc.db, "query", _explode)
    r = pc.provisoes("2026-08")
    assert r["erro"]
    assert r["itens"] == [] and r["abertas"] == []
    assert r["total_aberto"] == 0.0


# --------------------------------------------------------------------------
# datas
# --------------------------------------------------------------------------
def test_meses_vizinhos_atravessam_a_virada_do_ano():
    assert pc._ultimo_dia("2026-02") == datetime.date(2026, 2, 28)
    assert pc._ultimo_dia("2024-02") == datetime.date(2024, 2, 29)
    assert pc._mes_seguinte("2026-12") == "2027-01"
    assert pc._mes_anterior("2026-01") == "2025-12"


def test_razao_ate_nao_pode_olhar_data_futura():
    """O ERP tem lançamento com data futura (parcela programada): sem o teto em
    current_date, 'até quando já foi lançado' respondia dezembro."""
    assert "current_date" in pc.SQL_RAZAO_ATE


# --------------------------------------------------------------------------
# RBAC das rotas
# --------------------------------------------------------------------------
def test_as_duas_rotas_estao_mapeadas_e_na_ordem_certa():
    """`ROTA_TELAS` casa por PREFIXO e devolve o PRIMEIRO que casar.

    Com a genérica na frente, `/api/dre/parecer/narrativa` nunca chegaria à
    própria entrada — e o middleware é fail-closed, então errar aqui não dá
    erro visível: dá 403 numa aba que ninguém sabe por que parou.
    """
    from api import auth

    prefixos = [p for p, _ in auth.ROTA_TELAS]
    assert "/api/dre/parecer" in prefixos
    assert "/api/dre/parecer/narrativa" in prefixos
    assert (prefixos.index("/api/dre/parecer/narrativa")
            < prefixos.index("/api/dre/parecer"))

    for rota in ("/api/dre/parecer", "/api/dre/parecer/narrativa"):
        telas = next(t for p, t in auth.ROTA_TELAS if rota.startswith(p))
        assert "dre" in telas, rota


def test_parecer_recusa_periodo_de_um_mes(monkeypatch):
    monkeypatch.setattr(pc.queries, "get_dre",
                        lambda de, ate: {"meses": ["2026-08"], "linhas": []})
    # o cache da casa não expõe `__wrapped__`; a chave inclui os argumentos,
    # então esta chamada não colide com nenhuma outra do teste
    r = pc.parecer("2026-08", "2026-08")
    assert r["erro"]
    assert "dois meses" in r["erro"]
