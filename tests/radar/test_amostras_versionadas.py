# -*- coding: utf-8 -*-
"""Toda amostra que os testes do Radar leem está NO REPOSITÓRIO.

O QUE ACONTECEU (11/09/2026): a amostra da planilha da ANP entrou no disco e
não no git — o `.gitignore` recusa `*.xlsx`, e `git add` não reclama de
arquivo ignorado. Onze testes passavam na máquina de quem os escreveu e em
nenhuma outra; quem achou foi outra sessão, rodando a suíte numa worktree
limpa. Guard que muda de resultado conforme a máquina é primo de guard vazio.

A pergunta é feita ao GIT, e não ao disco: o disco de quem escreveu sempre tem
o arquivo — é exatamente o lugar onde o defeito não aparece.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "tests" / "radar" / "dados"


def _versionados() -> set[str]:
    if not shutil.which("git"):
        pytest.skip("sem git nesta máquina")
    r = subprocess.run(["git", "-C", str(RAIZ), "ls-files", "tests/radar/dados"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("fora de um repositório git")
    return {Path(l).name for l in r.stdout.split()}


def test_nenhuma_amostra_no_disco_esta_FORA_do_repositorio():
    no_disco = {p.name for p in PASTA.iterdir() if p.is_file()}
    assert no_disco, "a pasta de amostras veio vazia — a varredura passaria por vacuidade"
    fora = sorted(no_disco - _versionados())
    assert not fora, ("amostra no disco e FORA do repositório (o .gitignore a engoliu?): "
                      + ", ".join(fora) + " — o teste que a usa só passa nesta máquina")


def test_toda_amostra_PEDIDA_pelos_testes_existe_no_repositorio():
    """O lado de quem LÊ: um nome pedido a `ler()` ou às rotas do dublê tem de
    estar no git — ou, para a planilha, a fonte JSON dela."""
    versionados = _versionados()
    pedidos = set()
    for f in (RAIZ / "tests" / "radar").glob("*.py"):
        pedidos |= set(re.findall(r'"([a-z0-9_]+\.(?:json|xml|xlsx))"', f.read_text(encoding="utf-8")))
    pedidos.discard("radar_payload.json")      # é do e2e, em tests/frontend
    assert pedidos, "nenhuma amostra encontrada nos testes — a regex envelheceu"
    faltam = sorted(n for n in pedidos
                    if (Path(n).with_suffix(".json").name if n.endswith(".xlsx") else n)
                    not in versionados)
    assert not faltam, "amostra pedida pelos testes e ausente do repositório: " + ", ".join(faltam)
