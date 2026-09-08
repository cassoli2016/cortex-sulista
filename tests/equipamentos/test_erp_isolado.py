# -*- coding: utf-8 -*-
"""O ERP entra no cadastro por UMA porta só — `api/equipamentos/erp.py`.

POR QUE ESTE GUARD EXISTE
=========================
A decisão de quem opera é sair do Avacorp. Se a leitura do AVA voltar a vazar
para o resto do módulo, "sair do ERP" deixa de ser apagar um arquivo e vira
varredura arqueológica — e essa volta NÃO TEM SINTOMA: funciona perfeitamente,
com todos os testes verdes, até o dia do desligamento.

A varredura sai do DISCO, por `ast`, e leva um `assert` que reprova o
resultado VAZIO: varredura que não acha nenhum arquivo passa por vacuidade, e
já foi assim que um guard desta casa aprovou a única violação viva que existia.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULO = Path(__file__).resolve().parents[2] / "api" / "equipamentos"

#: A ÚNICA porta para o ERP. Trocar este nome sem trocar o arquivo faz o guard
#: vigiar um arquivo que não existe — por isso ele é conferido contra o disco.
PORTA = "erp.py"


def _arquivos() -> list[Path]:
    return sorted(p for p in MODULO.glob("*.py") if p.name != "__init__.py")


def test_a_porta_do_erp_existe_no_disco():
    """Lista escrita à mão que descreve o código se confere CONTRA o código.

    Sem isto, renomear `erp.py` deixaria o guard abaixo verde para sempre,
    vigiando um arquivo inexistente — que é como a varredura de agendadores
    passou a procurar uma thread chamada `aviso-carga` quando ela se chama
    `rastreio-aviso`.
    """
    assert (MODULO / PORTA).is_file(), (
        f"{PORTA} nao existe em {MODULO} — o guard esta vigiando um arquivo "
        f"que nao ha, e passaria calado para sempre")


def test_a_varredura_acha_arquivos():
    """Varredura que não acha nada passa por vacuidade."""
    arquivos = _arquivos()
    assert len(arquivos) >= 5, f"varredura achou so {len(arquivos)} arquivos"
    assert any(p.name == PORTA for p in arquivos)


@pytest.mark.parametrize(
    "arquivo", [p for p in _arquivos() if p.name != PORTA],
    ids=lambda p: p.name)
def test_so_o_erp_py_importa_o_banco_do_erp(arquivo: Path):
    """Nenhum outro módulo do cadastro fala com o AVA.

    Em guard parametrizado CADA PARÂMETRO É UM GUARD: sabotar um prova o
    mecanismo, não prova que os outros apontam para alvo real. Por isso o
    `test_a_porta_do_erp_existe_no_disco` acima confere a lista, e não só o
    mecanismo.
    """
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    ofensas: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            # `from .. import db` / `from api import db`
            nomes = {a.name for a in no.names}
            if "db" in nomes and (no.module or "").split(".")[-1] in ("", "api"):
                ofensas.append(f"linha {no.lineno}: from {no.module or '..'} import db")
            if (no.module or "").endswith("api.db"):
                ofensas.append(f"linha {no.lineno}: from {no.module} import ...")
        elif isinstance(no, ast.Import):
            for a in no.names:
                if a.name in ("api.db",) or a.name.endswith(".db"):
                    ofensas.append(f"linha {no.lineno}: import {a.name}")
    assert not ofensas, (
        f"{arquivo.name} fala com o ERP direto: {ofensas}. A leitura do AVA "
        f"mora so em {PORTA} — e o cadastro precisa sobreviver ao "
        f"desligamento do Avacorp.")


def test_o_erp_py_realmente_le_o_avacorp():
    """O espelho do guard: a porta tem de estar ABERTA.

    Um `erp.py` que não importa `db` passaria em todos os testes acima — e o
    cadastro nasceria vazio. Guard que só sabe proibir aprova o vazio.
    """
    fonte = (MODULO / PORTA).read_text(encoding="utf-8")
    assert "from .. import db" in fonte, (
        "erp.py deixou de ler o ERP — o cadastro perde a fonte principal")
