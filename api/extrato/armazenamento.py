"""Persistência local do extrato bancário — PostgreSQL (schema `cortex`).

Sexto store migrado do SQLite (27/08/2026 — ver `docs/MIGRACAO_POSTGRES.md`).
O `data/extrato.db` continua no disco até a fase seguinte fechar.

O ERP AVA é réplica somente-leitura, então o extrato importado é dado nosso.

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

from .. import migracoes, pglocal

# Manopla de redirecionamento, no lugar do antigo `DB_PATH`. Aqui ela tem um
# papel a mais: `servico.painel(..., path=arm.DB_PATH)` usava o valor como
# ARGUMENTO PADRÃO, avaliado no import — monkeypatch depois disso não teria
# efeito nenhum. Os padrões viraram `None`, e o None cai aqui.
ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    """O DDL mora em `sql/cortex/0007_extrato.sql`.

    SAIU DAQUI, e com ele duas coisas: os `ALTER TABLE` condicionais (que a
    migration numerada substitui) e `_remigra_chaves`, a rotina que recalculava
    chaves no formato antigo `fitid:<id>`. Ela rodava a cada `init_db` e não
    tem mais o que fazer: a base migrada foi conferida com zero chaves nesse
    formato, e a partir daqui só existe o formato novo. Carregar código morto
    que mexe em chave de dedup é convite a acidente.
    """
    migracoes.aplicar(_esq(esquema))


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


def obter_ou_criar_conta(esquema: str | None, ident: str, rotulo: str) -> int:
    init_db(esquema)
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM ext_conta WHERE ident=%s", (ident,))
            row = cur.fetchone()
            if row:
                return int(row["id"])
            cur.execute("INSERT INTO ext_conta(ident, rotulo) VALUES(%s,%s)"
                        " RETURNING id", (ident, rotulo))
            return int(cur.fetchone()["id"])


def mapear_conta(esquema: str | None, conta_id: int, erp_banco: int,
                 erp_agencia: str, erp_conta: str, rotulo: str | None = None) -> None:
    if rotulo:
        pglocal.executar(
            "UPDATE ext_conta SET erp_banco=%s, erp_agencia=%s, erp_conta=%s,"
            " rotulo=%s WHERE id=%s",
            (erp_banco, erp_agencia, erp_conta, rotulo, conta_id), esquema=_esq(esquema))
    else:
        pglocal.executar(
            "UPDATE ext_conta SET erp_banco=%s, erp_agencia=%s, erp_conta=%s"
            " WHERE id=%s",
            (erp_banco, erp_agencia, erp_conta, conta_id), esquema=_esq(esquema))


def salvar_mapa_csv(esquema: str | None, conta_id: int, mapa: dict) -> None:
    pglocal.executar("UPDATE ext_conta SET mapa_csv=%s WHERE id=%s",
                     (json.dumps(mapa, ensure_ascii=False), conta_id),
                     esquema=_esq(esquema))


def _conta_dict(row: dict) -> dict:
    d = dict(row)
    d["mapa_csv"] = json.loads(d["mapa_csv"]) if d.get("mapa_csv") else None
    return d


def _vazio_se_sem_tabela(fn, padrao):
    """Instalação que nunca importou extrato não tem as tabelas — é lista
    vazia, não falha. Erro de CONEXÃO sobe."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return padrao
        raise


def conta_por_ident(esquema: str | None, ident: str) -> dict | None:
    row = _vazio_se_sem_tabela(lambda: pglocal.um(
        "SELECT * FROM ext_conta WHERE ident=%s", (ident,),
        esquema=_esq(esquema)), None)
    return _conta_dict(row) if row else None


def listar_contas(esquema: str | None = None) -> list[dict]:
    rows = _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT * FROM ext_conta ORDER BY rotulo", esquema=_esq(esquema)), [])
    return [_conta_dict(r) for r in rows]


