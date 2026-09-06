"""Os lancadores versionados servem em QUALQUER instalacao, e carregam a
configuracao de concorrencia.

O QUE ESTE ARQUIVO IMPEDE, achado em 06/09/2026:

Os quatro `.vbs` de `scripts/win/` fixavam caminhos de OUTRA maquina --
`E:\\Cortex-Sulista\\cortex-sulista` e o perfil de outra pessoa. Quem os usasse
subiria a API do lugar errado, ou nao subiria; e como o `wscript` roda sem
janela, a falha e MUDA. O que a producao executa e uma copia em `data\\win\\`,
que NAO e versionada (o `.gitignore` tira `data/*`) -- entao o repositorio
guardava a versao errada e a certa nao estava em lugar nenhum.

O segundo ponto e a concorrencia: `WEB_CONCURRENCY` e a fonte UNICA do numero de
processos (o uvicorn a usa como padrao do numero de workers, e o
`api/processos.py` a le para dimensionar os pools e para exigir a eleicao de
lider do `api/lider.py`). Um lancador que passasse o numero na linha de comando
sem exportar a variavel dimensionaria os pools para UM processo e estouraria o
`max_connections` do PostgreSQL local.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
WIN = RAIZ / "scripts" / "win"
LANCADORES = sorted(WIN.glob("*.vbs"))

# `E:\Cortex-Sulista` e o perfil `casso` sao os dois caminhos que estavam
# fixados. Montados por partes para o proprio teste nao virar uma ocorrencia
# literal deles quando alguem der grep no repositorio.
FIXO_ANTIGO = re.compile(r"E:[\\/]Cortex-Sulista", re.IGNORECASE)
PERFIL_ALHEIO = re.compile(r"C:[\\/]Users[\\/]" + "casso" + r"\b", re.IGNORECASE)


def codigo(vbs: Path) -> str:
    """So as linhas EXECUTAVEIS.

    Os comentarios destes arquivos citam os caminhos antigos DE PROPOSITO: e a
    historia do defeito, e apaga-la para o teste passar seria trocar
    documentacao por verde.
    """
    linhas = []
    for l in vbs.read_text(encoding="utf-8").splitlines():
        limpo = l.strip()
        if not limpo or limpo.startswith("'") or limpo.upper().startswith("REM "):
            continue
        linhas.append(l)
    return "\n".join(linhas)


def test_ha_lancadores_para_conferir():
    assert LANCADORES, "nenhum .vbs em scripts/win -- o glob quebrou"


@pytest.mark.parametrize("vbs", LANCADORES, ids=lambda p: p.name)
def test_nenhum_lancador_fixa_caminho_de_outra_maquina(vbs):
    """Caminho absoluto so se justifica quando NAO da para derivar: o
    cloudflared vem do winget e mora no perfil de quem instalou, entao ele e
    procurado em varios lugares e o script RECLAMA quando nao acha. O que nao
    pode e apontar para o perfil de uma pessoa ou para uma unidade que so
    existe numa maquina.
    """
    exec_ = codigo(vbs)
    assert not FIXO_ANTIGO.search(exec_), f"{vbs.name} fixa a unidade de outra maquina"
    assert not PERFIL_ALHEIO.search(exec_), f"{vbs.name} fixa o perfil de outra pessoa"
    assert str(RAIZ).lower() not in exec_.lower(), (
        f"{vbs.name} fixa o caminho DESTA instalacao -- num clone em outro "
        "lugar ele apontaria para o vazio")


def test_o_lancador_da_api_carrega_a_concorrencia():
    exec_ = codigo(WIN / "run-api.vbs")
    m = re.search(r'WEB_CONCURRENCY"\)\s*=\s*"(\d+)"', exec_)
    assert m, "run-api.vbs nao exporta WEB_CONCURRENCY"
    assert int(m.group(1)) >= 1, "WEB_CONCURRENCY tem de ser inteiro positivo"

    # e NAO pode existir uma segunda fonte discordando dela
    assert "-workers" not in exec_, (
        "run-api.vbs passa o numero de workers na linha de comando: seriam "
        "DUAS fontes, e os pools do api/processos.py seguem a variavel")


@pytest.mark.skipif(os.name != "nt", reason="cscript so existe no Windows")
def test_a_raiz_e_derivada_do_proprio_caminho(tmp_path):
    """EXECUTA a derivacao, em vez de ler o texto.

    Copia a linha que calcula a raiz para uma arvore falsa `<tmp>/scripts/win/`
    e roda uma sonda que so a IMPRIME. Se a derivacao estiver errada -- ou se
    alguem voltar a fixar caminho -- o valor nao bate com a arvore falsa.
    """
    cscript = shutil.which("cscript")
    if not cscript:
        pytest.skip("cscript nao encontrado")

    destino = tmp_path / "scripts" / "win"
    destino.mkdir(parents=True)
    original = (WIN / "run-api.vbs").read_text(encoding="utf-8")
    linha = [l for l in original.splitlines() if l.startswith("raiz = ")]
    assert len(linha) == 1, "run-api.vbs deixou de derivar a raiz numa linha so"

    sonda = destino / "sonda.vbs"
    sonda.write_text(
        'Set fso = CreateObject("Scripting.FileSystemObject")\n'
        + linha[0] + "\n"
        + "WScript.Echo raiz\n",
        encoding="ascii")

    saida = subprocess.run([cscript, "//Nologo", str(sonda)],
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    calculada = Path(saida.stdout.strip())
    assert calculada == tmp_path, (
        f"a derivacao devolveu {calculada}, esperado {tmp_path} -- o lancador "
        "nao acha a raiz da propria instalacao")
