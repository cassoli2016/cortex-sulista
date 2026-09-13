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


def test_nao_ha_imagem_EXTERNA():
    """Imagem REMOTA continua proibida: e bloqueada por padrao na maior parte
    dos clientes e ainda entregaria ao servidor quem abriu e quando.

    A logo do CORTEX (desde 03/09/2026) e a excecao que confirma a regra: ela
    vai EMBUTIDA na mensagem (`cid:`), nao por URL."""
    html = painel.documento("t", [painel.kpis([{"rotulo": "a", "valor": "1"}])])
    assert not re.search(r'(src|background)\s*=\s*"https?://', html)
    for m in re.finditer(r'<img[^>]*src="([^"]+)"', html):
        assert m.group(1).startswith("cid:"), m.group(1)


def test_a_logo_vai_embutida_e_o_nome_vai_em_TEXTO():
    """A logo e decoracao, nao conteudo. Com a imagem bloqueada — o padrao em
    boa parte dos clientes — o cabecalho continua dizendo de quem e a
    mensagem."""
    html = painel.documento("Relatorio", [])
    assert f'src="cid:{painel.LOGO_CID}"' in html
    assert 'alt="CÓRTEX"' in html
    assert "CÓRTEX · SULISTA" in html, "o nome sumiu do cabecalho"


def test_a_faixa_do_cabecalho_usa_a_COR_DA_MARCA():
    """03/09/2026: o dono da marca disse que o e-mail parecia apagado. A
    identidade saiu de um filete de 4 px para a faixa inteira. A regra antiga
    (nenhuma area escura) foi trocada com o risco na mesa, nao por descuido —
    ver o docstring de `painel.cabecalho`."""
    html = painel.documento("Relatorio", [])
    assert f"background:{painel.MARCA}" in html
    # e a defesa contra o tema escuro do cliente repoe a FAIXA, nao o branco
    assert f"[data-ogsc] .faixa, [data-ogsb] .faixa {{background:{painel.MARCA}" in html


def test_a_tinta_sobre_a_faixa_tem_contraste():
    """Texto sobre a faixa nao pode virar decoracao ilegivel. 4,5:1 e o piso."""
    def lum(hexa):
        c = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def razao(a, b):
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    for tinta in (painel.BRANCO, painel.FAIXA_OLHO, painel.FAIXA_SUB):
        r = razao(tinta, painel.MARCA)
        assert r >= 4.5, f"{tinta} sobre {painel.MARCA} da {r:.2f}:1"


