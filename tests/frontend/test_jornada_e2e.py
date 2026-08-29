"""A tela de Jornada RasterJOR, desenhada com ECharts.

O que estes testes protegem, e por que cada um existe:

1. **O JS novo roda sem estourar.** Teste de texto sobre o `index.html` não
   pega `statChip` chamado com a assinatura errada nem paleta lida fora de
   função (TDZ) — pega quem abre a página.
2. **Mês sem coleta aparece como AUSÊNCIA, nunca como zero.** É a correção
   central desta rodada: a coleta externa ficou 136 dias parada e o sintoma
   era uma tela que se lia como "ninguém rodou".
3. **A taxa por jornada não mistura janelas.** Os recursos da API têm limites
   diferentes, então um lado pode ter três meses e o outro uma semana.
4. **A biblioteca não dispensa as regras da casa:** mês parcial hachurado e
   rótulo direto na linha de eixo secundário.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# Payload com o formato REAL da tela, incluindo o buraco de coleta: jan e abr
# têm dado, fev e mar não têm UMA jornada.
PAYLOAD = {
    "defasagem": {"ultimo_dado": "2026-04-30", "dias": 12, "parada": True,
                  "jornadas": 900, "motoristas": 40, "da_api": 900, "do_ava": 0,
                  "falhas_48h": 0, "coleta_configurada": True,
                  "coleta_falta": "", "corte_dias": 7,
                  "ultima_carga": None},
    "kpis": {
        "jornadas": 900, "motoristas": 40, "h_total": 6000.0,
        "h_direcao": 2000.0, "h_parado": 3200.0, "h_extra": 400.0,
        "h_falta": 100.0, "h_repouso": 9000.0, "h_falta_repouso": 25.0,
        "km": 210000, "razao_parado_direcao": 1.6, "pct_parado": 53.3,
        "pct_direcao": 33.3, "unconformidades": 800, "unconf_por_jornada": 0.67,
        "unconf_tempo": 500, "unconf_tempo_por_jornada": 0.41,
        "pct_noturna": 35.8, "km_por_h_direcao": 105.0,
        "dias_com_dado": 45, "dias_no_periodo": 120, "meses_sem_coleta": 2,
        "unconf_pareadas": 600, "unconf_fora_do_pareamento": 200,
        "dias_pareados": 45,
    },
    "partes": [
        {"chave": "direcao", "rotulo": "Direção", "horas": 2000.0, "pct": 33.3},
        {"chave": "parado", "rotulo": "Parado em jornada", "horas": 3200.0, "pct": 53.3},
        {"chave": "refeicao", "rotulo": "Refeição", "horas": 450.0, "pct": 7.5},
        {"chave": "descanso", "rotulo": "Descanso", "horas": 120.0, "pct": 2.0},
    ],
    "diferenca": 230.0,
    "mensal": [
        {"mes": "2026-01", "jornadas": 500, "motoristas": 40, "h_direcao": 1100.0,
         "h_parado": 1700.0, "h_extra": 220.0, "h_total": 3300.0,
         "dias": 31, "dias_possiveis": 31, "cobertura": 1.0, "sem_coleta": False,
         "parcial": False, "jornadas_dia": 16.1, "h_extra_media": 0.44},
        {"mes": "2026-02", "jornadas": 0, "motoristas": 0, "h_direcao": 0.0,
         "h_parado": 0.0, "h_extra": 0.0, "h_total": 0.0,
         "dias": 0, "dias_possiveis": 28, "cobertura": 0.0, "sem_coleta": True,
         "parcial": False, "jornadas_dia": None, "h_extra_media": None},
        {"mes": "2026-03", "jornadas": 0, "motoristas": 0, "h_direcao": 0.0,
         "h_parado": 0.0, "h_extra": 0.0, "h_total": 0.0,
         "dias": 0, "dias_possiveis": 31, "cobertura": 0.0, "sem_coleta": True,
         "parcial": False, "jornadas_dia": None, "h_extra_media": None},
        {"mes": "2026-04", "jornadas": 400, "motoristas": 38, "h_direcao": 900.0,
         "h_parado": 1500.0, "h_extra": 180.0, "h_total": 2700.0,
         "dias": 14, "dias_possiveis": 30, "cobertura": 0.467, "sem_coleta": False,
         "parcial": True, "jornadas_dia": 28.6, "h_extra_media": 0.45},
    ],
    "meses_sem_coleta": ["2026-02", "2026-03"],
    "diario": [
        {"dia": "2026-01-05", "jornadas": 18, "motoristas": 18,
         "h_direcao": 40.0, "h_extra": 8.0},
        {"dia": "2026-01-06", "jornadas": 20, "motoristas": 20,
         "h_direcao": 44.0, "h_extra": 9.0},
        {"dia": "2026-04-20", "jornadas": 29, "motoristas": 28,
         "h_direcao": 62.0, "h_extra": 12.0},
    ],
    "unconf_tipos_mes": ["DIRECAO NOTURNA", "EXCESSO DE JORNADA"],
    "unconf_por_mes": [
        {"mes": "2026-01", "sem_coleta": False,
         "por_tipo": {"DIRECAO NOTURNA": 160, "EXCESSO DE JORNADA": 280}},
        {"mes": "2026-02", "sem_coleta": True, "por_tipo": {}},
        {"mes": "2026-03", "sem_coleta": True, "por_tipo": {}},
        {"mes": "2026-04", "sem_coleta": False,
         "por_tipo": {"DIRECAO NOTURNA": 140, "EXCESSO DE JORNADA": 220}},
    ],
    "unconformidades": [
        {"tipo": "DIRECAO NOTURNA", "n": 300, "motoristas": 30, "horas": 500.0,
         "media_min": 100, "pct": 37.5, "classe": "fora", "por_jornada": 0.33},
        {"tipo": "EXCESSO DE JORNADA", "n": 500, "motoristas": 35, "horas": 300.0,
         "media_min": 36, "pct": 62.5, "classe": "tempo", "por_jornada": 0.56},
    ],
    "unconf_motoristas": [
        {"nome": "MOTORISTA DE MUITAS VIAGENS", "n": 60, "tipos": 4, "dias": 30,
         "n_tempo": 40, "jornadas": 30, "filial": "SULISTA - MTZ",
         "h_extra": 20.0, "por_jornada": 1.33},
        {"nome": "MOTORISTA DE UMA VIAGEM", "n": 3, "tipos": 1, "dias": 1,
         "n_tempo": 3, "jornadas": 1, "filial": "FILIAL JOI",
         "h_extra": 1.0, "por_jornada": 3.0},
    ],
    "filiais": [
        {"filial": "SULISTA - MTZ", "jornadas": 500, "motoristas": 20,
         "h_direcao": 1100.0, "h_parado": 1800.0, "h_extra": 220.0,
         "h_total": 3400.0, "pct_parado": 52.9},
    ],
    "tipos": [{"tipo": "N", "jornadas": 880, "med_direcao_min": 150,
               "med_total_min": 417, "km": 205000}],
    "ausencias": [{"tipo": "FOLGA", "n": 120, "motoristas": 35,
                   "mais_recente": "2026-04-28"}],
    "de": "2026-01-01", "ate": "2026-04-30",
    "atualizado_em": "2026-04-30T18:00:00",
    "fonte": "CÓRTEX · jor_* (banco local)",
}


def _abrir(pg, base_url, *, payload=None, coleta_resp=None):
    erros = []
    baixados = []

    def rota_api(route):
        u = route.request.url
        if "/api/jornada/coletar" in u:
            st, corpo = coleta_resp or (200, {})
            route.fulfill(status=st, content_type="application/json",
                          body=json.dumps(corpo))
            return
        corpo = (ADMIN if "/api/auth/me" in u
                 else (payload if payload is not None else PAYLOAD)
                 if "/api/jornada/raster" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    def rota_vendor(route):
        baixados.append(route.request.url)
        route.continue_()

    pg.route("**/api/**", rota_api)
    pg.route("**/vendor/echarts.min.js", rota_vendor)
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#jorraster")
    return erros, baixados


def test_a_tela_abre_sem_erro_e_desenha_os_quatro_graficos(pagina):
    """O teste mais barato e o que mais pega: JS que estoura no render deixa a
    tela pela metade sem dizer nada."""
    pg, base = pagina
    erros, baixados = _abrir(pg, base)
    for cid in ("#jr-mensal", "#jr-diario", "#jr-comp", "#jr-uncmes"):
        pg.wait_for_selector(f"{cid} svg", timeout=20000)
    assert erros == [], erros
    # UMA carga da biblioteca serve os quatro gráficos
    assert len(baixados) == 1, f"esperava uma carga, veio {len(baixados)}"


def test_mes_sem_coleta_nao_e_desenhado_como_zero(pagina):
    """A correção central desta rodada. Uma barra zerada diz "ninguém dirigiu";
    o que houve foi ausência de coleta, e é isso que o eixo tem de dizer."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#jr-mensal svg", timeout=20000)
    pg.wait_for_timeout(500)
    eixo = pg.inner_text("#jr-mensal")
    assert eixo.lower().count("sem coleta") >= 2, eixo


