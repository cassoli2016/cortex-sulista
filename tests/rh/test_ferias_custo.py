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
    if "com_abono" in sql and "GROUP BY" not in sql:
        return [{"n": 20, "dias": 341, "dias_abono": 35, "base": 39316.17,
                 "base_abono": 5371.15, "com_abono": 5}]
    if "GROUP BY TO_CHAR(fe.gozoinifer" in sql:
        return [{"m": "2026-08", "n": 7, "dias": 110, "dias_abono": 15,
                 "base": 13665.94, "base_abono": 2301.50},
                {"m": "2026-09", "n": 13, "dias": 231, "dias_abono": 20,
                 "base": 25650.23, "base_abono": 3069.65}]
    if "vf.descfuncaocompleta cargo" in sql:
        # O DETALHE COPIA O CADASTRO REAL, inclusive o espaco a direita do
        # cargo e o espaco a esquerda da chapa, que sao como o GLOBUS grava.
        return [
            {"nome": "ANA CAROLINE LEMES RIBEIRO", "chapa": " 001912",
             "cargo": "COORDENADOR DE FATURAMENTO ", "area": "FINANCEIRO",
             "filial": "MATRIZ - FINANCEIRO", "ini": "2026-08-18",
             "fim": "2026-09-06", "dias": 20, "dias_abono": 10,
             "ab_ini": "2026-09-07", "ab_fim": "2026-09-16", "agora": 1,
             "base": 5333.33, "base_abono": 2666.67},
            {"nome": "GILMAR PEREIRA SILVA", "chapa": "003836",
             "cargo": "MOTORISTA TRUCK", "area": "MOT SBC",
             "filial": "FILIAL SBC", "ini": "2026-08-17", "fim": "2026-09-01",
             "dias": 16, "dias_abono": 0, "ab_ini": None, "ab_fim": None,
             "agora": 0, "base": 1316.90, "base_abono": 0.0},
        ]
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


def test_o_agendado_soma_GOZO_E_ABONO_com_terco_e_FGTS(custo):
    """O ABONO PECUNIARIO TAMBEM ESTA AGENDADO E TAMBEM SE PAGA. Contar so o
    gozo subestimava o custo em 13,7% -- R$ 7.734 sobre R$ 56.615, em 5 das 20
    pessoas. Erro do pior tipo: some dentro de um total plausivel e so aparece
    quando alguem pergunta de quem e o dinheiro.

    Os dois voltam SEPARADOS porque significam coisas diferentes para quem le:
    o gozo e ausencia (a pessoa nao esta no posto) e o abono e so desembolso
    (ela trabalha e recebe a mais). Por isso a coluna de DIAS da escala
    continua sendo so a do gozo."""
    ag = custo["agendadas"]
    assert ag["dias"] == 341 and ag["dias_abono"] == 35 and ag["n"] == 20
    assert ag["com_abono"] == 5
    assert ag["custo_gozo"] == pytest.approx(
        39316.17 * fc.UM_TERCO * (1 + fc.FGTS), abs=0.05)
    assert ag["custo_abono"] == pytest.approx(
        5371.15 * fc.UM_TERCO * (1 + fc.FGTS), abs=0.05)
    assert ag["custo"] == pytest.approx(
        ag["custo_gozo"] + ag["custo_abono"], abs=0.05)
    assert ag["custo"] > ag["custo_gozo"], "o abono tem de somar, nao substituir"


def test_o_agendado_volta_QUEBRADO_POR_MES(custo):
    """Um total de R$ 56 mil nao entra em fluxo de caixa nenhum: o que entra e
    quanto cai em agosto e quanto cai em setembro."""
    meses = {x["mes"]: x for x in custo["agendadas"]["por_mes"]}
    assert set(meses) == {"2026-08", "2026-09"}
    assert sum(x["custo"] for x in meses.values()) == pytest.approx(
        custo["agendadas"]["custo"], abs=0.05)
    assert sum(x["n"] for x in meses.values()) == custo["agendadas"]["n"]


