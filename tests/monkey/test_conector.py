"""Conector da Monkey: paginacao, normalizacao e o que NAO pode vazar.

Roda inteiro contra um dube de HTTP — a integracao esta escrita e testada antes
de a credencial existir, entao no dia em que ela chegar e so configurar.
"""
import json

import pytest

from api.monkey import cliente as cli
from api.monkey import espelho
from api.monkey import normaliza as nz


# --------------------------------------------------------------------- dube
def _resp(corpo: dict, status: int = 200):
    return status, json.dumps(corpo).encode()


def _pagina(itens, pagina, total_paginas):
    return {"_embedded": {"receivables": itens},
            "page": {"size": len(itens), "number": pagina,
                     "totalPages": total_paginas,
                     "totalElements": len(itens) * total_paginas}}


# O /uaa/me e a PRIMEIRA chamada de qualquer fluxo /v2: e dele que sai o
# token do PROGRAMA (header `program`), sem o qual o /v2 inteiro responde
# HTTP 500 seco — medido ao vivo em 01/09/2026.
ME = {"principal": {
    "programs": [{"token": "PRG-TUPY", "name": "TUPY"}],
    "companies": [
        {"companyId": "4242", "governmentId": "11222333000144",
         "name": "SULISTA MATRIZ", "type": "SELLER", "active": True},
        {"companyId": "111", "governmentId": "11222333000225",
         "name": "SULISTA FILIAL 1", "type": "SELLER", "active": True},
        {"companyId": "222", "governmentId": "11222333000306",
         "name": "SULISTA FILIAL 2", "type": "SELLER", "active": True},
    ]}}


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
        "MONKEY_TOKEN": "tok-secreto", "MONKEY_SELLER_ID": "4242",
        "MONKEY_AMBIENTE": "hmg"}.get(n, ""))


# ---------------------------------------------------------------- paginacao
def test_percorre_todas_as_paginas(com_token):
    http = HttpFalso([
        _resp(ME),
        _resp(_pagina([{"invoiceNumber": "1"}, {"invoiceNumber": "2"}], 0, 3)),
        _resp(_pagina([{"invoiceNumber": "3"}], 1, 3)),
        _resp(_pagina([{"invoiceNumber": "4"}], 2, 3)),
    ])
    linhas = cli.Cliente(http=http).recebiveis(tamanho=2)
    assert [x["invoiceNumber"] for x in linhas] == ["1", "2", "3", "4"]
    assert len(http.chamadas) == 4          # /uaa/me + 3 paginas
    assert "/uaa/me" in http.chamadas[0]["url"]
    assert "page=0" in http.chamadas[1]["url"] and "size=2" in http.chamadas[1]["url"]
    # o header do programa vai em TODA chamada /v2 — e nao no /uaa/me
    assert http.chamadas[1]["headers"]["program"] == "PRG-TUPY"
    assert "program" not in http.chamadas[0]["headers"]


def test_pagina_vazia_encerra_mesmo_com_totalPages_mentiroso(com_token):
    """API paginada que mente no totalPages ja apareceu antes; sem esta saida o
    laco rodaria ate o teto e faria centenas de chamadas a toa."""
    http = HttpFalso([
        _resp(ME),
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 999)),
        _resp(_pagina([], 1, 999)),
    ])
    assert len(cli.Cliente(http=http).recebiveis()) == 1
    assert len(http.chamadas) == 3


def test_existe_freio_de_paginas():
    import inspect
    fonte = inspect.getsource(cli.Cliente.recebiveis)
    assert "maximo_paginas" in fonte


def test_busca_nao_leva_page_nem_size(com_token):
    """A Monkey confirmou (01/09/2026): search com page/size na MESMA
    requisicao devolve 200 com lista vazia — os parametros se invalidam sem
    erro nenhum. A busca tem de ir sozinha."""
    http = HttpFalso([_resp(ME), _resp(_pagina([{"invoiceNumber": "1"}], 0, 1))])
    linhas = cli.Cliente(http=http).recebiveis(busca="externalId:3082912")
    assert len(linhas) == 1 and len(http.chamadas) == 2
    url = http.chamadas[-1]["url"]
    assert "search=externalId%3A3082912" in url
    assert "page=" not in url and "size=" not in url


