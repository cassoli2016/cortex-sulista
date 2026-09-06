# -*- coding: utf-8 -*-
"""A entrada do app do motorista — guards de SEGURANÇA, antes de produto.

O QUE ESTES TESTES IMPEDEM:

- que o formulário público responda DIFERENTE para um número que existe e um
  que não existe — é o que o transformaria numa máquina de descobrir quem
  dirige para esta empresa, e daí a lista de placas e rotas de quem tiver
  paciência. A regra vale inclusive quando o envio falha e quando o freio corta;
- que o código de entrada seja GRAVADO em claro (backup e dump viram chave da
  conta de qualquer motorista);
- que um código sirva para sempre, ou aceite tentativa infinita;
- que um telefone vire disparador de WhatsApp contra alguém;
- que o telefone COMPARTILHADO (5 casos em 585, medido) entre no aparelho
  errado sem ninguém escolher quem é;
- que um motorista DESLIGADO continue entrando.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.motorista import entrada as ment

from .conftest import cadastrar, codigo_enviado

FONE = "5547999990001"
FONE_OUTRO = "5547999990002"
COD = "MOT-1"


# ------------------------------------------------------- a resposta uniforme

def test_pedido_responde_igual_para_numero_que_existe_e_que_nao_existe(esq, zap):
    cadastrar(esq, COD, FONE)

    conhecido = ment.pedir(FONE, esquema=esq)
    desconhecido = ment.pedir(FONE_OUTRO, esquema=esq)
    lixo = ment.pedir("nao é telefone", esquema=esq)

    assert conhecido == desconhecido == lixo
    assert conhecido["mensagem"] == ment.RESPOSTA_PEDIDO
    # e só o conhecido recebeu mensagem — a diferença existe no MUNDO, não na
    # resposta HTTP, que é o único lugar onde o desconhecido pode olhar
    assert len(zap) == 1
    assert zap[0]["telefone"] == FONE


def test_resposta_e_a_mesma_quando_o_envio_falha(esq, zap, monkeypatch):
    """WhatsApp desligado, teto do dia estourado, aparelho desconectado.

    Se a falha de envio mudasse a resposta, bastaria pedir num horário em que a
    casa está no teto para separar número cadastrado de número qualquer.
    """
    cadastrar(esq, COD, FONE)
    monkeypatch.setattr(ment.wa, "enviar",
                        lambda *a, **k: {"ok": False, "erro": "Envio DESLIGADO."})

    assert ment.pedir(FONE, esquema=esq)["mensagem"] == ment.RESPOSTA_PEDIDO
    assert ment.pedir(FONE_OUTRO, esquema=esq)["mensagem"] == ment.RESPOSTA_PEDIDO


def test_resposta_e_a_mesma_quando_a_configuracao_do_whatsapp_ESTOURA(esq, zap,
                                                                     monkeypatch):
    """`wa.enviar` tem contrato de nunca levantar — mas o que vem ANTES dele,
    ler a config da Z-API do banco local, pode. Uma exceção escapando daria 500
    para o número CADASTRADO e 200 para o desconhecido, e a resposta uniforme
    deixaria de ser uniforme exatamente no caso que ela protege."""
    cadastrar(esq, COD, FONE)

    def explode():
        raise RuntimeError("tabela zap_config não existe")

    monkeypatch.setattr(ment.zcfg, "ler", explode)

    conhecido = ment.pedir(FONE, esquema=esq)
    desconhecido = ment.pedir(FONE_OUTRO, esquema=esq)
    assert conhecido == desconhecido
    assert conhecido["mensagem"] == ment.RESPOSTA_PEDIDO


def test_freio_por_hora_nao_se_anuncia(esq, zap):
    cadastrar(esq, COD, FONE)
    respostas = [ment.pedir(FONE, esquema=esq) for _ in range(ment.MAX_PEDIDOS_HORA + 2)]

    assert all(r["mensagem"] == ment.RESPOSTA_PEDIDO for r in respostas), (
        "o freio anunciado é o próprio oráculo que a resposta uniforme fecha")
    assert len(zap) == ment.MAX_PEDIDOS_HORA, "o freio tem de FREAR de verdade"


def test_freio_por_ENDERECO_segura_o_volume_que_o_do_telefone_nao_segura(esq, zap):
    """O teto por telefone é de PESSOA; este é de SCRIPT. Sem ele, quem tivesse
    a lista de números pediria 3 para cada um, e a única coisa entre isso e
    centenas de mensagens seria o teto diário do WhatsApp da casa — que é uma
    proteção do número DELA, e que, gasto aqui, deixaria de valer para clientes
    e fornecedores no mesmo dia."""
    for i in range(ment.MAX_PEDIDOS_HORA_IP + 3):
        cadastrar(esq, f"MOT-{i}", f"55479999{i:05d}", nome=f"M{i}")
    for i in range(ment.MAX_PEDIDOS_HORA_IP + 3):
        r = ment.pedir(f"55479999{i:05d}", ip="203.0.113.7", esquema=esq)
        assert r["mensagem"] == ment.RESPOSTA_PEDIDO   # e nunca se anuncia

    assert len(zap) == ment.MAX_PEDIDOS_HORA_IP

    # de OUTRO endereço o freio não vale — senão um script derrubaria o app
    # para todo mundo, que é o oposto de proteger
    ment.pedir("5547999900000", ip="198.51.100.4", esquema=esq)
    assert len(zap) == ment.MAX_PEDIDOS_HORA_IP + 1


def test_numero_desconhecido_nao_deixa_rastro_na_tabela(esq, zap):
    """Gravar a tentativa faria `mot_codigos` virar a lista de quem tentou."""
    ment.pedir(FONE_OUTRO, esquema=esq)
    n = pglocal.um("SELECT count(*) AS n FROM mot_codigos", None, esq)["n"]
    assert n == 0


# ------------------------------------------------------------- o código

def test_o_codigo_nunca_e_gravado_em_claro(esq, zap):
    cadastrar(esq, COD, FONE)
    ment.pedir(FONE, esquema=esq)
    codigo = codigo_enviado(zap)

    linha = pglocal.um("SELECT * FROM mot_codigos", None, esq)
    guardado = " ".join(str(v) for v in linha.values())
    assert codigo not in guardado
    assert linha["codigo_hash"] != codigo and len(linha["codigo_hash"]) == 64


def test_codigo_certo_abre_sessao(esq, zap):
    cadastrar(esq, COD, FONE, nome="João da Silva")
    ment.pedir(FONE, esquema=esq)

    r = ment.confirmar(FONE, codigo_enviado(zap), aparelho="ap-1", esquema=esq)

    assert r["ok"] and r["motorista_codigo"] == COD and r["nome"] == "João da Silva"
    assert r["token"]
    viva = pglocal.um("SELECT * FROM mot_sessoes WHERE id = %(i)s",
                      {"i": r["sessao_id"]}, esq)
    assert viva["encerrada_em"] is None and viva["aparelho"] == "ap-1"


def test_codigo_errado_e_codigo_expirado_recusam_IGUAL(esq, zap):
    """Mensagens diferentes diriam a quem tenta em laço se vale continuar."""
    cadastrar(esq, COD, FONE)
    ment.pedir(FONE, esquema=esq)
    certo = codigo_enviado(zap)
    errado = "000000" if certo != "000000" else "111111"

    with pytest.raises(ment.Recusa) as e1:
        ment.confirmar(FONE, errado, esquema=esq)

    pglocal.executar("UPDATE mot_codigos SET expira_em = now() - interval '1 minute'",
                     None, esq)
    with pytest.raises(ment.Recusa) as e2:
        ment.confirmar(FONE, certo, esquema=esq)

    assert str(e1.value) == str(e2.value) == ment.RECUSA_CODIGO


def test_codigo_expirado_nao_entra(esq, zap):
    cadastrar(esq, COD, FONE)
    ment.pedir(FONE, esquema=esq)
    certo = codigo_enviado(zap)
    pglocal.executar("UPDATE mot_codigos SET expira_em = now() - interval '1 minute'",
                     None, esq)
    with pytest.raises(ment.Recusa):
        ment.confirmar(FONE, certo, esquema=esq)


def test_tentativas_tem_teto_e_matam_o_codigo(esq, zap):
    cadastrar(esq, COD, FONE)
    ment.pedir(FONE, esquema=esq)
    certo = codigo_enviado(zap)
    errado = "000000" if certo != "000000" else "111111"

    for _ in range(ment.MAX_TENTATIVAS):
        with pytest.raises(ment.Recusa):
            ment.confirmar(FONE, errado, esquema=esq)

    # passado o teto, nem o código CERTO entra — senão o teto seria um atraso,
    # não um limite
    with pytest.raises(ment.Recusa):
        ment.confirmar(FONE, certo, esquema=esq)


def test_usar_o_codigo_invalida_os_outros_em_aberto(esq, zap):
    cadastrar(esq, COD, FONE)
    ment.pedir(FONE, esquema=esq)
    primeiro = codigo_enviado(zap)
    ment.pedir(FONE, esquema=esq)
    segundo = codigo_enviado(zap)

    ment.confirmar(FONE, segundo, esquema=esq)
    with pytest.raises(ment.Recusa):
        ment.confirmar(FONE, primeiro, esquema=esq)


# --------------------------------------------------- telefone compartilhado

def test_telefone_de_dois_motoristas_pede_escolha_sem_queimar_o_codigo(esq, zap):
    """5 casos em 585 medidos. Queimar o código para perguntar quem é obrigaria
    a pedir outro só por dividir o aparelho com um colega."""
    cadastrar(esq, "MOT-A", FONE, nome="Ana")
    cadastrar(esq, "MOT-B", FONE, nome="Bruno")
    ment.pedir(FONE, esquema=esq)
    certo = codigo_enviado(zap)

    r = ment.confirmar(FONE, certo, esquema=esq)
    assert "token" not in r
    assert {m["nome"] for m in r["escolher"]} == {"Ana", "Bruno"}

    # o MESMO código ainda vale, e agora com o escolhido
    r2 = ment.confirmar(FONE, certo, motorista="MOT-B", esquema=esq)
    assert r2["ok"] and r2["motorista_codigo"] == "MOT-B" and r2["nome"] == "Bruno"


def test_nao_da_para_escolher_motorista_de_outro_telefone(esq, zap):
    """O parâmetro vem do navegador. Aceitá-lo sem conferir contra o telefone
    que acabou de provar o código seria trocar de identidade digitando."""
    cadastrar(esq, "MOT-A", FONE, nome="Ana")
    cadastrar(esq, "MOT-Z", FONE_OUTRO, nome="Zeca")
    ment.pedir(FONE, esquema=esq)

    with pytest.raises(ment.Recusa):
        ment.confirmar(FONE, codigo_enviado(zap), motorista="MOT-Z", esquema=esq)


# ------------------------------------------------------------ desligamento

def test_desligado_nao_recebe_codigo_nem_entra(esq, zap):
    cadastrar(esq, COD, FONE, ativo=False)

    assert ment.pedir(FONE, esquema=esq)["mensagem"] == ment.RESPOSTA_PEDIDO
    assert zap == [], "vínculo inativo não é destinatário"


def test_desligamento_entre_o_pedido_e_a_confirmacao(esq, zap):
    """Aqui a pessoa PROVOU quem é, então a recusa é legível e diferente:
    esconder o motivo só a faria tentar de novo para sempre."""
    cadastrar(esq, COD, FONE)
    ment.pedir(FONE, esquema=esq)
    certo = codigo_enviado(zap)
    pglocal.executar("UPDATE mot_vinculos SET ativo = false", None, esq)

    with pytest.raises(ment.Recusa) as e:
        ment.confirmar(FONE, certo, esquema=esq)
    assert "torre" in str(e.value).lower()
    assert str(e.value) != ment.RECUSA_CODIGO
