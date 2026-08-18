"""Confere os transportadores contratados contra a situação do RNTRC.

conferir e resumir são puros; só get_rntrc toca no AVA e só atualizar_base
toca na rede.
"""
from __future__ import annotations

from api import db
from api.antt import rntrc as ingestao
from api.antt.armazenamento import normalizar_rntrc, todas, ultima_sync
from api.antt.sql import RNTRC_TRANSPORTADORES_SQL

SITUACOES: tuple[str, ...] = ("ativo", "pendente", "nao_encontrado",
                              "sem_registro", "sem_base")


def conferir(contratados: list[dict], base: dict[str, dict]) -> list[dict]:
    saida = []
    for t in contratados:
        item = dict(t)
        chave = normalizar_rntrc(t.get("rntrc"))
        if not base:
            # Sem base local nada pode ser afirmado. Acusar todo mundo de
            # irregular por falta de sincronização seria pior que não medir.
            item.update(situacao="sem_base", risco=False, categoria=None,
                        uf=None, data_situacao=None)
        elif not chave:
            item.update(situacao="sem_registro", risco=True, categoria=None,
                        uf=None, data_situacao=None)
        else:
            achado = base.get(chave)
            if achado is None:
                item.update(situacao="nao_encontrado", risco=True,
                            categoria=None, uf=None, data_situacao=None)
            else:
                ativo = (achado.get("situacao") or "").upper() == "ATIVO"
                item.update(situacao="ativo" if ativo else "pendente",
                            risco=not ativo,
                            categoria=achado.get("categoria"),
                            uf=achado.get("uf"),
                            data_situacao=achado.get("data_situacao"))
        saida.append(item)
    return saida


def resumir(conferidos: list[dict]) -> dict:
    risco = [c for c in conferidos if c["risco"]]
    pago_total = sum(float(c.get("pago") or 0) for c in conferidos)
    pago_risco = sum(float(c.get("pago") or 0) for c in risco)
    return {
        "transportadores": len(conferidos),
        "ativos": sum(1 for c in conferidos if c["situacao"] == "ativo"),
        "pendentes": sum(1 for c in conferidos if c["situacao"] == "pendente"),
        "nao_encontrados": sum(1 for c in conferidos
                               if c["situacao"] == "nao_encontrado"),
        "sem_registro": sum(1 for c in conferidos
                            if c["situacao"] == "sem_registro"),
        "em_risco": len(risco),
        "viagens_em_risco": sum(int(c.get("viagens") or 0) for c in risco),
        "pago_total": pago_total,
        "pago_em_risco": pago_risco,
        "pct_risco": (pago_risco / pago_total) if pago_total else None,
    }


def _contratados(dt_de: str, dt_ate: str) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(RNTRC_TRANSPORTADORES_SQL, {"dt_de": dt_de, "dt_ate": dt_ate})
        return [dict(r) for r in cur.fetchall()]


def get_rntrc(dt_de: str, dt_ate: str) -> dict:
    conferidos = conferir(_contratados(dt_de, dt_ate), todas())
    # risco primeiro, e dentro dele o maior valor pago — é a ordem da ação
    conferidos.sort(key=lambda c: (not c["risco"], -float(c.get("pago") or 0)))
    return {
        "kpis": resumir(conferidos),
        "transportadores": conferidos,
        "sync": ultima_sync(),
        "dt_de": dt_de, "dt_ate": dt_ate,
        "fonte": ("ERP AVA · cadastro.numerorntrc × base aberta do RNTRC "
                  "(dados.antt.gov.br, CC-BY) · casamento pelo número de registro"),
    }


def atualizar_base(dt_de: str, dt_ate: str) -> dict:
    """Baixa a competência mais recente, guardando só quem a Sulista contrata."""
    alvos = {normalizar_rntrc(t["rntrc"]) for t in _contratados(dt_de, dt_ate)}
    alvos.discard("")
    return ingestao.sincronizar(alvos)