def test_listagem_completa_nao_leva_search(com_token):
    http = HttpFalso([_resp(ME), _resp(_pagina([{"invoiceNumber": "1"}], 0, 1))])
    cli.Cliente(http=http).recebiveis()
    assert "search=" not in http.chamadas[-1]["url"]


def test_o_campo_de_sellers_aceita_virgulas(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "MONKEY_SELLER_ID": " 111, 222 ,333 "}.get(n, ""))
    assert cli.seller_ids() == ["111", "222", "333"]


# ----------------------------------------------------------- configuracao
def test_sem_credencial_a_integracao_fica_desligada(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: "")
    assert cli.configurado() is False
    with pytest.raises(cli.MonkeyNaoConfigurado):
        cli.Cliente(http=HttpFalso([]))


def test_credencial_sem_sellerId_nao_basta(monkeypatch):
    """O sellerId e o {id} do caminho e nao ha como descobri-lo daqui."""
    monkeypatch.setattr(cli, "_cred",
                        lambda n: "tok" if n == "MONKEY_TOKEN" else "")
    assert cli.configurado() is False
    with pytest.raises(cli.MonkeyNaoConfigurado):
        cli.Cliente(http=HttpFalso([]))


def test_o_padrao_e_HOMOLOGACAO(monkeypatch):
    """Apontar para producao tem de ser deliberado: a primeira coleta de uma
    integracao nova e justamente quando o parser ainda pode estar errado."""
    monkeypatch.setattr(cli, "_cred", lambda n: "")
    assert cli.ambiente() == "hmg"
    assert cli.base_url() == "https://hmg-zuul.monkeyecx.com"


def test_ambiente_invalido_cai_em_homologacao(monkeypatch):
    monkeypatch.setattr(cli, "_cred",
                        lambda n: "producao!" if n == "MONKEY_AMBIENTE" else "")
    assert cli.ambiente() == "hmg"


# ------------------------------------------------------------------- oauth
OAUTH_CREDS = {
    "MONKEY_CLIENT_ID": "id", "MONKEY_CLIENT_SECRET": "seg",
    "MONKEY_USERNAME": "robo@sulista.com.br", "MONKEY_PASSWORD": "s3nh4",
    "MONKEY_SELLER_ID": "1", "MONKEY_TOKEN_URL": "https://x/oauth/token",
}


def test_o_primeiro_token_e_grant_password(monkeypatch):
    """Resposta oficial da Monkey (01/09/2026): a primeira obtencao usa
    grant_type=password com o usuario/senha da plataforma."""
    monkeypatch.setattr(cli, "_cred", lambda n: OAUTH_CREDS.get(n, ""))
    http = HttpFalso([
        _resp({"access_token": "ac-1", "refresh_token": "rf-1",
               "expires_in": 3600}),
        _resp(ME),
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 1)),
        _resp(_pagina([{"invoiceNumber": "2"}], 0, 1)),
    ])
    c = cli.Cliente(http=http)
    c.recebiveis()
    c.recebiveis()
    # uma chamada de token para DUAS coletas: o token fica em cache
    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert len(tokens) == 1
    assert b"grant_type=password" in tokens[0]["dados"]
    assert b"username=robo" in tokens[0]["dados"]
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac-1"


