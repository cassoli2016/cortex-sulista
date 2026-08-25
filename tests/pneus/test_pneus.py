"""Pneus/Prolog: denominador, cobertura e o que nao pode vazar.

Roda contra um dube de HTTP — o modulo fica escrito e verificado antes de a
credencial existir, como foi feito com a Monkey.
"""
import json

import pytest

from api.pneus import analise as an
from api.pneus import cliente as cli


# --------------------------------------------------------------------- dube
def _resp(corpo, status=200):
    return status, json.dumps(corpo).encode()


def _pagina(itens, ultima=True):
    return {"content": itens, "pageSize": len(itens), "pageNumber": 0,
            "numberOfElements": len(itens), "empty": not itens,
            "lastPage": ultima, "totalElements": len(itens)}


class HttpFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __call__(self, url, headers, timeout, dados=None):
        self.chamadas.append({"url": url, "headers": headers, "dados": dados})
        return self.respostas.pop(0)


@pytest.fixture
def com_token(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "PROLOG_TOKEN": "tok-secreto", "PROLOG_FILIAIS": "10,20"}.get(n, ""))


PNEU = {
    "id": 1, "serialNumber": "ABC123", "dot": "3524", "status": "INSTALLED",
    "branchOfficeName": "MATRIZ", "currentLifeCycle": 2, "timesRetreaded": 1,
    "maxRetreadsExpected": 3, "maxLifeCycles": 4,
    "recommendedPressure": 120.0, "currentPressure": 118.0,
    "innerTreadDepth": 8.0, "middleInnerTreadDepth": 8.2,
    "middleOuterTreadDepth": 7.9, "outerTreadDepth": 8.1,
    "smallestTreadDepth": 7.9, "purchaseCost": 2400.0, "cpk": 0.19,
    "previousTotalKilometersDriven": 90000,
    "make": {"name": "MICHELIN"}, "model": {"name": "X MULTI D"},
    "tireSize": {"formatted": "295/80R22.5"},
    "installed": {"licensePlate": "ABC1D23", "installedPositionName": "1E",
                  "installedAxle": 1, "onSteeringAxle": True,
                  "vehicleTypeName": "CAVALO"},
    "tireLifecycles": [{"lifecycle": 1, "totalDistanceDriven": 60000, "cpk": 0.22}],
}


# ------------------------------------------------------------- configuracao
def test_sem_credencial_a_integracao_fica_desligada(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: "")
    assert cli.configurado() is False and cli.pronto() is False
    with pytest.raises(cli.PrologNaoConfigurado):
        cli.Cliente(http=HttpFalso([]))


def test_credencial_sem_filial_lista_filial_mas_nao_pneu(monkeypatch):
    """`branchOfficesId` e OBRIGATORIO em /api/v3/tires e o id da Sulista so
    existe do lado da Prolog — por isso `pronto()` exige mais que
    `configurado()`."""
    monkeypatch.setattr(cli, "_cred",
                        lambda n: "tok" if n == "PROLOG_TOKEN" else "")
    assert cli.configurado() is True
    assert cli.pronto() is False
    c = cli.Cliente(http=HttpFalso([_resp([{"id": 10, "name": "MATRIZ"}])]))
    assert c.filiais() == [{"id": 10, "name": "MATRIZ"}]
    with pytest.raises(cli.PrologNaoConfigurado):
        c.pneus()


def test_token_com_prefixo_nao_vira_bearer_bearer(monkeypatch):
    """Vale quando o cabecalho e Authorization; no proprio da Prolog o token
    vai puro, seja qual for o conteudo."""
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "PROLOG_TOKEN": "Bearer ja-tem", "PROLOG_AUTH_HEADER": "Authorization",
        "PROLOG_FILIAIS": "10"}.get(n, ""))
    http = HttpFalso([_resp(_pagina([PNEU]))])
    cli.Cliente(http=http).pneus()
    assert http.chamadas[0]["headers"]["Authorization"] == "Bearer ja-tem"


