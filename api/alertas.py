"""Alertas proativos — o painel avisa, em vez de esperar alguém abrir.

`build_alertas()` varre as consultas já existentes (cacheadas) e devolve a
lista de itens que exigem ação, por severidade. `digest_texto()` monta o
resumo diário em texto puro (e-mail/notificação).

Envio: scripts/digest_diario.sh (LaunchAgent às 7h). Com SMTP_HOST/SMTP_USER/
SMTP_PASS/SMTP_PARA no .env envia e-mail; sem SMTP, notificação do macOS.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import queries
from . import db
# leitura ÚNICA de "quais fontes estão fora" (mesma regra do gate do snapshot
# em previsao/servico.py) — módulo puro, sem I/O no import.
from .previsao.motor import fontes_fora

log = logging.getLogger("cortex.alertas")


def _fmt_brl(v: float) -> str:
    s = f"{v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _data_br(iso: str | None) -> str:
    if not iso:
        return "-"
    p = str(iso).split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else str(iso)


def _fmt_brl_cent(v: float) -> str:
    """Como `_fmt_brl`, mas com centavos. A tolerância de divergência do
    extrato é de 1 centavo (`comparacao.TOLERANCIA`), então arredondar para
    o real inteiro (como `_fmt_brl` faz nos outros alertas) mostraria
    "R$ 0" num alerta CRÍTICO sempre que a diferença real for < R$ 0,50.

    Sinal SEMPRE antes do "R$" (`-R$ 1.250,40`, nunca `R$ -1.250,40`) - hoje
    só é chamada com `abs(...)`, mas normalizar aqui evita a armadilha para
    quem reusar a função depois com um valor negativo direto (achado da
    revisão, fix round 2)."""
    sinal = "-" if v < 0 else ""
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}R$ {s}"


def _alerta_divergencia(c: dict, f: dict) -> tuple[str, str, str]:
    """Monta o alerta CRÍTICO de divergência de uma conta - fonte ÚNICA usada
    tanto pelo estado `diverge` quanto pelo estado `desatualizado` com
    `diverge_no_ultimo_dia` (achado I3): duplicar este texto nos dois lugares
    é exatamente a classe de bug deste plano (regra repetida divergindo entre
    si)."""
    delta = f.get("delta")
    dt_txt = _data_br(f.get("dt"))
    if delta is None:
        # nenhum dos três campos (saldo/credito/debito) existia dos
        # dois lados para comparar - nao afirma valor nem direcao.
        return ("critico", "Extrato bancário divergente",
                f"A conta {c['rotulo']} tem um dia divergente em {dt_txt} "
                "sem valor comparável (sem saldo, crédito nem débito dos "
                "dois lados) - confira o painel. Detalhe: Financeiro > "
                "Extrato Bancário.")
    origem = f.get("delta_origem")
    if origem in ("credito", "debito"):
        # direção (acima/abaixo do saldo) só existe para saldo:
        # d_debito positivo empurra o saldo do extrato para BAIXO,
        # o oposto do que "acima" diria - por isso aqui NUNCA
        # entra acima/abaixo, só o valor e o campo de origem.
        rotulo_campo = "crédito" if origem == "credito" else "débito"
        return ("critico", "Extrato bancário divergente",
                f"A conta {c['rotulo']} tem divergência de "
                f"{_fmt_brl_cent(abs(delta))} no {rotulo_campo} do dia "
                f"{dt_txt}. Detalhe: Financeiro > Extrato Bancário.")
    # origem "saldo" (ou ausente/desconhecida - mesmo texto de
    # sempre, o único caso com semântica de direção definida)
    return ("critico", "Extrato bancário divergente",
            f"A conta {c['rotulo']} fecha {_fmt_brl_cent(abs(delta))} "
            f"{'acima' if delta > 0 else 'abaixo'} do ERP em "
            f"{dt_txt}. Detalhe: Financeiro > Extrato Bancário.")


def _alertas_extrato(painel: dict) -> list[tuple[str, str, str]]:
    """(nivel, titulo, texto) por conta com problema. Função pura para teste."""
    out: list[tuple[str, str, str]] = []
    for c in painel.get("contas") or []:
        if not c.get("mapeada"):
            continue          # sem vínculo com o ERP não há o que comparar
        f = c.get("farol") or {}
        estado = f.get("estado")
        if estado == "diverge":
            out.append(_alerta_divergencia(c, f))
        elif estado == "desatualizado":
            # I2: `dias_sem_extrato` é `None` para conta mapeada que NUNCA teve
            # importação (o fluxo CSV cria e mapeia a conta ANTES do primeiro
            # upload - basta o primeiro import falhar, ex. mapa de colunas
            # errado, para a conta ficar mapeada e cega pra sempre) ou depois
            # de desfazer o único upload. `and f.get("dias_sem_extrato")` era
            # truthiness sobre número: `None` E `0` os dois davam falso e o
            # caso mais grave (nunca importou) saía SEM nenhum alerta. Agora é
            # sempre `is not None`, com texto próprio para o caso `None`; `0`
            # continua sem alerta (dizer "há 0 dias" seria absurdo).
            d = f.get("dias_sem_extrato")
            if d is None:
                out.append((
                    "atencao", "Extrato bancário sem atualização",
                    f"A conta {c['rotulo']} está vinculada ao ERP mas nunca teve "
                    "um extrato importado - a validação de saldo dessa conta "
                    "está cega."))
            elif d > 0:
                # O que DISPARA o aviso e' o dia util pulado, nao o corrido: a
                # rotina e' subir o extrato do dia anterior, e sabado, domingo e
                # o proprio dia de hoje nao contam. Sem os dois numeros no
                # texto, "ha 4 dias sem extrato" numa terca-feira parece erro
                # de quem enviou na sexta - sao 4 corridos e 1 util.
                u = f.get("atraso_uteis")
                util = (f" ({u} {'dia útil' if u == 1 else 'dias úteis'} de movimento"
                        " sem enviar)") if u else ""
                out.append((
                    "atencao", "Extrato bancário sem atualização",
                    f"A conta {c['rotulo']} está há {d} {'dia' if d == 1 else 'dias'} "
                    f"sem extrato importado{util} - a validação de saldo está cega "
                    "nesse período."))
            # I3: a precedência de COR do farol põe "desatualizado" acima de
            # "diverge", mas uma divergência real confirmada no último dia
            # válido não pode desaparecer do digest por causa disso - emite os
            # DOIS alertas (o de desatualização acima e o crítico abaixo).
            if f.get("diverge_no_ultimo_dia"):
                out.append(_alerta_divergencia(c, f))
    return out


def _janela_alerta(hoje: date) -> tuple[str, str]:
    """Janela consultada ao `painel` do extrato para o digest: 30 dias corridos
    terminando hoje, NÃO o mês corrente (`hoje.replace(day=1)`) como as telas
    usam de costume. No dia 1º de qualquer mês, `replace(day=1)` reduziria a
    janela a um único dia (hoje) e apagaria justamente a divergência do
    fechamento do mês anterior — o caso em que o alerta mais importa. 30 dias
    atravessa qualquer virada de mês com folga acima do limiar de
    "desatualizado" do farol (hoje: mais de um dia ÚTIL pulado), sem inundar o digest
    antigo."""
    return (hoje - timedelta(days=30)).isoformat(), hoje.isoformat()


def _alertas_previsao(payload: dict) -> list[tuple[str, str, str]]:
    """Alertas da previsão de fechamento (mês corrente). Puro — testável.

    O digest/push é o ÚNICO canal que chega ao celular do gestor: se a
    previsão foi montada com uma fonte fora, ele precisa saber ANTES de agir
    sobre o número. Duas consequências, ambas obrigatórias:

    1. item próprio nomeando as fontes que falharam (o filtro de avisos só
       casa "diverge", que NENHUM dos avisos de degradação contém);
    2. o alerta de resultado negativo cai de `critico` para `atencao` e
       carrega a nota — previsão erguida sobre driver ausente não pode
       acordar ninguém como se fosse número firme.

    `fontes_fora(..., apenas_drivers=True)` ignora o orçamento: ele não entra
    em previsto nenhum, e um ano sem versão cadastrada rebaixaria todo dia um
    alerta legítimo."""
    itens: list[tuple[str, str, str]] = []
    k = payload.get("kpis") or {}
    fora = fontes_fora(payload.get("fontes"), apenas_drivers=True)
    nota = (" ATENÇÃO: previsão montada com fonte degradada ("
            + ", ".join(fora) + ") — o número pode mudar muito quando a fonte "
            "voltar.") if fora else ""
    if fora:
        itens.append(("atencao", "Previsão de fechamento com fonte degradada",
                      f"A previsão de {payload.get('mes')} foi montada sem: "
                      f"{', '.join(fora)}. As linhas que dependem dessa(s) fonte(s) "
                      "trocaram de método (nível histórico). Detalhe e chips de "
                      "fonte: Controladoria > Fechamento do Mês."))
    prev = k.get("resultado_previsto")
    orc = k.get("resultado_orcado")
    if prev is not None and prev < 0:
        itens.append(("atencao" if fora else "critico",
                      "Resultado do mês previsto NEGATIVO",
                      f"A previsão de fechamento de {payload.get('mes')} aponta "
                      f"{_fmt_brl(prev)}. Detalhe: Controladoria > Fechamento do "
                      f"Mês.{nota}"))
    elif prev is not None and orc is not None and prev < orc:
        itens.append(("atencao", "Resultado do mês abaixo do orçado",
                      f"Previsto {_fmt_brl(prev)} contra orçado {_fmt_brl(orc)} "
                      f"({_fmt_brl(prev - orc)}). Detalhe: Controladoria > "
                      f"Fechamento do Mês.{nota}"))
    for a in payload.get("avisos") or []:
        if "diverge" in a.lower():
            itens.append(("info", "Divergência de fonte na previsão", a))
    return itens


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

    try:
        # A FONTE MUDOU do ERP para a RasterJOR, que é quem apura jornada: lá a
        # violação dos 5h30 vem NOMEADA (`DIRECAO ININTERRUPTA`) em vez de
        # derivada dos macros. Mesma regra da Lei 13.103, origem melhor.
        from api.jornada.leitura import alerta_direcao_continua
        j = alerta_direcao_continua()
        if j:
            nivel = "critico" if j["n"] >= 20 else "atencao"
            add(nivel, "Excesso de direção contínua no mês",
                f"{j['n']} ocorrência(s) de direção contínua acima de 5h30 neste mês "
                f"(Lei 13.103), entre {j['motoristas']} motorista(s). "
                "Detalhe: Operação > Jornada do Motorista.")
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas jornada: %s", exc)

    try:
        r = db.query("""SELECT count(DISTINCT (grupo,empresa,filial,unidade,
              diferenciadornumero,serie,numero)) AS n
            FROM coleta_ocorrencia
            WHERE ocorrencia = 261 AND dtinc >= now() - interval '72 hours'""")
        n = (r[0]["n"] if r else 0) or 0
        if n:
            add("critico", "Cargas críticas nas últimas 72h",
                f"{n} coleta(s) marcada(s) como carga crítica nas últimas 72h — "
                "exigem acompanhamento. Detalhe: Operação > Torre de Controle.")
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas cargas criticas: %s", exc)

    try:
        from api.extrato.servico import painel as extrato_painel
        dt_de, dt_ate = _janela_alerta(date.today())
        p = extrato_painel(dt_de, dt_ate)
        for nivel, titulo, texto in _alertas_extrato(p):
            add(nivel, titulo, texto)
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas extrato: %s", exc)

    try:
        from api.previsao import get_previsao_fechamento
        p = get_previsao_fechamento()
        for nivel, titulo, texto in _alertas_previsao(p):
            add(nivel, titulo, texto)
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas previsao: %s", exc)

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
