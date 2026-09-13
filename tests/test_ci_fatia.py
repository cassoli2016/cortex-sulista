"""A divisão da suíte em fatias do CI não pode perder arquivo.

Um arquivo que cai fora de todas as fatias sai do CI inteiro, e o CI fica
VERDE sem rodá-lo — exatamente o tipo de defeito que não tem sintoma. Estes
testes cobram a partição sobre a coleta REAL, a recusa diante de coleta com
erro, e o formato das anotações (gerado por um pytest de verdade, não escrito
à mão: dublê de formato externo copia o real).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ci_fatia  # noqa: E402


def _particao_ok(fatias: list[list[str]], todos: set[str]) -> None:
    vistos: list[str] = [a for f in fatias for a in f]
    assert len(vistos) == len(set(vistos)), "arquivo em MAIS DE UMA fatia"
    assert set(vistos) == todos, (
        f"arquivos fora de todas as fatias: {sorted(todos - set(vistos))[:10]}")


def test_dividir_particiona_sem_perder_nem_repetir():
    pesos = {f"tests/t{i:03d}.py": (i * 7) % 23 + 1 for i in range(200)}
    for n in (1, 3, 8):
        _particao_ok(ci_fatia.dividir(pesos, n), set(pesos))


def test_dividir_e_deterministico_mesmo_com_empate():
    """As N fatias calculam a divisão cada uma na sua máquina: se duas
    discordarem, um arquivo roda duas vezes e outro nenhuma."""
    pesos = {f"tests/t{i}.py": 5 for i in range(40)}          # tudo empatado
    invertido = dict(reversed(list(pesos.items())))
    assert ci_fatia.dividir(pesos, 8) == ci_fatia.dividir(invertido, 8)


def test_a_divisao_REAL_cobre_todo_arquivo_coletado_e_equilibra():
    contagem = ci_fatia.coletar()
    assert len(contagem) > 300, "coleta pequena demais: varredura vazia?"
    pesos = {a: ci_fatia.peso(a, c) for a, c in contagem.items()}
    fatias = ci_fatia.dividir(pesos, 8)
    _particao_ok(fatias, set(contagem))
    cargas = [sum(pesos[a] for a in f) for f in fatias]
    assert max(cargas) <= 1.25 * min(cargas), f"fatias desequilibradas: {cargas}"


def test_coleta_com_import_quebrado_PARA_em_vez_de_seguir(tmp_path):
    (tmp_path / "test_bom.py").write_text("def test_ok():\n    pass\n",
                                          encoding="utf-8")
    (tmp_path / "test_quebrado.py").write_text(
        "import modulo_que_nao_existe_em_lugar_nenhum\n"
        "def test_x():\n    pass\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="coleta falhou"):
        ci_fatia.coletar(tmp_path)


def test_fatia_vazia_e_recusada(monkeypatch):
    monkeypatch.setattr(ci_fatia, "coletar", lambda: {"tests/a.py": 1})
    with pytest.raises(SystemExit, match="VAZIA"):
        ci_fatia.main(["ci_fatia.py", "listar", "1", "2"])


def test_anotar_le_o_junit_de_um_pytest_de_verdade(tmp_path, capsys):
    (tmp_path / "test_falha.py").write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('v', ['a,b'])\n"
        "def test_quebra(v):\n"
        "    assert v == 'x', 'primeira linha: 100%\\nsegunda linha'\n"
        "def test_passa():\n    pass\n", encoding="utf-8")
    xml = tmp_path / "resultado.xml"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p",
                    "no:cacheprovider", f"--junitxml={xml}", "test_falha.py"],
                   cwd=tmp_path, capture_output=True)
    assert xml.exists()

    assert ci_fatia.anotar(xml) == 1                  # só a que falhou
    linha = capsys.readouterr().out.strip()
    assert "\n" not in linha, "anotação com quebra crua vira duas linhas"
    assert linha.startswith("::error file=test_falha.py,title=test_quebra[a%2Cb]::")
    assert "100%25" in linha, "o % sem escape é lido como código de escape"
