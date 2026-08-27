# tests/correio/test_relatorios.py
"""Os relatorios que saem por e-mail.

HTML de e-mail tem regras proprias, e cada uma destas existe porque um cliente
popular quebra sem ela. Sao os testes que impedem alguem (inclusive eu) de
"melhorar" o layout usando flexbox e descobrir no Outlook do diretor.
"""
from __future__ import annotations

import re

import pytest

from api.correio import painel, relatorios


def test_nenhum_relatorio_levanta_excecao(monkeypatch):
    """A rotina roda sem ninguem olhando: um erro que a derruba some do mundo,
    enquanto um e-mail dizendo "nao consegui ler o ERP" e lido por uma pessoa
    na manha seguinte."""
    def explode(*a, **k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr("api.contrapartida.lote.resumo_fila", explode)
    r = relatorios.contrapartida()
    assert r["html"] and r["texto"]
    assert "falha" in r["assunto"].lower()


def test_relatorio_desconhecido_e_ERRO_e_nao_silencio():
    """Um id errado gravado na agenda pararia o envio para sempre sem dizer
    por que."""
    with pytest.raises(ValueError, match="desconhecido"):
        relatorios.montar("nao-existe")


def test_o_html_nao_usa_flex_nem_grid():
    """Outlook para Windows renderiza com o motor do Word: nao entende `flex`
    nem `grid`. Layout de e-mail se faz com <table>."""
    html = painel.documento("t", [painel.kpis([{"rotulo": "a", "valor": "1"}]),
                                  painel.tabela(["x"], [["y"]])])
    assert "display:flex" not in html and "display:grid" not in html
    assert "<table" in html


def test_o_estilo_e_INLINE():
    """Gmail remove <style> do <head> em parte dos casos e a mensagem chegaria
    sem formatacao nenhuma - pior do que nunca ter tido.

    Ha UM bloco <style>, so para declarar o tema claro (ver o teste seguinte,
    que garante que ele nao carrega layout). Todo o resto e inline.
    """
    html = painel.documento("t", [painel.paragrafo("oi")])
    assert html.count("<style") == 1
    assert 'style="' in html
    corpo = html.split("</head>")[1]
    assert "<style" not in corpo, "estilo no corpo nao sobrevive ao Gmail"


def test_nao_ha_imagem_externa():
    """Cliente de e-mail bloqueia imagem remota por padrao: o que precisa ser
    visto vem como texto e numero."""
    html = painel.documento("t", [painel.kpis([{"rotulo": "a", "valor": "1"}])])
    assert "<img" not in html
    assert not re.search(r'(src|background)\s*=\s*"https?://', html)


def test_variavel_css_nao_entra_no_email():
    """`var(--brand)` nao existe em cliente de e-mail: o token do design
    system vira hexadecimal literal."""
    html = painel.documento("t", [painel.paragrafo("oi"),
                                  painel.chip("x", "ok")])
    assert "var(--" not in html


def test_largura_travada_em_600():
    """600px cabe no painel de leitura do Outlook e num celular sem reducao;
    acima disso o cliente encolhe a pagina inteira e a tipografia some."""
    html = painel.documento("t", [])
    assert 'width="600"' in html and "max-width:100%" in html


def test_kpis_saem_DOIS_por_linha():
    """Quatro colunas de 150px viram 150px reais no celular e o numero quebra
    no meio."""
    html = painel.kpis([{"rotulo": f"k{i}", "valor": i} for i in range(4)])
    # duas linhas de cartoes, cada uma com dois `<td width="50%">`
    assert html.count('<td width="50%"') == 4
    assert len(re.findall(r'<tr>\s*<td width="50%"', html)) == 2


def test_kpi_impar_nao_deixa_celula_faltando():
    """Linha com uma celula so desalinha a tabela inteira no Outlook."""
    html = painel.kpis([{"rotulo": "a", "valor": 1},
                        {"rotulo": "b", "valor": 2},
                        {"rotulo": "c", "valor": 3}])
    # 3 cartoes + 1 celula vazia para fechar a segunda linha
    assert html.count('<td width="50%"') == 4
    assert '<td width="50%"></td>' in html


def test_valores_escapam_html():
    html = painel.tabela(["a"], [["<script>alert(1)</script>"]])
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_texto_puro_acompanha_sempre(monkeypatch):
    """E o que aparece na previa da caixa de entrada e o que sobra quando o
    cliente recusa HTML.

    As fontes sao SUBSTITUIDAS: montar de verdade significaria consultar o AVA
    e o registro de emissoes, e o teste passaria ou falharia conforme a fila
    do dia - termometro, nao teste. O que se verifica aqui e o contrato de
    quem monta, nao o numero que saiu.
    """
    monkeypatch.setattr("api.contrapartida.lote.resumo_fila",
                        lambda *a, **k: {"a_emitir": 3, "ja_emitidos": 1,
                                         "ctes_no_periodo": 4,
                                         "sem_agregado_pronto": 0,
                                         "sem_cadastro": 0, "em_quarentena": 0})
    monkeypatch.setattr("api.contrapartida.lote.estado",
                        lambda: {"automacao": {"ativa": False}})
    monkeypatch.setattr("api.contrapartida.servico._transmissoes",
                        lambda *a, **k: {"documentos": 2, "autorizadas": 1,
                                         "taxa_ok": 50.0, "producao": 0,
                                         "producao_autorizadas": 0})
    monkeypatch.setattr("api.contrapartida.servico.get_contrapartida",
                        lambda *a, **k: {"avisos": []})
    monkeypatch.setattr("api.alertas.build_alertas", lambda: [])
    monkeypatch.setattr("api.alertas.digest_texto", lambda: "sem alertas")
    for nome in relatorios.CATALOGO:
        r = relatorios.montar(nome)
        assert r["texto"].strip(), f"{nome} sem texto puro"
        assert r["assunto"].strip(), f"{nome} sem assunto"
        assert r["html"].startswith("<!DOCTYPE"), f"{nome} sem documento"


def test_catalogo_declara_o_que_fazer_com_relatorio_vazio():
    """Relatorio que chega todo dia dizendo "nada a relatar" ensina a arquivar
    sem ler - e no dia em que tiver conteudo sera arquivado junto. A decisao e
    por relatorio, nao global."""
    for nome, item in relatorios.CATALOGO.items():
        assert "pular_vazio" in item, nome
        assert isinstance(item["pular_vazio"], bool)


def test_moeda_e_numero_saem_em_pt_br():
    assert painel.brl(1234567) == "R$ 1.234.567"
    assert painel.inteiro(1234) == "1.234"
    assert painel.brl(None) == "—"


def test_so_o_tipo_Html_escapa_da_higienizacao():
    """A tabela deixava passar sem escapar tudo que comecasse com "<", para os
    selos funcionarem - e um valor vindo do banco comecando com "<" ia inteiro
    para o e-mail. Adivinhar pelo conteudo e o erro; quem produz HTML seguro
    diz isso com o TIPO."""
    seguro = painel.chip("ok", "ok")
    assert isinstance(seguro, painel.Html)
    html = painel.tabela(["a"], [[seguro]])
    assert "<span" in html

    perigoso = "<span onload=x>oi</span>"   # str comum, ainda que pareca HTML
    html = painel.tabela(["a"], [[perigoso]])
    assert "onload" not in html or "&lt;span" in html


def test_defesa_de_tema_escuro_NAO_reescreve_a_paleta():
    """A primeira versao desta defesa usava `background:inherit !important` e
    APAGOU a faixa navy do cabecalho - o !important vence o estilo inline, e o
    titulo virou branco sobre branco. Visto no navegador em tema escuro.
    Defender-se do tema escuro e DECLARAR o tema, nunca reescrever por cima da
    paleta que ja esta correta."""
    html = painel.documento("t", [])
    assert "color-scheme" in html and "light only" in html
    assert "background-color:inherit" not in html
    assert "!important" not in html.split("</style>")[0].replace(
        "[data-ogsc]", "").replace("[data-ogsb]", "") or "data-ogsc" in html
    # a faixa continua navy no estilo inline, que e quem manda
    assert f"background:{painel.NAVY}" in html


def test_o_bloco_de_estilo_nao_carrega_layout():
    """Gmail descarta <style> em parte dos casos: se o layout dependesse dele,
    a mensagem chegaria desmontada. Ele so declara tema."""
    html = painel.documento("t", [painel.kpis([{"rotulo": "a", "valor": 1}])])
    bloco = html.split("<style>")[1].split("</style>")[0]
    for proibido in ("display:", "width:", "padding:", "margin:", "font:"):
        assert proibido not in bloco, f"{proibido} nao pode viver no <style>"


def test_grafico_de_barras_e_feito_de_celula_e_nao_de_imagem():
    """Cliente de e-mail bloqueia imagem remota, e Outlook nao renderiza SVG:
    um grafico que chega como retangulo cinza e pior que nenhum."""
    html = painel.barras([{"rotulo": "27/08", "valor": 27},
                          {"rotulo": "26/08", "valor": 12}])
    assert "<img" not in html and "<svg" not in html
    assert "width=" in html and "%" in html


def test_a_barra_e_proporcional_ao_MAIOR_e_nao_a_cem():
    """Com escala fixa em 100, valores pequenos somem e o grafico nao diz
    nada."""
    html = painel.barras([{"rotulo": "a", "valor": 10},
                          {"rotulo": "b", "valor": 5}])
    assert 'width="100%"' in html.replace('width="100%" cellpadding', "X")  # a maior
    assert 'width="50%"' in html


def test_dia_sem_movimento_continua_ocupando_a_linha():
    """Zero e informacao: sumir com a linha faria o dia parado desaparecer do
    grafico como se nao tivesse existido."""
    html = painel.barras([{"rotulo": "a", "valor": 0},
                          {"rotulo": "b", "valor": 4}])
    # uma linha por item; a barra desenhada tem tabela propria por dentro,
    # entao a contagem e das linhas que carregam o ROTULO
    assert html.count('width="130"') == 2
    assert "border-bottom:1px dashed" in html, "o dia zerado perdeu a linha"
