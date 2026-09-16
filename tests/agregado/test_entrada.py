# -*- coding: utf-8 -*-
"""A entrada no app do agregado: a resposta que não denuncia, e as contenções.

A RESPOSTA UNIFORME É O CONTRATO deste fluxo. Um formulário aberto que responde
diferente para número que existe e que não existe vira uma máquina de descobrir
quem é dono de caminhão que roda para esta empresa — e, com paciência, quantos
veículos cada um tem. Por isso quase todo teste aqui compara a resposta de um
caso bom com a de um caso ruim, em vez de conferir texto solto.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.agregado import entrada as aent
from api.agregado import sessao as ases
from tests.agregado.conftest import cadastrar, codigo_enviado

FONE = "5541999990001"
OUTRO = "5541999990002"
COD = "12345678000190"


def test_a_resposta_e_a_mesma_para_numero_que_existe_e_que_nao_existe(esq, zap):
    cadastrar(esq, COD, FONE)
    existe = aent.pedir(FONE, ip="1.1.1.1", esquema=esq)
    nao_existe = aent.pedir(OUTRO, ip="1.1.1.1", esquema=esq)
    assert existe == nao_existe == {"ok": True, "mensagem": aent.RESPOSTA_PEDIDO}
    # e só o cadastrado recebeu mensagem
    assert [e["telefone"] for e in zap] == [FONE]


def test_o_numero_desconhecido_nao_vira_linha_na_tabela(esq, zap):
    """Gravar aqui faria a tabela de códigos virar a lista de quem TENTOU —
    justamente o dado que não se quer ter."""
    aent.pedir(OUTRO, ip="1.1.1.1", esquema=esq)
    n = pglocal.um("SELECT count(*) AS n FROM agr_codigos", {}, esq)
    assert int(n["n"]) == 0


def test_o_codigo_nao_e_gravado_em_lugar_nenhum(esq, zap):
    cadastrar(esq, COD, FONE)
    aent.pedir(FONE, esquema=esq)
    codigo = codigo_enviado(zap)
    linha = pglocal.um("SELECT codigo_hash FROM agr_codigos", {}, esq)
    assert codigo not in linha["codigo_hash"]
    assert len(linha["codigo_hash"]) == 64          # SHA-256 em hex


def test_entrar_com_o_codigo_abre_sessao_e_o_token_traz_o_id_opaco(esq, zap):
    ident = cadastrar(esq, COD, FONE, nome="Transportes Fulano")
    aent.pedir(FONE, esquema=esq)
    r = aent.confirmar(FONE, codigo_enviado(zap), aparelho="x1", esquema=esq)
    assert r["ok"] and r["agregado_id"] == ident and r["nome"] == "Transportes Fulano"
    # O DOCUMENTO NÃO SAI: o payload tem o id opaco, nunca o código do ERP.
    assert COD not in str(r)
    sess = ases.atual(r["token"], esq)
    assert sess["agregado_id"] == ident
    assert sess["proprietario_codigo"] == COD       # e ele existe, só que dentro


def test_codigo_errado_e_codigo_expirado_dizem_a_mesma_coisa(esq, zap):
    cadastrar(esq, COD, FONE)
    aent.pedir(FONE, esquema=esq)
    with pytest.raises(aent.Recusa) as errado:
        aent.confirmar(FONE, "000000", esquema=esq)
    pglocal.executar("UPDATE agr_codigos SET expira_em = now() - interval '1 min'", {}, esq)
    with pytest.raises(aent.Recusa) as expirado:
        aent.confirmar(FONE, codigo_enviado(zap), esquema=esq)
    assert str(errado.value) == str(expirado.value) == aent.RECUSA_CODIGO


def test_o_codigo_morre_depois_do_teto_de_tentativas(esq, zap):
    cadastrar(esq, COD, FONE)
    aent.pedir(FONE, esquema=esq)
    certo = codigo_enviado(zap)
    for _ in range(aent.MAX_TENTATIVAS):
        with pytest.raises(aent.Recusa):
            aent.confirmar(FONE, "000000", esquema=esq)
    # o código CERTO já não vale: seis dígitos são um milhão de combinações, e
    # sem o teto um laço acerta em minutos
    with pytest.raises(aent.Recusa):
        aent.confirmar(FONE, certo, esquema=esq)


def test_o_freio_por_telefone_nao_se_anuncia(esq, zap):
    """Passar do teto responde IGUAL a tudo o mais — senão o próprio freio
    vira o oráculo que a resposta uniforme existe para fechar."""
    cadastrar(esq, COD, FONE)
    for _ in range(aent.MAX_PEDIDOS_HORA):
        aent.pedir(FONE, esquema=esq)
    freado = aent.pedir(FONE, esquema=esq)
    assert freado == {"ok": True, "mensagem": aent.RESPOSTA_PEDIDO}
    assert len(zap) == aent.MAX_PEDIDOS_HORA       # o quarto não saiu


def test_o_desligado_nao_entra_mesmo_com_o_codigo_certo(esq, zap):
    """O vínculo é conferido na confirmação, e não só no pedido: entre um e
    outro cabe o desligamento."""
    cadastrar(esq, COD, FONE)
    aent.pedir(FONE, esquema=esq)
    codigo = codigo_enviado(zap)
    pglocal.executar("UPDATE agr_vinculos SET ativo = false", {}, esq)
    with pytest.raises(aent.Recusa) as exc:
        aent.confirmar(FONE, codigo, esquema=esq)
    # recusa DIFERENTE: aqui a pessoa provou quem é, e esconder o motivo só a
    # faria tentar de novo para sempre
    assert str(exc.value) != aent.RECUSA_CODIGO


def test_telefone_em_dois_cadastros_pergunta_quem_e_sem_queimar_o_codigo(esq, zap):
    """O caso comum aqui é o dono pessoa física que também tem veículo no CNPJ
    da empresa dele."""
    pf = cadastrar(esq, "11122233344", FONE, nome="Fulano de Tal")
    pj = cadastrar(esq, COD, FONE, nome="Transportes Fulano")
    aent.pedir(FONE, esquema=esq)
    codigo = codigo_enviado(zap)
    escolha = aent.confirmar(FONE, codigo, esquema=esq)
    assert {e["id"] for e in escolha["escolher"]} == {pf, pj}
    # A LISTA VAI PELO ID OPACO: mandar o código do ERP aqui exporia o CPF de
    # um terceiro (o outro cadastro) a quem digitou seis dígitos.
    assert "11122233344" not in str(escolha)
    # e o código NÃO foi consumido — a pessoa acabou de prová-lo
    r = aent.confirmar(FONE, codigo, agregado=str(pj), esquema=esq)
    assert r["ok"] and r["agregado_id"] == pj


def test_escolher_um_cadastro_que_nao_e_do_telefone_e_recusado(esq, zap):
    """Sem isto, o `agregado` do corpo do pedido seria um seletor de vítima."""
    cadastrar(esq, COD, FONE)
    alheio = cadastrar(esq, "99988877766", OUTRO, nome="Outro Dono")
    aent.pedir(FONE, esquema=esq)
    with pytest.raises(aent.Recusa):
        aent.confirmar(FONE, codigo_enviado(zap), agregado=str(alheio), esquema=esq)
