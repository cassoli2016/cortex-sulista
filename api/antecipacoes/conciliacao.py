"""Confronta os títulos do portal com o contas a receber do ERP.

Sem isto o upload seria um visualizador de planilha. O que decide é o
confronto: o portal diz "R$ 929 mil antecipáveis"; o CÓRTEX precisa dizer
quanto disso é recebível que ESTÁ no fluxo de caixa, com que vencimento, e
onde os dois discordam.

Três divergências que importam, em ordem de gravidade:

1. **Vencimento diferente.** É a pior. O fluxo de caixa projeta pela data do
   ERP; se o portal paga noutra data, a projeção está errada nesse valor —
   e ninguém percebe, porque os dois lados parecem certos isoladamente.
2. **Só no portal.** Título que o portal lista e o ERP não tem em aberto:
   normalmente já foi baixado (recebido) e o portal não atualizou, mas pode
   ser nota que nunca foi lançada.
3. **Valor diferente.** Costuma ser retenção/desconto aplicado por um lado só.

O casamento é por NÚMERO DO DOCUMENTO (nota fiscal), que é o que os dois
sistemas compartilham. O número do título do portal ("BRIM2026510013258...")
é interno dele e não existe no nosso lado.
"""
from __future__ import annotations

from datetime import date

from api import db

# Diferença de valor abaixo disto é arredondamento, não divergência.
TOL_VALOR = 0.05

# Recebíveis em aberto do ERP, pelo número do documento. Restringe ao CNPJ do
# sacado para não casar a nota 100226 de OUTRO cliente — numeração de NF se
# repete entre emitentes, e um falso casamento aqui vira número errado na tela.
CONC_SQL = """
SELECT fc.numerosequenciadocumentoorigem::text AS documento,
       coalesce(f.dtprevisaopagamento, f.dtvencimento)::date AS vencimento,
       sum(fc.valorpendentecnpjcliente)::float8 AS valor,
       count(*)::int AS partes,
       min(coalesce(nullif(trim(ca.nomefantasia),''),
                    nullif(trim(ca.razaosocial),''))) AS cliente
FROM fatura f
JOIN fatura_composicao fc USING (grupo, empresa, filial, unidade, sequencia)
LEFT JOIN cadastro ca ON ca.codigo = f.cliente
WHERE f.grupo = 1 AND fc.valorpendentecnpjcliente > 0
  AND f.dtcancelamento IS NULL AND f.composicao = 1 AND f.dtpagamento IS NULL
  AND fc.numerosequenciadocumentoorigem::text = ANY(%(docs)s)
GROUP BY 1, 2
"""


def _dias(a: date, b: date) -> int:
    return (a - b).days


def conciliar(titulos: list[dict]) -> dict:
    """Casa os títulos do portal com o ERP e classifica as diferenças."""
    docs = sorted({t["documento"] for t in titulos if t["documento"]})
    if not docs:
        return {"disponivel": False,
                "motivo": "o arquivo não traz número de documento"}

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CONC_SQL, {"docs": docs})
        linhas = cur.fetchall()

    # Um documento pode aparecer com mais de um vencimento (parcelas). Guarda
    # a lista e casa pela data mais próxima da do portal — casar pela primeira
    # marcaria a parcela 2 como divergente sempre.
    erp: dict = {}
    for l in linhas:
        erp.setdefault(l["documento"], []).append(l)

    casados, so_portal = [], []
    div_venc, div_valor = [], []

    for t in titulos:
        cands = erp.get(t["documento"] or "")
        if not cands:
            so_portal.append(t)
            continue
        alvo = min(cands, key=lambda c: abs(_dias(c["vencimento"], t["vencimento"])))
        dv = _dias(alvo["vencimento"], t["vencimento"])
        dvalor = round(alvo["valor"] - t["valor_saldo"], 2)
        item = {
            "documento": t["documento"],
            "titulo": t["titulo"],
            "cliente": alvo["cliente"],
            "venc_portal": t["vencimento"].isoformat(),
            "venc_erp": alvo["vencimento"].isoformat(),
            "dias_diferenca": dv,
            "valor_portal": t["valor_saldo"],
            "valor_erp": round(alvo["valor"], 2),
            "diferenca_valor": dvalor,
        }
        casados.append(item)
        if dv != 0:
            div_venc.append(item)
        if abs(dvalor) > TOL_VALOR:
            div_valor.append(item)

    val_casado = round(sum(c["valor_portal"] for c in casados), 2)
    val_portal = round(sum(t["valor_saldo"] for t in titulos), 2)

    return {
        "disponivel": True,
        "casados": len(casados),
        "valor_casado": val_casado,
        "cobertura_pct": round(100 * val_casado / max(0.01, val_portal), 1),
        "so_no_portal": len(so_portal),
        "valor_so_no_portal": round(sum(t["valor_saldo"] for t in so_portal), 2),
        # Ordenadas pela maior diferença: a data que mais desloca caixa vem
        # primeiro, não a primeira que apareceu no arquivo.
        "divergencia_vencimento": sorted(
            div_venc, key=lambda x: (-abs(x["dias_diferenca"]), -x["valor_portal"]))[:50],
        "divergencia_vencimento_total": len(div_venc),
        "valor_divergencia_vencimento": round(
            sum(x["valor_portal"] for x in div_venc), 2),
        "divergencia_valor": sorted(
            div_valor, key=lambda x: -abs(x["diferenca_valor"]))[:50],
        "divergencia_valor_total": len(div_valor),
        "amostra_so_portal": [{
            "documento": t["documento"], "titulo": t["titulo"],
            "vencimento": t["vencimento"].isoformat(),
            "valor": t["valor_saldo"],
        } for t in sorted(so_portal, key=lambda x: -x["valor_saldo"])[:50]],
    }