def test_basic_monta_o_cabecalho_certo(monkeypatch):
    import base64
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "PROLOG_USUARIO": "u", "PROLOG_SENHA": "s",
        "PROLOG_FILIAIS": "10"}.get(n, ""))
    http = HttpFalso([_resp(_pagina([PNEU]))])
    cli.Cliente(http=http).pneus()
    esperado = "Basic " + base64.b64encode(b"u:s").decode()
    # Basic e esquema do HTTP: vive no Authorization por definicao, e nao no
    # cabecalho proprio da Prolog (que e o padrao so para token)
    assert http.chamadas[0]["headers"]["Authorization"] == esperado
    assert "X-Prolog-Api-Token" not in http.chamadas[0]["headers"]


def test_a_filial_vai_na_consulta(com_token):
    http = HttpFalso([_resp(_pagina([PNEU]))])
    cli.Cliente(http=http).pneus()
    u = http.chamadas[0]["url"]
    assert "branchOfficesId=10" in u and "branchOfficesId=20" in u


def test_pagina_vazia_encerra_mesmo_sem_lastPage(com_token):
    http = HttpFalso([_resp(_pagina([PNEU], ultima=False)),
                      _resp(_pagina([], ultima=False))])
    assert len(cli.Cliente(http=http).pneus()) == 1
    assert len(http.chamadas) == 2


def test_o_token_nunca_aparece_no_erro(com_token):
    http = HttpFalso([_resp({"erro": "x"}, 500)])
    with pytest.raises(cli.PrologIndisponivel) as e:
        cli.Cliente(http=http).pneus()
    assert "tok-secreto" not in str(e.value)


def test_401_diz_o_que_conferir(com_token):
    http = HttpFalso([_resp({}, 403)])
    with pytest.raises(cli.PrologIndisponivel) as e:
        cli.Cliente(http=http).pneus()
    assert "filiais" in str(e.value)


# ---------------------------------------------------------------- analise
def test_so_pneu_INSTALLED_conta_como_rodando():
    """Pressao de pneu no estoque nao e pressao baixa e sulco de pneu
    sucateado nao e risco. Misturar os quatro estados num denominador so e o
    erro que ja custou uma tela."""
    d = an.analisar([
        PNEU,
        {**PNEU, "id": 2, "status": "INVENTORY", "smallestTreadDepth": 0.5},
        {**PNEU, "id": 3, "status": "DISPOSAL", "smallestTreadDepth": 0.2},
        {**PNEU, "id": 4, "status": "ANALYSIS", "currentPressure": 10.0},
    ])
    k = d["kpis"]
    assert k["total"] == 4 and k["rodando"] == 1
    assert k["abaixo_legal"] == 0, "pneu fora de servico nao e risco de circulacao"
    assert k["pressao_muito_baixa"] == 0
    assert k["por_status"] == {"INSTALLED": 1, "INVENTORY": 1,
                               "DISPOSAL": 1, "ANALYSIS": 1}


def test_sulco_abaixo_do_minimo_legal_e_alarme():
    """1,6 mm e o limite do CONTRAN: abaixo disso o veiculo nao pode circular."""
    d = an.analisar([{**PNEU, "smallestTreadDepth": 1.5}])
    assert d["kpis"]["abaixo_legal"] == 1
    assert d["pneus"][0]["estado_sulco"] == "abaixo do legal"


def test_no_limite_exato_ainda_e_legal():
    assert an.analisar([{**PNEU, "smallestTreadDepth": 1.6}]
                       )["kpis"]["abaixo_legal"] == 0


def test_o_direcional_e_separado():
    """Careca no eixo de direcao e parada imediata, nao agendamento."""
    d = an.analisar([
        {**PNEU, "smallestTreadDepth": 1.0},
        {**PNEU, "id": 2, "smallestTreadDepth": 1.0,
         "installed": {**PNEU["installed"], "onSteeringAxle": False}},
    ])
    assert d["kpis"]["abaixo_legal"] == 2
    assert d["kpis"]["abaixo_legal_direcional"] == 1
    assert d["criticos"][0]["direcional"] is True, "direcional vem primeiro"