def test_a_renovacao_usa_o_refresh_token(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: OAUTH_CREDS.get(n, ""))
    http = HttpFalso([
        _resp({"access_token": "ac-1", "refresh_token": "rf-1",
               "expires_in": 3600}),
        _resp(ME),
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 1)),
        _resp({"access_token": "ac-2", "refresh_token": "rf-2",
               "expires_in": 3600}),
        _resp(_pagina([{"invoiceNumber": "2"}], 0, 1)),
    ])
    c = cli.Cliente(http=http)
    c.recebiveis()
    c._tok_expira = 0.0          # o relógio andou: o access venceu
    c.recebiveis()
    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert len(tokens) == 2
    assert b"grant_type=refresh_token" in tokens[1]["dados"]
    assert b"refresh_token=rf-1" in tokens[1]["dados"]
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac-2"


def test_refresh_recusado_cai_de_volta_no_password(monkeypatch):
    """Refresh vencido ou rotacionado nao pode travar a coleta ate alguem
    reiniciar o processo: a recusa cai de volta no grant password."""
    monkeypatch.setattr(cli, "_cred", lambda n: OAUTH_CREDS.get(n, ""))
    http = HttpFalso([
        _resp({"access_token": "ac-1", "refresh_token": "rf-velho",
               "expires_in": 3600}),
        _resp(ME),
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 1)),
        _resp({"error": "invalid_grant"}, 400),          # refresh recusado
        _resp({"access_token": "ac-3", "expires_in": 3600}),
        _resp(_pagina([{"invoiceNumber": "2"}], 0, 1)),
    ])
    c = cli.Cliente(http=http)
    c.recebiveis()
    c._tok_expira = 0.0
    c.recebiveis()
    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert len(tokens) == 3
    assert b"grant_type=refresh_token" in tokens[1]["dados"]
    assert b"grant_type=password" in tokens[2]["dados"]
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac-3"


def test_oauth_sem_usuario_e_senha_nao_esta_configurado(monkeypatch):
    """So o par client_id/client_secret nao basta: o primeiro token e
    grant_type=password e a Monkey recusaria — melhor dizer o que falta."""
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "MONKEY_CLIENT_ID": "id", "MONKEY_CLIENT_SECRET": "seg",
        "MONKEY_SELLER_ID": "1"}.get(n, ""))
    assert cli.modo_auth() == ""
    assert cli.configurado() is False


def test_falha_ao_pedir_token_nao_ecoa_o_corpo(monkeypatch):
    """Numa troca de credencial o retorno pode devolver o que foi enviado, e
    isso iria para o log."""
    monkeypatch.setattr(cli, "_cred", lambda n: {
        **OAUTH_CREDS, "MONKEY_CLIENT_SECRET": "SENHA-SECRETA"}.get(n, ""))
    http = HttpFalso([_resp({"erro": "client_secret SENHA-SECRETA invalido"}, 400)])
    with pytest.raises(cli.MonkeyIndisponivel) as e:
        cli.Cliente(http=http).recebiveis()
    assert "SENHA-SECRETA" not in str(e.value)


def test_401_diz_o_que_conferir(com_token):
    http = HttpFalso([_resp({"erro": "x"}, 401)])
    with pytest.raises(cli.MonkeyIndisponivel) as e:
        cli.Cliente(http=http).recebiveis()
    assert "sellerId" in str(e.value)


def test_o_token_nunca_aparece_na_mensagem_de_erro(com_token):
    http = HttpFalso([_resp({"erro": "x"}, 500)])
    with pytest.raises(cli.MonkeyIndisponivel) as e:
        cli.Cliente(http=http).recebiveis()
    assert "tok-secreto" not in str(e.value)


# -------------------------------------------------------------- normalizacao
# Formato REAL medido em producao (01/09/2026): sponsor e a ANCORA (Tupy,
# o sacado); buyer e o INVESTIDOR que comprou o titulo (um banco). O palpite
# original tinha os dois trocados — e o dado real e o que impede regredir.
RECEB = {
    "invoiceNumber": "123456", "invoiceKey": "3526" + "0" * 40,
    "invoiceDate": "2026-08-01T00:00:00.000-03:00",
    "paymentDate": "2026-10-15T00:00:00.000-03:00",
    "paymentValue": 10000.0, "receiptValue": 9750.5,
    "status": "ACTIVE", "purchasedTax": 1.85,
    "installment": 1, "totalInstallment": 3,
    "assetType": "DUPLICATA_MERCANTIL",
    "sponsorName": "TUPY S/A", "sponsorGovernmentId": "84.683.374/0001-49",
    "buyerName": "BANCO SOFISA S.A.", "buyerGovernmentId": "60889128000180",
    "externalId": "MK-999",
}


