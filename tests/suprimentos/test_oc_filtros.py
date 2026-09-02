"""Filtro enviado × parâmetro consumido — e o loader tem de USAR o qsView.

Os selects de origem e filial do Painel de Custos existiam, disparavam recarga
e nunca chegavam à API: `loadCustos` montava a query string à mão só com as
datas, enquanto `qsView('custos')` (que ninguém chamava) montava os quatro.
Comparar qsView com a assinatura da rota passaria — por isso o segundo assert.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from api import main

HTML = (Path(__file__).resolve().parents[2] / "api" / "static" / "index.html").read_text(encoding="utf-8")


def _params_qsview(k: str) -> set[str]:
    i = HTML.index("function qsView(k){")
    corpo = HTML[i:HTML.index("\n}\n", i)]
    m = re.search(rf"k==='{k}'\)\{{(.*?)\n  \}} else if", corpo, re.S) or \
        re.search(rf"k==='{k}'\)\{{(.*?)\n  \}}", corpo, re.S)
    assert m, k
    return set(re.findall(r"p\.set\('(\w+)'", m.group(1)))


def _corpo_js(nome: str) -> str:
    i = HTML.index(f"async function {nome}(")
    return HTML[i:HTML.index("\n}\n", i)]


@pytest.mark.parametrize("view, rota", [("oc", main.ordens_compra), ("custos", main.suprimentos_custos)])
def test_todo_filtro_enviado_e_consumido_pela_rota(view, rota):
    enviados = _params_qsview(view)
    aceitos = set(inspect.signature(rota).parameters)
    assert enviados, view
    assert enviados <= aceitos, f"{view}: a tela manda {enviados - aceitos} e a rota ignora"


@pytest.mark.parametrize("loader, view, rota", [
    ("loadOc", "oc", "/api/suprimentos/ordens-compra?"),
    ("loadCustos", "custos", "/api/suprimentos/custos?"),
])
def test_o_loader_usa_o_qsview_na_requisicao(loader, view, rota):
    corpo = _corpo_js(loader)
    assert f"qsView('{view}')" in corpo, f"{loader} não monta a query por qsView"
    assert rota + "'+q" in corpo, f"{loader} não manda a query montada"
    assert "'dt_de='+" not in corpo, f"{loader} monta a query à mão"


def test_os_dois_loaders_passam_por_respostaJSON():
    for loader in ("loadOc", "loadCustos", "carregarOcPendentes"):
        corpo = _corpo_js(loader)
        assert "respostaJSON(r)" in corpo, loader
        assert "await r.json()" not in corpo, loader


def test_status_do_filtro_bate_com_o_registro():
    from api import suprimentos_oc as oc
    i = HTML.index('<select id="fOcStatus"')
    bloco = HTML[i:HTML.index("</select>", i)]
    assert {v for v in re.findall(r'value="(\w+)"', bloco)} == set(oc.STATUS_TODOS)
