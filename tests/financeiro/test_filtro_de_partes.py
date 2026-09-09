# -*- coding: utf-8 -*-
"""O filtro por CLIENTE (a receber) e por CREDOR (a pagar) recorta a tela TODA.

O QUE ESTA GUARDA PROTEGE
=========================
Contas a Receber e Contas a Pagar dividem UMA resposta
(`/api/financeiro/overview`) com o Fluxo de Caixa: os quatro indicadores, o
aging, os vencimentos por mês, o top-15 e os alertas saem todos dela. Um filtro
que entrasse em algumas consultas e não em outras produziria a pior versão do
defeito conhecido da casa — não o "campo que aceita valor e não muda nada", mas
o campo que muda METADE da tela: o total do topo contando quem já não está na
tabela de baixo, sem erro nenhum aparecer.

Por isso o teste central não confere uma consulta escolhida a dedo: ele LÊ do
`api/queries.py` quais constantes o `get_overview` executa com o dicionário de
parâmetros compartilhado e cobra o filtro de CADA UMA que toca `fatura` ou
`contaapagar`. Consulta nova entra na varredura sozinha — que é o contrário do
guard de lista escrita à mão, o que já aprovou em silêncio a única violação
viva do `EXISTS`.

A SEGUNDA COISA GUARDADA É PII
==============================
`fatura.cliente` e `contaapagar.cnpjcpfcodigo` guardam o CNPJ/CPF cru — a mesma
coluna que o top-15 masca com `_mask_doc` antes de responder. Se o seletor
mandasse o código, o documento apareceria na barra de endereço, no histórico do
navegador e no log do Cloudflare. A chave que viaja é um digest opaco, e os
testes abaixo provam isso pelo VALOR (nenhum id contém o documento) e pela
ESTRUTURA (o payload não tem a chave `codigo`).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from api import queries

FONTE = Path(__file__).resolve().parents[2] / "api" / "queries.py"


# ==========================================================================
# A varredura: quem o overview executa, e com quais parâmetros
# ==========================================================================
def _executados() -> dict[str, list[str]]:
    """Constantes que `get_overview` passa ao `cur.execute`, separadas por
    terem ou não recebido o dicionário `params` compartilhado.

    Sai do DISCO por `ast`, e não de uma lista escrita aqui: consulta nova
    dentro do `get_overview` entra na cobrança sozinha, e uma que saia some
    junto — que é o que uma lista à mão nunca faz.
    """
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    alvo = next((n for n in ast.walk(arvore)
                 if isinstance(n, ast.FunctionDef) and n.name == "get_overview"), None)
    assert alvo is not None, "get_overview sumiu de api/queries.py — alvo perdido"
    com, sem = [], []
    for no in ast.walk(alvo):
        if not (isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and no.func.attr == "execute"):
            continue
        if not no.args or not isinstance(no.args[0], ast.Name):
            continue                       # f-string do `SELECT current_timestamp`
        nome = no.args[0].id
        segundo = no.args[1] if len(no.args) > 1 else None
        if isinstance(segundo, ast.Name) and segundo.id == "params":
            com.append(nome)
        else:
            sem.append(nome)
    return {"com_params": com, "sem_params": sem}


def test_a_varredura_acha_alguma_coisa():
    """Varredura que não acha nada passa por VACUIDADE. Se a forma do
    `get_overview` mudar e o `ast` parar de casar, é aqui que aparece — e não
    num verde silencioso lá embaixo."""
    achado = _executados()
    assert len(achado["com_params"]) >= 10, achado


@pytest.mark.parametrize("nome", sorted(set(_executados()["com_params"])))
def test_consulta_do_overview_carrega_o_filtro_da_tabela_que_ela_soma(nome):
    """Quem soma `contaapagar` obedece ao filtro de credor; quem soma `fatura`
    obedece ao de cliente. Sem isso o indicador do topo e a tabela de baixo
    passam a falar de universos diferentes na mesma tela."""
    sql = getattr(queries, nome)
    if re.search(r"\bcontaapagar\b", sql):
        assert "%(fornecedores)s" in sql, (
            f"{nome} soma contaapagar e ignora o filtro de credor — o número "
            f"não vai obedecer ao filtro da tela de Contas a Pagar")
    if re.search(r"\bfatura\b", sql):
        assert "%(clientes)s" in sql, (
            f"{nome} soma fatura e ignora o filtro de cliente — o número não "
            f"vai obedecer ao filtro da tela de Contas a Receber")


def test_as_consultas_de_FORA_do_filtro_sao_essas_e_o_motivo_esta_escrito():
    """As exceções são declaradas, e a lista se confere contra o disco.

    DSO e DPO medem PRAZO MÉDIO da empresa (dias entre emissão e liquidação) e
    alimentam só o ciclo de caixa, que vive na tela de Fluxo — onde o filtro de
    parte nem aparece. Recortá-las por cliente devolveria o prazo de três
    sacados apresentado como o da casa.

    FIN_MENSAL_SQL é o custo financeiro do RAZÃO (estrutural 4.2.4): juros e
    tarifas não têm cliente nem credor a que se prender, e ele nem toca as duas
    tabelas.

    As três rodam sem o `params` compartilhado de propósito, e é por isso que a
    varredura acima não as alcança. Se um dia passarem a receber o dicionário,
    este teste quebra e a decisão volta para a mesa em vez de acontecer
    sozinha.
    """
    assert sorted(set(_executados()["sem_params"])) == [
        "DPO_SQL", "DSO_SQL", "FIN_MENSAL_SQL"]
    # e a razão declarada para o FIN_MENSAL se confere contra o SQL:
    for proibido in ("fatura", "contaapagar"):
        assert not re.search(r"\b" + proibido + r"\b", queries.FIN_MENSAL_SQL)


# ==========================================================================
# As consultas são COMPARTILHADAS — quem mais as executa não pode ficar para trás
# ==========================================================================
class _FaltouParametro(AssertionError):
    pass


class _CursorConferente:
    """Faz a conferência que o psycopg faz: todo `%(nome)s` do SQL tem de estar
    no dicionário de parâmetros. Sem banco, e sem depender de o AVA estar de pé.
    """

    _NOMES = re.compile(r"%\((\w+)\)s")

    def __init__(self, faltas):
        self._faltas = faltas

    def execute(self, sql, params=None):
        pedidos = set(self._NOMES.findall(sql))
        dados = set(params or {})
        if pedidos - dados:
            self._faltas.append(sorted(pedidos - dados))

    def fetchone(self):
        return {}

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _faltas_de(fn) -> list:
    faltas: list = []

    class _Conn:
        def cursor(self):
            return _CursorConferente(faltas)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import api.db as _db
    orig = _db.get_conn
    _db.get_conn = lambda *a, **k: _Conn()
    queries._RESP_CACHE.clear()
    try:
        try:
            fn()
        except Exception:
            # o dublê não devolve linhas, então o cálculo morre logo depois —
            # o que interessa já foi coletado nos `execute`
            pass
    finally:
        _db.get_conn = orig
        queries._RESP_CACHE.clear()
    return faltas


def _compartilhadas() -> set[str]:
    """Constantes de `api/queries.py` cujo SQL carrega o filtro de parte."""
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    achadas = {
        n.targets[0].id
        for n in arvore.body
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and isinstance(getattr(queries, n.targets[0].id, None), str)
        and ("%(clientes)s" in getattr(queries, n.targets[0].id)
             or "%(fornecedores)s" in getattr(queries, n.targets[0].id))
    }
    assert achadas, "nenhuma consulta com o filtro de parte — alvo perdido"
    return achadas


def _chamadas_com_dicionario_literal() -> list[tuple[int, str, set[str]]]:
    """Cada `execute(CONSTANTE, {...})` / `query(CONSTANTE, {...})` do módulo,
    com as chaves que o dicionário literal declara.

    Existe porque a varredura EXECUTADA não alcança tudo: o
    `db.query(KPI_SQL, {...})` do Fluxo Consolidado fica no fim de uma função
    longa que o dublê não consegue percorrer, e a falha dele é engolida por um
    `except` — some sem sintoma. Aqui ele é visto pelo texto, que é o que
    sobra quando a execução não chega.
    """
    compart = _compartilhadas()
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    fora = []
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and no.func.attr in ("execute", "query")):
            continue
        if len(no.args) < 2 or not isinstance(no.args[0], ast.Name):
            continue
        if no.args[0].id not in compart or not isinstance(no.args[1], ast.Dict):
            continue
        chaves = set()
        for k, v in zip(no.args[1].keys, no.args[1].values):
            if k is None:                      # `**SEM_PARTES`
                if isinstance(v, ast.Name):
                    chaves |= set(getattr(queries, v.id, {}))
            elif isinstance(k, ast.Constant):
                chaves.add(k.value)
        fora.append((no.lineno, no.args[0].id, chaves))
    return fora


def test_a_varredura_de_dicionarios_literais_acha_alguma_coisa():
    assert _chamadas_com_dicionario_literal(), (
        "nenhum `execute(CONSTANTE, {...})` — a varredura perdeu o alvo e "
        "passaria por vacuidade")


def test_dicionario_literal_de_consulta_compartilhada_traz_as_duas_chaves():
    faltando = [(ln, nome, sorted({"clientes", "fornecedores"} - ch))
                for ln, nome, ch in _chamadas_com_dicionario_literal()
                if not {"clientes", "fornecedores"} <= ch]
    assert not faltando, (
        "api/queries.py executa consulta com filtro de parte sem as chaves "
        "(linha, consulta, o que falta): %s — espalhe `**SEM_PARTES`" % faltando)


def _funcoes_que_usam_as_consultas_compartilhadas() -> list[str]:
    """Funções de `api/queries.py` que mencionam alguma consulta parametrizada
    pelo filtro de parte — LIDAS DO DISCO.

    A lista não pode ser escrita à mão: a Visão Geral e o Fluxo Consolidado
    reusam `KPI_SQL`, `SALDO_SQL`, `RUNRATE_SQL` e `FLUXO_SQL` com dicionários
    PRÓPRIOS, montados longe daqui, e um quinto consumidor apareceria sem
    ninguém lembrar de vir atualizar um `parametrize`.
    """
    compartilhadas = _compartilhadas()
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    usam = []
    for no in arvore.body:
        if not isinstance(no, ast.FunctionDef) or not no.name.startswith("get_"):
            continue
        nomes = {x.id for x in ast.walk(no) if isinstance(x, ast.Name)}
        if nomes & compartilhadas:
            usam.append(no.name)
    return sorted(usam)


# Argumentos mínimos de cada consumidor. É lista à mão, então o teste abaixo a
# confere contra a varredura: consumidor novo reprova a suíte até alguém
# declarar como chamá-lo.
COMO_CHAMAR = {
    "get_overview": (),
    "get_visao_geral": (),
    "get_fluxo_consolidado": ("semana", 30),
}


def test_a_lista_de_consumidores_esta_conferida_contra_o_disco():
    assert _funcoes_que_usam_as_consultas_compartilhadas() == sorted(COMO_CHAMAR)


@pytest.mark.parametrize("nome", sorted(COMO_CHAMAR))
def test_quem_executa_as_consultas_compartilhadas_passa_as_duas_chaves(nome):
    """O filtro é parâmetro NOMEADO: um dicionário próprio sem as duas chaves
    faz o psycopg recusar a consulta inteira. Na Visão Geral isso derruba a
    tela; no Fluxo Consolidado a recusa cai dentro de um `except` e vira
    "recebíveis: não sei", calado. Foi assim que a primeira versão deste filtro
    quebrou as duas — e quem acusou foi o conferidor de números, não um guard."""
    fn = getattr(queries, nome)
    args = COMO_CHAMAR[nome]
    assert _faltas_de(lambda: fn(*args)) == [], (
        f"{nome} executa uma consulta compartilhada sem clientes/fornecedores "
        f"— espalhe `**queries.SEM_PARTES` no dicionário de parâmetros")


def test_o_conferente_de_parametros_acusa_de_verdade():
    """Sem isto os dois testes acima passariam por VACUIDADE no dia em que o
    dublê deixasse de ver os `execute`."""
    faltas: list = []
    _CursorConferente(faltas).execute("SELECT %(a)s, %(b)s", {"a": 1})
    assert faltas == [["b"]]


# ==========================================================================
# O documento não viaja
# ==========================================================================
CNPJ = "61156113000175"


def test_o_id_da_parte_nao_e_o_documento_nem_o_contem():
    ident = queries.parte_id(CNPJ)
    assert CNPJ not in ident
    assert ident != CNPJ
    # e nenhum pedaço reconhecível do documento sobrevive no digest
    assert not any(CNPJ[i:i + 5] in ident for i in range(len(CNPJ) - 4))


def test_o_id_e_estavel_entre_processos():
    """É derivado SÓ do código, sem sal por processo: a seleção que a pessoa
    deixou aberta continua valendo depois de um deploy, e o resolvedor de outro
    worker entende o id que este emitiu. (Foi uma chave por processo que matou
    todo link de rastreio no deploy seguinte, em silêncio.)"""
    assert queries.parte_id(CNPJ) == "53e1292f9f11"


def test_o_payload_do_seletor_nao_leva_o_codigo(monkeypatch):
    linhas = {
        "clientes": [{"codigo": CNPJ, "nome": "IOCHPE", "titulos": 3, "valor": 10.0}],
        "fornecedores": [{"codigo": "00360305000104", "nome": "CAIXA",
                          "titulos": 1, "valor": 5.0}],
    }
    monkeypatch.setattr(queries, "_partes_cru", lambda: linhas)
    saida = queries.get_partes()
    for lista in (saida["clientes"], saida["fornecedores"]):
        for r in lista:
            assert "codigo" not in r
            assert CNPJ not in repr(r)
            assert "00360305000104" not in repr(r)
    assert saida["clientes"][0]["doc"] == "61••••••••••75"


def test_publicar_nao_estraga_a_lista_guardada_no_cache(monkeypatch):
    """`_partes_cru` é memoizada e devolve SEMPRE o mesmo objeto. Se `get_partes`
    apagasse `codigo` dele em vez de copiar a linha, o resolvedor pararia de
    funcionar depois da primeira leitura da tela — e o filtro passaria a
    recusar toda seleção, sem erro que aponte para cá."""
    linhas = {"clientes": [{"codigo": CNPJ, "nome": "X", "titulos": 1, "valor": 1.0}],
              "fornecedores": []}
    monkeypatch.setattr(queries, "_partes_cru", lambda: linhas)
    queries.get_partes()
    queries.get_partes()
    assert linhas["clientes"][0]["codigo"] == CNPJ


# ==========================================================================
# Resolver: recusa, não descarta
# ==========================================================================
def _cru():
    return {"clientes": [{"codigo": CNPJ, "nome": "IOCHPE", "titulos": 1, "valor": 1.0}],
            "fornecedores": []}


def test_resolver_traduz_o_id_no_codigo_do_erp(monkeypatch):
    monkeypatch.setattr(queries, "_partes_cru", _cru)
    assert queries.resolver_partes([queries.parte_id(CNPJ)], "clientes") == [CNPJ]


def test_resolver_RECUSA_id_desconhecido_em_vez_de_ignorar(monkeypatch):
    """Descartar em silêncio o id que não resolve devolveria um total MENOR com
    aparência de correto — o pior defeito possível num painel financeiro,
    porque ninguém desconfia de um número que some sozinho."""
    monkeypatch.setattr(queries, "_partes_cru", _cru)
    with pytest.raises(ValueError):
        queries.resolver_partes([queries.parte_id(CNPJ), "0123456789ab"], "clientes")


class _Parou(Exception):
    """Interrompe o `get_overview` na primeira consulta: o que interessa aqui é
    o dicionário de parâmetros, não o resto do cálculo."""


def _espiar_params(monkeypatch, **kw) -> dict:
    """Roda o `get_overview` até o primeiro `execute` e devolve os parâmetros."""
    vistos: dict = {}

    class _Cur:
        def execute(self, sql, params=None):
            vistos.update(params or {})
            raise _Parou

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    queries._RESP_CACHE.clear()      # senão uma leitura boa anterior responderia
    monkeypatch.setattr(queries.db, "get_conn", lambda *a, **k: _Conn())
    with pytest.raises(_Parou):
        queries.get_overview(**kw)
    queries._RESP_CACHE.clear()
    return vistos


def test_selecao_vazia_vira_NULL_que_e_TODOS_e_nao_ninguem(monkeypatch):
    """`= ANY('{}')` não casa com ninguém: se a lista vazia descesse como array
    em vez de NULL, tirar o filtro zeraria a tela inteira em vez de mostrar
    tudo — e o SQL estaria "certo" nos dois casos."""
    vistos = _espiar_params(monkeypatch)
    assert vistos["clientes"] is None
    assert vistos["fornecedores"] is None


def test_a_selecao_desce_como_lista_de_codigos(monkeypatch):
    vistos = _espiar_params(monkeypatch, clientes=(CNPJ,), fornecedores=())
    assert vistos["clientes"] == [CNPJ]
    assert vistos["fornecedores"] is None


def test_o_filtro_opcional_e_escrito_com_o_IS_NULL_do_lado_de_fora():
    """A forma importa: sem o `IS NULL` na frente, o `= ANY` sozinho descartaria
    toda linha quando a chave viesse nula — e "sem filtro" viraria "nada"."""
    frag = queries._lista_de("f.cliente", "clientes")
    assert frag.startswith("AND (%(clientes)s::varchar[] IS NULL")
    assert "OR f.cliente = ANY(%(clientes)s::varchar[])" in frag
    # cast nas DUAS pontas: o 9.3 não adivinha o tipo do array do outro lado
    assert frag.count("::varchar[]") == 2
