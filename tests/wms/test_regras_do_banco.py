# -*- coding: utf-8 -*-
"""As regras que o BANCO garante — saldo nunca negativo, kardex imutável,
endereço bloqueado parado — testadas por baixo do Python, direto no SQL.

Se estas regras morassem só na rota, bastaria a próxima rota (ou um script
de correção escrito às pressas) para atravessá-las. O teste escreve SQL cru
de propósito: é o caminho que nenhuma validação do módulo protege.
"""
from __future__ import annotations

import threading

import psycopg
import pytest

from api import pglocal
from api.validacao import DadoInvalido
from api.wms import estoque, recebimento
from tests.wms.conftest import CNPJ_DEP, USUARIO


def _entrar(arm, qtd=10, endereco="A-01-01-01"):
    r = recebimento.abrir({"armazem_id": arm["id"], "doca_id": arm["doca"],
                           "depositante_cnpj": CNPJ_DEP,
                           "itens": [{"produto_id": arm["p1"], "qtd_nf": qtd}]}, USUARIO)
    recebimento.conferir(r["id"], [{"id": r["itens"][0]["id"], "qtd_conferida": qtd}], USUARIO)
    recebimento.fechar(r["id"], USUARIO)
    estoque.transferir({"origem_id": arm["doca"], "produto_id": arm["p1"], "qtd": qtd,
                        "destino_codigo": endereco}, USUARIO)
    return arm["end"][endereco]


def _sql(esquema, sql, params=()):
    with pglocal.get_conn(esquema) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def test_o_banco_recusa_saldo_negativo_mesmo_com_SQL_cru(armazem):
    end = _entrar(armazem, 10)
    with pytest.raises(psycopg.errors.RaiseException, match="saldo insuficiente"):
        _sql(armazem["esquema"],
             """INSERT INTO wms_movimento(tipo, produto_id, endereco_id, lote, qtd, doc_tipo)
                VALUES ('saida', %s, %s, '', -11, 'ajuste')""", (armazem["p1"], end))


def test_o_kardex_nao_se_edita_nem_se_apaga(armazem):
    _entrar(armazem, 2)
    for sql in ("UPDATE wms_movimento SET qtd = qtd * 2", "DELETE FROM wms_movimento"):
        with pytest.raises(psycopg.errors.RaiseException, match="imutável"):
            _sql(armazem["esquema"], sql)


def test_endereco_bloqueado_nao_movimenta_e_a_recusa_vira_frase(armazem):
    end = _entrar(armazem, 5)
    estoque.bloquear(end, "quarentena", USUARIO)
    with pytest.raises(DadoInvalido, match="bloqueado"):
        estoque.transferir({"origem_id": end, "produto_id": armazem["p1"], "qtd": 1,
                            "destino_codigo": "A-01-01-02"}, USUARIO)
    # ajuste com motivo passa: é a correção de quem bloqueou
    estoque.ajustar({"endereco_id": end, "produto_id": armazem["p1"], "qtd": "-1",
                     "motivo": "avaria achada na quarentena"}, USUARIO)
    estoque.desbloquear(end, USUARIO)
    assert estoque.saldo(armazem["id"], endereco_id=end)["saldo"][0]["qtd"] == 4


def test_ajuste_sem_motivo_e_recusado(armazem):
    end = _entrar(armazem, 5)
    with pytest.raises(DadoInvalido, match="motivo"):
        estoque.ajustar({"endereco_id": end, "produto_id": armazem["p1"], "qtd": -1}, USUARIO)


def test_duas_retiradas_simultaneas_nao_passam_as_duas(armazem):
    """A corrida que a trava por produto existe para impedir: duas pessoas
    tirando 6 de um endereço com 10, ao mesmo tempo. Sem a trava, as duas
    leriam 10 e o endereço terminaria em −2."""
    end = _entrar(armazem, 10)
    barreira = threading.Barrier(2)
    resultados: list[str] = []

    def tirar(destino):
        barreira.wait()
        try:
            estoque.transferir({"origem_id": end, "produto_id": armazem["p1"], "qtd": 6,
                                "destino_codigo": destino}, USUARIO)
            resultados.append("ok")
        except DadoInvalido as exc:
            resultados.append("recusa: " + str(exc))

    th = [threading.Thread(target=tirar, args=(d,)) for d in ("A-01-01-02", "A-02-01-01")]
    for t in th:
        t.start()
    for t in th:
        t.join(30)
    assert sorted(r[:2] for r in resultados) == ["ok", "re"], resultados
    total = sum(x["qtd"] for x in estoque.saldo(armazem["id"])["saldo"])
    assert total == 10, "a corrida criou ou destruiu mercadoria"
