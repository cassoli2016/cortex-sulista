# -*- coding: utf-8 -*-
"""O ciclo inteiro de um armazém, de ponta a ponta, contra o banco de verdade
(schema descartável): nota → conferência cega → doca → armazenagem →
pedido → separação FEFO → expedição. Cada passo confere o SALDO, que é a
única coisa que o armazém existe para manter certa."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api.validacao import DadoInvalido
from api.wms import cadastro, estoque, expedicao, recebimento
from tests.wms.conftest import CNPJ_DEP, USUARIO


def _saldo(arm, **k):
    return {(x["endereco"], x["produto"], x["lote"]): x["qtd"]
            for x in estoque.saldo(arm["id"], **k)["saldo"]}


def _receber(arm, itens, **extra):
    r = recebimento.abrir({"armazem_id": arm["id"], "doca_id": arm["doca"],
                           "depositante_cnpj": CNPJ_DEP, "nf_numero": 1234,
                           "itens": [{"produto_id": p, "qtd_nf": q} for p, q, *_ in itens],
                           **extra}, USUARIO)
    conf = []
    for it, (_p, _q, contado, *resto) in zip(r["itens"], itens):
        lote, val, av = (resto + [None, None, None])[:3]
        conf.append({"id": it["id"], "qtd_conferida": contado, "lote": lote,
                     "validade": val, "qtd_avaria": av})
    recebimento.conferir(r["id"], conf, USUARIO)
    return r["id"]


def test_a_conferencia_e_cega_ate_fechar(armazem):
    r = recebimento.abrir({"armazem_id": armazem["id"], "doca_id": armazem["doca"],
                           "depositante_cnpj": CNPJ_DEP,
                           "itens": [{"produto_id": armazem["p1"], "qtd_nf": "10"}]}, USUARIO)
    assert r["cego"] is True
    assert r["itens"][0]["qtd_nf"] is None, "a quantidade da nota vazou para quem confere"
    lista = recebimento.listar(armazem["id"])["recebimentos"][0]
    assert lista["qtd_nf"] is None and lista["itens_divergentes"] is None
    recebimento.conferir(r["id"], [{"id": r["itens"][0]["id"], "qtd_conferida": "9"}], USUARIO)
    fechado = recebimento.fechar(r["id"], USUARIO)
    assert fechado["cego"] is False
    assert fechado["itens"][0]["qtd_nf"] == 10.0
    assert fechado["itens"][0]["divergencia"] == -1.0
    assert fechado["resumo"]["falta"] == 1.0


def test_fechar_da_entrada_na_doca_e_a_avaria_vai_para_a_area_de_avaria(armazem):
    rid = _receber(armazem, [(armazem["p1"], 10, 10, "", None, 2)])
    recebimento.fechar(rid, USUARIO)
    s = _saldo(armazem)
    assert s[("DOCA1", "961.0301-0", "")] == 8
    assert s[("AVARIA", "961.0301-0", "")] == 2


def test_nao_fecha_com_item_sem_conferir_nem_sem_lote_de_quem_controla(armazem):
    r = recebimento.abrir({"armazem_id": armazem["id"], "doca_id": armazem["doca"],
                           "depositante_cnpj": CNPJ_DEP,
                           "itens": [{"produto_id": armazem["p1"], "qtd_nf": 5},
                                     {"produto_id": armazem["p2"], "qtd_nf": 3}]}, USUARIO)
    recebimento.conferir(r["id"], [{"id": r["itens"][0]["id"], "qtd_conferida": 5}], USUARIO)
    with pytest.raises(DadoInvalido, match="Faltam conferir 1"):
        recebimento.fechar(r["id"], USUARIO)
    recebimento.conferir(r["id"], [{"id": r["itens"][1]["id"], "qtd_conferida": 3}], USUARIO)
    with pytest.raises(DadoInvalido, match="controla lote"):
        recebimento.fechar(r["id"], USUARIO)
    # a recusa não deixou meia entrada para trás
    assert _saldo(armazem) == {}


def test_armazenar_sugere_endereco_vazio_e_depois_junta_com_o_mesmo_lote(armazem):
    rid = _receber(armazem, [(armazem["p1"], 10, 10)])
    recebimento.fechar(rid, USUARIO)
    doca = estoque.doca(armazem["id"])
    assert doca["total"] == 1
    sug = doca["doca"][0]["sugestao"]
    assert sug["codigo"] == "A-01-01-01" and sug["motivo"] == "endereço vazio"
    estoque.transferir({"origem_id": armazem["doca"], "produto_id": armazem["p1"],
                        "qtd": 6, "destino_codigo": "a-01-01-01"}, USUARIO)
    # o que sobrou na doca é sugerido para junto do mesmo produto e lote
    sug2 = estoque.doca(armazem["id"])["doca"][0]["sugestao"]
    assert sug2["codigo"] == "A-01-01-01" and "mesmo produto" in sug2["motivo"]
    s = _saldo(armazem)
    assert s[("DOCA1", "961.0301-0", "")] == 4 and s[("A-01-01-01", "961.0301-0", "")] == 6


def test_a_doca_so_recebe_pelo_recebimento(armazem):
    rid = _receber(armazem, [(armazem["p1"], 5, 5)])
    recebimento.fechar(rid, USUARIO)
    estoque.transferir({"origem_id": armazem["doca"], "produto_id": armazem["p1"], "qtd": 5,
                        "destino_id": armazem["end"]["A-01-01-01"]}, USUARIO)
    with pytest.raises(DadoInvalido, match="não recebe"):
        estoque.transferir({"origem_id": armazem["end"]["A-01-01-01"],
                            "produto_id": armazem["p1"], "qtd": 1,
                            "destino_id": armazem["doca"]}, USUARIO)


def _estocar_dois_lotes(arm):
    """Lote L2 vence ANTES do L1, e está num endereço de código MAIOR — FEFO
    tem de ir buscá-lo mesmo assim."""
    hoje = date.today()
    rid = _receber(arm, [(arm["p2"], 10, 10, "L1", (hoje + timedelta(days=200)).isoformat()),
                         (arm["p2"], 10, 10, "L2", (hoje + timedelta(days=20)).isoformat())])
    recebimento.fechar(rid, USUARIO)
    estoque.transferir({"origem_id": arm["doca"], "produto_id": arm["p2"], "lote": "L1",
                        "qtd": 10, "destino_codigo": "A-01-01-01"}, USUARIO)
    estoque.transferir({"origem_id": arm["doca"], "produto_id": arm["p2"], "lote": "L2",
                        "qtd": 10, "destino_codigo": "B-02-01-02"}, USUARIO)


def test_separacao_e_FEFO_e_a_expedicao_zera_o_que_saiu(armazem):
    _estocar_dois_lotes(armazem)
    p = expedicao.criar({"armazem_id": armazem["id"], "depositante_cnpj": CNPJ_DEP,
                         "numero": "PV-1", "itens": [{"produto_id": armazem["p2"], "qtd": 12}]},
                        USUARIO)
    lib = expedicao.liberar(p["id"], USUARIO)
    tarefas = sorted(lib["tarefas"], key=lambda t: t["qtd"], reverse=True)
    assert [(t["lote"], t["qtd"]) for t in tarefas] == [("L2", 10.0), ("L1", 2.0)], \
        "FEFO: o lote que vence primeiro sai primeiro, mesmo no fundo da rua"
    assert lib["situacao"] == "em_separacao"
    for t in lib["tarefas"]:
        expedicao.confirmar_tarefa(t["id"], None, USUARIO)
    assert expedicao.detalhe(p["id"])["situacao"] == "separado"
    s = _saldo(armazem)
    assert s[("EXP1", "OLEO-20L", "L2")] == 10 and s[("EXP1", "OLEO-20L", "L1")] == 2
    with pytest.raises(DadoInvalido, match="placa"):
        expedicao.expedir(p["id"], {}, USUARIO)
    expedicao.expedir(p["id"], {"placa": "abc1d23"}, USUARIO)
    s = _saldo(armazem)
    assert ("EXP1", "OLEO-20L", "L2") not in s and s[("A-01-01-01", "OLEO-20L", "L1")] == 8
    assert expedicao.detalhe(p["id"])["placa"] == "ABC1D23"


def test_liberar_e_tudo_ou_nada_e_reserva_o_disponivel(armazem):
    _estocar_dois_lotes(armazem)
    grande = expedicao.criar({"armazem_id": armazem["id"], "depositante_cnpj": CNPJ_DEP,
                              "itens": [{"produto_id": armazem["p2"], "qtd": 25}]}, USUARIO)
    with pytest.raises(DadoInvalido, match="faltam 5"):
        expedicao.liberar(grande["id"], USUARIO)
    assert expedicao.detalhe(grande["id"])["tarefas"] == [], "reserva parcial ficou presa"
    p = expedicao.criar({"armazem_id": armazem["id"], "depositante_cnpj": CNPJ_DEP,
                         "itens": [{"produto_id": armazem["p2"], "qtd": 10}]}, USUARIO)
    expedicao.liberar(p["id"], USUARIO)
    # o L2 inteiro está reservado: movimentar dele é recusado, com o número
    with pytest.raises(DadoInvalido, match="reservados para separação"):
        estoque.transferir({"origem_id": armazem["end"]["B-02-01-02"],
                            "produto_id": armazem["p2"], "lote": "L2", "qtd": 1,
                            "destino_codigo": "B-01-01-01"}, USUARIO)
    disp = cadastro.listar_produtos(depositante=CNPJ_DEP, armazem_id=armazem["id"])
    oleo = next(x for x in disp["produtos"] if x["codigo"] == "OLEO-20L")
    assert oleo["disponivel"] == 10.0 and oleo["saldo"] == 20.0


def test_cancelar_devolve_o_separado_para_a_origem(armazem):
    _estocar_dois_lotes(armazem)
    p = expedicao.criar({"armazem_id": armazem["id"], "depositante_cnpj": CNPJ_DEP,
                         "itens": [{"produto_id": armazem["p2"], "qtd": 4}]}, USUARIO)
    t = expedicao.liberar(p["id"], USUARIO)["tarefas"][0]
    expedicao.confirmar_tarefa(t["id"], 3, USUARIO)          # corte de 1
    assert _saldo(armazem)[("EXP1", "OLEO-20L", "L2")] == 3
    expedicao.cancelar(p["id"], "cliente desistiu", USUARIO)
    s = _saldo(armazem)
    assert ("EXP1", "OLEO-20L", "L2") not in s
    assert s[("B-02-01-02", "OLEO-20L", "L2")] == 10


def test_a_mesma_nota_nao_entra_duas_vezes(armazem):
    chave = "31251136448137000150550110001797951350179825"
    base = {"armazem_id": armazem["id"], "doca_id": armazem["doca"],
            "depositante_cnpj": CNPJ_DEP, "nf_chave": chave,
            "itens": [{"produto_id": armazem["p1"], "qtd_nf": 1}]}
    r = recebimento.abrir(base, USUARIO)
    with pytest.raises(DadoInvalido, match="já tem um recebimento"):
        recebimento.abrir(base, USUARIO)
    recebimento.cancelar(r["id"], "nota errada", USUARIO)
    recebimento.abrir(base, USUARIO)          # cancelado libera a chave


def test_kardex_guarda_cada_passo_com_o_documento(armazem):
    rid = _receber(armazem, [(armazem["p1"], 3, 3)])
    recebimento.fechar(rid, USUARIO)
    estoque.transferir({"origem_id": armazem["doca"], "produto_id": armazem["p1"], "qtd": 3,
                        "destino_codigo": "A-01-01-02"}, USUARIO)
    k = estoque.kardex(armazem["id"])
    docs = [(m["doc_tipo"], m["endereco"], m["qtd"]) for m in reversed(k["movimentos"])]
    assert docs == [("recebimento", "DOCA1", 3.0), ("armazenagem", "DOCA1", -3.0),
                    ("armazenagem", "A-01-01-02", 3.0)]
    assert all(m["usuario"] == USUARIO for m in k["movimentos"])
