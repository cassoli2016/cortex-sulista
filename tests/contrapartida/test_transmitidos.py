# tests/contrapartida/test_transmitidos.py
"""Painel dos CT-e ja transmitidos.

Esta tela existe para NAO somar o que nao se soma. Cada teste aqui trava uma
das tres separacoes: autorizado x valendo, homologacao x producao, recusado x
documento. Errar qualquer uma produz um numero que nao existe em lugar nenhum —
e que alguem levaria para uma reuniao.
"""
from __future__ import annotations

import pytest

from api.contrapartida import emissao, transmitidos

_XML = ('<?xml version="1.0"?><CTe><infCte><vPrest>'
        '<vTPrest>{v}</vTPrest><vRec>{v}</vRec></vPrest></infCte></CTe>')
_PROT = "<protCTe><infProt><nProt>135</nProt></infProt></protCTe>"


def _grava(chave, *, ambiente="1", cstat="100", numero=1, valor="100.00",
           cnpj="11111111111111", quando="2099-01-01T10:00:00", com_xml=True,
           origem=None):
    with transmitidos._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo, protocolo, xml,"
            " xml_prot) VALUES(%s,'t',%s,%s,900,%s,%s,%s,%s,'m','p',%s,%s)",
            (quando, ambiente, cnpj, numero, chave,
             origem or ("orig-" + chave), cstat,
             _XML.format(v=valor) if com_xml else None,
             _PROT if com_xml else None))


def _cancela(chave, *, ambiente="1", numero=1, cnpj="11111111111111"):
    with transmitidos._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo)"
            " VALUES('2099-01-02T10:00:00','t',%s,%s,900,%s,%s,'o','CANC:135',"
            " 'evento registrado')", (ambiente, cnpj, numero, chave))


# --- autorizado NAO e valendo -----------------------------------------------

def test_cancelado_sai_de_TODO_total():
    """A linha original guarda cstat='100' para sempre — e o que a SEFAZ
    respondeu na hora. Conta-la como documento vigente infla o numero e some
    com o cancelamento, que e justamente o evento que alguem quer ver."""
    _grava("viva", numero=1, valor="500.00")
    _grava("morta", numero=2, valor="900.00")
    _cancela("morta", numero=2)

    k = transmitidos.painel()["kpis"]
    assert k["validos"] == 1
    assert k["valor_valido"] == 500.0
    assert k["cancelados"] == 1


def test_cancelado_ainda_APARECE_na_lista_com_o_selo():
    """Sair dos totais nao e sumir: quem procura "o que aconteceu com aquele
    documento" precisa encontra-lo."""
    _grava("morta", numero=1)
    _cancela("morta", numero=1)
    docs = transmitidos.painel()["documentos"]
    assert [d["cancelado"] for d in docs] == [True]


# --- homologacao NAO soma com producao --------------------------------------

def test_homologacao_fora_dos_totais_de_producao():
    """Documento de teste nao tem valor fiscal e nao e escriturado."""
    _grava("prod", ambiente="1", numero=1, valor="100.00")
    _grava("homo", ambiente="2", numero=1, valor="999.00", cnpj="22222222222222")

    k = transmitidos.painel()["kpis"]
    assert k["validos"] == 1 and k["valor_valido"] == 100.0
    assert k["autorizados_homo"] == 1


def test_a_MESMA_chave_em_dois_ambientes_nao_marca_o_teste_como_enviado():
    """A chave de 44 digitos NAO carrega o ambiente, e o cNF e deterministico:
    o mesmo emitente, serie e numero no mesmo mes gera a MESMA chave em
    homologacao e em producao. Sem separar, a linha de teste aparecia na tela
    como "XML enviado a contabilidade" por casar com a chave do documento
    real."""
    _grava("MESMA-CHAVE", ambiente="1", numero=1)
    _grava("MESMA-CHAVE", ambiente="2", numero=1, origem="outra-origem")
    with transmitidos._conn() as c:
        c.execute("INSERT INTO cte_xml_email(chave, ok, tentativas)"
                  " VALUES('MESMA-CHAVE', true, 1)")

    docs = {(d["ambiente"], d["xml_enviado"])
            for d in transmitidos.painel()["documentos"]}
    assert ("1", True) in docs, "producao deveria constar como enviada"
    assert ("2", None) in docs, "homologacao NUNCA entra na fila da contabilidade"


# --- recusado nao emitiu nada -----------------------------------------------

def test_recusado_conta_como_TENTATIVA_e_nunca_como_documento():
    _grava("ok", numero=1, valor="100.00")
    _grava("nao", numero=2, cstat="229", valor="700.00")

    k = transmitidos.painel()["kpis"]
    assert k["validos"] == 1 and k["valor_valido"] == 100.0
    assert k["tentativas_prod"] == 2 and k["autorizados_prod"] == 1
    assert k["taxa_prod"] == 50.0


def test_a_748_sai_do_denominador_da_taxa_de_homologacao():
    """Ela diz que o CT-e de origem nao consta na base de teste — e nunca vai
    constar, porque foi autorizado em producao. Deixa-la dentro faria o periodo
    de teste medir o AMBIENTE em vez do trabalho."""
    _grava("h1", ambiente="2", numero=1)
    _grava("h2", ambiente="2", numero=2, cstat="748")

    k = transmitidos.painel()["kpis"]
    assert k["esperadas_homo"] == 1
    # 1 autorizada sobre 1 avaliada (a 748 saiu dos dois lados)
    assert k["taxa_homo"] == 100.0


