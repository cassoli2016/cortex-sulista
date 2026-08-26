"""Parser de OFX (Open Financial Exchange) — formato padrão dos internet
bankings brasileiros.

Cobre as duas variantes com um único caminho: OFX 1.x é SGML (tags sem
fechamento: `<TRNAMT>10.50` até o fim da linha) e 2.x é XML bem-formado. Uma
regex por tag atende os dois, o que evita depender de parser XML (que quebraria
no SGML) ou de biblioteca externa.

Um export pode consolidar mais de uma conta num único arquivo (mais de um
bloco `<STMTRS>`) — `parse_ofx` devolve uma **lista**, um extrato por bloco,
para nunca misturar lançamentos/saldo de contas diferentes sob uma única
identidade.

Encoding: OFX de banco BR costuma vir em cp1252/latin-1, não utf-8.

Limitação conhecida da abordagem por regex: o valor de uma tag termina no
primeiro `<` ou quebra de linha. Na prática os campos usados aqui (MEMO, NAME,
datas, valores) não trazem `<`, então isso não é um problema real; se algum
dia trouxer, o texto sai truncado ali — não tentamos resolver isso com um
parser completo (é exatamente a complexidade que a abordagem por regex evita).

NEM TODO `<STMTTRN>` É MOVIMENTO
================================
Medido em sete arquivos reais de agosto/2026 (Bradesco, CEF, Itaú, Safra,
Santander, Sicredi): dois dos sete emitem o **saldo do dia como se fosse
transação**, e o parser antigo os somava como crédito.

  - Safra: 20 de 37 linhas com `TRNTYPE=BALANCE` e MEMO "SALDO TOTAL".
  - Itaú: 18 de 184 linhas com `TRNTYPE=DEBIT`/`CREDIT` (o tipo não denuncia
    nada) e MEMO "SALDO ANTERIOR" / "SALDO TOTAL DISPONÍVEL DIA".

O efeito no Itaú: movimento líquido lido como R$ 157.152,97 quando o real é
R$ 4.028,73 — 39 vezes maior. A prova de que são saldo e não movimento fecha
na casa do centavo: abertura (-2.703,15) + movimento real (4.028,73) =
1.325,58, contra o `LEDGERBAL` de 1.325,59 do mesmo arquivo.

Essas linhas saem de `itens` e entram em `saldos`, onde valem MUITO mais do
que valiam como movimento: viram âncora de saldo POR DIA, em vez de uma única
âncora de `LEDGERBAL` com todo o resto derivado por soma.
"""
from __future__ import annotations

import html
import re
from datetime import date

_TAG = r"<{t}>\s*([^<\r\n]*)"