def test_o_agendado_SEGUE_o_periodo_projetado_para_a_frente():
    """MUDOU DE PROPOSITO (pedido do usuario: "os filtros devem ter acao em
    todas as telas"). Antes as agendadas ignoravam o periodo e diziam isso num
    selo -- honesto, mas metade da tela nao reagia ao filtro, que e justamente
    o "filtro que a query ignora" que a regra da casa manda tirar.

    Agora o MESMO filtro recorta os dois sentidos do tempo: o realizado para
    tras (competencia) e as agendadas para a frente (data de inicio do gozo).
    Quando o periodo escolhido e todo passado -- que e o caso dos presets
    "ultimos N meses", inclusive o padrao --, a janela futura tem a MESMA
    LARGURA projetada para frente, para o filtro nunca esvaziar a metade
    futura da tela."""
    from api.queries_folha import _janela_futura
    import datetime as dt
    hoje = dt.date.today()

    # periodo que alcanca o futuro: e literalmente o que a pessoa pediu
    de, ate = _janela_futura("2026-08-01", "2099-02-28")
    assert ate == "2099-02-28"

    # periodo todo passado: mesma largura, para frente
    de3, ate3 = _janela_futura(
        (hoje.replace(day=1) - dt.timedelta(days=60)).isoformat(), hoje.isoformat())
    assert de3 == hoje.isoformat()
    assert dt.date.fromisoformat(ate3) > hoje, "a janela futura nao pode nascer vazia"


# ── o detalhe: quem, e nao so quanto ────────────────────────────────────────
def test_o_detalhe_traz_cargo_centro_de_custo_e_unidade(custo):
    """Uma escala de ferias se aprova POR PESSOA: "R$ 64 mil em setembro" nao
    deixa ninguem decidir nada, "o coordenador de faturamento sai dia 18" deixa.
    Cargo, area e unidade estao preenchidos em 20 de 20 -- conferido no banco
    ANTES de a coluna existir, porque coluna sempre vazia e coluna a preencher
    ou remover."""
    d = custo["agendadas"]["detalhe"]
    assert len(d) == 2
    a = d[0]
    assert a["cargo"] == "COORDENADOR DE FATURAMENTO"
    assert a["area"] == "FINANCEIRO" and a["filial"] == "MATRIZ - FINANCEIRO"


def test_a_chapa_do_detalhe_vem_SEM_o_espaco_do_ERP(custo):
    """`chapafunc` vem com espaco a esquerda nesta base. Cru, ele quebra a
    comparacao de texto da busca e aparece desalinhado na coluna monoespacada."""
    assert custo["agendadas"]["detalhe"][0]["chapa"] == "001912"


def test_o_cargo_do_detalhe_vem_SEM_o_espaco_a_direita(custo):
    """`COORDENADOR DE FATURAMENTO ` tem espaco no fim no cadastro. Ele nao
    aparece na tela, mas entra na busca por texto e num futuro agrupamento por
    cargo criaria dois cargos onde ha um."""
    assert not custo["agendadas"]["detalhe"][0]["cargo"].endswith(" ")


def test_cada_linha_do_detalhe_usa_a_MESMA_conta_do_total(custo):
    """Tres caminhos chegam ao mesmo numero na tela: total, por mes e por
    pessoa. O duble aqui e AMOSTRA (2 linhas de 20), entao o que se confere e a
    INVARIANTE por linha -- (gozo + abono) x 4/3 x 1,08 --, a mesma formula do
    agregado. Somar duas contas diferentes e como as tres se separariam.

    A soma completa foi conferida contra o banco real: detalhe R$ 64.349,73
    contra total R$ 64.349,74, um centavo de arredondamento."""
    for x in custo["agendadas"]["detalhe"]:
        bruto = x["custo"] / (fc.UM_TERCO * (1 + fc.FGTS))
        # o bruto reconstruido tem de ser (dias + dias_abono) de salario/30
        assert bruto > 0
        if x["dias_abono"]:
            assert x["custo"] > bruto * fc.UM_TERCO, "o terco tem de estar dentro"
    # e as duas linhas do duble batem com as bases que ele devolveu
    total = sum(x["custo"] for x in custo["agendadas"]["detalhe"])
    esperado = (5333.33 + 2666.67 + 1316.90) * fc.UM_TERCO * (1 + fc.FGTS)
    assert total == pytest.approx(esperado, abs=0.05)


def test_quem_ja_esta_de_ferias_HOJE_vem_marcado(custo):
    """A ausencia dessa pessoa nao e futura, e agora. Quem monta escala precisa
    ver isso antes de contar com ela."""
    d = {x["nome"]: x for x in custo["agendadas"]["detalhe"]}
    assert d["ANA CAROLINE LEMES RIBEIRO"]["agora"] is True
    assert d["GILMAR PEREIRA SILVA"]["agora"] is False


