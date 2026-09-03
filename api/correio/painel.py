"""Monta o HTML dos relatórios que saem por e-mail.

POR QUE ESTE ARQUIVO NÃO PARECE COM O RESTO DO PAINEL
=====================================================
E-mail não é navegador. O que vale no `index.html` — grid, flexbox, variáveis
CSS, folha de estilo no `<head>` — não vale aqui:

- **Outlook para Windows renderiza com o motor do Word.** Não entende `flex`
  nem `grid`, e ignora `padding` em vários elementos. Layout de e-mail se faz
  com `<table>`, que é o único componente que todos os clientes concordam em
  desenhar do mesmo jeito. Não é nostalgia: é o denominador comum.
- **Estilo tem de ser INLINE.** Gmail remove `<style>` do `<head>` em parte
  dos casos (notadamente no app e no encaminhamento), e a mensagem chegaria
  sem formatação nenhuma — que é pior do que nunca ter tido.
- **Variável CSS não existe.** Os tokens do design system entram como
  hexadecimal literal, e por isso ficam nomeados em constantes aqui: quando a
  marca mudar, muda num lugar só.
- **Imagem externa costuma vir bloqueada.** Nada de gráfico como `<img>` de
  URL: o que precisa ser visto vem como texto, número e barra desenhada com
  `<td>` de largura percentual.

LARGURA de 600px porque é o que cabe no painel de leitura do Outlook e na
tela de um celular sem redução. Acima disso o cliente reduz a página inteira
e a tipografia fica ilegível justamente em quem lê no telefone.

TEXTO PURO SEMPRE JUNTO. `envio.enviar` manda as duas versões; a de texto não
é enfeite de acessibilidade, é o que aparece na pré-visualização da caixa de
entrada e o que sobra quando o cliente recusa HTML.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Tokens do design system, em hexadecimal — ver o cabeçalho do módulo.
#
# ── E-MAIL DO CÓRTEX NÃO TEM ÁREA ESCURA ────────────────────────────────────
# Regra da casa, e ela já foi quebrada duas vezes: a faixa do cabeçalho era
# navy e o boas-vindas nasceu copiando o padrão. Fundo escuro em e-mail não é
# só questão de gosto — ele imprime mal, some no modo de leitura de vários
# clientes e briga com o tema escuro do aparelho, que já inverte tudo por
# conta própria.
#
# A CONSEQUÊNCIA DIRETA: o amarelo da marca NÃO PODE APARECER. Ele tem 1,44:1
# de contraste no branco e vira um borrão ilegível — ele existia aqui porque
# havia fundo escuro embaixo dele. Sem o fundo escuro, o accent é o LARANJA,
# que é o que o design system manda usar em superfície clara.
#
# Texto continua escuro, evidentemente: a regra é sobre ÁREA (fundo, faixa,
# bloco), não sobre tinta.
TINTA_FORTE = "#14181D"          # texto, nunca fundo
AZUL_GRAFICO = "#5F87AC"         # navy-400: barra sobre claro.
# O navy-500 (#38648D) era escuro demais para a regra — uma barra cheia
# dele ainda é um bloco escuro no meio da mensagem. O 400 lê igual de bem
# como barra e não cria área escura nenhuma.
LARANJA = "#E85D10"

# ── A MARCA NO E-MAIL (pedido do usuário, 30/08/2026) ───────────────────────
# O e-mail usava a paleta neutra e não carregava identidade nenhuma.
#
# CORREÇÃO DO USUÁRIO, NO MEIO DO TRABALHO: **não há amarelo na marca da
# Sulista.** Eu tinha posto `#FFD31C` como filete, seguindo o que o CLAUDE.md
# afirmava ("amarelo Sulista = --brand"). A afirmação do projeto estava errada,
# e quem é dono da marca disse.
#
# A PALETA REAL foi então MEDIDA nos arquivos de marca do próprio repositório
# (favicon.png, icon-192, icon-512, apple-touch), e os quatro concordam: o
# símbolo tem dois tons sobre branco — vermelho tijolo `#942821` (62% dos
# pixels) e um quase-preto arroxeado `#1E172F` (37%). Nenhum amarelo.
#
# E o e-mail é o lugar EXATO da marca: o vermelho rende **8,12:1 sobre branco**
# — no painel ele daria 1,92:1 sobre o navy da barra lateral, e por isso lá
# existe uma versão clareada. Aqui a superfície é branca, então entra o tom
# original, sem adaptação.
#
#   MARCA      — filete do topo, olho e accent. É a identidade chegando.
#   MARCA_INK  — tinta do título (17:1 sobre branco). É o outro tom do símbolo,
#                e escurece o título sem virar área escura.
#
# Como ÁREA os dois continuam proibidos: uma faixa cheia é o bloco escuro que a
# regra da casa veta, e o teste de luminância a barraria.
#
# Não há LOGO, e não é por esquecimento: o único arquivo é
# `sulista-logo-branco.svg`, branco puro e invisível aqui; imagem em e-mail vem
# bloqueada por padrão em boa parte dos clientes; e o Outlook não renderiza
# SVG. A identidade fica no TIPOGRÁFICO e na COR, que chegam em 100% dos casos.
MARCA = "#942821"                # vermelho do símbolo — filete, olho, accent
MARCA_INK = "#1E172F"            # o segundo tom do símbolo — tinta de título
NAVY = "#17344F"                 # navy-700: tinta de título, nunca fundo
VERDE = "#1E7F4F"
AMBAR = "#B97709"
VERMELHO = "#C03221"
TINTA = "#14181D"
CINZA = "#6B7580"
BORDA = "#E3E8EE"
FUNDO = "#F4F6F8"
BRANCO = "#FFFFFF"

# ── A LOGO DO CÓRTEX NO E-MAIL ────────────────────────────────────────────
# É um QUADRO do próprio `api/static/anel.js` (o mesmo código que anima a marca
# no login), gerado uma vez e guardado como PNG. Não é um desenho novo: marca
# redesenhada à mão envelhece separado da marca do produto.
#
# VAI EMBUTIDA (anexo `cid:`), nunca por URL. Imagem remota em e-mail é
# bloqueada por padrão na maior parte dos clientes, e ainda entregaria ao
# servidor um sinal de quem abriu e quando — o que a mensagem não precisa
# saber. PNG e não SVG porque o Outlook usa o motor do Word e não renderiza
# SVG.
#
# E o cabeçalho NÃO DEPENDE DELA: o nome "CÓRTEX · SULISTA" está em texto ao
# lado, e o `alt` repete a marca. Com a imagem bloqueada a mensagem continua
# assinada — a identidade que chega em 100% dos casos continua sendo a tinta e
# o tipo.
LOGO_CID = "cortex-selo"
LOGO_ARQUIVO = Path(__file__).resolve().parent.parent / "static" / "cortex-selo.png"


def logo_bytes() -> bytes:
    """O PNG do selo. Devolve vazio se o arquivo sumir — e-mail sem logo é uma
    mensagem menos bonita; e-mail que não sai é um problema."""
    try:
        return LOGO_ARQUIVO.read_bytes()
    except OSError:
        return b""


# Imagens que o layout pode referenciar por `cid:`. `api/correio/envio.py` lê
# este mapa e embute só as que o HTML realmente usa.
def imagens_embutidas() -> dict:
    dados = logo_bytes()
    return {LOGO_CID: dados} if dados else {}

# Pilha com fallback: nenhum cliente de e-mail baixa fonte da web, então a
# Saira do painel não chega aqui. O que se pode garantir é a família.
FONTE = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,"
         "Arial,sans-serif")
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

CORES_ESTADO = {"ok": VERDE, "warn": AMBAR, "bad": VERMELHO, "neutro": CINZA}


class Html(str):
    """Trecho JÁ seguro, que a tabela pode inserir sem escapar.

    Existe porque a alternativa era ADIVINHAR: a tabela deixava passar sem
    escapar tudo que começasse com "<", para os selos coloridos funcionarem.
    Um teste com `<script>alert(1)</script>` numa célula mostrou o buraco na
    hora — começa com "<" e ia inteiro para o e-mail. Quem produz HTML seguro
    diz isso com o tipo; o resto é sempre escapado.
    """


def _esc(t) -> str:
    return (str(t if t is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def brl(v: float | None, casas: int = 0) -> str:
    if v is None:
        return "—"
    s = f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",")
    return "R$ " + s.replace("X", ".")


def inteiro(v) -> str:
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


# Tinta sobre a faixa da marca. Não é branco puro no olho e no subtítulo: o
# branco cheio ao lado do branco cheio do título achata a hierarquia. São dois
# claros derivados do próprio tijolo, e os dois passam de 4,5:1 sobre #942821.
FAIXA_OLHO = "#F3C9C4"
FAIXA_SUB = "#EFD3CF"


def cabecalho(titulo: str, subtitulo: str = "") -> str:
    """Cabeçalho com a FAIXA da marca, a logo do CÓRTEX e o título.

    MUDOU EM 03/09/2026, a pedido de quem é dono da marca: "as cores parecem
    muito apagadas". A versão anterior punha a identidade só num filete de 4 px
    sobre branco — correto pela regra antiga ("e-mail do CÓRTEX não tem área
    escura") e, na prática, uma mensagem que não parecia de ninguém.

    A REGRA ANTIGA NÃO ERA CAPRICHO, e o risco que ela evitava continua de pé:
    Gmail e Outlook INVERTEM a paleta da mensagem quando o aparelho está em
    tema escuro, e o Outlook renderiza com o motor do Word. Uma faixa cheia
    pode sair remendada. O que dá para fazer está feito — as metas
    `color-scheme: light only` declaram o tema, e o bloco `[data-ogsc]` repõe a
    cor da faixa para o Outlook.com, que marca a mensagem quando reescreve as
    cores. É mitigação, não garantia, e a decisão de correr o risco foi tomada
    com ele na mesa.

    A LOGO É DECORAÇÃO, NÃO CONTEÚDO: o nome vai em texto ao lado dela. Com a
    imagem bloqueada — o padrão em boa parte dos clientes — o cabeçalho
    continua dizendo de quem é a mensagem.
    """
    sub = (f'<div style="font:400 12.5px/1.4 {FONTE};color:{FAIXA_SUB};'
           f'margin-top:4px">{_esc(subtitulo)}</div>') if subtitulo else ""
    return f"""
<tr><td class="faixa" style="background:{MARCA};padding:0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
   <td width="76" style="padding:18px 0 18px 22px;vertical-align:middle">
     <img src="cid:{LOGO_CID}" width="54" height="54" alt="CÓRTEX"
          style="display:block;border-radius:11px;border:0"></td>
   <td style="padding:18px 22px 18px 14px;vertical-align:middle">
     <div style="font:700 10.5px/1 {FONTE};letter-spacing:.24em;
                 color:{FAIXA_OLHO};text-transform:uppercase">CÓRTEX · SULISTA</div>
     <div style="font:700 21px/1.25 {FONTE};color:{BRANCO};margin-top:6px">
       {_esc(titulo)}</div>{sub}
   </td>
  </tr></table>
</td></tr>
<tr><td style="border-top:3px solid {MARCA_INK};font-size:0;line-height:0">&nbsp;</td></tr>"""


def secao(titulo: str, hint: str = "") -> str:
    h = (f'<span style="font:400 12px/1 {FONTE};color:{CINZA};'
         f'font-weight:400"> · {_esc(hint)}</span>') if hint else ""
    # O titulo de secao passou a ser TIJOLO com filete proprio: era cinza com
    # borda de 1 px, e num e-mail de tres secoes nada separava uma da outra.
    return f"""
<tr><td style="padding:26px 26px 0">
  <div style="font:700 11.5px/1 {FONTE};letter-spacing:.12em;color:{MARCA};
              text-transform:uppercase;border-bottom:2px solid {MARCA};
              padding-bottom:8px">{_esc(titulo)}{h}</div>
</td></tr>"""


def kpis(itens: list[dict]) -> str:
    """Cartões de indicador, DOIS POR LINHA.

    Não é escolha estética: quatro colunas de 150px viram 150px de largura
    real no celular, e o número quebra no meio. Duas colunas continuam
    legíveis nos dois lugares — e é por isso que a lista é fatiada em pares
    aqui, e não deixada para o cliente decidir.
    """
    if not itens:
        return ""
    linhas = []
    for i in range(0, len(itens), 2):
        par = itens[i:i + 2]
        celulas = []
        for k in par:
            cor = CORES_ESTADO.get(k.get("estado") or "neutro", TINTA)
            sub = (f'<div style="font:400 12px/1.45 {FONTE};color:{CINZA};'
                   f'margin-top:6px">{_esc(k.get("sub"))}</div>'
                   if k.get("sub") else "")
            celulas.append(f"""
<td width="50%" valign="top" style="padding:0 6px 12px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{BRANCO};border:1px solid {BORDA};border-radius:8px">
    <tr><td style="padding:14px 16px">
      <div style="font:600 11px/1.3 {FONTE};color:{CINZA};
                  text-transform:uppercase;letter-spacing:.06em">
        {_esc(k.get('rotulo'))}</div>
      <div style="font:700 26px/1.15 {MONO};color:{cor};margin-top:7px">
        {_esc(k.get('valor'))}</div>{sub}
    </td></tr>
  </table></td>""")
        if len(par) == 1:
            celulas.append('<td width="50%"></td>')
        linhas.append("<tr>" + "".join(celulas) + "</tr>")
    return f"""
<tr><td style="padding:16px 26px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    {''.join(linhas)}
  </table></td></tr>"""


def tabela(colunas: list[str], linhas: list[list], *, alinha_dir=(),
           vazio: str = "Nada a listar.") -> str:
    """Tabela simples. `alinha_dir` são os índices numéricos.

    Sem `<div>` de rolagem: e-mail não rola na horizontal. Tabela que não cabe
    é tabela com colunas demais — o corte tem de ser na hora de escolher o que
    mostrar, não na hora de desenhar.
    """
    if not linhas:
        return (f'<tr><td style="padding:12px 26px 0;font:400 13px/1.5 {FONTE};'
                f'color:{CINZA}">{_esc(vazio)}</td></tr>')
    th = "".join(
        f'<th align="{"right" if i in alinha_dir else "left"}" '
        f'style="font:700 10.5px/1 {FONTE};letter-spacing:.06em;color:{CINZA};'
        f'text-transform:uppercase;padding:0 10px 8px 0;'
        f'border-bottom:1px solid {BORDA}">{_esc(c)}</th>'
        for i, c in enumerate(colunas))
    trs = []
    for n, lin in enumerate(linhas):
        fundo = FUNDO if n % 2 else BRANCO
        tds = "".join(
            f'<td align="{"right" if i in alinha_dir else "left"}" '
            f'style="font:400 13px/1.45 {MONO if i in alinha_dir else FONTE};'
            f'color:{TINTA};padding:9px 10px 9px 0;'
            f'border-bottom:1px solid {BORDA}">'
            f'{c if isinstance(c, Html) else _esc(c)}</td>'
            for i, c in enumerate(lin))
        trs.append(f'<tr style="background:{fundo}">{tds}</tr>')
    return f"""
<tr><td style="padding:14px 26px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>{th}</tr>{''.join(trs)}
  </table></td></tr>"""


def chip(texto: str, estado: str = "neutro") -> Html:
    """Selo colorido. Devolve `Html` — é assim que a tabela sabe que este
    trecho já está seguro, sem precisar farejar o conteúdo."""
    cor = CORES_ESTADO.get(estado, CINZA)
    return Html(f'<span style="display:inline-block;font:700 11px/1 {FONTE};'
                f'color:{cor};border:1px solid {cor};border-radius:999px;'
                f'padding:4px 9px">{_esc(texto)}</span>')


def paragrafo(texto: str, *, destaque: bool = False) -> str:
    borda = f"border-left:3px solid {MARCA};" if destaque else ""
    fundo = f"background:{FUNDO};" if destaque else ""
    return f"""
<tr><td style="padding:14px 26px 0">
  <div style="{fundo}{borda}padding:{'12px 14px' if destaque else '0'};
              font:400 13.5px/1.6 {FONTE};color:{TINTA};border-radius:6px">
    {_esc(texto)}</div></td></tr>"""


def barras(itens: list[dict], *, unidade: str = "") -> str:
    """Gráfico de barras horizontais desenhado com CÉLULAS DE TABELA.

    Não é `<img>` de propósito: cliente de e-mail bloqueia imagem remota por
    padrão, e um gráfico que chega como retângulo cinza é pior que nenhum.
    Não é SVG porque Outlook não renderiza SVG em e-mail. Célula com largura
    percentual é o único desenho que todos concordam em mostrar.

    Cada item: {rotulo, valor, total?, cor?, sub?}. A barra é proporcional ao
    MAIOR valor da lista, não a 100%: com valores pequenos e escala fixa todas
    as barras somem e o gráfico não diz nada.
    """
    if not itens:
        return ""
    topo = max((float(i.get("valor") or 0) for i in itens), default=0) or 1
    linhas = []
    for i in itens:
        v = float(i.get("valor") or 0)
        pct = max(round(100 * v / topo), 1) if v else 0
        cor = i.get("cor") or AZUL_GRAFICO
        rotulo = _esc(i.get("rotulo"))
        num = i.get("texto") or (inteiro(v) + (f" {unidade}" if unidade else ""))
        # a barra vazia ainda ocupa a linha: dia sem movimento e informacao
        barra = (f'<table role="presentation" width="100%" cellpadding="0" '
                 f'cellspacing="0"><tr>'
                 f'<td width="{pct}%" style="background:{cor};height:14px;'
                 f'border-radius:3px;font-size:0;line-height:0">&nbsp;</td>'
                 f'<td style="font-size:0;line-height:0">&nbsp;</td></tr></table>'
                 if pct else
                 f'<div style="height:14px;border-bottom:1px dashed {BORDA}"></div>')
        linhas.append(f"""
<tr>
  <td width="130" valign="middle" style="font:400 12.5px/1.3 {FONTE};
      color:{TINTA};padding:5px 10px 5px 0;white-space:nowrap">{rotulo}</td>
  <td valign="middle" style="padding:5px 10px 5px 0">{barra}</td>
  <td width="86" align="right" valign="middle" style="font:600 12.5px/1.3 {MONO};
      color:{TINTA};padding:5px 0">{_esc(num)}</td>
</tr>""")
    return f"""
<tr><td style="padding:14px 26px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    {''.join(linhas)}
  </table></td></tr>"""


def legenda(itens: list[tuple[str, str]]) -> str:
    """Chaves de cor do gráfico. Sem ela, barra colorida é enfeite."""
    partes = "".join(
        f'<span style="display:inline-block;margin-right:14px">'
        f'<span style="display:inline-block;width:9px;height:9px;'
        f'background:{cor};border-radius:2px"></span>'
        f'<span style="font:400 11.5px/1 {FONTE};color:{CINZA};'
        f'padding-left:5px">{_esc(rot)}</span></span>'
        for rot, cor in itens)
    return (f'<tr><td style="padding:8px 26px 0">{partes}</td></tr>')


def botao(texto: str, url: str) -> str:
    """Botão de ação. `<td>` com fundo, não `<button>` nem imagem: botão de
    e-mail que depende de CSS de borda some no Outlook, e como imagem some em
    quem bloqueia imagem — que é a maioria, por padrão."""
    return f"""
<tr><td style="padding:18px 26px 4px">
  <table role="presentation" cellpadding="0" cellspacing="0"><tr>
    <td style="background:{LARANJA};border-radius:7px">
      <a href="{_esc(url)}" style="display:inline-block;padding:12px 26px;
         font:700 14.5px/1 {FONTE};color:{BRANCO};text-decoration:none">
        {_esc(texto)}</a></td>
  </tr></table>
</td></tr>"""


def campos(itens: list[tuple[str, str]], *, titulo: str = "",
           mono: tuple = ()) -> str:
    """Caixa de rótulo → valor, para dado que a pessoa vai LER e DIGITAR.

    `mono` marca os índices que saem em monoespaçada: endereço, usuário e
    senha são copiados à mão, e em fonte proporcional o l vira 1 e o O vira 0
    justamente no momento em que errar custa um chamado.
    """
    tit = (f'<div style="font:700 11px/1 {FONTE};letter-spacing:.16em;'
           f'color:{CINZA};text-transform:uppercase;margin:0 0 10px">'
           f'{_esc(titulo)}</div>') if titulo else ""
    linhas = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font:400 12.5px/1.4 {FONTE};'
        f'color:{CINZA};vertical-align:top;white-space:nowrap">{_esc(r)}</td>'
        f'<td style="padding:6px 0;font:{"700 15px/1.4 " + MONO if i in mono else "400 14px/1.5 " + FONTE};'
        f'color:{TINTA};word-break:break-all">{v if isinstance(v, Html) else _esc(v)}</td></tr>'
        for i, (r, v) in enumerate(itens))
    return f"""
<tr><td style="padding:14px 26px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{FUNDO};border:1px solid {BORDA};border-radius:8px">
   <tr><td style="padding:16px 18px">{tit}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {linhas}</table>
   </td></tr></table>
</td></tr>"""


def rodape(origem: str, *, agendado: bool = True) -> str:
    """Rodapé comum. `agendado=False` para mensagem DISPARADA POR UMA AÇÃO.

    O convite a "Gestão › Integrações" só é verdade no e-mail AGENDADO, que é
    o que tem horário, lista de destinatários e um botão de desligar naquela
    tela. Numa mensagem disparada por ação — boas-vindas, redefinição de
    senha, mensagem do CRM — não há horário nem lista: o destinatário é quem
    pediu ou quem foi cadastrado, e não existe nada para mudar lá. Pior no
    CRM, que sai para CONTATO DE CLIENTE: mandar alguém de fora "entrar no
    painel" é instrução impossível e ainda conta como navegamos por dentro.
    """
    quando = datetime.now().strftime("%d/%m/%Y às %H:%M")
    gerencia = ("Para mudar horário, destinatários ou parar o envio, entre no "
                "painel em <b>Gestão › Integrações</b>." if agendado else "")
    return f"""
<tr><td style="padding:26px 26px 24px">
  <div style="border-top:1px solid {BORDA};padding-top:14px;
              font:400 11.5px/1.6 {FONTE};color:{CINZA}">
    Gerado pelo CÓRTEX em {quando} · fonte: {_esc(origem)}<br>
    Mensagem automática. {gerencia}
  </div></td></tr>"""


def documento(titulo: str, blocos: list[str], *, subtitulo: str = "",
              origem: str = "", agendado: bool = True) -> str:
    """Envelope. `role="presentation"` em toda tabela de layout: sem isso o
    leitor de tela anuncia "tabela de 3 colunas" a cada moldura."""
    corpo = "".join(blocos)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<title>{_esc(titulo)}</title>
<!-- MODO ESCURO DO CLIENTE. Gmail e Outlook INVERTEM as cores da mensagem
     quando o aparelho esta em tema escuro: o fundo branco vira quase preto e
     o cliente reescreve a paleta inteira - o resultado nao e o design system
     de ninguem. E a razao a mais para a mensagem nao ter area escura PROPRIA:
     ela ja corre o risco de ganhar uma sem pedir. As
     duas metas acima declaram que a mensagem SO tem tema claro, e este bloco
     e a segunda linha de defesa para quem le a meta e ignora. Ele NAO carrega
     regra de layout: o layout inteiro esta inline, e continua de pe se o
     cliente jogar este bloco fora (que e o que o Gmail faz as vezes). -->
<style>
  :root{{color-scheme:light only;supported-color-schemes:light only}}
  /* NADA de `background:inherit !important` aqui. A primeira versao deste
     bloco fazia exatamente isso e APAGOU a faixa navy do cabecalho - o
     `!important` vence o estilo inline, e o titulo virou branco sobre branco.
     A defesa contra o tema escuro e DECLARAR o tema (as metas acima), nunca
     reescrever a paleta por cima da que ja esta correta.
     O `[data-ogsc]` e a marca que o Outlook.com poe quando reescreve as
     cores: para ele repomos o fundo claro, um por um, sem tocar no resto. */
  [data-ogsc] .corpo, [data-ogsb] .corpo {{background:{BRANCO} !important}}
  [data-ogsc] .fundo, [data-ogsb] .fundo {{background:{FUNDO} !important}}
  [data-ogsc] .faixa, [data-ogsb] .faixa {{background:{MARCA} !important}}
</style></head>
<body style="margin:0;padding:0;background:{FUNDO};">
<table role="presentation" class="fundo" width="100%" cellpadding="0"
       cellspacing="0" style="background:{FUNDO};padding:20px 10px">
 <tr><td align="center">
  <table role="presentation" class="corpo" width="600" cellpadding="0"
         cellspacing="0"
         style="width:600px;max-width:100%;background:{BRANCO};
                border:1px solid {BORDA};border-radius:10px;overflow:hidden">
   {cabecalho(titulo, subtitulo)}
   {corpo}
   {rodape(origem or 'painel CÓRTEX', agendado=agendado)}
  </table>
 </td></tr>
</table></body></html>"""
