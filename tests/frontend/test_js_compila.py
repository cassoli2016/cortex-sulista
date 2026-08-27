"""O JavaScript embutido no index.html tem de COMPILAR.

Por que este teste existe: uma edicao por fatia de texto atravessou DUAS
funcoes e comeu uma chave de fechamento. O resultado foi `SyntaxError` na
avaliacao do arquivo, que no navegador nao quebra so aquela tela - mata o
script inteiro no boot, e o app aparece TRAVADO. Quem encontrou foi o usuario.

Nada mais pegava: `verificar_estrutura.py` olha atributos e classes do HTML, o
smoke conta cartoes, e os testes de Playwright carregavam a pagina mas nao
falhavam por erro de console. Um `node --check` de 50 milissegundos pega.

O que este teste NAO garante (ja documentado no manual do projeto): aspa curva
dentro de string continua sendo sintaxe valida. Isto acusa estrutura quebrada,
nao conteudo errado.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


def _maior_script() -> str:
    fonte = HTML.read_text(encoding="utf-8")
    blocos = re.findall(r"<script>(.*?)</script>", fonte, re.S)
    assert blocos, "nenhum <script> inline no index.html"
    return max(blocos, key=len)


@pytest.mark.skipif(not shutil.which("node"), reason="node ausente")
def test_o_script_do_app_compila(tmp_path):
    alvo = tmp_path / "app.js"
    alvo.write_text(_maior_script(), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(alvo)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "o JavaScript do index.html nao compila — no navegador isso mata o "
        "script no boot e o app fica TRAVADO:\n" + (r.stderr or r.stdout))


def test_o_bloco_de_transmissoes_aparece_UMA_vez():
    """A fatia que quebrou o arquivo tambem DUPLICOU o trecho, porque o
    marcador de fim casou dentro de outra funcao. Contar e barato."""
    fonte = HTML.read_text(encoding="utf-8")
    assert fonte.count("cpTxTab').innerHTML") == 1
    assert fonte.count("id=\"cpTxTab\"") == 1
