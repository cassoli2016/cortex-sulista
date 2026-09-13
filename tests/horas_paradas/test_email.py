"""O e-mail das horas paradas: o que o cliente recebe e o que fica registrado."""
from __future__ import annotations

import pytest

from api.horas_paradas import cadastro, fonte
from api.horas_paradas import email as hpe
from tests.horas_paradas.test_servico import CARGAS, CONTRATO

DE, ATE = "2026-09-07", "2026-09-13"


@pytest.fixture
def perfil(esquema_pg, monkeypatch):
    monkeypatch.setattr(fonte, "cargas", lambda cli, de, ate: {
        "cargas": [dict(c) for c in CARGAS], "contrato": [dict(x) for x in CONTRATO],
        "lido_em": "2026-09-12T10:00:00"})
    p = cadastro.criar_perfil(8, "CLIENTE A", "a@x", esquema=esquema_pg)
    return p["id"], esquema_pg


class Servidor:
    """O `envio.enviar` da casa, dublado: guarda o que recebeu."""
    def __init__(self, ok=True, erro=""):
        self.ok, self.erro, self.chamadas = ok, erro, []

    def __call__(self, dests, assunto, corpo, **kw):
        self.chamadas.append(dict(dests=dests, assunto=assunto, corpo=corpo, **kw))
        return {"ok": self.ok, "erro": self.erro, "destinatarios": dests}


def test_o_e_mail_e_o_que_a_tela_mostra(perfil):
    pid, esq = perfil
    e = hpe.montar(pid, DE, ATE, mensagem="Segue a <b>planilha</b>.\n\nQualquer dúvida, responda.",
                   esquema=esq)
    assert e["assunto"] == "Horas paradas · CLIENTE A · semana 37 (07/09/2026 a 13/09/2026)"
    assert "CLIENTE A" in e["html"]
    # texto de quem envia é ESCAPADO — vai para fora da empresa
    assert "&lt;b&gt;planilha" in e["html"] and "<b>planilha" not in e["html"]
    assert e["anexos"][0]["nome"] == e["arquivo"] and e["arquivo"].endswith(".xlsx")
    assert e["anexos"][0]["conteudo"][:2] == b"PK"
    # na tabela, SÓ quem passou do tempo: a coleta 1 excedeu, a 2 não
    assert "Coleta 1 " in e["texto"] and "Coleta 2 " not in e["texto"]
    assert "50,00" in e["html"]


def test_o_que_e_INTERNO_nao_vai_ao_cliente(perfil):
    """Ajuste manual, motivo e o valor que o ERP daria são da casa."""
    pid, esq = perfil
    cadastro.ajustar(fonte.chave(CARGAS[1]), "descarga_saida", "2026-09-09 19:00", None,
                     "motivo interno da torre", "a@x", esquema=esq)
    e = hpe.montar(pid, DE, ATE, esquema=esq)
    for interno in ("motivo interno", "ajust", "ERP"):
        assert interno not in e["html"] and interno not in e["texto"], interno


def test_envia_com_RESPOSTA_para_quem_atende_e_registra(perfil):
    pid, esq = perfil
    srv = Servidor()
    r = hpe.enviar(pid, DE, ATE, "A@Cliente.com; b@cliente.com", "torre@sulista.com.br",
                   "", "", "op@x", esquema=esq, enviar_=srv)
    assert r["ok"] and r["destinatarios"] == ["a@cliente.com", "b@cliente.com"]
    c = srv.chamadas[0]
    assert c["responder_para"] == ["torre@sulista.com.br"]
    assert c["anexos"][0]["nome"].endswith(".xlsx") and c["corpo_html"].startswith("<!DOCTYPE")
    assert c["origem"] == "horas_paradas:%d:%s:%s" % (pid, DE, ATE)
    h = hpe.envios(pid, esquema=esq)
    assert h[0]["ok"] is True and h[0]["destinatarios"] == "a@cliente.com, b@cliente.com"
    assert h[0]["responder_para"] == "torre@sulista.com.br" and h[0]["autor"] == "op@x"
    assert h[0]["cargas"] == 2 and h[0]["valor_total"] == 50.0


def test_LEMBRAR_grava_no_perfil_so_se_o_e_mail_saiu(perfil):
    pid, esq = perfil
    hpe.enviar(pid, DE, ATE, "x@cliente.com", "t@sulista.com.br", "", "", "op@x",
               lembrar=True, esquema=esq, enviar_=Servidor(ok=False, erro="caiu"))
    assert cadastro.perfil(pid, esquema=esq)["config"]["email"]["destinatarios"] == []
    hpe.enviar(pid, DE, ATE, "x@cliente.com", "t@sulista.com.br", "", "", "op@x",
               lembrar=True, esquema=esq, enviar_=Servidor())
    e = cadastro.perfil(pid, esquema=esq)["config"]["email"]
    assert e["destinatarios"] == ["x@cliente.com"] and e["responder_para"] == ["t@sulista.com.br"]


def test_falha_do_servidor_fica_REGISTRADA(perfil):
    pid, esq = perfil
    r = hpe.enviar(pid, DE, ATE, "x@cliente.com", "", "", "", "op@x", esquema=esq,
                   enviar_=Servidor(ok=False, erro="Servidor recusou a autenticação"))
    assert not r["ok"] and "recusou" in r["erro"]
    u = hpe.ultimo_envio(esquema=esq)
    assert u["ok"] is False and "recusou" in u["erro"]


@pytest.mark.parametrize("para, resp, trecho", [
    ("", "", "ao menos um destinatário"),
    ("nao-e-email", "", "Destinatário inválido"),
    ("x@cliente.com", "torre@", "Endereço de resposta inválido"),
])
def test_recusa_ANTES_de_tocar_no_servidor(perfil, para, resp, trecho):
    pid, esq = perfil
    srv = Servidor()
    with pytest.raises(cadastro.Recusa, match=trecho):
        hpe.enviar(pid, DE, ATE, para, resp, "", "", "op@x", esquema=esq, enviar_=srv)
    assert srv.chamadas == [] and hpe.envios(pid, esquema=esq) == []


def test_periodo_sem_carga_NAO_manda_e_mail_vazio(perfil):
    pid, esq = perfil
    srv = Servidor()
    with pytest.raises(cadastro.Recusa, match="Nenhuma carga"):
        hpe.enviar(pid, "2026-01-05", "2026-01-11", "x@cliente.com", "", "", "", "op@x",
                   esquema=esq, enviar_=srv)
    assert srv.chamadas == []


def test_config_de_e_mail_do_perfil_e_validada():
    with pytest.raises(cadastro.Recusa, match="Destinatário inválido"):
        cadastro.validar_config({"email": {"destinatarios": "fulano"}})
    cfg = cadastro.validar_config({"email": {"destinatarios": "a@x.com, B@x.com",
                                             "assunto": ""}})
    assert cfg["email"]["destinatarios"] == ["a@x.com", "b@x.com"]
    assert cfg["email"]["assunto"] == cadastro.ASSUNTO_PADRAO
