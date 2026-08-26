"""Conector da Monkey: paginacao, normalizacao e o que NAO pode vazar.

Roda inteiro contra um dube de HTTP — a integracao esta escrita e testada antes
de a credencial existir, entao no dia em que ela chegar e so configurar.
"""
import json

import pytest

from api.monkey import cliente as cli
from api.monkey import normaliza as nz


# --------------------------------------------------------------------- dube
def _resp(corpo: dict, status: int = 200):
    return status, json.dumps(corpo).encode()


def _pagina(itens, pagina, total_paginas):
    return {"_embedded": {"receivables": itens},
            "page": {"size": len(itens), "number": pagina,
                     "totalPages": total_paginas,
                     "totalElements": len(itens) * total_paginas}}


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
        _resp(_pagina([{"invoiceNumber": "1"}, {"invoiceNumber": "2"}], 0, 3)),
        _resp(_pagina([{"invoiceNumber": "3"}], 1, 3)),
        _resp(_pagina([{"invoiceNumber": "4"}], 2, 3)),
    ])
    linhas = cli.Cliente(http=http).recebiveis(tamanho=2)
    assert [x["invoiceNumber"] for x in linhas] == ["1", "2", "3", "4"]
    assert len(http.chamadas) == 3
    assert "page=0" in http.chamadas[0]["url"] and "size=2" in http.chamadas[0]["url"]


def test_pagina_vazia_encerra_mesmo_com_totalPages_mentiroso(com_token):
    """API paginada que mente no totalPages ja apareceu antes; sem esta saida o
    laco rodaria ate o teto e faria centenas de chamadas a toa."""
    http = HttpFalso([
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 999)),
        _resp(_pagina([], 1, 999)),
    ])
    assert len(cli.Cliente(http=http).recebiveis()) == 1
    assert len(http.chamadas) == 2


def test_existe_freio_de_paginas():
    import inspect
    fonte = inspect.getsource(cli.Cliente.recebiveis_de)
    assert "maximo_paginas" in fonte


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
def test_oauth_troca_credencial_por_token_e_reaproveita(monkeypatch):
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "MONKEY_CLIENT_ID": "id", "MONKEY_CLIENT_SECRET": "seg",
        "MONKEY_SELLER_ID": "1", "MONKEY_TOKEN_URL": "https://x/oauth/token",
    }.get(n, ""))
    http = HttpFalso([
        _resp({"access_token": "ac-1", "expires_in": 3600}),
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 1)),
        _resp(_pagina([{"invoiceNumber": "2"}], 0, 1)),
    ])
    c = cli.Cliente(http=http)
    c.recebiveis()
    c.recebiveis()
    # uma chamada de token para DUAS coletas: o token fica em cache
    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert len(tokens) == 1
    assert b"grant_type=client_credentials" in tokens[0]["dados"]
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac-1"


def test_falha_ao_pedir_token_nao_ecoa_o_corpo(monkeypatch):
    """Numa troca de credencial o retorno pode devolver o que foi enviado, e
    isso iria para o log."""
    monkeypatch.setattr(cli, "_cred", lambda n: {
        "MONKEY_CLIENT_ID": "id", "MONKEY_CLIENT_SECRET": "SENHA-SECRETA",
        "MONKEY_SELLER_ID": "1"}.get(n, ""))
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
RECEB = {
    "invoiceNumber": "123456", "invoiceKey": "3526" + "0" * 40,
    "invoiceDate": "2026-08-01T00:00:00.000-03:00",
    "paymentDate": "2026-10-15T00:00:00.000-03:00",
    "paymentValue": 10000.0, "receiptValue": 9750.5,
    "status": "ACTIVE", "purchasedTax": 1.85,
    "installment": 1, "totalInstallment": 3,
    "buyerName": "TUPY S.A.", "buyerGovernmentId": "73178600/0001-18",
    "sponsorName": "TUPY", "sponsorGovernmentId": "73178600000118",
    "externalId": "MK-999",
}


