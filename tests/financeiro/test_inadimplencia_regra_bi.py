# -*- coding: utf-8 -*-
"""A inadimplência é a do BI de Inadimplência do Avacorp: valor, faixas e grupo.

O SQL DE VERDADE, num banco de dublê. As consultas de `api/queries.py` e de
`api/financeiro/inadimplencia.py` rodam num schema de teste do PostgreSQL
local, com as tabelas do ERP recriadas com os TIPOS do ERP (lidos do
`information_schema` em 14/09/2026 — inclusive as colunas que
`fatura_composicao` repete de `fatura`, para que coluna sem prefixo quebre aqui
como quebraria lá). Guard de texto aprovaria uma consulta que soma errado;
aqui quem responde é o banco.

Nomes, CNPJs e valores são de mentira — o repositório é público.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

import pytest

from api import db, pglocal, queries
from api.antecipacoes import conciliacao, elegiveis
from api.financeiro import inadimplencia as fi

RAIZ = Path(__file__).resolve().parents[2]

DDL = """
CREATE TABLE fatura (
  grupo integer, empresa integer, filial integer, unidade integer, sequencia integer,
  cliente varchar, composicao integer, dtcancelamento date, dtpagamento date,
  dtprevisaopagamento date, dtvencimento date, dtemissao timestamp,
  dtemissaodocumentoorigem timestamp,
  valorsaldoreceber numeric, valortitulo numeric);
CREATE TABLE fatura_composicao (
  grupo integer, empresa integer, filial integer, unidade integer, sequencia integer,
  cliente varchar, dtemissao date, dtpagamento date, dtvencimento date,
  valorsaldoreceber numeric, valorpendentecnpjcliente numeric, valortitulo numeric,
  tipodocumentoorigem integer, grupodocumentoorigem integer,
  empresadocumentoorigem integer, filialdocumentoorigem integer,
  unidadedocumentoorigem integer, diferenciadornumerodocumentoorigem integer,
  seriedocumentoorigem integer, numerosequenciadocumentoorigem integer);
CREATE TABLE conhecimento (
  grupo integer, empresa integer, filial integer, unidade integer,
  diferenciadornumero integer, serie integer, numero integer, situacaocte integer);
CREATE TABLE cadastro (codigo varchar, nomefantasia varchar, razaosocial varchar);
-- o KPI_SQL também lê o a pagar; aqui ele fica vazio
CREATE TABLE contaapagar (
  filial integer, cnpjcpfcodigo varchar, valorpendente numeric, dtvencimento date);
CREATE TABLE agrupamentocliente (
  grupo integer, empresa integer, codigo integer, descricao varchar);
CREATE TABLE agrupamentocliente_cnpjcpfcodigo (
  grupo integer, empresa integer, codigo integer, cnpjcpfcodigo varchar,
  vinculo integer, dtinc timestamp, dtalt timestamp);
