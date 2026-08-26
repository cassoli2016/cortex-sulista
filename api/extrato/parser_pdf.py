"""Parser de extrato em PDF — hoje só o layout do Banco C6.

POR QUE EXISTE
==============
O C6 é o único banco do lote da Sulista que não oferece OFX no internet
banking: o extrato sai em PDF e mais nada. Sem este módulo, a conta 336 fica
permanentemente fora da conciliação — não por divergir, mas por não ter como
entrar.

O PDF é gerado por PDFium com texto de verdade (não é digitalização), então a
extração é de TEXTO, não OCR. Se algum dia vier um PDF escaneado, `parse_pdf`
levanta erro dizendo isso, em vez de devolver zero lançamento com `ok`.

POR QUE UM LAYOUT POR VEZ, E NUNCA UM PARSER "GENÉRICO DE PDF"
==============================================================
PDF não tem estrutura de dados: tem posição de glifo. Duas colunas só são
"colunas" porque estão alinhadas na página. Um parser que tenta adivinhar
qualquer extrato bancário acerta o banco que o autor tinha na mão e erra os
outros em silêncio — e errar em silêncio, aqui, é lançar dinheiro na
conciliação. Por isso cada layout é declarado, reconhecido pelo cabeçalho, e
o que não for reconhecido é RECUSADO com o motivo.

A CONFERÊNCIA QUE TORNA ISSO SEGURO
===================================
O extrato do C6 imprime o saldo disponível ao fim de cada dia movimentado.
Isso dá uma verificação aritmética fechada, que roda em toda importação:

    saldo do dia == saldo do dia anterior + soma dos movimentos do dia

No arquivo de agosto/2026 a cadeia fecha em todos os onze dias movimentados
(0,00 → 0,01 → 0,01 → 0,02 → 0,11 → 0,00 → … → 202,02), o que prova que o
recorte de coluna está certo. Quando NÃO fechar, `parse_pdf` devolve o desvio
em `conferencia` e quem chama decide — é o sinal de que o layout mudou.

O CAMPO DE VALOR MUDA DE CONVENÇÃO DENTRO DO MESMO ARQUIVO
==========================================================
Os movimentos saem em convenção en-US (`200,000.00` = duzentos mil) e as
linhas de saldo em pt-BR (`202,02` = duzentos e dois). No mesmo PDF, a duas
linhas de distância. Por isso o valor passa pelo `_valor` do parser OFX, que
decide pelo separador que aparece por ÚLTIMO, e não pelo `valor_br` do parser
CSV: `valor_br("200,000.00")` devolve `None`, ou seja, descartaria em silêncio
todos os créditos e débitos do arquivo.
"""
from __future__ import annotations

import re
from datetime import date

# O mesmo conversor do OFX, de propósito - ver a última seção da docstring.
from api.extrato.parser_ofx import _valor

# --------------------------------------------------------------- layout C6

# 336 é o código COMPE do Banco C6 S.A.; o PDF traz a razão social por extenso
# e nunca o número, então ele entra aqui, junto do resto da declaração do
# layout, e não espalhado pelo código.
C6_BANCO = 336

_C6_MARCA = re.compile(r"BANCO C6 S\.A\.", re.IGNORECASE)
_C6_CONTA = re.compile(
    r"Ag[êe]ncia:\s*(\S+)\s+Conta:\s*(\S+)", re.IGNORECASE)

# Movimento: data, histórico, documento, valor, e o indicador C/D em último.
# O `\s{2,}` antes do documento é o que separa histórico de coluna: o histórico
# tem espaço simples dentro ("APLIC. EM  COMPROMI." tem até espaço duplo, por
# isso o histórico é non-greedy e a âncora de verdade é o bloco de 12 dígitos).
_C6_MOV = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s{2,}(\d{6,})\s+([\d.,]+)\s+([CD])\s*$")

# Linha de saldo: sem documento e sem indicador C/D - é isso que a distingue.
_C6_SALDO = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(SALDO\s+[A-ZÇÃÉÊÍÓÚ ]+?)\s{2,}([\d.,]+)\s*$",
    re.IGNORECASE)

# Das linhas de saldo, só o DISPONÍVEL é comparável com o `contacorrente_saldo`
# do ERP. "SALDO VINCULADO" e "SALDO BLOQUEADO" são posições paralelas (e no
# arquivo medido são zero em todos os dias); tratá-las como saldo da conta
# sobrescreveria o número certo pelo errado, já que caem no mesmo dia.
_C6_SALDO_BOM = re.compile(r"^SALDO\s+DISPON[IÍ]VEL", re.IGNORECASE)


