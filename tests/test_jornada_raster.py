"""Jornada da RasterJOR — a integração no banco local do CÓRTEX.

Medido em 29/08/2026, depois da carga inicial: 314 motoristas, 53.621 jornadas
e 49.208 inconformidades no banco local, de 01/01/2025 a 15/04/2026.

DOIS NÚMEROS QUE MUDARAM AO TRAZER O DADO PARA CÁ, e os dois são conserto:

- 98.109 linhas de inconformidade na origem viraram 49.208 eventos. A tabela do
  AVA não tem chave nenhuma e acumulou ~50% de duplicata por recarga repetida.
- Com isso a taxa caiu de 2,22 para 0,85 inconformidade por jornada. A primeira
  estava inflada pela duplicação da origem.

A parte com banco usa a fixture `esquema_pg` (schema descartável por teste); o
resto é análise de fonte, porque o AVA é de terceiro e não sobe em CI.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from api import pglocal
from api.jornada import cliente, coleta, leitura

RAIZ = Path(__file__).resolve().parents[1]
COLETA = RAIZ / "api" / "jornada" / "coleta.py"
CLIENTE = RAIZ / "api" / "jornada" / "cliente.py"
LEITURA = RAIZ / "api" / "jornada" / "leitura.py"
MIG = RAIZ / "sql" / "cortex" / "0021_jornada.sql"
HTML = RAIZ / "api" / "static" / "index.html"


@pytest.fixture(autouse=True)
def _sem_credencial(monkeypatch):
    """NENHUM teste desta suíte fala com a RasterJOR de verdade.

    No dia em que o token entrou no cofre, três testes que exercitam a recusa
    por FALTA de credencial passaram a chamar a API do fornecedor — e a falha
    apareceu como `HTTP 400 em motoristas`, que é a API real respondendo. Um
    teste que só passa em máquina sem credencial não testa nada: ele mede o
    .env de quem rodou. Quem precisa de cliente configurado configura no
    próprio teste, com `_configura(monkeypatch)`.
    """
    monkeypatch.setattr(cliente, "_cred", lambda nome: "")


def _configura(monkeypatch, **extra):
    """Cliente configurado, sem tocar no cofre nem na rede."""
    vals = {"RASTERJOR_API_BASE_URL": "https://exemplo.invalido/external-api",
            "RASTERJOR_TOKEN": "segredo-de-teste"}
    vals.update(extra)
    monkeypatch.setattr(cliente, "_cred", lambda nome: vals.get(nome, ""))


class _Resposta:
    """Dublê de resposta HTTP para `urlopen`, no formato de context manager."""

    def __init__(self, corpo: str):
        self._corpo = corpo.encode("utf-8")

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture()
def esq(esquema_pg):
    coleta.ESQUEMA = esquema_pg
    try:
        yield esquema_pg
    finally:
        coleta.ESQUEMA = None


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def _jornada(**kw) -> dict:
    d = {"driver_document": "111", "driver_name": "Fulano",
         "branch_name": "MTZ", "work_schedule_name": "ESCALA",
         "date": "2026-03-10", "journey_type": "N",
         "total_time": 600, "driving_time": 200, "stopped_in_journey_time": 300,
         "meal_time": 60, "rest_time": 40, "repose_time": 660,
         "over_time": 90, "missing_time": 0, "missing_repose_time": 30,
         "activity_time": 560, "activity_time_over_max_time": 0,
         "kilometers_driven": 420.5}
    d.update(kw)
    return d


# ─────────────────────────────────────────────── grava no banco do CÓRTEX

def test_a_jornada_e_gravada_no_banco_local(esq):
    """O ponto da mudança: o dado passa a ser NOSSO. A rotina que alimentava
    `sulista.rasterjor_*` é externa e ficou 136 dias parada sem que o CÓRTEX
    pudesse saber."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        n = coleta._grava_jornadas(cur, [_jornada()], "2026-03-11T08:00:00", "api")
        cx.commit()
    assert n == 1
    r = pglocal.um("SELECT * FROM jor_jornadas", esquema=esq)
    assert r["documento"] == "111" and r["data"] == date(2026, 3, 10)
    assert r["min_parado"] == 300 and r["min_direcao"] == 200
    assert float(r["km"]) == 420.5 and r["origem"] == "api"


