"""Persistência local do orçamento — PostgreSQL (schema `cortex`).

Sétimo store migrado do SQLite (27/08/2026 — ver `docs/MIGRACAO_POSTGRES.md`),
e o maior: 21.696 linhas. O `data/orcamento.db` continua no disco.

O ERP AVA é réplica somente-leitura, então o orçamento é dado nosso.

Regra central: `valor_efetivo = coalesce(valor_ajustado, valor_baseline)`.
Regerar o baseline recalcula APENAS `valor_baseline` — o ajuste manual sobrevive,
senão recalcular jogaria fora o trabalho da controladoria.
"""
from __future__ import annotations

import json
from datetime import datetime

from .. import migracoes, pglocal

# Manopla de redirecionamento, no lugar do antigo `DB_PATH`.
ESQUEMA: str | None = None

# `ajustado_em`/`quando` são gravados pelo BANCO, não pelo Python: é o mesmo
# relógio para todas as linhas de uma transação, e continua no formato de texto
# que a tela já lê.
_AGORA_SQL = "to_char(now(), 'YYYY-MM-DD HH24:MI:SS')"


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    """O DDL mora em `sql/cortex/0008_orcamento.sql`, com as quatro colunas que
    aqui nasciam de `ALTER TABLE` condicional já no lugar."""
    migracoes.aplicar(_esq(esquema))


