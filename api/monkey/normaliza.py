"""ReceivableDTO da Monkey → o formato de título que o CÓRTEX já usa.

O modelo do portal já existe (`api/antecipacoes/registro.py`, tabela `titulos`)
porque hoje ele é alimentado por planilha. Esta camada faz a API entrar pelo
MESMO formato, para que a tela, a conciliação e a simulação de antecipação não
saibam a diferença entre um portal que veio de arquivo e um que veio de API.

QUEM É QUEM — MEDIDO NOS DADOS REAIS (01/09/2026, produção), porque o palpite
original estava INVERTIDO: `sponsor` é a ÂNCORA (TUPY S/A — quem deve o
título, o SACADO) e `buyer` é o INVESTIDOR que comprou o recebível (nos dados:
BANCO SOFISA). O cedente é a própria Sulista (o seller da URL), e o payload
NÃO traz o CNPJ dela — a coleta anota `_seller_cnpj`/`_seller_nome` em cada
recebível a partir de /uaa/me (companies). Se o sacado apontasse para o buyer,
a elegibilidade por convênio — que casa pela raiz do CNPJ do SACADO — casaria
com o banco investidor e nunca com a Tupy.

O STATUS É GANHO NOVO. A planilha só dizia que o título está no portal; aqui
vem se ele já foi VENDIDO, se foi RECUSADO ou se está em custódia. Só
`ACTIVE`/`OFFERED` são de fato antecipáveis — um título `SOLD` já foi
antecipado e contá-lo de novo inflaria o disponível.
"""
from __future__ import annotations

# Situações que ainda podem virar antecipação. Fora daqui o título existe, mas
# não é oferta disponível: SOLD já foi vendido, PAID já liquidou, REFUSED e
# CANCELLED saíram, WAITING_* estão presos em processo, DELAYED está atrasado.
ANTECIPAVEIS = {"ACTIVE", "OFFERED"}

# Situações que SAÍRAM da posição do portal — o dinheiro já veio (SOLD), o
# ciclo fechou (PAID) ou o título caiu fora (REFUSED/CANCELLED). A primeira
# coleta real (01/09/2026) trouxe 48.666 títulos, TODOS vendidos/liquidados
# desde o início do convênio: gravar isso como "posição" encheria a tela de
# Antecipações com 48 mil linhas mortas. Posição é o que está EM ABERTO;
# status desconhecido fica DENTRO (fail-open: título novo não pode sumir em
# silêncio por causa de um rótulo que ainda não conhecemos).
FORA_DA_POSICAO = {"SOLD", "PAID", "REFUSED", "CANCELLED"}

# Rótulo em português para a tela; código desconhecido aparece cru em vez de
# virar rótulo inventado (mesma regra do "Tipo (cód.)" da Manutenção).
ROTULOS = {
    "ACTIVE": "disponível",
    "OFFERED": "ofertado",
    "SOLD": "vendido",
    "PAID": "liquidado",
    "REFUSED": "recusado",
    "CANCELLED": "cancelado",
    "WAITING_CUSTODY": "aguardando custódia",
    "WAITING_DELETE": "aguardando exclusão",
    "DELAYED": "atrasado",
}


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v) -> float:
    """Valor monetário. A API é JSON e manda número, mas string com vírgula já
    apareceu em API brasileira mais de uma vez — custa nada aceitar."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if "," in s:                     # 1.234,56 -> 1234.56
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _data(v) -> str:
    """ISO-8601 (a Monkey usa '2019-01-22T13:37:00.000-03:00') → 'AAAA-MM-DD'.

    Corta no 'T' em vez de fazer parse: o fuso vem no fim e converter para UTC
    voltaria um dia em datas perto da meia-noite — o mesmo erro que o `_iso()`
    do frontend existe para evitar.
    """
    s = _txt(v)
    return s[:10] if len(s) >= 10 else ""


def _digitos(v) -> str:
    return "".join(c for c in _txt(v) if c.isdigit())


def titulo(r: dict) -> dict:
    """Um ReceivableDTO no formato da tabela `titulos`."""
    status = _txt(r.get("status")).upper()
    valor = _num(r.get("paymentValue"))
    # `receiptValue` é o que a Sulista recebe de fato; quando não vem, o saldo
    # é o próprio nominal. Deixar 0 faria o título sumir das somas.
    recebe = _num(r.get("receiptValue")) or valor
    parc = r.get("installment")
    total_parc = r.get("totalInstallment")
    return {
        "titulo": _txt(r.get("invoiceNumber")),
        "documento": _txt(r.get("invoiceNumber")),
        "emissao": _data(r.get("invoiceDate")),
        "vencimento": _data(r.get("paymentDate")),
        "valor_nominal": valor,
        "valor_saldo": recebe,
        "antecipavel": 1 if status in ANTECIPAVEIS else 0,
        "situacao": ROTULOS.get(status, status or "(sem status)"),
        "situacao_api": status,
        # sponsor = âncora (sacado); o cedente é o próprio seller, anotado
        # pela coleta — ver o QUEM É QUEM no topo. O buyer (investidor que
        # comprou o título) não tem coluna na tabela e fica de fora.
        "cnpj_cedente": _digitos(r.get("_seller_cnpj")),
        "nome_cedente": _txt(r.get("_seller_nome")),
        "cnpj_sacado": _digitos(r.get("sponsorGovernmentId")),
        "nome_sacado": _txt(r.get("sponsorName")),
        "chave": _txt(r.get("invoiceKey")),
        "id_portal": _txt(r.get("externalId")),
        # extras que a planilha nunca teve
        "taxa": _num(r.get("purchasedTax")),
        "parcela": f"{parc}/{total_parc}" if parc and total_parc else "",
        "pagamento_real": _data(r.get("realPaymentDate")
                                or r.get("effectivePaymentDate")),
    }


def lote(recebiveis: list[dict]) -> dict:
    """Converte a lista e resume, no mesmo formato que o leitor de planilha
    devolve — é o que permite gravar pelo caminho que já existe."""
    linhas = [titulo(r) for r in recebiveis]
    disponiveis = [t for t in linhas if t["antecipavel"]]
    por_status: dict[str, int] = {}
    for t in linhas:
        por_status[t["situacao"]] = por_status.get(t["situacao"], 0) + 1
    return {
        "titulos": linhas,
        "resumo": {
            "linhas": len(linhas),
            "antecipaveis": len(disponiveis),
            "valor_nominal": round(sum(t["valor_nominal"] for t in linhas), 2),
            "valor_saldo": round(sum(t["valor_saldo"] for t in linhas), 2),
            "valor_antecipavel": round(
                sum(t["valor_saldo"] for t in disponiveis), 2),
            "por_status": por_status,
            "sacados": sorted({t["cnpj_sacado"] for t in linhas if t["cnpj_sacado"]}),
        },
    }
