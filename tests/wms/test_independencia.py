# -*- coding: utf-8 -*-
"""O ARMAZÉM NÃO PARA QUANDO O ERP PARA — cobrado pelos dois lados.

1. Estrutural: só `api/wms/erp.py` importa `api.db`. A lista de arquivos sai
   do DISCO, e a varredura reprova o resultado vazio (varredura que não acha
   nada passa por vacuidade).
2. Comportamental: com o ERP derrubado, o recebimento manual abre, confere,
   fecha e o saldo aparece.
"""
from __future__ import annotations

import ast
from pathlib import Path

from api.wms import erp, estoque, recebimento
from tests.wms.conftest import CNPJ_DEP, USUARIO

PASTA = Path(__file__).resolve().parents[2] / "api" / "wms"


def _importa_db(caminho: Path) -> bool:
    arv = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arv):
        if isinstance(no, ast.ImportFrom):
            mod = no.module or ""
            nomes = {a.name for a in no.names}
            if mod in ("api.db",) or (mod in ("", "api") and "db" in nomes) \
                    or (no.level >= 1 and mod == "" and "db" in nomes) \
                    or (no.level >= 2 and mod == "db"):
                return True
        if isinstance(no, ast.Import) and any(a.name == "api.db" for a in no.names):
            return True
    return False


def test_so_o_erp_py_fala_com_o_avacorp():
    arquivos = sorted(PASTA.glob("*.py"))
    assert len(arquivos) >= 9, "a varredura não achou os arquivos do módulo"
    quem = [p.name for p in arquivos if _importa_db(p)]
    assert quem == ["erp.py"], f"importam api.db: {quem}"


def test_a_varredura_enxerga_o_import_do_erp_py():
    """Se a detecção quebrar, o teste de cima passaria com `quem == []`... não:
    exige exatamente `erp.py`. Este confere o detector isoladamente."""
    assert _importa_db(PASTA / "erp.py")
    assert not _importa_db(PASTA / "estoque.py")


def test_recebimento_manual_funciona_com_o_erp_fora_do_ar(armazem, monkeypatch):
    def cai(*a, **k):
        raise OSError("ERP fora do ar")
    monkeypatch.setattr(erp.db, "query", cai)
    r = recebimento.abrir({"armazem_id": armazem["id"], "doca_id": armazem["doca"],
                           "depositante_cnpj": CNPJ_DEP, "nf_numero": 99,
                           "itens": [{"produto_id": armazem["p1"], "qtd_nf": 4}]}, USUARIO)
    recebimento.conferir(r["id"], [{"id": r["itens"][0]["id"], "qtd_conferida": 4}], USUARIO)
    recebimento.fechar(r["id"], USUARIO)
    assert estoque.saldo(armazem["id"])["saldo"][0]["qtd"] == 4
