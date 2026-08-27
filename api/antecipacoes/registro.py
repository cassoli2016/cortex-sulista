"""Armazenamento local das planilhas de antecipação — PostgreSQL (`cortex`).

Quinto store migrado do SQLite (27/08/2026 — ver `docs/MIGRACAO_POSTGRES.md`).
O `data/antecipacoes.db` continua no disco até a fase seguinte fechar.

O AVA é réplica somente-leitura, então tudo que o CÓRTEX ESCREVE mora aqui.
As tabelas levam o prefixo `ant_`: `envios` já é do correio, e `titulos` é
nome genérico demais para um schema que vai receber os dez módulos.

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

from datetime import datetime

from .. import migracoes, pglocal

# Manopla de redirecionamento, no lugar do antigo `DB_PATH`: o teste faz
# `monkeypatch.setattr(reg, "ESQUEMA", <schema do teste>)` e o módulo inteiro
# passa a escrever lá.
ESQUEMA: str | None = None


def init_db(esquema: str | None = None) -> None:
    """O DDL saiu daqui e virou `sql/cortex/0006_antecipacoes.sql`.

    No SQLite, `_conn()` rodava o schema E três `ALTER TABLE` condicionais a
    cada conexão, porque `CREATE TABLE IF NOT EXISTS` não altera tabela que já
    existe. Era o remendo que a migration numerada substitui.
    """
    migracoes.aplicar(esquema or ESQUEMA)


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

    Tudo numa transação só: no SQLite o `isolation_level=None` deixava cada
    statement por conta própria, e uma falha no meio podia deixar o envio
    gravado sem os títulos — posição zerada com cara de posição.
    """
    imp = impressao(dados) if dados is not None else None
    init_db()
    with pglocal.get_conn(ESQUEMA) as conn:
        with conn.cursor() as cur:
            if imp:
                cur.execute(
                    "SELECT id FROM ant_envios WHERE impressao=%s AND portal=%s"
                    " ORDER BY id DESC LIMIT 1", (imp, lido["portal"]))
                ja = cur.fetchone()
                if ja:
                    # marca que foi reenviado agora, sem duplicar a linha
                    cur.execute("UPDATE ant_envios SET ts=%s WHERE id=%s",
                                (_agora(), ja["id"]))
                    return int(ja["id"]), True

            cur.execute(
                "INSERT INTO ant_envios (ts,usuario,arquivo,portal,portal_rotulo,"
                "titulos,valor_nominal,valor_saldo,total_declarado,divergencia,"
                "rejeitadas,impressao,vigente)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING id",
                (_agora(), usuario, lido["arquivo"], lido["portal"],
                 lido["portal_rotulo"], resumo["titulos"], resumo["valor_nominal"],
                 resumo["valor_saldo"], lido["total_declarado"], lido["divergencia"],
                 len(lido["rejeitadas"]), imp))
            envio_id = int(cur.fetchone()["id"])

            # o arquivo novo é a posição atual DESTE portal; o anterior sai de cena
            cur.execute("DELETE FROM ant_titulos WHERE envio_id IN"
                        " (SELECT id FROM ant_envios WHERE portal=%s AND id<>%s)",
                        (lido["portal"], envio_id))
            cur.execute("UPDATE ant_envios SET vigente=0 WHERE portal=%s AND id<>%s",
                        (lido["portal"], envio_id))
            cur.executemany(
                "INSERT INTO ant_titulos (envio_id,titulo,documento,emissao,"
                "vencimento,valor_nominal,valor_saldo,antecipavel,situacao,"
                "cnpj_cedente,nome_cedente,cnpj_sacado,nome_sacado,chave,id_portal)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(envio_id, t["titulo"], t["documento"],
                  t["emissao"].isoformat() if t["emissao"] else None,
                  t["vencimento"].isoformat(), t["valor_nominal"], t["valor_saldo"],
                  None if t["antecipavel"] is None else int(t["antecipavel"]),
                  t["situacao"], t["cnpj_cedente"], t["nome_cedente"],
                  t["cnpj_sacado"], t["nome_sacado"], t["chave"], t["id_portal"])
                 for t in lido["titulos"]])

            # Sacado do arquivo entra como elegível — se o cliente exporta
            # planilha de antecipação, existe convênio. NÃO sobrescreve
            # `elegivel` de quem já está lá: um sacado desligado à mão
            # continuaria voltando a cada arquivo novo, e a decisão manual tem
            # de ganhar da automática.
            for s in resumo["sacados"]:
                cur.execute(
                    "INSERT INTO ant_sacados"
                    " (cnpj,nome,portal,elegivel,origem,atualizado_em)"
                    " VALUES (%s,%s,%s,1,'arquivo',%s)"
                    " ON CONFLICT(cnpj) DO UPDATE SET nome=excluded.nome,"
                    " portal=excluded.portal, atualizado_em=excluded.atualizado_em",
                    (s["cnpj"], s["nome"], lido["portal"], _agora()))
    return envio_id, False