def test_recoletar_o_mesmo_dia_atualiza_em_vez_de_duplicar(esq):
    """Recoletar é o caso NORMAL: a API devolve o dia inteiro a cada chamada e
    o dia só fecha à noite."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada()], "t1", "api")
        coleta._grava_jornadas(cur, [_jornada(driving_time=999)], "t2", "api")
        cx.commit()
    linhas = pglocal.query("SELECT * FROM jor_jornadas", esquema=esq)
    assert len(linhas) == 1, "recoleta duplicou a jornada"
    assert linhas[0]["min_direcao"] == 999, "recoleta não atualizou"


def test_inconformidade_SEM_hora_de_inicio_entra(esq):
    """56% das inconformidades não têm `event_start` — EXCESSO DE JORNADA,
    JORNADA SEM PARADA PARA REFEICAO e NAO CUMPRIMENTO DO INTERVALO nunca têm,
    porque são fato do DIA. A primeira versão do loader as descartava: 55.017
    de 98.109 linhas, justamente os tipos mais frequentes."""
    linhas = [
        {"driver_document": "111", "unconformity_type": "EXCESSO DE JORNADA",
         "unconformity_date": "2026-03-10", "event_start": None},
        {"driver_document": "111", "unconformity_type": "DIRECAO NOTURNA",
         "unconformity_date": "2026-03-10",
         "event_start": "2026-03-10T23:10:00", "duration_minutes": 84},
    ]
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        assert coleta._grava_inconformidades(cur, linhas, "t", "api") == 2
        cx.commit()
    r = pglocal.query("SELECT tipo, inicio, chave_evento FROM jor_inconformidades"
                      " ORDER BY tipo", esquema=esq)
    assert len(r) == 2
    sem_hora = [x for x in r if x["tipo"] == "EXCESSO DE JORNADA"][0]
    # `inicio` fica NULO: preencher com meia-noite inventaria um horário que a
    # fonte não deu, e horário inventado vira gráfico.
    assert sem_hora["inicio"] is None
    assert sem_hora["chave_evento"] == datetime(2026, 3, 10, 0, 0)


def test_inconformidade_sem_hora_tambem_e_idempotente(esq):
    """Um UNIQUE sobre `inicio` nulo não restringe nada — no Postgres NULL é
    sempre distinto de NULL —, então as 55 mil duplicariam a cada recarga. É
    para isso que existe `chave_evento`."""
    linha = {"driver_document": "111", "unconformity_type": "EXCESSO DE JORNADA",
             "unconformity_date": "2026-03-10", "event_start": None}
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_inconformidades(cur, [linha, dict(linha)], "t", "api")
        coleta._grava_inconformidades(cur, [dict(linha)], "t2", "api")
        cx.commit()
    n = pglocal.um("SELECT count(*)::int c FROM jor_inconformidades",
                   esquema=esq)["c"]
    assert n == 1, f"duplicou: {n} linhas para o mesmo evento"


def test_toda_passagem_grava_na_trilha_inclusive_a_que_falhou(esq):
    """É `jor_carga` que faz a Saúde descobrir uma parada no dia em que ela
    acontece. A rotina anterior vivia no AVA e ficou 136 dias parada porque o
    único sintoma era uma tela vazia."""
    r = coleta.coletar(esquema=esq)          # sem credencial: recusa
    assert r["ok"] is False and "RasterJOR" in r["erro"]
    t = pglocal.query("SELECT * FROM jor_carga", esquema=esq)
    assert len(t) == 1 and t[0]["ok"] == 0
    assert "RASTERJOR_API_BASE_URL" in t[0]["mensagem"]


def test_sem_credencial_a_coleta_recusa_dizendo_o_que_falta(esq):
    """Mensagem que manda a pessoa adivinhar é mensagem que gera chamado."""
    r = coleta.coletar(esquema=esq)
    assert "Gestão › Integrações" in r["erro"]
    assert not cliente.configurado()


def test_nulo_da_api_nao_vira_zero_silencioso(esq):
    """`kilometers_driven` e as datas vêm nulas em dia sem jornada."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(kilometers_driven=None,
                                              start=None, end=None,
                                              total_time=None)], "t", "api")
        cx.commit()
    r = pglocal.um("SELECT km, inicio, min_total FROM jor_jornadas", esquema=esq)
    assert r["km"] is None and r["inicio"] is None
    assert r["min_total"] == 0          # coluna NOT NULL: zero é o certo aqui


# ─────────────────────────────────────────────────────────── leitura

def test_a_janela_e_ancorada_no_ultimo_dado(esq):
    """Com a coleta parada, uma janela contada de hoje devolveria tela vazia —
    que se lê como "ninguém rodou" em vez de "parou de chegar"."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(date="2026-03-10")], "t", "api")
        cx.commit()
    d = leitura.get_jornada_raster(esquema=esq)
    assert d["ate"] == "2026-03-10", "a janela deveria terminar no último dado"
    assert d["kpis"]["jornadas"] == 1


def test_a_defasagem_distingue_o_que_veio_da_api_do_que_veio_do_ava(esq):
    """No dia em que os números divergirem, é a coluna `origem` que responde."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(driver_document="1")], "t", "api")
        coleta._grava_jornadas(cur, [_jornada(driver_document="2")], "t", "ava")
        cx.commit()
    d = leitura.defasagem(esq)
    assert d["da_api"] == 1 and d["do_ava"] == 1
    assert d["coleta_configurada"] is False


