"""Nome usado e não importado — o defeito que só aparece em produção.

O QUE ISTO CONSERTA (Premiação, 29–30/08/2026)
=============================================
`api/main.py` usava `datetime.now()` numa rota, e o módulo importa apenas
`from datetime import date`. Resultado: **`NameError` toda vez que a tela
abria a configuração da premiação sem competência na URL** — que é
exatamente o primeiro carregamento.

Por que passou por todos os testes: **eu sempre chamei a rota com a
competência explícita.** O ramo `competencia or datetime.now()` nunca foi
exercitado. Um `NameError` num ramo pouco percorrido é invisível até alguém
tropeçar nele em produção — e ali ele chega como 500 sem explicação.

E não era um: o `ruff` achou **três**, todos em ramos raros:
- `main.py` `datetime` — a Premiação;
- `main.py` `ROOT` — a rota que grava a planilha do plano orçamentário;
- `servidor.py` `pglocal` — no ramo de EXCEÇÃO da Saúde, que estouraria
  justamente quando as tabelas da premiação faltassem, ou seja no caso que
  aquela verificação existe para relatar.

POR QUE UM TESTE, E NÃO "rodar o linter às vezes"
=================================================
`[tool.ruff]` já estava no `pyproject.toml` desde sempre — configurado e nunca
instalado, nunca executado. Ferramenta que depende de alguém lembrar de rodar
não pega nada. Aqui ela roda com a suíte.

O RECORTE É ESTREITO DE PROPÓSITO: só `F821` (nome não definido). Ligar o
ruff inteiro num projeto de 25 mil linhas traria centenas de apontamentos de
estilo, o teste nasceria vermelho e seria desligado na primeira semana. F821
não é estilo — é código que vai quebrar.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
ALVOS = ["api", "scripts", "tests"]


def _ruff() -> list[str] | None:
    """O ruff do venv, se houver; senão o `uvx`, que o baixa sob demanda."""
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    uvx = shutil.which("uvx")
    return [uvx, "ruff"] if uvx else None


def test_nenhum_nome_usado_sem_estar_definido():
    cmd = _ruff()
    if not cmd:
        pytest.skip("ruff indisponível (sem `ruff` nem `uvx` no PATH)")
    r = subprocess.run(
        [*cmd, "check", "--select", "F821", "--output-format", "concise",
         *ALVOS],
        cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)
    saida = ((r.stdout or "") + (r.stderr or "")).strip()
    achados = [l for l in saida.splitlines() if "F821" in l]
    assert not achados, (
        "nome usado sem estar definido — vira NameError em produção, no ramo "
        "que ninguém exercitou:\n  " + "\n  ".join(achados)
        + "\n\nFoi assim que a Premiação ficou dois dias em 500: "
          "`datetime.now()` num módulo que só importava `date`.")


def test_o_proprio_linter_ESTA_FUNCIONANDO(tmp_path):
    """Sem isto, o teste acima ficaria verde para sempre se o ruff parasse de
    rodar (não instalado, argumento mudado, alvo errado) — e um verde que não
    mede nada é pior que vermelho.
    """
    cmd = _ruff()
    if not cmd:
        pytest.skip("ruff indisponível")
    ruim = tmp_path / "com_erro.py"
    ruim.write_text("def f():\n    return nome_que_nao_existe\n",
                    encoding="utf-8")
    r = subprocess.run(
        [*cmd, "check", "--select", "F821", "--output-format", "concise",
         str(ruim)],
        cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)
    saida = (r.stdout or "") + (r.stderr or "")
    assert "F821" in saida, (
        "o ruff não acusou um nome indefinido plantado — o teste acima está "
        f"passando por vacuidade. Saída: {saida[:300]!r}")