def _texto(bruto: bytes) -> str:
    """Texto do PDF em modo `layout`, que preserva as colunas.

    O modo padrão do pypdf concatena a linha na ordem em que os glifos estão no
    arquivo, e no cabeçalho do C6 isso embaralha rótulo e valor
    ("AGÊNCIA: CONTA CORRENTE: SITUAÇÃO:0001 000034988068-9 LIBERADA"). Em modo
    `layout` a mesma linha sai alinhada e o par agência/conta é legível.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:                              # pragma: no cover
        raise ValueError(
            "Leitura de extrato em PDF exige a biblioteca `pypdf`, que não está "
            "instalada neste ambiente.") from exc

    import io

    try:
        leitor = PdfReader(io.BytesIO(bruto))
        paginas = [p.extract_text(extraction_mode="layout") or "" for p in leitor.pages]
    except Exception as exc:
        raise ValueError(f"Não foi possível ler o PDF: {exc}") from exc

    texto = "\n".join(paginas)
    if not texto.strip():
        raise ValueError(
            "O PDF não tem texto extraível - provavelmente é uma digitalização "
            "(imagem). Peça ao banco o extrato em PDF de texto ou em OFX; este "
            "módulo não faz OCR.")
    return texto


def _data_br(txt: str) -> str | None:
    d, m, a = txt.split("/")
    try:
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _conferir(itens: list[dict], saldos: list[dict]) -> dict:
    """Saldo do dia == saldo anterior + movimento do dia, para cada âncora.

    Devolve o resumo em vez de levantar erro: um desvio pode ser layout que
    mudou (grave) ou um dia em que o banco imprimiu saldo sem imprimir o
    movimento (acontece em conta com aplicação automática). Quem chama mostra
    o aviso; o dado continua disponível.
    """
    mov: dict[str, float] = {}
    for i in itens:
        mov[i["dt"]] = mov.get(i["dt"], 0.0) + i["valor"]
    desvios = []
    for ant, atual in zip(saldos, saldos[1:]):
        esperado = ant["saldo"] + mov.get(atual["dt"], 0.0)
        d = atual["saldo"] - esperado
        if abs(d) > 0.01:
            desvios.append({"dt": atual["dt"], "esperado": round(esperado, 2),
                            "no_extrato": atual["saldo"], "desvio": round(d, 2)})
    return {"dias": max(len(saldos) - 1, 0), "desvios": desvios,
            "fecha": not desvios}


def _parse_c6(texto: str) -> dict:
    m = _C6_CONTA.search(texto)
    if not m:
        raise ValueError(
            "PDF do C6 sem o par agência/conta no cabeçalho - não é possível "
            "saber a que conta bancária o extrato pertence.")
    agencia, conta = m.group(1).strip(), m.group(2).strip()

    itens: list[dict] = []
    por_dia: dict[str, float] = {}
    linhas_saldo = ignoradas = 0

    for linha in texto.split("\n"):
        linha = linha.rstrip()
        mv = _C6_MOV.match(linha.strip())
        if mv:
            dt = _data_br(mv.group(1))
            valor = _valor(mv.group(4))
            if dt is None or valor is None:
                ignoradas += 1
                continue
            # No C6 o sinal NÃO está no número: o valor é sempre positivo e
            # quem manda é a coluna D/C do fim da linha. É o inverso do OFX,
            # onde o sinal do TRNAMT é a fonte da verdade.
            if mv.group(5).upper() == "D":
                valor = -valor
            itens.append({
                "dt": dt, "valor": valor, "tipo": "C" if valor >= 0 else "D",
                "historico": " ".join(mv.group(2).split()),
                "numerodoc": mv.group(3).strip(),
                # PDF não tem identificador de transação. Deixar `None` é o
                # correto: a chave de deduplicação já não confia em FITID
                # (ver `armazenamento._chave`) e inventar um id aqui só criaria
                # a ilusão de unicidade.
                "fitid": None,
            })
            continue

        sd = _C6_SALDO.match(linha.strip())
        if sd:
            linhas_saldo += 1
            if not _C6_SALDO_BOM.match(sd.group(2).strip()):
                continue          # vinculado/bloqueado não são o saldo da conta
            dt = _data_br(sd.group(1))
            valor = _valor(sd.group(3))
            if dt is not None and valor is not None:
                por_dia[dt] = valor

    saldos = [{"dt": d, "saldo": v, "origem": "linha"} for d, v in sorted(por_dia.items())]
    if not itens and not saldos:
        raise ValueError(
            "PDF reconhecido como extrato do C6, mas nenhuma linha de "
            "lançamento ou de saldo foi encontrada - o layout pode ter mudado.")

    return {
        "ident": f"{C6_BANCO}/{agencia}/{conta}",
        "banco": C6_BANCO, "agencia": agencia, "conta": conta,
        "itens": itens, "saldos": saldos,
        # `saldo` (singular) é o contrato que o parser OFX expõe e o serviço
        # conhece: a última posição do arquivo.
        "saldo": ({"dt": saldos[-1]["dt"], "saldo": saldos[-1]["saldo"]}
                  if saldos else None),
        "linhas_saldo": linhas_saldo, "ignoradas": ignoradas,
        "conferencia": _conferir(itens, saldos),
    }


# Layout novo entra aqui: uma marca que o reconhece e a função que o lê.
_LAYOUTS = ((_C6_MARCA, _parse_c6, "Banco C6"),)


def parse_pdf(bruto: bytes) -> list[dict]:
    """Mesma forma de retorno do `parse_ofx`: uma lista de extratos.

    Lista, e não um extrato só, para que o serviço de importação trate PDF e
    OFX pelo mesmo caminho. Nenhum layout conhecido hoje consolida mais de uma
    conta num arquivo, então a lista tem sempre um elemento - mas o dia em que
    tiver, o chamador não muda.
    """
    texto = _texto(bruto)
    for marca, ler, _nome in _LAYOUTS:
        if marca.search(texto):
            return [ler(texto)]
    raise ValueError(
        "Extrato em PDF de layout não reconhecido. Hoje o CÓRTEX lê o PDF do "
        + ", ".join(n for _m, _l, n in _LAYOUTS)
        + "; para os demais bancos, use o arquivo OFX do internet banking, que "
        "é lido de qualquer instituição.")
