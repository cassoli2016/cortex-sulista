"""Alertas proativos — o painel avisa, em vez de esperar alguém abrir.

`build_alertas()` varre as consultas já existentes (cacheadas) e devolve a
lista de itens que exigem ação, por severidade. `digest_texto()` monta o
resumo diário em texto puro (e-mail/notificação).

Envio: scripts/digest_diario.sh (LaunchAgent às 7h). Com SMTP_HOST/SMTP_USER/
SMTP_PASS/SMTP_PARA no .env envia e-mail; sem SMTP, notificação do macOS.
"""
from __future__ import annotations

import logging
from datetime import date

from . import queries

log = logging.getLogger("cortex.alertas")


def _fmt_brl(v: float) -> str:
    s = f"{v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def build_alertas() -> list[dict]:
    """Itens de ação: nivel critico|atencao|info, titulo, texto."""
    itens: list[dict] = []

    def add(nivel: str, titulo: str, texto: str) -> None:
        itens.append({"nivel": nivel, "titulo": titulo, "texto": texto})

    try:
        p = queries.get_programacao()["kpis"]
        if p["cnh_vencida_rodando"]:
            add("critico", "Motorista com CNH vencida EM VIAGEM",
                f"{p['cnh_vencida_rodando']} motorista(s) rodando agora com CNH vencida "
                f"(total vencidas: {p['cnh_vencida']}). Infração gravíssima e risco de seguro. "
                "Detalhe: Operação > Programação Intel.")
        elif p["cnh_vencida"]:
            add("atencao", "CNH vencida no quadro ativo",
                f"{p['cnh_vencida']} motorista(s) ativos com CNH vencida; "
                f"{p['cnh_vencendo']} vencem em 30 dias.")
        if p["sem_retorno"]:
            add("info", "Veículos descarregando sem retorno casado",
                f"{p['sem_retorno']} veículo(s) chegam ao destino em 72h sem carga de volta "
                "programada — fila de venda de frete de retorno.")
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas programacao: %s", exc)

    try:
        vg = queries.get_visao_geral()
        at = vg.get("atingimento_mes")
        if at is not None and at <= 2:   # vem como fração (0..1)
            at *= 100
        if at is not None and at < 90:
            add("atencao", "Meta do mês em risco",
                f"Atingimento acumulado de {at:.0f}% da meta de faturamento. "
                f"Realizado {_fmt_brl(vg.get('realizado_acumulado') or 0)} de "
                f"{_fmt_brl(vg.get('meta_acumulada') or 0)}.")
        saldo = vg.get("saldo_atual")
        if saldo is not None and saldo < 0:
            add("critico", "Caixa negativo",
                f"Saldo consolidado em {_fmt_brl(saldo)}.")
        gap = vg.get("gap_mes")
        if gap and gap not in ("sem gap no horizonte", "agora"):  # "agora" = caixa negativo, já alertado
            add("atencao", "Gap de caixa no horizonte",
                f"Fluxo projetado fica negativo em: {gap}.")
        venc = vg.get("receber_vencido")
        if venc:
            add("atencao", "Recebíveis vencidos",
                f"{_fmt_brl(venc)} vencidos em aberto. Régua: Financeiro > Cobrança.")
        if vg.get("oc_atrasadas"):
            add("info", "Ordens de compra atrasadas",
                f"{vg['oc_atrasadas']} OCs com recebimento atrasado "
                f"({_fmt_brl(vg.get('oc_atraso_valor') or 0)}).")
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas visao geral: %s", exc)

    try:
        s = queries.get_seguranca()["kpis"]
        if s["cercas_24h"]:
            add("atencao", "Violações de cerca nas últimas 24h",
                f"{s['cercas_24h']} novas violações ({s['cercas_abertas_7d']} abertas na semana). "
                "Detalhe: Torres > Torre de Segurança.")
        if s["excesso_agora"]:
            add("critico", "Excesso de velocidade agora",
                f"{s['excesso_agora']} veículo(s) acima de 90 km/h nas últimas 2 horas.")
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas seguranca: %s", exc)

    ordem = {"critico": 0, "atencao": 1, "info": 2}
    itens.sort(key=lambda i: ordem.get(i["nivel"], 9))
    return itens


def digest_texto() -> str:
    hoje = date.today().strftime("%d/%m/%Y")
    itens = build_alertas()
    linhas = [f"CÓRTEX SULISTA — resumo do dia {hoje}", ""]
    if not itens:
        linhas.append("Sem pendências críticas hoje.")
    icone = {"critico": "[CRÍTICO]", "atencao": "[ATENÇÃO]", "info": "[info]"}
    for i in itens:
        linhas.append(f"{icone[i['nivel']]} {i['titulo']}")
        linhas.append(f"  {i['texto']}")
        linhas.append("")
    linhas.append("Painel: http://127.0.0.1:8000")
    return "\n".join(linhas)
