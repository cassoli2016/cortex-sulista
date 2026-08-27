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

# Tokens do design system, em hexadecimal — ver o cabeçalho do módulo.
NAVY = "#14181D"
NAVY_MEDIO = "#2C3742"
BRAND = "#FFD31C"
LARANJA = "#E85D10"
VERDE = "#1E7F4F"
AMBAR = "#B97709"
VERMELHO = "#C03221"
TINTA = "#14181D"
CINZA = "#6B7580"
BORDA = "#E3E8EE"
FUNDO = "#F4F6F8"
BRANCO = "#FFFFFF"

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


def cabecalho(titulo: str, subtitulo: str = "") -> str:
    """Faixa escura com o nome do relatório. O amarelo da marca só aparece
    sobre fundo escuro — no claro ele tem contraste de 1,44:1 e some."""
    sub = (f'<div style="font:400 13px/1.4 {FONTE};color:#B9C2CC;'
           f'margin-top:5px">{_esc(subtitulo)}</div>') if subtitulo else ""
    return f"""
<tr><td class="faixa" style="background:{NAVY};padding:22px 26px 20px">
  <div style="font:700 11px/1 {FONTE};letter-spacing:.22em;color:{BRAND};
              text-transform:uppercase">CÓRTEX · SULISTA</div>
  <div style="font:700 21px/1.25 {FONTE};color:{BRANCO};margin-top:9px">
    {_esc(titulo)}</div>{sub}
</td></tr>"""


def secao(titulo: str, hint: str = "") -> str:
    h = (f'<span style="font:400 12px/1 {FONTE};color:{CINZA};'
         f'font-weight:400"> · {_esc(hint)}</span>') if hint else ""
    return f"""
<tr><td style="padding:26px 26px 0">
  <div style="font:700 11px/1 {FONTE};letter-spacing:.12em;color:{CINZA};
              text-transform:uppercase;border-bottom:1px solid {BORDA};
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
    borda = f"border-left:3px solid {LARANJA};" if destaque else ""
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
        cor = i.get("cor") or NAVY_MEDIO
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


def rodape(origem: str) -> str:
    quando = datetime.now().strftime("%d/%m/%Y às %H:%M")
    return f"""
<tr><td style="padding:26px 26px 24px">
  <div style="border-top:1px solid {BORDA};padding-top:14px;
              font:400 11.5px/1.6 {FONTE};color:{CINZA}">
    Gerado pelo CÓRTEX em {quando} · fonte: {_esc(origem)}<br>
    Mensagem automática. Para mudar horário, destinatários ou parar o envio,
    entre no painel em <b>Gestão › Integrações</b>.
  </div></td></tr>"""


def documento(titulo: str, blocos: list[str], *, subtitulo: str = "",
              origem: str = "") -> str:
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
     quando o aparelho esta em tema escuro: o fundo branco vira quase preto, o
     navy da faixa clareia e o amarelo da marca fica ilegivel - o cliente
     reescreve a paleta e o resultado nao e o design system de ninguem. As
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
  [data-ogsc] .faixa, [data-ogsb] .faixa {{background:{NAVY} !important}}
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
   {rodape(origem or 'painel CÓRTEX')}
  </table>
 </td></tr>
</table></body></html>"""
