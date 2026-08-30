"""Falar com o contato pelo CRM — WhatsApp e e-mail.

O que se prova aqui, e que nenhum dos outros testes cobre:

1. **Ninguém digita telefone.** O destino vem do CONTATO cadastrado, pelo id.
   Campo livre numa tela de CRM é o caminho para disparar para número que
   ninguém conferiu, sem passar pelo cadastro.
2. **Recusa do envio NÃO vira interação.** Nada saiu para fora, e uma
   interação gravada faria o "dias sem contato" da conta contar um contato que
   não houve — mentindo justamente para o lado que esconde o problema.
3. **O e-mail passa pelo ENVELOPE do layout da casa.** `cabecalho` e
   `paragrafo` devolvem `<tr><td>…</td></tr>`; concatená-los sem
   `documento()` produz linha de tabela órfã, que o Outlook (motor do Word)
   descarta — e a mensagem chega desmontada sem ninguém ficar sabendo.
4. **O envio é o MESMO caminho de sempre.** Não existe "modo CRM" mais frouxo:
   um caminho paralelo viraria o atalho para disparar sem trilha, sem limite
   diário e sem janela de horário.
"""
from __future__ import annotations

import pytest

from api.crm import atividades, comum, contas, mensagens
from api.validacao import DadoInvalido


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    return esquema_pg


def _conta_com_contato(esq, **extra):
    c = contas.gravar({"nome": "TUPY", "dono_nome": "Ana"}, usuario="t",
                      esquema=esq)
    base = {"conta_id": c["id"], "nome": "Carlos Compras",
            "telefone": "(47) 99999-8888", "email": "carlos@tupy.com.br"}
    ct = contas.gravar_contato({**base, **extra}, usuario="t", esquema=esq)
    return c, ct


# ------------------------------------------------------------------ WhatsApp

def test_envio_usa_o_telefone_DO_CADASTRO(esq, monkeypatch):
    vistos = {}

    def falso(telefone, mensagem, **kw):
        vistos.update(telefone=telefone, mensagem=mensagem, **kw)
        return {"ok": True, "telefone": telefone, "message_id": "abc"}

    from api.whatsapp import envio as we
    monkeypatch.setattr(we, "enviar", falso)
    c, ct = _conta_com_contato(esq)
    r = mensagens.whatsapp(ct["id"], mensagem="Bom dia", usuario="ana@x",
                           esquema=esq)
    assert r["envio"]["ok"] is True
    # NORMALIZADO, como está no cadastro — e não como alguém digitaria
    assert vistos["telefone"] == "5547999998888"
    # e passou pela porta de sempre, com a origem marcada para a auditoria
    assert vistos["origem"] == "crm"


def test_contato_sem_telefone_recusa_dizendo_o_conserto(esq):
    c, ct = _conta_com_contato(esq, telefone="")
    with pytest.raises(DadoInvalido) as e:
        mensagens.whatsapp(ct["id"], mensagem="oi", esquema=esq)
    assert "não tem telefone cadastrado" in str(e.value)
    assert "ficha do contato" in str(e.value)


def test_contato_inativo_recusa(esq):
    """Inativo costuma significar que a pessoa saiu da empresa."""
    c, ct = _conta_com_contato(esq)
    contas.gravar_contato({"conta_id": c["id"], "nome": ct["nome"],
                           "telefone": ct["telefone_fmt"], "ativo": False},
                          usuario="t", contato_id=ct["id"], esquema=esq)
    with pytest.raises(DadoInvalido) as e:
        mensagens.whatsapp(ct["id"], mensagem="oi", esquema=esq)
    assert "inativo" in str(e.value)


def test_envio_bem_sucedido_registra_a_interacao_sozinho(esq, monkeypatch):
    """O ganho não é o botão: é a interação nascer sozinha. CRM em que
    registrar é uma segunda tarefa manual é CRM com histórico vazio."""
    from api.whatsapp import envio as we
    monkeypatch.setattr(we, "enviar",
                        lambda t, m, **k: {"ok": True, "telefone": t,
                                           "message_id": "x"})
    c, ct = _conta_com_contato(esq)
    mensagens.whatsapp(ct["id"], mensagem="Proposta enviada", usuario="ana@x",
                       esquema=esq)
    hist = atividades.interacoes(conta_id=c["id"], esquema=esq)
    assert len(hist) == 1
    assert hist[0]["canal"] == "whatsapp"
    assert hist[0]["automatica"] is True
    assert hist[0]["resumo"] == "Proposta enviada"
    assert hist[0]["contato_id"] == ct["id"]