def test_mapeia_os_campos_para_o_formato_que_a_tela_ja_usa():
    t = nz.titulo(RECEB)
    assert t["documento"] == "123456"
    assert t["emissao"] == "2026-08-01" and t["vencimento"] == "2026-10-15"
    assert t["valor_nominal"] == 10000.0 and t["valor_saldo"] == 9750.5
    assert t["cnpj_sacado"] == "84683374000149", "sacado = SPONSOR, so digitos"
    assert t["parcela"] == "1/3" and t["taxa"] == 1.85


def test_a_data_nao_anda_um_dia_por_causa_do_fuso():
    """ISO com offset -03:00 perto da meia-noite vira o dia anterior se alguem
    converter para UTC. Aqui corta no 'T'."""
    t = nz.titulo({**RECEB, "paymentDate": "2026-10-15T23:30:00.000-03:00"})
    assert t["vencimento"] == "2026-10-15"


@pytest.mark.parametrize("status,esperado", [
    ("ACTIVE", 1), ("OFFERED", 1),
    ("SOLD", 0), ("PAID", 0), ("REFUSED", 0), ("CANCELLED", 0),
    ("WAITING_CUSTODY", 0), ("DELAYED", 0),
])
def test_so_e_antecipavel_o_que_ainda_pode_ser_vendido(status, esperado):
    """Titulo SOLD ja foi antecipado; conta-lo de novo inflaria o disponivel."""
    assert nz.titulo({**RECEB, "status": status})["antecipavel"] == esperado


def test_status_desconhecido_nao_vira_rotulo_inventado():
    t = nz.titulo({**RECEB, "status": "ALGO_NOVO"})
    assert t["situacao"] == "ALGO_NOVO" and t["antecipavel"] == 0


def test_saldo_ausente_cai_no_nominal():
    """Deixar zero faria o titulo sumir das somas."""
    t = nz.titulo({**RECEB, "receiptValue": None})
    assert t["valor_saldo"] == 10000.0


def test_aceita_valor_como_string_pt_br():
    assert nz.titulo({**RECEB, "paymentValue": "1.234,56"})["valor_nominal"] == 1234.56


def test_o_lote_resume_por_status_e_so_soma_o_disponivel():
    d = nz.lote([RECEB, {**RECEB, "status": "SOLD", "invoiceNumber": "2"},
                 {**RECEB, "status": "OFFERED", "invoiceNumber": "3"}])
    r = d["resumo"]
    assert r["linhas"] == 3 and r["antecipaveis"] == 2
    assert r["valor_nominal"] == 30000.0
    assert r["valor_antecipavel"] == round(9750.5 * 2, 2)
    assert r["por_status"] == {"disponível": 1, "vendido": 1, "ofertado": 1}


def test_o_sacado_e_o_SPONSOR_e_nunca_o_banco_investidor():
    """Medido em producao: sponsor=TUPY (a ancora, quem deve), buyer=banco
    que comprou o titulo. Se o sacado apontasse para o buyer, a elegibilidade
    por convenio (raiz do CNPJ do sacado) casaria com o banco — nunca com a
    Tupy — e nenhum titulo seria elegivel."""
    t = nz.titulo(RECEB)
    assert t["nome_sacado"] == "TUPY S/A"
    assert "SOFISA" not in t["nome_sacado"]
    assert t["cnpj_sacado"] == "84683374000149"


