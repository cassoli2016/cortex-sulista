# -*- coding: utf-8 -*-
"""Guard da fonte unica do agrupador gerencial.

`sulista.agrupadorgerencial` e uma tabela do ERP sem chave primaria e sem
contrato de tipo. Em 02/09/2026 ela foi recriada com `grupo` em varchar (era
integer) e com uma conta duplicada: as cinco telas que dependem dela pararam
de responder, e o resultado ficou R$ 1,5 mi diferente do razao. Nenhum teste
pegou, porque todos usam duble.

O que da para garantir SEM o banco e o que este arquivo cobra: ninguem volta a
juntar a tabela CRUA. Quem passa por `api.agrupador_gerencial.left_join()`
herda de graca o cast de tipo e a agregacao por (grupo, reduzido) — as duas
defesas. Quem escreve o JOIN a mao perde as duas, em silencio.

A conferencia do CADASTRO (duplicata viva, conta de balanco classificada, os
dois caminhos do resultado) e do `scripts/conferir_agrupador.py`, que roda
contra o banco vivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DONO = ROOT / "api" / "agrupador_gerencial.py"

# `JOIN <tabela>` e o defeito. `FROM <tabela>` sozinho nao multiplica linha
# nenhuma (e o que a propria fonte e os conferidores de cadastro fazem).
JOIN_CRU = re.compile(r"JOIN\s+sulista\.agrupadorgerencial\b", re.I)


def _fontes() -> list[Path]:
    return [p for p in (ROOT / "api").rglob("*.py") if p != DONO]


def test_nenhum_modulo_junta_a_tabela_crua():
    """O JOIN da tabela sai de api/agrupador_gerencial.py, de lugar nenhum mais."""
    culpados = []
    for p in _fontes():
        texto = p.read_text(encoding="utf-8")
        for n, linha in enumerate(texto.splitlines(), 1):
            if JOIN_CRU.search(linha):
                culpados.append(f"{p.relative_to(ROOT)}:{n}: {linha.strip()}")
    assert not culpados, (
        "JOIN direto em sulista.agrupadorgerencial — use "
        "agrupador_gerencial.left_join(), que normaliza o tipo de `grupo` e "
        "agrega por (grupo, reduzido):\n  " + "\n  ".join(culpados))


@pytest.mark.parametrize("modulo", [
    "api.queries", "api.orcamento.sql", "api.previsao.sql", "api.custos_sql",
])
def test_sql_montado_nao_junta_a_tabela_crua(modulo):
    """O texto MONTADO tambem: f-string e .replace() escondem o join do grep."""
    import importlib
    mod = importlib.import_module(modulo)
    culpados = [nome for nome in dir(mod)
                if isinstance(getattr(mod, nome), str)
                and JOIN_CRU.search(getattr(mod, nome))]
    assert not culpados, f"{modulo}: SQL com JOIN cru -> {culpados}"


def test_a_fonte_normaliza_o_tipo_e_agrega():
    from api import agrupador_gerencial as ag
    # o cast e o que sobrevive a coluna varchar de hoje E a integer de ontem
    assert "grupo::text" in ag.FONTE and "::int" in ag.FONTE
    # uma linha por conta: sem isto a duplicata do cadastro dobra o lancamento
    assert "GROUP BY" in ag.FONTE and "min(ag_.descricao)" in ag.FONTE
    j = ag.left_join("ag", "l")
    assert j.startswith("LEFT JOIN (SELECT")
    assert "ag.reduzido = l.reduzido" in j and "ag.grupo = l.grupo" in j


def test_conferidor_usa_a_mesma_alocacao_da_dre():
    """A linha da DRE de um agrupador tem UMA definicao: DRE_MODELO."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_conf_ag", ROOT / "scripts" / "conferir_agrupador.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from api.queries import DRE_MODELO
    assert mod.DRE_MODELO is DRE_MODELO
    assert mod._linha_da_dre("CV - COMBUSTIVEL") == "CUSTO VARIAVEL"
    assert mod._linha_da_dre("CF - DESPESAS ADM") == "CUSTO FIXO"
    # o agrupador que o ERP criou sem prefixo continua sem linha — e por isso
    # que o conferidor o acusa em vez de o esconder
    assert mod._linha_da_dre("CUSTOS OPERACIONAIS") is None


