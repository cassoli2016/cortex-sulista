"""Envio de e-mail: configuração, validação, trilha e o envio em si.

Nenhum teste toca a rede nem o data/ real: `config.CAMINHO` vai para tmp_path,
a trilha vai para um SCHEMA exclusivo do teste no PostgreSQL local (a trilha
migrou do SQLite em 27/08/2026) e o SMTP é dublê. Sem banco, os testes da
trilha se pulam dizendo por quê — ver tests/conftest.py.
"""
from __future__ import annotations

import smtplib

import pytest

from api.correio import config as cfg
from api.correio import envio, registro


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch, esquema_pg):
    """Isola arquivo de config, trilha e cofre da senha."""
    monkeypatch.setattr(cfg, "CAMINHO", tmp_path / "email_config.json")
    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(cfg, "senha", lambda: "segredo")
    return tmp_path


def _config_valida():
    return cfg.gravar({"host": "smtp.teste.local", "porta": 587,
                       "seguranca": "starttls", "usuario": "bot@sulista.com.br",
                       "remetente": "bot@sulista.com.br", "remetente_nome": "CÓRTEX"})


class SMTPFake:
    """Dublê de smtplib.SMTP. Guarda o que foi chamado para os testes olharem."""
    ultima = None

    def __init__(self, host=None, porta=None, timeout=None, **kw):
        self.host, self.porta, self.timeout = host, porta, timeout
        self.logou = False
        self.enviadas = []
        self.starttls_chamado = False
        SMTPFake.ultima = self

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, context=None): self.starttls_chamado = True
    def login(self, u, s): self.logou = True
    def send_message(self, msg): self.enviadas.append(msg)


# ----------------------------------------------------------------- helpers

def test_separar_destinatarios_aceita_virgula_pontoevirgula_e_quebra():
    assert cfg.separar_destinatarios("a@b.com, c@d.com; e@f.com\ng@h.com") == [
        "a@b.com", "c@d.com", "e@f.com", "g@h.com"]


def test_separar_destinatarios_aceita_lista_e_descarta_vazio():
    assert cfg.separar_destinatarios(["a@b.com", "  ", "c@d.com"]) == ["a@b.com", "c@d.com"]


@pytest.mark.parametrize("bom", ["a@b.com", "nome.sobrenome@sulista.com.br"])
def test_email_valido_aceita(bom):
    assert cfg.email_valido(bom)


@pytest.mark.parametrize("ruim", ["a@", "sem-arroba", "a@b", "", "a b@c.com"])
def test_email_valido_recusa(ruim):
    assert not cfg.email_valido(ruim)


# ----------------------------------------------------------------- config

def test_config_nasce_nao_configurada():
    assert cfg.configurado() is False
    assert cfg.status()["configurado"] is False


def test_gravar_config_valida_e_marca_configurado():
    st = _config_valida()
    assert st["configurado"] is True
    assert st["host"] == "smtp.teste.local"
    assert cfg.ler()["porta"] == 587


@pytest.mark.parametrize("dados,trecho", [
    ({"host": "", "remetente": "a@b.com"}, "servidor SMTP"),
    ({"host": "x", "porta": "abc", "remetente": "a@b.com"}, "Porta inválida"),
    ({"host": "x", "porta": 99999, "remetente": "a@b.com"}, "Porta inválida"),
    ({"host": "x", "porta": 587, "remetente": "invalido"}, "Remetente inválido"),
    ({"host": "x", "porta": 587, "remetente": "a@b.com", "seguranca": "xpto"}, "Segurança inválida"),
])
def test_gravar_config_recusa_entrada_invalida(dados, trecho):
    with pytest.raises(ValueError, match=trecho):
        cfg.gravar(dados)


def test_status_nunca_devolve_a_senha():
    _config_valida()
    st = cfg.status()
    assert "senha" not in st
    assert "segredo" not in str(st)
    assert st["senha_configurada"] is True   # só o SE, nunca o QUAL


# ----------------------------------------------------------------- validação de envio