def test_mes_de_cobertura_parcial_sai_hachurado(pagina):
    """Regra mais antiga dos painéis da casa, agora via `decal` do ECharts."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#jr-mensal svg", timeout=20000)
    pg.wait_for_timeout(500)
    svg = pg.inner_html("#jr-mensal")
    assert "pattern" in svg.lower(), "nenhuma hachura no mês parcial"
    assert "parcial" in pg.inner_text("#jr-mensal").lower()


def test_a_linha_por_dia_coletado_tem_rotulo_direto(pagina):
    """Ela vive num eixo escondido: sem o número em cima do ponto não há como
    ler valor nenhum. É o número que torna meses de cobertura diferente
    comparáveis entre si."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#jr-mensal svg", timeout=20000)
    pg.wait_for_timeout(500)
    txt = pg.inner_text("#jr-mensal")
    assert "16,1" in txt and "28,6" in txt, txt


def test_a_serie_diaria_tem_zoom(pagina):
    """É o zoom que justifica a biblioteca nesta tela — são centenas de dias."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#jr-diario svg", timeout=20000)
    pg.wait_for_timeout(500)
    assert pg.locator("#jr-diario svg").count() >= 1
    # o slider de dataZoom desenha alças próprias
    assert pg.evaluate(
        "document.querySelector('#jr-diario').innerHTML.length") > 2000


def test_a_tarja_avisa_do_buraco_e_do_denominador(pagina):
    """Os dois recados que impedem a leitura errada: meses sem coleta não são
    meses sem operação, e a taxa por jornada não mistura janelas."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#jr-tarja .toast", timeout=20000)
    t = pg.inner_text("#jr-tarja").lower()
    assert "sem coleta nenhuma" in t
    assert "os dois lados" in t
    assert "parou de chegar" in t