def test_o_cedente_vem_da_anotacao_da_coleta():
    """O payload nao traz o CNPJ do proprio seller: a coleta anota
    _seller_cnpj/_seller_nome a partir de /uaa/me."""
    t = nz.titulo({**RECEB, "_seller_cnpj": "11222333000144",
                   "_seller_nome": "SULISTA MATRIZ"})
    assert t["cnpj_cedente"] == "11222333000144"
    assert t["nome_cedente"] == "SULISTA MATRIZ"
    # sem anotacao, cedente fica vazio — nunca herda o sponsor
    assert nz.titulo(RECEB)["cnpj_cedente"] == ""


# ------------------------------------------------------- gravacao (servico)
def test_cinco_sellers_viram_UMA_posicao(esquema_pg, monkeypatch):
    """A Sulista tem um sellerId por CNPJ. gravar_envio SUBSTITUI a posicao
    do portal: gravar por CNPJ deixaria so o ultimo e os outros sumiriam sem
    erro nenhum — por isso a coleta soma os sellers e grava UMA vez."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(cli, "_cred", lambda n: {
        "MONKEY_TOKEN": "tok", "MONKEY_SELLER_ID": "111,222",
        "MONKEY_AMBIENTE": "hmg"}.get(n, ""))
    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    http = HttpFalso([
        _resp(ME),
        _resp(_pagina([RECEB], 0, 1)),
        _resp(_pagina([{**RECEB, "invoiceNumber": "777"}], 0, 1)),
    ])
    r = servico.coletar(http=http)
    assert r["sellers"] == 2 and r["recebidos"] == 2 and r["gravados"] == 2
    # o espelho tambem foi gravado — no schema DESTE teste (o guard
    # `producao_intocada` do conftest acusa se cair em producao)
    from api import pglocal
    assert r["espelho"] == 2
    carga = pglocal.um("SELECT recebidos, gravados FROM mky_carga ORDER BY id DESC LIMIT 1", esquema=esquema_pg)
    assert (carga["recebidos"], carga["gravados"]) == (2, 2)
    assert "/uaa/me" in http.chamadas[0]["url"], "o programa se descobre UMA vez"
    assert "/sellers/111/" in http.chamadas[1]["url"]
    assert "/sellers/222/" in http.chamadas[2]["url"]
    pos = registro.posicao_atual()
    assert len(pos) == 1, "UMA posicao do portal, nao uma por seller"
    assert len(registro.titulos_vigentes()) == 2


def test_coleta_grava_pelo_mesmo_caminho_da_planilha(esquema_pg, monkeypatch, com_token):
    """Reusar `gravar_envio` de proposito: ele ja resolve "qual e a posicao
    atual do portal". Um caminho paralelo criaria duas regras que um dia
    discordariam."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    http = HttpFalso([_resp(ME), _resp(_pagina([RECEB], 0, 1))])
    r = servico.coletar(http=http)

    assert r["gravados"] == 1 and r["antecipaveis"] == 1
    assert r["sem_mudanca"] is False
    assert r["ambiente"] == "hmg", "coleta nao pode ir para producao por acidente"

    # posicao_atual() devolve os ENVIOS vigentes (um por portal);
    # titulos_vigentes() e que traz as linhas
    pos = registro.posicao_atual()
    assert len(pos) == 1 and pos[0]["portal"] == "tupy"
    tits = registro.titulos_vigentes()
    assert len(tits) == 1 and tits[0]["documento"] == "123456"


def test_coleta_identica_nao_cria_envio_novo(esquema_pg, monkeypatch, com_token):
    """A coleta agendada roda de tempos em tempos. Se nada mudou no portal, ela
    nao pode criar envio novo — a lista de importacoes mentiria sobre a
    frequencia com que o dado REALMENTE muda."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    r1 = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([RECEB], 0, 1))]))
    r2 = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([RECEB], 0, 1))]))
    assert r1["sem_mudanca"] is False
    assert r2["sem_mudanca"] is True
    assert r1["envio_id"] == r2["envio_id"]


def test_a_ordem_das_linhas_nao_muda_a_impressao(esquema_pg, monkeypatch, com_token):
    """API pode devolver a mesma posicao em ordem diferente; isso nao e
    mudanca de posicao."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    b = {**RECEB, "invoiceNumber": "999"}
    servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([RECEB, b], 0, 1))]))
    r2 = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([b, RECEB], 0, 1))]))
    assert r2["sem_mudanca"] is True


