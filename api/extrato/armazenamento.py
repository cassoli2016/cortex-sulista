"""Persistência local do extrato bancário (SQLite).

O ERP AVA é réplica somente-leitura, então o extrato importado é dado nosso.
Segue o padrão de `api/orcamento/armazenamento.py`: conexão curta com commit
automático e WAL.

Dedup (idempotência de re-upload): o OFX traz FITID, identificador único do
lançamento no banco -> chave natural. CSV não tem FITID: a chave passa a ser o
hash de (dt, valor, historico, numerodoc) + a ORDEM da ocorrência DENTRO DESSA
MESMA identidade, para que dois lançamentos legitimamente idênticos em todos os
campos no mesmo dia (duas tarifas iguais) sejam preservados, mas o mesmo arquivo
subido duas vezes — mesmo com a ordem das linhas trocada — não duplique nada.
`_identidade()` é a ÚNICA função que define essa identidade: tanto o contador de
ocorrência quanto o hash usam exatamente o que ela devolve, para não divergirem.

`tipo` (C/D) nunca é confiado ao item de entrada: é sempre DERIVADO do sinal de
`valor` (crédito >= 0, débito < 0), a constraint canônica do projeto. Isso
elimina a classe de bug "parser grava tipo errado" em vez de só detectá-la.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "extrato.db"


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path = DB_PATH) -> None:
    with _conn(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS ext_conta(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ident       TEXT NOT NULL UNIQUE,
            rotulo      TEXT NOT NULL,
            erp_banco   INTEGER,
            erp_agencia TEXT,
            erp_conta   TEXT,
            mapa_csv    TEXT,
            criado_em   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ext_importacao(
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            conta_id  INTEGER NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
            arquivo   TEXT NOT NULL,
            formato   TEXT NOT NULL,
            dt_de     TEXT,
            dt_ate    TEXT,
            novas     INTEGER NOT NULL DEFAULT 0,
            duplicadas INTEGER NOT NULL DEFAULT 0,
            ignoradas INTEGER NOT NULL DEFAULT 0,
            quando    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ext_lancamento(
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            conta_id      INTEGER NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
            importacao_id INTEGER NOT NULL REFERENCES ext_importacao(id) ON DELETE CASCADE,
            dt            TEXT NOT NULL,
            valor         REAL NOT NULL,
            tipo          TEXT NOT NULL,
            historico     TEXT NOT NULL DEFAULT '',
            numerodoc     TEXT NOT NULL DEFAULT '',
            fitid         TEXT,
            chave         TEXT NOT NULL,
            UNIQUE (conta_id, chave)
        );
        CREATE TABLE IF NOT EXISTS ext_saldo(
            conta_id      INTEGER NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
            dt            TEXT NOT NULL,
            saldo         REAL NOT NULL,
            importacao_id INTEGER REFERENCES ext_importacao(id) ON DELETE CASCADE,
            -- 'linha' (o banco imprimiu o saldo daquele dia) vence 'ledgerbal'
            -- (a posicao final do arquivo). Ver `gravar_saldo_extrato`.
            origem        TEXT NOT NULL DEFAULT 'ledgerbal',
            PRIMARY KEY (conta_id, dt)
        );
        CREATE INDEX IF NOT EXISTS ix_ext_lanc_conta_dt ON ext_lancamento(conta_id, dt);
        CREATE INDEX IF NOT EXISTS ix_ext_lanc_imp ON ext_lancamento(importacao_id);
        """)
        # migração: banco criado antes desta revisão não tem `importacao_id` em
        # ext_saldo (CREATE TABLE IF NOT EXISTS não altera tabela existente -
        # padrão de `api/orcamento/armazenamento.py`). Sem esse vínculo,
        # "desfazer" uma importação removia os lançamentos e deixava a âncora
        # de saldo órfã: se a âncora órfã fosse mais recente que a âncora boa,
        # `saldo_derivado` (que usa `max(dt)` das âncoras) partia dela e TODOS
        # os saldos derivados saíam errados - achado d1 da revisão final. As
        # âncoras gravadas ANTES da migração ficam com `importacao_id=NULL`
        # (decisão: mantê-las como estão - não sabemos a qual importação
        # pertenciam - `apagar_importacao` só remove as que casam o id exato,
        # nunca as `NULL`).
        cols = {r["name"] for r in c.execute("PRAGMA table_info(ext_saldo)")}
        if "importacao_id" not in cols:
            c.execute("ALTER TABLE ext_saldo ADD COLUMN importacao_id "
                     "INTEGER REFERENCES ext_importacao(id) ON DELETE CASCADE")
        if "origem" not in cols:
            # Ancora gravada antes desta revisao fica como 'ledgerbal', o valor
            # mais fraco: assim a primeira linha de saldo de verdade que chegar
            # a substitui. O contrario (assumir 'linha') protegeria para sempre
            # um numero que pode ser o consolidado errado.
            c.execute("ALTER TABLE ext_saldo ADD COLUMN origem TEXT NOT NULL "
                      "DEFAULT 'ledgerbal'")

        _remigra_chaves(c)


