"""Armazenamento local das planilhas de antecipação (data/antecipacoes.db).

SQLite pelo mesmo motivo do `orcamento.db` e do `email.db`: o AVA é réplica
somente-leitura, então tudo que o CÓRTEX ESCREVE mora ao lado. Conexão curta,
WAL, commit automático.

Guarda três coisas:

1. **Envios** — cada arquivo importado, com quem enviou, o portal detectado e
   os totais. É a trilha: "de quando é o dado que estou vendo".
2. **Títulos** — as linhas do arquivo mais recente de cada portal. Só o mais
   recente conta como posição atual; os anteriores ficam para histórico.
3. **Sacados elegíveis** — quais clientes têm convênio de antecipação. É o que
   faltava para a simulação parar de sugerir antecipar recebível de cliente
   que não tem portal. Alimentado automaticamente por quem aparece como
   sacado num arquivo importado, e editável na tela: convênio assinado hoje
   vale antes de existir a primeira planilha, e convênio encerrado precisa
   sair sem esperar o arquivo parar de chegar.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "antecipacoes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS envios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  usuario TEXT,
  arquivo TEXT NOT NULL,
  portal TEXT NOT NULL,
  portal_rotulo TEXT,
  titulos INTEGER NOT NULL,
  valor_nominal REAL NOT NULL,
  valor_saldo REAL NOT NULL,
  total_declarado REAL,
  divergencia REAL,
  rejeitadas INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS titulos (
  envio_id INTEGER NOT NULL REFERENCES envios(id) ON DELETE CASCADE,
  titulo TEXT, documento TEXT, emissao TEXT, vencimento TEXT,
  valor_nominal REAL, valor_saldo REAL, antecipavel INTEGER,
  situacao TEXT, cnpj_cedente TEXT, nome_cedente TEXT,
  cnpj_sacado TEXT, nome_sacado TEXT, chave TEXT, id_portal TEXT
);
CREATE INDEX IF NOT EXISTS ix_tit_envio ON titulos(envio_id);
CREATE INDEX IF NOT EXISTS ix_tit_doc ON titulos(documento);
CREATE TABLE IF NOT EXISTS sacados (
  cnpj TEXT PRIMARY KEY,
  nome TEXT,
  portal TEXT,
  elegivel INTEGER NOT NULL DEFAULT 1,
  origem TEXT,          -- 'arquivo' ou 'manual'
  atualizado_em TEXT,
  observacao TEXT
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(_SCHEMA)
    # `CREATE TABLE IF NOT EXISTS` não altera tabela que já existe: coluna
    # nova precisa de ALTER explícito, senão só bancos criados do zero teriam.
    cols = {r["name"] for r in c.execute("PRAGMA table_info(envios)")}
    if "impressao" not in cols:
        c.execute("ALTER TABLE envios ADD COLUMN impressao TEXT")
    if "vigente" not in cols:
        # 1 = é a posição atual daquele portal. Envio antigo continua na lista
        # (é a trilha de "de quando é o dado"), mas seus títulos são apagados.
        c.execute("ALTER TABLE envios ADD COLUMN vigente INTEGER NOT NULL DEFAULT 1")
    if "origem" not in cols:
        # 'planilha' ou 'api'. So a Tupy tem API (Monkey Exchange); Maxion e
        # Adient continuam por arquivo, entao a tela convive com as duas
        # origens e precisa dizer qual e qual — "lida ha 10 minutos" e uma
        # garantia diferente de "planilha de 24/08". Envio antigo e planilha
        # por definicao: a API nao existia quando ele foi gravado.
        c.execute("ALTER TABLE envios ADD COLUMN origem TEXT NOT NULL"
                  " DEFAULT 'planilha'")
    return c


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def impressao(dados: bytes) -> str:
    """Impressão digital do arquivo, para reconhecer reimportação do mesmo."""
    import hashlib
    return hashlib.sha256(dados or b"").hexdigest()


def gravar_envio(lido: dict, resumo: dict, usuario: str = "",
                 dados: bytes | None = None) -> tuple[int, bool]:
    """Grava o arquivo importado. Devolve (envio_id, ja_existia).

    Duas regras que evitam duplicidade, e por motivos diferentes:

    1. **Arquivo IDÊNTICO (mesma impressão) não cria envio novo.** Reimportar
       a mesma planilha é acidente comum — clicar duas vezes, ou não ter
       certeza se o primeiro envio pegou. Sem isto o banco acumula cópias e a
       lista de importações mente sobre a frequência com que o dado é
       atualizado. Devolve o envio original com `ja_existia=True` para a tela
       poder dizer "este arquivo já foi importado em <data>".

    2. **Arquivo NOVO do mesmo portal substitui o anterior.** A posição atual
       daquele cliente é o último arquivo; os títulos do anterior são
       apagados. O registro do envio antigo fica (é a trilha de quando o dado
       foi atualizado), mas sem os títulos — senão o banco cresce 226 linhas
       por importação para sempre.

    Portais DIFERENTES coexistem: Maxion, Tupy e Adient são três posições
    simultâneas, não uma substituindo a outra.
    """
    imp = impressao(dados) if dados is not None else None
    with _conn() as c:
        if imp:
            ja = c.execute("SELECT id FROM envios WHERE impressao=? AND portal=?"
                           " ORDER BY id DESC LIMIT 1",
                           (imp, lido["portal"])).fetchone()
            if ja:
                # marca que foi reenviado agora, sem duplicar a linha
                c.execute("UPDATE envios SET ts=? WHERE id=?", (_agora(), ja["id"]))
                return int(ja["id"]), True

        cur = c.execute(
            "INSERT INTO envios (ts,usuario,arquivo,portal,portal_rotulo,titulos,"
            "valor_nominal,valor_saldo,total_declarado,divergencia,rejeitadas,"
            "impressao,vigente)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (_agora(), usuario, lido["arquivo"], lido["portal"],
             lido["portal_rotulo"], resumo["titulos"], resumo["valor_nominal"],
             resumo["valor_saldo"], lido["total_declarado"], lido["divergencia"],
             len(lido["rejeitadas"]), imp))
        envio_id = cur.lastrowid

        # o arquivo novo é a posição atual DESTE portal; o anterior sai de cena
        c.execute("DELETE FROM titulos WHERE envio_id IN"
                  " (SELECT id FROM envios WHERE portal=? AND id<>?)",
                  (lido["portal"], envio_id))
        c.execute("UPDATE envios SET vigente=0 WHERE portal=? AND id<>?",
                  (lido["portal"], envio_id))
        c.executemany(
            "INSERT INTO titulos (envio_id,titulo,documento,emissao,vencimento,"
            "valor_nominal,valor_saldo,antecipavel,situacao,cnpj_cedente,"
            "nome_cedente,cnpj_sacado,nome_sacado,chave,id_portal)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(envio_id, t["titulo"], t["documento"],
              t["emissao"].isoformat() if t["emissao"] else None,
              t["vencimento"].isoformat(), t["valor_nominal"], t["valor_saldo"],
              None if t["antecipavel"] is None else int(t["antecipavel"]),
              t["situacao"], t["cnpj_cedente"], t["nome_cedente"],
              t["cnpj_sacado"], t["nome_sacado"], t["chave"], t["id_portal"])
             for t in lido["titulos"]])

        # Sacado do arquivo entra como elegível — se o cliente exporta planilha
        # de antecipação, existe convênio. NÃO sobrescreve `elegivel` de quem
        # já está lá: um sacado desligado à mão continuaria voltando a cada
        # arquivo novo, e a decisão manual tem de ganhar da automática.
        for s in resumo["sacados"]:
            c.execute(
                "INSERT INTO sacados (cnpj,nome,portal,elegivel,origem,atualizado_em)"
                " VALUES (?,?,?,1,'arquivo',?)"
                " ON CONFLICT(cnpj) DO UPDATE SET nome=excluded.nome,"
                " portal=excluded.portal, atualizado_em=excluded.atualizado_em",
                (s["cnpj"], s["nome"], lido["portal"], _agora()))
    return envio_id, False


def marcar_origem(envio_id: int, origem: str) -> None:
    """Diz se a posicao veio de planilha ou de API. Chamado logo depois de
    gravar; separado de `gravar_envio` para nao mudar a assinatura que o
    caminho de planilha ja usa."""
    with _conn() as c:
        c.execute("UPDATE envios SET origem=? WHERE id=?",
                  (origem if origem in ("planilha", "api") else "planilha",
                   envio_id))


def posicao_atual() -> list[dict]:
    """Um envio VIGENTE por portal — a posição de cada cliente hoje.

    `ultimo_envio()` devolvia o mais recente de todos, o que bastava enquanto
    só existia a Maxion. Com Tupy e Adient no convênio, importar o arquivo de
    um faria os outros dois SUMIREM da tela — o dado continuaria no banco e o
    painel mostraria uma fração da posição, sem avisar.
    """
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM envios WHERE vigente=1 ORDER BY valor_saldo DESC")]


def titulos_vigentes() -> list[dict]:
    """Títulos de TODOS os portais vigentes, somados numa lista só."""
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT t.* FROM titulos t JOIN envios e ON e.id=t.envio_id"
            " WHERE e.vigente=1 ORDER BY t.valor_saldo DESC")]


def envios(limite: int = 30) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM envios ORDER BY id DESC LIMIT ?", (limite,))]


def ultimo_envio(portal: str | None = None) -> dict | None:
    with _conn() as c:
        if portal:
            r = c.execute("SELECT * FROM envios WHERE portal=? ORDER BY id DESC"
                          " LIMIT 1", (portal,)).fetchone()
        else:
            r = c.execute("SELECT * FROM envios ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None


def titulos_do_envio(envio_id: int) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM titulos WHERE envio_id=? ORDER BY valor_saldo DESC",
            (envio_id,))]


def apagar_envio(envio_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM titulos WHERE envio_id=?", (envio_id,))
        c.execute("DELETE FROM envios WHERE id=?", (envio_id,))


def sacados(so_elegiveis: bool = False) -> list[dict]:
    sql = "SELECT * FROM sacados"
    if so_elegiveis:
        sql += " WHERE elegivel=1"
    sql += " ORDER BY elegivel DESC, nome"
    with _conn() as c:
        return [dict(r) for r in c.execute(sql)]


def cnpjs_elegiveis() -> set[str]:
    """Só os dígitos, para casar com o CNPJ do ERP sem máscara."""
    return {s["cnpj"] for s in sacados(so_elegiveis=True) if s["cnpj"]}


def definir_sacado(cnpj: str, nome: str = "", elegivel: bool = True,
                   observacao: str = "", portal: str = "") -> dict:
    """Marca/desmarca um sacado. `origem='manual'` para a próxima importação
    não desfazer a decisão de quem opera."""
    cnpj = "".join(ch for ch in (cnpj or "") if ch.isdigit())
    if not cnpj:
        raise ValueError("Informe o CNPJ do cliente.")
    with _conn() as c:
        c.execute(
            "INSERT INTO sacados (cnpj,nome,portal,elegivel,origem,atualizado_em,observacao)"
            " VALUES (?,?,?,?,'manual',?,?)"
            " ON CONFLICT(cnpj) DO UPDATE SET"
            " nome=CASE WHEN excluded.nome<>'' THEN excluded.nome ELSE sacados.nome END,"
            " portal=CASE WHEN excluded.portal<>'' THEN excluded.portal ELSE sacados.portal END,"
            " elegivel=excluded.elegivel, origem='manual',"
            " atualizado_em=excluded.atualizado_em, observacao=excluded.observacao",
            (cnpj, nome, portal, int(elegivel), _agora(), observacao))
        r = c.execute("SELECT * FROM sacados WHERE cnpj=?", (cnpj,)).fetchone()
    return dict(r)


def raizes_elegiveis() -> set[str]:
    """Raízes de CNPJ (8 primeiros dígitos) com convênio de antecipação.

    RAIZ e não o CNPJ inteiro de propósito. O portal da Maxion manda como
    pagador só o CNPJ da matriz (61.156.113/0001-75), mas o ERP tem QUATRO
    filiais dela cadastradas como clientes distintos (0001-75, 0005-07,
    0006-80, 0007-60) e o faturamento se espalha entre elas. O convênio é do
    GRUPO: casar os 14 dígitos deixaria três quartos do recebível de fora e a
    tela diria que não dá para antecipar o que dá.
    """
    return {c[:8] for c in cnpjs_elegiveis() if len(c) >= 8}


def documentos_no_portal() -> set[tuple[str, str]]:
    """Documentos LANÇADOS nos portais, como (raiz do CNPJ do sacado, nº).

    Ter convênio não basta para antecipar: o título precisa estar lançado no
    portal do cliente. Como não há API para consultar isso, a planilha
    importada É a fonte de verdade — só o que está nela pode ser antecipado.

    A chave leva a RAIZ do CNPJ junto com o número do documento porque
    numeração de nota se repete entre emitentes: casar só pelo número faria a
    NF 100226 de um cliente autorizar a NF 100226 de outro.

    Título marcado como não antecipável no próprio portal fica de fora.
    """
    with _conn() as c:
        linhas = c.execute(
            "SELECT t.cnpj_sacado, t.documento FROM titulos t"
            " JOIN envios e ON e.id = t.envio_id"
            " WHERE e.vigente=1 AND t.documento <> ''"
            "   AND (t.antecipavel IS NULL OR t.antecipavel = 1)").fetchall()
    return {(r["cnpj_sacado"][:8], r["documento"]) for r in linhas
            if r["cnpj_sacado"]}


def portais_com_planilha() -> set[str]:
    """Raízes de CNPJ que TÊM planilha vigente importada.

    Separa "cliente com convênio mas sem planilha" (falta pedir o arquivo) de
    "cliente sem convênio" (falta negociar) — são pendências diferentes, com
    donos diferentes.
    """
    with _conn() as c:
        linhas = c.execute(
            "SELECT DISTINCT t.cnpj_sacado FROM titulos t"
            " JOIN envios e ON e.id = t.envio_id WHERE e.vigente=1").fetchall()
    return {r["cnpj_sacado"][:8] for r in linhas if r["cnpj_sacado"]}