def test_a_razao_parado_direcao_e_calculada(esq):
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada()], "t", "api")
        cx.commit()
    k = leitura.get_jornada_raster(esquema=esq)["kpis"]
    # 300 min parado / 200 min direção = 1,50 exato. Se sair 1,52, a conta
    # está sendo feita sobre as horas já arredondadas.
    assert k["razao_parado_direcao"] == 1.5


# ─────────────────────────────────────────── disciplina que não pode voltar

def test_o_cliente_nao_inventa_a_url_do_fornecedor():
    """Adivinhar host no melhor caso dá 404 e no pior acerta o endpoint de
    outra empresa."""
    fonte = CLIENTE.read_text(encoding="utf-8")
    assert "NÃO INVENTA A URL" in fonte
    assert "rastergr" not in fonte and "rastersistemas.com" not in fonte


def test_o_erro_do_fornecedor_passa_por_sanitizacao():
    """A lição é da Z-API, onde a URL ERA a credencial e `str(exc)` a despejava
    na tela, no log e na trilha."""
    fonte = CLIENTE.read_text(encoding="utf-8")
    assert "def _sanitizar(" in fonte
    assert "RASTERJOR_SENHA" in fonte


@pytest.mark.parametrize("corpo", [
    '[{"a": 1}, {"a": 2}]',                       # produtividade, motoristas
    '{"items": [{"a": 1}, {"a": 2}], "total_pages": 1}',   # inconformidades
])
def test_resposta_lista_no_topo_e_envelope_sao_tratadas(monkeypatch, corpo):
    """A MESMA API mistura as duas formas, e enfiar uma lista num `dict.get()`
    devolve "nenhum registro" sem erro nenhum — foi o que aconteceu com o
    `/groups` da Z-API.

    Asserção sobre COMPORTAMENTO e não sobre o texto do módulo: a versão
    anterior procurava `'"data", "results", "items"'` na fonte e quebrou quando
    a ordem das chaves mudou, sem que nada tivesse deixado de funcionar.
    """
    _configura(monkeypatch)
    monkeypatch.setattr(cliente.urllib.request, "urlopen",
                        lambda *a, **k: _Resposta(corpo))
    linhas, _ = cliente.chamar("motoristas")
    assert [d["a"] for d in linhas] == [1, 2]


def test_200_que_e_recusa_nao_vira_registro(monkeypatch):
    """O limite de taxa da RasterJOR NÃO vem como 429: vem HTTP 200 com
    `{"mensagem": "Faltam 10 minutos…"}`. Quem confia no código de status conta
    isso como UM registro — foi o que a trilha mostrou antes do conserto:
    janelas de 7 e de 93 dias "trazendo 1 registro" em 145 ms."""
    _configura(monkeypatch)
    monkeypatch.setattr(
        cliente.urllib.request, "urlopen",
        lambda *a, **k: _Resposta(
            '{"mensagem": "Faltam 10 minutos para fazer outra consulta"}'))
    with pytest.raises(cliente.RasterRecusou) as e:
        cliente.chamar("motoristas")
    assert "10 minutos" in str(e.value)


def test_a_janela_e_fatiada_no_teto_da_api(monkeypatch):
    """A API recusa período acima de 31 dias, e recusa de DUAS formas: HTTP 400
    nas inconformidades, HTTP 200 com mensagem nas ausências. O cliente fatia
    sozinho — sem isso, preencher o buraco de quatro meses exigiria oito
    comandos à mão."""
    _configura(monkeypatch)
    pedidas: list[str] = []

    def _falso(req, *a, **k):
        pedidas.append(req.full_url)
        return _Resposta("[]")

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _falso)
    cliente.chamar("ausencias", de="2026-01-01", ate="2026-03-31")
    assert len(pedidas) == 3          # 90 dias em fatias de 31
    assert "2026-01-01" in pedidas[0] and "2026-03-31" in pedidas[-1]


def test_a_espera_pedida_pela_api_e_respeitada_ate_um_teto():
    """A recusa DIZ quantos segundos esperar, então o cliente espera e repete.
    Mas dormir os DEZ MINUTOS que o relatório de produtividade pede seria pior
    que a recusa: acima do teto ela sobe, com o motivo."""
    assert cliente._espera_pedida("aguarde 30 segundos.") == 30
    assert cliente._espera_pedida("Faltam 10 minutos") == 600
    assert cliente._espera_pedida("HTTP 400: período inválido") == 0
    assert cliente._espera_pedida("Faltam 10 minutos") > cliente.ESPERA_MAX_S