# ============================================================================
# O cartao da Saude do Servidor. Funcao PURA sobre o diagnostico — nada de
# banco aqui, mesmo padrao de tests/test_saude_integracoes.py.
# ============================================================================

def diag(**kw) -> dict:
    """Mapa SAO: e a partir dele que cada teste estraga uma coisa so."""
    d = {"legivel": True, "erro": None, "de": "2025-09-01", "ate": "2026-09-01",
         "meses": 12, "linhas": 584, "contas": 584, "duplicadas": [],
         "grupo_invalido": [], "orfaos": [], "balanco": [],
         "balanco_valor": 0.0, "divergencia": 0.0, "meses_divergentes": 0}
    d.update(kw)
    return d


def cartao(**kw) -> dict:
    from api import servidor as sv
    return sv._servico_agrupador(diag(**kw))


def test_mapa_sao_e_verde_e_diz_que_os_dois_caminhos_fecham():
    c = cartao()
    assert c["status"] == "ok"
    assert "584 classificações em 584 contas" in c["detalhe"]
    assert "fecham" in c["detalhe"]


def test_mapa_ilegivel_e_VERMELHO_e_nomeia_as_telas_que_caem():
    """O caso de 02/09/2026: `grupo` em varchar tornou o mapa impossivel de
    ler. Nao e numero torto, e cinco telas sem dado."""
    c = cartao(legivel=False, erro="UndefinedFunction")
    assert c["status"] == "erro"
    assert "UndefinedFunction" in c["detalhe"]
    for tela in ("DRE Gerencial", "Contabilidade", "Orçamento", "Previsão", "Custos"):
        assert tela in c["detalhe"]


def test_conta_com_duas_classificacoes_acusa_a_CHAVE():
    """Sem a chave na tela, o operador nao tem por onde comecar."""
    c = cartao(duplicadas=[{"grupo": "1", "reduzido": 425406, "linhas": 2,
                            "descricoes": "A || B"}])
    assert c["status"] == "alerta"
    assert "1|425406" in c["detalhe"]
    assert "apagar a antiga no ERP" in c["detalhe"]


def test_conta_de_balanco_conta_as_DUAS_populacoes():
    """A sem movimento esta igualmente mal classificada — dispara sozinha no
    dia em que o ERP lancar nela, e por isso aparece na contagem."""
    c = cartao(balanco=[{"valor": 1_071_887.58}, {"valor": 399_245.06},
                        {"valor": 0.0}],
               balanco_valor=1_471_132.64)
    assert c["status"] == "alerta"
    assert "3 conta(s) de BALANÇO" in c["detalhe"]
    assert "2 com movimento" in c["detalhe"]
    assert "R$ 1,47 mi" in c["detalhe"]


def test_empresa_nao_numerica_e_achado_e_nao_silencio():
    """A conta perde o agrupador em vez de derrubar a consulta — o preco de
    nao cair e justamente este: some sem avisar. O cartao avisa."""
    c = cartao(grupo_invalido=[{"grupo": "EMP1", "linhas": 3}])
    assert c["status"] == "alerta"
    assert "3 classificação(ões) com empresa não numérica" in c["detalhe"]


def test_classificacao_sem_conta_no_plano():
    c = cartao(orfaos=[{"grupo": "1", "reduzido": 999999, "agrupador": "X"}])
    assert c["status"] == "alerta"
    assert "conta que não existe no plano" in c["detalhe"]


def test_os_dois_caminhos_divergindo_e_achado_por_si_so():
    """A reconciliacao pega o que as conferencias de cadastro nao preveem."""
    c = cartao(divergencia=-250_000.0, meses_divergentes=3)
    assert c["status"] == "alerta"
    assert "divergem" in c["detalhe"] and "3 de 12 meses" in c["detalhe"]


