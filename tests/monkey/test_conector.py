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
    fonte = inspect.getsource(cli.Cliente.recebiveis)
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
