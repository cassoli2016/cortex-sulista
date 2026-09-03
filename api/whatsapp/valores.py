"""Quem preenche as variáveis de um modelo com os números de verdade.

Sem isto, um modelo de faturamento diário obrigaria alguém a digitar nove
valores todo dia, copiando da Visão Geral — que é justamente o tipo de tarefa
em que o erro passa despercebido (um dígito a menos no acumulado do mês e a
mensagem sai dizendo que a empresa faturou um décimo do que faturou).

A ARMADILHA DESTE MÓDULO, e a razão de ele existir separado: **o CÓRTEX tem
TRÊS recortes de receita que não são o mesmo número**, e a Visão Geral devolve
os três lado a lado —

    faturamento_mes        faturas emitidas          R$ 11,28 mi
    realizado_acumulado    a régua da META           R$ 10,73 mi
    receita_mes_cte        CT-e                      (outro corte ainda)

Misturar `faturamento_mes` com `meta_acumulada` produziria um atingimento de
96% onde o real é 91,3%: numerador de uma régua, denominador de outra. Aqui
numerador E denominador saem do MESMO `diario` (a régua da meta, já com a
distribuição sazonal), recortados nos DIAS FECHADOS — o resumo sai às 07:00,
e o dia corrente entra na régua MTD do painel com a meta cheia e o realizado
de minutos, derrubando atingimento e previsão todo início de manhã (medido
em 01/09: "-85,8% vs meta" às 04h de um mês que mal começara).

O DIA É O ÚLTIMO COM MOVIMENTO, não `hoje`: pela manhã o dia corrente tem
faturamento parcial e a série ainda traz zeros nos dias que não aconteceram.
Mandar "faturamos R$ 0 hoje" às 8h seria alarme falso diário.

E QUANDO ESSE DIA É O DE HOJE, A MENSAGEM DIZ QUE ESTÁ EM CURSO. Às 11h o dia
tinha 20% da meta — número correto e leitura desastrosa, porque faltavam nove
horas de faturamento. É a mesma regra que o painel aplica à barra do mês
corrente (hachurada, rotulada "parcial"); aqui não há hachura, então vai por
escrito no lugar em que a pessoa está olhando: o próprio atingimento.
"""
from __future__ import annotations

from datetime import date, timedelta


def brl(valor) -> str:
    """R$ 1.234.567,89 — o formato que quem lê espera, sem depender de locale
    instalado no servidor (que no Windows desta bancada não está)."""
    try:
        n = float(valor or 0)
    except (TypeError, ValueError):
        return "R$ 0,00"
    inteiro, dec = f"{abs(n):,.2f}".split(".")
    inteiro = inteiro.replace(",", ".")
    return f"{'-' if n < 0 else ''}R$ {inteiro},{dec}"


def pct(valor) -> str:
    try:
        return f"{float(valor or 0) * 100:.1f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return "0,0%"


# A URL pública do painel (túnel Cloudflare). Vai no fim do resumo diário —
# o clique cai no login de sempre, com MFA; o link em si não abre nada.
URL_PAINEL = "https://cortex.cassolitech.com.br"

_MES_PT = {1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
           5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
           9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO",
           12: "DEZEMBRO"}


def _semaforo(razao: float) -> str:
    """O semáforo da casa (>=95 / 70-94 / <70), em emoji — WhatsApp não tem
    a cor do painel, então a bolinha É o semáforo."""
    if razao >= 0.95:
        return "🟢"
    return "🟡" if razao >= 0.70 else "🔴"


def _farol_dia(faturado: float, meta: float, em_curso: bool) -> str:
    """⏳ quando o dia ainda está acontecendo (julgar às 07:00 acusaria quem
    ainda tem o dia inteiro pela frente) e ⚪ quando não havia meta a bater."""
    if not meta:
        return "⚪"
    if em_curso:
        return "⏳"
    return _semaforo(faturado / meta)


def _atingimento_dia(faturado: float, meta: float, em_curso: bool) -> str:
    """O atingimento do dia, dizendo quando o dia ainda não acabou.

    Sem a marca, o resumo das 11h anuncia 20% da meta — certo e desastroso,
    porque faltam nove horas de faturamento. Quem lê no celular não tem a
    hachura do painel para avisar; a frase precisa avisar sozinha.
    """
    if not meta:
        return "sem meta no dia"
    texto = pct(faturado / meta)
    return f"{texto} — dia ainda em curso" if em_curso else texto


