"""Cache local das coletas lentas da Gobrax — data/telemetria.db.

O ÚNICO STORE QUE FICOU EM SQLITE, e de propósito. Os outros dez migraram para
o PostgreSQL em 27/08/2026 (docs/MIGRACAO_POSTGRES.md); este não, porque é
CACHE DESCARTÁVEL de verdade: guarda exatamente as duas competências que a
tarefa agendada recoleta de 3 em 3 horas (mês corrente e anterior, ver
`scripts/coletar_telemetria.py`). Apagar o arquivo custa uma coleta, não um
dado — e levá-lo para o banco só encheria o backup de linhas que se refazem
sozinhas antes do próximo dump.

NÃO copie esta forma para módulo novo: quem ESCREVE dado da casa usa
`api/pglocal.py`. Ver a seção "Onde o dado é ESCRITO" do CLAUDE.md.

vehicle-statistics leva 73 s para a frota e vehicle-odometer 66 s. Nenhuma tela
pode pagar isso no carregamento, então o resultado é coletado em segundo plano e
lido daqui. O registro vai como JSON: o formato da API muda com o tempo e não
vale criar coluna para cada campo.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "telemetria.db"


class ColetaVazia(Exception):
    """Coleta sem registros. Nunca substitui o que já está gravado."""


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path | None = None) -> None:
    with _conn(path or DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS coleta(
            colecao     TEXT NOT NULL,
            competencia TEXT NOT NULL,
            registro    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_coleta ON coleta(colecao, competencia);
        CREATE TABLE IF NOT EXISTS coleta_log(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            colecao     TEXT NOT NULL,
            competencia TEXT NOT NULL,
            quando      TEXT NOT NULL,
            registros   INTEGER NOT NULL
        );
        """)


def gravar(colecao: str, competencia: str, registros: list[dict],
           path: Path | None = None) -> int:
    if not registros:
        raise ColetaVazia(f"coleta de {colecao}/{competencia} veio vazia")
    p = path or DB_PATH
    init_db(p)
    with _conn(p) as c:
        c.execute("DELETE FROM coleta WHERE colecao=? AND competencia=?",
                  (colecao, competencia))
        c.executemany(
            "INSERT INTO coleta(colecao, competencia, registro) VALUES(?,?,?)",
            [(colecao, competencia, json.dumps(r, ensure_ascii=False))
             for r in registros])
        c.execute("INSERT INTO coleta_log(colecao, competencia, quando, registros)"
                  " VALUES(?,?,?,?)",
                  (colecao, competencia,
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(registros)))
    return len(registros)


def ler(colecao: str, competencia: str, path: Path | None = None) -> list[dict]:
    p = path or DB_PATH
    if not Path(p).exists():
        return []
    with _conn(p) as c:
        return [json.loads(r["registro"]) for r in c.execute(
            "SELECT registro FROM coleta WHERE colecao=? AND competencia=?",
            (colecao, competencia))]


def competencia_atual(colecao: str, path: Path | None = None) -> dict | None:
    """Coleta da MAIOR competência, não a última gravada.

    `ultima()` ordena por `id DESC`, isto é, pela ordem de INSERÇÃO. Isso
    basta enquanto se coleta um mês só, mas quebra na hora em que alguém
    recoleta um mês antigo: a coleta de julho, feita depois da de agosto,
    passaria a ser "a última" e a Torre voltaria a mostrar julho como se
    fosse a posição de hoje. Aconteceu na primeira execução do coletor
    agendado, que busca o mês corrente e o anterior.

    Como a competência é 'AAAA-MM', a ordenação alfabética é cronológica.
    """
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute(
            "SELECT competencia, quando, registros FROM coleta_log"
            " WHERE colecao=? ORDER BY competencia DESC, id DESC LIMIT 1",
            (colecao,)).fetchone()
    return dict(row) if row else None


def ultima(colecao: str, path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute(
            "SELECT competencia, quando, registros FROM coleta_log"
            " WHERE colecao=? ORDER BY id DESC LIMIT 1", (colecao,)).fetchone()
    return dict(row) if row else None


# coleções que a tarefa agendada alimenta. Estatística e odômetro andam
# JUNTAS: a Torre cruza as duas, e uma fresca com a outra parada é pior que as
# duas velhas — por isso o diagnóstico reporta sempre a MAIS ATRASADA.
COLECOES = (("estatisticas", "estatísticas"), ("odometro", "odômetro"))

# CADÊNCIA DIÁRIA, e por isso FORA da lista acima. `vehicle-performance` exige
# uma chamada POR PLACA: são 108 chamadas contra 1 das outras duas, e varrer a
# frota de 3 em 3 horas seriam ~860 requisições por dia ao fornecedor para um
# dado que muda devagar (o acumulado do mês).
#
# Misturá-la com o par acima quebraria o alarme da Saúde: aquele limiar é de
# duas janelas de 3 h, e uma coleta diária o estouraria TODO DIA — o cartão
# ficaria vermelho com a integração funcionando, que é a forma conhecida de
# ensinar a ignorar o alarme.
COLECOES_DIARIAS = (("performance", "indicadores de condução"),)


def diagnostico(path: Path | None = None) -> dict:
    """Estado da integração Gobrax, sem expor segredo — alimenta a Saúde.

    Lê o CACHE, nunca a API: uma volta em vehicle-statistics leva 73 s e a tela
    de Saúde recarrega a cada 5 s. O que interessa aqui não é "responde?" — é
    se o retrato que as telas mostram está fresco.

    São DUAS credenciais diferentes no mesmo fornecedor, e é fácil esquecer:
    a telemetria usa `GOBRAX_TOKEN` (cofre) e a premiação usa o login do portal
    (`GOBRAX_EMAIL`/`GOBRAX_SENHA`). Uma pode estar de pé com a outra caída.
    """
    from . import cliente
    from ..premiacao import gobrax as prem
    return {
        "configurado": cliente.configurado(),
        "premiacao_configurada": prem.configurado(),
        "colecoes": {c: competencia_atual(c, path) for c, _ in COLECOES},
        "diarias": {c: competencia_atual(c, path)
                    for c, _ in COLECOES_DIARIAS},
    }