def test_a_inconformidade_aceita_o_vocabulario_da_api_e_o_do_ava(esq):
    """A API e a tabela do AVA chamam os MESMOS campos por nomes diferentes, e
    a coleta lê da primeira enquanto a carga inicial lê da segunda. Medido na
    primeira coleta real: 425 registros lidos e ZERO gravados, porque o
    gravador só conhecia o vocabulário do AVA."""
    da_api = {"driver_document": "1", "driver_name": "F", "plate": "MOBILE",
              "unconformity": "EXCESSO DE JORNADA", "date": "2026-08-21",
              "start": None, "end": None, "duration_minutes": 0}
    do_ava = {"driver_document": "2", "driver_name": "G", "plate": "ABC1D23",
              "unconformity_type": "DIRECAO NOTURNA",
              "unconformity_date": "2026-08-21",
              "event_start": "2026-08-21 23:10:00",
              "event_end": "2026-08-22 01:00:00", "duration_minutes": 110}
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        assert coleta._grava_inconformidades(cur, [da_api], "t", "api") == 1
        assert coleta._grava_inconformidades(cur, [do_ava], "t", "ava") == 1
        cx.commit()
    linhas = pglocal.query(
        "SELECT documento, tipo, inicio FROM jor_inconformidades"
        " ORDER BY documento", esquema=esq)
    assert [r["tipo"] for r in linhas] == ["EXCESSO DE JORNADA",
                                           "DIRECAO NOTURNA"]
    # `inicio` guarda a VERDADE: nulo quando a fonte não deu hora.
    assert linhas[0]["inicio"] is None and linhas[1]["inicio"] is not None


def test_a_migration_explica_a_chave_do_evento():
    sql = MIG.read_text(encoding="utf-8")
    assert "chave_evento" in sql
    assert "NULL é" in sql and "sempre distinto de NULL" in sql
    assert "UNIQUE (documento, tipo, chave_evento)" in sql


def test_as_credenciais_estao_no_cofre_e_no_panorama():
    """O usuário vai colar o token em Gestão › Integrações: o campo tem de
    estar lá."""
    from api import credenciais
    for campo in ("RASTERJOR_API_BASE_URL", "RASTERJOR_TOKEN"):
        assert campo in credenciais.CAMPOS, campo
    svc = [s for s in credenciais.SERVICOS if s["chave"] == "rasterjor"]
    assert svc, "RasterJOR não aparece no panorama de integrações"
    assert svc[0]["alimenta"] == "Jornada RasterJOR"


def test_a_saude_separa_nao_configurado_de_parado():
    """Sem credencial NÃO é falha: é instalação que ainda não ligou a coleta.
    Marcar erro ali ensinaria a ignorar o vermelho."""
    fonte = (RAIZ / "api" / "servidor.py").read_text(encoding="utf-8")
    assert "coleta_configurada" in fonte
    assert "não é falha" in fonte or "NÃO é falha" in fonte
    assert "falhas_48h" in fonte


def test_o_script_da_tarefa_agendada_existe():
    p = RAIZ / "scripts" / "coletar_jornada.py"
    assert p.exists()
    fonte = p.read_text(encoding="utf-8")
    assert "--carga-ava" in fonte
    assert "Rodar duas vezes é seguro" in fonte


def test_a_rota_de_coleta_nao_trava_o_event_loop():
    """Rota `async def` com I/O de rede trava o CÓRTEX inteiro pelo tempo da
    chamada — foi assim que o envio de WhatsApp derrubou o painel por minutos."""
    fonte = (RAIZ / "api" / "main.py").read_text(encoding="utf-8")
    i = fonte.index("async def jornada_coletar(")
    trecho = fonte[i:i + 2200]
    assert "sem_travar(" in trecho
    assert "HTTP_RECUSA" in trecho, "sem credencial é recusa (4xx), não 5xx"


def test_o_leitor_do_ava_saiu_do_pacote():
    """Módulo órfão volta a ser importado por engano."""
    assert not (RAIZ / "api" / "jornada" / "raster.py").exists()
    assert not (RAIZ / "api" / "jornada" / "espera.py").exists()
    # as CONSULTAS, e não o docstring que explica o que foi substituído
    consultas = [v for k, v in vars(leitura).items()
                 if k.startswith("_") and isinstance(v, str) and "SELECT" in v]
    assert consultas
    for q in consultas:
        assert "sulista." not in q, "voltou a ler o AVA"
        assert "jor_" in q