def test_sulco_ausente_nao_vira_zero():
    """Campo vazio e ausencia de medida; zero e uma medicao possivel e grave.
    Confundir os dois inventa um pneu careca que ninguem tem."""
    d = an.analisar([{k: v for k, v in PNEU.items()
                      if "TreadDepth" not in k}])
    assert d["pneus"][0]["sulco_menor"] is None
    assert d["pneus"][0]["estado_sulco"] == "sem medida"
    assert d["kpis"]["abaixo_legal"] == 0
    assert d["kpis"]["sulco_cobertura"] == 0


def test_sulco_zero_e_medida_de_verdade():
    d = an.analisar([{**PNEU, "smallestTreadDepth": 0.0}])
    assert d["pneus"][0]["sulco_menor"] == 0.0
    assert d["kpis"]["abaixo_legal"] == 1


def test_pressao_sem_recomendada_nao_produz_desvio():
    """Com recomendada zerada a divisao explodiria, e um pneu sem cadastro
    viraria '-100%'."""
    d = an.analisar([{**PNEU, "recommendedPressure": 0}])
    assert d["pneus"][0]["pressao_desvio"] is None
    assert d["pneus"][0]["estado_pressao"] == "sem medida"
    assert d["kpis"]["pressao_cobertura"] == 0


@pytest.mark.parametrize("atual,esperado", [
    # recomendada = 120; os cortes sao -10%/-20% e +10%/+20%
    (120.0, "ok"),          # 0%
    (110.0, "ok"),          # -8,3% — ainda dentro da faixa
    (108.0, "baixa"),       # -10,0% exato
    (95.0, "muito baixa"),  # -20,8%
    (133.0, "alta"),        # +10,8%
    (145.0, "muito alta"),  # +20,8%
])
def test_faixas_de_pressao(atual, esperado):
    d = an.analisar([{**PNEU, "currentPressure": atual}])
    assert d["pneus"][0]["estado_pressao"] == esperado


def test_cobertura_de_cpk_e_de_custo_sao_devolvidas():
    """Sao os campos mais expostos a cadastro incompleto: valem zero ate
    alguem lancar a nota. Sem a cobertura, um CPK mediano calculado sobre 3 de
    800 pneus passaria como se fosse da frota."""
    d = an.analisar([PNEU, {**PNEU, "id": 2, "cpk": None, "purchaseCost": None},
                     {**PNEU, "id": 3, "cpk": 0, "purchaseCost": 0}])
    k = d["kpis"]
    assert k["cpk_cobertura"] == 1 and k["custo_cobertura"] == 1
    assert k["total"] == 3


def test_cpk_mediano_e_none_quando_ninguem_tem():
    d = an.analisar([{**PNEU, "cpk": None}])
    assert d["kpis"]["cpk_mediana"] is None
    assert d["kpis"]["investido"] is not None  # custo existe, cpk nao


def test_fim_de_vida_usa_o_limite_do_proprio_pneu():
    """maxRetreadsExpected varia por modelo; um numero fixo condenaria pneu
    bom e liberaria pneu no fim."""
    d = an.analisar([
        {**PNEU, "timesRetreaded": 3, "maxRetreadsExpected": 3},
        {**PNEU, "id": 2, "timesRetreaded": 1, "maxRetreadsExpected": 3},
        {**PNEU, "id": 3, "timesRetreaded": 2, "maxRetreadsExpected": None},
    ])
    assert d["kpis"]["fim_de_vida"] == 1


def test_nao_expoe_imagem_nem_nota_fiscal():
    """A API traz URLs de imagem e vinculo de nota; nada disso e preciso para
    decidir troca de pneu, e imagem de sucata carrega placa."""
    d = an.analisar([{**PNEU, "registrationImages": [{"url": "x"}],
                      "invoiceLink": {"id": 9}, "disposal":
                      {"disposalReasonDescription": "DESGASTE",
                       "disposalImagesUrl": ["http://x/1.jpg"]}}])
    p = d["pneus"][0]
    assert "registrationImages" not in p and "invoiceLink" not in p
    assert p["sucata_motivo"] == "DESGASTE"
    assert not any("http" in str(v) for v in p.values())