def faturamento_diario(visao: dict | None = None,
                       diario_ant: list | None = None) -> dict:
    """As variáveis do contexto `faturamento` — o resumo da manhã.

    A REGRA DO DIA 1º (pedido do dono, 01/09/2026): a mensagem mostra SEMPRE
    o fechamento do dia ANTERIOR — e no dia 1º, quando ontem pertence ao mês
    que acabou, ela vira o FECHAMENTO DO MÊS: total × meta total, resultado
    final e o veredito, lidos do diário do mês anterior.

    `visao` e `diario_ant` são injetáveis para o teste não depender do ERP.
    """
    hoje = date.today()
    ontem = hoje - timedelta(days=1)
    fechamento = hoje.day == 1

    if visao is None:                       # pragma: no cover - caminho de produção
        from api import queries
        visao = queries.get_visao_geral()
    if fechamento and diario_ant is None:   # pragma: no cover - caminho de produção
        from api import queries
        diario_ant = queries.get_diario_mes_anterior()

    # o "mês" da mensagem: o corrente ATÉ ONTEM, ou o anterior INTEIRO no dia 1º
    dias = (diario_ant if fechamento else visao.get("diario")) or []
    if fechamento:
        dias_fechados = list(dias)
    else:
        dias_fechados = [d for d in dias if int(d.get("dia") or 0) < hoje.day]

    # ---- o DIA da mensagem é sempre ONTEM, já fechado ----
    # "Último dia com movimento" mostrava o parcial de hoje cedo com a marca
    # "em curso"; o pedido é o fechamento de ontem — e ontem sem movimento
    # num dia com meta é notícia (🔴 0,0%), não algo a esconder.
    dia = next((d for d in dias if int(d.get("dia") or 0) == ontem.day), {})
    fat_dia = float(dia.get("realizado") or 0)
    meta_dia = float(dia.get("meta") or 0)
    data = ontem.strftime("%d/%m/%Y")

    # ---- atingimento do mês sobre DIAS FECHADOS, nunca a régua MTD ----
    # A régua MTD do painel inclui o dia em curso com a meta CHEIA e o
    # realizado de minutos: às 07:00 isso derruba atingimento e previsão sem
    # ninguém ter errado nada — medido em 01/09: "-85,8% vs meta" às 04h de
    # um mês que mal começara. Numerador e denominador saem do MESMO `diario`
    # (a régua da meta, já sazonal) — não há mistura de réguas.
    meta_total = sum(float(d.get("meta") or 0) for d in dias)
    realizado_fech = sum(float(d.get("realizado") or 0) for d in dias_fechados)
    meta_fech = sum(float(d.get("meta") or 0) for d in dias_fechados)

    ritmo = (realizado_fech / meta_fech) if meta_fech > 0 else 1.0
    previsao = realizado_fech + ritmo * max(0.0, meta_total - meta_fech)

    if meta_total > 0:
        dif = previsao / meta_total - 1
        sinal = "+" if dif >= 0 else "-"
        previsao_vs_meta = f"{sinal}{pct(abs(dif))} vs meta do mês"
        farol_previsao = "📈" if previsao >= meta_total else "📉"
    else:
        previsao_vs_meta = "sem meta no mês"
        farol_previsao = "➖"

    fechados = [d for d in dias_fechados if float(d.get("meta") or 0) > 0]
    media_fechados = (sum(float(d.get("realizado") or 0) for d in fechados)
                      / len(fechados)) if fechados else 0.0
    falta_total = max(0.0, meta_total - realizado_fech)

    if fechamento:
        titulo_mes = f"FECHAMENTO DE {_MES_PT[ontem.month]}"
        titulo_previsao = "RESULTADO FINAL"
        # não há ritmo a cobrar de um mês encerrado — a linha vira a média
        # realizada, que é o número que o próximo mês tem de sustentar
        linha_ritmo = (f"Média realizada: {brl(media_fechados)}/dia "
                       f"({len(fechados)} dias com meta)" if fechados
                       else "mês sem meta cadastrada")
        # o veredito segue a MESMA régua do semáforo (≥95 = quase, âmbar):
        # 95,4% com farol verde e veredito vermelho na linha seguinte seria a
        # mensagem se desmentindo — visto na primeira prévia real
        pontos: list[str] = []
        if meta_total > 0:
            razao = realizado_fech / meta_total
            if razao >= 1:
                pontos.append(f"✅ Meta do mês batida: +{pct(razao - 1)}")
            elif razao >= 0.95:
                pontos.append(f"🟡 Quase: fechou {brl(falta_total)} abaixo "
                              f"da meta ({pct(falta_total / meta_total)})")
            else:
                pontos.append(f"🔴 Fechou {brl(falta_total)} abaixo da meta "
                              f"({pct(falta_total / meta_total)})")
        abaixo = sum(1 for d in fechados
                     if float(d.get("realizado") or 0) < float(d.get("meta") or 0))
        if fechados and abaixo > len(fechados) / 2:
            pontos.append(f"📉 {abaixo} de {len(fechados)} dias com meta "
                          "ficaram abaixo dela")
        pontos_atencao = ("\n".join(pontos[:3]) if pontos
                          else "✅ Mês encerrado sem pontos de atenção")
    else:
        titulo_mes = "MÊS ATÉ ONTEM"
        titulo_previsao = "PREVISÃO DE FECHAMENTO"
        restantes = [d for d in dias
                     if float(d.get("meta") or 0) > 0
                     and int(d.get("dia") or 0) >= hoje.day]
        if falta_total == 0:
            necessario_v = 0.0
            linha_ritmo = "Meta do mês já batida 🎉"
        elif restantes:
            necessario_v = falta_total / len(restantes)
            linha_ritmo = (f"Ritmo p/ meta: {brl(necessario_v)}/dia "
                           f"({len(restantes)} dias com meta)")
        else:
            necessario_v = 0.0
            linha_ritmo = (f"Faltam {brl(falta_total)} — sem dias com meta "
                           "restantes")
        pontos = []
        if meta_total > 0 and previsao < meta_total:
            gap = 1 - previsao / meta_total
            if gap > 0.02:
                pontos.append(f"🔴 No ritmo atual o mês fecha {pct(gap)} "
                              "abaixo da meta")
            else:
                pontos.append(f"🟡 Projeção no limite: {pct(gap)} abaixo da meta")
        seguidos = 0
        for d in reversed(fechados):
            if float(d.get("realizado") or 0) < float(d.get("meta") or 0):
                seguidos += 1
            else:
                break
        if seguidos >= 2:
            pontos.append(f"📉 {seguidos} dias seguidos abaixo da meta diária")
        if media_fechados > 0 and necessario_v > media_fechados * 1.10:
            alta = int(round((necessario_v / media_fechados - 1) * 100))
            pontos.append(f"⚡ O ritmo diário precisa subir {alta}% "
                          "para fechar o mês")
        pontos_atencao = ("\n".join(pontos[:3]) if pontos
                          else "✅ Ritmo dentro da meta — sem pontos de atenção")

    out = {
        "data": data,
        "faturado_dia": brl(fat_dia),
        "meta_dia": brl(meta_dia),
        # dia sem meta (domingo, feriado) não é 0% de atingimento: é dia sem
        # meta a bater, e mostrar "0,0%" em vermelho seria acusar quem cumpriu
        "atingimento_dia": _atingimento_dia(fat_dia, meta_dia, False),
        "farol_dia": _farol_dia(fat_dia, meta_dia, False),
        "titulo_mes": titulo_mes,
        "acumulado_mes": brl(realizado_fech),
        "meta_mes": brl(meta_fech),
        "atingimento_mes": (pct(realizado_fech / meta_fech) if meta_fech > 0
                            else "sem meta até aqui"),
        "farol_mes": (_semaforo(realizado_fech / meta_fech) if meta_fech > 0
                      else "⚪"),
        "falta_mes": brl(falta_total),
        "mes_anterior": brl(visao.get("faturamento_mes_ant")),
        "titulo_previsao": titulo_previsao,
        "previsao_mes": brl(previsao),
        "previsao_vs_meta": previsao_vs_meta,
        "farol_previsao": farol_previsao,
        "linha_ritmo": linha_ritmo,
        "pontos_atencao": pontos_atencao,
        # atrás do Cloudflare Access: quem clica passa pelo login de sempre
        "link_painel": URL_PAINEL,
    }
    if not any((d.get("realizado") or 0) > 0 for d in dias) and not (
            fechamento and meta_total > 0):
        # nem emissão nem (no dia 1º) meta: não há resumo a fazer — é o
        # terceiro estado da agenda (nada a enviar), não uma falha
        out["_silencio"] = ("o mês anterior não tem movimento nem meta"
                            if fechamento
                            else "o mês ainda não tem emissão registrada")
    return out


