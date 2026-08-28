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
    marcador de fim casou dentro de outra funcao. Contar e barato.

    A guarda ja valeu duas vezes, com dois anos de distancia entre uma linha e
    outra deste arquivo: em 26/08, quando nasceu, e em 28/08, quando a tabela
    virou a aba "Transmitidos" e um `s.index` pegou uma ocorrencia ANTERIOR ao
    trecho a remover — a fatia `s[:i] + s[j:]` com j < i nao remove, DUPLICA.
    Os ids mudaram (`cpTxTab` -> `ctetxTab`); a contagem continua barata.
    """
    fonte = HTML.read_text(encoding="utf-8")
    # a tabela: uma no HTML, uma no script que a preenche
    assert fonte.count('id="ctetxTab"') == 1
    assert fonte.count("getElementById('ctetxTab')") == 1
    # e cada funcao da aba, uma vez so. `loadCtecp` esta aqui porque foi ELA
    # que duplicou em 28/08 — a fatia atravessou o fim dela.
    for f in ("ctetxTabela", "ctetxRender", "loadCtetx", "loadCtecp"):
        assert fonte.count(f"function {f}(") == 1, f"{f} nao aparece uma vez so"