def test_a_tela_esta_registrada(html):
    """A tela da RasterJOR ASSUMIU o id `jorn`, que era da apuração do ERP.

    Reusar o id em vez de criar um novo tem uma razão prática: as concessões
    de RBAC já existentes (a migration v3 deu `jorn` aos perfis Operação e
    Diretoria) continuam valendo, e quem tinha a tela ontem continua tendo
    hoje. Um id novo exigiria migration só para devolver o acesso que as
    pessoas já tinham — e, no intervalo, a jornada sumiria do menu de todo
    mundo que não é administrador. Favorito antigo (#jorn) também continua
    abrindo.
    """
    for marca in ('id="view-jorn"', "jorn:loadJorraster", 'href="#jorn"'):
        assert marca in html, marca
    # a apuração do ERP saiu inteira: tela, ficha e o JS das duas
    for morta in ('id="view-jornf"', "loadJornf", "renderJorn(", "DATAJORN",
                  "jorraster", "abrirJornf"):
        assert morta not in html, f"sobrou {morta}"


# ── A COBERTURA DA COLETA ────────────────────────────────────────────────────
# Estes quatro testes existem por causa de um desenho que quase foi ao ar: a
# série mensal saía de um `GROUP BY mês`, que simplesmente NÃO DEVOLVE o mês
# sem linha. Maio, junho e julho de 2026 não têm uma jornada (a coleta externa
# ficou parada de 15/04 a 27/08), então o gráfico emendava abril em agosto e
# desenhava uma série contínua. Quem olha lê queda de operação.


def test_mes_sem_coleta_aparece_na_serie_em_vez_de_sumir(esq):
    """O mês vazio tem de EXISTIR no eixo, marcado — se ele some, dois meses
    distantes ficam lado a lado sugerindo continuidade."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(date="2026-01-10")], "t", "api")
        coleta._grava_jornadas(cur, [_jornada(date="2026-04-10")], "t", "api")
        cx.commit()
    d = leitura.get_jornada_raster("2026-01-01", "2026-04-30", esquema=esq)
    meses = [m["mes"] for m in d["mensal"]]
    assert meses == ["2026-01", "2026-02", "2026-03", "2026-04"]
    vazios = [m["mes"] for m in d["mensal"] if m["sem_coleta"]]
    assert vazios == ["2026-02", "2026-03"]
    assert d["meses_sem_coleta"] == vazios
    assert d["kpis"]["meses_sem_coleta"] == 2


def test_mes_de_cobertura_parcial_e_marcado_e_tem_media_por_dia(esq):
    """Outubro/25 tinha 10 dias de dado e 1.206 jornadas contra 3.672 de
    setembro: parece despencar, mas por dia coletado são 121 contra 122 —
    está plano. A barra hachura e o número comparável é o POR DIA."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        for dia in ("2026-01-05", "2026-01-06"):
            coleta._grava_jornadas(
                cur, [_jornada(date=dia, driver_document="1"),
                      _jornada(date=dia, driver_document="2")], "t", "api")
        cx.commit()
    m = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["mensal"][0]
    assert m["dias"] == 2 and m["dias_possiveis"] == 31
    assert m["parcial"] is True and m["sem_coleta"] is False
    assert m["jornadas"] == 4 and m["jornadas_dia"] == 2.0