def marcar_origem(envio_id: int, origem: str) -> None:
    """Diz se a posicao veio de planilha ou de API. Chamado logo depois de
    gravar; separado de `gravar_envio` para nao mudar a assinatura que o
    caminho de planilha ja usa."""
    pglocal.executar(
        "UPDATE ant_envios SET origem=%s WHERE id=%s",
        (origem if origem in ("planilha", "api") else "planilha", envio_id),
        esquema=ESQUEMA)


def _vazio_se_sem_tabela(fn, padrao):
    """Instalação que nunca importou planilha não tem as tabelas — é lista
    vazia, não falha. Erro de CONEXÃO sobe (pglocal.sem_tabela)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return padrao
        raise


def posicao_atual() -> list[dict]:
    """Um envio VIGENTE por portal — a posição de cada cliente hoje.

    `ultimo_envio()` devolvia o mais recente de todos, o que bastava enquanto
    só existia a Maxion. Com Tupy e Adient no convênio, importar o arquivo de
    um faria os outros dois SUMIREM da tela — o dado continuaria no banco e o
    painel mostraria uma fração da posição, sem avisar.
    """
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT * FROM ant_envios WHERE vigente=1 ORDER BY valor_saldo DESC",
        esquema=ESQUEMA), [])


def titulos_vigentes() -> list[dict]:
    """Títulos de TODOS os portais vigentes, somados numa lista só."""
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT t.* FROM ant_titulos t JOIN ant_envios e ON e.id=t.envio_id"
        " WHERE e.vigente=1 ORDER BY t.valor_saldo DESC", esquema=ESQUEMA), [])


def envios(limite: int = 30) -> list[dict]:
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT * FROM ant_envios ORDER BY id DESC LIMIT %s", (limite,),
        esquema=ESQUEMA), [])


def ultimo_envio(portal: str | None = None) -> dict | None:
    sql = "SELECT * FROM ant_envios"
    params: tuple | None = None
    if portal:
        sql += " WHERE portal=%s"
        params = (portal,)
    sql += " ORDER BY id DESC LIMIT 1"
    return _vazio_se_sem_tabela(
        lambda: pglocal.um(sql, params, esquema=ESQUEMA), None)


def titulos_do_envio(envio_id: int) -> list[dict]:
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT * FROM ant_titulos WHERE envio_id=%s ORDER BY valor_saldo DESC",
        (envio_id,), esquema=ESQUEMA), [])


def apagar_envio(envio_id: int) -> None:
    with pglocal.get_conn(ESQUEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ant_titulos WHERE envio_id=%s", (envio_id,))
            cur.execute("DELETE FROM ant_envios WHERE id=%s", (envio_id,))


def sacados(so_elegiveis: bool = False) -> list[dict]:
    sql = "SELECT * FROM ant_sacados"
    if so_elegiveis:
        sql += " WHERE elegivel=1"
    sql += " ORDER BY elegivel DESC, nome"
    return _vazio_se_sem_tabela(
        lambda: pglocal.query(sql, esquema=ESQUEMA), [])


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
    init_db()
    with pglocal.get_conn(ESQUEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ant_sacados"
                " (cnpj,nome,portal,elegivel,origem,atualizado_em,observacao)"
                " VALUES (%s,%s,%s,%s,'manual',%s,%s)"
                " ON CONFLICT(cnpj) DO UPDATE SET"
                " nome=CASE WHEN excluded.nome<>'' THEN excluded.nome"
                "           ELSE ant_sacados.nome END,"
                " portal=CASE WHEN excluded.portal<>'' THEN excluded.portal"
                "             ELSE ant_sacados.portal END,"
                " elegivel=excluded.elegivel, origem='manual',"
                " atualizado_em=excluded.atualizado_em,"
                " observacao=excluded.observacao",
                (cnpj, nome, portal, int(elegivel), _agora(), observacao))
            cur.execute("SELECT * FROM ant_sacados WHERE cnpj=%s", (cnpj,))
            return dict(cur.fetchone())


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
    linhas = _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT t.cnpj_sacado, t.documento FROM ant_titulos t"
        " JOIN ant_envios e ON e.id = t.envio_id"
        " WHERE e.vigente=1 AND t.documento <> ''"
        "   AND (t.antecipavel IS NULL OR t.antecipavel = 1)",
        esquema=ESQUEMA), [])
    return {(r["cnpj_sacado"][:8], r["documento"]) for r in linhas
            if r["cnpj_sacado"]}


def portais_com_planilha() -> set[str]:
    """Raízes de CNPJ que TÊM planilha vigente importada.

    Separa "cliente com convênio mas sem planilha" (falta pedir o arquivo) de
    "cliente sem convênio" (falta negociar) — são pendências diferentes, com
    donos diferentes.
    """
    linhas = _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT DISTINCT t.cnpj_sacado FROM ant_titulos t"
        " JOIN ant_envios e ON e.id = t.envio_id WHERE e.vigente=1",
        esquema=ESQUEMA), [])
    return {r["cnpj_sacado"][:8] for r in linhas if r["cnpj_sacado"]}
