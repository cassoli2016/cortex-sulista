# -*- coding: utf-8 -*-
"""Inventário: bloqueia o escopo, conta às cegas, exige TODOS os endereços
contados, ajusta a diferença e só desbloqueia o que ele mesmo bloqueou."""
from __future__ import annotations

import pytest

from api.validacao import DadoInvalido
from api.wms import estoque, inventario, recebimento
from tests.wms.conftest import CNPJ_DEP, USUARIO


def _estocar(arm, destino, qtd):
    r = recebimento.abrir({"armazem_id": arm["id"], "doca_id": arm["doca"],
                           "depositante_cnpj": CNPJ_DEP,
                           "itens": [{"produto_id": arm["p1"], "qtd_nf": qtd}]}, USUARIO)
    recebimento.conferir(r["id"], [{"id": r["itens"][0]["id"], "qtd_conferida": qtd}], USUARIO)
    recebimento.fechar(r["id"], USUARIO)
    estoque.transferir({"origem_id": arm["doca"], "produto_id": arm["p1"], "qtd": qtd,
                        "destino_codigo": destino}, USUARIO)


def test_ciclo_do_inventario_da_rua_A(armazem):
    _estocar(armazem, "A-01-01-01", 10)
    _estocar(armazem, "A-02-01-01", 5)
    # um endereço JÁ bloqueado por avaria antes do inventário
    estoque.bloquear(armazem["end"]["A-02-01-02"], "estrutura danificada", USUARIO)

    inv = inventario.abrir({"armazem_id": armazem["id"], "rua": "A"}, USUARIO)
    codigos = [e["codigo"] for e in inv["enderecos"]]
    assert codigos == ["A-01-01-01", "A-01-01-02", "A-02-01-01", "A-02-01-02"]
    # a contagem é cega: o detalhe não traz saldo nenhum
    assert "saldo" not in str(inv).lower() or all("qtd" not in e for e in inv["enderecos"])
    # o escopo ficou bloqueado — ninguém mexe enquanto se conta
    with pytest.raises(DadoInvalido, match="bloqueado"):
        estoque.transferir({"origem_id": armazem["end"]["A-01-01-01"],
                            "produto_id": armazem["p1"], "qtd": 1,
                            "destino_codigo": "B-01-01-01"}, USUARIO)

    ends = {e["codigo"]: e["endereco_id"] for e in inv["enderecos"]}
    inventario.contar(inv["id"], ends["A-01-01-01"], [{"produto_id": armazem["p1"], "qtd": 9}],
                      USUARIO)
    with pytest.raises(DadoInvalido, match="Faltam contar 3"):
        inventario.fechar(inv["id"], USUARIO)
    inventario.contar(inv["id"], ends["A-02-01-01"], [{"produto_id": armazem["p1"], "qtd": 5}],
                      USUARIO)
    for vazio in ("A-01-01-02", "A-02-01-02"):
        inventario.contar(inv["id"], ends[vazio], [], USUARIO)     # "está vazio" é contagem

    r = inventario.fechar(inv["id"], USUARIO)
    assert r["enderecos"] == 4 and r["com_divergencia"] == 1 and r["ajustes"] == 1
    assert r["acuracia"] == 75.0 and r["falta"] == 1.0
    s = {x["endereco"]: x["qtd"] for x in estoque.saldo(armazem["id"])["saldo"]}
    assert s["A-01-01-01"] == 9 and s["A-02-01-01"] == 5
    # desbloqueou o que ELE bloqueou; o bloqueio por avaria continua
    bloqueados = {e["codigo"] for e in estoque.saldo(armazem["id"])["saldo"] if e["bloqueado"]}
    assert not bloqueados
    from api.wms import cadastro
    ainda = [e["codigo"] for e in cadastro.listar_enderecos(armazem["id"],
                                                             situacao="bloqueado")["enderecos"]]
    assert ainda == ["A-02-01-02"]
    det = inventario.detalhe(inv["id"])
    assert det["acuracia"] == 75.0 and det["ajustes"][0]["qtd"] == -1.0


def test_endereco_do_inventario_nao_se_desbloqueia_a_mao(armazem):
    inv = inventario.abrir({"armazem_id": armazem["id"], "rua": "B-01"}, USUARIO)
    alvo = inv["enderecos"][0]["endereco_id"]
    with pytest.raises(DadoInvalido, match="inventário #"):
        estoque.desbloquear(alvo, USUARIO)
    inventario.cancelar(inv["id"], USUARIO)
    estoque.bloquear(alvo, "quarentena", USUARIO)      # voltou a ser livre


def test_dois_inventarios_nao_disputam_o_mesmo_endereco(armazem):
    inventario.abrir({"armazem_id": armazem["id"], "rua": "A"}, USUARIO)
    with pytest.raises(DadoInvalido, match="outro inventário aberto"):
        inventario.abrir({"armazem_id": armazem["id"], "rua": "A-01"}, USUARIO)
