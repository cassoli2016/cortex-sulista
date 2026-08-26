"""Parser do extrato em PDF (hoje só o layout do Banco C6).

Os testes atacam `_parse_c6`, que recebe o TEXTO já extraído, e não o PDF
binário. É de propósito: o que pode quebrar e precisa de rede de segurança é o
recorte de coluna e a convenção de número; a extração em si é uma chamada de
uma linha ao pypdf, e gerar PDF de mentira no teste exigiria uma dependência de
ESCRITA de PDF que o projeto não tem e não precisa.

O texto das fixtures é o do arquivo real de agosto/2026 em modo `layout`,
com o alinhamento de coluna preservado e os valores trocados.
"""
from __future__ import annotations

import pytest

from api.extrato.parser_pdf import _parse_c6, parse_pdf

CABECALHO = """
Sistema de Conta Corrente
                                    REL. DE EXTRATO PERIÓDICO PARA CORRENTISTA

BANCO C6 S.A.                                        ABERTO              DR:   26/08/2026

Agência:    0001                 Conta:    000034988068-9          Situação:  LIBERADA

TRANSPORTADORA SULISTA S/A                                          76.104.397/0001-23

 DATA.     DESCRIÇÃO                                                        DOC
"""


def _mov(dt: str, desc: str, valor: str, dc: str) -> str:
    return f"{dt} {desc:<70}          000000000000              {valor}   {dc}"


def _saldo(dt: str, rotulo: str, valor: str) -> str:
    return f"{dt} {rotulo:<100}                          {valor}"


# O trecho real de 03/08 a 07/08: a cadeia de saldo fecha em 0,01 / 0,01 /
# 0,02 / 0,11 justamente porque a aplicação automática devolve centavos.
C6_REAL = CABECALHO + "\n".join([
    _saldo("31/07/2026", "SALDO DISPONIVEL INICIAL", "0,00"),
    _saldo("31/07/2026", "SALDO VINCULADO INICIAL", "0,00"),
    _saldo("31/07/2026", "SALDO BLOQUEADO INICIAL", "0,00"),
    _mov("03/08/2026", "PIX RECEBIDO-TRANSPORTADORA SULISTA", "200,000.00", "C"),
    _mov("03/08/2026", "APLIC. EM  COMPROMI.", "199,999.99", "D"),
    _saldo("03/08/2026", "SALDO DISPONIVEL", "0,01"),
    _mov("04/08/2026", "PIX RECEBIDO-TRANSPORTADORA SULISTA", "200,000.00", "C"),
    _mov("04/08/2026", "APLIC. EM  COMPROMI.", "200,000.00", "D"),
    _saldo("04/08/2026", "SALDO DISPONIVEL", "0,01"),
    _mov("06/08/2026", "PIX RECEBIDO-TRANSPORTADORA SULISTA S/A", "200,000.00", "C"),
    _mov("06/08/2026", "APLIC. EM  COMPROMI.", "199,999.99", "D"),
    _saldo("06/08/2026", "SALDO DISPONIVEL", "0,02"),
    _mov("07/08/2026", "RESG.COMPROMISSADA", "260,000.09", "C"),
    _mov("07/08/2026", "ENVIO DE TED CLI-TRANSPORTADORA SULISTA S/A", "260,000.00", "D"),
    _saldo("07/08/2026", "SALDO DISPONIVEL", "0,11"),
])


def test_le_a_conta_do_cabecalho():
    d = _parse_c6(C6_REAL)
    assert d["banco"] == 336
    assert d["agencia"] == "0001"
    assert d["conta"] == "000034988068-9"
    assert d["ident"] == "336/0001/000034988068-9"


def test_separa_movimento_de_linha_de_saldo():
    d = _parse_c6(C6_REAL)
    assert len(d["itens"]) == 8
    assert d["linhas_saldo"] == 7
    assert d["ignoradas"] == 0


def test_o_sinal_vem_da_coluna_dc_e_nao_do_numero():
    """No C6 o valor é sempre positivo; quem manda é o D/C do fim da linha —
    o inverso do OFX, onde o sinal do TRNAMT é a fonte da verdade."""
    d = _parse_c6(C6_REAL)
    por_hist = {i["historico"]: i for i in d["itens"]}
    assert por_hist["APLIC. EM COMPROMI."]["valor"] == pytest.approx(-199999.99)
    assert por_hist["APLIC. EM COMPROMI."]["tipo"] == "D"
    pix = [i for i in d["itens"] if i["historico"].startswith("PIX")][0]
    assert pix["valor"] == pytest.approx(200000.00)
    assert pix["tipo"] == "C"


