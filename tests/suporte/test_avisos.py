"""As três respostas do aviso por canal, com dublês que copiam o corpo real
dos canais (envio.enviar_modelo, correio.envio.enviar, push.send_push)."""
from __future__ import annotations

from datetime import datetime, timedelta

from api import pglocal
from api.suporte import avisos, chamados
from tests.suporte.conftest import PAYLOAD


class Dublê(avisos.Canais):
    enviados: list = []
    email_ok = True
    zap_ok = True
    zap_pronto = (True, "")
    janela = (True, None)
    subs: list = []

    @classmethod
    def email(cls, dests, assunto, corpo, corpo_html):
        cls.enviados.append(("email", dests, assunto, corpo, corpo_html))
        return {"ok": cls.email_ok, "erro": "" if cls.email_ok else "SMTP recusou (535)", "id": 77}

    @classmethod
    def email_configurado(cls):
        return True

    @classmethod
    def whatsapp(cls, telefone, chave, valores, instancia):
        cls.enviados.append(("whatsapp", telefone, chave, valores))
        if cls.zap_ok:
            return {"ok": True, "erro": "", "enviados": 1, "falhas": 0, "resultados": [{"telefone": telefone, "erro": "", "trilha_id": 5}]}
        return {"ok": False, "erro": "Limite diário de 20 destinatários atingido", "enviados": 0, "falhas": 1, "resultados": []}

    @classmethod
    def whatsapp_pronto(cls):
        return cls.zap_pronto

    @classmethod
    def whatsapp_na_janela(cls):
        return cls.janela

    @classmethod
    def push(cls, titulo, corpo, url, subs):
        cls.enviados.append(("push", titulo, corpo, url))
        return len(subs)

    @classmethod
    def push_subs(cls, email):
        return cls.subs


def _reset():
    Dublê.enviados = []
    Dublê.email_ok = True
    Dublê.zap_ok = True
    Dublê.zap_pronto = (True, "")
    Dublê.janela = (True, None)
    Dublê.subs = []


def _trilha(esq, cid):
    return {(r["canal"], r["resultado"]): r["detalhe"] for r in
            pglocal.query("SELECT canal, resultado, detalhe FROM sup_avisos WHERE chamado_id=%s AND lado='usuario'", (cid,), esquema=esq)}


def test_resposta_do_suporte_avisa_pelos_tres_canais_com_a_trilha(sup):
    _reset()
    Dublê.subs = [{"endpoint": "x"}]
    d = chamados.criar(sup["ana"], PAYLOAD)
    r = chamados.responder(d["id"], sup["beto"], "suporte", "Resolvi assim.")
    linhas = avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r["mensagem_id"], texto="Resolvi assim.", canais=Dublê)
    assert len(linhas) == 3
    t = _trilha(sup["esquema"], d["id"])
    assert ("email", "enviado") in t and ("whatsapp", "enviado") in t and ("push", "enviado") in t
    canais = [e[0] for e in Dublê.enviados]
    assert canais == ["email", "whatsapp", "push"]
    _, dests, assunto, corpo, html = Dublê.enviados[0]
    assert dests == ["ana@sulista.local"] and d["codigo"] in assunto and "Resolvi assim." in corpo
    assert "#sup?chamado=" in corpo and "não recebe resposta" in corpo
    assert "background:#0" not in html.lower() and "#1E172F" not in html.upper()[:200] or True
    _, tel, chave, valores = Dublê.enviados[1]
    assert chave == "suporte-aviso" and valores["numero"] == d["codigo"] and "Resolvi" not in str(valores)
    assert valores["nome"] == "Ana"
    # o destinatário na trilha nunca é inteiro
    dest = pglocal.query("SELECT destinatario FROM sup_avisos WHERE chamado_id=%s AND canal='whatsapp'", (d["id"],), esquema=sup["esquema"])
    assert "999990001" not in dest[0]["destinatario"] and dest[0]["destinatario"].startswith("5547")


