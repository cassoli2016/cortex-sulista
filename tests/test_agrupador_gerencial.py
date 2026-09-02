# -*- coding: utf-8 -*-
"""Guard da fonte unica do agrupador gerencial.

`sulista.agrupadorgerencial` e uma tabela do ERP sem chave primaria e sem
contrato de tipo. Em 02/09/2026 ela foi recriada com `grupo` em varchar (era
integer) e com uma conta duplicada: as cinco telas que dependem dela pararam
de responder, e o resultado ficou R$ 1,5 mi diferente do razao. Nenhum teste
pegou, porque todos usam duble.

O que da para garantir SEM o banco e o que este arquivo cobra: ninguem volta a
juntar a tabela CRUA. Quem passa por `api.agrupador_gerencial.left_join()`
herda de graca o cast de tipo e a agregacao por (grupo, reduzido) — as duas
defesas. Quem escreve o JOIN a mao perde as duas, em silencio.

A conferencia do CADASTRO (duplicata viva, conta de balanco classificada, os
dois caminhos do resultado) e do `scripts/conferir_agrupador.py`, que roda
contra o banco vivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DONO = ROOT / "api" / "agrupador_gerencial.py"

# `JOIN <tabela>` e o defeito. `FROM <tabela>` sozinho nao multiplica linha
# nenhuma (e o que a propria fonte e os conferidores de cadastro fazem).
JOIN_CRU = re.compile(r"JOIN\s+sulista\.agrupadorgerencial\b", re.I)


def _fontes() -> list[Path]:
    return [p for p in (ROOT / "api").rglob("*.py") if p != DONO]


def test_nenhum_modulo_junta_a_tabela_crua():
    """O JOIN da tabela sai de api/agrupador_gerencial.py, de lugar nenhum mais."""
    culpados = []
    for p in _fontes():
        texto = p.read_text(encoding="utf-8")
        for n, linha in enumerate(texto.splitlines(), 1):
            if JOIN_CRU.search(linha):
                culpados.append(f"{p.relative_to(ROOT)}:{n}: {linha.strip()}")
    assert not culpados, (
        "JOIN direto em sulista.agrupadorgerencial — use "
        "agrupador_gerencial.left_join(), que normaliza o tipo de `grupo` e "
        "agrega por (grupo, reduzido):\n  " + "\n  ".join(culpados))


@pytest.mark.parametrize("modulo", [
    "api.queries", "api.orcamento.sql", "api.previsao.sql", "api.custos_sql",
])
def test_sql_montado_nao_junta_a_tabela_crua(modulo):
    """O texto MONTADO tambem: f-string e .replace() escondem o join do grep."""
    import importlib
    mod = importlib.import_module(modulo)
    culpados = [nome for nome in dir(mod)
                if isinstance(getattr(mod, nome), str)
                and JOIN_CRU.search(getattr(mod, nome))]
    assert not culpados, f"{modulo}: SQL com JOIN cru -> {culpados}"


def test_a_fonte_normaliza_o_tipo_e_agrega():
    from api import agrupador_gerencial as ag
    # o cast e o que sobrevive a coluna varchar de hoje E a integer de ontem
    assert "grupo::text" in ag.FONTE and "::int" in ag.FONTE
    # uma linha por conta: sem isto a duplicata do cadastro dobra o lancamento
    assert "GROUP BY" in ag.FONTE and "min(ag_.descricao)" in ag.FONTE
    j = ag.left_join("ag", "l")
    assert j.startswith("LEFT JOIN (SELECT")
    assert "ag.reduzido = l.reduzido" in j and "ag.grupo = l.grupo" in j


def test_conferidor_usa_a_mesma_alocacao_da_dre():
    """A linha da DRE de um agrupador tem UMA definicao: DRE_MODELO."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_conf_ag", ROOT / "scripts" / "conferir_agrupador.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from api.queries import DRE_MODELO
    assert mod.DRE_MODELO is DRE_MODELO
    assert mod._linha_da_dre("CV - COMBUSTIVEL") == "CUSTO VARIAVEL"
    assert mod._linha_da_dre("CF - DESPESAS ADM") == "CUSTO FIXO"
    # o agrupador que o ERP criou sem prefixo continua sem linha — e por isso
    # que o conferidor o acusa em vez de o esconder
    assert mod._linha_da_dre("CUSTOS OPERACIONAIS") is None