def smartec_prazo_indicacao(dados: dict | None = None) -> dict:
    """As variáveis do contexto `smartec_prazo`.

    DUAS COISAS QUE ESTA FUNÇÃO FAZ E QUE NÃO SÃO ÓBVIAS:

    1. **`_silencio` quando não há nada vencendo.** Não é erro, é a resposta
       certa: mandar "0 notificações vencem hoje" toda manhã transforma o aviso
       em ruído, e o dia em que houver três ninguém vai ler. Quem trata isso é
       `agenda.montar_texto`, que distingue os três estados — mandou, não
       mandou por falha, não havia o que mandar.

    2. **NENHUMA VARIÁVEL SAI VAZIA.** `montar_texto` recusa o envio se
       qualquer variável do modelo vier em branco — guarda certa, que existe
       para "Faturamento de hoje: R$ 0,00" não chegar à diretoria. Aqui isso
       morde num caso específico: quando só há notificações vencendo HOJE e
       nenhuma nos próximos dias, `proximos` ficaria vazio e o aviso inteiro
       seria engolido — justamente no dia mais urgente. Por isso `proximos` tem
       texto também quando não há próximos.

    `dados` é injetável para o teste não depender do banco.
    """
    if dados is None:                       # pragma: no cover - produção
        from api.smartec import leitura
        dados = leitura.prazo_indicacao_alerta(dias=2)

    if dados.get("erro"):
        # Não dá para SABER. Sobe como exceção para `montar_texto` registrar o
        # motivo e não enviar — silenciar aqui seria afirmar que não há prazo
        # correndo quando a verdade é que ninguém está olhando.
        raise ValueError(dados["erro"])
    if dados.get("silencio"):
        return {"_silencio": dados["silencio"]}

    hoje = dados.get("hoje") or []
    depois = dados.get("depois") or []

    linhas = []
    for x in hoje:
        pts = x.get("pontuacao")
        linhas.append("\U0001f69b *%s*" % (x.get("placa") or "?"))
        linhas.append("     %s" % (x.get("descricao") or "infração não descrita"))
        linhas.append("     \U0001f4c4 AIT %s · %s"
                      % (x.get("ait") or "?",
                         x.get("orgao") or "órgão não informado"))
        linhas.append("     \U0001f4b0 %s  ·  ⚠️ %s pontos"
                      % (brl(x.get("valor_a_pagar")),
                         pts if pts is not None else "?"))
        linhas.append("")
    lista = "\n".join(linhas).rstrip()

    if depois:
        por_dia: dict[int, list[str]] = {}
        for x in depois:
            por_dia.setdefault(int(x["dias"]), []).append(x.get("placa") or "?")
        partes = []
        for d in sorted(por_dia):
            quando = "Amanhã" if d == 1 else "Em %d dias" % d
            partes.append("%s vencem mais *%d*: %s"
                          % (quando, len(por_dia[d]), ", ".join(por_dia[d])))
        proximos = "\U0001f4c5 " + " · ".join(partes)
    else:
        # NUNCA vazio — ver a nota 2 no cabeçalho.
        proximos = "✅ Nenhuma outra vence nos próximos dias."

    return {
        "data": date.today().strftime("%d/%m/%Y"),
        "quantidade": str(len(hoje)),
        "lista": lista,
        "total": brl(dados.get("total_hoje")),
        "proximos": proximos,
    }