def test_movimento_en_us_e_saldo_pt_br_no_mesmo_arquivo():
    """`200,000.00` são duzentos mil e `0,01` é um centavo, a duas linhas de
    distância. Ler tudo como pt-BR (o que o `valor_br` do parser CSV faria)
    devolveria `None` e descartaria TODO movimento do arquivo."""
    d = _parse_c6(C6_REAL)
    assert max(i["valor"] for i in d["itens"]) == pytest.approx(260000.09)
    assert d["saldos"][1] == {"dt": "2026-08-03", "saldo": 0.01, "origem": "linha"}


def test_so_o_saldo_disponivel_vira_ancora():
    """Vinculado e bloqueado caem no MESMO dia; tratá-los como saldo da conta
    sobrescreveria o número comparável pelo que não é."""
    d = _parse_c6(C6_REAL)
    assert [s["dt"] for s in d["saldos"]] == [
        "2026-07-31", "2026-08-03", "2026-08-04", "2026-08-06", "2026-08-07"]
    assert d["saldos"][0]["saldo"] == 0.0


def test_a_cadeia_de_saldo_fecha():
    d = _parse_c6(C6_REAL)
    assert d["conferencia"]["fecha"] is True
    assert d["conferencia"]["desvios"] == []
    assert d["conferencia"]["dias"] == 4


def test_cadeia_que_nao_fecha_e_reportada_e_nao_engolida():
    """É o sinal de que o layout mudou. O dado continua vindo — com o desvio
    junto — porque decidir por conta própria descartar um extrato inteiro é
    pior do que mostrar o número e o aviso."""
    quebrado = C6_REAL.replace(
        _saldo("07/08/2026", "SALDO DISPONIVEL", "0,11"),
        _saldo("07/08/2026", "SALDO DISPONIVEL", "999,99"))
    d = _parse_c6(quebrado)
    assert d["conferencia"]["fecha"] is False
    assert len(d["conferencia"]["desvios"]) == 1
    dv = d["conferencia"]["desvios"][0]
    assert dv["dt"] == "2026-08-07"
    assert dv["esperado"] == pytest.approx(0.11)
    assert dv["no_extrato"] == pytest.approx(999.99)
    assert len(d["itens"]) == 8, "os lançamentos continuam disponíveis"


def test_saldo_singular_e_a_ultima_posicao():
    """Contrato que o serviço de importação já conhece do parser OFX."""
    d = _parse_c6(C6_REAL)
    assert d["saldo"] == {"dt": "2026-08-07", "saldo": 0.11}


def test_sem_fitid_de_mentira():
    """PDF não tem identificador de transação; inventar um criaria a ilusão de
    unicidade justamente na chave de deduplicação."""
    d = _parse_c6(C6_REAL)
    assert all(i["fitid"] is None for i in d["itens"])


def test_cabecalho_sem_agencia_e_conta_e_recusado():
    sem = C6_REAL.replace("Agência:    0001                 Conta:    000034988068-9", "")
    with pytest.raises(ValueError, match="agência/conta"):
        _parse_c6(sem)


def test_layout_desconhecido_e_recusado_com_motivo(monkeypatch):
    """Melhor recusar do que adivinhar coluna de um banco nunca visto: PDF não
    tem estrutura, só posição de glifo, e um palpite errado lança dinheiro na
    conciliação sem avisar."""
    monkeypatch.setattr("api.extrato.parser_pdf._texto",
                        lambda _b: "BANCO QUALQUER OUTRO S.A.\n01/08/2026 ALGO 10,00")
    with pytest.raises(ValueError, match="layout não reconhecido"):
        parse_pdf(b"%PDF-1.7")


def test_pdf_sem_texto_avisa_que_e_digitalizacao(monkeypatch):
    """PDF escaneado abre e tem páginas — só não tem texto. Sem esta checagem
    ele cairia em "layout não reconhecido", mandando o usuário procurar um
    defeito de layout quando o problema é que não há o que ler."""
    class _PaginaVazia:
        def extract_text(self, extraction_mode=""):
            return ""

    class _LeitorDeImagem:
        def __init__(self, _fp):
            self.pages = [_PaginaVazia(), _PaginaVazia()]

    monkeypatch.setattr("pypdf.PdfReader", _LeitorDeImagem)
    with pytest.raises(ValueError, match="digitalização"):
        parse_pdf(b"%PDF-1.7")


def test_arquivo_que_nao_e_pdf():
    with pytest.raises(ValueError, match="Não foi possível ler o PDF"):
        parse_pdf(b"isto nao e um pdf")