def test_o_divisor_da_cobertura_e_o_recorte_e_nao_o_mes_inteiro(esq):
    """Uma janela que começa no meio do mês não torna o mês parcial: o divisor
    é o que cabe DENTRO do recorte pedido, senão o primeiro mês sempre
    apareceria com cobertura pela metade sem faltar coleta nenhuma."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        for d_ in ("2026-01-30", "2026-01-31"):
            coleta._grava_jornadas(cur, [_jornada(date=d_)], "t", "api")
        cx.commit()
    m = leitura.get_jornada_raster("2026-01-30", "2026-01-31",
                                   esquema=esq)["mensal"][0]
    assert m["dias_possiveis"] == 2 and m["cobertura"] == 1.0
    assert m["parcial"] is False


def test_mes_fechado_com_domingo_sem_jornada_nao_vira_parcial(esq):
    """O corte de parcial é 90%, não 100%: mês normal tem dia sem jornada
    (domingo, feriado), e marcar isso como falha hachuraria a série toda."""
    from datetime import date as _d, timedelta as _td
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        dia = _d(2026, 1, 1)
        while dia <= _d(2026, 1, 29):        # 29 de 31 dias = 93,5%
            coleta._grava_jornadas(cur, [_jornada(date=dia.isoformat())],
                                   "t", "api")
            dia += _td(days=1)
        cx.commit()
    m = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["mensal"][0]
    assert m["dias"] == 29 and m["parcial"] is False


# ── O DENOMINADOR DA TAXA ────────────────────────────────────────────────────


def test_a_taxa_por_jornada_so_usa_dias_que_tem_os_dois_lados(esq):
    """A armadilha que este teste tranca custou um número dez vezes errado.

    Os recursos da API têm limites diferentes — o relatório de produtividade
    aceita UMA consulta a cada 10 minutos, as inconformidades não —, então é
    normal a coleta ter três meses de inconformidade e uma semana de jornada.
    A divisão ingênua entre as duas contagens deu 8,55 inconformidades por
    jornada onde o real é 0,67: o numerador tinha 90 dias e o denominador 8.
    """
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        # jornada só no dia 10
        coleta._grava_jornadas(cur, [_jornada(date="2026-01-10")], "t", "api")
        # inconformidade no dia 10 (pareada) e no dia 20 (sem jornada)
        coleta._grava_inconformidades(cur, [
            {"driver_document": "111", "unconformity": "EXCESSO DE JORNADA",
             "date": "2026-01-10"},
            {"driver_document": "111", "unconformity": "EXCESSO DE JORNADA",
             "date": "2026-01-20"},
            {"driver_document": "111", "unconformity": "DIRECAO ININTERRUPTA",
             "date": "2026-01-20"},
        ], "t", "api")
        cx.commit()
    k = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["kpis"]
    assert k["jornadas"] == 1
    assert k["unconformidades"] == 3          # a contagem é a real
    assert k["unconf_por_jornada"] == 1.0     # mas a TAXA usa só o dia pareado
    assert k["unconf_fora_do_pareamento"] == 2
    assert k["dias_pareados"] == 1


# ── TEMPO × MARCAÇÃO ─────────────────────────────────────────────────────────


def test_direcao_noturna_nao_entra_no_kpi_de_conformidade(esq):
    """DIRECAO NOTURNA é 35% dos eventos e NÃO É VIOLAÇÃO de nada: é trabalho
    noturno, que é legal e gera adicional. Somada ao resto, inflava a taxa por
    jornada em um terço — e o KPI que decide ação passaria a medir escala de
    operação em vez de risco trabalhista."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(date="2026-01-10")], "t", "api")
        coleta._grava_inconformidades(cur, [
            {"driver_document": "111", "unconformity": "DIRECAO NOTURNA",
             "date": "2026-01-10"},
            {"driver_document": "111", "unconformity": "EXCESSO DE JORNADA",
             "date": "2026-01-10"},
        ], "t", "api")
        cx.commit()
    d = leitura.get_jornada_raster("2026-01-01", "2026-01-31", esquema=esq)
    k = d["kpis"]
    assert k["unconformidades"] == 2 and k["unconf_tempo"] == 1
    assert k["unconf_tempo_por_jornada"] == 1.0
    assert k["pct_noturna"] == 50.0
    classes = {u["tipo"]: u["classe"] for u in d["unconformidades"]}
    assert classes["DIRECAO NOTURNA"] == "fora"
    assert classes["EXCESSO DE JORNADA"] == "tempo"


def test_tipo_novo_do_fornecedor_entra_como_tempo(esq):
    """Errar para o lado de MOSTRAR o risco. Um tipo que ninguém viu ainda
    caindo num balde silencioso é o jeito de descobrir tarde."""
    assert leitura._classe("ALGO QUE A RASTER INVENTOU AMANHA") == "tempo"
    assert leitura._classe("DIRECAO NOTURNA") == "fora"


def test_o_ranking_de_motorista_traz_o_denominador(esq):
    """Sem o número de jornadas ao lado, o ranking premia quem rodou mais
    dias: quem faz 90 jornadas aparece na frente de quem faz 12, mesmo tendo
    taxa menor."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        for i in range(4):
            coleta._grava_jornadas(
                cur, [_jornada(date=f"2026-01-0{i+1}", driver_document="1",
                               driver_name="MUITAS JORNADAS")], "t", "api")
        coleta._grava_jornadas(
            cur, [_jornada(date="2026-01-01", driver_document="2",
                           driver_name="UMA JORNADA")], "t", "api")
        coleta._grava_inconformidades(cur, [
            {"driver_document": "1", "unconformity": "EXCESSO DE JORNADA",
             "date": f"2026-01-0{i+1}"} for i in range(4)
        ] + [
            {"driver_document": "2", "unconformity": "EXCESSO DE JORNADA",
             "date": "2026-01-01"},
        ], "t", "api")
        cx.commit()
    M = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["unconf_motoristas"]
    # As inconformidades acima NÃO trazem `driver_name` — é o caso real, e é
    # por isso que o nome cai de volta para o da jornada. Sem esse fallback a
    # tabela de motoristas aparece com a coluna do motorista em branco.
    por_doc = {m["nome"]: m for m in M}
    assert por_doc["MUITAS JORNADAS"]["n_tempo"] == 4
    assert por_doc["MUITAS JORNADAS"]["jornadas"] == 4
    assert por_doc["MUITAS JORNADAS"]["por_jornada"] == 1.0
    # mesma TAXA, volume bem menor: é por isso que a tela atenua o de baixo
    assert por_doc["UMA JORNADA"]["por_jornada"] == 1.0
    assert por_doc["UMA JORNADA"]["jornadas"] == 1
    # a ordem padrão é a CONTAGEM, não a taxa
    assert M[0]["nome"] == "MUITAS JORNADAS"


def test_a_serie_diaria_existe_e_nao_inventa_dia(esq):
    """A série diária é o que justifica a biblioteca de gráficos nesta tela.
    Ela traz só os dias QUE EXISTEM: o gráfico usa eixo de tempo, então o vão
    aparece como vão em vez de virar um zero."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(date="2026-01-05")], "t", "api")
        coleta._grava_jornadas(cur, [_jornada(date="2026-01-09")], "t", "api")
        cx.commit()
    D = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["diario"]
    assert [x["dia"] for x in D] == ["2026-01-05", "2026-01-09"]


