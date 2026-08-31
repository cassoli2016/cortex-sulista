# -*- coding: utf-8 -*-
"""Custo de ferias: o que a folha PAGOU e o passivo que ainda nao gozaram.

MEDIDO EM 31/08/2026 (12 meses, empresa 1):
    realizado ......... R$ 1.731.807  (12 competencias, media R$ 144.317/mes)
    pago em DOBRO ..... R$    12.154  em 23 lancamentos
    passivo estimado .. R$   744.943  (322.743 vencido + 367.019 avos + FGTS)
    exposicao ......... R$    70.905  em 12 pessoas
    fator medido ...... 1,08x         (a folha paga 8% acima do salario base)

POR QUE O DUBLE COPIA O CORPO REAL
==================================
"Duble otimista testa um fornecedor que nao existe" ja custou uma producao
quebrada nesta casa (a Z-API respondia um campo `error` que o duble omitia).
Aqui o duble carrega o que a base REALMENTE tem e que e facil esquecer:

  - o evento `1/3 FERIAS EM DOBRO`, que cai em DOIS baldes possiveis e so vai
    para o certo se a ordem de teste estiver certa;
  - o evento truncado `MEDIAS S/ VARIAVEIS -`, que NAO pode entrar no total;
  - uma competencia SEM lancamento nenhum, que o `GROUP BY` nao devolve.

Sem esses tres, todo teste aqui passaria por vacuidade.
"""
from __future__ import annotations

import pytest

from api.rh import ferias_custo as fc

# ── o que a base devolve, copiado da medicao real ───────────────────────────
#
# Tres competencias, e a do MEIO nao tem lancamento nenhum: e ela que prova que
# a serie e GERADA e nao colhida. Mes sem ferias nao volta do `GROUP BY`, e o
# grafico emendaria o anterior no seguinte desenhando continuidade sobre um
# buraco — a mesma armadilha que fez a serie da jornada ligar abril em agosto.
_EVENTOS = [
    ("FERIAS NORMAIS",         "2026-06", 585, 672253.79),
    ("1/3 S/ REMUNERACAO DE",  "2026-06", 585, 224084.56),
    ("FERIAS PROPORCIONAIS",   "2026-06", 130, 243921.60),
    ("FERIAS INDENIZADAS",     "2026-08",  68, 248107.29),
    ("ABONO PECUNIARIO",       "2026-08", 105, 119456.37),
    # os dois da dobra: o segundo comeca por "1/3", que tambem e o inicio de
    # rubricas de ferias gozadas. Se a ordem de classificacao inverter, ele
    # some dentro do balde errado e o cartao da dobra fica menor.
    ("FERIAS EM DOBRO",        "2026-08",  11,   9064.04),
    ("1/3 FERIAS EM DOBRO",    "2026-08",  11,   3021.35),
]

_PROVISAO = [
    # filial, pessoas, com_vencido, base_vencido, base_avos, massa
    ("FILIAL CURITIBA", 43, 13, 65327.65, 100612.13, 150000.0),
    ("MATRIZ - RH",      2,  0,      0.0,  14768.31,  12000.0),
]


def _falso(sql: str, params=None):
    params = params or {}
    if "GROUP BY fe.desceven" in sql:
        return [{"ev": e, "comp": c, "n": n, "tot": v}
                for e, c, n, v in _EVENTOS]
    if "CONNECT BY LEVEL" in sql:
        return [{"c": c} for c in ("2026-06", "2026-07", "2026-08")]
    if "ff.codevento IN" in sql:
        return [{"n": 767, "tot": 190810.64, "com_ferias": 679}]
    if "GROUP BY vf.descsecao" in sql:
        return [{"filial": f, "pessoas": p, "com_vencido": cv,
                 "base_vencido": bv, "base_avos": ba, "massa": m}
                for f, p, cv, bv, ba, m in _PROVISAO]
    if "BETWEEN TRUNC(SYSDATE) - 365" in sql:
        return [{"n": 12, "base": 39832.0}]
    if "no_periodo" in sql:
        return [{"n": 20, "dias": 341, "base": 39316.17, "no_periodo": 7}]
    if "GROUP BY TO_CHAR(fe.gozoinifer" in sql:
        return [{"m": "2026-08", "n": 7, "dias": 110, "base": 13665.94},
                {"m": "2026-09", "n": 13, "dias": 231, "base": 25650.23}]
    if "FROM flp_ferias fr" in sql:
        # 5.447 dias gozados; a base por dia foi montada para o fator dar 1,08,
        # que e o valor medido na base real.
        return [{"base_dia": 20000000.0, "dias": 5447}]
    return [{"agora": "2026-08-31 09:00"}]


