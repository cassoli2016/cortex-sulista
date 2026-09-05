# -*- coding: utf-8 -*-
"""Nenhum byte de controle invisível no código.

O GUARD DE UM DEFEITO QUE ME PEGOU TRÊS VEZES NO MESMO DIA. Um `\\b` escrito
numa regex acabou virando o byte 0x08 (backspace) DENTRO do arquivo — engolido
por uma camada de shell no caminho. O estrago é específico e cruel:

    pattern: '^\\s*\\w+\\W{0,3}(\\d{3,12})\\x08'

Impresso, ele parece idêntico ao padrão certo. `repr()` no terminal não
destaca. O diff do git mostra a linha como igual. E a regex simplesmente não
casa com nada — a funcionalidade fica morta sem erro nenhum, e a conclusão
natural é que a LÓGICA está errada. Foram três tentativas de conserto na
lógica antes de alguém olhar os bytes.

O QUE É PERMITIDO. Tabulação, quebra de linha e o CR do CRLF do Windows são
normais. Um `\\x01` legítimo existe dentro de um intervalo de caracteres numa
regex do SQL (`'[^\\x01-\\xff]'`) e está no repositório desde antes — ele é
declarado abaixo, com o motivo, em vez de a varredura ser afrouxada.
"""
from __future__ import annotations

import pathlib

import pytest

#: CR (13) é o fim de linha do Windows; tab (9) e LF (10) são texto normal.
PERMITIDOS = {9, 10, 13}

#: As exceções conhecidas, uma a uma e com motivo. Lista curta de propósito:
#: quem precisar acrescentar a próxima escreve por que ela não é engano.
EXCECOES = {
    # Intervalo de caracteres numa regex do PostgreSQL que tira acentuação da
    # descrição da conta: `regexp_replace(..., '[^\x01-\xff]', '-', 'g')`.
    "api/queries.py": {1},
}


def _arquivos():
    raiz = pathlib.Path(__file__).resolve().parent.parent
    for padrao in ("api/**/*.py", "api/**/*.html", "api/**/*.js",
                   "scripts/**/*.py", "tests/**/*.py", "sql/**/*.sql"):
        for f in raiz.glob(padrao):
            yield raiz, f


def test_nenhum_byte_de_controle_invisivel_no_codigo():
    achados = []
    for raiz, f in _arquivos():
        rel = f.relative_to(raiz).as_posix()
        permitidos = PERMITIDOS | EXCECOES.get(rel, set())
        b = f.read_bytes()
        ruins = sorted({x for x in b if x < 32 and x not in permitidos})
        if ruins:
            # ONDE, e não só QUE: sem a linha, achar um caractere invisível
            # num arquivo de 9.000 linhas é o próprio problema outra vez.
            pos = next(i for i, x in enumerate(b) if x in ruins)
            achados.append("%s:%d byte %s"
                           % (rel, b[:pos].count(b"\n") + 1,
                              " ".join(hex(x) for x in ruins)))
    assert not achados, (
        "byte de controle invisível — quase sempre um `\\b` ou `\\n` engolido "
        "por uma camada de shell na hora de escrever o arquivo: %s" % achados)


def test_o_guard_ACENDE_com_um_backspace(tmp_path):
    """Verde que nunca ficaria vermelho não conferiu nada. Este prova que a
    varredura enxerga exatamente o byte que causou o defeito."""
    alvo = tmp_path / "exemplo.py"
    alvo.write_bytes(b'RE = re.compile(r"^sair\\d+\x08")\n')
    b = alvo.read_bytes()
    ruins = {x for x in b if x < 32 and x not in PERMITIDOS}
    assert ruins == {8}


def test_a_lista_de_excecoes_e_VERDADEIRA():
    """Exceção que não corresponde a nada é exceção esquecida — e ela afrouxa
    a varredura para sempre, calada."""
    raiz = pathlib.Path(__file__).resolve().parent.parent
    for rel, bytes_ok in EXCECOES.items():
        f = raiz / rel
        assert f.exists(), "exceção para arquivo que não existe: %s" % rel
        presentes = {x for x in f.read_bytes() if x < 32}
        sobrando = bytes_ok - presentes
        assert not sobrando, ("exceção desnecessária em %s: %s" %
                              (rel, [hex(x) for x in sobrando]))