def test_gravidade_vem_antes_da_posicao_na_lista_de_acao():
    """Circular com sulco abaixo de 1,6 mm e ILEGAL; pressao baixa, por pior
    que seja, nao e. Ordenar so pelo eixo direcional punha um pneu com sulco
    bom e pressao baixa acima de outro fora do limite legal — e o topo de uma
    lista chamada "acao imediata" precisa ser o que para o veiculo primeiro."""
    sem_dir = {**PNEU["installed"], "onSteeringAxle": False}
    d = an.analisar([
        # direcional, sulco OK, pressao critica
        {**PNEU, "id": 1, "currentPressure": 90.0},
        # NAO direcional, mas abaixo do limite legal
        {**PNEU, "id": 2, "smallestTreadDepth": 1.0, "installed": sem_dir},
        # direcional E abaixo do legal — o pior de todos
        {**PNEU, "id": 3, "smallestTreadDepth": 1.2},
    ])
    assert [p["id"] for p in d["criticos"]] == [3, 2, 1]


def test_dentro_da_mesma_gravidade_o_direcional_vem_antes():
    sem_dir = {**PNEU["installed"], "onSteeringAxle": False}
    d = an.analisar([
        {**PNEU, "id": 1, "smallestTreadDepth": 1.0, "installed": sem_dir},
        {**PNEU, "id": 2, "smallestTreadDepth": 1.5},
    ])
    assert [p["id"] for p in d["criticos"]] == [2, 1]


# ------------------------------------------------------------------- base
def test_a_barra_no_fim_da_base_nao_vira_barra_dupla(monkeypatch):
    """A Prolog entrega a URL com barra no fim e os caminhos comecam com
    barra: concatenar daria `//api/v3/tires`. Alguns servidores normalizam,
    outros devolvem 404 — e um 404 aqui pareceria credencial errada."""
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "PROLOG_API_BASE_URL": "https://prologapp.com/prolog/",
        "PROLOG_TOKEN": "t", "PROLOG_FILIAIS": "10"}.get(n, ""))
    assert cli.base_url() == "https://prologapp.com/prolog"
    http = HttpFalso([_resp(_pagina([PNEU]))])
    cli.Cliente(http=http).pneus()
    assert "//api/v3/tires" not in http.chamadas[0]["url"]
    assert http.chamadas[0]["url"].startswith(
        "https://prologapp.com/prolog/api/v3/tires?")


def test_aceita_os_dois_nomes_de_variavel(monkeypatch):
    """O nome que a Prolog entrega e PROLOG_API_BASE_URL; o antigo continua
    valendo para nao quebrar quem ja configurou."""
    monkeypatch.setattr(cli, "_cred",
                        lambda n: "https://x/y" if n == "PROLOG_BASE_URL" else "")
    assert cli.base_url() == "https://x/y"
    monkeypatch.setattr(cli, "_cred",
                        lambda n: "https://a/b" if n == "PROLOG_API_BASE_URL" else "")
    assert cli.base_url() == "https://a/b"


def test_sem_configurar_cai_no_padrao_da_documentacao(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: "")
    assert cli.base_url() == "https://prologapp.com/prolog"


# ------------------------------------------------------ formato do token
def _com(cfg):
    base = {"PROLOG_TOKEN": "abc123", "PROLOG_FILIAIS": "10"}
    return lambda n: {**base, **cfg}.get(n, "")