@pytest.fixture()
def custo(monkeypatch):
    monkeypatch.setattr(fc.db, "query", _falso)
    return fc.get_ferias_custo(dt_de="2026-06-01", dt_ate="2026-08-31")


# ── a dobra: o balde que nao pode se esconder ───────────────────────────────
def test_o_terco_da_DOBRA_nao_cai_no_balde_das_ferias_gozadas():
    """`1/3 FERIAS EM DOBRO` comeca com "1/3", igual a `1/3 S/ REMUNERACAO`.
    Classificado pela primeira regra que casar, ele iria para "gozadas" e o
    unico custo EVITAVEL da tela apareceria um quarto menor — sem erro nenhum,
    e com o total geral certo, que e o que torna isso dificil de notar."""
    assert fc.natureza("1/3 FERIAS EM DOBRO") == "Dobra (art. 137)"
    assert fc.natureza("FERIAS EM DOBRO") == "Dobra (art. 137)"
    assert fc.natureza("1/3 S/ REMUNERACAO DE") == "Gozadas (normais)"


def test_a_dobra_aparece_com_o_valor_e_a_contagem(custo):
    """R$ 12.085 medidos. E o KPI de dobra da aba de RISCO pode ler zero ao
    mesmo tempo: aquele mede o estado de hoje, este mede o que ja foi pago."""
    k = custo["kpis"]
    assert k["dobra_paga"] == pytest.approx(9064.04 + 3021.35, abs=0.01)
    assert k["dobra_lanc"] == 22
    nat = {n["natureza"]: n for n in custo["naturezas"]}
    assert "Dobra (art. 137)" in nat


# ── a serie e GERADA, nunca colhida ─────────────────────────────────────────
def test_o_mes_SEM_lancamento_aparece_como_zero(custo):
    """Julho nao tem uma linha nos eventos. Colhida do `GROUP BY`, a serie
    teria dois pontos e o grafico ligaria junho em agosto, desenhando
    continuidade sobre um mes que existe e vale zero."""
    meses = [x["comp"] for x in custo["serie"]]
    assert meses == ["2026-06", "2026-07", "2026-08"]
    julho = next(x for x in custo["serie"] if x["comp"] == "2026-07")
    assert julho["valor"] == 0.0


def test_a_serie_soma_o_mesmo_que_o_total(custo):
    """Duas contas para o mesmo numero: se a classificacao por natureza e a
    agregacao por competencia discordarem, uma das duas esta perdendo linha."""
    assert sum(x["valor"] for x in custo["serie"]) == pytest.approx(
        custo["kpis"]["realizado"], abs=0.05)
    assert sum(n["valor"] for n in custo["naturezas"]) == pytest.approx(
        custo["kpis"]["realizado"], abs=0.05)