def test_e_mail_sem_a_logo_no_disco_continua_saindo():
    """Arquivo de imagem que sumiu e uma mensagem menos bonita; mensagem que
    nao sai e um problema."""
    original = painel.LOGO_ARQUIVO
    try:
        painel.LOGO_ARQUIVO = original.parent / "nao-existe-xyz.png"
        assert painel.logo_bytes() == b""
        assert painel.LOGO_CID not in painel.imagens_embutidas()
        assert "CÓRTEX · SULISTA" in painel.documento("t", [])
    finally:
        painel.LOGO_ARQUIVO = original


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
    APAGOU a faixa do cabecalho - o !important vence o estilo inline, e o
    titulo virou branco sobre branco. Visto no navegador em tema escuro.
    Defender-se do tema escuro e DECLARAR o tema, nunca reescrever por cima da
    paleta que ja esta correta.

    A FAIXA JA FOI NAVY (ate 29/08/2026), depois branca com filete, e desde
    03/09/2026 e a cor da marca — o dono dela disse que o e-mail parecia
    apagado. O que este teste guarda atravessou as tres versoes e nao muda: a
    defesa DECLARA o tema e repoe a cor da faixa, nunca reescreve a paleta com
    `!important` generico. Por isso ele segue o TOKEN, nao a cor literal."""
    html = painel.documento("t", [])
    assert "color-scheme" in html and "light only" in html
    assert "background-color:inherit" not in html
    assert "!important" not in html.split("</style>")[0].replace(
        "[data-ogsc]", "").replace("[data-ogsb]", "") or "data-ogsc" in html
    # o corpo da mensagem continua CLARO: o que virou colorido foi o cabecalho
    assert f"background:{painel.BRANCO}" in html


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


# ── O PONTO DE ONTEM ────────────────────────────────────────────────────────
#
# O e-mail existe porque o Globus so enxerga o ponto depois que alguem importa
# o AFD a mao (mediana de 3 dias, maximo de 18): quem nao bateu ontem so
# aparece la na semana seguinte, quando nao ha mais o que perguntar.
#
# E ele e uma lista para CONFERIR, nunca uma lista de faltas — por isso os
# guards abaixo cobram o texto da ressalva e o denominador, e nao so que o
# e-mail sai.

def _ponto(monkeypatch, *, ausentes, esperados=79, atipico=False,
           modo="padrao", locais=None):
    """Arranjo com os dois lados dublados: quem bateu e quem tinha de bater."""
    dia = {
        "dia": "ontem", "data": "2026-09-10", "em_curso": False,
        "kpis": {"pessoas": 82, "batidas": 284, "dentro": 73, "fora": 67,
                 "sem_coordenada": 144, "primeira": "00:16", "ultima": "23:58"},
        "pessoas": [], "locais": locais if locais is not None else [
            {"local": "longe de SBC OPERACIONAL", "situacao": "fora",
             "batidas": 37, "pessoas": 10, "distancia_m": 1885},
            {"local": "PIRAQUARA", "situacao": "dentro", "batidas": 50,
             "pessoas": 21, "distancia_m": 40}],
        "fonte": "duble",
    }
    aus = {
        "dia": "2026-09-10", "em_curso": False, "modo": modo,
        "atipico": atipico, "esperados": esperados, "bateram": 82,
        "ferias": 10, "erp_ate": "2026-09-06", "janela_dias": 28,
        "minimo_dias": 3, "ausentes": ausentes,
    }
    monkeypatch.setattr("api.pontocertificado.painel.do_dia", lambda d: dia)
    monkeypatch.setattr("api.frequencia.ausentes_do_dia", lambda d: aus)
    return relatorios.montar("ponto_do_dia")


_UM = [{"chapa": "003838", "nome": "CAROLINE DE MACEDO BARBOSA",
        "filial": "FILIAL SBC", "funcao": "APRENDIZ ( AUX ESCRITORIO )",
        "vistos": 3, "registro_erp": None}]


def test_o_ponto_de_ontem_nomeia_quem_nao_bateu(monkeypatch):
    r = _ponto(monkeypatch, ausentes=_UM)
    assert "CAROLINE DE MACEDO BARBOSA" in r["html"]
    assert "1 sem batida" in r["assunto"]
    # o cargo inteiro, sem corte no meio do parenteses
    assert "APRENDIZ ( AUX ESCRITORIO )" in r["html"]


def test_o_e_mail_DIZ_que_nao_e_lista_de_faltas(monkeypatch):
    """A frase nao e decoracao: e o que separa um instrumento de uma acusacao
    automatica que chega todo dia de manha na caixa do RH."""
    r = _ponto(monkeypatch, ausentes=_UM)
    texto = r["html"].lower()
    assert "não é uma lista de faltas" in texto
    assert "atestado" in texto and "folga" in texto
    # e diz de onde veio o esperado, porque sem isso o numero nao se confere
    assert "06/09" in r["html"] and "dias iguais da semana" in r["html"]


def test_ninguem_faltando_AINDA_MANDA(monkeypatch):
    """"Todos bateram" e a noticia que o RH quer receber. Sumir nesse dia
    ensina a duvidar do envio no dia seguinte — e no dia em que houver
    ausencia, o e-mail sera arquivado junto com os outros."""
    r = _ponto(monkeypatch, ausentes=[])
    assert r["vazio"] is False
    assert "todos bateram" in r["assunto"].lower()
    assert "79 pessoas esperadas bateram" in r["html"]
    assert relatorios.CATALOGO["ponto_do_dia"]["pular_vazio"] is False


def test_dia_atipico_NAO_lista_ninguem(monkeypatch):
    """Metade do quadro fora no mesmo dia e feriado, parada ou coleta que nao
    rodou. Nomear setenta e nove pessoas seria acusar a casa inteira de
    faltar — e a lista longa e justamente a que ninguem confere."""
    muitos = [{**_UM[0], "chapa": f"{i:06d}", "nome": f"PESSOA {i}"}
              for i in range(60)]
    r = _ponto(monkeypatch, ausentes=muitos, atipico=True)
    assert "PESSOA 1" not in r["html"]
    assert "coleta" in r["html"].lower() and "feriado" in r["html"].lower()
    assert "atípico" in r["assunto"].lower()


def test_o_fora_de_cerca_vem_como_EVOLUCAO_por_cerca(monkeypatch):
    """O total de ontem nao diz o que fazer; a distancia SE REPETINDO diz.

    Onze pessoas a mil oitocentos e oitenta e poucos metros todo dia sao um
    local de trabalho sem cerca cadastrada. A mesma gente com a distancia
    pulando de 2,8 km para 100 km esta em transito, e cerca nenhuma resolve.
    O e-mail precisa levar os dois lados para quem le decidir.
    """
    ev = {"dias": ["2026-09-08", "2026-09-09", "2026-09-10"],
          "rotulos": ["08/09", "09/09", "10/09"], "total": 120,
          "tolerancia": 0.10,
          "cercas": [
              {"cerca": "SBC OPERACIONAL", "serie": [39, 44, 37], "total": 120,
               "pessoas": 11, "distancia_m": 1884,
               "dias_com_movimento": 3, "dias_no_mesmo_lugar": 3},
              {"cerca": "MAXION CRZ", "serie": [5, 7, 6], "total": 18,
               "pessoas": 3, "distancia_m": 51858,
               "dias_com_movimento": 3, "dias_no_mesmo_lugar": 1}]}
    monkeypatch.setattr("api.pontocertificado.painel.fora_por_dia",
                        lambda dias, ate=None: ev)
    r = _ponto(monkeypatch, ausentes=_UM)
    h = r["html"]
    assert "SBC OPERACIONAL" in h and "1,9" in h          # virgula, nao ponto
    assert "39" in h and "44" in h                        # a serie, dia a dia
    assert "3/3" in h and "1/3" in h                      # o que separa os dois
    # e a explicacao do que a coluna significa, sem tag literal
    assert "Mesmo lugar" in h and "&lt;b&gt;" not in h


def test_o_relatorio_nao_derruba_a_rotina(monkeypatch):
    """Ela roda sem ninguem olhando: erro que a derruba some do mundo."""
    def explode(*a, **k):
        raise RuntimeError("ERP fora")
    monkeypatch.setattr("api.pontocertificado.painel.do_dia", explode)
    r = relatorios.montar("ponto_do_dia")
    assert r["html"] and r["texto"] and "falha" in r["assunto"].lower()


# ── O GRAFICO E O MEDIDOR ───────────────────────────────────────────────────
#
# Os dois sao desenhados com CELULA DE TABELA, e nao com img, svg ou canvas.
# Nao e preciosismo: imagem remota e bloqueada por padrao e chega como
# retangulo cinza; Outlook renderiza e-mail com o motor do Word e nao desenha
# SVG. Celula com largura percentual e o unico desenho que todo cliente mostra.

def test_o_grafico_e_o_medidor_sao_TABELA_e_nao_desenho():
    from api.correio import painel as p
    html = (p.barras_empilhadas(
                [{"rotulo": "10/09", "valores": [73, 67, 144]}],
                [{"nome": "Dentro", "cor": p.VERDE},
                 {"nome": "Fora", "cor": p.VERMELHO},
                 {"nome": "Sem GPS", "cor": p.CINZA}])
            + p.medidor(titulo="Dentro da cerca", pct=52.1, texto="x"))
    for proibido in ("<svg", "<img", "<canvas", "display:flex", "display:grid"):
        assert proibido not in html, proibido
    assert "<table" in html and "52,1%" in html      # virgula, nao ponto


def test_o_medidor_sem_base_DIZ_que_nao_sabe():
    """Trilho vazio se le como 0%, que e uma afirmacao. Nao ter base nao e."""
    from api.correio import painel as p
    html = p.medidor(titulo="Dentro da cerca", pct=None, texto="sem batida com GPS")
    # `"0%" not in html` nao serve: a tabela de fora tem width="100%". O que
    # importa e que o NUMERO nao virou zero.
    assert ">—</div>" in html and ">0,0%<" not in html
    assert "dashed" in html          # o trilho vazio se mostra como ausencia


def test_a_barra_do_dia_diz_o_VOLUME_e_a_composicao():
    """A barra inteira e proporcional ao maior DIA; os pedacos, ao proprio dia.
    Com escala fixa em 100%, um dia de 5 batidas e um de 350 sairiam do mesmo
    tamanho e o grafico mentiria sobre o movimento."""
    from api.correio import painel as p
    html = p.barras_empilhadas(
        [{"rotulo": "grande", "valores": [200, 100, 50]},
         {"rotulo": "pequeno", "valores": [2, 1, 1]}],
        [{"nome": "a", "cor": p.VERDE}, {"nome": "b", "cor": p.VERMELHO},
         {"nome": "c", "cor": p.CINZA}])
    import re
    # so as tabelas DA BARRA: a de fora tambem e width="100%", e pega-la
    # faria o guard passar por acidente.
    larguras = re.findall(
        r'<table role="presentation" width="(\d+)%" cellpadding="0" '
        r'cellspacing="0"><tr>', html)
    assert larguras == ["100", "1"], larguras


def test_o_e_mail_do_ponto_leva_o_medidor_e_o_grafico(monkeypatch):
    comp = {"rotulos": ["09/09", "10/09"],
            "serie": [{"dia": "2026-09-09", "rotulo": "09/09", "dentro": 81,
                       "fora": 72, "sem_coordenada": 133},
                      {"dia": "2026-09-10", "rotulo": "10/09", "dentro": 73,
                       "fora": 67, "sem_coordenada": 144}],
            "dentro": 154, "fora": 139, "sem_coordenada": 277,
            "com_gps": 293, "total": 570,
            "pct_dentro": 52.6, "pct_sem_coordenada": 48.6}
    monkeypatch.setattr("api.pontocertificado.painel.composicao_por_dia",
                        lambda dias, ate=None: comp)
    r = _ponto(monkeypatch, ausentes=_UM)
    h = r["html"]
    assert "52,6%" in h                       # o medidor, com virgula
    assert "154 de 293" in h                  # o denominador que ele usa
    assert "277" in h and "48,6%" in h        # e o que ficou de fora, ao lado
    assert "09/09" in h and "10/09" in h      # a serie diaria