def test_o_kpi_de_conformidade_exclui_a_direcao_noturna(pagina):
    """Direção noturna é 35% dos eventos e não é violação de nada. O KPI que
    decide ação mostra 500, não 800."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#kpis-jr2 .kpi", timeout=20000)
    t = pg.inner_text("#kpis-jr2")
    assert "500" in t
    assert "35,8% é direção noturna" in t.replace("\n", " ")


def test_motorista_de_baixo_volume_e_atenuado_e_nao_escondido(pagina):
    """Registro de baixo volume é atenuado com marca, nunca removido: quem tem
    1 jornada e 3 ocorrências tem taxa 3,00 e não pode liderar nada."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#jr-motoristas tr", timeout=20000)
    linhas = pg.locator("#jr-motoristas tr")
    assert linhas.count() == 2
    assert "MOTORISTA DE UMA VIAGEM" in pg.inner_text("#jr-motoristas")
    assert "baixo volume" in pg.inner_text("#jr-motoristas").lower()
    # a ordem é a CONTAGEM, não a taxa: quem tem taxa 3,00 fica em segundo
    assert "MUITAS VIAGENS" in linhas.nth(0).inner_text()


def test_sem_jornada_no_periodo_o_grafico_diz_isso(pagina):
    """Cartão vazio faria parecer erro da tela. E o `gx-vazio` não pode ser a
    mesma frase para "não houve" e "não chegou"."""
    pg, base = pagina
    vazio = {**PAYLOAD, "mensal": [], "diario": [], "partes": [],
             "unconf_por_mes": [], "unconf_tipos_mes": []}
    _abrir(pg, base, payload=vazio)
    pg.wait_for_selector("#jr-mensal", timeout=20000)
    pg.wait_for_timeout(600)
    assert "sem série no período" in pg.inner_text("#jr-mensal")
    assert "sem dia com jornada" in pg.inner_text("#jr-diario")