# ── o evento truncado que o ERP nao termina de nomear ───────────────────────
def test_o_evento_de_nome_CORTADO_fica_fora_do_total(custo):
    """`MEDIAS S/ VARIAVEIS -` sao R$ 190.811 e 89% deles caem numa competencia
    com ferias. 89% e indicio, nao prova — soma-lo afirmaria o que a fonte nao
    diz. Mas escondê-lo faria a tela publicar um custo possivelmente
    subestimado em seis digitos sem ninguem saber, entao ele volta no payload
    com o percentual a mostra."""
    assert custo["cinza"]["valor"] == pytest.approx(190810.64, abs=0.01)
    assert custo["cinza"]["pct"] == pytest.approx(88.5, abs=0.1)
    assert custo["kpis"]["realizado"] < 190810.64 + sum(
        v for _, _, _, v in _EVENTOS), "o cinza nao pode ter entrado no total"
    assert custo["kpis"]["realizado"] == pytest.approx(
        sum(v for _, _, _, v in _EVENTOS), abs=0.05)


# ── a provisao ──────────────────────────────────────────────────────────────
def test_a_provisao_soma_vencido_avos_e_FGTS(custo):
    """O passivo e (30 dias do periodo fechado + 2,5 dias por mes do periodo em
    curso) x 4/3 x 1,08. Cada parcela volta separada porque elas tem donos
    diferentes: o vencido e fila de agendamento, os avos sao inevitaveis."""
    k = custo["kpis"]
    base = sum(bv + ba for _, _, _, bv, ba, _ in _PROVISAO)
    assert k["prov_vencido"] + k["prov_avos"] == pytest.approx(
        base * fc.UM_TERCO, abs=0.05)
    assert k["prov_fgts"] == pytest.approx(
        (k["prov_vencido"] + k["prov_avos"]) * fc.FGTS, abs=0.05)
    assert k["provisao"] == pytest.approx(
        k["prov_vencido"] + k["prov_avos"] + k["prov_fgts"], abs=0.05)


def test_unidade_sem_ninguem_vencido_ainda_provisiona_os_avos(custo):
    """Quem nunca fechou periodo tambem gera passivo — 2,5 dias por mes. Uma
    provisao que so contasse o vencido zeraria a unidade inteira e faria o RH
    achar que nao ha nada a provisionar ali."""
    rh = next(x for x in custo["provisao_filial"] if x["filial"] == "MATRIZ - RH")
    assert rh["com_vencido"] == 0 and rh["vencido"] == 0.0
    assert rh["avos"] > 0 and rh["total"] > 0


def test_a_exposicao_e_UMA_vez_o_periodo_e_nao_o_dobro(custo):
    """A dobra paga duas vezes, mas uma delas seria paga de qualquer jeito. O
    numero que decide agendar e o EVITAVEL — a diferenca, nao o total."""
    k = custo["kpis"]
    assert k["exposicao"] == pytest.approx(
        39832.0 * fc.UM_TERCO * (1 + fc.FGTS), abs=0.05)
    assert k["exposicao_n"] == 12


# ── o fator: a estimativa nao se afirma exata ───────────────────────────────
def test_o_fator_mede_o_quanto_o_salario_base_SUBESTIMA(custo):
    """A folha paga media de hora extra e adicional noturno sobre as ferias; a
    estimativa usa so o salario base. Sem medir isso, o passivo sairia com cara
    de valor exato — e ele erra sempre para o mesmo lado, o de menos."""
    assert custo["kpis"]["fator"] is not None
    assert custo["kpis"]["fator"] > 1.0, (
        "o realizado tem de superar a estimativa sobre salario base")


def test_a_ficha_CANCELADA_nao_entra_no_denominador_do_fator():
    """`statusferias='S'` e ficha EXCLUIDA (230 de 233 tem `dtexclferias`), nao
    "sim". Conta-la infla os dias gozados em 42% e o fator desaba, fazendo a
    estimativa parecer generosa quando ela e curta."""
    from pathlib import Path
    fonte = (Path(fc.__file__)).read_text(encoding="utf-8")
    i = fonte.index("FROM flp_ferias fr")
    assert "dtexclferias IS NULL" in fonte[i:i + 500]


