"""Agendamento dos relatórios por e-mail.

O AGENDADOR DO SISTEMA NÃO DECIDE NADA. Ele dispara de tempos em tempos e
pergunta ao CÓRTEX se já passou a hora de cada agendamento — mesmo desenho da
emissão de contrapartida, e pela mesma razão: mudar horário ou destinatário na
tela vale na hora, sem reinstalar tarefa, e a configuração continua num lugar
só.

TRÊS GUARDAS, todas aprendidas doendo no módulo de emissão:

1. **PADRÃO DESLIGADO.** Ausência de decisão nunca significa "manda e-mail
   para fora da empresa".
2. **A PASSAGEM É MARCADA MESMO SEM ENVIAR.** Sem isso a rotina se acha
   sempre na primeira execução e reenvia a cada disparo do agendador — foi
   exatamente o defeito da automação de emissão, e lá ele ficou invisível por
   horas.
3. **JANELA DE ATRASO.** Se a máquina estava desligada às 7h e a rotina só
   roda às 11h, o relatório das 7h sai — uma vez — porque atrasado ainda serve.
   Passada a janela, não sai: relatório de ontem chegando hoje à tarde é ruído
   que ensina a ignorar o remetente.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .. import migracoes, pglocal

log = logging.getLogger("cortex.correio.agenda")

FREQUENCIAS = ("diario", "semanal", "mensal")

# Atraso tolerado entre a hora marcada e o disparo do agendador. Quatro horas
# cobrem máquina que dormiu, deploy demorado e reinício — e ainda entrega o
# relatório dentro do mesmo turno de trabalho.
JANELA_ATRASO_MIN = 240

DIAS = {1: "segunda", 2: "terça", 3: "quarta", 4: "quinta", 5: "sexta",
        6: "sábado", 7: "domingo"}

ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def _hhmm(txt: str) -> tuple[int, int]:
    """'07:30' -> (7, 30). Recusa em vez de assumir: hora ilegível gravada na
    agenda faria o relatório sair na hora errada todo dia, calado."""
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


def validar(dados: dict) -> dict:
    """Normaliza e recusa o que não dá para agendar.

    Recusar na gravação e não no envio: erro que só aparece na rotina
    desassistida é erro que ninguém vê.
    """
    from api.correio import config as cfg
    from api.correio.relatorios import CATALOGO

    rel = str(dados.get("relatorio") or "").strip()
    if rel not in CATALOGO:
        raise ValueError(f"Relatório desconhecido: {rel!r}.")

    dest = cfg.separar_destinatarios(dados.get("destinatarios") or "")
    ruins = [e for e in dest if not cfg.email_valido(e)]
    if not dest:
        raise ValueError("Informe ao menos um destinatário.")
    if ruins:
        raise ValueError("Endereço inválido: " + ", ".join(ruins[:3]))

    freq = str(dados.get("frequencia") or "diario").strip().lower()
    if freq not in FREQUENCIAS:
        raise ValueError(f"Frequência deve ser uma de: {', '.join(FREQUENCIAS)}.")

    h, m = _hhmm(dados.get("hora") or "07:00")

    dia_semana = dados.get("dia_semana")
    dia_mes = dados.get("dia_mes")
    if freq == "semanal":
        try:
            dia_semana = int(dia_semana)
        except (TypeError, ValueError):
            raise ValueError("Escolha o dia da semana.") from None
        if not (1 <= dia_semana <= 7):
            raise ValueError("Dia da semana deve ser de 1 (segunda) a 7.")
        dia_mes = None
    elif freq == "mensal":
        try:
            dia_mes = int(dia_mes)
        except (TypeError, ValueError):
            raise ValueError("Escolha o dia do mês.") from None
        # 28 e o teto porque 29, 30 e 31 nao existem em todo mes: um mensal
        # marcado no dia 31 nao sairia em fevereiro nenhum, e o usuario nunca
        # saberia por que.
        if not (1 <= dia_mes <= 28):
            raise ValueError("Dia do mês deve ser de 1 a 28 — 29, 30 e 31 não "
                             "existem em todos os meses.")
        dia_semana = None
    else:
        dia_semana = dia_mes = None

    return {"relatorio": rel, "destinatarios": ", ".join(dest),
            "frequencia": freq, "hora": f"{h:02d}:{m:02d}",
            "dia_semana": dia_semana, "dia_mes": dia_mes,
            "ativo": bool(dados.get("ativo"))}


def listar(esquema: str | None = None) -> list[dict]:
    init_db(esquema)
    return pglocal.query(
        "SELECT id, relatorio, destinatarios, frequencia, hora, dia_semana,"
        " dia_mes, ativo, ultima_execucao, ultimo_resultado, criado_por,"
        " criado_em, alterado_por, alterado_em"
        " FROM correio_agenda ORDER BY id", (), esquema=_esq(esquema))


def gravar(dados: dict, quem: str, esquema: str | None = None) -> dict:
    if not quem:
        raise ValueError("Informe quem está criando o agendamento.")
    v = validar(dados)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    init_db(esquema)
    ident = dados.get("id")
    if ident:
        r = pglocal.um(
            "UPDATE correio_agenda SET relatorio=%s, destinatarios=%s,"
            " frequencia=%s, hora=%s, dia_semana=%s, dia_mes=%s, ativo=%s,"
            " alterado_por=%s, alterado_em=%s WHERE id=%s RETURNING id",
            (v["relatorio"], v["destinatarios"], v["frequencia"], v["hora"],
             v["dia_semana"], v["dia_mes"], v["ativo"], quem, agora,
             int(ident)), esquema=_esq(esquema))
        if not r:
            raise ValueError(f"Agendamento {ident} não existe.")
        novo_id = int(r["id"])
    else:
        r = pglocal.um(
            "INSERT INTO correio_agenda(relatorio, destinatarios,"
            " frequencia, hora, dia_semana, dia_mes, ativo, criado_por)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (v["relatorio"], v["destinatarios"], v["frequencia"], v["hora"],
             v["dia_semana"], v["dia_mes"], v["ativo"], quem),
            esquema=_esq(esquema))
        novo_id = int(r["id"])
    return {**v, "id": novo_id}


def remover(ident: int, esquema: str | None = None) -> None:
    init_db(esquema)
    pglocal.executar("DELETE FROM correio_agenda WHERE id=%s",
                     (int(ident),), esquema=_esq(esquema))


def registrar_execucao(ident: int, resultado: str,
                       esquema: str | None = None) -> None:
    """Marca a passagem da rotina — inclusive quando não houve envio."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pglocal.executar("UPDATE correio_agenda SET ultima_execucao=%s,"
                     " ultimo_resultado=%s WHERE id=%s",
                     (agora, str(resultado)[:200], int(ident)),
                     esquema=_esq(esquema))


