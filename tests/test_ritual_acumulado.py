# -*- coding: utf-8 -*-
"""O acumulado do ano no Ritual Semanal.

Quem opera, 18/09/2026: "alguns indicadores que são automáticos precisa vir o
acumulado do sistema". A linha passou a ter dois números — no mês e no ano — e
é aí que mora o defeito que estes guards existem para impedir: DUAS COLUNAS DA
MESMA LINHA COM RÉGUAS DIFERENTES. Uma reunião que vê 7,2 no mês e 99,7 no ano
só descobre que os dois não se somam quando alguém faz a conta na sala.

Três coisas se conferem aqui, e as três são comportamento, não texto:

1. **A janela que a fonte do ano usa é o ANO** — provado interceptando a função
   de origem e lendo os argumentos com que ela foi chamada. É a única forma de
   distinguir "recalculou sobre o ano" de "somou/mediou os meses", que dão
   números diferentes e parecidos.
2. **Estoque não acumula** — e a lista de quem não acumula é conferida contra
   o registro, não escrita à mão nos dois lados.
3. **A régua nova bate com a velha ao centavo** (`get_faturado` × Visão Geral),
   que é o único teste que precisa do ERP e por isso se pula quando ele falta.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.gestao import ritual

#: Fontes que são FOTOGRAFIA DE AGORA. Somar doze fotos do mesmo estoque produz
#: um número que não existe no mundo — 51 OS abertas em janeiro e 51 em
#: fevereiro não são 102 OS. A lista está aqui para que acrescentar acumulado a
#: uma delas por engano reprove a suíte com o nome da fonte no erro.
ESTOQUE = {
    "receber_vencido", "os_abertas", "oc_atrasadas", "cnh_vencidas",
    "cnh_vence_prazo", "ferias_sem_agenda", "hc_ativos", "afastados",
    "pneus_abaixo_limite", "trocas_pneus_30d", "cpk_pneus",
    "crm_contas_paradas",
}


def test_todo_acumulado_registrado_EXECUTA_sem_levantar():
    """O mesmo guard das fontes do mês, para o segundo leitor.

    Não exige número — o ERP pode estar fora, e teste que exige valor de
    terceiro vira alarme de terceiro. Exige que RODE: assinatura errada
    (`get_combustivel` não recebe filial, `get_analise_km` recebe) e caminho
    aninhado torto aparecem aqui, e em nenhum outro lugar. Foi assinatura
    errada, não chave errada, que deixou três fontes mudas quando este módulo
    nasceu.
    """
    for chave, f in ritual.FONTES.items():
        if f.ler_ano is None:
            continue
        v = ritual.ler_acumulado(chave)
        assert v is None or isinstance(v, float), (
            "acumulado de %s devolveu %r, que não é número nem ausência"
            % (chave, v))


def test_o_que_e_FOTO_DE_AGORA_nao_acumula():
    """Estoque com acumulado é um número inventado, e ele NÃO teria sintoma:
    apareceria como uma coluna a mais preenchida, plausível, na reunião."""
    erradas = sorted(c for c in ESTOQUE
                     if c in ritual.FONTES and ritual.FONTES[c].ler_ano)
    assert not erradas, (
        "estas são fotografia de agora e não podem acumular: %s" % erradas)
    # e a lista não pode envelhecer em silêncio: fonte que sumiu do registro
    # deixaria o guard acima passando por vacuidade
    sumidas = sorted(c for c in ESTOQUE if c not in ritual.FONTES)
    assert not sumidas, "fontes que não existem mais no registro: %s" % sumidas


def test_o_ACUMULADO_do_fluxo_e_da_razao_EXISTE():
    """O espelho do teste acima. Sem ele, apagar todos os `_acumular` deixaria
    a suíte verde — e a tela sem a coluna que o pedido criou."""
    devem = {"receita_faturada_mes", "atingimento_meta", "manutencao_mes",
             "retorno_vazio", "rkm", "diesel_km", "combustivel_mes",
             "receita_cte_mes"}
    faltam = sorted(c for c in devem if not ritual.FONTES[c].ler_ano)
    assert not faltam, "estas deviam acumular e não acumulam: %s" % faltam


def test_a_RAZAO_do_ano_e_RECALCULADA_sobre_o_ano(monkeypatch):
    """O guard que separa "recalculou" de "mediou os meses".

    RKM do ano NÃO é a média dos RKM mensais: seria dar o mesmo peso a um mês
    de 400 mil km e a um de 900 mil. A prova é a JANELA com que a função de
    origem é chamada — e ela só aparece interceptando a chamada, porque os dois
    caminhos devolvem um `float` parecido e nenhum levanta erro.
    """
    vistos = []

    def falso_km(filial, de, ate, *a, **kw):
        vistos.append((filial, de, ate))
        return {"kpis": {"rkm": 9.99, "retorno_vazio": 0.1234}, "diesel_km": 2.5}

    from api import queries
    monkeypatch.setattr(queries, "get_analise_km", falso_km)

    assert ritual.ler_acumulado("rkm") == 9.99
    assert ritual.ler_fonte("rkm") == 9.99
    ano = date.today().replace(month=1, day=1).isoformat()
    mes = date.today().replace(day=1).isoformat()
    assert vistos[0] == (None, ano, date.today().isoformat()), vistos[0]
    assert vistos[1] == (None, mes, date.today().isoformat()), vistos[1]
    # o fator continua valendo no acumulado (fração → percentual)
    assert ritual.ler_acumulado("retorno_vazio") == pytest.approx(12.34)


def test_a_funcao_SEM_FILIAL_e_chamada_sem_filial(monkeypatch):
    """`get_combustivel(de, ate)` não recebe filial, e passar `None` na frente
    deslocaria as datas em silêncio: o `de` viraria `None` e a consulta leria o
    ano inteiro do fornecedor, ou levantaria — as duas caladas atrás do
    `except` de `ler_acumulado`."""
    vistos = []

    def falso_comb(de, ate, *a, **kw):
        vistos.append((de, ate))
        return {"kpis": {"custo_proprio": 123.0}}

    from api import queries
    monkeypatch.setattr(queries, "get_combustivel", falso_comb)
    assert ritual.ler_acumulado("combustivel_mes") == 123.0
    assert vistos[0] == (date.today().replace(month=1, day=1).isoformat(),
                         date.today().isoformat()), vistos[0]


def test_o_MES_EM_CURSO_entra_com_a_meta_ATE_HOJE(monkeypatch):
    """O veneno do dia em curso, na conta do atingimento do ano.

    Com a meta CHEIA do mês corrente, o acumulado despencaria todo dia 1º e
    subiria ao longo do mês sem nada ter acontecido. Medido em 18/09/2026: com
    a meta cheia de setembro o ano dava 86,2%; com a meta até o dia, 90,4% — a
    diferença entre "estamos atrás" e "estamos na média".
    """
    hoje = date.today()
    corrente = hoje.strftime("%Y-%m")
    anterior = "%s-%02d" % (hoje.year, hoje.month - 1) if hoje.month > 1 else None

    mensal = [{"mes": corrente, "realizado": 50.0, "meta": 200.0}]
    if anterior:
        mensal.insert(0, {"mes": anterior, "realizado": 100.0, "meta": 100.0})
    # a meta ATÉ HOJE do mês corrente é a metade da cheia, no dublê
    payload = {"mensal": mensal, "kpis": {"meta_mtd": 100.0}}

    from api import faturamento
    monkeypatch.setattr(faturamento, "get_detalhado", lambda *a, **kw: payload)

    v = ritual.ler_acumulado("atingimento_meta")
    real = 150.0 if anterior else 50.0
    meta_certa = 200.0 if anterior else 100.0        # 100 do fechado + 100 MTD
    meta_errada = 300.0 if anterior else 200.0       # se usasse a meta CHEIA
    assert v == pytest.approx(100.0 * real / meta_certa), v
    assert v != pytest.approx(100.0 * real / meta_errada)


def test_o_ano_NAO_pega_os_meses_do_ano_passado(monkeypatch):
    """A série do faturamento tem TREZE meses: quatro deles são do ano
    anterior. Somar a série inteira daria um "acumulado do ano" que inclui
    setembro passado — e ele seria plausível, porque é só maior."""
    hoje = date.today()
    passado = "%d-12" % (hoje.year - 1)
    payload = {"mensal": [{"mes": passado, "realizado": 999.0, "meta": 999.0},
                          {"mes": hoje.strftime("%Y-%m"),
                           "realizado": 10.0, "meta": 100.0}],
               "kpis": {"meta_mtd": 20.0}}
    from api import faturamento
    monkeypatch.setattr(faturamento, "get_detalhado", lambda *a, **kw: payload)
    assert ritual.ler_acumulado("atingimento_meta") == pytest.approx(50.0)


def test_fonte_que_nao_acumula_devolve_None_e_nao_levanta():
    assert ritual.ler_acumulado("os_abertas") is None
    assert ritual.ler_acumulado("chave_que_nao_existe") is None


def test_o_catalogo_DIZ_quem_acumula():
    """A tela de cadastro precisa saber, senão o gerente escolhe uma fonte
    achando que vai ganhar a coluna do ano."""
    cat = {f["chave"]: f for f in ritual.fontes_publicas()}
    assert cat["rkm"]["tem_acumulado"] is True
    assert cat["rkm"]["acumulado_onde"]
    assert cat["os_abertas"]["tem_acumulado"] is False
    assert cat["os_abertas"]["acumulado_onde"] == ""


# =================================================== a régua, contra o ERP

def test_a_janela_nova_do_faturado_bate_com_a_VISAO_GERAL_ao_centavo():
    """A prova de que o acumulado é a MESMA régua do número do mês.

    `get_faturado` nasceu para o acumulado do ano porque a Visão Geral só
    publica o mês. Rodada na janela do MÊS INTEIRO, ela tem de devolver
    exatamente `faturamento_mes` — e o "mês inteiro" não é detalhe: a casa tem
    faturas com data de emissão FUTURA (19 delas, R$ 54,3 mil em 18/09/2026), e
    fechar a janela em "hoje" deixava essas de fora.
    """
    import calendar

    from api import queries
    try:
        vg = queries.get_visao_geral()
        h = date.today()
        fim = h.replace(day=calendar.monthrange(h.year, h.month)[1])
        m = queries.get_faturado(h.replace(day=1).isoformat(), fim.isoformat())
    except Exception as exc:  # noqa: BLE001
        pytest.skip("ERP fora do ar: %s" % type(exc).__name__)
    assert m["valor"] == pytest.approx(float(vg["faturamento_mes"]), abs=0.005), (
        "o acumulado leria uma régua diferente da do número ao lado")


def test_a_janela_do_faturado_pega_o_DIA_INTEIRO_do_fim(esquema_pg, monkeypatch):
    """O SQL de verdade, num banco de dublê com os TIPOS do ERP.

    `fatura.dtemissao` é `timestamp`, e hoje toda emissão está gravada à
    meia-noite — então trocar `< fim + 1 dia` por `<= fim` não muda um centavo
    contra o ERP vivo, e o guard que compara com a Visão Geral APROVA a troca.
    No dia em que o ERP gravar uma fatura às 23h30 do último dia do ano, o
    acumulado perderia essa fatura em silêncio, e ninguém procuraria ali.

    Por isso este guard não pergunta ao ERP: ele cria a fatura das 23h30 e
    exige que ela entre.
    """
    from contextlib import contextmanager

    from api import db, pglocal, queries

    with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE fatura (dtcancelamento date,"
                    " dtemissao timestamp, valortitulo numeric)")
        cur.execute("INSERT INTO fatura VALUES"
                    " (NULL, '2026-12-31 23:30:00', 100),"     # o último minuto
                    " (NULL, '2026-01-01 00:00:00', 10),"      # o primeiro dia
                    " (NULL, '2026-06-15 13:45:00', 5),"       # o meio
                    " (NULL, '2027-01-01 00:10:00', 999),"     # ano que vem
                    " (NULL, '2025-12-31 23:59:00', 888),"     # ano passado
                    " ('2026-03-01', '2026-03-01 10:00:00', 777)")   # cancelada

    @contextmanager
    def conexao_dubla():
        with pglocal.get_conn(esquema_pg) as c:
            yield c

    monkeypatch.setattr(db, "get_conn", conexao_dubla)
    queries._RESP_CACHE.clear()
    try:
        d = queries.get_faturado("2026-01-01", "2026-12-31")
    finally:
        queries._RESP_CACHE.clear()
    assert d["valor"] == pytest.approx(115.0), (
        "faltou a fatura das 23h30 do último dia, ou entrou o que está fora "
        "da janela: %r" % d)
    assert d["faturas"] == 3


# ============================================================== a rota/tela

def test_acumulados_separa_QUEM_NAO_ACUMULA_de_quem_nao_respondeu(esquema_pg):
    """`None` tem dois significados e a tela os escreve diferente: "não
    acumula" (decisão) e "—" (a fonte não respondeu agora). Juntá-los faria
    "não se aplica" parecer defeito, e defeito parecer regra."""
    # o seed das gerências e dos indicadores vem da migration, não de função
    c = ritual.abrir_ciclo(date.today().isoformat(), usuario="teste",
                           esquema=esquema_pg)
    d = ritual.acumulados(c["id"], esquema=esquema_pg)
    assert d["de"].endswith("-01-01") and d["ate"] == date.today().isoformat()
    assert d["indicadores"], "o ciclo semeado tem indicadores"
    for x in d["indicadores"].values():
        assert set(x) == {"acumula", "valor", "onde", "semana_anterior",
                          "media", "tipo"}
        if x["acumula"]:
            assert x["onde"], "acumulado sem procedência escrita"
        else:
            assert x["valor"] is None
    # e existe ao menos um de cada lado, senão o teste passa por vacuidade
    lados = {x["acumula"] for x in d["indicadores"].values()}
    assert lados == {True, False}, lados


# =========================================================== a média sugerida

def test_a_media_de_FLUXO_tira_o_mes_em_curso(monkeypatch):
    """A média por mês sai de aritmética sobre dois números que o painel já
    tem: `(ano − mês) ÷ meses fechados`. O mês em curso SAI — com ele dentro, a
    média despencaria todo dia 1º e subiria sozinha ao longo do mês, sem nada
    ter acontecido. É o veneno do dia em curso na conta da referência.
    """
    import datetime as _dt

    class _Data(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 18)          # oito meses fechados

    monkeypatch.setattr(_dt, "date", _Data)
    monkeypatch.setattr("api.gestao.ritual.date", _Data)
    # 99,7 no ano, 7,2 no mês → (99,7 − 7,2) ÷ 8
    v = ritual.media_mensal("receita_faturada_mes", 7.2, 99.7)
    assert v == pytest.approx((99.7 - 7.2) / 8)
    # com o mês dentro dariam 12,46 — plausível, e errado
    assert v != pytest.approx(99.7 / 8)


def test_a_media_de_RAZAO_e_a_propria_razao_do_ano():
    """RKM do ano já É a média: foi recalculado sobre o período inteiro.
    Dividir por doze daria um número sem significado nenhum — e plausível."""
    assert ritual.media_mensal("rkm", 11.74, 11.53) == pytest.approx(11.53)
    assert ritual.media_mensal("retorno_vazio", 19.4, 17.9) == pytest.approx(17.9)


def test_contagem_na_JANELA_nao_vira_media():
    """25 clientes distintos no ano não são 3 por mês: são os mesmos 19 quase
    todo mês. Dividir aqui inventaria um número."""
    assert ritual.media_mensal("clientes_ativos_mes", 19.0, 25.0) is None
    assert ritual.FONTES["clientes_ativos_mes"].tipo == "janela"


def test_em_JANEIRO_nao_ha_media_porque_nao_ha_mes_fechado(monkeypatch):
    """Média de referência só sobre mês FECHADO. Em janeiro não há nenhum, e a
    resposta é ausência — não uma divisão por zero nem o mês em curso servindo
    de média de si mesmo."""
    import datetime as _dt

    class _Jan(date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 9)

    monkeypatch.setattr(_dt, "date", _Jan)
    monkeypatch.setattr("api.gestao.ritual.date", _Jan)
    assert ritual.media_mensal("receita_faturada_mes", 1.0, 1.0) is None


def test_o_ESTOQUE_nao_tem_media():
    assert ritual.media_mensal("os_abertas", 53.0, None) is None
    assert ritual.FONTES["os_abertas"].tipo == "estoque"


def test_toda_fonte_que_acumula_DECLARA_o_tipo():
    """`tipo` decide a conta da média, não é etiqueta. Fonte nova que esquecer
    de declarar cairia no padrão e a média sairia errada em silêncio — por isso
    `_acumular` recusa tipo fora da lista, e este guard cobra a varredura."""
    for chave, f in ritual.FONTES.items():
        if f.ler_ano is None:
            assert f.tipo == "estoque", (chave, f.tipo)
        else:
            assert f.tipo in ("fluxo", "razao", "janela"), (chave, f.tipo)


def test_as_fontes_do_painel_sao_lidas_EM_PARALELO(monkeypatch):
    """Vinte e quatro indicadores lidos em fila fariam a reunião esperar a
    tela: eram ~10 s com treze. O guard não cronometra (isso mediria a máquina)
    — ele conta quantas leituras acontecem AO MESMO TEMPO."""
    import threading
    import time

    vivos, pico = [0], [0]
    trava = threading.Lock()

    def lento(_chave):
        with trava:
            vivos[0] += 1
            pico[0] = max(pico[0], vivos[0])
        time.sleep(0.05)
        with trava:
            vivos[0] -= 1
        return 1.0

    ritual._em_paralelo(["a", "b", "c", "d", "e", "f"], lento)
    assert pico[0] > 1, "as fontes foram lidas uma por vez"
    # e o leque respeita o teto do pool: passar disso derrubou a Visão Geral
    # com PoolTimeout em 04/09/2026
    from api import processos
    assert pico[0] <= processos.LEQUE_MAXIMO, pico[0]


def test_o_tipo_bate_com_o_COMPORTAMENTO_da_fonte():
    """O guard que pega tipo trocado — que é silencioso e plausível.

    `km_por_veiculo` nasceu marcado como RAZÃO e a média sugerida saiu 22.956
    km/mês, que é o acumulado do ano inteiro: uma meta sete vezes maior que o
    mês, apresentada como referência. O que separa razão de fluxo não é o nome
    da unidade — é o COMPORTAMENTO: razão não cresce com a janela (RKM do mês e
    do ano são ~11,7), fluxo cresce (receita do ano é doze vezes a do mês).

    Por isso o guard MEDE os dois valores em vez de ler a declaração. Sem ERP
    ele se pula, porque teste que exige número de terceiro vira alarme de
    terceiro.
    """
    suspeitas = []
    for chave, f in ritual.FONTES.items():
        if f.ler_ano is None:
            continue
        mes, ano = ritual.ler_fonte(chave), ritual.ler_acumulado(chave)
        if mes is None or ano is None or abs(mes) < 1e-9:
            continue
        cresceu = abs(ano) > 3 * abs(mes)
        if cresceu and f.tipo == "razao":
            suspeitas.append("%s cresce %.1fx com a janela e está como razão"
                             % (chave, ano / mes))
        if not cresceu and f.tipo == "fluxo":
            suspeitas.append("%s não cresce com a janela e está como fluxo"
                             % chave)
    if not suspeitas and all(ritual.ler_fonte(c) is None
                             for c in ("rkm", "receita_faturada_mes")):
        pytest.skip("ERP fora do ar: nada foi medido")
    assert not suspeitas, suspeitas