def test_o_botao_de_coleta_so_aparece_com_a_coleta_configurada(pagina):
    """Oferecer uma ação que vai recusar por falta de credencial é convidar ao
    erro — e a tarja logo acima já diz qual campo preencher."""
    pg, base = pagina
    sem = {**PAYLOAD, "defasagem": {**PAYLOAD["defasagem"],
                                    "coleta_configurada": False,
                                    "coleta_falta": "falta RASTERJOR_TOKEN"}}
    _abrir(pg, base, payload=sem)
    pg.wait_for_selector("#kpis-jr .kpi", timeout=20000)
    assert pg.locator("#jr-acao").is_hidden()
    assert "RASTERJOR_TOKEN" in pg.inner_text("#jr-tarja")


def test_a_coleta_pela_tela_relata_o_que_gravou(pagina):
    """A tela usa o MESMO caminho da tarefa agendada: mesma janela, mesma
    trilha, mesma auditoria. Não existe modo teste mais frouxo."""
    pg, base = pagina
    resp = (200, {"ok": True, "de": "2026-04-24", "ate": "2026-04-30",
                  "erro": "", "recursos": {
                      "motoristas": {"ok": True, "lidos": 300, "gravados": 300},
                      "jornadas": {"ok": True, "lidos": 640, "gravados": 640}}})
    _abrir(pg, base, coleta_resp=resp)
    pg.wait_for_selector("#btnJrColetar", timeout=20000)
    pg.click("#btnJrColetar")
    pg.wait_for_function(
        "document.getElementById('jrColetaMsg').textContent.includes('gravados')",
        timeout=20000)
    t = pg.inner_text("#jrColetaMsg")
    assert "jornadas: 640 gravados" in t
    assert "24/04/2026" in t and "30/04/2026" in t


def test_recusa_da_coleta_e_MENSAGEM_e_nao_erro_de_api(pagina):
    """RECUSA NÃO É 5xx. 409 é o CÓRTEX dizendo não, com um motivo que a pessoa
    precisa ler — limite de taxa do fornecedor, credencial faltando. Tratar
    isso como falha genérica manda procurar defeito onde não há."""
    pg, base = pagina
    resp = (409, {"erro": "nao_configurado",
                  "mensagem": "Faltam 10 minutos para fazer outra consulta"})
    _abrir(pg, base, coleta_resp=resp)
    pg.wait_for_selector("#btnJrColetar", timeout=20000)
    pg.click("#btnJrColetar")
    pg.wait_for_function(
        "document.getElementById('jrColetaMsg').textContent.includes('minutos')",
        timeout=20000)
    assert "Faltam 10 minutos" in pg.inner_text("#jrColetaMsg")
    # o botão volta a funcionar: recusa não deixa a tela travada
    assert pg.locator("#btnJrColetar").is_enabled()
