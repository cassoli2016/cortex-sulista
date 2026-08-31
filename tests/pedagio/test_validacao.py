"""Validação de pedágio — as regras que o número depende para não mentir.

O QUE ESTA TELA COMPARA, E POR QUE OS TRÊS NÃO BATEM
====================================================
Medido em 30/08/2026, 12 meses:

    conhecimento.valortaxapedagio   R$ 4,86 mi  (cobrado do cliente no CT-e)
    coleta.valorpedagio             R$ 5,69 mi  (pedágio da operação)
    valepedagio.valorcartao         R$ 1,76 mi  (adiantado ao transportador)

O vale cobre 36% do cobrado, e a quebra por modalidade explica a maior parte:
AGR R$ 1,26 mi (71%), LOC R$ 307 mil, TER R$ 143 mil, frota própria R$ 56 mil.
É coerente com a Lei 10.209/2001 — o vale é obrigação do embarcador para com o
transportador autônomo, e a frota própria passa por tag.

O ACHADO QUE ESTES TESTES PROTEGEM
==================================
Dos 8.868 vales ligados a uma coleta, **88,3% têm o vale MAIOR** que o pedágio
lançado, e a razão mediana é **1,9** — quase o dobro. Não é cauda, é regra, e a
hipótese natural (o vale cobre ida e volta, a coleta lança o trecho carregado)
é de quem opera, não do painel.
"""
from __future__ import annotations

import pytest

from api.pedagio import validacao as V


# ── a classificação ─────────────────────────────────────────────────────────


def test_pedagio_ZERO_na_coleta_e_categoria_propria():
    """Zero na coleta é AUSÊNCIA DE LANÇAMENTO, não "vale maior".

    Somá-lo à diferença real inflaria o achado com um problema de outra
    natureza — e de outro dono: um é conferência de valor, o outro é cadastro.
    Mesma regra do zero que virou `n/d` em cinza na Análise de KM.
    """
    assert V._classificar({"vale": 120.0, "coleta": 0.0}) == "coleta_zero"
    assert V._classificar({"vale": 120.0, "coleta": None}) == "coleta_zero"


def test_diferenca_de_centavo_NAO_e_divergencia():
    """Arredondamento de centavo não é achado — vira ruído que esconde o real."""
    assert V._classificar({"vale": 100.00, "coleta": 100.004}) == "igual"
    assert V._classificar({"vale": 100.02, "coleta": 100.00}) == "vale_maior"
    assert V._classificar({"vale": 99.90, "coleta": 100.00}) == "vale_menor"


# ── a razão ─────────────────────────────────────────────────────────────────


def test_a_razao_sai_dos_valores_e_nao_do_arredondado(monkeypatch):
    """Arredondar antes de dividir move o número de lado da fronteira, e aqui
    o limiar de leitura é 1,00: decide se a frase é "o vale cobre mais que o
    lançado" ou não. Mesma lição do `razao_parado_direcao` da jornada, que saía
    1,52 onde o certo era 1,50."""
    linhas = [{"vale": 100.004, "coleta": 100.0, "veiculo": "AAA0A00",
               "quantidadetotaleixos": 6}]
    monkeypatch.setattr(V.db, "query", lambda *a, **k: linhas)
    r = V.confronto("2026-01-01", "2026-12-31")
    assert r["linhas"][0]["razao"] == 1.0


def test_a_mediana_e_nao_a_media(monkeypatch):
    """Um punhado de vales de valor alto puxaria a média e diria que a
    diferença é maior do que a maioria dos casos mostra."""
    linhas = [{"vale": 10.0, "coleta": 10.0},   # 1,0
              {"vale": 20.0, "coleta": 10.0},   # 2,0
              {"vale": 900.0, "coleta": 10.0}]  # 90,0 — o outlier
    monkeypatch.setattr(V.db, "query", lambda *a, **k: linhas)
    r = V.confronto("2026-01-01", "2026-12-31")
    assert r["razao_mediana"] == 2.0, (
        "a média daria 31,0 e diria que o vale é 31 vezes o lançado")


# ── a série mensal ──────────────────────────────────────────────────────────


