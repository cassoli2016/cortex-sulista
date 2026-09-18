# -*- coding: utf-8 -*-
"""O banco da campanha: a régua do regulamento, as fotos e os sorteios."""
from __future__ import annotations

import logging
from datetime import datetime

from api import pglocal

log = logging.getLogger("cortex.campanha.armazenamento")

ESQUEMA: str | None = None

#: Os padrões do regulamento de 3.º trimestre/2026, que é o documento em vigor
#: quando isto nasceu. Eles são só o FORMULÁRIO da tela — o que vale é o que
#: está gravado na campanha, porque campanha nova pode ter outra régua.
PADRAO = {"peso_gobrax": 50, "peso_conduta": 30, "peso_gr": 20,
          "cat_elite": 90, "cat_ouro": 85, "cat_prata": 75}


def _esq():
    from . import ESQUEMA as padrao
    return ESQUEMA or padrao


def _linha(r) -> dict:
    d = dict(r)
    for k in ("peso_gobrax", "peso_conduta", "peso_gr",
              "cat_elite", "cat_ouro", "cat_prata"):
        d[k] = float(d[k])
    return d


def listar(esquema: str | None = None) -> list[dict]:
    try:
        return [_linha(r) for r in pglocal.query(
            "SELECT * FROM cmp_campanha ORDER BY ate_ciclo DESC, id DESC",
            esquema=esquema or _esq())]
    except Exception as exc:  # noqa: BLE001
        log.warning("campanha: listagem indisponivel (%s)", type(exc).__name__)
        return []


def ler(campanha_id: int, esquema: str | None = None) -> dict | None:
    r = pglocal.um("SELECT * FROM cmp_campanha WHERE id = %s",
                   (int(campanha_id),), esquema=esquema or _esq())
    return _linha(r) if r else None


def vigente(esquema: str | None = None) -> dict | None:
    """A campanha aberta mais recente — a que a tela abre por padrão."""
    r = pglocal.um("SELECT * FROM cmp_campanha WHERE situacao = 'aberta'"
                   " ORDER BY ate_ciclo DESC, id DESC LIMIT 1",
                   esquema=esquema or _esq())
    return _linha(r) if r else None


def criar(dados: dict, autor: str, esquema: str | None = None) -> dict:
    """Cria a campanha. Os pesos TÊM de somar 100 — é média ponderada, e uma
    régua que soma 90 dá uma nota que não é comparável com nada."""
    if not autor:
        raise ValueError("Informe quem está criando (trilha de auditoria).")
    campos = {}
    for k in ("nome", "de_ciclo", "ate_ciclo", "premio", "onde"):
        campos[k] = str(dados.get(k) or "").strip()
    if not campos["nome"]:
        raise ValueError("A campanha precisa de um nome.")
    for k in ("de_ciclo", "ate_ciclo"):
        from api.premiacao import ciclo as ciclo_mod
        if not ciclo_mod.valido(campos[k]):
            raise ValueError(f"Ciclo inválido em {k}: {campos[k]!r}. Use 'AAAA-MM'.")
    if campos["de_ciclo"] > campos["ate_ciclo"]:
        raise ValueError("O ciclo inicial é depois do final.")
    for k, v in PADRAO.items():
        try:
            campos[k] = float(dados.get(k, v))
        except (TypeError, ValueError):
            raise ValueError(f"Valor inválido em {k}: {dados.get(k)!r}")
    soma = campos["peso_gobrax"] + campos["peso_conduta"] + campos["peso_gr"]
    if abs(soma - 100) > 0.01:
        raise ValueError(f"Os pesos somam {soma:.0f}% — têm de somar 100%.")
    if not (campos["cat_elite"] > campos["cat_ouro"] > campos["cat_prata"]):
        raise ValueError("As faixas têm de ser decrescentes: Elite > Ouro > Prata.")
    campos["sorteio_em"] = str(dados.get("sorteio_em") or "") or None
    campos["exige_gobrax"] = bool(dados.get("exige_gobrax", True))
    campos["criado_em"] = datetime.now().isoformat(timespec="seconds")
    campos["criado_por"] = autor
    r = pglocal.um(
        "INSERT INTO cmp_campanha(nome, de_ciclo, ate_ciclo, sorteio_em, premio,"
        " onde, peso_gobrax, peso_conduta, peso_gr, cat_elite, cat_ouro,"
        " cat_prata, exige_gobrax, criado_em, criado_por)"
        " VALUES(%(nome)s,%(de_ciclo)s,%(ate_ciclo)s,%(sorteio_em)s,%(premio)s,"
        "%(onde)s,%(peso_gobrax)s,%(peso_conduta)s,%(peso_gr)s,%(cat_elite)s,"
        "%(cat_ouro)s,%(cat_prata)s,%(exige_gobrax)s,%(criado_em)s,"
        "%(criado_por)s) RETURNING id",
        campos, esquema=esquema or _esq())
    return ler(int(r["id"]), esquema=esquema or _esq())