@pytest.mark.parametrize("dest,assunto,trecho", [
    ("", "Assunto", "ao menos um destinatário"),
    ("nao-eh-email", "Assunto", "Destinatário inválido"),
    ("a@b.com", "", "Informe o assunto"),
])
def test_envio_recusa_entrada_invalida_sem_levantar(dest, assunto, trecho):
    _config_valida()
    r = envio.enviar(dest, assunto, "corpo")
    assert r["ok"] is False
    assert trecho in r["erro"]


def test_envio_sem_configuracao_avisa_onde_configurar():
    r = envio.enviar("a@b.com", "Assunto", "corpo")
    assert r["ok"] is False
    assert "não configurado" in r["erro"]
    assert "Gestão" in r["erro"]


def test_falha_de_validacao_tambem_entra_na_trilha():
    """Registro só de sucesso esconderia justamente o caso a investigar."""
    envio.enviar("", "Assunto", "corpo")
    assert registro.resumo()["falha"] == 1


# ----------------------------------------------------------------- envio

def test_envio_bem_sucedido_usa_starttls_loga_e_registra(monkeypatch):
    _config_valida()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFake)
    r = envio.enviar("cliente@x.com", "Oi", "corpo", usuario="admin@sulista.com.br",
                     origem="teste")
    assert r["ok"] is True and r["erro"] == ""
    s = SMTPFake.ultima
    assert s.starttls_chamado is True and s.logou is True
    assert s.timeout == envio.TIMEOUT, "sem timeout o worker do uvicorn trava"
    assert len(s.enviadas) == 1
    linha = registro.listar()[0]
    assert linha["ok"] == 1 and linha["usuario"] == "admin@sulista.com.br"


def test_sem_usuario_configurado_o_login_e_pulado(monkeypatch):
    """Relay interno autenticado por IP recusa AUTH — logar quebraria o envio."""
    cfg.gravar({"host": "relay.local", "porta": 25, "seguranca": "nenhuma",
                "usuario": "", "remetente": "bot@sulista.com.br"})
    monkeypatch.setattr(smtplib, "SMTP", SMTPFake)
    r = envio.enviar("a@b.com", "Oi", "corpo")
    assert r["ok"] is True
    assert SMTPFake.ultima.logou is False
    assert SMTPFake.ultima.starttls_chamado is False


def test_erro_de_autenticacao_nao_vaza_resposta_bruta_do_servidor(monkeypatch):
    _config_valida()

    def explode(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 user bot@sulista.com.br rejected")
    monkeypatch.setattr(smtplib, "SMTP", explode)
    r = envio.enviar("a@b.com", "Oi", "corpo")
    assert r["ok"] is False
    assert "bot@sulista.com.br" not in r["erro"], "eco do servidor vazaria o usuário"
    assert "senha de aplicativo" in r["erro"]


def test_servidor_fora_do_ar_vira_mensagem_acionavel(monkeypatch):
    _config_valida()

    def explode(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(smtplib, "SMTP", explode)
    r = envio.enviar("a@b.com", "Oi", "corpo")
    assert r["ok"] is False
    assert "firewall" in r["erro"]


def test_envio_nunca_levanta_mesmo_com_erro_inesperado(monkeypatch):
    """Contrato do módulo: rotina agendada não pode morrer por causa do SMTP."""
    _config_valida()

    def explode(*a, **k):
        raise RuntimeError("coisa estranha")
    monkeypatch.setattr(smtplib, "SMTP", explode)
    r = envio.enviar("a@b.com", "Oi", "corpo")
    assert r["ok"] is False and "RuntimeError" in r["erro"]


def test_html_vai_como_alternativa_do_texto(monkeypatch):
    _config_valida()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFake)
    envio.enviar("a@b.com", "Oi", "texto puro", corpo_html="<b>rico</b>")
    msg = SMTPFake.ultima.enviadas[0]
    assert msg.is_multipart()
    tipos = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in tipos and "text/html" in tipos


def test_ssl_direto_nao_chama_starttls(monkeypatch):
    cfg.gravar({"host": "smtp.x.com", "porta": 465, "seguranca": "ssl",
                "usuario": "u@x.com", "remetente": "u@x.com"})
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFake)
    r = envio.enviar("a@b.com", "Oi", "corpo")
    assert r["ok"] is True
    assert SMTPFake.ultima.starttls_chamado is False