def test_mes_SEM_DADO_e_marcado_e_nao_vira_zero(monkeypatch):
    """`GROUP BY` não devolve o mês sem lançamento, e o gráfico emendaria o
    anterior com o seguinte desenhando continuidade sobre um buraco. Barra
    zerada diria "não houve pedágio", que é outra coisa."""
    linhas = [{"competencia": "2026-01", "cte_taxa": 100.0, "cte_n": 2,
               "coleta_pedagio": 90.0, "coleta_n": 2, "vale": 50.0,
               "vale_n": 1, "vale_cancelados": 0},
              {"competencia": "2026-02", "cte_taxa": 0.0, "cte_n": 0,
               "coleta_pedagio": 0.0, "coleta_n": 0, "vale": 0.0,
               "vale_n": 0, "vale_cancelados": 0}]
    monkeypatch.setattr(V.db, "query", lambda *a, **k: linhas)
    m = V.mensal("2026-01-01", "2026-02-28")
    assert m[0]["sem_dado"] is False
    assert m[1]["sem_dado"] is True


def test_cobertura_sem_DENOMINADOR_e_None_e_nao_zero(monkeypatch):
    """Mês sem CT-e com pedágio não tem cobertura definida. Preencher com 0%
    o faria parecer o pior mês da série, quando não há o que dividir — a mesma
    regra do KPI que mostra `—` quando o filtro exclui a base dele."""
    linhas = [{"competencia": "2026-01", "cte_taxa": 0.0, "cte_n": 0,
               "coleta_pedagio": 0.0, "coleta_n": 0, "vale": 50.0,
               "vale_n": 1, "vale_cancelados": 0}]
    monkeypatch.setattr(V.db, "query", lambda *a, **k: linhas)
    assert V.mensal("2026-01-01", "2026-01-31")[0]["cobertura_vale"] is None


# ── o join, que é onde este módulo mais podia errar ─────────────────────────


def test_o_confronto_liga_pela_chave_COMPOSTA_da_coleta():
    """`coleta.numero` NÃO é único: a chave é `grupo, empresa, filial, unidade,
    numero`. Ligando só pelo número, os 8.868 vales viravam **24.803 linhas** —
    quase três vezes, medido.

    É o espelho do "coluna zerada com KPI cheio" da tela de Agregados: lá o
    join não casava nada, aqui casa demais. Quando o total muda de ordem de
    grandeza ao ligar duas tabelas, é o join, não o negócio.
    """
    sql = " ".join(V.CONFRONTO_SQL.split())
    for campo in ("c.grupo = vp.grupodocumentoorigem",
                  "c.empresa = vp.empresadocumentoorigem",
                  "c.filial = vp.filialdocumentoorigem",
                  "c.unidade = vp.unidadedocumentoorigem",
                  "c.numero = vp.numerodocumentoorigem"):
        assert campo in sql, "o join perdeu %s e vai multiplicar linha" % campo


def test_nenhum_SQL_tem_porcento_solto():
    """`%` dentro da string vira placeholder do psycopg e a consulta morre com
    `incomplete placeholder`. Um comentário com "88,3%" já derrubou uma
    consulta desta casa; a explicação vai em comentário PYTHON, acima da
    constante."""
    import re
    for nome in dir(V):
        if not nome.endswith("_SQL"):
            continue
        sql = getattr(V, nome)
        soltos = [m.group(0) for m in re.finditer(r"%(?!\()", sql)]
        assert not soltos, "%s tem %%: %s" % (nome, soltos)


def test_os_campos_sempre_vazios_do_ERP_nao_entram_na_conta():
    """`valorpedagiodestacado`, `valorpedagiocompra` e
    `valorpedagiocontratadocalculado` são ZERO em 100% das linhas — medido em
    68.367 CT-e e 38.840 coletas. São a família do "mão de obra R$ 0 com 747
    OSs": campo que existe, parece número e não é.

    Somá-los produziria zero com cara de dado, e um total que ninguém consegue
    explicar. A tela DIZ que eles não são usados; não os soma.
    """
    todo = " ".join(getattr(V, n) for n in dir(V) if n.endswith("_SQL"))
    for campo in ("valorpedagiodestacado", "valorpedagiocompra",
                  "valorpedagiocontratadocalculado"):
        assert campo not in todo, (
            "%s é zero em 100%% das linhas — somá-lo inventa um número" % campo)