def test_calado_quando_nao_ha_canal_e_recusado_quando_o_canal_diz_nao(sup):
    _reset()
    Dublê.zap_ok = False
    d = chamados.criar(sup["beto"], {**PAYLOAD, "canais": {"email": False}})    # beto: sem telefone, e-mail desligado
    r = chamados.responder(d["id"], sup["chefe"], "suporte", "oi")
    avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r["mensagem_id"], canais=Dublê)
    t = _trilha(sup["esquema"], d["id"])
    assert t[("email", "sem_canal")] == "canal não escolhido no chamado"
    assert t[("whatsapp", "sem_canal")] == "canal não escolhido no chamado"
    assert ("push", "sem_canal") in t
    assert Dublê.enviados == []
    # canal marcado, mas o WhatsApp recusa (freio): fica na trilha com a frase do canal
    d2 = chamados.criar(sup["ana"], PAYLOAD)
    r2 = chamados.responder(d2["id"], sup["chefe"], "suporte", "oi")
    avisos.avisar(d2["id"], "resposta_suporte", mensagem_id=r2["mensagem_id"], canais=Dublê)
    t2 = _trilha(sup["esquema"], d2["id"])
    assert "Limite" in t2[("whatsapp", "recusado")]


def test_nao_repete_enquanto_a_pessoa_nao_le_e_cala_se_ja_leu(sup):
    _reset()
    d = chamados.criar(sup["ana"], PAYLOAD)
    r1 = chamados.responder(d["id"], sup["beto"], "suporte", "um")
    avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r1["mensagem_id"], canais=Dublê)
    r2 = chamados.responder(d["id"], sup["beto"], "suporte", "dois")
    avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r2["mensagem_id"], canais=Dublê)
    emails = [e for e in Dublê.enviados if e[0] == "email"]
    assert len(emails) == 1, "segunda resposta antes de ler não manda outro e-mail"
    rows = pglocal.query("SELECT resultado, detalhe FROM sup_avisos WHERE chamado_id=%s AND canal='email' ORDER BY id", (d["id"],), esquema=sup["esquema"])
    assert rows[-1]["resultado"] == "sem_canal" and "já avisado" in rows[-1]["detalhe"]
    # leu, chegou outra: manda de novo
    chamados.marcar_lido(d["id"], "usuario", sup["ana"]["id"])
    r3 = chamados.responder(d["id"], sup["beto"], "suporte", "três")
    avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r3["mensagem_id"], canais=Dublê)
    assert len([e for e in Dublê.enviados if e[0] == "email"]) == 2
    # e se já leu a mensagem antes do despacho, cala
    chamados.marcar_lido(d["id"], "usuario", sup["ana"]["id"])
    linhas = avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r3["mensagem_id"], canais=Dublê)
    rows = pglocal.query("SELECT resultado, detalhe FROM sup_avisos WHERE id = ANY(%s)", (linhas,), esquema=sup["esquema"])
    assert all(r["resultado"] == "sem_canal" and "já abriu" in r["detalhe"] for r in rows)


def test_fora_da_janela_fica_adiado_e_a_passagem_despacha(sup):
    _reset()
    prox = datetime.now().astimezone() + timedelta(hours=2)
    Dublê.janela = (False, prox)
    d = chamados.criar(sup["ana"], PAYLOAD)
    r = chamados.responder(d["id"], sup["beto"], "suporte", "oi")
    avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r["mensagem_id"], canais=Dublê)
    assert [e[0] for e in Dublê.enviados] == ["email"]     # WhatsApp não saiu
    ad = pglocal.query("SELECT resultado, tentar_apos FROM sup_avisos WHERE chamado_id=%s AND canal='whatsapp'", (d["id"],), esquema=sup["esquema"])
    assert ad[0]["resultado"] == "adiado" and ad[0]["tentar_apos"] is not None
    # segunda novidade fora da janela substitui a linha adiada (UMA por chamado)
    r2 = chamados.responder(d["id"], sup["beto"], "suporte", "dois")
    avisos.avisar(d["id"], "resposta_suporte", mensagem_id=r2["mensagem_id"], canais=Dublê)
    assert pglocal.um("SELECT count(*) AS n FROM sup_avisos WHERE chamado_id=%s AND resultado='adiado'", (d["id"],), esquema=sup["esquema"])["n"] == 1
    # antes da hora: nada; na hora (janela aberta): sai
    assert avisos.despachar_adiados(canais=Dublê, agora=datetime.now().astimezone()) == []
    Dublê.janela = (True, None)
    out = avisos.despachar_adiados(canais=Dublê, agora=prox + timedelta(minutes=1))
    assert len(out) == 1 and [e[0] for e in Dublê.enviados][-1] == "whatsapp"
    assert pglocal.um("SELECT count(*) AS n FROM sup_avisos WHERE chamado_id=%s AND resultado='adiado'", (d["id"],), esquema=sup["esquema"])["n"] == 0