def _marcado_para(ag: dict, quando: datetime) -> datetime | None:
    """O horário marcado NO DIA de `quando`, ou None se não é dia dele."""
    try:
        h, m = _hhmm(ag.get("hora"))
    except ValueError:
        log.warning("agendamento %s com hora ilegivel: %r",
                    ag.get("id"), ag.get("hora"))
        return None
    freq = str(ag.get("frequencia") or "diario")
    if freq == "semanal" and quando.isoweekday() != (ag.get("dia_semana") or 0):
        return None
    if freq == "mensal" and quando.day != (ag.get("dia_mes") or 0):
        return None
    return quando.replace(hour=h, minute=m, second=0, microsecond=0)


def deve_rodar(ag: dict, agora: datetime | None = None) -> tuple[bool, str]:
    """Está na hora deste agendamento? Devolve também o PORQUÊ."""
    agora = agora or datetime.now()
    if not ag.get("ativo"):
        return False, "agendamento desligado"
    marcado = _marcado_para(ag, agora)
    if marcado is None:
        return False, "não é o dia deste agendamento"
    if agora < marcado:
        falta = (marcado - agora).total_seconds() / 60
        return False, f"faltam {falta:.0f} min para as {ag.get('hora')}"
    atraso = (agora - marcado).total_seconds() / 60
    if atraso > JANELA_ATRASO_MIN:
        # Relatorio de manha chegando a noite ensina a ignorar o remetente.
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
    """Quando sai o próximo — para a tela dizer, em vez de deixar adivinhar."""
    agora = agora or datetime.now()
    if not ag.get("ativo"):
        return None
    for d in range(0, 400):
        alvo = agora + timedelta(days=d)
        marcado = _marcado_para(ag, alvo)
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
    return f"todo dia às {hora}"


def estado(esquema: str | None = None) -> dict:
    """Tudo que a tela precisa, com o catálogo junto."""
    from api.correio import config as cfg
    from api.correio.relatorios import CATALOGO

    itens = []
    for ag in listar(esquema):
        pode, porque = deve_rodar(ag)
        itens.append({**ag,
                      "quando": descrever(ag),
                      "proxima": proxima(ag),
                      "pronto": pode, "motivo": porque,
                      "relatorio_nome": (CATALOGO.get(ag["relatorio"], {})
                                         .get("nome") or ag["relatorio"])})
    return {
        "agendamentos": itens,
        "relatorios": [{"id": k, "nome": v["nome"],
                        "descricao": v["descricao"]}
                       for k, v in sorted(CATALOGO.items())],
        "smtp_configurado": cfg.configurado(),
        "janela_atraso_min": JANELA_ATRASO_MIN,
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