def test_todo_achado_manda_para_o_conferidor():
    c = cartao(duplicadas=[{"grupo": "1", "reduzido": 1, "linhas": 2, "descricoes": "A || B"}])
    assert "scripts/conferir_agrupador.py" in c["detalhe"]


@pytest.mark.parametrize("valor,esperado", [
    (1_471_132.64, "R$ 1,47 mi"),
    (-1_471_132.64, "-R$ 1,47 mi"),
    (12_345_678.0, "R$ 12,35 mi"),
    (85_034.70, "R$ 85,03 mil"),
    (-6_754.66, "-R$ 6,75 mil"),
    (12.5, "R$ 12,50"),
])
def test_valor_curto_sai_em_pt_br(valor, esperado):
    from api import servidor as sv
    assert sv._brl_mi(valor) == esperado

# --------------------------------------------------------------------------
# A NATUREZA DA CONTA MANDA, e não o mapa

_DRE = ("DRE_AG_SQL", "DRE_AG_CONTA_SQL", "DRE_AJUSTADAS_SQL")


@pytest.mark.parametrize("nome", _DRE)
def test_a_dre_exige_conta_de_RESULTADO(nome):
    """O filtro era "tem agrupador OU é conta de resultado", e o OU deixava a
    classificação passar por cima da natureza da conta.

    Quatro contas de BALANÇO entravam por essa porta: o Ticket Car (passivo)
    somava −1,07 mi em 12 meses dentro de CV-COMBUSTÍVEL, e em julho/26 fazia
    a linha mostrar 299.951,18 onde o relatório de Lançamentos CTB do próprio
    AVA mostra 485.176,86 — o ERP monta a linha pela ÁRVORE da conta (reduzido
    mãe 4111) e nunca teve o problema.
    """
    from api import queries

    sql = " ".join(getattr(queries, nome).split())
    assert "AND p.estrutural ~ '^[34]'" in sql, nome
    assert "ag.descricao IS NOT NULL OR" not in sql, (
        "%s voltou a aceitar conta por classificação, ignorando a natureza"
        % nome)


def test_o_conferidor_CONTINUA_permissivo_de_proposito():
    """O conferidor mede o que o mapa DEIXARIA entrar — é o alarme de cadastro
    furado. Apertá-lo junto com a DRE cegaria a medição: os dois caminhos
    passariam a fechar sempre, e o erro de classificação viraria invisível.

    AFIRMA O COMPORTAMENTO, não o texto. Até 07/09/2026 este teste procurava a
    string `ag.descricao IS NOT NULL OR`; trocar o LEFT JOIN por EXISTS (mesma
    elegibilidade, 47 s → 4,5 s) o deixaria vermelho sem que nada tivesse
    apertado. O que precisa continuar verdade é que a CTE do MAPA aceita a
    conta por DUAS portas — ter agrupador, ou ser conta de resultado — e que a
    do ESTRUTURAL aceita só pela segunda. É essa assimetria que faz os dois
    caminhos divergirem quando o cadastro está furado."""
    from api import agrupador_gerencial

    sql = " ".join(agrupador_gerencial.DOIS_CAMINHOS_SQL.split())
    mapa, estrutural = sql.split("por_estrutural AS (")
    assert "agrupadorgerencial" in mapa and "p.estrutural ~ '^[34]'" in mapa, (
        "a CTE do mapa deixou de aceitar a conta por classificação — os dois "
        "caminhos passariam a fechar sempre e o cadastro furado ficaria mudo")
    assert "agrupadorgerencial" not in estrutural, (
        "a CTE do estrutural olhou o mapa: ela é o SEGUNDO caminho, e um "
        "segundo caminho que depende do primeiro não confere nada")


def test_a_contabilidade_ainda_MOSTRA_a_conta_mal_classificada():
    """A tela de Contabilidade existe para classificar. Esconder dela a conta
    errada tiraria justamente de quem conserta a chance de ver o problema."""
    from api import queries

    sql = " ".join(queries.CONTAB_CONTAS_SQL.split())
    assert "ag.descricao IS NOT NULL OR" in sql