def _remigra_chaves(c) -> int:
    """Recalcula as chaves gravadas no formato antigo `fitid:<id>` (ver `_chave`).

    Sem isto, uma base que ja tenha lancamentos fica com dois formatos de chave
    convivendo, e o reimport do MESMO arquivo passa a inserir tudo de novo: as
    linhas antigas estao sob `fitid:...` e as novas sob `hash:...`, entao o
    `INSERT OR IGNORE` nao encontra colisao nenhuma e a conta dobra.

    A reconstrucao repete exatamente o que `gravar_lancamentos` faria: agrupa
    por importacao e percorre por `id` (a ordem de insercao original), porque o
    contador de ocorrencia e por IMPORTACAO, nao por conta.

    Duas linhas da mesma conta podem cair na mesma chave nova - acontece quando
    o esquema antigo as manteve separadas SO por terem FITIDs diferentes sendo,
    em tudo o mais, o mesmo lancamento importado duas vezes. Sob a regra nova
    isso e duplicata; fica a de menor `id` (a primeira que entrou) e a outra sai,
    com a contagem no log para que a remocao nao seja silenciosa.
    """
    import logging

    antigas = c.execute(
        "SELECT id, conta_id, importacao_id, dt, valor, historico, numerodoc, fitid "
        "FROM ext_lancamento WHERE chave LIKE 'fitid:%' ORDER BY conta_id, importacao_id, id"
    ).fetchall()
    if not antigas:
        return 0

    vistos: dict[tuple, int] = {}
    novas: dict[int, str] = {}
    for r in antigas:
        item = {"dt": r["dt"], "valor": r["valor"], "historico": r["historico"],
                "numerodoc": r["numerodoc"], "fitid": r["fitid"]}
        base = (r["importacao_id"], *_identidade(item))
        vistos[base] = vistos.get(base, 0) + 1
        novas[r["id"]] = _chave(item, vistos[base])

    # colisao entre chaves novas dentro da MESMA conta: fica o menor id
    dono: dict[tuple[int, str], int] = {}
    sobra: list[int] = []
    for r in antigas:
        k = (r["conta_id"], novas[r["id"]])
        if k in dono:
            sobra.append(r["id"])
        else:
            dono[k] = r["id"]

    if sobra:
        c.executemany("DELETE FROM ext_lancamento WHERE id=?", [(i,) for i in sobra])
    # a chave antiga e sempre distinta da nova (prefixo diferente), entao nao ha
    # colisao com linhas ainda nao migradas no meio do caminho
    c.executemany("UPDATE ext_lancamento SET chave=? WHERE id=?",
                  [(novas[r["id"]], r["id"]) for r in antigas if r["id"] not in set(sobra)])
    logging.getLogger(__name__).warning(
        "extrato: %d chaves remigradas do formato fitid: para hash: (%d duplicatas removidas)",
        len(antigas) - len(sobra), len(sobra))
    return len(antigas) - len(sobra)


def _norm_historico(s: str | None) -> str:
    """Maiúsculas + colapsa espaços internos repetidos (export de banco costuma
    trazer "TARIFA  PACOTE" com espaço duplo) — mesmo padrão de normalização de
    rótulo do ERP já usado no projeto (`" ".join(x.split())`)."""
    return " ".join((s or "").upper().split())