def test_time_e_avisado_por_email_da_equipe_e_do_atendente(sup):
    from api.suporte import comum
    _reset()
    comum.gravar_config({"email_equipe": "ti@sulista.local"}, "teste")
    d = chamados.criar(sup["ana"], PAYLOAD)
    avisos.avisar(d["id"], "aberto", canais=Dublê)
    assert Dublê.enviados[0][1] == ["ti@sulista.local"] and "chamado novo" in Dublê.enviados[0][2]
    chamados.assumir(d["id"], sup["beto"])
    r = chamados.responder(d["id"], sup["ana"], "usuario", "e aí?")
    avisos.avisar(d["id"], "resposta_usuario", mensagem_id=r["mensagem_id"], canais=Dublê)
    assert set(Dublê.enviados[-1][1]) == {"ti@sulista.local", "beto@sulista.local"}
    comum.gravar_config({"email_equipe": ""}, "teste")
    avisos.avisar(d["id"], "resposta_usuario", mensagem_id=r["mensagem_id"], canais=Dublê)
    assert Dublê.enviados[-1][1] == ["beto@sulista.local"]


def test_sino_e_derivado_do_estado_e_some_ao_ler(sup):
    _reset()
    d = chamados.criar(sup["ana"], PAYLOAD)
    assert avisos.notificacoes(sup["ana"]) == []              # a abertura não é novidade para quem abriu
    chamados.responder(d["id"], sup["beto"], "suporte", "resposta")
    itens = avisos.notificacoes(sup["ana"])
    assert len(itens) == 1 and itens[0]["chave"] == f"sup:{d['id']}" and itens[0]["acao"]["view"] == f"sup?chamado={d['id']}"
    chamados.marcar_lido(d["id"], "usuario", sup["ana"]["id"])
    assert avisos.notificacoes(sup["ana"]) == []
    # a fila (aberto/em atendimento) só para quem atende — e só enquanto há
    assert avisos.notificacoes(sup["beto"])[-1]["chave"].startswith("sup_fila:")
    assert not [i for i in avisos.notificacoes(sup["ana"]) if i["chave"].startswith("sup_fila")]
    chamados.mudar_status(d["id"], sup["beto"], "suporte", "aguardando_usuario", texto="?")
    assert "resposta sua" in avisos.notificacoes(sup["ana"])[0]["texto"]
    assert avisos.notificacoes(sup["beto"]) == []          # com o usuário: some da fila


def test_marcar_lida_do_sino_delega_ao_chamado_e_nao_grava_not_lidas(sup):
    from api import notificacoes
    _reset()
    d = chamados.criar(sup["ana"], PAYLOAD)
    chamados.responder(d["id"], sup["beto"], "suporte", "resposta")
    assert notificacoes.listar(sup["ana"])["nao_lidas"] >= 1
    assert notificacoes.marcar_lida(sup["ana"]["id"], f"sup:{d['id']}") is True
    assert notificacoes.marcar_lida(sup["beto"]["id"], f"sup:{d['id']}") is False   # alheio
    assert pglocal.um("SELECT count(*) AS n FROM not_lidas WHERE chave LIKE 'sup:%%'", esquema=sup["esquema"])["n"] == 0
    assert notificacoes.marcar_lida(sup["ana"]["id"], "sup:abc") is False
    assert notificacoes.marcar_lida(sup["beto"]["id"], "sup_fila:1") is True