# Linha de saldo disfarcada de transacao: o criterio e o MEMO, e SO o MEMO.
#
# A primeira versao deste remendo tambem aceitava `TRNTYPE=BALANCE` como
# prova, e estava errada - o proprio dado real derrubou a ideia. O Safra
# marca com `BALANCE` TODA linha do extrato do dia, saldo e movimento junto:
#
#     TRNTYPE=BALANCE  MEMO="SALDO INICIAL"      657.41   <- abertura
#     TRNTYPE=BALANCE  MEMO=" BLOQUEIO JUDICIAL" -656.45  <- MOVIMENTO REAL
#     TRNTYPE=BALANCE  MEMO="SALDO TOTAL"          0.96   <- fechamento
#
# Confiar no `TRNTYPE` engolia o bloqueio judicial de R$ 656,45 - a mesma
# classe de perda silenciosa que este arquivo existe para impedir. Quem pegou
# foi a conferencia aritmetica (ancora do dia == ancora anterior + movimento
# do dia), que e o teste que vale para qualquer banco novo.
#
# A ancora `^` tambem nao e decoracao: nos mesmos sete arquivos ha DOIS
# lancamentos reais de tarifa do Santander cujo historico CONTEM a palavra -
# "JUROS SALDO UTILIZ ATE LIMITE" e "JUROS SALDO UTILIZ PERIODO EXCESSO". E o
# `\b` no fim evita casar "SALDOS A PAGAR".
_LINHA_SALDO = re.compile(r"^SALDO\b", re.IGNORECASE)


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _campo(bloco: str, tag: str) -> str:
    m = re.search(_TAG.format(t=tag), bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _data(cru: str) -> str | None:
    """OFX grava YYYYMMDD, opcionalmente com hora e fuso ('20260702120000[-03:EBT]').

    O `date(...)` no fim NÃO é preciosismo de validação: o Bradesco exporta
    `<DTASOF>00000000000000` (e `<DTSERVER>` idem), e a versão anterior, que só
    fatiava a string, devolvia obedientemente "0000-00-00". Esse dia não existe,
    então a âncora de saldo do Bradesco era gravada num dia que nunca casa com
    dia nenhum do ERP - a conta perdia o saldo do banco na comparação e nada na
    tela dizia por quê. Data impossível vira `None`, que o chamador já sabe
    tratar (lançamento entra em `ignoradas`; saldo simplesmente não vira âncora).
    """
    m = re.match(r"\s*(\d{4})(\d{2})(\d{2})", cru or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _valor(cru: str) -> float | None:
    """Converte TRNAMT/BALAMT (texto) para float.

    A spec OFX define o valor como ponto-decimal: um único '.' é SEMPRE o
    separador decimal, mesmo com 3 dígitos depois (ex.: "1.234" vale 1.234,
    não 1234) — o oposto da convenção de milhar do CSV brasileiro, que é
    tratada por outra task; não unifique as duas regras aqui.

    Quando a string malformada traz os DOIS separadores (banco que exporta
    errado, ou formato en-US "10,000.00"), o separador DECIMAL é o último que
    aparece na string (por posição) — o outro é tratado como separador de
    milhar e descartado. Isso evita o bug de ler "10,000.00" como 10.0 (mil
    vezes menor) ao assumir sempre o formato BR.
    """
    txt = (cru or "").strip().replace(" ", "")
    if not txt:
        return None
    pos_virgula = txt.rfind(",")
    pos_ponto = txt.rfind(".")
    if pos_virgula != -1 and pos_ponto != -1:
        if pos_virgula > pos_ponto:
            # último separador é a vírgula => formato BR: ponto é milhar
            txt = txt.replace(".", "").replace(",", ".")
        else:
            # último separador é o ponto => formato en-US: vírgula é milhar
            txt = txt.replace(",", "")
    elif pos_virgula != -1:
        # só vírgula: decimal BR sem milhar
        txt = txt.replace(",", ".")
    # só ponto, ou nenhum separador: mantém como está — TRNAMT é ponto-decimal
    try:
        return float(txt)
    except ValueError:
        return None


def _extrair_extrato(bloco: str) -> dict:
    """Extrai identidade, lançamentos e saldo de UM bloco <STMTRS>."""
    banco_cru = _campo(bloco, "BANKID")
    agencia = _campo(bloco, "BRANCHID")
    conta = _campo(bloco, "ACCTID")
    try:
        banco = int(banco_cru) if banco_cru else None
    except ValueError:
        banco = None

    itens: list[dict] = []
    por_dia: dict[str, float] = {}      # saldo do dia vindo de linha de saldo
    ignoradas = 0
    linhas_saldo = 0
    for trn in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", bloco, re.IGNORECASE | re.DOTALL):
        dt = _data(_campo(trn, "DTPOSTED"))
        valor = _valor(_campo(trn, "TRNAMT"))
        if dt is None or valor is None:
            ignoradas += 1
            continue
        historico = html.unescape(_campo(trn, "MEMO") or _campo(trn, "NAME"))

        # Linha de SALDO não é movimento (ver docstring do módulo). Vai para
        # `saldos` como âncora do dia, e o ÚLTIMO registro do dia vence: no
        # Safra o dia 26/08 traz "SALDO INICIAL" 657,41 (a abertura, que é o
        # fechamento de 25/08) e depois "SALDO TOTAL" 0,96 (o fechamento, já
        # com o bloqueio judicial daquele dia). Ficar com o primeiro gravaria
        # a abertura como se fosse o fechamento.
        if _LINHA_SALDO.match(historico.strip()):
            por_dia[dt] = valor
            linhas_saldo += 1
            continue

        # o sinal do TRNAMT é a fonte da verdade; TRNTYPE só confirma
        tipo = "C" if valor >= 0 else "D"
        itens.append({
            "dt": dt, "valor": valor, "tipo": tipo,
            "historico": historico,
            "numerodoc": _campo(trn, "CHECKNUM"),
            "fitid": _campo(trn, "FITID") or None,
        })

    saldo = None
    m = re.search(r"<LEDGERBAL>(.*?)</LEDGERBAL>", bloco, re.IGNORECASE | re.DOTALL)
    if m:
        s_valor = _valor(_campo(m.group(1), "BALAMT"))
        s_dt = _data(_campo(m.group(1), "DTASOF"))
        if s_valor is not None and s_dt:
            saldo = {"dt": s_dt, "saldo": s_valor}

    # Âncoras de saldo do extrato. A linha de saldo do dia VENCE o `LEDGERBAL`
    # quando os dois falam do mesmo dia, e a razão é medida: no Safra o
    # `LEDGERBAL` de 24/08 diz 10.502,92 enquanto a linha "SALDO TOTAL" do
    # mesmo 24/08 diz 657,38. Os movimentos da conta no mês são rendimento de
    # CDB de centavos, então o `LEDGERBAL` ali é a posição CONSOLIDADA (conta
    # + aplicação) e a linha é o saldo da conta corrente - que é o que o
    # `contacorrente_saldo` do ERP guarda, e portanto o único comparável.
    saldos = [{"dt": d, "saldo": v, "origem": "linha"} for d, v in sorted(por_dia.items())]
    if saldo and saldo["dt"] not in por_dia:
        saldos.append({**saldo, "origem": "ledgerbal"})
        saldos.sort(key=lambda s: s["dt"])

    # I4 (achado da revisão final): sem BANKID nem ACCTID, `ident` caía sempre
    # em "?/?/?" - dois extratos DIFERENTES sem identificação (comum em
    # pseudo-contas de meio de pagamento: eFrete, PAMCARD, REPOM são as menos
    # padronizadas) caíam na MESMA `ext_conta`, somando lançamentos de duas
    # instituições e comparando contra uma única conta do ERP, com `ok: true`
    # e nenhum aviso - o mesmo Critical da identidade do CSV pelo nome do
    # arquivo (Task 5), reencarnado no caminho OFX. Só levanta se o bloco tem
    # conteúdo de verdade (itens ou saldo); um `<STMTRS>` vazio já é
    # descartado depois, em `parse_ofx`, sem precisar de identificação.
    if (itens or saldos) and not banco_cru and not conta:
        raise ValueError(
            "Extrato OFX sem identificação de conta (BANKID e ACCTID ausentes "
            "em BANKACCTFROM) - não é possível saber a qual conta bancária ele "
            "pertence. Extratos de meio de pagamento (ex.: pedágio, cartão-"
            "combustível) às vezes exportam sem essa informação; confira o "
            "arquivo com o provedor antes de reenviar.")

    ident = "/".join([banco_cru or "?", agencia or "?", conta or "?"])
    return {"ident": ident, "banco": banco, "agencia": agencia, "conta": conta,
            "itens": itens, "saldo": saldo, "saldos": saldos,
            "linhas_saldo": linhas_saldo, "ignoradas": ignoradas}


def parse_ofx(bruto: bytes) -> list[dict]:
    texto = _decodificar(bruto)
    if "<OFX" not in texto.upper():
        raise ValueError("Arquivo não parece ser um OFX (tag <OFX> não encontrada).")

    blocos = re.findall(r"<STMTRS>(.*?)</STMTRS>", texto, re.IGNORECASE | re.DOTALL)
    if not blocos:
        # arquivo fora do padrão (sem <STMTRS>): trata o documento inteiro como
        # um único bloco, para não regredir em relação ao comportamento anterior.
        blocos = [texto]

    candidatos = [_extrair_extrato(bloco) for bloco in blocos]
    extratos = [e for e in candidatos if e["itens"] or e["saldos"]]

    if not extratos:
        raise ValueError("OFX sem lançamentos nem saldo legíveis.")

    return extratos