def gravar_foto(campanha_id: int, ciclo: str, grupos: dict,
                esquema: str | None = None) -> int:
    """Regrava a foto do ciclo — idempotente por (campanha, ciclo, grupo, chave).

    Fotografar de novo é o caminho normal: o mês só fecha de verdade depois que
    a coleta da Gobrax daquele mês entrou, e entre uma coisa e outra alguém vai
    querer conferir. O que não pode é a foto do ciclo de ENCERRAMENTO mudar
    depois do sorteio — e essa trava é do sorteio, que lê a foto que existia.
    """
    esq = esquema or _esq()
    pglocal.executar("DELETE FROM cmp_foto WHERE campanha_id = %s AND ciclo = %s",
                     (campanha_id, ciclo), esquema=esq)
    n = 0
    for grupo, d in grupos.items():
        for x in d["linhas"]:
            pglocal.executar(
                "INSERT INTO cmp_foto(campanha_id, ciclo, grupo, chave, nome,"
                " gobrax, conduta, gr, nota, categoria, elegivel, motivo)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (campanha_id, ciclo, grupo, x["chave"], x["nome"], x["gobrax"],
                 x["conduta"], x["gr"], x["nota"], x["categoria"],
                 bool(x["elegivel"]), x["motivo"]), esquema=esq)
            n += 1
    return n


def ler_foto(campanha_id: int, ciclo: str, grupo: str | None = None,
             esquema: str | None = None) -> list[dict]:
    sql = ("SELECT chave, nome, grupo, gobrax, conduta, gr, nota, categoria,"
           " elegivel, motivo FROM cmp_foto WHERE campanha_id = %(c)s"
           " AND ciclo = %(ci)s")
    p = {"c": campanha_id, "ci": ciclo}
    if grupo:
        sql += " AND grupo = %(g)s"
        p["g"] = grupo
    sql += " ORDER BY nota DESC NULLS LAST, nome"
    try:
        linhas = pglocal.query(sql, p, esquema=esquema or _esq())
    except Exception as exc:  # noqa: BLE001
        log.warning("campanha: foto indisponivel (%s)", type(exc).__name__)
        return []
    saida = []
    for r in linhas:
        d = dict(r)
        for k in ("gobrax", "conduta", "gr", "nota"):
            d[k] = float(d[k]) if d[k] is not None else None
        saida.append(d)
    return saida


def sorteios(campanha_id: int, esquema: str | None = None) -> list[dict]:
    try:
        return [dict(r) for r in pglocal.query(
            "SELECT grupo, ciclo, elegiveis, semente, ganhador_nome,"
            " suplente_nome, ata, realizado_em, realizado_por"
            " FROM cmp_sorteio WHERE campanha_id = %s ORDER BY id",
            (campanha_id,), esquema=esquema or _esq())]
    except Exception as exc:  # noqa: BLE001
        log.warning("campanha: sorteios indisponiveis (%s)", type(exc).__name__)
        return []