def _identidade(item: dict) -> tuple[str, str, str, str]:
    """(dt, valor, historico normalizado, numerodoc) — a identidade natural de um
    lançamento sem FITID. ÚNICO lugar que define isso: tanto o contador de
    ocorrência (`gravar_lancamentos`) quanto o hash (`_chave`) partem daqui, para
    que não possam divergir entre si (causa raiz de um bug já corrigido: contar
    ocorrência sem o numerodoc fazia dois boletos de mesmo dia/valor/histórico
    mas numerodoc diferente colidirem no mesmo contador, tornando a chave
    dependente da ORDEM da lista em vez do conteúdo)."""
    return (
        item["dt"],
        f"{float(item['valor']):.2f}",
        _norm_historico(item.get("historico")),
        (item.get("numerodoc") or "").strip(),
    )


def _chave(item: dict, ocorrencia: int) -> str:
    """Hash estavel da identidade + FITID + ocorrencia. NUNCA o FITID sozinho.

    O FITID e, pela especificacao OFX, unico dentro da conta - e e por isso que
    a versao anterior confiava nele como chave inteira. Banco brasileiro nao
    cumpre isso, e o desvio nao e de borda:

      - Caixa Economica, agosto/2026: 65 lancamentos, 15 FITIDs distintos. O
        valor repetido 26 vezes e "341" - o CODIGO DO BANCO DE ORIGEM da TED,
        nao um identificador de transacao. Outro repete 9 vezes com "33".
      - Bradesco: um boleto agendado colide com um lancamento ja realizado.

    Com `UNIQUE (conta_id, chave)` e `INSERT OR IGNORE`, cada colisao dessas e
    um lancamento DESCARTADO EM SILENCIO, contado na tela como "duplicada".
    Medido nos sete arquivos reais: 53 de 756 lancamentos (7%) sumiam, sendo
    50 so na Caixa - R$ 2.464.042,23 de credito, incluindo TEDs de R$ 287 mil,
    R$ 327 mil e R$ 377 mil, com a importacao reportando sucesso.

    O FITID continua entrando na chave (banco que o preenche direito ganha a
    unicidade de graca), mas so como MAIS UM campo, ao lado da identidade
    natural e do contador de ocorrencia - que e o que ja separava dois
    lancamentos gemeos do mesmo arquivo.

    A troca tem um custo, e ele e o lado certo de errar: se um banco reexportar
    o MESMO lancamento com o historico diferente, a chave muda e ele entra
    duas vezes. Duplicata aparece na tela e alguem corrige; sumico silencioso
    de R$ 2,4 mi nao aparece em lugar nenhum.
    """
    dt, valor, historico, numerodoc = _identidade(item)
    fitid = (item.get("fitid") or "").strip()
    cru = "|".join([dt, valor, historico, numerodoc, fitid, str(ocorrencia)])
    return "hash:" + hashlib.sha1(cru.encode("utf-8")).hexdigest()


def obter_ou_criar_conta(path: Path, ident: str, rotulo: str) -> int:
    with _conn(path) as c:
        row = c.execute("SELECT id FROM ext_conta WHERE ident=?", (ident,)).fetchone()
        if row:
            return int(row["id"])
        cur = c.execute("INSERT INTO ext_conta(ident, rotulo) VALUES(?,?)", (ident, rotulo))
        return int(cur.lastrowid)


def mapear_conta(path: Path, conta_id: int, erp_banco: int, erp_agencia: str,
                 erp_conta: str, rotulo: str | None = None) -> None:
    with _conn(path) as c:
        if rotulo:
            c.execute("UPDATE ext_conta SET erp_banco=?, erp_agencia=?, erp_conta=?, rotulo=? "
                      "WHERE id=?", (erp_banco, erp_agencia, erp_conta, rotulo, conta_id))
        else:
            c.execute("UPDATE ext_conta SET erp_banco=?, erp_agencia=?, erp_conta=? WHERE id=?",
                      (erp_banco, erp_agencia, erp_conta, conta_id))


def salvar_mapa_csv(path: Path, conta_id: int, mapa: dict) -> None:
    with _conn(path) as c:
        c.execute("UPDATE ext_conta SET mapa_csv=? WHERE id=?",
                  (json.dumps(mapa, ensure_ascii=False), conta_id))


def _conta_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["mapa_csv"] = json.loads(d["mapa_csv"]) if d.get("mapa_csv") else None
    return d


def conta_por_ident(path: Path, ident: str) -> dict | None:
    with _conn(path) as c:
        row = c.execute("SELECT * FROM ext_conta WHERE ident=?", (ident,)).fetchone()
    return _conta_dict(row) if row else None