# ── o que nunca pode entrar no custo do empregador ──────────────────────────
def test_so_PROVENTO_entra_no_custo():
    """`tipoeven='B'` sao BASES de calculo (base de IRRF, base de INSS): somadas
    contariam a mesma ferias tres vezes. `'D'` sao descontos, que saem do
    liquido do empregado e nao do custo da empresa — `LIQUIDO DE FERIAS`
    sozinho sao R$ 1,19 mi que nao sao custo nenhum."""
    from pathlib import Path
    fonte = (Path(fc.__file__)).read_text(encoding="utf-8")
    assert "fe.tipoeven = 'P'" in fonte


def test_o_INSS_patronal_NAO_e_estimado():
    """A aliquota depende do enquadramento e ha eventos de SIMPLES nesta folha.
    Estimar 20% somaria milhoes inventados — mesma decisao do Custo de Folha,
    onde dizer que nao da para medir foi a resposta certa."""
    from pathlib import Path
    fonte = (Path(fc.__file__)).read_text(encoding="utf-8")
    assert "INSS patronal NÃO entra" in fonte
    assert not any(x in fonte for x in ("0.20", "* 20", "INSS_PATRONAL"))


def test_a_serializacao_atravessa_o_JSON(custo):
    """`numeric` do banco vira `Decimal`, e o estouro do `json` acontece no
    `render()` da resposta — DEPOIS do try/except da rota, que e o que faz o
    navegador receber 500 em text/plain sem uma pista. Converter no limite do
    modulo e onde o tipo do banco para de importar."""
    import json
    json.dumps(custo)


# ── o prefixo curto que inventou R$ 3.843 de custo ──────────────────────────
def test_DIFERENCA_de_SALARIO_nao_e_ferias():
    """O evento 490 esta gravado como `DIFEREN<C-cedilha>A DE FERIAS`, com o
    cedilha em latin-1 (byte 199) numa coluna que o resto do ERP escreve sem
    acento. Alcanca-lo pelo prefixo curto `DIFEREN` casa TAMBEM diferenca de
    salario, de 13o, de PTS, de CCT, de diaria e de adicional noturno — R$
    3.843 de custo de ferias que nao e ferias.

    O QUE TORNA ESSA FAMILIA PERIGOSA: 3.843 sobre 1,83 milhao e 0,21%. Nenhum
    numero muda de ordem de grandeza, nenhuma proporcao se desloca, nenhum
    veredito da tela vira. So um segundo caminho para o mesmo total denuncia."""
    assert fc.natureza("DIFERENCA DE SALARIO D") != "Gozadas (normais)"
    for falso in ("DIFERENCA DE SALARIO D", "DIFERENCA 13o", "DIFERENCA PTS",
                  "DIFERENCA SALARIO CCT", "DIFERENCA DE DIARIA",
                  "DIFERENCA ADIC NOTURNO"):
        assert not any(fc._casa(falso, p)
                       for _, nomes in fc.NATUREZAS for p in nomes), falso


def test_o_curinga_alcanca_o_nome_CORROMPIDO():
    """E o `_` tem de valer UM caractere qualquer, senao o evento de R$ 7.459
    fica de fora e o custo sai subestimado — o erro no sentido oposto."""
    assert fc.natureza("DIFERENÇA DE FERIAS") == "Gozadas (normais)"
    assert fc.natureza("DIFERENCA DE FERIAS NO") == "Gozadas (normais)"
    # e a diferenca da DOBRA continua na dobra: a ordem decide, nao o curinga
    assert fc.natureza("DIFERENCA DE FERIAS EM") == "Dobra (art. 137)"


def test_o_curinga_nao_casa_nome_mais_CURTO_que_o_padrao():
    """`zip` para no menor, entao um nome curto casaria um padrao longo por
    engano — "FERIAS" casaria "FERIAS NORMAIS"."""
    assert not fc._casa("FERIAS", "FERIAS NORMAIS")
    assert fc._casa("FERIAS NORMAIS 30D", "FERIAS NORMAIS")


