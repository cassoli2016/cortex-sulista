# -*- coding: utf-8 -*-
"""A logo da Sulista em TODO modelo de e-mail (12/09/2026).

Pedido de quem opera: "em todos os modelos de e-mail precisamos colocar também
a logo da Sulista; hoje temos somente a do CÓRTEX". Todo modelo passa pelo
cabeçalho do `painel.documento`, e é por isso que o guard principal aqui é
"cada modelo tem UMA faixa": três deles (boas-vindas, Suporte, CRM) montavam
uma segunda por dentro, e a logo teria saído duas vezes. Nenhum teste envia.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

from api.correio import boas_vindas, envio, painel

RAIZ = Path(__file__).resolve().parents[2]
SVG = RAIZ / "api" / "static" / "sulista-logo-branco.svg"


def _png(caminho: Path) -> tuple[int, int, int]:
    b = caminho.read_bytes()[:26]
    assert b[:8] == b"\x89PNG\r\n\x1a\n", f"{caminho.name} não é PNG"
    w, h = struct.unpack(">II", b[16:24])
    return w, h, b[25]


def _faixas(html: str) -> int:
    return html.count('class="faixa"')


# ═══════════════════════════════════════════════════════ a imagem ═══════

def test_o_png_e_o_SVG_OFICIAL_na_proporcao_certa_e_com_fundo_transparente():
    """Gerado do SVG da marca, não redesenhado: se a proporção destoar do
    `viewBox`, alguém trocou o arquivo por outra coisa."""
    w, h, tipo = _png(painel.SULISTA_ARQUIVO)
    vb = re.search(r'viewBox="([^"]+)"', SVG.read_text(encoding="utf-8")).group(1).split()
    proporcao_svg = float(vb[2]) / float(vb[3])
    assert abs(w / h - proporcao_svg) / proporcao_svg < 0.015, (w, h, proporcao_svg)
    assert tipo == 6, "sem canal alfa: a logo branca sairia num retângulo sobre o tijolo"
    assert h == 3 * painel.SULISTA_ALTURA, "gerada em 3x a altura de exibição"
    assert abs(painel.SULISTA_LARGURA - w / 3) <= 1
    assert "fill:#fff" in SVG.read_text(encoding="utf-8"), "a fonte é a versão BRANCA"


def test_a_imagem_vai_EMBUTIDA_junto_com_o_selo():
    imgs = painel.imagens_embutidas()
    assert set(imgs) == {painel.LOGO_CID, painel.SULISTA_CID}


def test_o_envio_embute_AS_DUAS_na_mensagem():
    """O `envio` só embute o que o HTML referencia: a logo nova tem de chegar
    como parte relacionada, com o Content-ID que o `<img>` pede."""
    html = painel.documento("Teste", [painel.paragrafo("oi")])
    msg = envio._mensagem(["a@exemplo.test"], "Teste", "oi", html,
                          {"remetente": "cortex@exemplo.test"})
    cids = {p.get("Content-ID") for p in msg.walk() if p.get("Content-ID")}
    assert {"<cortex-selo>", "<sulista-logo>"} <= cids, cids


# ═══════════════════════════════════════════════════════ o cabeçalho ════

def test_o_cabecalho_tem_AS_DUAS_logos_e_o_nome_em_TEXTO():
    html = painel.documento("Relatório", [])
    assert f'src="cid:{painel.LOGO_CID}"' in html
    assert f'src="cid:{painel.SULISTA_CID}"' in html
    assert 'alt="Sulista"' in html
    assert "CÓRTEX · SULISTA" in html, "com a imagem bloqueada, o nome some"
    assert not re.search(r'<img[^>]+src="https?://', html), "imagem remota é bloqueada"


def test_o_alt_da_Sulista_sai_em_BRANCO_sobre_a_faixa():
    """Com a imagem bloqueada — o padrão em boa parte dos clientes —, o `alt`
    herda a cor do texto; preto sobre o tijolo não se leria."""
    img = re.search(r'<img src="cid:sulista-logo"[^>]+>', painel.documento("t", [])).group(0)
    assert f"color:{painel.BRANCO}" in img


def test_sem_o_PNG_o_email_sai_sem_imagem_quebrada(monkeypatch):
    monkeypatch.setattr(painel, "SULISTA_ARQUIVO", painel.SULISTA_ARQUIVO.parent / "nao-existe.png")
    html = painel.documento("t", [])
    assert "cid:sulista-logo" not in html, "quadrado quebrado no lugar da logo"
    assert painel.SULISTA_CID not in painel.imagens_embutidas()
    assert _faixas(html) == 1


# ═══════════════════════════════════════════════════════ todo modelo ════

def _boas_vindas():
    return boas_vindas.montar("Fulana de Tal", "fulana@exemplo.test", "Xk7pQ2wz",
                              "https://exemplo.test")[2]


def _suporte():
    from api.suporte import avisos
    return avisos._corpo_email({"codigo": "SUP-0001", "titulo": "Teste", "id": 1,
                                "status": "aberto"}, "resposta_suporte", "resposta")[2]


def _relatorio():
    return painel.documento("Relatório", [painel.paragrafo("x")], subtitulo="12/09")


def _redefinir_senha():
    from api.correio import redefinir_senha
    return redefinir_senha.montar("Fulana de Tal", "https://exemplo.test/#redefinir=x", 60)[2]


@pytest.mark.parametrize("montar", [_boas_vindas, _suporte, _relatorio, _redefinir_senha],
                         ids=["boas-vindas", "suporte", "relatorio", "redefinir-senha"])
def test_cada_modelo_tem_UMA_faixa_e_UMA_de_cada_logo(montar):
    html = montar()
    assert _faixas(html) == 1, "duas faixas de cabeçalho empilhadas"
    assert html.count("cid:sulista-logo") == 1
    assert html.count("cid:cortex-selo") == 1


def test_o_boas_vindas_mantem_o_TITULO_e_o_subtitulo_na_faixa():
    html = _boas_vindas()
    assert "Bem-vindo, Fulana." in html
    assert "Seu acesso ao painel de gestão da Sulista" in html
