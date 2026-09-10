# -*- coding: utf-8 -*-
"""O JavaScript do painel COMPILA — e falha em um segundo quando não compila.

POR QUE ISTO EXISTE
===================
Em 10/09/2026 uma edição no `index.html` declarou `let freqBatSeq` duas vezes.
O arquivo tem um único bloco de script de 2 MB: um `SyntaxError` em qualquer
linha dele **não carrega nada** — `abaTrocar is not defined`, o login não some
da tela, o painel inteiro morre. É o mesmo modo de falha da lição de TDZ que a
casa já conhece, e a causa é sempre trivial.

O defeito FOI pego, mas pela régua de altura: `medir_paineis.py` estourou com
um stack trace de Playwright de dez linhas apontando para
`Page.evaluate: ReferenceError`. Levou minutos para virar diagnóstico, e a
régua não existe para isso — ela mede altura.

Aqui a mesma coisa falha em ~1 s dizendo `Identifier 'x' has already been
declared` e a linha. `node --check` só compila: não executa nada da página.

SEM NODE, O TESTE É PULADO — nunca falha por ausência de ferramenta, e nunca
finge que passou.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
HTML = RAIZ / "api" / "static" / "index.html"

#: Só blocos INLINE: `<script src=...>` é arquivo vendorizado, e conferir a
#: sintaxe do ECharts a cada rodada não diz nada sobre o nosso código.
_BLOCO = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


def _blocos() -> list[str]:
    s = io.open(HTML, encoding="utf-8").read()
    return [b for b in _BLOCO.findall(s) if len(b.strip()) > 50]


@pytest.fixture(scope="module")
def node() -> str:
    caminho = shutil.which("node")
    if not caminho:
        pytest.skip("node não encontrado no PATH")
    return caminho


def test_a_varredura_acha_o_script_do_painel():
    """O painel tem um bloco gigante (~2 MB). Se a regex parar de casar, todo
    teste daqui vira verde-para-sempre."""
    blocos = _blocos()
    assert blocos, "nenhum <script> inline encontrado — a regex envelheceu"
    assert max(len(b) for b in blocos) > 500_000, (
        "o bloco principal do painel não foi encontrado; a varredura está "
        "olhando para outra coisa")


def test_todo_script_inline_do_painel_COMPILA(node):
    """Um `SyntaxError` em qualquer linha derruba o arquivo inteiro — não é
    'aquela função para de funcionar', é o painel não abrir."""
    for i, bloco in enumerate(_blocos()):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(bloco)
            caminho = f.name
        try:
            r = subprocess.run([node, "--check", caminho], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
        finally:
            os.unlink(caminho)
        assert r.returncode == 0, (
            f"o bloco de script #{i} do index.html NÃO compila — o painel não "
            f"abre com isto:\n\n{(r.stderr or '')[:900]}")