# ── o periodo por datas ─────────────────────────────────────────────────────
def test_o_default_sao_DOZE_competencias_e_nao_treze():
    """O preset "Ultimos 12 meses" da tela produz 12 competencias contando a
    corrente. Recuar 12 meses cheios no servidor daria TREZE, e o cartao diria
    "em 13 meses" sobre um filtro rotulado 12 -- dois recortes com o mesmo nome
    sao o comeco de uma discussao sobre qual esta certo."""
    import datetime as dt
    de, ate = fc._periodo("", "")
    hoje = dt.date.today()
    assert ate == hoje.isoformat()
    d = dt.date.fromisoformat(de)
    assert d.day == 1
    meses = (hoje.year - d.year) * 12 + (hoje.month - d.month) + 1
    assert meses == 12, (de, ate, meses)


def test_data_INVALIDA_e_descartada_e_nao_corrigida():
    """`03/04` e marco ou abril? Adivinhar produz um recorte plausivel e
    errado, que e a pior das saidas -- ninguem confere um intervalo que parece
    certo. Entrada nao-ISO cai no default."""
    de, ate = fc._periodo("03/04/2026", "31/12/2026")
    padrao = fc._periodo("", "")
    assert (de, ate) == padrao


def test_intervalo_INVERTIDO_e_endireitado():
    """Quem digita a data final no campo inicial nao recebe uma tela vazia: o
    intervalo se corrige sozinho. Vazio ali se leria como "nao houve ferias"."""
    assert fc._periodo("2026-08-31", "2026-06-01") == ("2026-06-01", "2026-08-31")


# ── ferias agendadas: o custo que ainda vai sair ────────────────────────────
def test_o_custo_agendado_conta_o_dia_de_INICIO():
    """DIAS = fim menos inicio MAIS UM. Sem o `+1`, ferias de 30 dias viram 29:
    erro de 3,3% em TODA linha -- pequeno o bastante para nunca chamar atencao
    e grande o bastante para o numero nunca fechar com a folha.

    ESTE E TESTE DE FONTE, e de proposito: a subtracao acontece DENTRO do SQL,
    entao o duble -- que devolve o resultado pronto -- passaria com o `+1`
    removido. Sabotar o modulo e ver os testes seguirem verdes foi o que
    revelou a brecha. Onde a conta mora no banco, e o texto da conta que se
    confere."""
    from pathlib import Path as _P
    fonte = _P(fc.__file__).read_text(encoding="utf-8")
    assert 'ag_dias = "(fe.gozofinfer - fe.gozoinifer + 1)"' in fonte


def test_o_agendado_soma_terco_e_FGTS(custo):
    ag = custo["agendadas"]
    assert ag["dias"] == 341 and ag["n"] == 20
    assert ag["custo"] == pytest.approx(
        39316.17 * fc.UM_TERCO * (1 + fc.FGTS), abs=0.05)


def test_o_agendado_volta_QUEBRADO_POR_MES(custo):
    """Um total de R$ 56 mil nao entra em fluxo de caixa nenhum: o que entra e
    quanto cai em agosto e quanto cai em setembro."""
    meses = {x["mes"]: x for x in custo["agendadas"]["por_mes"]}
    assert set(meses) == {"2026-08", "2026-09"}
    assert sum(x["custo"] for x in meses.values()) == pytest.approx(
        custo["agendadas"]["custo"], abs=0.05)
    assert sum(x["n"] for x in meses.values()) == custo["agendadas"]["n"]


def test_o_agendado_NAO_e_recortado_pelo_periodo(custo):
    """Ele e sempre de hoje em diante, e isso e dito no cartao. Recortado por um
    filtro de 12 meses PASSADOS ele daria zero -- e "nenhuma ferias agendada" e
    a leitura oposta da verdade quando ha vinte marcadas. O que o payload traz
    e quantas caem DENTRO do recorte, para a tela poder dizer a diferenca."""
    ag = custo["agendadas"]
    assert ag["n"] == 20, "o total ignora o periodo"
    assert ag["no_periodo"] == 7, "e o recorte volta separado, para ser dito"
    assert ag["no_periodo"] <= ag["n"]
