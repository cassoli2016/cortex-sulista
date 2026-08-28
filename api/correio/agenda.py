"""Agendamento dos relatórios por e-mail — o QUE mandar e para QUEM.

O QUANDO mora em `api/agendamento.py`, de onde os nomes abaixo são importados.
Ele saiu daqui quando o WhatsApp ganhou agenda própria: a lógica de tempo é a
parte delicada de um agendador (idempotência, janela de atraso, padrão
desligado), e duplicá-la para o segundo canal seria duplicar a chance de errar
justamente onde já se errou uma vez, na automação de emissão de CT-e.

Os nomes continuam visíveis por aqui (`deve_rodar`, `proxima`, `descrever`,
`FREQUENCIAS`…) porque o script da rotina, as rotas e os testes já os chamam
assim — extrair não podia virar renomeação em cascata.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .. import migracoes, pglocal
from ..agendamento import (DIAS, FREQUENCIAS, JANELA_ATRASO_MIN,  # noqa: F401
                           descrever, deve_rodar, proxima)
from ..agendamento import hhmm as _hhmm
from ..agendamento import marcado_para as _marcado_para  # noqa: F401

log = logging.getLogger("cortex.correio.agenda")

ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


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