# ── A TELA ───────────────────────────────────────────────────────────────────


def test_a_tela_desenha_os_quatro_graficos_com_echarts(html):
    """ECharts entra aqui pelo critério do CLAUDE.md: a série diária tem
    centenas de pontos e precisa de zoom. Os contêineres têm altura explícita
    porque o ECharts mede o elemento no init — sem altura, desenha 0px."""
    for cid in ("jr-mensal", "jr-diario", "jr-comp", "jr-uncmes"):
        assert f'id="{cid}"' in html, cid
        i = html.index(f'id="{cid}"')
        assert "height:" in html[i:i + 160], f"{cid} sem altura explícita"
    assert "jrMensalEC" in html and "jrDiarioEC" in html
    assert "jrCompEC" in html and "jrUncMesEC" in html
    # carga SOB DEMANDA: a tela usa o carregador, nunca uma tag <script> fixa
    assert html.count("carregarECharts()") >= 4


def test_a_falha_da_biblioteca_e_dita_no_cartao(html):
    """Cartão vazio faria parecer que não houve jornada no período. O arquivo
    vem do nosso disco: não carregar significa deploy quebrado."""
    assert "jrFalhaGrafico" in html
    i = html.index("function jrFalhaGrafico")
    trecho = html[i:i + 600]
    assert "biblioteca de gráficos" in trecho
    assert "continuam corretos" in trecho


def test_a_tarja_fala_da_coleta_propria_e_nao_de_rotina_externa(html):
    """A tarja mudou de recado junto com a integração: antes dizia "a rotina é
    externa, só quem a mantém pode religá-la"; agora o conserto está aqui."""
    i = html.index("function jrTarja")
    trecho = html[i:html.index("function jrMensalEC")]
    assert "não roda no CÓRTEX" not in trecho
    assert "coleta_configurada" in trecho and "falhas_48h" in trecho
    assert "parou de chegar" in trecho


def test_a_taxa_POR_TIPO_tambem_usa_so_os_dias_pareados(esq):
    """O mesmo denominador errado, agora na coluna da tabela.

    Este passou pela primeira revisão e só apareceu ao RENDERIZAR a tela com
    dado real: "3,05 por jornada" em DIRECAO NOTURNA dividia 90 dias de evento
    por 8 dias de jornada. Corrigir o KPI e esquecer a coluna deixa a tabela
    desmentindo o cartão logo acima dela.
    """
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [_jornada(date="2026-01-10")], "t", "api")
        coleta._grava_inconformidades(cur, [
            {"driver_document": "111", "unconformity": "DIRECAO NOTURNA",
             "date": "2026-01-10"},
            {"driver_document": "111", "unconformity": "DIRECAO NOTURNA",
             "date": "2026-01-20"},   # dia sem jornada: conta, mas não divide
            {"driver_document": "222", "unconformity": "DIRECAO NOTURNA",
             "date": "2026-01-21"},
        ], "t", "api")
        cx.commit()
    U = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["unconformidades"]
    noturna = next(u for u in U if u["tipo"] == "DIRECAO NOTURNA")
    assert noturna["n"] == 3            # a contagem do período é a real
    assert noturna["por_jornada"] == 1.0  # 1 pareada ÷ 1 jornada, não 3,00