# ----------------------------------------------------------------- trilha

def test_corpo_grande_e_truncado_na_trilha(esquema_pg):
    registro.gravar(["a@b.com"], "Assunto", "x" * 10000, ok=True)
    assert len(registro.listar()[0].get("assunto")) > 0
    # o corpo não volta na listagem (é da tela), mas foi truncado ao gravar
    from api import pglocal
    r = pglocal.um("SELECT length(corpo) AS n FROM correio_envios",
                   esquema=esquema_pg)
    assert r["n"] == registro.MAX_CORPO


def test_resumo_conta_ok_e_falha():
    registro.gravar(["a@b.com"], "A", "x", ok=True)
    registro.gravar(["a@b.com"], "B", "x", ok=False, erro="deu ruim")
    r = registro.resumo()
    assert r["total"] == 2 and r["ok"] == 1 and r["falha"] == 1


# ---------------------------------------------------------------------------
# Porta/host de LEITURA no formulário de ENVIO. Caso real: a configuração foi
# gravada com outlook.office365.com:995 (POP3 sobre SSL) e cinco testes de
# envio seguidos falharam com "Erro do servidor SMTP: SMTPConnectError." —
# sem host, sem porta, sem pista do que consertar.
# ---------------------------------------------------------------------------

def test_porta_de_leitura_e_recusada_na_gravacao():
    with pytest.raises(ValueError) as e:
        cfg.gravar({"host": "outlook.office365.com", "porta": 995,
                    "seguranca": "ssl", "remetente": "x@sulista.com.br"})
    msg = str(e.value)
    assert "995" in msg and "POP3" in msg
    # a mensagem tem de trazer o CONSERTO, não só o diagnóstico
    assert "smtp.office365.com" in msg and "587" in msg


def test_host_de_leitura_e_recusado_mesmo_com_porta_certa():
    with pytest.raises(ValueError, match="smtp.office365.com"):
        cfg.gravar({"host": "outlook.office365.com", "porta": 587,
                    "seguranca": "starttls", "remetente": "x@sulista.com.br"})


def test_host_de_envio_legitimo_passa():
    st = cfg.gravar({"host": "smtp.office365.com", "porta": 587,
                     "seguranca": "starttls", "remetente": "x@sulista.com.br"})
    assert st["host"] == "smtp.office365.com" and st["porta"] == 587


def test_prefixo_pop_vira_sugestao_de_smtp():
    assert "smtp.empresa.com.br" in cfg.problema_de_leitura("pop.empresa.com.br", 995)


def test_servidor_proprio_em_porta_de_envio_nao_gera_aviso():
    assert cfg.problema_de_leitura("smtp.sulista.com.br", 587) is None
    assert cfg.problema_de_leitura("mail.sulista.com.br", 465) is None


def test_erro_de_conexao_diz_contra_qual_servidor_tentou(monkeypatch):
    """O operador precisa saber host, porta e segurança para consertar."""
    _config_valida()
    def _explode(*a, **kw):
        raise smtplib.SMTPConnectError(421, b"nao atendeu")
    monkeypatch.setattr(smtplib, "SMTP", _explode)
    r = envio.enviar("a@sulista.com.br", "assunto", "corpo")
    assert not r["ok"]
    assert "smtp.teste.local" in r["erro"] and "587" in r["erro"]
    assert "starttls" in r["erro"]


def test_falha_no_m365_cita_o_smtp_autenticado_desligado(monkeypatch):
    """535 5.7.139 no Microsoft 365 quase nunca é senha errada."""
    cfg.gravar({"host": "smtp.office365.com", "porta": 587,
                "seguranca": "starttls", "usuario": "bot@sulista.com.br",
                "remetente": "bot@sulista.com.br"})
    def _explode(*a, **kw):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.139 auth disabled")
    monkeypatch.setattr(smtplib, "SMTP", _explode)
    r = envio.enviar("a@sulista.com.br", "assunto", "corpo")
    assert "Authenticated SMTP" in r["erro"]