def _barra(parte: int, todo: int, casas: int = 10) -> str:
    """A barra de progresso em emoji. No WhatsApp não há gráfico, e um
    percentual solto (“24%”) não dá a noção de quanto FALTA — a barra dá, e é
    a única coisa da mensagem que se lê sem ler."""
    if not todo:
        return "⬜" * casas
    cheios = int(round(casas * parte / todo))
    return "🟩" * cheios + "⬜" * (casas - cheios)


def comunicacao_3s(dados: dict | None = None) -> dict:
    """As variáveis do contexto `comunicacao_3s` — o alerta diário das carretas.

    O QUE ESTE AVISO FAZ DE DIFERENTE dos outros do canal:

    1. **Ele NÃO se cala quando não há novidade.** Os outros avisos silenciam
       para não virar ruído; este é uma RÉGUA de acompanhamento, e a régua que
       só aparece em dia ruim não mede nada. O dia em que os 142 continuarem
       142 é informação — é justamente o dia em que alguém precisa cobrar.

    2. **A recusa tem texto próprio e acusa o lado certo.** Se a integração de
       posições parar, a leitura crua diria “0 comunicaram”: alarme verdadeiro
       no número e falso na conclusão, que culparia a 3S por um cano nosso.
       `status_alerta` confere o frescor do cano ANTES do conteúdo e devolve o
       motivo; aqui ele sobe como ValueError para `montar_texto` registrar e
       não enviar.

    3. **O dia é FECHADO** (até 23:59 de ontem). Às 09:00, “hoje” contaria como
       muda toda carreta que ainda não reportou desde a meia-noite.
    """
    if dados is None:                       # pragma: no cover - produção
        from api import comunicacao_3s as _c3
        dados = _c3.status_alerta()

    if dados.get("erro"):
        raise ValueError(dados["erro"])

    dia, t = dados["dia"], dados["hoje"]
    frota, comunicou = t["frota"], t["comunicou"]
    ant = dados.get("anterior")
    # O aviso é SÓ da 3S: a régua da frota com motor saiu do texto a pedido de
    # quem opera, e estava certo — ela respondia uma pergunta que não é a deste
    # aviso. O que ela protegia continua de pé em `status_alerta`, que recusa o
    # envio quando a integração de posições para, em vez de mandar "0
    # comunicaram" e culpar a 3S por um cano nosso. Some a linha, fica a trava.
    dif = dados.get("diferenca") or {}
    if dif.get("primeira"):
        lista = "📎 A partir de amanhã, o anexo com as placas vem quando a lista mudar."
    elif dif.get("mudou"):
        partes = []
        if dif.get("entraram"):
            partes.append("entraram %d" % len(dif["entraram"]))
        if dif.get("sairam"):
            partes.append("saíram %d" % len(dif["sairam"]))
        lista = "📎 A lista mudou (%s) — segue em anexo." % " · ".join(partes)
    else:
        lista = "📎 A lista é a mesma de ontem — sem anexo hoje."

    if ant and dados.get("troca_de_regua"):
        # Ver a nota em `comunicacao_3s.status_alerta`: no dia em que a leitura
        # direta da 3S entrou, o salto é de RÉGUA, não de frota. Anunciar "+74
        # comunicando" seria comemorar o que não aconteceu.
        evolucao = ("🔎 A partir de hoje o número vem direto da 3S, e não mais "
                    "só do ERP — por isso o salto. A comparação com ontem "
                    "recomeça amanhã.")
    elif ant:
        d_com = comunicou - ant["comunicou"]
        d_nunca = t["nunca"] - ant["nunca"]
        sinal = lambda n: ("+%d" % n) if n > 0 else str(n)
        if d_com == 0 and d_nunca == 0:
            evolucao = "➡️ Igual a %s — nada mudou." % ant["dia"].strftime("%d/%m")
        else:
            # A SETA SEGUE O QUE MELHORA, não o que cresce: “nunca” caindo é
            # bom e leva ▲ verde na leitura de quem cobra.
            evolucao = "%s Contra %s: %s comunicando · %s nunca" % (
                "📈" if (d_com > 0 or d_nunca < 0) else "📉",
                ant["dia"].strftime("%d/%m"), sinal(d_com), sinal(d_nunca))
    else:
        evolucao = "🆕 Primeira medição — a partir de amanhã este aviso mostra a variação."

    # O ANEXO SÓ QUANDO A LISTA MUDA, e "mudou" é por PLACA, não por contagem.
    # A lista de 142 não muda de um dia para o outro, e um PDF de cinco páginas
    # todo santo dia vira o anexo que ninguém abre — inclusive no dia em que
    # ele importa. `_anexo` sai de `vals` na agenda, antes de renderizar.
    fora = {}
    if dif.get("mudou") and dados.get("placas"):
        from api import comunicacao_pdf as _pdf
        cobranca = [p for p in dados["placas"]
                    if p["situacao"] in ("nunca", "mudo15", "parou")]
        if cobranca:
            fora["_anexo"] = (_pdf.gerar(dia, cobranca, dados.get("alvo", "3S")),
                              _pdf.nome_arquivo(dia, dados.get("alvo", "3S")),
                              "pdf")

    return {
        **fora,
        "data": dia.strftime("%d/%m/%Y"),
        "barra": "%s  %d%%" % (_barra(comunicou, frota),
                               round(100 * comunicou / frota) if frota else 0),
        "total": str(frota),
        "comunicou": str(comunicou),
        "nunca": str(t["nunca"]),
        "mudo15": str(t["mudo_15d"]),
        "parou": str(max(0, t["parou"])),
        "evolucao": evolucao,
        "lista": lista,
    }


PROVEDORES = {"faturamento_diario": faturamento_diario,
              "smartec_prazo_indicacao": smartec_prazo_indicacao,
              "comunicacao_3s": comunicacao_3s}


def obter(nome: str) -> dict:
    """Valores do provedor pedido. Nome desconhecido devolve vazio, e não
    exceção: a tela pergunta por um provedor que pode não existir para aquele
    contexto, e isso é resposta normal, não erro."""
    fn = PROVEDORES.get(str(nome or ""))
    return fn() if fn else {}
