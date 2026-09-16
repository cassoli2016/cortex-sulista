"""Acidente com vítima fatal — o registro que o ERP não tem.

Ver `sql/cortex/0099_sst_acidente_fatal.sql`: a tabela da Qualidade no ERP
classifica acidente em leve, médio e grave e não registra morte, e quem opera
definiu "com vítima" como "com morte". O painel de TV do RH conta daqui.

Só acréscimo. Registro errado sai por RETIRADA com motivo (o banco recusa
editar e apagar). O número da parede conta só o que não foi retirado.
"""
from __future__ import annotations

from datetime import date

from api import pglocal

ESQUEMA: str | None = None

FILIAIS = ("Matriz", "SBC", "Cruzeiro", "Joinville", "Pouso Alegre", "Outra")
DESCRICAO_MAX = 1000


class Recusa(Exception):
    """Entrada recusada; a mensagem vai para a tela."""


def _texto(v, nome: str, maximo: int) -> str:
    t = str(v or "").strip()
    if not t:
        raise Recusa(f"Informe {nome}.")
    if len(t) > maximo:
        raise Recusa(f"{nome.capitalize()} passa de {maximo} caracteres.")
    return t


def validar(dados: dict, *, hoje: date) -> dict:
    try:
        d = date.fromisoformat(str(dados.get("data") or ""))
    except ValueError:
        raise Recusa("Data inválida: use AAAA-MM-DD.") from None
    if d > hoje:
        raise Recusa("A data do acidente não pode ser futura.")
    filial = _texto(dados.get("filial"), "a filial", 60)
    if filial not in FILIAIS:
        raise Recusa("Filial fora da lista.")
    return {"data": d, "filial": filial,
            "descricao": _texto(dados.get("descricao"), "a descrição", DESCRICAO_MAX)}


def _publicar(r: dict) -> dict:
    iso = lambda v: v.isoformat() if hasattr(v, "isoformat") else v   # noqa: E731
    return {"id": r["id"], "data": iso(r["data"]), "filial": r["filial"], "descricao": r["descricao"],
            "autor": r["autor"], "em": iso(r["em"]), "retirado_em": iso(r["retirado_em"]),
            "retirado_por": r["retirado_por"], "retirado_motivo": r["retirado_motivo"]}


def registrar(dados: dict, *, autor: str, hoje: date | None = None, esquema: str | None = None) -> dict:
    v = validar(dados, hoje=hoje or date.today())
    autor = _texto(autor, "o autor", 200)
    r = pglocal.um("""INSERT INTO sst_acidente_fatal (data, filial, descricao, autor)
                      VALUES (%s, %s, %s, %s) RETURNING *""",
                   (v["data"], v["filial"], v["descricao"], autor), esquema or ESQUEMA)
    return _publicar(r)


def retirar(id_: int, motivo: str, *, autor: str, esquema: str | None = None) -> dict:
    motivo = _texto(motivo, "o motivo da retirada", 500)
    autor = _texto(autor, "o autor", 200)
    r = pglocal.um("""UPDATE sst_acidente_fatal
                         SET retirado_em = now(), retirado_por = %s, retirado_motivo = %s
                       WHERE id = %s AND retirado_em IS NULL RETURNING *""",
                   (autor, motivo, int(id_)), esquema or ESQUEMA)
    if not r:
        raise Recusa("Registro não encontrado ou já retirado.")
    return _publicar(r)


def listar(esquema: str | None = None) -> list[dict]:
    return [_publicar(r) for r in pglocal.query(
        "SELECT * FROM sst_acidente_fatal ORDER BY data DESC, id DESC", None, esquema or ESQUEMA)]


def datas_validas(desde: date, esquema: str | None = None) -> list[str]:
    """As datas (AAAA-MM-DD) dos registros não retirados desde `desde` — o que
    a parede conta."""
    return [r["data"].isoformat() for r in pglocal.query(
        "SELECT data FROM sst_acidente_fatal WHERE retirado_em IS NULL AND data >= %s ORDER BY data",
        (desde,), esquema or ESQUEMA)]