def test_recusa_do_envio_NAO_vira_interacao(esq, monkeypatch):
    """Nada saiu para fora. Gravar aqui faria o "dias sem contato" contar um
    contato que não houve — mentindo para o lado que esconde o problema."""
    from api.whatsapp import envio as we
    monkeypatch.setattr(we, "enviar",
                        lambda t, m, **k: {"ok": False, "telefone": t,
                                           "erro": "O envio está DESLIGADO."})
    c, ct = _conta_com_contato(esq)
    r = mensagens.whatsapp(ct["id"], mensagem="oi", usuario="ana@x",
                           esquema=esq)
    assert r["envio"]["ok"] is False
    assert r["interacao"] is None
    assert atividades.interacoes(conta_id=c["id"], esquema=esq) == []


def test_falha_ao_registrar_NAO_esconde_que_a_mensagem_saiu(esq, monkeypatch):
    """A mensagem já saiu; reportar erro faria a pessoa reenviar, e o cliente
    receber duas vezes. A falha do registro é reportada COMO TAL, ao lado do
    sucesso do envio."""
    from api.whatsapp import envio as we
    monkeypatch.setattr(we, "enviar",
                        lambda t, m, **k: {"ok": True, "telefone": t,
                                           "message_id": "x"})
    monkeypatch.setattr(atividades, "registrar",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    c, ct = _conta_com_contato(esq)
    r = mensagens.whatsapp(ct["id"], mensagem="oi", usuario="ana@x",
                           esquema=esq)
    assert r["envio"]["ok"] is True
    assert r["interacao"] is None
    assert r["interacao_erro"] == "RuntimeError"


# -------------------------------------------------------------------- e-mail

def test_email_passa_pelo_envelope_do_layout_da_casa(esq, monkeypatch):
    """`cabecalho` e `paragrafo` devolvem `<tr><td>…</td></tr>`.

    Sem `documento()` o corpo sai como linha de tabela ÓRFÃ, que o Outlook
    (motor do Word) descarta ou renderiza fora de ordem — e a mensagem chega
    desmontada sem ninguém ficar sabendo.
    """
    capturado = {}

    def falso(dests, assunto, corpo, *, corpo_html=None, **kw):
        capturado.update(dests=dests, assunto=assunto, corpo=corpo,
                         html=corpo_html, **kw)
        return {"ok": True, "erro": "", "destinatarios": dests}

    from api.correio import envio as ce
    monkeypatch.setattr(ce, "enviar", falso)
    c, ct = _conta_com_contato(esq)
    mensagens.email(ct["id"], assunto="Proposta 2027",
                    corpo="Bom dia\n\nSegue a proposta.", usuario="ana@x",
                    esquema=esq)
    html = capturado["html"]
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert html.count("<table") >= 1
    # e as regras de e-mail da casa continuam valendo neste corpo
    assert "display:flex" not in html and "display:grid" not in html
    # o corpo em TEXTO PURO é o que garante ler a mensagem quando o HTML não
    # renderiza — não é formalidade
    assert "Segue a proposta." in capturado["corpo"]


def test_email_tambem_registra_a_interacao(esq, monkeypatch):
    from api.correio import envio as ce
    monkeypatch.setattr(ce, "enviar",
                        lambda d, a, c, **k: {"ok": True, "erro": "",
                                              "destinatarios": d})
    c, ct = _conta_com_contato(esq)
    mensagens.email(ct["id"], assunto="Proposta", corpo="texto",
                    usuario="ana@x", esquema=esq)
    hist = atividades.interacoes(conta_id=c["id"], esquema=esq)
    assert len(hist) == 1 and hist[0]["canal"] == "email"
    assert hist[0]["automatica"] is True


def test_canais_indisponiveis_dizem_o_conserto(monkeypatch):
    """Botão que sempre falha é pior que botão ausente: ensina que o sistema
    está quebrado. A tela desabilita e diz por quê, com o caminho."""
    from api.whatsapp import cliente as wc
    monkeypatch.setattr(wc, "configurado", lambda *a, **k: False)
    d = mensagens.canais_disponiveis()
    assert d["whatsapp"]["disponivel"] is False
    assert "Gestão" in d["whatsapp"]["motivo"]