def listar_contas(path: Path = DB_PATH) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM ext_conta ORDER BY rotulo").fetchall()
    return [_conta_dict(r) for r in rows]


def gravar_lancamentos(path: Path, conta_id: int, itens: list[dict], arquivo: str,
                       formato: str, ignoradas: int = 0) -> dict:
    datas = sorted(i["dt"] for i in itens) or [None]
    novas = dupl = 0
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO ext_importacao(conta_id, arquivo, formato, dt_de, dt_ate, ignoradas) "
            "VALUES(?,?,?,?,?,?)", (conta_id, arquivo, formato, datas[0], datas[-1], ignoradas))
        imp_id = int(cur.lastrowid)
        vistos: dict[tuple[str, str, str, str], int] = {}
        for item in itens:
            base = _identidade(item)
            vistos[base] = vistos.get(base, 0) + 1
            chave = _chave(item, vistos[base])
            valor = float(item["valor"])
            tipo = "C" if valor >= 0 else "D"  # sinal manda, nunca o campo de entrada
            ins = c.execute(
                "INSERT OR IGNORE INTO ext_lancamento"
                "(conta_id, importacao_id, dt, valor, tipo, historico, numerodoc, fitid, chave) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (conta_id, imp_id, item["dt"], valor, tipo,
                 item.get("historico") or "", item.get("numerodoc") or "",
                 item.get("fitid"), chave))
            if ins.rowcount:
                novas += 1
            else:
                dupl += 1
        c.execute("UPDATE ext_importacao SET novas=?, duplicadas=? WHERE id=?",
                  (novas, dupl, imp_id))
        # importação que não trouxe nada novo não fica na trilha (poluiria a lista
        # de uploads com registros vazios a cada re-upload)
        if novas == 0:
            c.execute("DELETE FROM ext_importacao WHERE id=?", (imp_id,))
    return {"importacao_id": imp_id if novas else 0, "novas": novas, "duplicadas": dupl}


def gravar_saldo_extrato(path: Path, conta_id: int, dt: str, saldo: float,
                         importacao_id: int | None = None,
                         origem: str = "ledgerbal") -> None:
    """Grava a âncora de saldo de um dia, respeitando a PRECEDÊNCIA da origem.

    `importacao_id` amarra a âncora à importação que a gravou, para que
    desfazer aquela importação (`apagar_importacao`) leve a âncora junto -
    sem isso ela ficava órfã e podia virar a mais recente por engano,
    corrompendo TODOS os saldos derivados dali pra frente (achado d1). No
    UPDATE do upsert o `importacao_id` também é sobrescrito: a âncora sempre
    pertence à importação mais recente que a confirmou, nunca à primeira.

    A PRECEDÊNCIA existe por causa do uso DIÁRIO, e o defeito só aparece nele.
    Um arquivo traz dois tipos de saldo: a linha impressa do dia ('linha') e o
    `LEDGERBAL`, que é a posição final do arquivo ('ledgerbal'). Dentro de um
    arquivo só, o parser já dá preferência à linha. Mas quem envia um extrato
    por dia manda o `LEDGERBAL` de novo em CADA arquivo, e ele costuma vir com
    a data de um dia anterior - então o envio de hoje reescrevia a âncora de
    ontem, que era boa.

    Medido no Safra: o `LEDGERBAL` de 24/08 diz R$ 10.502,92 (posição
    consolidada, conta + aplicação) enquanto a linha do mesmo 24/08 diz
    R$ 657,38 (a conta corrente, que é o que o `contacorrente_saldo` do ERP
    guarda). Importando o mês inteiro de uma vez o número certo ficava;
    importando dia a dia, o errado sobrescrevia - e a conta passava a divergir
    do ERP em R$ 9.845,54 por um saldo que o próprio arquivo já tinha certo.

    Por isso 'ledgerbal' NÃO sobrescreve 'linha'. O contrário sobrescreve (é
    dado melhor), e origem igual sempre sobrescreve (reenvio corrige).
    """
    with _conn(path) as c:
        c.execute(
            "INSERT INTO ext_saldo(conta_id, dt, saldo, importacao_id, origem) "
            "VALUES(?,?,?,?,?) "
            # COALESCE: reimportar o MESMO arquivo (0 lancamentos novos) chama aqui
            # com importacao_id None, porque a importacao sem novidade se autodeleta
            # da trilha. Sobrescrever com NULL destruiria o vinculo BOM criado pela
            # importacao original - que segue viva - e um "desfazer" nela deixaria a
            # ancora orfa, corrompendo todos os saldos derivados. Vinculo existente
            # so e substituido quando ha um novo de verdade para oferecer.
            "ON CONFLICT(conta_id, dt) DO UPDATE SET saldo=excluded.saldo, "
            "importacao_id=COALESCE(excluded.importacao_id, ext_saldo.importacao_id), "
            "origem=excluded.origem "
            # o WHERE do upsert e' o que implementa a precedencia: sem ele o
            # SET acima roda sempre e o LEDGERBAL de amanha apaga a linha de hoje
            "WHERE excluded.origem='linha' OR ext_saldo.origem<>'linha'",
            (conta_id, dt, float(saldo), importacao_id, origem))


