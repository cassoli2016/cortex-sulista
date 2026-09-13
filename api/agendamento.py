"""Quando uma rotina agendada deve rodar — a parte que não depende do canal.

Nasceu dentro de `api/correio/agenda.py` e saiu de lá quando o WhatsApp passou
a ter agenda própria. **Não foi reescrita: foi movida.** A lógica de tempo é a
parte delicada de um agendador, e as três guardas abaixo foram aprendidas
doendo na automação de emissão de CT-e — duplicá-las para o segundo canal seria
duplicar a chance de errar exatamente onde já se errou uma vez.

O AGENDADOR DO SISTEMA NÃO DECIDE NADA. Ele dispara de tempos em tempos e
pergunta ao CÓRTEX se já passou a hora de cada agendamento. Assim mudar horário
na tela vale na hora, sem reinstalar tarefa, e a configuração fica num lugar só.

AS TRÊS GUARDAS:

1. **PADRÃO DESLIGADO.** Ausência de decisão nunca significa "manda mensagem
   para fora da empresa".
2. **A PASSAGEM É MARCADA MESMO SEM ENVIAR.** Sem isso a rotina se acha sempre
   na primeira execução e reenvia a cada disparo do agendador — foi exatamente
   o defeito da automação de emissão, e lá ele ficou invisível por horas. Quem
   marca é o chamador (`registrar_execucao` de cada canal); aqui a guarda
   aparece como a comparação com `ultima_execucao`.
3. **JANELA DE ATRASO.** Se a máquina estava desligada às 7h e a rotina só roda
   às 11h, a mensagem sai — uma vez — porque atrasada ainda serve. Passada a
   janela, não sai: resumo de ontem chegando hoje à tarde é ruído que ensina a
   ignorar o remetente.

Tudo aqui é FUNÇÃO sobre um dicionário e não sabe de canal, e por isso serve ao
e-mail e ao WhatsApp sem adaptação. A única leitura de fora é o calendário de
feriados (`api/calendario.py`), e só para quem marcou "só dias úteis": com
cache, e com a lista federal como piso quando o banco não responde.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("cortex.agendamento")

FREQUENCIAS = ("diario", "semanal", "mensal")

# Atraso tolerado entre a hora marcada e o disparo do agendador. Quatro horas
# cobrem máquina que dormiu, deploy demorado e reinício — e ainda entrega
# dentro do mesmo turno de trabalho.
JANELA_ATRASO_MIN = 240

DIAS = {1: "segunda", 2: "terça", 3: "quarta", 4: "quinta", 5: "sexta",
        6: "sábado", 7: "domingo"}


def hhmm(txt: str) -> tuple[int, int]:
    """'07:30' -> (7, 30). Recusa em vez de assumir: hora ilegível gravada na
    agenda faria a mensagem sair na hora errada todo dia, calada."""
    partes = str(txt or "").strip().split(":")
    if len(partes) != 2:
        raise ValueError("Horário deve estar no formato HH:MM.")
    try:
        h, m = int(partes[0]), int(partes[1])
    except ValueError:
        raise ValueError("Horário deve estar no formato HH:MM.") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Horário fora do intervalo (00:00 a 23:59).")
    return h, m


def marcado_para(ag: dict, quando: datetime) -> datetime | None:
    """O horário marcado NO DIA de `quando`, ou None se não é dia dele."""
    try:
        h, m = hhmm(ag.get("hora"))
    except ValueError:
        log.warning("agendamento %s com hora ilegivel: %r",
                    ag.get("id"), ag.get("hora"))
        return None
    freq = str(ag.get("frequencia") or "diario")
    if freq == "semanal" and quando.isoweekday() != (ag.get("dia_semana") or 0):
        return None
    if freq == "mensal" and quando.day != (ag.get("dia_mes") or 0):
        return None
    # `dias_uteis` é opcional: um resumo de faturamento no domingo sai com "sem
    # meta no dia" e vira ruído que ensina a ignorar o remetente. Desde
    # 12/09/2026 o FERIADO do calendário da casa também não é dia útil. Quem não
    # passa a chave não muda de comportamento.
    if ag.get("dias_uteis"):
        from api import calendario
        if not calendario.dia_util(quando.date()):
            return None
    return quando.replace(hour=h, minute=m, second=0, microsecond=0)


def deve_rodar(ag: dict, agora: datetime | None = None) -> tuple[bool, str]:
    """Está na hora deste agendamento? Devolve também o PORQUÊ.

    O porquê não é enfeite: é o que a tela mostra quando alguém pergunta "por
    que não saiu?", e o que o log da rotina imprime a cada disparo.
    """
    agora = agora or datetime.now()
    if not ag.get("ativo"):
        return False, "agendamento desligado"
    marcado = marcado_para(ag, agora)
    if marcado is None:
        if ag.get("dias_uteis") and agora.isoweekday() > 5:
            return False, "fim de semana (marcado só para dias úteis)"
        if ag.get("dias_uteis"):
            from api import calendario
            nome = calendario.feriado(agora.date())
            if nome:
                return False, f"feriado: {nome} (marcado só para dias úteis)"
        return False, "não é o dia deste agendamento"
    if agora < marcado:
        falta = (marcado - agora).total_seconds() / 60
        return False, f"faltam {falta:.0f} min para as {ag.get('hora')}"
    atraso = (agora - marcado).total_seconds() / 60
    if atraso > JANELA_ATRASO_MIN:
        return False, (f"passou {atraso/60:.0f}h da hora marcada — fora da "
                       f"janela de {JANELA_ATRASO_MIN//60}h")
    ult = ag.get("ultima_execucao")
    if ult:
        try:
            quando = datetime.fromisoformat(str(ult).replace(" ", "T"))
        except ValueError:
            return True, "última execução com data ilegível"
        if quando >= marcado:
            return False, "já enviado nesta janela"
    return True, f"na hora ({ag.get('hora')}, atraso de {atraso:.0f} min)"


def proxima(ag: dict, agora: datetime | None = None) -> str | None:
    """Quando sai a próxima — para a tela dizer, em vez de deixar adivinhar."""
    agora = agora or datetime.now()
    if not ag.get("ativo"):
        return None
    for d in range(0, 400):
        alvo = agora + timedelta(days=d)
        marcado = marcado_para(ag, alvo)
        if marcado and marcado > agora:
            return marcado.strftime("%Y-%m-%d %H:%M")
    return None


def descrever(ag: dict) -> str:
    """Frase que a tela mostra no lugar de três campos soltos."""
    freq = str(ag.get("frequencia") or "diario")
    hora = ag.get("hora") or "?"
    if freq == "semanal":
        return f"toda {DIAS.get(ag.get('dia_semana'), '?')} às {hora}"
    if freq == "mensal":
        return f"todo dia {ag.get('dia_mes')} do mês às {hora}"
    if ag.get("dias_uteis"):
        return f"todo dia útil às {hora}"
    return f"todo dia às {hora}"


# ─────────────────────────── A CADA N HORAS, NUMA FAIXA ────────────────────
#
# A agenda de relatórios recusou "a cada N horas" de propósito (ver o
# comentário de `correio_agenda.frequencia`, migration 0009): relatório que
# chega várias vezes por dia deixa de ser lido. O MONITORAMENTO DE CLIENTE é o
# caso contrário, e é por isso que ele ganhou esta grade em vez de uma
# frequência nova na agenda de relatórios: ele não é um resumo, é a posição da
# operação, e quem o recebe hoje recebe a planilha da torre de duas em duas
# horas — é o costume que ele substitui, não um que ele inventa.
#
# A GRADE É FIXA NO RELÓGIO (06:00, 08:00, 10:00…), não "duas horas depois do
# último envio". Contada do último envio, uma máquina que acordou às 09:10
# empurraria todos os envios do dia para 09:10, 11:10… e quem recebe deixaria
# de saber a que horas procurar a mensagem. Com a grade fixa o atraso de UM
# envio não contamina os seguintes.
#
# E NÃO HÁ JANELA DE ATRASO DE 4 H AQUI: a rodada seguinte já substitui a
# atrasada. Se a máquina ficou desligada às 08:00 e voltou às 09:30, a rodada
# das 08:00 ainda sai (a das 10:00 não chegou); se voltou às 10:05, sai só a
# das 10:00 — duas posições da mesma operação em cinco minutos seria ruído.

#: Os intervalos aceitos, em minutos. Lista curta de propósito: quinze minutos
#: viraria spam, e oito horas já não é monitoramento.
INTERVALOS_MIN = (60, 120, 180, 240, 360)


def rodada(ag: dict, quando: datetime) -> datetime | None:
    """A rodada da grade que vale em `quando`, ou None fora do dia/da faixa.

    É o último horário da grade que já chegou — desde que a PRÓXIMA ainda não
    tenha chegado. Depois do fim da faixa, a última rodada do dia continua
    valendo por um intervalo inteiro (é a mesma regra do meio do dia), e
    passado isso não há rodada pendente até o dia seguinte.
    """
    try:
        h0, m0 = hhmm(ag.get("hora_inicio"))
        h1, m1 = hhmm(ag.get("hora_fim"))
        passo = int(ag.get("intervalo_min") or 0)
    except (TypeError, ValueError):
        log.warning("monitoramento %s com grade ilegivel", ag.get("id"))
        return None
    if passo <= 0:
        return None
    if str(quando.isoweekday()) not in str(ag.get("dias_semana") or ""):
        return None
    ini = quando.replace(hour=h0, minute=m0, second=0, microsecond=0)
    fim = quando.replace(hour=h1, minute=m1, second=0, microsecond=0)
    if quando < ini or fim < ini:
        return None
    k = int((min(quando, fim) - ini).total_seconds() // (passo * 60))
    marcada = ini + timedelta(minutes=k * passo)
    if quando - marcada >= timedelta(minutes=passo):
        return None                       # passou do fim da faixa
    return marcada


def deve_rodar_intervalo(ag: dict, agora: datetime | None = None) -> tuple[bool, str]:
    """Está na hora deste monitoramento? Devolve também o PORQUÊ, como
    `deve_rodar` — é o que a tela e o log da rotina mostram."""
    agora = agora or datetime.now()
    if not ag.get("ativo"):
        return False, "monitoramento desligado"
    if str(agora.isoweekday()) not in str(ag.get("dias_semana") or ""):
        return False, f"{DIAS[agora.isoweekday()]} não está entre os dias marcados"
    marcada = rodada(ag, agora)
    if marcada is None:
        return False, (f"fora da faixa ({ag.get('hora_inicio')} às "
                       f"{ag.get('hora_fim')})")
    ult = ag.get("ultima_execucao")
    if ult:
        try:
            quando = datetime.fromisoformat(str(ult).replace(" ", "T"))
        except ValueError:
            return True, "última execução com data ilegível"
        if quando >= marcada:
            return False, f"rodada das {marcada:%H:%M} já passou"
    atraso = (agora - marcada).total_seconds() / 60
    return True, f"rodada das {marcada:%H:%M} (atraso de {atraso:.0f} min)"


def proxima_intervalo(ag: dict, agora: datetime | None = None) -> str | None:
    """A próxima rodada da grade depois de `agora` — para a tela dizer."""
    agora = agora or datetime.now()
    if not ag.get("ativo"):
        return None
    try:
        h0, m0 = hhmm(ag.get("hora_inicio"))
        h1, m1 = hhmm(ag.get("hora_fim"))
        passo = int(ag.get("intervalo_min") or 0)
    except (TypeError, ValueError):
        return None
    if passo <= 0:
        return None
    for d in range(0, 8):
        dia = agora + timedelta(days=d)
        if str(dia.isoweekday()) not in str(ag.get("dias_semana") or ""):
            continue
        t = dia.replace(hour=h0, minute=m0, second=0, microsecond=0)
        fim = dia.replace(hour=h1, minute=m1, second=0, microsecond=0)
        while t <= fim:
            if t > agora:
                return t.strftime("%Y-%m-%d %H:%M")
            t += timedelta(minutes=passo)
    return None


def _dias_frase(dias: str) -> str:
    d = "".join(sorted(set(str(dias or "")) & set("1234567")))
    if d == "1234567":
        return "todos os dias"
    if d == "12345":
        return "de segunda a sexta"
    if d == "123456":
        return "de segunda a sábado"
    return ", ".join(DIAS[int(c)] for c in d) or "nenhum dia"


def descrever_intervalo(ag: dict) -> str:
    """"a cada 2 h, das 06:00 às 22:00, de segunda a sábado"."""
    passo = int(ag.get("intervalo_min") or 0)
    ritmo = (f"a cada {passo // 60} h" if passo and passo % 60 == 0
             else f"a cada {passo} min")
    return (f"{ritmo}, das {ag.get('hora_inicio')} às {ag.get('hora_fim')}, "
            f"{_dias_frase(ag.get('dias_semana'))}")
