# -*- coding: utf-8 -*-
"""O anexo do aviso da 3S: a lista de placas que não comunicam.

POR QUE PDF e não planilha: o anexo é lido no CELULAR, dentro do grupo. PDF
abre sem app nenhum; .xlsx pede um instalado, e o anexo que não abre não é
anexo. A planilha ganharia em filtrar — mas quem filtra faz isso no painel, que
tem a mesma lista com filtro de verdade.

O QUE O ANEXO NÃO FAZ: dizer que o equipamento está com defeito. Ele lista
placa e desde quando, separando quem NUNCA comunicou de quem comunicava e
parou. A primeira coluna dessas é provisionamento, contrato ou aparelho que não
existe; a segunda é falha. São cobranças diferentes, e misturá-las numa lista
só faria a 3S responder a única coisa fácil.

A MARCA É A DA CASA (#942821 sobre branco). Sem logo embutida de propósito:
o anexo sai do servidor todo dia e uma imagem que falta transforma o PDF em
página com um X no meio — o nome em texto não falha.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as _canvas

MARCA = colors.HexColor("#942821")
TINTA = colors.HexColor("#14181D")
CINZA = colors.HexColor("#636C76")
LINHA = colors.HexColor("#D8DDE2")

#: Como cada situação se chama para quem vai cobrar. O texto é o da tela, não
#: o da coluna do banco: "mudo15" não quer dizer nada para quem lê no celular.
TITULOS = {
    "nunca": ("NUNCA COMUNICARAM",
              "Sem nenhuma posição registrada. Verificar instalação, "
              "ativação e contrato."),
    "mudo15": ("SEM COMUNICAR HÁ MAIS DE 15 DIAS",
               "Já comunicaram e pararam. Verificar equipamento."),
    "parou": ("PARARAM NOS ÚLTIMOS 15 DIAS",
              "Silêncio recente — pode ser carreta parada em pátio."),
}

_LARG, _ALT = A4
_MARGEM = 15 * mm


class _Folha:
    """O papel, com cabeçalho e rodapé — e a conta de quanto ainda cabe.

    Existe porque a quebra de página é o defeito clássico desta classe de
    código: a tabela cresce com o dado, e uma lista de 142 placas passa da
    página sem erro nenhum. Aqui a linha só é escrita depois de perguntar se
    cabe, e o cabeçalho da seção se repete na folha nova — senão a página 3
    chega sem dizer do que é a lista.
    """

    def __init__(self, dia: date, alvo: str):
        self.buf = io.BytesIO()
        self.c = _canvas.Canvas(self.buf, pagesize=A4)
        self.dia, self.alvo = dia, alvo
        self.pagina = 0
        self._secao = None          # (titulo, ajuda, quantos), para repetir
        self._nova()

    def _nova(self) -> None:
        if self.pagina:
            self.c.showPage()
        self.pagina += 1
        c = self.c
        c.setFillColor(MARCA)
        c.rect(0, _ALT - 22 * mm, _LARG, 22 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(_MARGEM, _ALT - 13 * mm,
                     "%s — CARRETAS SEM COMUNICAÇÃO" % self.alvo)
        c.setFont("Helvetica", 9)
        c.drawRightString(_LARG - _MARGEM, _ALT - 13 * mm,
                          "Dia fechado: %s" % self.dia.strftime("%d/%m/%Y"))
        c.setFillColor(CINZA)
        c.setFont("Helvetica", 7.5)
        c.drawString(_MARGEM, 10 * mm,
                     "CÓRTEX · Transportadora Sulista · fonte: ERP AVA "
                     "(veiculo × veiculo_posicao) · página %d" % self.pagina)
        self.y = _ALT - 32 * mm
        # A seção continua na folha nova. Sem isto a página 2 abre numa placa
        # solta e quem lê não sabe se aquilo é "nunca comunicou" ou "parou" —
        # que é justamente a distinção que o anexo existe para fazer.
        if self._secao:
            self._escrever_secao(*self._secao, continuacao=True)

    def cabe(self, altura: float) -> None:
        if self.y - altura < 16 * mm:
            self._nova()

    def secao(self, titulo: str, ajuda: str, quantos: int) -> None:
        # A seção nova que cai numa folha cheia vira a PRIMEIRA da folha
        # seguinte, não a continuação de si mesma. Por isso a lembrança é
        # limpa antes de virar a página: senão o `_nova` escreveria o
        # cabeçalho dela já marcado como "continuação", no ponto exato em que
        # a seção está começando.
        if self.y - 20 * mm < 16 * mm:
            self._secao = None
            self._nova()
        self._secao = (titulo, ajuda, quantos)
        self._escrever_secao(titulo, ajuda, quantos)

    def _escrever_secao(self, titulo: str, ajuda: str, quantos: int,
                        continuacao: bool = False) -> None:
        c = self.c
        c.setFillColor(TINTA)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(_MARGEM, self.y, "%s  (%d)%s"
                     % (titulo, quantos, "  — continuação" if continuacao else ""))
        self.y -= 4.5 * mm
        c.setFillColor(CINZA)
        c.setFont("Helvetica", 8)
        c.drawString(_MARGEM, self.y, ajuda)
        self.y -= 3 * mm
        c.setStrokeColor(MARCA)
        c.setLineWidth(1)
        c.line(_MARGEM, self.y, _LARG - _MARGEM, self.y)
        self.y -= 5 * mm

    def linha(self, placa: str, quando: str) -> None:
        self.cabe(6 * mm)
        c = self.c
        c.setFillColor(TINTA)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(_MARGEM + 2 * mm, self.y, placa)
        c.setFillColor(CINZA)
        c.setFont("Helvetica", 9)
        c.drawString(_MARGEM + 45 * mm, self.y, quando)
        c.setStrokeColor(LINHA)
        c.setLineWidth(0.4)
        c.line(_MARGEM, self.y - 1.6 * mm, _LARG - _MARGEM, self.y - 1.6 * mm)
        self.y -= 5.5 * mm

    def fechar(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def gerar(dia: date, placas: list[dict], alvo: str = "3S") -> bytes:
    """O PDF da lista. `placas` vem de `comunicacao_3s.placas_do_dia`."""
    folha = _Folha(dia, alvo)
    for chave in ("nunca", "mudo15", "parou"):
        grupo = [p for p in placas if p["situacao"] == chave]
        if not grupo:
            continue
        titulo, ajuda = TITULOS[chave]
        folha.secao(titulo, ajuda, len(grupo))
        for p in grupo:
            u = p.get("ultima")
            if chave == "nunca":
                quando = "nenhuma posição registrada"
            elif u:
                dias = (dia - u).days
                quando = "última em %s  ·  %d dia%s" % (
                    u.strftime("%d/%m/%Y"), dias, "" if dias == 1 else "s")
            else:
                quando = "—"
            folha.linha(p["placa"], quando)
        folha.y -= 4 * mm
    return folha.fechar()


def nome_arquivo(dia: date, alvo: str = "3S") -> str:
    return "%s-sem-comunicacao-%s.pdf" % (alvo.lower(), dia.strftime("%Y-%m-%d"))