def test_sem_tentativa_a_taxa_e_None_e_nao_zero():
    """"0% de acerto" sem nenhuma tentativa e um numero que acusa alguem."""
    assert transmitidos.painel()["kpis"]["taxa_prod"] is None


# --- numeracao ---------------------------------------------------------------

def test_buraco_na_faixa_e_numero_que_SUMIU_do_registro():
    """Nao e o mesmo que recusado: o recusado continua registrado. Buraco so
    acontece quando a transmissao falha ANTES de ser gravada — e ai o documento
    pode ter chegado a SEFAZ mesmo assim."""
    _grava("a", numero=1)
    _grava("c", numero=3)          # o 2 nunca foi gravado
    emi = transmitidos.painel()["por_emitente"]
    assert len(emi) == 1
    assert emi[0]["n_de"] == 1 and emi[0]["n_ate"] == 3
    assert emi[0]["buracos"] == 1

    av = " ".join(a["texto"] for a in transmitidos.painel()["alertas"])
    assert "SUMIRAM" in av


def test_faixa_sem_buraco_nao_gera_alerta():
    _grava("a", numero=1)
    _grava("b", numero=2)
    assert transmitidos.painel()["por_emitente"][0]["buracos"] == 0


def test_emitentes_diferentes_no_MESMO_numero_nao_e_duplicidade():
    """A numeracao e por emitente: o primeiro documento de cada agregado e o
    900/1. Foi essa leitura que fez o "900/1 tres vezes" parecer defeito."""
    _grava("a", numero=1, cnpj="11111111111111")
    _grava("b", numero=1, cnpj="22222222222222")
    emi = transmitidos.painel()["por_emitente"]
    assert len(emi) == 2
    assert all(r["buracos"] == 0 for r in emi)
    assert transmitidos.painel()["kpis"]["emitentes"] == 2


# --- valor -------------------------------------------------------------------

def test_o_valor_sai_do_vTPrest_e_nao_do_vRec():
    """Os dois tem o mesmo valor hoje; ancorar na tag errada daria um total
    certo por acidente, que e pior que um errado."""
    _grava("a", numero=1, valor="1234.56")
    assert transmitidos.painel()["kpis"]["valor_valido"] == 1234.56


def test_documento_sem_XML_guardado_nao_derruba_o_total():
    """Sem arquivo nao ha valor a somar, mas o documento existe e precisa
    aparecer — inclusive no alerta, porque falta o que a contabilidade importa."""
    _grava("com", numero=1, valor="100.00")
    _grava("sem", numero=2, com_xml=False)

    p = transmitidos.painel()
    assert p["kpis"]["validos"] == 2
    assert p["kpis"]["valor_valido"] == 100.0
    assert p["kpis"]["sem_arquivo"] == 1
    assert any("SEM o XML" in a["texto"] for a in p["alertas"])


# --- robustez ---------------------------------------------------------------

def test_falha_de_leitura_devolve_o_TIPO_e_nao_o_texto(monkeypatch):
    """A mensagem do psycopg pode trazer o conninfo. E a tela nao pode dar 500:
    e nela que se olha justamente quando algo nao esta indo."""
    def explode():
        raise RuntimeError("senha=segredo host=1.2.3.4")
    monkeypatch.setattr(transmitidos, "_conn", explode)
    p = transmitidos.painel()
    assert p["erro"] == "RuntimeError"
    assert "segredo" not in str(p)
    assert p["kpis"] == {} and p["documentos"] == []


def test_a_janela_recorta_a_LISTA_e_nao_os_totais():
    """Recorte de lista virando total foi o defeito que a tela de conciliacao
    ja teve ("5 de 30 autorizadas" quando eram 30 em 99)."""
    _grava("velha", numero=1, quando="2000-01-01T10:00:00")
    _grava("nova", numero=2, quando="2099-01-01T10:00:00")

    p = transmitidos.painel(dias=30)
    assert [d["chave"] for d in p["documentos"]] == ["nova"]
    assert p["kpis"]["validos"] == 2, "os cartoes leem o registro INTEIRO"


def test_lista_de_cancelamento_vem_de_emissao():
    """Uma segunda definicao de "cancelado" na casa acabaria divergindo — e a
    que divergisse contaria documento morto como vigente."""
    import inspect
    assert "emissao.CANCELAMENTOS" in inspect.getsource(transmitidos.painel)


# --- numero consumido sem retorno da SEFAZ ----------------------------------

def test_numero_SEM_RETORNO_aparece_no_painel_e_no_alerta():
    """E a unica pendencia desta tela que nao se resolve sozinha: o documento
    partiu, a resposta nao voltou, e ele PODE estar autorizado no orgao sem
    estar aqui. Some da vista = numero consumido que ninguem confere."""
    _grava("ok", numero=1)
    with transmitidos._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave_origem, xmotivo)"
            " VALUES('2099-01-01T11:00','t','1','11111111111111',900,2,'o2',"
            " 'SEM RETORNO DA SEFAZ (TimeoutError) — confira no portal')")

    p = transmitidos.painel()
    assert p["kpis"]["sem_retorno"] == 1
    assert p["kpis"]["validos"] == 1, "reserva nao e documento"
    assert any("SEM retorno" in a["texto"] for a in p["alertas"])


def test_reserva_EM_VOO_nao_conta_como_sem_retorno():
    """Uma reserva que acabou de nascer esta em voo, nao parada — acusa-la
    faria a tela gritar durante cada emissao normal."""
    with transmitidos._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave_origem, xmotivo)"
            " VALUES('2099-01-01T11:00','t','1','11111111111111',900,1,'o',"
            " 'reservado')")
    assert transmitidos.painel()["kpis"]["sem_retorno"] == 0
