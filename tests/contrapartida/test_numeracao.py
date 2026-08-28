# tests/contrapartida/test_numeracao.py
"""A numeracao do CT-e nao se repete — e agora quem garante e o BANCO.

O QUE ESTAVA ABERTO
===================
`proximo_numero` lia `max(numero)` numa transacao curta e o `INSERT` do
resultado acontecia em OUTRA, depois de uma chamada SOAP de segundos. Sem lock,
sem sequence e sem restricao: duas execucoes simultaneas liam o mesmo maximo e
escolhiam o mesmo numero.

E nao pararia em "numero repetido". O codigo numerico da chave (cNF) NAO e
aleatorio — a biblioteca o calcula como soma dos campos anteriores —, entao o
mesmo emitente, serie, numero e mes produzem a MESMA chave de 44 digitos, bit a
bit. Numero colidido e chave colidida, garantida.

Estes testes vao ao banco DE VERDADE, com threads de verdade: a corrida so se
prova acontecendo. Sem banco, pulam dizendo por que (fixture do diretorio).
"""
from __future__ import annotations

import threading

import pytest

from api.contrapartida import emissao


def _reserva(cnpj="11111111111111", serie=900, ambiente="1", origem="orig"):
    return emissao.reservar_numero(cnpj, serie, ambiente, "teste", origem)


# --- a corrida ---------------------------------------------------------------

def test_reservas_SEQUENCIAIS_nunca_repetem():
    nums = [_reserva()[1] for _ in range(5)]
    assert nums == [1, 2, 3, 4, 5]


def test_reservas_SIMULTANEAS_nunca_repetem(esquema_pg, monkeypatch):
    """O teste que a suite nao tinha: 12 threads reservando ao mesmo tempo.

    Antes da reserva, todas liam o mesmo `max(numero)` e escolhiam o mesmo
    numero. Agora o indice parcial `ux_emissao_numero` recusa a segunda, e
    quem perde pega a proxima — antes de montar e antes de assinar.
    """
    from api.contrapartida import cadastro
    monkeypatch.setattr(cadastro, "ESQUEMA", esquema_pg)

    N = 12
    achados: list[int] = []
    erros: list[Exception] = []
    trava = threading.Lock()
    largada = threading.Event()

    def corre():
        largada.wait()
        try:
            _, numero = _reserva()
            with trava:
                achados.append(numero)
        except Exception as exc:  # noqa: BLE001
            with trava:
                erros.append(exc)

    fios = [threading.Thread(target=corre) for _ in range(N)]
    for f in fios:
        f.start()
    largada.set()          # todas partem juntas
    for f in fios:
        f.join(timeout=30)

    assert not erros, f"reserva falhou: {erros[:3]}"
    assert len(achados) == N
    assert len(set(achados)) == N, f"NUMERO REPETIDO: {sorted(achados)}"
    assert sorted(achados) == list(range(1, N + 1)), "a serie ficou com buraco"


def test_o_banco_RECUSA_numero_repetido_mesmo_por_fora():
    """O indice e a garantia, nao a boa vontade de quem chama."""
    import psycopg
    _reserva()
    with pytest.raises(psycopg.errors.UniqueViolation):
        with emissao._conn() as c:
            c.execute(
                "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente,"
                " serie, numero, chave_origem)"
                " VALUES('2099-01-01T10:00','t','1','11111111111111',900,1,'o')")


def test_numeracao_e_por_EMITENTE_e_por_AMBIENTE():
    """Cada agregado emite na propria serie 900, e producao nao herda numero
    gasto em homologacao. Por isso varios documentos "900/1" convivem."""
    assert _reserva(cnpj="11111111111111")[1] == 1
    assert _reserva(cnpj="22222222222222")[1] == 1
    assert _reserva(cnpj="11111111111111", ambiente="2")[1] == 1
    assert _reserva(cnpj="11111111111111")[1] == 2


# --- o que o numero reservado significa --------------------------------------