@pytest.mark.parametrize("cfg,esperado", [
    # PADRAO: cabecalho proprio, token puro — confirmado contra a API
    ({}, {"X-Prolog-Api-Token": "abc123"}),
    ({"PROLOG_AUTH_HEADER": "Authorization"}, {"Authorization": "Bearer abc123"}),
    ({"PROLOG_AUTH_HEADER": "Authorization", "PROLOG_AUTH_PREFIXO": "Token"},
     {"Authorization": "Token abc123"}),
    ({"PROLOG_AUTH_HEADER": "X-API-Key"}, {"X-API-Key": "abc123"}),
    ({"PROLOG_AUTH_HEADER": "apikey", "PROLOG_AUTH_PREFIXO": "k"},
     {"apikey": "k abc123"}),
])
def test_formato_do_token_e_configuravel(monkeypatch, cfg, esperado):
    """Token pode ir como Bearer, puro ou em cabecalho proprio, e nada disso
    esta na documentacao da Prolog. Configuravel para nao virar mexida em
    codigo no dia em que o token chegar."""
    monkeypatch.setattr(cli, "_cred", _com(cfg))
    assert cli.Cliente(http=HttpFalso([])).cabecalhos_auth() == esperado


def test_token_que_ja_traz_esquema_nao_ganha_outro(monkeypatch):
    """Vale so quando o cabecalho e Authorization — o proprio da Prolog leva o
    token puro."""
    for bruto in ("Bearer ja-tem", "Token ja-tem", "Basic ja-tem"):
        monkeypatch.setattr(cli, "_cred", _com(
            {"PROLOG_TOKEN": bruto, "PROLOG_AUTH_HEADER": "Authorization"}))
        assert cli.Cliente(http=HttpFalso([])).cabecalhos_auth() == {
            "Authorization": bruto}


def test_o_cabecalho_configurado_chega_na_chamada(monkeypatch):
    monkeypatch.setattr(cli, "_cred", _com({"PROLOG_AUTH_HEADER": "X-API-Key"}))
    http = HttpFalso([_resp(_pagina([PNEU]))])
    cli.Cliente(http=http).pneus()
    h = http.chamadas[0]["headers"]
    assert h["X-API-Key"] == "abc123" and "Authorization" not in h


# --------------------------------------------------------------- cota e rota
def test_o_cabecalho_padrao_e_o_que_a_prolog_aceita(com_token):
    """Descoberto por sondagem: com `Authorization: Bearer` a Prolog responde
    "Autenticacao invalida, usuario nao encontrado"; com este, 200."""
    http = HttpFalso([_resp(_pagina([PNEU]))])
    cli.Cliente(http=http).pneus()
    h = http.chamadas[0]["headers"]
    assert h["X-Prolog-Api-Token"] == "tok-secreto"
    assert "Authorization" not in h


def test_429_nao_e_tratado_como_credencial_invalida(com_token):
    """A cota da Prolog e por periodo e se recupera sozinha. Chamar isso de
    credencial recusada mandaria conferir a coisa errada — e foi assim que eu
    esgotei a cota varrendo companyId."""
    http = HttpFalso([_resp({"httpStatusCode": 429,
                             "message": "You have exhausted your API Request Quota"}, 429)])
    with pytest.raises(cli.PrologIndisponivel) as e:
        cli.Cliente(http=http).pneus()
    msg = str(e.value)
    assert "cota" in msg.lower() and "recupera sozinha" in msg
    assert "credencial" not in msg.split("nao e credencial")[0].lower()


def test_rota_barrada_para_token_de_api_diz_isso(com_token):
    """/api/v3/retreaders existe, esta documentada e responde "Authorization
    method not allowed for this resource: API". Sem essa distincao a mensagem
    mandaria conferir o token, que esta certo."""
    http = HttpFalso([_resp(
        {"message": "Authorization method not allowed for this resource: API"}, 401)])
    with pytest.raises(cli.PrologIndisponivel) as e:
        cli.Cliente(http=http).pneus()
    assert "so para sessao de usuario" in str(e.value)


# ------------------------------------------------------- coleta retomavel
@pytest.fixture
def snap(tmp_path, monkeypatch):
    from api.pneus import coleta
    monkeypatch.setattr(coleta, "ATUAL", tmp_path / "p.json")
    return coleta