"""

# Dois CNPJs no mesmo grupo, um cliente sem grupo e um CNPJ que o cadastro
# põe em DOIS grupos (o caso real que o `DISTINCT ON` existe para segurar).
NORTE, SUL = "11222333000181", "11222333000262"
AVULSO = "44555666000172"
DOBRADO = "77888999000155"
CNPJS = (NORTE, SUL, AVULSO, DOBRADO)


def _popular(cur):
    cur.executemany("INSERT INTO cadastro VALUES (%s, %s, %s)", [
        (NORTE, "FILIAL NORTE FICTICIA", "FICTICIA NORTE LTDA"),
        (SUL, "FILIAL SUL FICTICIA", "FICTICIA SUL LTDA"),
        (AVULSO, "INDUSTRIA DE MENTIRA SA", "INDUSTRIA DE MENTIRA SA"),
        (DOBRADO, "COMERCIO DUBLE ME", "COMERCIO DUBLE ME")])
    cur.executemany("INSERT INTO agrupamentocliente VALUES (1, 1, %s, %s)",
                    [(7, "GRUPO FICTICIO"), (8, "OUTRO GRUPO")])
    cur.executemany(
        "INSERT INTO agrupamentocliente_cnpjcpfcodigo VALUES (1, 1, %s, %s, 1, %s, NULL)",
        [(7, NORTE, "2025-01-01"), (7, SUL, "2025-01-01"),
         # o vínculo MAIS NOVO vence — e o título não pode aparecer nos dois
         (7, DOBRADO, "2025-01-01"), (8, DOBRADO, "2025-06-01")])

    seq = iter(range(1, 1000))

    def doc(cliente, dias, pend, saldo=None, *, pago=False, composicao=1):
        """Uma fatura com uma composição, vencida há `dias` (negativo = a vencer)."""
        s = next(seq)
        cur.execute("""
            INSERT INTO fatura (grupo, empresa, filial, unidade, sequencia, cliente,
                                composicao, dtpagamento, dtvencimento, dtemissao,
                                valorsaldoreceber, valortitulo)
            VALUES (1, 1, 1, 1, %(s)s, %(c)s, %(comp)s,
                    CASE WHEN %(pago)s THEN current_date END,
                    current_date - %(d)s, current_date - %(d)s - 30,
                    %(saldo)s, %(pend)s)""",
                    {"s": s, "c": cliente, "comp": composicao, "pago": pago, "d": dias,
                     "saldo": pend if saldo is None else saldo, "pend": pend})
        cur.execute("""
            INSERT INTO fatura_composicao (grupo, empresa, filial, unidade, sequencia,
                                           cliente, valorpendentecnpjcliente, valortitulo,
                                           tipodocumentoorigem, numerosequenciadocumentoorigem)
            VALUES (1, 1, 1, 1, %(s)s, %(c)s, %(pend)s, %(pend)s, 10, %(s)s)""",
                    {"s": s, "c": cliente, "pend": pend})

    # GRUPO FICTICIO: dois títulos IGUAIS (mesmo valor, mesmos dias — os que a
    # DISTINCT do BI funde num só) e uma fatura paga em 70% com a composição
    # cheia (o que o pendente sozinho conta inteiro).
    doc(NORTE, 10, 100.0)
    doc(NORTE, 10, 100.0)
    doc(SUL, 20, 1000.0, 300.0)
    # os cortes das faixas, dos dois lados de cada um
    for dias, pend in ((15, 50.0), (16, 60.0), (30, 70.0), (31, 80.0), (90, 90.0), (91, 110.0)):
        doc(AVULSO, dias, pend)
    doc(DOBRADO, 5, 40.0)
    # o que NÃO é vencido oficial
    doc(NORTE, -3, 500.0)                    # a vencer
    doc(SUL, -2, 200.0)                      # a vencer, a outra empresa do grupo
    doc(SUL, 12, 999.0, pago=True)           # pago
    doc(AVULSO, 40, 777.0, composicao=2)     # pendente de faturamento


@pytest.fixture
def ava(esquema_pg, monkeypatch):
    with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        _popular(cur)

    @contextmanager
    def conexao_dubla():
        with pglocal.get_conn(esquema_pg) as c:
            yield c
    monkeypatch.setattr(db, "get_conn", conexao_dubla)
    queries._RESP_CACHE.clear()
    yield esquema_pg
    queries._RESP_CACHE.clear()


def _sql(ava, sql, params):
    with pglocal.get_conn(ava) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


P_REC = {"filial": None, "data_ref": None, "venc_de": None, "venc_ate": None,
         "clientes": None, "fornecedores": None, "horizonte": 12}


# ═══════════════════════════════════════════════════════════ o valor ═════

def test_o_valor_e_o_MENOR_entre_o_pendente_e_o_saldo_da_fatura(ava):
    """A fatura paga em 70% vale os 30% que faltam, não o pendente cheio da
    composição — era a única divergência contra o BI, conferida em 14/09/2026."""
    kpi = _sql(ava, queries.KPI_SQL, P_REC)[0]
    assert kpi["receber_vencido"] == pytest.approx(1000.0)
    assert kpi["receber_aberto"] == pytest.approx(1700.0)
    assert kpi["receber_pendente_fatur"] == pytest.approx(777.0), \
        "o pendente de faturamento segue à parte, pelo pendente"
    grupo = [c for c in queries.get_cobranca(None)["clientes"]
             if c["cliente"] == "GRUPO FICTICIO"][0]
    assert grupo["vencido"] == pytest.approx(500.0)
    assert grupo["de_16_30"] == pytest.approx(300.0)


# ══════════════════════════════════════════════════════════ as faixas ════

def test_as_faixas_sao_as_do_BI_e_cada_documento_conta(ava):
    """O gráfico de faixas do BI não soma o próprio total: a `DISTINCT` dele
    funde títulos iguais. Aqui os dois títulos de 100 contam, e as faixas
    somam o vencido."""
    aging = {r["faixa"]: r for r in _sql(ava, queries.AGING_AR_SQL, P_REC)}
    assert {k: (r["qtd"], round(r["valor"], 2)) for k, r in aging.items()} == {
        "1_a_vencer": (2, 700.0),
        "2_vencido_ate_15": (4, 290.0),      # 100 + 100 + 50 (15 dias) + 40
        "3_vencido_16_30": (3, 430.0),       # 300 + 60 (16 dias) + 70 (30 dias)
        "4_vencido_31_90": (2, 170.0),       # 80 (31 dias) + 90 (90 dias)
        "5_vencido_mais_90": (1, 110.0),     # 91 dias
    }
    vencido = sum(r["valor"] for k, r in aging.items() if k != "1_a_vencer")
    assert vencido == pytest.approx(_sql(ava, queries.KPI_SQL, P_REC)[0]["receber_vencido"])


def test_a_regua_corta_as_faixas_nos_MESMOS_dias_do_aging(ava):
    avulso = [c for c in queries.get_cobranca(None)["clientes"]
              if c["cliente"] == "INDUSTRIA DE MENTIRA SA"][0]
    assert (avulso["ate_15"], avulso["de_16_30"], avulso["de_31_90"], avulso["mais_90"]) == \
        pytest.approx((50.0, 130.0, 170.0, 110.0))
    assert avulso["vencido"] == pytest.approx(460.0)


# ═════════════════════════════════════════════════════════ o agrupamento ═

def test_a_regua_e_por_GRUPO_e_nao_dobra_o_CNPJ_que_esta_em_dois(ava):
    r = queries.get_cobranca(None)
    linhas = {c["cliente"]: c for c in r["clientes"]}
    assert list(linhas) == ["GRUPO FICTICIO", "INDUSTRIA DE MENTIRA SA", "OUTRO GRUPO"], \
        "do maior vencido para o menor"
    g = linhas["GRUPO FICTICIO"]
    assert (g["grupo"], g["empresas"], g["titulos"], g["doc"]) == (True, 2, 3, None)
    assert {t["empresa"] for t in g["titulos_lista"]} == {"FILIAL NORTE FICTICIA",
                                                           "FILIAL SUL FICTICIA"}
    outro = linhas["OUTRO GRUPO"]
    assert (outro["grupo"], outro["titulos"], outro["vencido"]) == (True, 1, 40.0), \
        "o CNPJ em dois grupos fica no vínculo mais novo, e uma vez só"
    assert sum(c["titulos"] for c in r["clientes"]) == 10
    assert r["total_vencido_top"] == pytest.approx(1000.0)
    avulso = linhas["INDUSTRIA DE MENTIRA SA"]
    assert avulso["grupo"] is False and avulso["empresas"] == 1
    assert avulso["doc"] and avulso["doc"] != AVULSO, "o documento sai MASCARADO"
    assert r["pendente_faturamento"] == pytest.approx(777.0)


def test_o_payload_da_regua_nao_leva_CNPJ_nem_a_chave_do_grupo(ava):
    bruto = json.dumps(queries.get_cobranca(None), default=str)
    for cnpj in CNPJS:
        assert cnpj not in bruto, cnpj
    assert '"chave' not in bruto and '"codigo' not in bruto


def test_o_filtro_de_cliente_casa_o_nome_do_GRUPO_e_o_da_empresa(ava):
    grupo = queries.get_cobranca(None, cliente="grupo fic")["clientes"]
    assert [(c["cliente"], c["vencido"]) for c in grupo] == [("GRUPO FICTICIO", 500.0)]
    norte = queries.get_cobranca(None, cliente="norte")["clientes"]
    assert [(c["cliente"], c["vencido"], c["empresas"]) for c in norte] == \
        [("GRUPO FICTICIO", 200.0, 1)]
    assert {t["empresa"] for t in norte[0]["titulos_lista"]} == {"FILIAL NORTE FICTICIA"}, \
        "os títulos seguem o MESMO filtro que a linha"


def test_as_listas_do_email_saem_por_GRUPO(ava):
    """As duas empresas do grupo numa linha só, nas duas listas. A janela
    aberta ao máximo põe todo o vencido em "entraram em atraso" — o teste não
    depende de em que dia da semana roda."""
    novos = _sql(ava, fi.NOVOS_SQL, {"filial": None, "desde": "2000-01-01"})
    assert [(r["cliente"], r["titulos"], round(r["valor"], 2)) for r in novos] == [
        ("GRUPO FICTICIO", 3, 500.0), ("INDUSTRIA DE MENTIRA SA", 6, 460.0),
        ("OUTRO GRUPO", 1, 40.0)]
    avencer = _sql(ava, fi.AVENCER_SQL, {"filial": None, "clientes": None, "ate": "2100-01-01"})
    assert [(r["cliente"], r["titulos"], round(r["valor"], 2)) for r in avencer] == [
        ("GRUPO FICTICIO", 2, 700.0)]


def test_o_email_soma_as_faixas_e_conta_clientes_por_grupo(ava):
    r = fi.resumo()
    assert r["vencido"] == pytest.approx(1000.0)
    assert sum(f["valor"] for f in r["faixas"]) == pytest.approx(r["vencido"]), \
        "as faixas somam o vencido"
    assert [f["faixa"] for f in r["faixas"]] == [k for k, _ in fi.FAIXAS]
    assert r["clientes"] == 3, "clientes são GRUPOS, como nas listas"
    assert [d["cliente"] for d in r["devedores"]] == \
        ["GRUPO FICTICIO", "INDUSTRIA DE MENTIRA SA", "OUTRO GRUPO"]
    assert r["a_vencer"]["itens"][0]["cliente"] == "GRUPO FICTICIO"
    bruto = json.dumps(fi.resumo_copiloto(), default=str)
    for cnpj in CNPJS:
        assert cnpj not in bruto


# ═════════════════════════════════════ o fluxo de caixa e a antecipação ══

def test_o_ATRASADO_do_fluxo_de_caixa_e_o_vencido_oficial(ava):
    """O balde 'atrasado' do Fluxo de Caixa — que a Visão Geral e a TV da
    Diretoria também mostram — é o MESMO número do "A receber vencido": sem o
    pendente de faturamento, sem o título pago, pelo valor do BI, cortado na
    data de referência. Até 15/09/2026 ele somava o saldo de toda fatura
    vencida antes do dia 1º do mês e dizia ~17 vezes o vencido oficial."""
    fluxo = _sql(ava, queries.FLUXO_SQL, P_REC)
    kpi = _sql(ava, queries.KPI_SQL, P_REC)[0]
    assert fluxo[0]["periodo"] == "atrasado"
    assert kpi["receber_vencido"] == pytest.approx(1000.0)
    assert fluxo[0]["receber"] == pytest.approx(kpi["receber_vencido"])
    assert sum(r["receber"] for r in fluxo) == pytest.approx(kpi["receber_aberto"]), \
        "o a vencer segue no fluxo, pelo mesmo valor e sem o pendente de faturamento"


def test_a_antecipacao_le_o_MESMO_valor(ava):
    """Os elegíveis (e o plano de antecipação, que reusa a consulta) e a
    conferência com o portal: a fatura paga em 70% vale os 30% que faltam."""
    esperado = [100.0, 100.0, 200.0, 300.0, 500.0]   # o grupo NORTE/SUL, em aberto
    eleg = _sql(ava, elegiveis.ERP_SQL, {"raizes": [NORTE[:8]]})
    assert sorted(round(r["valor"], 2) for r in eleg) == esperado
    conc = _sql(ava, conciliacao.CONC_SQL, {"docs": [r["documento"] for r in eleg]})
    assert sorted(round(r["valor"], 2) for r in conc) == esperado


# ═══════════════════════════════════════════════ guards sem banco ════════

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


# O pendente de FATURAMENTO (composição 2) mora dentro do KPI_SQL e não é a
# regra oficial: ele segue pelo pendente, e é a única soma crua permitida.
_PEND_FATUR = re.compile(
    r"coalesce\(sum\(fc\.valorpendentecnpjcliente\),0\)::float8 FROM fatura f JOIN "
    r"fatura_composicao fc USING \(grupo,empresa,filial,unidade,sequencia\) WHERE "
    r"[^()]*?f\.composicao=2")


def test_nenhuma_consulta_da_regra_oficial_soma_o_pendente_CRU():
    """Toda constante SQL que lê o faturado (composição 1) pela composição
    vale `_VAL_OF`; o pendente cru só aparece no filtro `> 0`. A varredura sai
    dos MÓDULOS, não de uma lista escrita à mão — consulta nova entra sozinha."""
    achadas, cruas = [], []
    for mod in (queries, fi, elegiveis, conciliacao):
        for nome, v in vars(mod).items():
            if not (isinstance(v, str) and "fatura_composicao fc" in v
                    and re.search(r"composicao ?= ?1\b", v)):
                continue
            achadas.append(nome)
            s = _norm(v)
            if nome == "KPI_SQL":
                s, n = _PEND_FATUR.subn("", s)
                assert n == 1, "o pendente de faturamento saiu do KPI_SQL — conferir a exceção"
            s = s.replace(queries._VAL_OF, "")
            s = re.sub(r"fc\.valorpendentecnpjcliente ?> ?0", "", s)
            if "valorpendentecnpjcliente" in s:
                cruas.append(f"{mod.__name__}.{nome}")
    assert {"KPI_SQL", "AGING_AR_SQL", "VENC_AR_SQL", "DRILL_AR_SQL", "COB_CLI_SQL",
            "COB_TIT_SQL", "CLIF_RECEB_SQL", "FLUXCON_REC_SQL", "ANTEC_REC_TIT_SQL",
            "TOTAIS_SQL", "ABERTO_SQL", "NOVOS_SQL", "AVENCER_SQL", "SERIE_SQL",
            "FLUXO_SQL", "ERP_SQL", "CONC_SQL"} <= set(achadas), \
        "a varredura não achou as consultas que devia — ela está olhando o lugar certo?"
    assert not cruas, f"somam o pendente cru, e não o valor do BI: {cruas}"


def test_as_faixas_tem_as_MESMAS_chaves_no_SQL_no_email_e_na_tela():
    """Três sotaques da mesma régua: o CASE do SQL, a lista do e-mail e o
    mapa da tela. Chave que diverge some calada — a faixa vira zero."""
    sql = re.findall(r"'(\d_[a-z0-9_]+)'", queries._FAIXA_OF)
    assert sql == ["1_a_vencer", "2_vencido_ate_15", "3_vencido_16_30",
                   "4_vencido_31_90", "5_vencido_mais_90"]
    assert [k for k, _ in fi.FAIXAS] == sql[1:]
    html = (RAIZ / "api" / "static" / "index.html").read_text(encoding="utf-8")
    bloco = html.split("const FAIXAS_AR = {", 1)[1].split("};", 1)[0]
    assert re.findall(r"'(\d_[a-z0-9_]+)'", bloco) == sql