def test_mapeia_os_campos_para_o_formato_que_a_tela_ja_usa():
    t = nz.titulo(RECEB)
    assert t["documento"] == "123456"
    assert t["emissao"] == "2026-08-01" and t["vencimento"] == "2026-10-15"
    assert t["valor_nominal"] == 10000.0 and t["valor_saldo"] == 9750.5
    assert t["cnpj_sacado"] == "73178600000118", "CNPJ tem de vir so com digitos"
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


def test_cedente_e_sacado_nao_estao_trocados():
    """A Sulista e o SELLER; o buyer e quem deve. Invertido, a elegibilidade
    por convenio (que casa pela raiz do CNPJ do sacado) quebraria."""
    t = nz.titulo(RECEB)
    assert t["nome_sacado"] == "TUPY S.A."


# ------------------------------------------------------- gravacao (servico)
def test_coleta_grava_pelo_mesmo_caminho_da_planilha(tmp_path, monkeypatch, com_token):
    """Reusar `gravar_envio` de proposito: ele ja resolve "qual e a posicao
    atual do portal". Um caminho paralelo criaria duas regras que um dia
    discordariam."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "a.db")
    http = HttpFalso([_resp(_pagina([RECEB], 0, 1))])
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


def test_coleta_identica_nao_cria_envio_novo(tmp_path, monkeypatch, com_token):
    """A coleta agendada roda de tempos em tempos. Se nada mudou no portal, ela
    nao pode criar envio novo — a lista de importacoes mentiria sobre a
    frequencia com que o dado REALMENTE muda."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "b.db")
    r1 = servico.coletar(http=HttpFalso([_resp(_pagina([RECEB], 0, 1))]))
    r2 = servico.coletar(http=HttpFalso([_resp(_pagina([RECEB], 0, 1))]))
    assert r1["sem_mudanca"] is False
    assert r2["sem_mudanca"] is True
    assert r1["envio_id"] == r2["envio_id"]


def test_a_ordem_das_linhas_nao_muda_a_impressao(tmp_path, monkeypatch, com_token):
    """API pode devolver a mesma posicao em ordem diferente; isso nao e
    mudanca de posicao."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "c.db")
    b = {**RECEB, "invoiceNumber": "999"}
    servico.coletar(http=HttpFalso([_resp(_pagina([RECEB, b], 0, 1))]))
    r2 = servico.coletar(http=HttpFalso([_resp(_pagina([b, RECEB], 0, 1))]))
    assert r2["sem_mudanca"] is True


def test_mudanca_de_status_conta_como_posicao_nova(tmp_path, monkeypatch, com_token):
    """Titulo que passou de disponivel para VENDIDO mudou o que importa."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "d.db")
    servico.coletar(http=HttpFalso([_resp(_pagina([RECEB], 0, 1))]))
    r2 = servico.coletar(http=HttpFalso([
        _resp(_pagina([{**RECEB, "status": "SOLD"}], 0, 1))]))
    assert r2["sem_mudanca"] is False and r2["antecipaveis"] == 0


def test_titulo_sem_vencimento_e_rejeitado(tmp_path, monkeypatch, com_token):
    """Sem vencimento nao ha antecipacao nem posicao no fluxo de caixa. A
    planilha ja trata assim; a API segue a mesma regra."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "e.db")
    r = servico.coletar(http=HttpFalso([_resp(_pagina(
        [RECEB, {**RECEB, "invoiceNumber": "7", "paymentDate": None}], 0, 1))]))
    assert r["recebidos"] == 2 and r["gravados"] == 1
    assert r["rejeitados_sem_vencimento"] == 1


def test_a_posicao_fica_marcada_como_API(tmp_path, monkeypatch, com_token):
    """Maxion e Adient continuam por planilha: a tela precisa distinguir."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "f.db")
    r = servico.coletar(http=HttpFalso([_resp(_pagina([RECEB], 0, 1))]))
    with registro._conn() as c:
        linha = c.execute("SELECT origem, portal FROM envios WHERE id=?",
                          (r["envio_id"],)).fetchone()
    assert linha["origem"] == "api" and linha["portal"] == "tupy"


