# -*- coding: utf-8 -*-
"""O manifesto do app do motorista — o que o celular lê para instalá-lo.

O botão "Instalar o app" (`motorista.html`) só existe quando o navegador
oferece a instalação, e o navegador decide isso LENDO ESTE ARQUIVO. Manifesto
errado não dá erro em lugar nenhum: o convite simplesmente não chega, o botão
vira passo a passo, e o atalho que sai pelo menu abre a página errada ou com
ícone borrado. Por isso cada campo que decide a instalação tem guard aqui.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"


def _manifesto() -> dict:
    return json.loads((STATIC / "manifest-motorista.json").read_text(encoding="utf-8"))


def _png(nome: str) -> tuple[int, int]:
    """Largura e altura lidas do CABEÇALHO do PNG, não do nome do arquivo."""
    b = (STATIC / nome).read_bytes()[:24]
    assert b[:8] == b"\x89PNG\r\n\x1a\n", f"{nome} não é PNG"
    return struct.unpack(">II", b[16:24])


def test_o_atalho_abre_o_APP_e_nao_o_painel():
    """O manifesto do painel abre em `/`, uma tela de login que o motorista não
    consegue passar — por isso este é próprio, e é isto que o prova."""
    m = _manifesto()
    assert m["start_url"] == "/motorista"
    assert m["start_url"].startswith(m["scope"]), "o app abriria fora do próprio escopo"
    assert m["display"] in ("standalone", "fullscreen", "minimal-ui"), \
        "sem isto o atalho abre como aba do navegador, e não como app"
    assert m.get("name") and m.get("short_name")
    assert not m.get("prefer_related_applications"), \
        "isto manda o celular procurar um app na loja em vez de instalar este"


def test_cada_icone_tem_o_tamanho_que_o_manifesto_DECLARA():
    """É o ícone que vai para a tela inicial. Declarado com um tamanho e salvo
    com outro, ele sai esticado — e ninguém percebe olhando o JSON."""
    tamanhos = set()
    for i in _manifesto()["icons"]:
        assert i["src"].startswith("/static/")
        w, h = _png(i["src"][len("/static/"):])
        assert i["sizes"] == f"{w}x{h}", (i["src"], i["sizes"], (w, h))
        tamanhos.add(w)
    assert {192, 512} <= tamanhos, "o Android pede os dois tamanhos"


def test_a_pagina_aponta_o_manifesto_e_o_icone_do_IPHONE():
    """O iPhone não lê o ícone do manifesto: usa o `apple-touch-icon`."""
    html = (STATIC / "motorista.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="/static/manifest-motorista.json">' in html
    m = re.search(r'<link rel="apple-touch-icon" sizes="(\d+)x(\d+)" href="/static/([^"]+)"',
                  html)
    assert m, "sem apple-touch-icon o iPhone fotografa a página para fazer o ícone"
    assert _png(m.group(3)) == (int(m.group(1)), int(m.group(2)))
