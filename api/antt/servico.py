"""Confere as viagens de compra contra o piso mínimo e resume para a tela.

A separação importa: conferir_viagens, resumir e serie_mensal são puros e
testáveis sem banco; só get_piso_minimo toca no AVA.
"""
from __future__ import annotations

from datetime import datetime

from api import db
from api.antt.eixos import resolver_carga
from api.antt.piso import avaliar, calcular_piso
from api.antt.sql import PISO_VIAGENS_SQL

# contêiner é o caso em que o retorno vazio é obrigatório por norma; frota
# dedicada por razão sanitária depende de contrato e não está no cadastro, por
# isso não é inferida aqui.
CARGAS_VAZIO_OBRIGATORIO = frozenset({"conteinerizada", "perigosa_conteinerizada"})


def conferir_viagens(linhas: list[dict]) -> list[dict]:
    out = []
    for l in linhas:
        # eixos vêm somados do SQL (tração + carretas); 0 significa cadastro
        # incompleto, não veículo sem eixo
        eixos = l.get("eixos") or None
        carga = resolver_carga(l.get("veic_tipocarga"))
        quando = datetime.strptime(l["dtemissao"], "%Y-%m-%d").date()
        vazio = bool(l.get("vazio"))
        item = dict(l)
        if l.get("alto_desempenho"):
            # Tabela C (alto desempenho) ainda não está carregada. Conferir
            # esta viagem contra a Tabela A cobraria piso MAIOR que o devido e
            # acusaria de irregular quem pagou certo — então ela não é
            # conferida, e aparece como pendência.
            calc = {"estado": "alto_desempenho", "piso": None, "ccd": None,
                    "cc": None, "resolucao": None}
        else:
            calc = calcular_piso(
                km=float(l.get("km") or 0), tipo_carga=carga, eixos=eixos,
                quando=quando, vazio=vazio,
                vazio_obrigatorio=vazio and carga in CARGAS_VAZIO_OBRIGATORIO)
        item.update(avaliar(float(l.get("pago") or 0), calc))
        item["eixos"] = eixos
        item["tipo_carga"] = carga
        out.append(item)
    return out


def resumir(conferidas: list[dict]) -> dict:
    viagens = len(conferidas)
    calc = [c for c in conferidas if c["estado"] == "calculado"]
    isentas = [c for c in conferidas if c["estado"] == "isento"]
    pendentes = [c for c in conferidas
                 if c["estado"] not in ("calculado", "isento")]
    abaixo = [c for c in calc if c["abaixo"]]
    return {
        "viagens": viagens,
        "conferidas": len(calc),
        "isentas": len(isentas),
        "nao_conferidas": len(pendentes),
        "placas_pendentes": len({c.get("placa") for c in pendentes if c.get("placa")}),
        "pago": sum(float(c.get("pago") or 0) for c in calc),
        "piso_total": sum(float(c["piso"]) for c in calc),
        "abaixo": len(abaixo),
        "exposicao": sum(float(c["gap"]) for c in abaixo),
        "aderencia": (1 - len(abaixo) / len(calc)) if calc else None,
        # Quanto do piso a empresa efetivamente paga, no agregado. Com 87% das
        # viagens abaixo do mínimo, a contagem sozinha não orienta — todo mês
        # fica vermelho. O percentual do piso mostra a distância real e permite
        # acompanhar se ela está encolhendo.
        "pct_piso": (sum(float(c.get("pago") or 0) for c in calc)
                     / sum(float(c["piso"]) for c in calc)) if calc else None,
    }


def serie_mensal(conferidas: list[dict]) -> list[dict]:
    """Aderência mês a mês. Só entra o que foi efetivamente conferido — mês
    inteiro sem cálculo não vira ponto de 100%, some do gráfico."""
    por_mes: dict[str, dict] = {}
    for c in conferidas:
        if c["estado"] != "calculado":
            continue
        mes = c["dtemissao"][:7]
        r = por_mes.setdefault(mes, {"mes": mes, "conferidas": 0, "abaixo": 0,
                                     "exposicao": 0.0})
        r["conferidas"] += 1
        if c["abaixo"]:
            r["abaixo"] += 1
            r["exposicao"] += float(c["gap"])
    saida = []
    for mes in sorted(por_mes):
        r = por_mes[mes]
        r["aderencia"] = 1 - r["abaixo"] / r["conferidas"]
        saida.append(r)
    return saida


# campos que a tela realmente usa no detalhe de cada viagem. Mandar a linha
# inteira do SQL levava o payload de julho a 1,8 MB; a projeção corta o que só
# serviu para calcular (coeficientes, flags de cadastro, eixos da tração).
_CAMPOS_DETALHE = ("numero", "dtemissao", "placa", "origem", "destino", "km",
                   "eixos", "tipo_carga", "pago", "piso", "gap", "estado")


def _enxugar(c: dict) -> dict:
    return {k: c.get(k) for k in _CAMPOS_DETALHE}


def get_piso_minimo(filial: int | None, dt_de: str, dt_ate: str,
                    modalidade: str | None = None,
                    transportador: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate,
              "modalidade": modalidade, "transportador": transportador}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(PISO_VIAGENS_SQL, params)
        linhas = cur.fetchall()
    conferidas = conferir_viagens([dict(l) for l in linhas])
    por_transp: dict[str, dict] = {}
    for c in conferidas:
        t = por_transp.setdefault(c["codigo"] or "(sem)", {
            "codigo": c["codigo"], "transportador": c["transportador"],
            "viagens": 0, "pago": 0.0, "abaixo": 0, "exposicao": 0.0,
            "detalhe": []})
        t["viagens"] += 1
        t["pago"] += float(c.get("pago") or 0)
        if c["abaixo"]:
            t["abaixo"] += 1
            t["exposicao"] += float(c["gap"])
        t["detalhe"].append(_enxugar(c))
    ordenado = sorted(por_transp.values(), key=lambda x: x["exposicao"])
    pendentes = sorted({
        (c.get("placa") or "", c.get("veic_tipo") or "",
         c.get("veic_carroceria") or "", c["estado"])
        for c in conferidas if c["estado"] not in ("calculado", "isento")})
    return {
        "kpis": resumir(conferidas),
        "mensal": serie_mensal(conferidas),
        "transportadores": ordenado,
        "pendencias": [{"placa": p, "tipo": t, "carroceria": cr, "motivo": e}
                       for p, t, cr, e in pendentes],
        "dt_de": dt_de, "dt_ate": dt_ate,
        "fonte": ("ERP AVA · programacaoembarque (frete de compra) × tabela ANTT "
                  "vigente na data da viagem · leitura"),
    }
