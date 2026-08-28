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

Tudo aqui é FUNÇÃO PURA sobre um dicionário: não toca banco, não sabe de canal,
e por isso serve ao e-mail e ao WhatsApp sem adaptação.
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
    # `dias_uteis` é opcional e só o WhatsApp usa hoje: um resumo de faturamento
    # no domingo sai com "sem meta no dia" e vira ruído que ensina a ignorar o
    # remetente. Quem não passa a chave não muda de comportamento.
    if ag.get("dias_uteis") and quando.isoweekday() > 5:
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