def _pag(ids, ultima=False):
    return _resp(_pagina([{**PNEU, "id": i, "serialNumber": f"S{i}"} for i in ids],
                         ultima=ultima) | {"totalElements": 500})


def test_a_coleta_para_no_teto_e_guarda_onde_parou(snap, com_token):
    """A Prolog tem cota de ~10 requisicoes por janela e uma volta completa
    custa 86: coletar "de uma vez" nao existe aqui."""
    http = HttpFalso([_pag([1, 2]), _pag([3, 4]), _pag([5, 6])])
    r = snap.coletar(status=["INSTALLED"], pausa=0, paginas=3, http=http)
    assert r["paginas_lidas"] == 3 and r["acumulado"] == 6
    assert r["cursor"] == 3 and r["volta_fechou"] is False


def test_a_execucao_seguinte_continua_de_onde_parou(snap, com_token):
    snap.coletar(status=["INSTALLED"], pausa=0, paginas=2,
                 http=HttpFalso([_pag([1, 2]), _pag([3, 4])]))
    http = HttpFalso([_pag([5, 6])])
    r = snap.coletar(status=["INSTALLED"], pausa=0, paginas=1, http=http)
    assert "pageNumber=2" in http.chamadas[0]["url"], "tem de retomar na pagina 2"
    assert r["acumulado"] == 6 and r["novos"] == 2


def test_fim_da_volta_zera_o_cursor_e_conta_a_volta(snap, com_token):
    r = snap.coletar(status=["INSTALLED"], pausa=0, paginas=3,
                     http=HttpFalso([_pag([1, 2]), _pag([3, 4], ultima=True)]))
    assert r["volta_fechou"] is True and r["cursor"] == 0 and r["voltas"] == 1


def test_a_cota_interrompe_sem_perder_o_que_ja_veio(snap, com_token):
    """Parcial e melhor que nada — desde que fique dito, e a tela diz."""
    http = HttpFalso([_pag([1, 2]),
                      _resp({"message": "You have exhausted your API Request Quota"}, 429)])
    r = snap.coletar(status=["INSTALLED"], pausa=0, paginas=5, http=http)
    assert r["parou_por_cota"] is True
    assert r["acumulado"] == 2, "o que veio antes do 429 tem de ficar"
    assert r["cursor"] == 1


def test_o_mesmo_pneu_em_duas_voltas_atualiza_em_vez_de_duplicar(snap, com_token):
    snap.coletar(status=["INSTALLED"], pausa=0, paginas=1,
                 http=HttpFalso([_pag([1, 2], ultima=True)]))
    r = snap.coletar(status=["INSTALLED"], pausa=0, paginas=1,
                     http=HttpFalso([_pag([1, 2], ultima=True)]))
    assert r["acumulado"] == 2 and r["novos"] == 0 and r["voltas"] == 2


def test_trocar_o_recorte_descarta_o_acumulado(snap, com_token):
    """Misturar meia volta de INSTALLED com meia volta de tudo produziria um
    retrato que nunca existiu."""
    snap.coletar(status=["INSTALLED"], pausa=0, paginas=1,
                 http=HttpFalso([_pag([1, 2])]))
    r = snap.coletar(status=["DISPOSAL"], pausa=0, paginas=1,
                     http=HttpFalso([_pag([9])]))
    assert r["acumulado"] == 1, "o acumulado do recorte anterior tem de sair"


def test_o_instantaneo_guarda_pneu_JA_normalizado(snap, com_token):
    """E por isso que existe `analisar_normalizados`: passar o normalizado de
    novo por `pneu()` produziria campos vazios em silencio."""
    snap.coletar(status=["INSTALLED"], pausa=0, paginas=1,
                 http=HttpFalso([_pag([1], ultima=True)]))
    d = snap.ler()
    p = d["pneus"][0]
    assert "serie" in p and "serialNumber" not in p
    assert an.analisar_normalizados(d["pneus"])["kpis"]["total"] == 1