def test_nao_inventa_total_declarado(tmp_path, monkeypatch, com_token):
    """A API nao declara total. Copiar o somado faria a divergencia sair
    sempre zero e parecer conferencia que nao houve."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "g.db")
    r = servico.coletar(http=HttpFalso([_resp(_pagina([RECEB], 0, 1))]))
    with registro._conn() as c:
        linha = c.execute("SELECT total_declarado, divergencia FROM envios"
                          " WHERE id=?", (r["envio_id"],)).fetchone()
    assert linha["total_declarado"] is None and linha["divergencia"] is None


# ------------------------------------------------- host, grant e renovacao
def _creds(**extra):
    base = {"MONKEY_CLIENT_ID": "id", "MONKEY_CLIENT_SECRET": "seg",
            "MONKEY_SELLER_ID": "1", "MONKEY_TOKEN_URL": "https://x/oauth/token"}
    base.update(extra)
    return lambda n: base.get(n, "")


def test_base_url_configurada_vence_o_ambiente(monkeypatch):
    """A Monkey indicou sandbox.monkeyecx.com, que nao bate com o hmg-zuul
    daqui. Ate ela confirmar qual e o host de API, o certo entra por
    configuracao em vez de trocar o dicionario no escuro."""
    monkeypatch.setattr(cli, "_cred", _creds(
        MONKEY_BASE_URL="https://sandbox.monkeyecx.com/"))
    assert cli.base_url() == "https://sandbox.monkeyecx.com", "a barra final sai"


def test_sem_base_url_o_ambiente_continua_mandando(monkeypatch):
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_AMBIENTE="prod"))
    assert cli.base_url() == "https://zuul.monkey.exchange"


def test_grant_type_configuravel(monkeypatch):
    monkeypatch.setattr(cli, "_cred", _creds(
        MONKEY_GRANT_TYPE="password", MONKEY_USUARIO="u", MONKEY_SENHA="p"))
    http = HttpFalso([_resp({"access_token": "ac", "expires_in": 60}),
                      _resp(_pagina([], 0, 1))])
    cli.Cliente(http=http).recebiveis()
    corpo = [x for x in http.chamadas if x["dados"] is not None][0]["dados"]
    assert b"grant_type=password" in corpo and b"username=u" in corpo


def test_grant_escrito_errado_falha_dizendo_o_que_vale(monkeypatch):
    """Grant com typo falharia como 'credencial recusada' e a gente iria cacar
    a senha em vez do erro de digitacao."""
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_GRANT_TYPE="client_credential"))
    with pytest.raises(cli.MonkeyNaoConfigurado) as e:
        cli.Cliente(http=HttpFalso([]))
    assert "client_credentials" in str(e.value)


def test_password_sem_usuario_nao_passa(monkeypatch):
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_GRANT_TYPE="password"))
    with pytest.raises(cli.MonkeyNaoConfigurado):
        cli.Cliente(http=HttpFalso([]))


def test_renova_pelo_refresh_token_quando_o_access_vence(monkeypatch):
    """O fluxo que a Monkey descreveu: o refresh vem na resposta e e ele que
    renova, sem reapresentar a credencial."""
    monkeypatch.setattr(cli, "_cred", _creds())
    http = HttpFalso([
        _resp({"access_token": "ac-1", "expires_in": 3600, "refresh_token": "rf-1"}),
        _resp(_pagina([], 0, 1)),
        _resp({"access_token": "ac-2", "expires_in": 3600, "refresh_token": "rf-2"}),
        _resp(_pagina([], 0, 1)),
    ])
    c = cli.Cliente(http=http)
    c.recebiveis()
    c._tok_expira = 0            # simula o access_token vencendo
    c.recebiveis()

    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert len(tokens) == 2
    assert b"grant_type=refresh_token" in tokens[1]["dados"]
    assert b"refresh_token=rf-1" in tokens[1]["dados"]
    assert c._refresh == "rf-2", "refresh novo substitui o antigo"
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac-2"


def test_refresh_recusado_cai_de_volta_na_credencial(monkeypatch):
    """Refresh vencido deixaria a coleta presa para sempre — o defeito que so
    aparece depois de horas no ar, quando ninguem esta olhando."""
    monkeypatch.setattr(cli, "_cred", _creds())
    http = HttpFalso([
        _resp({"access_token": "ac-1", "expires_in": 3600, "refresh_token": "rf-1"}),
        _resp(_pagina([], 0, 1)),
        _resp({"erro": "refresh expirado"}, 400),      # renovacao recusada
        _resp({"access_token": "ac-3", "expires_in": 3600}),
        _resp(_pagina([], 0, 1)),
    ])
    c = cli.Cliente(http=http)
    c.recebiveis()
    c._tok_expira = 0
    c.recebiveis()

    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert b"grant_type=refresh_token" in tokens[1]["dados"]
    assert b"grant_type=client_credentials" in tokens[2]["dados"]
    assert c._refresh == "", "refresh morto e esquecido, nao retentado toda coleta"
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac-3"


def test_expires_in_estranho_nao_derruba_a_coleta(monkeypatch):
    monkeypatch.setattr(cli, "_cred", _creds())
    http = HttpFalso([_resp({"access_token": "ac", "expires_in": "3599.5"}),
                      _resp(_pagina([], 0, 1))])
    cli.Cliente(http=http).recebiveis()
    assert http.chamadas[-1]["headers"]["Authorization"] == "Bearer ac"


# ------------------------------------------------- varios CNPJs / sellerIds
def test_cinco_sellers_uma_autenticacao_so(monkeypatch):
    """Um perfil por CNPJ na Monkey. Cinco coletas nao podem custar cinco
    autenticacoes."""
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_SELLER_IDS="11, 22 ,33;44,55"))
    http = HttpFalso([_resp({"access_token": "ac", "expires_in": 3600})]
                     + [_resp(_pagina([{"invoiceNumber": str(i)}], 0, 1))
                        for i in range(5)])
    c = cli.Cliente(http=http)
    assert c.sellers == ["11", "22", "33", "44", "55"]
    assert len(c.recebiveis()) == 5
    tokens = [x for x in http.chamadas if x["dados"] is not None]
    assert len(tokens) == 1
    gets = [x["url"] for x in http.chamadas if x["dados"] is None]
    assert all("/v2/sellers/%s/receivables" % i in u
               for i, u in zip(["11", "22", "33", "44", "55"], gets))


def test_seller_repetido_nao_coleta_duas_vezes(monkeypatch):
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_SELLER_IDS="7,7, 7 "))
    assert cli.seller_ids() == ["7"]


def test_seller_id_antigo_continua_valendo(monkeypatch):
    """Quem ja configurou um so nao pode parar de funcionar."""
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_SELLER_ID="9"))
    assert cli.seller_ids() == ["9"] and cli.seller_id() == "9"


def test_a_quebra_por_seller_mostra_quem_veio_vazio(monkeypatch):
    """Seller que parou de responder, somado aos outros, sumiria sem rastro."""
    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_SELLER_IDS="a,b"))
    http = HttpFalso([
        _resp({"access_token": "ac", "expires_in": 3600}),
        _resp(_pagina([{"invoiceNumber": "1"}], 0, 1)),
        _resp(_pagina([], 0, 1)),
    ])
    d = cli.Cliente(http=http).recebiveis_por_seller()
    assert len(d["a"]) == 1 and d["b"] == []


def test_cinco_CNPJs_gravam_UMA_posicao_com_tudo(tmp_path, monkeypatch):
    """`gravar_envio` SUBSTITUI a posicao do portal. Gravar por CNPJ deixaria
    so o ultimo, e os outros quatro sumiriam sem erro nenhum."""
    from api.antecipacoes import registro
    from api.monkey import servico

    monkeypatch.setattr(cli, "_cred", _creds(MONKEY_SELLER_IDS="a,b"))
    monkeypatch.setattr(registro, "DB_PATH", tmp_path / "multi.db")
    http = HttpFalso([
        _resp({"access_token": "ac", "expires_in": 3600}),
        _resp(_pagina([RECEB], 0, 1)),
        _resp(_pagina([{**RECEB, "invoiceNumber": "888"}], 0, 1)),
    ])
    r = servico.coletar(http=http)

    assert r["gravados"] == 2
    assert r["por_seller"] == {"a": 1, "b": 1}
    assert len(registro.posicao_atual()) == 1, "um portal, uma posicao"
    docs = sorted(t["documento"] for t in registro.titulos_vigentes())
    assert docs == ["123456", "888"], "nenhum CNPJ pode ser engolido pelo outro"
