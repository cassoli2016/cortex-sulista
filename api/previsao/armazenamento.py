"""Persistência local da previsão de fechamento — PostgreSQL (schema `cortex`).

Quarto store migrado do SQLite (27/08/2026 — ver `docs/MIGRACAO_POSTGRES.md`).
O `data/previsao.db` continua no disco até a fase seguinte fechar.

O AVA é réplica somente-leitura; ajuste manual e snapshot diário são dado
nosso.

Regra central (herdada do orçamento): recalcular a previsão NUNCA apaga o
ajuste manual — o efetivo é previsto_calculado + delta (ou o valor absoluto),
resolvido no motor (motor.aplicar_ajustes), não aqui.

O primeiro parâmetro era `path` (o arquivo `.db`) e virou `esquema`, na mesma
posição: as chamadas passavam `arm.DB_PATH` e passam `arm.ESQUEMA`. Manter a
POSIÇÃO importa — trocar a aridade faria uma chamada posicional antiga mandar
o mês para o lugar do schema, sem erro nenhum.
"""
from __future__ import annotations

from .. import migracoes, pglocal

# `None` = o schema de produção (`cortex`). O teste passa o seu próprio, como
# antes passava um arquivo em tmp_path.
ESQUEMA: str | None = None

TIPOS_AJUSTE = ("delta", "valor")


def init_db(esquema: str | None = ESQUEMA) -> None:
    migracoes.aplicar(esquema)


def ler_ajustes_prev(esquema: str | None, mes: str) -> dict[str, dict]:
    rows = pglocal.query(
        "SELECT linha, tipo, valor, motivo, autor, criado_em"
        " FROM prev_ajuste WHERE mes=%s", (mes,), esquema=esquema)
    return {r["linha"]: {k: r[k] for k in
                         ("tipo", "valor", "motivo", "autor", "criado_em")}
            for r in rows}


def salvar_ajuste_prev(esquema: str | None, mes: str, linha: str, tipo: str,
                       valor: float, motivo: str, autor: str) -> None:
    if tipo not in TIPOS_AJUSTE:
        raise ValueError(f"tipo deve ser um de {TIPOS_AJUSTE}")
    if not (motivo or "").strip():
        raise ValueError("motivo é obrigatório")
    # ajuste e trilha na MESMA transação: ajuste gravado sem registro de quem
    # o fez é exatamente o que a auditoria vem procurar
    with pglocal.get_conn(esquema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO prev_ajuste(mes, linha, tipo, valor, motivo, autor)"
                " VALUES(%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (mes, linha) DO UPDATE SET"
                "   tipo=excluded.tipo, valor=excluded.valor,"
                "   motivo=excluded.motivo, autor=excluded.autor",
                (mes, linha, tipo, float(valor), motivo.strip(), autor))
            cur.execute(
                "INSERT INTO prev_log(autor, acao, detalhe) VALUES(%s,%s,%s)",
                (autor, "ajuste",
                 f"{mes} {linha} {tipo}={valor} ({motivo.strip()})"))


def remover_ajuste_prev(esquema: str | None, mes: str, linha: str,
                        autor: str | None = None) -> bool:
    """autor e' OPCIONAL na assinatura (mantem call sites antigos validos), mas
    a camada API sempre passa quem removeu: em controladoria "quem apagou o
    ajuste manual" e' exatamente a pergunta da auditoria."""
    with pglocal.get_conn(esquema) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM prev_ajuste WHERE mes=%s AND linha=%s",
                        (mes, linha))
            houve = bool(cur.rowcount)
            if houve:
                cur.execute(
                    "INSERT INTO prev_log(autor, acao, detalhe) VALUES(%s,%s,%s)",
                    (autor, "ajuste_removido", f"{mes} {linha}"))
    return houve


def gravar_snapshot(esquema: str | None, data_foto: str, mes: str,
                    linhas: list[dict]) -> None:
    if not linhas:
        return
    with pglocal.get_conn(esquema) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO prev_snapshot"
                "(data, mes, linha, previsto_base, previsto_otim, previsto_pess,"
                " realizado_contabil, estrategia) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (data, mes, linha) DO UPDATE SET"
                "   previsto_base=excluded.previsto_base,"
                "   previsto_otim=excluded.previsto_otim,"
                "   previsto_pess=excluded.previsto_pess,"
                "   realizado_contabil=excluded.realizado_contabil,"
                "   estrategia=excluded.estrategia",
                [(data_foto, mes, ln["linha"], ln["previsto_base"],
                  ln.get("previsto_otim"), ln.get("previsto_pess"),
                  ln.get("realizado_contabil"), ln.get("estrategia"))
                 for ln in linhas])


def ler_snapshots(esquema: str | None, mes: str) -> list[dict]:
    return pglocal.query(
        "SELECT data, mes, linha, previsto_base, previsto_otim, previsto_pess,"
        "       realizado_contabil, estrategia"
        " FROM prev_snapshot WHERE mes=%s ORDER BY data, linha",
        (mes,), esquema=esquema)


def registrar_log(esquema: str | None, autor: str | None, acao: str,
                  detalhe: str) -> None:
    pglocal.executar(
        "INSERT INTO prev_log(autor, acao, detalhe) VALUES(%s,%s,%s)",
        (autor, acao, detalhe), esquema=esquema)