def test_falha_ANTES_de_transmitir_DEVOLVE_o_numero():
    """Nada saiu da maquina: queimar numeracao por cadastro incompleto
    encheria a serie de buracos para inutilizar depois."""
    ident, numero = _reserva()
    assert numero == 1
    emissao.liberar_reserva(ident)
    assert _reserva()[1] == 1, "o numero deveria ter voltado para a fila"


def test_falha_DEPOIS_de_transmitir_NAO_devolve_o_numero():
    """Este e o buraco que a auditoria apontou: um timeout depois de a SEFAZ
    receber deixava o documento orfao e o numero livre. Reusa-lo criaria uma
    segunda chave identica a de um documento que talvez exista."""
    ident, numero = _reserva()
    emissao._sem_retorno(ident, TimeoutError("a SEFAZ nao respondeu"))

    assert _reserva()[1] == numero + 1, "o numero NAO pode voltar para a fila"
    pend = emissao.sem_retorno()
    assert len(pend) == 1 and pend[0]["numero"] == numero
    assert "SEM RETORNO" in pend[0]["xmotivo"]
    assert "portal" in pend[0]["xmotivo"], "tem de dizer o que fazer"


def test_reserva_em_voo_nao_aparece_como_pendencia():
    """`sem_retorno` e a fila que precisa de GENTE. Uma reserva que acabou de
    nascer esta em voo, nao parada."""
    _reserva()
    assert emissao.sem_retorno() == []


def test_reserva_fica_FORA_das_contagens_de_transmissao():
    """Numero reservado nao e tentativa nem documento: contar como recusa
    afundaria a taxa de acerto com trabalho que nem chegou a acontecer."""
    _reserva()
    t = emissao.totais()
    assert t["documentos"] == 0 and t["autorizados"] == 0


# --- numero informado a mao ---------------------------------------------------

def test_numero_FIXO_ja_usado_e_recusado_ANTES_de_assinar():
    """Os scripts de operacao passam `numero=`. A recusa tem de vir aqui, com
    uma frase que diz o que aconteceu — nao como rejeicao 539 depois de o
    documento ter sido assinado em nome de outra empresa."""
    _reserva()
    with pytest.raises(ValueError, match="já foi usado"):
        emissao._reservar_numero_fixo("11111111111111", 900, "1", "t", "o", 1)


def test_numero_fixo_livre_e_aceito():
    ident = emissao._reservar_numero_fixo("11111111111111", 900, "1", "t", "o", 77)
    assert ident
    assert _reserva()[1] == 78, "o proximo automatico respeita o que foi fixado"


# --- cancelamento reusa a numeracao, e o indice tem de deixar -----------------

def test_o_evento_de_CANCELAMENTO_reusa_serie_e_numero():
    """O evento entra como linha propria, na mesma numeracao do documento que
    derruba. Um indice que incluisse essas linhas faria TODO cancelamento
    falhar — por isso ele e parcial."""
    ident, numero = _reserva()
    emissao._concluir(ident, "CH-A", {"cStat": "100", "xMotivo": "ok",
                                      "protocolo": "p1"},
                      "<xml/>", "<prot/>", "t", "11111111111111", "1", 900,
                      numero)
    with emissao._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo)"
            " VALUES('2099-01-02T10:00','t','1','11111111111111',900,%s,'CH-A',"
            " 'o','CANC:135','evento registrado')", (numero,))
    assert emissao._autorizado_para("orig", "1") is None, "cancelado nao vale"


def test_transmitir_RESERVA_antes_de_montar():
    """A ordem e o ponto: reservar depois de montar deixaria a janela de
    corrida exatamente onde ela estava."""
    import inspect
    fonte = inspect.getsource(emissao.transmitir)
    assert fonte.index("reservar_numero(") < fonte.index("documento.montar(")
    # e a idempotencia continua ANTES da reserva: barrar depois ja teria
    # gasto um numero
    assert fonte.index("_autorizado_para(") < fonte.index("reservar_numero(")