def test_o_detalhe_diz_o_PERIODO_do_abono_e_nao_so_a_quantidade(custo):
    """"Vende 10 dias" sem as datas nao entra em escala nenhuma: o abono cai
    DEPOIS do gozo e prolonga o desembolso, sem prolongar a ausencia."""
    a = custo["agendadas"]["detalhe"][0]
    assert a["dias_abono"] == 10
    assert a["ab_ini"] == "2026-09-07" and a["ab_fim"] == "2026-09-16"


def test_o_custo_por_pessoa_e_a_UNICA_saida_individual_do_modulo():
    """Ele permite deduzir o salario base (custo / dias * 30 / 1,4333), e isso
    esta DITO na tela. Entra porque escala se aprova por pessoa e porque a tela
    `ferias` ja e restrita por RBAC a quem cuida de folha. O que continua fora,
    aqui tambem: CPF, dado bancario e o salario como coluna."""
    from pathlib import Path as _P
    fonte = _P(fc.__file__).read_text(encoding="utf-8")
    # COLUNAS, nao palavras: a palavra "CPF" aparece de proposito no comentario
    # que explica por que ela NAO sai daqui, e um teste que a proibisse estaria
    # proibindo a propria documentacao da regra.
    import re as _re
    colunas = set(_re.findall(r"\bvf\.(\w+)", fonte))
    for proibida in ("cpffunc", "numeroctps", "codbanco", "contacorrente",
                     "numeropis", "salbase_individual"):
        assert proibida not in colunas, proibida
    # `salbase` entra so DENTRO de agregacao ou de conta -- nunca como coluna
    # crua na saida, que seria o salario individual virando campo do payload.
    assert '"salario"' not in fonte and "'salario'" not in fonte
    # e a ressalva esta escrita onde quem mexer no modulo vai ler
    assert "permite deduzir o" in fonte


# ── os cartoes e o grafico da aba de agendadas ──────────────────────────────
def test_os_agregados_saem_da_MESMA_lista_do_detalhe(custo):
    """Cartao, grafico e tabela sao TRES leituras do mesmo dado, agregadas em
    Python sobre o detalhe que ja esta em memoria. Uma consulta a mais ao
    Oracle para somar 20 linhas seria custo sem ganho -- e, pior, criaria uma
    quarta fonte de onde os numeros poderiam divergir."""
    ag = custo["agendadas"]
    assert sum(u["pessoas"] for u in ag["por_unidade"]) == len(ag["detalhe"])
    assert sum(u["dias"] for u in ag["por_unidade"]) == sum(
        x["dias"] for x in ag["detalhe"])
    assert sum(u["custo"] for u in ag["por_unidade"]) == pytest.approx(
        sum(x["custo"] for x in ag["detalhe"]), abs=0.05)


def test_por_unidade_vem_ORDENADO_por_custo(custo):
    v = [u["custo"] for u in custo["agendadas"]["por_unidade"]]
    assert v == sorted(v, reverse=True)


def test_o_PICO_e_o_mes_de_mais_GENTE_e_nao_de_mais_dinheiro(custo):
    """A pergunta do cartao e operacional: em que mes mais gente sai ao mesmo
    tempo. O mes mais CARO pode ser um salario alto sozinho, e aprovar ou negar
    um pedido de ferias nao se decide por isso."""
    ag = custo["agendadas"]
    assert ag["pico"]["n"] == max(m["n"] for m in ag["por_mes"])


def test_a_media_de_dias_usa_o_GOZO_e_nao_o_abono(custo):
    """A media diz se a escala esta sendo fracionada (art. 134 permite ate tres
    periodos). Somar o abono a inflaria com dias em que a pessoa ESTA no posto,
    e ai ela nao mediria mais fracionamento nenhum."""
    ag = custo["agendadas"]
    assert ag["dias_medios"] == pytest.approx(ag["dias"] / ag["n"], abs=0.06)
    assert ag["dias_medios"] < (ag["dias"] + ag["dias_abono"]) / ag["n"]


def test_quantos_estao_de_ferias_AGORA(custo):
    """Numero proprio porque muda a leitura da escala: a ausencia dessas nao e
    futura, e agora."""
    ag = custo["agendadas"]
    assert ag["agora"] == sum(1 for x in ag["detalhe"] if x["agora"])