def test_km_por_hora_usa_so_as_jornadas_que_tem_km(esq):
    """`km` é NULO em 65% das jornadas — o fornecedor não reporta hodômetro em
    todas. Dividir o km de um terço delas pelas HORAS DE TODAS devolvia 35,9
    km/h onde o honesto é 43,2: uma queda de um quarto sem que nada tivesse
    mudado na operação. E o cartão diz a cobertura, porque cobertura ruim de
    campo é informação, não sujeira para esconder."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        coleta._grava_jornadas(cur, [
            _jornada(date="2026-01-10", driver_document="1",
                     kilometers_driven=300, driving_time=300),   # 5 h, 300 km
            _jornada(date="2026-01-10", driver_document="2",
                     kilometers_driven=None, driving_time=300),  # sem km
        ], "t", "api")
        cx.commit()
    k = leitura.get_jornada_raster("2026-01-01", "2026-01-31",
                                   esquema=esq)["kpis"]
    assert k["jornadas"] == 2 and k["jornadas_com_km"] == 1
    assert k["pct_jornadas_com_km"] == 50.0
    # 300 km ÷ 5 h = 60. Com as 10 h das duas jornadas daria 30.
    assert k["km_por_h_direcao"] == 60.0


def test_motoristas_atingidos_nao_e_o_tamanho_do_ranking(esq):
    """O ranking tem teto, e contar as linhas dele daria sempre o teto — o KPI
    diria "40 de 135" tanto para 41 motoristas quanto para 130. A contagem sai
    de uma consulta própria, e a tela DIZ que a lista está cortada."""
    with pglocal.get_conn(esq) as cx:
        cur = cx.cursor()
        n = leitura.RANKING_LIMITE + 5
        coleta._grava_jornadas(cur, [
            _jornada(date="2026-01-10", driver_document=str(i))
            for i in range(n)], "t", "api")
        coleta._grava_inconformidades(cur, [
            {"driver_document": str(i), "unconformity": "EXCESSO DE JORNADA",
             "date": "2026-01-10"} for i in range(n)], "t", "api")
        cx.commit()
    d = leitura.get_jornada_raster("2026-01-01", "2026-01-31", esquema=esq)
    assert len(d["unconf_motoristas"]) == leitura.RANKING_LIMITE
    assert d["kpis"]["motoristas_com_unconf_tempo"] == n
    assert d["kpis"]["ranking_limite"] == leitura.RANKING_LIMITE


# ── A COR DA SAÚDE ───────────────────────────────────────────────────────────
# Regra: VERMELHO é "não está chegando", e só isso. Recusa do fornecedor é
# resposta NORMAL — dois cliques seguidos em "Coletar agora" já produzem uma,
# porque o relatório de produtividade só aceita uma consulta a cada 10 minutos.
# Deixar a Saúde vermelha por 48 h por causa disso ensina a ignorar o vermelho,
# que é o oposto do que a linha existe para fazer.


def _carga(cx, recurso, ok, ts, msg=""):
    cx.cursor().execute(
        "INSERT INTO jor_carga (ts, recurso, ok, lidos, gravados, ms,"
        " mensagem, origem) VALUES (%s,%s,%s,0,0,0,%s,'api')",
        (ts, recurso, 1 if ok else 0, msg))


def test_recusa_ja_superada_nao_deixa_a_saude_vermelha(esq):
    """O caso real: três recusas do fornecedor durante o dia (janela acima de
    31 dias, limite de taxa) e, depois delas, a coleta passando. A última
    passagem de cada recurso deu certo — o dado ESTÁ chegando."""
    from datetime import datetime as _dt
    agora = _dt.now()
    with pglocal.get_conn(esq) as cx:
        coleta._grava_jornadas(
            cx.cursor(), [_jornada(date=agora.date().isoformat())], "t", "api")
        _carga(cx, "jornadas", False, (agora.replace(microsecond=0)).isoformat(),
               "Limite de consultas excedido aguarde 30 segundos.")
        _carga(cx, "jornadas", True, (agora.replace(microsecond=0)).isoformat())
        cx.commit()
    d = leitura.defasagem(esq)
    assert d["falhas_48h"] == 1            # a falha continua registrada
    assert d["recursos_falhando"] == []    # mas a ÚLTIMA passagem deu certo
    assert d["parada"] is False


def test_ultima_passagem_falhando_e_que_acusa(esq):
    """O contrário: o histórico não importa se a tentativa mais recente
    falhou — aí o dado realmente parou de chegar, e a Saúde tem de dizer QUAL
    recurso, porque cada um tem causa e conserto diferentes."""
    from datetime import datetime as _dt
    agora = _dt.now()
    with pglocal.get_conn(esq) as cx:
        coleta._grava_jornadas(
            cx.cursor(), [_jornada(date=agora.date().isoformat())], "t", "api")
        _carga(cx, "inconformidades", True, agora.replace(microsecond=0).isoformat())
        _carga(cx, "inconformidades", False,
               agora.replace(microsecond=0).isoformat(), "HTTP 401")
        cx.commit()
    d = leitura.defasagem(esq)
    assert d["recursos_falhando"] == ["inconformidades"]