def _vazio_se_sem_tabela(fn, padrao):
    """Instalação que nunca gerou orçamento não tem as tabelas — é lista vazia,
    não falha. Erro de CONEXÃO sobe."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return padrao
        raise


def criar_versao(esquema: str | None, ano: int, rotulo: str, fator: float,
                 quem: str, meses_base: list[str] | None = None,
                 metodo: str = "espelho") -> int:
    init_db(esquema)
    r = pglocal.um(
        "INSERT INTO orc_versao(ano, rotulo, fator_tendencia, criado_por,"
        " meses_base, metodo) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (ano, rotulo, fator, quem,
         json.dumps(meses_base) if meses_base else None, metodo),
        esquema=_esq(esquema))
    return int(r["id"])


def atualizar_versao(esquema: str | None, versao_id: int, fator: float,
                     meses_base: list[str] | None = None,
                     metodo: str | None = None) -> None:
    """Regeração troca fator e base da versão; ano e rótulo continuam os mesmos.

    `metodo=None` NÃO altera o método gravado — regerar sempre re-deriva pelo
    método ORIGINAL da versão, não pelo que a requisição de regerar mandar.
    """
    n = pglocal.executar(
        "UPDATE orc_versao SET fator_tendencia=%s, meses_base=%s,"
        " metodo=coalesce(%s, metodo) WHERE id=%s",
        (fator, json.dumps(meses_base) if meses_base else None, metodo, versao_id),
        esquema=_esq(esquema))
    if n == 0:
        raise KeyError(f"versão inexistente: {versao_id}")


def aprovar(esquema: str | None, versao_id: int, quem: str, agora: datetime | None = None) -> None:
    """Aprova a versão — a partir daqui `ajustar` fica bloqueado até reabrir.

    Reaprovar uma versão já aprovada é idempotente: regrava quem/quando (não
    é erro reforçar a aprovação, só é vedado aprovar uma arquivada).
    """
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.execute("SELECT status FROM orc_versao WHERE id=%s", (versao_id,))
            row = c.fetchone()
            if row is None:
                raise KeyError(f"versão inexistente: {versao_id}")
            if row["status"] == "arquivada":
                raise ValueError(
                    "Versão arquivada não pode ser aprovada — gere ou regenere "
                    "uma versão rascunho.")
            quando = (agora or datetime.now()).strftime("%Y-%m-%d %H:%M")
            c.execute(
                "UPDATE orc_versao SET status='aprovado', aprovado_em=%s,"
                " aprovado_por=%s WHERE id=%s", (quando, quem, versao_id))


def reabrir(esquema: str | None, versao_id: int) -> None:
    """Volta a versão para rascunho e limpa quem/quando aprovou.

    Arquivada é registro histórico e não reabre — para corrigir uma versão
    aprovada, reabra ANTES de arquivar (ou arquive uma cópia da rascunho nova).
    """
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.execute("SELECT status FROM orc_versao WHERE id=%s", (versao_id,))
            row = c.fetchone()
            if row is None:
                raise KeyError(f"versão inexistente: {versao_id}")
            if row["status"] == "arquivada":
                raise ValueError(
                    "Versão arquivada é registro histórico — não pode ser reaberta.")
            c.execute(
                "UPDATE orc_versao SET status='rascunho', aprovado_em=NULL,"
                " aprovado_por=NULL WHERE id=%s", (versao_id,))


def arquivar_copia(esquema: str | None, versao_id: int, rotulo_novo: str) -> int:
    """Congela a versão atual numa cópia histórica com status='arquivada'.

    A original não é tocada (segue podendo ser aprovada/reaberta normalmente);
    a cópia nasce arquivada e imutável. Cabeçalho e todas as linhas (baseline
    E ajuste, fielmente) copiam numa única transação — devolve o id novo.
    """
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.execute(
                "SELECT ano, fator_tendencia, metodo, meses_base, criado_por"
                " FROM orc_versao WHERE id=%s", (versao_id,))
            original = c.fetchone()
            if original is None:
                raise KeyError(f"versão inexistente: {versao_id}")
            c.execute(
                "INSERT INTO orc_versao(ano, rotulo, status, fator_tendencia,"
                " metodo, meses_base, criado_por)"
                " VALUES (%s,%s,'arquivada',%s,%s,%s,%s) RETURNING id",
                (original["ano"], rotulo_novo, original["fator_tendencia"],
                 original["metodo"], original["meses_base"], original["criado_por"]))
            novo_id = int(c.fetchone()["id"])
            c.execute(
                "INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline,"
                " valor_ajustado, origem, meses_com_dado, ajustado_em, ajustado_por)"
                " SELECT %s, conta, mes, valor_baseline, valor_ajustado, origem,"
                " meses_com_dado, ajustado_em, ajustado_por FROM orc_linha"
                " WHERE versao_id=%s", (novo_id, versao_id))
            return novo_id


def zerar_fora_do_conjunto(esquema: str | None, versao_id: int,
                           chaves: set[tuple[str, int]]) -> int:
    """Zera o baseline das células que a nova derivação não produziu.

    A linha NÃO é apagada: se a controladoria ajustou aquela célula, o ajuste
    sobrevive à regeração — é a mesma regra do `coalesce`. Sem isso, um baseline
    velho de conta que sumiu do histórico continuaria somando no orçado.
    """
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.execute("SELECT conta, mes FROM orc_linha WHERE versao_id=%s",
                      (versao_id,))
            atuais = c.fetchall()
            sobrando = [(versao_id, r["conta"], r["mes"]) for r in atuais
                        if (r["conta"], r["mes"]) not in chaves]
            if sobrando:
                c.executemany(
                    "UPDATE orc_linha SET valor_baseline=0, origem='sem_base',"
                    " meses_com_dado=0 WHERE versao_id=%s AND conta=%s AND mes=%s",
                    sobrando)
            return len(sobrando)


def gravar_baseline(esquema: str | None, versao_id: int, linhas: list[dict]) -> int:
    """Insere ou atualiza o baseline. NÃO toca em valor_ajustado."""
    if not linhas:
        return 0
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.executemany("""
                INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline,
                                      origem, meses_com_dado)
                VALUES (%(v)s, %(conta)s, %(mes)s, %(valor_baseline)s,
                        %(origem)s, %(meses_com_dado)s)
                ON CONFLICT(versao_id, conta, mes) DO UPDATE SET
                    valor_baseline = excluded.valor_baseline,
                    origem         = excluded.origem,
                    meses_com_dado = excluded.meses_com_dado
            """, [{**l, "v": versao_id} for l in linhas])
            return len(linhas)


def ajustar(esquema: str | None, versao_id: int, conta: str, mes: int,
            valor: float | None, quem: str) -> None:
    """Grava (ou limpa, com valor=None) o ajuste manual de uma célula.

    Versão aprovada ou arquivada é imutável: reabra antes de ajustar. Versão
    inexistente segue para o KeyError de linha inexistente, como antes.
    """
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.execute("SELECT status FROM orc_versao WHERE id=%s", (versao_id,))
            versao = c.fetchone()
            if versao is not None and versao["status"] != "rascunho":
                raise ValueError(
                    "Versão aprovada/arquivada é imutável — reabra antes de ajustar.")
            c.execute(
                "SELECT valor_baseline, valor_ajustado FROM orc_linha"
                " WHERE versao_id=%s AND conta=%s AND mes=%s",
                (versao_id, conta, mes))
            row = c.fetchone()
            if row is None:
                raise KeyError(
                    f"linha inexistente: versao={versao_id} conta={conta} mes={mes}")
            de = (row["valor_ajustado"] if row["valor_ajustado"] is not None
                  else row["valor_baseline"])
            # o ajuste e a trilha na MESMA transação: célula alterada sem
            # registro de quem alterou é o que a controladoria vem cobrar
            c.execute(
                "UPDATE orc_linha SET valor_ajustado=%s,"
                f" ajustado_em={_AGORA_SQL}, ajustado_por=%s"
                " WHERE versao_id=%s AND conta=%s AND mes=%s",
                (valor, quem, versao_id, conta, mes))
            c.execute(
                "INSERT INTO orc_log(versao_id, conta, mes, valor_de, valor_para,"
                " quem) VALUES (%s,%s,%s,%s,%s,%s)",
                (versao_id, conta, mes, de, valor, quem))


def ler_linhas(esquema: str | None, versao_id: int) -> list[dict]:
    return _vazio_se_sem_tabela(lambda: pglocal.query("""
        SELECT conta, mes, valor_baseline, valor_ajustado, origem, meses_com_dado,
               ajustado_em, ajustado_por,
               coalesce(valor_ajustado, valor_baseline) AS valor_efetivo
        FROM orc_linha WHERE versao_id=%s ORDER BY conta, mes
    """, (versao_id,), esquema=_esq(esquema)), [])


def listar_versoes(esquema: str | None, ano: int | None = None) -> list[dict]:
    sql = "SELECT * FROM orc_versao"
    par: tuple | None = None
    if ano is not None:
        sql += " WHERE ano=%s"
        par = (ano,)
    sql += " ORDER BY ano DESC, id DESC"
    return _vazio_se_sem_tabela(
        lambda: pglocal.query(sql, par, esquema=_esq(esquema)), [])


def versao_vigente(esquema: str | None, ano: int | None = None) -> dict | None:
    """Escolhe a versão "em uso" dentre `listar_versoes(esquema, ano)`.

    Regra única, compartilhada por quem precisa de UM default (o painel de
    Fluxo em `caixa.provisao_do_ano` e o endpoint de comparativo sem
    `versao_id`): aprovada tem prioridade sobre rascunho — regerar não pode
    fazer quem lê "a versão atual" saltar silenciosamente para o snapshot
    congelado que o regerar acabou de criar. Arquivada NUNCA é escolhida (é
    histórico, não o orçamento vigente). Versão sem `status` gravado (banco
    de antes desta coluna) é tratada como rascunho.

    `ano=None` varre TODAS as versões (mesmo comportamento de
    `listar_versoes`), útil para "a versão mais recente de qualquer ano".
    """
    versoes = listar_versoes(esquema, ano)
    if not versoes:
        return None
    aprovada = next((v for v in versoes if v.get("status") == "aprovado"), None)
    if aprovada is not None:
        return aprovada
    return next((v for v in versoes if v.get("status") in (None, "", "rascunho")), None)


def ler_log(esquema: str | None, versao_id: int, limite: int = 200) -> list[dict]:
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT * FROM orc_log WHERE versao_id=%s ORDER BY id DESC LIMIT %s",
        (versao_id, limite), esquema=_esq(esquema)), [])