def test_mudanca_de_status_conta_como_posicao_nova(esquema_pg, monkeypatch, com_token):
    """Titulo que passou de disponivel para VENDIDO mudou o que importa."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([RECEB], 0, 1))]))
    r2 = servico.coletar(http=HttpFalso([
        _resp(ME), _resp(_pagina([{**RECEB, "status": "SOLD"}], 0, 1))]))
    assert r2["sem_mudanca"] is False and r2["antecipaveis"] == 0


def test_vendido_e_liquidado_NAO_entram_na_posicao(esquema_pg, monkeypatch, com_token):
    """A primeira coleta real (01/09/2026) trouxe 48.666 titulos — TODOS
    vendidos/liquidados desde o inicio do convenio. Posicao e o que esta EM
    ABERTO; gravar o historico encheria a tela com 48 mil linhas mortas. E o
    hash e sobre a posicao: SOLD virando PAID no historico nao e mudanca."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    r = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([
        RECEB,
        {**RECEB, "invoiceNumber": "2", "status": "SOLD"},
        {**RECEB, "invoiceNumber": "3", "status": "PAID"},
        {**RECEB, "invoiceNumber": "4", "status": "CANCELLED"},
    ], 0, 1))]))
    assert r["recebidos"] == 4 and r["gravados"] == 1
    assert r["fora_da_posicao"] == 3
    tits = registro.titulos_vigentes()
    assert len(tits) == 1 and tits[0]["documento"] == "123456"
    # segunda coleta: o historico mudou (SOLD->PAID), a posicao NAO
    r2 = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([
        RECEB,
        {**RECEB, "invoiceNumber": "2", "status": "PAID"},
        {**RECEB, "invoiceNumber": "3", "status": "PAID"},
        {**RECEB, "invoiceNumber": "4", "status": "CANCELLED"},
    ], 0, 1))]))
    assert r2["sem_mudanca"] is True, "posicao igual = mesmo envio"


def test_titulo_sem_vencimento_e_rejeitado(esquema_pg, monkeypatch, com_token):
    """Sem vencimento nao ha antecipacao nem posicao no fluxo de caixa. A
    planilha ja trata assim; a API segue a mesma regra."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    r = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina(
        [RECEB, {**RECEB, "invoiceNumber": "7", "paymentDate": None}], 0, 1))]))
    assert r["recebidos"] == 2 and r["gravados"] == 1
    assert r["rejeitados_sem_vencimento"] == 1


def test_a_posicao_fica_marcada_como_API(esquema_pg, monkeypatch, com_token):
    """Maxion e Adient continuam por planilha: a tela precisa distinguir."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    r = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([RECEB], 0, 1))]))
    from api import pglocal
    linha = pglocal.um("SELECT origem, portal FROM ant_envios WHERE id=%s",
                       (r["envio_id"],), esquema=esquema_pg)
    assert linha["origem"] == "api" and linha["portal"] == "tupy"


def test_nao_inventa_total_declarado(esquema_pg, monkeypatch, com_token):
    """A API nao declara total. Copiar o somado faria a divergencia sair
    sempre zero e parecer conferencia que nao houve."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(espelho, "ESQUEMA", esquema_pg)
    r = servico.coletar(http=HttpFalso([_resp(ME), _resp(_pagina([RECEB], 0, 1))]))
    from api import pglocal
    linha = pglocal.um("SELECT total_declarado, divergencia FROM ant_envios"
                       " WHERE id=%s", (r["envio_id"],), esquema=esquema_pg)
    assert linha["total_declarado"] is None and linha["divergencia"] is None
