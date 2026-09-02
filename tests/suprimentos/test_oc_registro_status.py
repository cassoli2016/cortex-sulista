"""O domínio de status de OC vive em QUATRO registros e nenhum teste os cruzava.

`main._OC_STATUS_VALIDOS` (a rota recusa com 422), `OC_STATUS` no JS (a badge
e o rótulo), as `<option>` de `#fOcStatus` (o filtro) e o que `oc_status`
devolve. Um estado novo que entre num deles e falte nos outros não dá erro:
a option nova volta 422, ou a badge cai em `[o.status,'b-info']` sem rótulo.
Essa classe de defeito não tem sintoma, só ausência.
"""
from __future__ import annotations

import re
from pathlib import Path

from api import main, suprimentos_oc as oc

HTML = (Path(__file__).resolve().parents[2] / "api" / "static" / "index.html").read_text(encoding="utf-8")


def _js_status():
    i = HTML.index("const OC_STATUS = {")
    bloco = HTML[i:HTML.index("};", i)]
    return set(re.findall(r"^\s*(\w+):\[", bloco, re.M))


def _options():
    i = HTML.index('<select id="fOcStatus"')
    bloco = HTML[i:HTML.index("</select>", i)]
    return {v for v in re.findall(r'<option value="([^"]*)"', bloco) if v}


def test_os_quatro_registros_dizem_o_mesmo():
    canonico = set(oc.STATUS_TODOS)
    assert set(main._OC_STATUS_VALIDOS) == canonico, "a rota recusa o que a tela oferece"
    assert _js_status() == canonico, "badge sem rótulo para algum estado"
    assert _options() == canonico, "o filtro oferece estado que a rota não aceita (ou esconde um)"


def test_rota_recusa_status_fora_do_registro():
    r = main.ordens_compra(status="entregue")
    assert r.status_code == 422