# ==========================================================================
# JOIN QUE SO RESPONDE SIM OU NAO, e o que ele custou (06/09/2026)
# ==========================================================================

# A LISTA NAO E ESCRITA A MAO -- ela e CONFERIDA contra o disco logo abaixo.
# Ate 07/09/2026 ela era so estas quatro linhas, e faltava justamente
# `api.agrupador_gerencial`: o guard do EXISTS varria os OUTROS modulos e nao o
# proprio, onde vivia a unica violacao da casa (o `DOIS_CAMINHOS_SQL`, 47 s).
# Ele nasceu dizendo "ZERO violacoes" porque nunca olhou para dentro de casa.
MODULOS_SQL = ("api.agrupador_gerencial", "api.queries", "api.orcamento.sql",
               "api.previsao.sql", "api.custos_sql")


def _constantes_sql(modulo):
    import importlib
    mod = importlib.import_module(modulo)
    for nome in sorted(dir(mod)):
        v = getattr(mod, nome)
        if isinstance(v, str) and "agrupadorgerencial" in v:
            yield nome, v


def test_ninguem_JUNTA_a_fonte_so_para_saber_SE_a_conta_tem_agrupador():
    """O join que so responde sim ou nao sai caro, e o preco cresce sozinho.

    A consulta do historico do Orcamento usava `left_join()` e so olhava
    `ag.descricao IS NOT NULL` no WHERE -- nada do agrupador entrava no
    resultado. Medido: 3 meses 0,9 s, 9 meses 7,5 s, 24 meses ESTOURA os 60 s
    do `statement_timeout`. Quatro vezes mais dado, oitenta vezes mais tempo,
    porque o plano vira com o tamanho:

        Merge Cond:  (l.grupo = ag.grupo)      <- so o grupo
        Join Filter: (ag.reduzido = l.reduzido)

    `grupo` tem meia duzia de valores distintos: casar so por ele contra 584
    linhas de agrupador e quase um produto cartesiano sobre 2,5 milhoes de
    lancamentos. Na janela de 3 meses o MESMO SQL casava pelas duas colunas e
    ia bem -- por isso nenhum teste pequeno jamais acusaria.

    Quem so precisa da resposta sim/nao usa `agrupador_gerencial.existe()`, que
    o planejador resolve como semi-join com hash: 24 meses em ~20 s, resultado
    identico.

    Este guard nasceu com ZERO violacoes -- a varredura mostrou que todas as
    outras consultas leem `descricao` de verdade. Ele existe para que a
    proxima nao volte a juntar por inercia.
    """
    import re

    from api import agrupador_gerencial as ag

    culpados = []
    for modulo in MODULOS_SQL:
        for nome, sql in _constantes_sql(modulo):
            junta = "LEFT JOIN (SELECT" in sql and "min(ag_.descricao)" in sql
            if not junta:
                continue
            # A FONTE SAI DO TEXTO ANTES DA BUSCA, e esta linha e o guard do
            # guard. A primeira versao procurava `.descricao` no SQL inteiro --
            # e o `min(ag_.descricao)` de dentro da propria FONTE casava, entao
            # TODA consulta parecia "usar o nome" e o teste passava mesmo com o
            # defeito reintroduzido. Descoberto sabotando: o SQL voltou a
            # juntar, e o verde continuou verde.
            corpo = sql.replace(ag.FONTE, " ")
            usa_nome = re.search(r"\.descricao\b(?!\s+IS\s+NOT\s+NULL)", corpo)
            if not usa_nome:
                culpados.append("%s.%s" % (modulo, nome))
    assert not culpados, (
        "estas consultas JUNTAM a fonte do agrupador e nunca leem o nome dele "
        "— troque por agrupador_gerencial.existe(), que nao multiplica linha "
        "e nao deixa o plano virar com o tamanho da janela: %s" % culpados)


