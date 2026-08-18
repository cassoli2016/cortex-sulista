"""Conferência do RNTRC — pura, sem banco e sem rede."""
from __future__ import annotations

from api.antt.rntrc_servico import conferir, resumir


def _contratado(rntrc="7600540", nome="ALFA", pessoa="PJ", viagens=10,
                pago=100000.0):
    return {"codigo": "C1", "rntrc": rntrc, "nome": nome, "pessoa": pessoa,
            "viagens": viagens, "pago": pago, "ultima_viagem": "2026-08-01"}


def _base(**kw):
    padrao = {"7600540": {"rntrc": "7600540", "situacao": "ATIVO",
                          "categoria": "ETC", "uf": "SP", "nome": "ALFA",
                          "data_situacao": "01/07/2026"}}
    padrao.update(kw)
    return padrao


def test_registro_ativo_fica_regular():
    r = conferir([_contratado()], _base())[0]
    assert r["situacao"] == "ativo"
    assert r["risco"] is False


def test_registro_pendente_e_risco_com_valor_ao_lado():
    base = _base(**{"7600540": {"rntrc": "7600540", "situacao": "PENDENTE",
                                "categoria": "TAC", "uf": "RS", "nome": "X",
                                "data_situacao": "01/07/2026"}})
    r = conferir([_contratado(pago=1058578.0)], base)[0]
    assert r["situacao"] == "pendente"
    assert r["risco"] is True
    assert r["pago"] == 1058578.0


def test_zero_a_esquerda_no_cadastro_nao_vira_falso_alarme():
    """O defeito que custou 19 falsos positivos na validação."""
    r = conferir([_contratado(rntrc="07600540")], _base())[0]
    assert r["situacao"] == "ativo"


def test_ausente_da_base_nao_e_o_mesmo_que_sem_registro():
    """A base aberta só publica ATIVO e PENDENTE: quem não aparece pode estar
    baixado. É risco, mas de natureza diferente de quem nem tem registro."""
    fora = conferir([_contratado(rntrc="9999999")], _base())[0]
    sem = conferir([_contratado(rntrc="")], _base())[0]
    assert fora["situacao"] == "nao_encontrado"
    assert sem["situacao"] == "sem_registro"
    assert fora["risco"] is True and sem["risco"] is True


def test_resumo_separa_regular_de_risco_e_soma_o_exposto():
    base = _base(**{"111": {"rntrc": "111", "situacao": "PENDENTE",
                            "categoria": "TAC", "uf": "SP", "nome": "B",
                            "data_situacao": "01/07/2026"}})
    conf = conferir([_contratado(pago=50000.0),
                     _contratado(rntrc="111", nome="B", pago=30000.0),
                     _contratado(rntrc="9999999", nome="C", pago=20000.0)], base)
    k = resumir(conf)
    assert k["transportadores"] == 3
    assert k["ativos"] == 1
    assert k["em_risco"] == 2
    assert k["pago_em_risco"] == 50000.0
    assert k["pago_total"] == 100000.0


def test_resumo_de_lista_vazia_nao_divide_por_zero():
    k = resumir([])
    assert k["transportadores"] == 0
    assert k["pct_risco"] is None


def test_base_nunca_sincronizada_nao_acusa_ninguem():
    """Sem base local, todo mundo pareceria irregular. A tela precisa dizer
    'base ausente', não 'todos irregulares'."""
    conf = conferir([_contratado()], {})
    assert conf[0]["situacao"] == "sem_base"
    assert conf[0]["risco"] is False


def test_ordenacao_poe_o_risco_primeiro_e_o_maior_valor_no_topo():
    """É a ordem da ação: quem está irregular e recebeu mais vem primeiro."""
    from api.antt.rntrc_servico import ordenar
    base = _base(**{"111": {"rntrc": "111", "situacao": "PENDENTE",
                            "categoria": "TAC", "uf": "SP", "nome": "B",
                            "data_situacao": "01/07/2026"}})
    conf = ordenar(conferir([
        _contratado(pago=900000.0, nome="REGULAR GRANDE"),
        _contratado(rntrc="111", nome="PENDENTE PEQUENO", pago=30000.0),
        _contratado(rntrc="9999999", nome="FORA DA BASE", pago=200000.0),
    ], base))
    assert [c["nome"] for c in conf] == [
        "FORA DA BASE", "PENDENTE PEQUENO", "REGULAR GRANDE"]