def gravar_lancamentos(esquema: str | None, conta_id: int, itens: list[dict],
                       arquivo: str, formato: str, ignoradas: int = 0) -> dict:
    datas = sorted(i["dt"] for i in itens) or [None]
    novas = dupl = 0
    init_db(esquema)
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ext_importacao(conta_id, arquivo, formato, dt_de,"
                " dt_ate, ignoradas) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                (conta_id, arquivo, formato, datas[0], datas[-1], ignoradas))
            imp_id = int(cur.fetchone()["id"])
            vistos: dict[tuple[str, str, str, str], int] = {}
            for item in itens:
                base = _identidade(item)
                vistos[base] = vistos.get(base, 0) + 1
                chave = _chave(item, vistos[base])
                valor = float(item["valor"])
                tipo = "C" if valor >= 0 else "D"  # sinal manda, nunca o campo de entrada
                # `ON CONFLICT DO NOTHING` é o `INSERT OR IGNORE`: o rowcount
                # volta 0 quando a linha já existia, e é assim que se conta
                # novas × duplicadas sem uma segunda consulta
                cur.execute(
                    "INSERT INTO ext_lancamento"
                    "(conta_id, importacao_id, dt, valor, tipo, historico,"
                    " numerodoc, fitid, chave)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT (conta_id, chave) DO NOTHING",
                    (conta_id, imp_id, item["dt"], valor, tipo,
                     item.get("historico") or "", item.get("numerodoc") or "",
                     item.get("fitid"), chave))
                if cur.rowcount:
                    novas += 1
                else:
                    dupl += 1
            cur.execute("UPDATE ext_importacao SET novas=%s, duplicadas=%s"
                        " WHERE id=%s", (novas, dupl, imp_id))
            # importação que não trouxe nada novo não fica na trilha (poluiria a
            # lista de uploads com registros vazios a cada re-upload)
            if novas == 0:
                cur.execute("DELETE FROM ext_importacao WHERE id=%s", (imp_id,))
    return {"importacao_id": imp_id if novas else 0, "novas": novas, "duplicadas": dupl}


def gravar_saldo_extrato(esquema: str | None, conta_id: int, dt: str,
                         saldo: float, importacao_id: int | None = None,
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
    pglocal.executar(
            "INSERT INTO ext_saldo(conta_id, dt, saldo, importacao_id, origem) "
            "VALUES(%s,%s,%s,%s,%s) "
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
            (conta_id, dt, float(saldo), importacao_id, origem),
            esquema=_esq(esquema))


def saldos_extrato(esquema: str | None, conta_id: int) -> list[dict]:
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT dt, saldo FROM ext_saldo WHERE conta_id=%s ORDER BY dt",
        (conta_id,), esquema=_esq(esquema)), [])


def lancamentos(esquema: str | None, conta_id: int, dt_de: str,
                dt_ate: str) -> list[dict]:
    return _vazio_se_sem_tabela(lambda: pglocal.query(
            # o `id` viaja junto porque a conciliacao linha a linha precisa de uma
            # referencia ESTAVEL para o par que ela montou - dt+valor+historico nao
            # serve, que e justamente o caso de dois lancamentos gemeos no mesmo dia
        "SELECT id, dt, valor, tipo, historico, numerodoc FROM ext_lancamento"
        " WHERE conta_id=%s AND dt BETWEEN %s AND %s ORDER BY dt, id",
        (conta_id, dt_de, dt_ate), esquema=_esq(esquema)), [])


def listar_importacoes(esquema: str | None = None, limite: int = 20) -> list[dict]:
    """As `limite` importações mais recentes, para a TABELA DA TELA. NUNCA usar
    isto para decidir o último dia coberto por conta (regra de negócio) - com
    8 contas subindo 1 extrato/dia, 20 linhas enchem em 2,5 dias e uma conta de
    upload menos frequente some da lista sem ter ficado desatualizada de
    verdade. Para isso existe `ultimo_dt_por_conta`, sem limite."""
    return _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT i.*, c.rotulo AS conta_rotulo FROM ext_importacao i"
        " JOIN ext_conta c ON c.id=i.conta_id ORDER BY i.id DESC LIMIT %s",
        (limite,), esquema=_esq(esquema)), [])


def ultimo_dt_por_conta(esquema: str | None = None) -> dict[int, str]:
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
    rows = _vazio_se_sem_tabela(lambda: pglocal.query(
        "SELECT conta_id, max(dt_ate) AS dt_ate FROM ext_importacao"
        " WHERE dt_ate IS NOT NULL GROUP BY conta_id", esquema=_esq(esquema)), [])
    return {int(r["conta_id"]): r["dt_ate"] for r in rows}


def apagar_importacao(esquema: str | None, importacao_id: int) -> int:
    with pglocal.get_conn(_esq(esquema)) as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM ext_lancamento WHERE importacao_id=%s",
                      (importacao_id,))
            n = c.rowcount
            # remove só a(s) âncora(s) de saldo QUE PERTENCEM a esta
            # importação — âncoras de outras importações ou anteriores à
            # migração (`importacao_id IS NULL`) nunca são tocadas (d1).
            c.execute("DELETE FROM ext_saldo WHERE importacao_id=%s",
                      (importacao_id,))
            c.execute("DELETE FROM ext_importacao WHERE id=%s", (importacao_id,))
    return int(n)