def saldos_extrato(path: Path, conta_id: int) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("SELECT dt, saldo FROM ext_saldo WHERE conta_id=? ORDER BY dt",
                         (conta_id,)).fetchall()
    return [dict(r) for r in rows]


def lancamentos(path: Path, conta_id: int, dt_de: str, dt_ate: str) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            # o `id` viaja junto porque a conciliacao linha a linha precisa de uma
            # referencia ESTAVEL para o par que ela montou - dt+valor+historico nao
            # serve, que e justamente o caso de dois lancamentos gemeos no mesmo dia
            "SELECT id, dt, valor, tipo, historico, numerodoc FROM ext_lancamento "
            "WHERE conta_id=? AND dt BETWEEN ? AND ? ORDER BY dt, id", (conta_id, dt_de, dt_ate)
        ).fetchall()
    return [dict(r) for r in rows]


def listar_importacoes(path: Path = DB_PATH, limite: int = 20) -> list[dict]:
    """As `limite` importações mais recentes, para a TABELA DA TELA. NUNCA usar
    isto para decidir o último dia coberto por conta (regra de negócio) - com
    8 contas subindo 1 extrato/dia, 20 linhas enchem em 2,5 dias e uma conta de
    upload menos frequente some da lista sem ter ficado desatualizada de
    verdade. Para isso existe `ultimo_dt_por_conta`, sem limite."""
    with _conn(path) as c:
        rows = c.execute(
            "SELECT i.*, c.rotulo AS conta_rotulo FROM ext_importacao i "
            "JOIN ext_conta c ON c.id=i.conta_id ORDER BY i.id DESC LIMIT ?", (limite,)
        ).fetchall()
    return [dict(r) for r in rows]


def ultimo_dt_por_conta(path: Path = DB_PATH) -> dict[int, str]:
    """Último `dt_ate` de importação por conta, direto do banco - sem o
    `LIMIT 20` de `listar_importacoes` (que é só da listagem da tela, Task 7).

    Achado C1 (crítico) da revisão final: `servico.painel` montava isso a
    partir de `listar_importacoes`, então uma conta cuja importação mais
    recente caísse fora das 20 mais novas ficava com `ultimo_upload=None` e o
    farol caía em "desatualizado" por ausência de dado (`comparacao.farol`,
    ramo `dias_sem is None`) - cuja precedência engole uma divergência real,
    fazendo-a sumir do farol e do digest. As contas afetadas são justamente
    as de upload menos frequente, as mais expostas ao problema que este
    painel existe para pegar."""
    with _conn(path) as c:
        rows = c.execute(
            "SELECT conta_id, max(dt_ate) AS dt_ate FROM ext_importacao "
            "WHERE dt_ate IS NOT NULL GROUP BY conta_id").fetchall()
    return {int(r["conta_id"]): r["dt_ate"] for r in rows}


def apagar_importacao(path: Path, importacao_id: int) -> int:
    with _conn(path) as c:
        n = c.execute("DELETE FROM ext_lancamento WHERE importacao_id=?",
                      (importacao_id,)).rowcount
        # remove só a(s) âncora(s) de saldo QUE PERTENCEM a esta importação -
        # âncoras de outras importações ou anteriores à migração
        # (`importacao_id IS NULL`) nunca são tocadas por este DELETE (d1).
        c.execute("DELETE FROM ext_saldo WHERE importacao_id=?", (importacao_id,))
        c.execute("DELETE FROM ext_importacao WHERE id=?", (importacao_id,))
    return int(n)
