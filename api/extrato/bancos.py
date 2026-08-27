"""Visão estratégica de bancos: onde está o dinheiro, por onde ele passa e
quanto cada banco cobra por isso.

POR QUE ESTA TELA É SEPARADA DO EXTRATO BANCÁRIO
================================================
A tela de Extrato responde "o meu ERP bate com o banco?". Esta responde "quanto
tenho, onde, e quanto isso está custando?". São duas perguntas com donos
diferentes, e estavam nos mesmos oito cartões: quem abria para decidir onde
deixar o dinheiro atravessava cinco cartões de conferência antes de chegar ao
número.

O QUE É MEDIDO E O QUE É DERIVADO — a distinção governa a tela inteira
=====================================================================
**Medido** (linha de extrato, sem conta nenhuma por cima): o custo bancário, o
volume que entra e sai, e o saldo dos dias em que o banco imprimiu a linha de
saldo.

**Derivado** (soma a partir da última âncora): o saldo dos demais dias. Itaú,
Safra e C6 mandam saldo diário (19, 18 e 12 âncoras em agosto); Caixa,
Santander e Sicredi mandam UMA, o `LEDGERBAL`; o Bradesco não manda nenhuma
utilizável, porque grava a data zerada. Um gráfico que pintasse os dois iguais
estaria inventando precisão, então a série carrega a COBERTURA de cada dia.

O SALDO DAQUI NÃO É O CAIXA DA EMPRESA
======================================
É o saldo em CONTA CORRENTE. O dinheiro varrido para aplicação não aparece:
nenhum dos sete arquivos traz saldo de investimento, e o ERP não tem tabela de
aplicação (procurado: nada com `aplicacao`, `investiment`, `cdb`, `resgate`).

A única exceção mede o tamanho do buraco: o Safra manda `AVAILBAL` = R$
10.502,92 enquanto a linha de saldo do mesmo dia diz R$ 657,38 — R$ 9.845,54
aplicados que a tela não teria como saber sozinha. Por isso o rótulo é "Saldo
em conta corrente", e não "Total nos bancos", que seria mentira por omissão.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime

from api.extrato import armazenamento as arm
from api.extrato import comparacao as cmp
from api.extrato.servico import banco_da_conta, posicao

# ---------------------------------------------------------------- custo
# Natureza do custo, na ordem em que é testada — a primeira que casar vence.
#
# As expressões são ANCORADAS no início (`^`) porque o histórico do banco
# menciona essas palavras no meio de lançamento que NÃO é custo: "JUROS SALDO
# UTILIZ ATE LIMITE" é encargo, mas um "PAGTO JUROS FORNECEDOR" não seria.
#
# Medido em agosto/2026 sobre 745 lançamentos: 69 são custo, R$ 46.343,96, e
# 86,5% disso está em SEIS lançamentos de juros de limite.
NATUREZAS = (
    ("juros", "Juros de limite / cheque especial", re.compile(r"^JUROS", re.I)),
    ("iof", "IOF", re.compile(r"^IOF", re.I)),
    ("pacote", "Pacote / manutenção de conta",
     re.compile(r"^(TARIFA MENSALIDADE|TARIFA MANUTENCAO|CESTA)", re.I)),
    ("transacao", "Tarifa por transação",
     re.compile(r"^(TARIFA BANCARIA|TAR PIX|TARIFA TED|TAR |TARIFA AUTORIZ)", re.I)),
    ("outras", "Outras tarifas", re.compile(r"^TARIFA", re.I)),
)


def natureza(historico: str) -> tuple[str, str] | None:
    h = (historico or "").strip()
    for chave, rotulo, rx in NATUREZAS:
        if rx.match(h):
            return chave, rotulo
    return None


def _vazio(dt_de: str, dt_ate: str) -> dict:
    return {"kpis": {"saldo_total": 0.0, "contas": 0, "contas_sem_saldo": 0,
                     "custo": 0.0, "custo_ano": 0.0, "custo_juros": 0.0,
                     "contas_com_juros": 0, "concentracao_2": 0.0,
                     "recebido": 0.0, "pago": 0.0},
            "bancos": [], "serie": [], "custo_por_natureza": [],
            "alertas": [], "dt_de": dt_de, "dt_ate": dt_ate}


def painel(dt_de: str, dt_ate: str, esquema=None) -> dict:
    """Tudo que a tela de Bancos mostra, numa consulta local + a do ERP."""
    arm.init_db(esquema)
    contas = arm.listar_contas(esquema)
    if not contas:
        return _vazio(dt_de, dt_ate)

    pos = {x["conta_id"]: x for x in posicao(esquema)["linhas"]}

    bancos, serie_por_dia = [], defaultdict(lambda: {"saldo": 0.0, "contas": 0})
    custo_nat: dict[str, dict] = {}
    for c in contas:
        lancs = arm.lancamentos(esquema, c["id"], dt_de, dt_ate)
        cod, nome = banco_da_conta(c)
        recebido = sum(x["valor"] for x in lancs if x["valor"] > 0)
        pago = sum(x["valor"] for x in lancs if x["valor"] < 0)

        custo, por_nat = 0.0, defaultdict(lambda: [0, 0.0])
        for x in lancs:
            if x["valor"] >= 0:
                continue
            nat = natureza(x.get("historico"))
            if not nat:
                continue
            chave, rotulo = nat
            custo += -x["valor"]
            por_nat[chave][0] += 1
            por_nat[chave][1] += -x["valor"]
            g = custo_nat.setdefault(chave, {"chave": chave, "rotulo": rotulo,
                                             "qtd": 0, "valor": 0.0})
            g["qtd"] += 1
            g["valor"] += -x["valor"]

        # Série do saldo consolidado: só entram os dias em que ESTA conta tem
        # saldo conhecido. A cobertura sobe junto, para o gráfico poder dizer
        # com quantas contas cada ponto foi somado.
        saldos = arm.saldos_extrato(esquema, c["id"])
        dias_ancora = {s["dt"] for s in saldos}
        if saldos:
            der = cmp.saldo_derivado(cmp.agregar_extrato(lancs), saldos)
            for dt, v in der.items():
                if v is None or not (dt_de <= dt <= dt_ate):
                    continue
                serie_por_dia[dt]["saldo"] += v
                serie_por_dia[dt]["contas"] += 1

        p = pos.get(c["id"], {})
        bancos.append({
            "conta_id": c["id"], "ident": c["ident"], "rotulo": c["rotulo"],
            "banco": cod, "banco_nome": nome,
            "recebido": round(recebido, 2), "pago": round(pago, 2),
            "lancamentos": len(lancs),
            "saldo": p.get("saldo"), "saldo_dt": p.get("dt"),
            "sem_saldo_por": p.get("sem_saldo_por"),
            "atraso_uteis": p.get("atraso_uteis"),
            "custo": round(custo, 2),
            # O CUSTO POR R$ MIL RECEBIDO é a coluna que decide realocação de
            # fluxo, e é o que expõe que Itaú e Bradesco movimentam quase o
            # mesmo (R$ 9,18 mi x R$ 9,10 mi) e o Itaú custa 125 vezes mais.
            # Sem denominador não é comparável: em valor absoluto o Sicredi
            # (R$ 1.659) parece barato ao lado do Itaú (R$ 36.935), quando na
            # verdade consome 35% de tudo que passa por ele.
            "custo_por_mil": (round(custo / (recebido / 1000), 2)
                              if recebido >= 1000 else None),
            "custo_natureza": [{"chave": k, "qtd": v[0], "valor": round(v[1], 2)}
                               for k, v in sorted(por_nat.items(),
                                                  key=lambda kv: -kv[1][1])],
            "ancoras": len(dias_ancora),
            "saldo_medido": len(dias_ancora) > 1,
        })

    total_recebido = sum(b["recebido"] for b in bancos) or 0.0
    for b in bancos:
        b["pct_recebido"] = (round(100 * b["recebido"] / total_recebido, 1)
                             if total_recebido else 0.0)
    # ordenado pelo que decide: custo relativo primeiro, depois volume
    bancos.sort(key=lambda b: (-(b["custo_por_mil"] or -1), -b["recebido"]))

    serie = [{"dt": d, "saldo": round(v["saldo"], 2), "contas": v["contas"]}
             for d, v in sorted(serie_por_dia.items())]
    custo_total = sum(g["valor"] for g in custo_nat.values())
    juros = custo_nat.get("juros", {}).get("valor", 0.0)

    dias = max((date.fromisoformat(dt_ate) - date.fromisoformat(dt_de)).days + 1, 1)
    por_pct = sorted((b["pct_recebido"] for b in bancos), reverse=True)

    kpis = {
        "saldo_total": round(sum(b["saldo"] or 0 for b in bancos), 2),
        "contas": sum(1 for b in bancos if b["saldo"] is not None),
        "contas_sem_saldo": sum(1 for b in bancos if b["saldo"] is None),
        "recebido": round(total_recebido, 2),
        "pago": round(sum(b["pago"] for b in bancos), 2),
        "custo": round(custo_total, 2),
        # ANUALIZADO A PARTIR DO PERÍODO ESCOLHIDO, não multiplicado por 12: o
        # filtro pode trazer 26 dias ou 90, e um "x12" cego em cima de meio mês
        # dobraria o número.
        "custo_ano": round(custo_total / dias * 365, 2),
        "custo_juros": round(juros, 2),
        "custo_juros_pct": round(100 * juros / custo_total, 1) if custo_total else 0.0,
        "contas_com_juros": sum(1 for b in bancos
                                if any(n["chave"] == "juros" for n in b["custo_natureza"])),
        "concentracao_2": round(sum(por_pct[:2]), 1),
        "dias": dias,
    }
    return {
        "kpis": kpis, "bancos": bancos, "serie": serie,
        "custo_por_natureza": sorted(custo_nat.values(),
                                     key=lambda g: -g["valor"]),
        "alertas": _alertas(bancos, kpis),
        "dt_de": dt_de, "dt_ate": dt_ate,
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "fonte": ("extrato importado (ext_lancamento e ext_saldo). O saldo é o "
                  "de CONTA CORRENTE — aplicação não aparece em arquivo nenhum."),
    }


def _alertas(bancos: list[dict], kpis: dict) -> list[dict]:
    """O que exige ação, com o número que sustenta cada frase.

    Alerta sem número é opinião; por isso cada um carrega o valor medido e o
    banco a que se refere.
    """
    out = []
    for b in bancos:
        nome = b["banco_nome"] or b["rotulo"]
        # conta que custa uma fatia grande do que movimenta: o denominador é
        # que denuncia, não o valor absoluto
        if b["custo_por_mil"] is not None and b["custo_por_mil"] > 50:
            out.append({
                "nivel": "critico", "banco": nome,
                "texto": (f"{nome} custou R$ {b['custo']:,.2f} para movimentar "
                          f"R$ {b['recebido']:,.2f} — {b['custo_por_mil']/10:.1f}% "
                          "de tudo que passou por ela.")})
        juros = next((n for n in b["custo_natureza"] if n["chave"] == "juros"), None)
        if juros and juros["valor"] > 1000:
            out.append({
                "nivel": "critico", "banco": nome,
                "texto": (f"{nome} cobrou R$ {juros['valor']:,.2f} de juros de "
                          f"limite em {juros['qtd']} lançamento(s) — a conta "
                          "passou o período no negativo.")})
        if b["saldo"] is None:
            out.append({
                "nivel": "atencao", "banco": nome,
                "texto": (f"{nome} fica fora do saldo consolidado: "
                          f"{b['sem_saldo_por'] or 'sem âncora de saldo'}.")})
        if (b["atraso_uteis"] or 0) > 1:
            out.append({
                "nivel": "atencao", "banco": nome,
                "texto": (f"{nome} está há {b['atraso_uteis']} dias úteis sem "
                          "extrato importado.")})
    if kpis["concentracao_2"] >= 70:
        dois = [b["banco_nome"] or b["rotulo"] for b in
                sorted(bancos, key=lambda x: -x["recebido"])[:2]]
        out.append({
            "nivel": "atencao", "banco": None,
            "texto": (f"{kpis['concentracao_2']}% do que entra passa por dois "
                      f"bancos ({' e '.join(dois)}).")})
    ordem = {"critico": 0, "atencao": 1}
    out.sort(key=lambda a: ordem.get(a["nivel"], 9))
    return out