def test_o_existe_carrega_o_MESMO_cast_da_fonte():
    """Uma regra de cast, dois usos. Se `existe()` tivesse a copia dele, o dia
    em que a Contabilidade recriar a tabela consertaria metade da casa."""
    from api import agrupador_gerencial as ag
    assert ag._GRUPO_INT in ag.FONTE, "a fonte deixou de usar o cast comum"
    assert ag._GRUPO_INT in ag.existe("l"), "o existe() tem cast proprio"
    e = ag.existe("l")
    assert e.startswith("EXISTS (SELECT 1") and "ag_.descricao IS NOT NULL" in e
    # e ele NAO pode multiplicar linha: sem JOIN, sem GROUP BY
    assert "JOIN" not in e.upper()


def test_o_existe_e_o_left_join_respondem_a_MESMA_pergunta():
    """`min(descricao)` da fonte e NULL exatamente quando nao ha linha com
    descricao preenchida — e e essa equivalencia que autoriza a troca."""
    from api import agrupador_gerencial as ag
    j = ag.left_join("ag", "l")
    e = ag.existe("l")
    for lado in (j, e):
        assert "ag_.reduzido" in lado or "ag.reduzido" in lado
    # os dois casam pelas DUAS colunas: foi casar so por uma que custou caro
    assert "reduzido" in e and "grupo" in e


def test_a_lista_de_modulos_do_guard_e_conferida_CONTRA_O_DISCO():
    """Guard cego nao acusa: ele passa.

    O teste acima varre `MODULOS_SQL`, uma lista escrita a mao. Enquanto
    `api.agrupador_gerencial` nao estava nela, o `DOIS_CAMINHOS_SQL` -- que
    juntava a fonte so para perguntar sim/nao, e custava 47 s contra 4,5 s --
    passou aprovado pelo guard que existe exatamente para pega-lo. O relatorio
    "ZERO violacoes" era verdadeiro sobre o que ele olhou; a LISTA e que estava
    errada, e lista errada nao tem sintoma.

    Entao a lista se confere pelo DISCO: todo modulo de `api/` que carrega SQL
    da `agrupadorgerencial` numa CONSTANTE DE MODULO tem de estar em
    `MODULOS_SQL`. Le por `ast` e nao por regex sobre o arquivo inteiro --
    senao um comentario que menciona a tabela acusaria um modulo que nao tem
    SQL nenhum, e guard que grita a toa acaba desligado.

    E procura o nome QUALIFICADO (`sulista.agrupadorgerencial`), que e como
    toda consulta de verdade a escreve. So "agrupadorgerencial" pegava dois
    falsos positivos, os dois COMENTARIOS -- um em `api/motorista/viagem.py`
    (fora de constante) e outro DENTRO da constante de `api/smartec/viagem.py`,
    um `--` de SQL contando a historia da troca de tipo. O segundo passa pelo
    `ast` sem esforco: para o parser, comentario de SQL e texto.

    O `achados` no fim e o guard do guard: varredura que nao acha NADA passa
    por vacuidade, e e assim que este arquivo ja errou antes.
    """
    import ast

    raiz = Path(__file__).resolve().parents[1] / "api"
    fora, achados = [], []
    for arq in sorted(raiz.rglob("*.py")):
        try:
            arvore = ast.parse(arq.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover
            continue
        tem_sql = any(
            isinstance(no, (ast.Assign, ast.AnnAssign))
            and isinstance(getattr(no, "value", None), ast.Constant)
            and isinstance(no.value.value, str)
            and "sulista.agrupadorgerencial" in no.value.value
            for no in arvore.body)
        if not tem_sql:
            continue
        modulo = ".".join(arq.relative_to(raiz.parent).with_suffix("").parts)
        achados.append(modulo)
        if modulo not in MODULOS_SQL:
            fora.append(modulo)
    assert "api.agrupador_gerencial" in achados, (
        "a varredura nao achou nem o modulo que DEFINE a fonte — ela parou de "
        "enxergar, e um guard que nao enxerga passa sempre")
    assert not fora, (
        "estes modulos tem SQL da agrupadorgerencial em constante e o guard do "
        "EXISTS NAO os varre -- acrescente em MODULOS_SQL: %s" % fora)
