"""Projetos — o controle do que acontece DEPOIS da venda.

O que se prova aqui, e que nenhum CHECK do banco garante sozinho:

1. **Nada de tempo é gravado.** Atraso, idade, duração e "parado há N dias" são
   todos derivados das datas contra hoje. No ERP de origem existe uma coluna
   `aging_dias` preenchida em ZERO de 194 projetos — e a tela que a lia mostrava
   "—" em todas as linhas desde sempre.
2. **O combinado e o acontecido não se confundem.** `deadline` × `entrega`,
   `inicio_previsto` × `inicio_real`. Guardar só o que aconteceu faz projeto
   entregue com três meses de atraso parecer entregue no prazo.
3. **O realizado NÃO é a receita do cliente dividida pelo prometido.** Essa
   conta deu 480% na bancada, com dado real, e era uma mentira com sinal de
   porcentagem. O que se mede é a VARIAÇÃO do faturamento depois do início.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api.crm import comum, contas, oportunidades, precificacao, projetos
from api.validacao import DadoInvalido


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(precificacao, "referencia_ckm",
                        lambda *a, **k: {"disponivel": True,
                                         "ckm_marginal": 13.28,
                                         "ckm_cheio": 24.93,
                                         "ckm_bruto": 10.22,
                                         "ckm_bruto_cheio": 19.17,
                                         "fonte": "dublê de teste"})
    return esquema_pg


def _conta(esq, **extra):
    return contas.gravar({"nome": "TUPY", "dono_nome": "Ana", **extra},
                         usuario="t", esquema=esq)


def _projeto(esq, conta, **extra):
    base = {"conta_id": conta["id"], "nome": "Implantação eixo sul",
            "responsavel_nome": "Bruno"}
    return projetos.gravar({**base, **extra}, usuario="t", esquema=esq)


def _colunas(esq, tabela):
    from api import pglocal
    return {r["column_name"] for r in pglocal.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s", (esq, tabela), esquema=esq)}


# ======================================================== nada de tempo gravado

def test_nao_existe_coluna_de_aging_nem_de_atraso(esq):
    """O ERP de origem tem `aging_dias` preenchida em 0 de 194 projetos, e
    tipada como timestamp apesar do nome. Aqui a idade é derivada."""
    cols = _colunas(esq, "crm_projetos")
    for proibida in ("aging_dias", "atrasado", "dias_atraso", "idade_dias",
                     "duracao_dias", "parado_dias"):
        assert proibida not in cols, proibida


def test_atraso_sai_das_datas_e_some_quando_entrega(esq):
    """Projeto entregue não "está atrasado" — ele atrasou ou não, e isso é
    outra coisa (`dias_de_atraso`)."""
    c = _conta(esq)
    ontem = (date.today() - timedelta(days=5)).isoformat()
    p = _projeto(esq, c, deadline=ontem, status="implantacao")
    assert p["atrasado"] is True and p["dias_para_deadline"] == -5
    assert p["dias_de_atraso"] is None       # ainda não entregou

    d = projetos.gravar(
        {"conta_id": c["id"], "nome": p["nome"], "responsavel_nome": "Bruno",
         "deadline": ontem, "status": "entregue",
         "entrega": date.today().isoformat()},
        usuario="t", projeto_id=p["id"], esquema=esq)
    assert d["atrasado"] is False            # fechado não "está" atrasado
    assert d["dias_de_atraso"] == 5 and d["no_prazo"] is False


def test_sem_prazo_combinado_nao_ha_afirmacao_de_pontualidade(esq):
    """Inventar zero faria a média de pontualidade mentir."""
    c = _conta(esq)
    p = _projeto(esq, c, status="entregue", entrega=date.today().isoformat())
    assert p["no_prazo"] is None and p["dias_de_atraso"] is None
    assert p["atrasado"] is False


# ============================================== combinado × acontecido

def test_entregue_exige_a_data_e_o_contrario_tambem(esq):
    c = _conta(esq)
    with pytest.raises(DadoInvalido) as e:
        _projeto(esq, c, status="entregue")
    assert "data de entrega" in str(e.value)

    p = _projeto(esq, c)
    with pytest.raises(DadoInvalido) as e2:
        projetos.gravar({"conta_id": c["id"], "nome": p["nome"],
                         "responsavel_nome": "Bruno", "status": "implantacao",
                         "entrega": date.today().isoformat()},
                        usuario="t", projeto_id=p["id"], esquema=esq)
    assert "status Entregue" in str(e2.value)


def test_datas_fora_de_ordem_sao_recusadas_dizendo_qual(esq):
    """A mensagem do CHECK do banco não diz QUAL das três datas está fora."""
    c = _conta(esq)
    with pytest.raises(DadoInvalido) as e:
        _projeto(esq, c, recebimento="2026-06-01", inicio_real="2026-05-01")
    assert "início real não pode ser anterior ao recebimento" in str(e.value)


# ================================================ nasce da oportunidade ganha

def test_projeto_so_nasce_de_oportunidade_GANHA(esq):
    c = _conta(esq)
    o = oportunidades.gravar({"conta_id": c["id"], "titulo": "Eixo sul",
                              "dono_nome": "Ana", "estagio": "proposta"},
                             usuario="t", esquema=esq)
    with pytest.raises(DadoInvalido) as e:
        projetos.de_oportunidade(o["id"], usuario="t", esquema=esq)
    assert "GANHA" in str(e.value)


def test_lanes_sao_COPIADAS_e_nao_referenciadas(esq):
    """Corrigir a proposta depois não pode reescrever o escopo prometido — é
    contra ele que o realizado vai ser medido."""
    c = _conta(esq)
    o = oportunidades.gravar({"conta_id": c["id"], "titulo": "Eixo sul",
                              "dono_nome": "Ana", "estagio": "proposta"},
                             usuario="t", esquema=esq)
    ln = oportunidades.gravar_lane(
        {"oportunidade_id": o["id"], "origem_cidade": "Joinville",
         "origem_uf": "SC", "destino_cidade": "Betim", "destino_uf": "MG",
         "km": "1000", "viagens_mes": "20", "valor_viagem": "9.000,00"},
        esquema=esq)
    oportunidades.mover(o["id"], "ganha", usuario="t", esquema=esq)
    p = projetos.de_oportunidade(o["id"], usuario="t", esquema=esq)
    assert p["lanes_copiadas"] == 1
    assert p["rob_mensal"] == 180000.0 and p["origem_rob"] == "lanes"

    # mexer na lane da PROPOSTA não mexe no escopo prometido do projeto
    oportunidades.gravar_lane({"id": ln["id"], "oportunidade_id": o["id"],
                               "origem_cidade": "Joinville", "origem_uf": "SC",
                               "destino_cidade": "Betim", "destino_uf": "MG",
                               "km": "1000", "viagens_mes": "20",
                               "valor_viagem": "5.000,00"},
                              lane_id=ln["id"], esquema=esq)
    d = projetos.obter(p["id"], com_erp=False, esquema=esq)
    assert d["rob_mensal"] == 180000.0, "o escopo prometido tem de ficar congelado"


def test_uma_venda_gera_UM_projeto(esq):
    """Dois projetos para a mesma venda dividiriam o ROB prometido em dois."""
    c = _conta(esq)
    o = oportunidades.gravar({"conta_id": c["id"], "titulo": "Eixo sul",
                              "dono_nome": "Ana", "estagio": "proposta"},
                             usuario="t", esquema=esq)
    oportunidades.mover(o["id"], "ganha", usuario="t", esquema=esq)
    projetos.de_oportunidade(o["id"], usuario="t", esquema=esq)
    with pytest.raises(DadoInvalido) as e:
        projetos.de_oportunidade(o["id"], usuario="t", esquema=esq)
    assert "já gerou o projeto" in str(e.value)


def test_a_lane_pertence_a_UM_dono(esq):
    """Oportunidade, contrato ou projeto — exatamente um. Lane com dois donos
    apareceria em duas telas com o mesmo id; com nenhum, em tela nenhuma."""
    c = _conta(esq)
    p = _projeto(esq, c)
    o = oportunidades.gravar({"conta_id": c["id"], "titulo": "X",
                              "dono_nome": "Ana"}, usuario="t", esquema=esq)
    with pytest.raises(DadoInvalido):
        oportunidades.gravar_lane({"projeto_id": p["id"],
                                   "oportunidade_id": o["id"], "km": "100"},
                                  esquema=esq)
    with pytest.raises(DadoInvalido):
        oportunidades.gravar_lane({"km": "100"}, esquema=esq)


# ============================================================ andamento

def test_andamento_registra_a_transicao_e_e_append_only(esq):
    c = _conta(esq)
    p = _projeto(esq, c)
    projetos.registrar_andamento(p["id"], texto_="Doca confirmada.",
                                 status="implantacao", percentual=30,
                                 usuario="t", esquema=esq)
    h = projetos.andamentos(p["id"], esquema=esq)
    assert len(h) == 2                      # criação + este
    assert h[0]["status_de"] == "nao_iniciado"
    assert h[0]["status_para"] == "implantacao"
    assert h[0]["percentual"] == 30
    assert not hasattr(projetos, "editar_andamento")


def test_andamento_NAO_encerra_projeto(esq):
    """Encerrar pede motivo e data — o andamento serve para o que anda."""
    c = _conta(esq)
    p = _projeto(esq, c)
    for st in ("entregue", "cancelado", "declinado"):
        with pytest.raises(DadoInvalido):
            projetos.registrar_andamento(p["id"], status=st, usuario="t",
                                         esquema=esq)


def test_encerrar_sem_motivo_e_recusado(esq):
    c = _conta(esq)
    p = _projeto(esq, c)
    with pytest.raises(DadoInvalido) as e:
        projetos.gravar({"conta_id": c["id"], "nome": p["nome"],
                         "responsavel_nome": "Bruno", "status": "cancelado"},
                        usuario="t", projeto_id=p["id"], esquema=esq)
    assert "motivo" in str(e.value).lower()


def test_projeto_aberto_sem_andamento_conta_desde_a_criacao(esq):
    """O que ninguém tocou desde o primeiro dia escaparia do alerta justamente
    por não ter histórico."""
    from api import pglocal
    c = _conta(esq)
    p = _projeto(esq, c)
    velho = (date.today() - timedelta(days=60)).isoformat() + "T09:00:00"
    pglocal.executar("UPDATE crm_projetos SET criado_em=%s WHERE id=%s",
                     (velho, p["id"]), esquema=esq)
    pglocal.executar("DELETE FROM crm_projeto_andamentos WHERE projeto_id=%s",
                     (p["id"],), esquema=esq)
    d = projetos.obter(p["id"], com_erp=False, esquema=esq)
    assert d["parado"] is True and d["parado_dias"] == 60


# ================================================= prometido × realizado

def test_realizado_mede_VARIACAO_e_nao_a_receita_do_cliente(esq, monkeypatch):
    """A primeira versão dividia a receita do cliente pelo ROB prometido e
    chamava de "atingimento": deu 480% com dado real, porque o numerador era o
    faturamento inteiro da TUPY e o denominador, um projeto.

    O que vale é a VARIAÇÃO — as duas pontas são incrementos e se comparam.
    """
    from api.crm import ava
    c = _conta(esq, ava_agrupamento=None)
    from api import pglocal
    pglocal.executar("UPDATE crm_contas SET ava_agrupamento=7 WHERE id=%s",
                     (c["id"],), esquema=esq)
    monkeypatch.setattr(ava, "carteira", lambda cods: {})
    monkeypatch.setattr(ava, "serie_mensal", lambda ag: [
        {"mes": "2026-01", "receita": 1000000.0, "viagens": 10, "km": 1.0},
        {"mes": "2026-02", "receita": 1000000.0, "viagens": 10, "km": 1.0},
        {"mes": "2026-03", "receita": 1500000.0, "viagens": 15, "km": 1.0},
        {"mes": "2026-04", "receita": 1500000.0, "viagens": 15, "km": 1.0},
    ])
    p = _projeto(esq, c, inicio_real="2026-02-15",
                 rob_mensal_manual="400.000,00")
    d = projetos.obter(p["id"], esquema=esq)
    r = d["realizado"]
    assert r["disponivel"] is True and r["atribuivel"] is True
    # o mês do início (02) fica FORA das duas metades: é parcial dos dois lados
    assert r["media_antes"] == 1000000.0 and r["meses_antes"] == 1
    assert r["media_depois"] == 1500000.0 and r["meses_depois"] == 2
    assert r["variacao"] == 500000.0
    assert r["atingimento"] == pytest.approx(500000.0 / 400000.0)


def test_realizado_avisa_quando_a_conta_tem_MAIS_DE_UM_projeto(esq, monkeypatch):
    """Com dois projetos abertos, a variação do faturamento não pode ser
    creditada a um deles — e a tela diz isso em vez de fingir."""
    from api import pglocal
    from api.crm import ava
    c = _conta(esq)
    pglocal.executar("UPDATE crm_contas SET ava_agrupamento=7 WHERE id=%s",
                     (c["id"],), esquema=esq)
    monkeypatch.setattr(ava, "carteira", lambda cods: {})
    monkeypatch.setattr(ava, "serie_mensal", lambda ag: [
        {"mes": "2026-01", "receita": 100.0, "viagens": 1, "km": 1.0},
        {"mes": "2026-03", "receita": 200.0, "viagens": 1, "km": 1.0}])
    p = _projeto(esq, c, inicio_real="2026-02-01")
    _projeto(esq, c, nome="Segundo projeto")
    d = projetos.obter(p["id"], esquema=esq)
    assert d["realizado"]["atribuivel"] is False
    assert d["realizado"]["projetos_na_conta"] == 2


def test_sem_vinculo_com_o_ERP_o_realizado_diz_por_que(esq):
    """Motivo escrito, não campo vazio — vazio manda a pessoa adivinhar."""
    c = _conta(esq)
    p = _projeto(esq, c, inicio_real=date.today().isoformat())
    d = projetos.obter(p["id"], esquema=esq)
    assert d["realizado"]["disponivel"] is False
    assert "grupo econômico" in d["realizado"]["motivo"]


def test_sem_inicio_real_nao_ha_periodo_depois(esq, monkeypatch):
    """`inicio_previsto` NÃO serve: o realizado se mede do que aconteceu.

    A conta precisa estar vinculada ao ERP para o teste chegar até aqui — sem
    vínculo o motivo é outro, e é o do teste anterior.
    """
    from api import pglocal
    from api.crm import ava
    c = _conta(esq)
    pglocal.executar("UPDATE crm_contas SET ava_agrupamento=7 WHERE id=%s",
                     (c["id"],), esquema=esq)
    monkeypatch.setattr(ava, "carteira", lambda cods: {})
    p = _projeto(esq, c, inicio_previsto="2026-01-01")
    d = projetos.obter(p["id"], esquema=esq)
    assert d["realizado"]["disponivel"] is False
    assert "não começou" in d["realizado"]["motivo"]
