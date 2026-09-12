# -*- coding: utf-8 -*-
"""Os avisos do app do motorista (`api/motorista/avisos.py`).

O que se prova aqui é o que o desenho promete: o aviso não duplica, a PRIMEIRA
varredura não avisa, o push não leva conteúdo nem o código do ERP, o acesso
mestre não marca nem inscreve — e nenhum teste manda push de verdade nem lê o
ERP (o envio e os leitores das fontes são dublês).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api import pglocal
from api.motorista import avisos
from api.motorista.conversas import Recusa
from tests.motorista.conftest import cadastrar

RAIZ = Path(__file__).resolve().parents[2]
SUB = {"endpoint": "https://push.exemplo.test/abc",
       "keys": {"p256dh": "chave-p256dh", "auth": "chave-auth"}}


def _sess(esq, codigo, *, mestre=False) -> dict:
    """A sessão como `sessao.atual` a devolve — o código é interno."""
    l = pglocal.um("SELECT id, nome, telefone FROM mot_vinculos WHERE motorista_codigo = %(c)s",
                   {"c": codigo}, esq)
    return {"motorista_codigo": codigo, "motorista_id": int(l["id"]),
            "nome": l["nome"], "telefone": l["telefone"], "sessao_id": 1,
            "mestre": mestre}


@pytest.fixture
def dois(esq):
    cadastrar(esq, "MOT-A", "5547999990001", "ANA")
    cadastrar(esq, "MOT-B", "5547999990002", "BIA")
    cadastrar(esq, "MOT-X", "5547999990003", "XAVIER", ativo=False)
    return esq


@pytest.fixture
def push_ligado(monkeypatch):
    from api import push
    monkeypatch.setattr(push, "habilitado", lambda: True)
    monkeypatch.setattr(push, "_pub", lambda: "CHAVE-PUBLICA")


class Envio:
    """O `webpush` de mentira: anota o que sairia e responde o combinado."""

    def __init__(self, resposta: str = "ok"):
        self.chamadas: list = []
        self.resposta = resposta

    def __call__(self, sub, payload):
        self.chamadas.append((sub["endpoint"], json.loads(payload)))
        return self.resposta


# ═══════════════════════════════════════════════════════ registrar ═══════

def test_o_mesmo_recado_registrado_duas_vezes_e_UM_aviso(dois):
    assert avisos.registrar("MOT-A", "rh", "msg:1", esquema=dois)
    assert avisos.registrar("MOT-A", "rh", "msg:1", esquema=dois) is None
    assert avisos.nao_lidos("MOT-A", dois) == 1


def test_o_mural_avisa_TODOS_os_ativos_e_so_eles(dois):
    assert avisos.para_todos("mural", "comunicado:7", "Férias", esquema=dois) == 2
    assert avisos.para_todos("mural", "comunicado:7", "Férias", esquema=dois) == 0
    assert avisos.nao_lidos("MOT-X", dois) == 0, "desligado não recebe"


def test_a_resposta_do_RH_vira_aviso_UMA_vez_por_mensagem(dois):
    """Pelo caminho REAL do canal (`abrir` + `responder_rh`), e não por INSERT
    à mão: dublê de tabela tem as colunas que nós escrevemos, não as que o
    módulo grava."""
    from api.motorista import conversas as mc
    c = mc.abrir(_sess(dois, "MOT-A"), "ferias", "quando?", esquema=dois)
    assert avisos.da_conversa(c["id"], esquema=dois) is None, \
        "pedido sem resposta do RH não é aviso"
    mc.responder_rh(c["id"], "em outubro", autor_nome="rh@x", esquema=dois)
    assert avisos.da_conversa(c["id"], esquema=dois)
    assert avisos.da_conversa(c["id"], esquema=dois) is None, "a mesma resposta é um aviso só"
    mc.responder_rh(c["id"], "confirmado", autor_nome="rh@x", esquema=dois)
    assert avisos.da_conversa(c["id"], esquema=dois), "a resposta seguinte é aviso novo"
    assert avisos.nao_lidos("MOT-A", dois) == 2


# ═══════════════════════════════════════════════════════ o motorista ═════

def test_a_lista_e_DELE_e_marcar_por_aba_por_id_e_tudo(dois, push_ligado):
    a1 = avisos.registrar("MOT-A", "multa", "M1", "VELOCIDADE · 04/08", esquema=dois)
    avisos.registrar("MOT-A", "viagem", "V1", "JOINVILLE/SC → CURITIBA/PR", esquema=dois)
    avisos.registrar("MOT-B", "multa", "M9", esquema=dois)
    s = _sess(dois, "MOT-A")
    d = avisos.meus(s, dois)
    assert d["nao_lidos"] == 2 and len(d["itens"]) == 2
    assert {i["aba"] for i in d["itens"]} == {"multas", "viagem"}
    assert "MOT-A" not in json.dumps(d), "o código do ERP não sai no payload"
    assert d["push"] == {"habilitado": True, "chave": "CHAVE-PUBLICA",
                         "aparelhos": 0, "mestre": False}
    assert avisos.marcar_lidos(s, aba="multas", esquema=dois)["marcados"] == 1
    assert avisos.marcar_lidos(s, ids=[a1], esquema=dois)["marcados"] == 0, "já estava lido"
    assert avisos.marcar_lidos(s, esquema=dois)["marcados"] == 1
    assert avisos.nao_lidos("MOT-A", dois) == 0
    assert avisos.nao_lidos("MOT-B", dois) == 1, "marcar é só os DELE"


def test_id_de_aviso_de_OUTRO_motorista_nao_e_marcado(dois):
    b = avisos.registrar("MOT-B", "multa", "M9", esquema=dois)
    avisos.marcar_lidos(_sess(dois, "MOT-A"), ids=[b], esquema=dois)
    assert avisos.nao_lidos("MOT-B", dois) == 1


def test_o_acesso_MESTRE_nao_marca_nem_inscreve(dois, push_ligado):
    """Quem confere o app de um motorista não apaga o "não lido" dele, e o
    celular de quem confere não passa a receber as notificações de outro."""
    avisos.registrar("MOT-A", "multa", "M1", esquema=dois)
    m = _sess(dois, "MOT-A", mestre=True)
    assert avisos.marcar_lidos(m, esquema=dois)["marcados"] == 0
    assert avisos.nao_lidos("MOT-A", dois) == 1
    with pytest.raises(Recusa):
        avisos.inscrever(m, SUB, esquema=dois)
    assert avisos.meus(m, dois)["push"]["mestre"] is True


def test_inscricao_INVALIDA_e_recusada_com_motivo(dois, push_ligado):
    with pytest.raises(Recusa):
        avisos.inscrever(_sess(dois, "MOT-A"), {"endpoint": "http://sem-tls"}, esquema=dois)


# ═══════════════════════════════════════════════════════ o push ══════════

def test_o_push_NAO_leva_o_conteudo_nem_o_codigo(dois, push_ligado):
    """A notificação é lida na tela de bloqueio, às vezes num aparelho
    compartilhado: diz que há uma multa, não qual nem de quanto."""
    avisos.inscrever(_sess(dois, "MOT-A"), SUB, esquema=dois)
    avisos.registrar("MOT-A", "multa", "M1", "VELOCIDADE ACIMA · 04/08", esquema=dois)
    env = Envio()
    assert avisos.despachar(dois, enviar=env)["enviados"] == 1
    (_, payload), = env.chamadas
    assert payload["title"] == "Há uma nova multa no seu app."
    assert payload["url"] == "/motorista#multas"
    bruto = json.dumps(payload, ensure_ascii=False)
    assert "VELOCIDADE" not in bruto and "MOT-A" not in bruto
    assert avisos.despachar(dois, enviar=env)["enviados"] == 0, "entregue não sai de novo"


def test_varios_do_mesmo_tipo_viram_UM_push_com_a_contagem(dois, push_ligado):
    avisos.inscrever(_sess(dois, "MOT-A"), SUB, esquema=dois)
    for k in range(3):
        avisos.registrar("MOT-A", "multa", f"M{k}", esquema=dois)
    env = Envio()
    avisos.despachar(dois, enviar=env)
    assert [c[1]["title"] for c in env.chamadas] == ["Há 3 novas multas no seu app."]


def test_aparelho_MORTO_sai_da_lista(dois, push_ligado):
    avisos.inscrever(_sess(dois, "MOT-A"), SUB, esquema=dois)
    avisos.registrar("MOT-A", "rh", "msg:1", esquema=dois)
    avisos.despachar(dois, enviar=Envio("morta"))
    assert pglocal.um("SELECT count(*)::int AS n FROM mot_push_subs", esquema=dois)["n"] == 0


def test_aviso_de_ANTES_de_ligar_nao_vibra_depois_e_continua_na_lista(dois, push_ligado):
    avisos.registrar("MOT-A", "multa", "M1", esquema=dois)
    avisos.despachar(dois, enviar=Envio())            # sem aparelho: carimba 0
    avisos.inscrever(_sess(dois, "MOT-A"), SUB, esquema=dois)
    env = Envio()
    avisos.despachar(dois, enviar=env)
    assert env.chamadas == []
    assert avisos.nao_lidos("MOT-A", dois) == 1


def test_com_o_push_DESLIGADO_no_servidor_nada_sai(dois, monkeypatch):
    from api import push
    monkeypatch.setattr(push, "habilitado", lambda: False)
    avisos.registrar("MOT-A", "multa", "M1", esquema=dois)
    assert avisos.despachar(dois)["enviados"] == 0


# ═══════════════════════════════════════════════════════ a varredura ═════

class Fonte:
    def __init__(self):
        self.itens: list = []

    def __call__(self, ativos, esq):
        return list(self.itens)


@pytest.fixture
def fontes():
    return {t: Fonte() for t in avisos.FONTES}


def test_a_PRIMEIRA_varredura_nao_avisa_e_a_seguinte_so_o_NOVO(dois, fontes):
    """Sem a base, o primeiro dia seria uma avalanche de novidades velhas, e o
    motorista aprenderia no primeiro dia a ignorar o aviso."""
    fontes["multa"].itens = [{"codigo": "MOT-A", "ref": "M1", "detalhe": "antiga"}]
    r = avisos.varrer(dois, leitores=fontes)
    assert r["multa"]["novos"] == 0 and r["multa"]["base"] == 2
    assert avisos.nao_lidos("MOT-A", dois) == 0
    fontes["multa"].itens.append({"codigo": "MOT-A", "ref": "M2", "detalhe": "nova"})
    assert avisos.varrer(dois, leitores=fontes)["multa"]["novos"] == 1
    assert [i["detalhe"] for i in avisos.meus(_sess(dois, "MOT-A"), dois)["itens"]] == ["nova"]
    assert avisos.varrer(dois, leitores=fontes)["multa"]["novos"] == 0, "visto não volta"


def test_motorista_NOVO_tambem_comeca_pela_base(dois, fontes):
    avisos.varrer(dois, leitores=fontes)
    cadastrar(dois, "MOT-C", "5547999990004", "CAIO")
    fontes["viagem"].itens = [{"codigo": "MOT-C", "ref": "V1", "detalhe": "x"}]
    assert avisos.varrer(dois, leitores=fontes)["viagem"]["novos"] == 0
    assert avisos.nao_lidos("MOT-C", dois) == 0


def test_uma_fonte_que_CAI_nao_derruba_as_outras_e_fica_DITA(dois, fontes):
    avisos.varrer(dois, leitores=fontes)

    def quebra(ativos, esq):
        raise RuntimeError("ERP fora")
    fontes["registro"] = quebra
    fontes["multa"].itens = [{"codigo": "MOT-B", "ref": "M5", "detalhe": ""}]
    r = avisos.varrer(dois, leitores=fontes)
    assert r["registro"] == {"erro": "RuntimeError"} and r["multa"]["novos"] == 1
    assert "registro: RuntimeError" in avisos.contagem(dois)["varredura_erro"]


def test_item_de_motorista_DESLIGADO_nao_vira_aviso(dois, fontes):
    """Desligado DEPOIS da base: ele tem marca, e só o filtro de ativos o
    segura. (Desligado desde sempre nem chega a ter marca — esse caso não
    provaria nada.)"""
    avisos.varrer(dois, leitores=fontes)
    pglocal.executar("UPDATE mot_vinculos SET ativo = false WHERE motorista_codigo = 'MOT-B'",
                     esquema=dois)
    fontes["multa"].itens = [{"codigo": "MOT-B", "ref": "M7", "detalhe": ""}]
    avisos.varrer(dois, leitores=fontes)
    assert avisos.nao_lidos("MOT-B", dois) == 0


def test_as_consultas_do_ERP_sao_UMA_para_a_frota_e_seguem_a_politica_da_aba():
    for sql in (avisos._REGISTROS_SQL, avisos._VIAGENS_SQL):
        assert "= ANY(%(mots)s)" in sql, "uma ida ao ERP por passada, não uma por motorista"
    # a mesma política da aba Viagem: cancelada não conta, só a liberada
    assert "p.dtcancelamento IS NULL" in avisos._VIAGENS_SQL
    assert "p.semaforo = 1" in avisos._VIAGENS_SQL


# ═══════════════════════════════════════════════════════ pelas ROTAS ═════
#
# Os ganchos moram em `api/main.py`, e o módulo não os vê: sem estes testes, o
# `da_conversa` e o `para_todos` podiam sair das rotas do RH com a suíte verde.

def test_o_eu_traz_os_avisos_novos_numa_conta_PROPRIA(dois):
    from api import main
    avisos.registrar("MOT-A", "multa", "M1", esquema=dois)
    d = main._mot_avisos(_sess(dois, "MOT-A"))
    assert d["novos"] == 1
    assert d["conversas"] == 0, "multa nova não acende a bolinha do RH"


def test_a_resposta_do_RH_PELA_ROTA_vira_aviso(dois, zap):
    """`_avisar_motorista` é o que as duas rotas do RH chamam; o WhatsApp vai
    pelo dublê (`zap`) — nenhum teste manda mensagem."""
    import asyncio

    from api import main
    from api.motorista import conversas as mc
    c = mc.abrir(_sess(dois, "MOT-A"), "ferias", "quando?", esquema=dois)
    mc.responder_rh(c["id"], "em outubro", autor_nome="rh@x", esquema=dois)
    asyncio.run(main._avisar_motorista(c["id"]))
    assert avisos.nao_lidos("MOT-A", dois) == 1


def test_o_comunicado_do_mural_PELA_ROTA_vira_aviso_para_todos(dois, monkeypatch):
    """A rota inteira do mural, com a sessão do RH dublada (é a única parte
    que não é deste assunto)."""
    import asyncio

    from api import main

    async def escrever(req, acao, evento, alvo=None):
        return main.JSONResponse(acao(None, "rh@x"))

    class Pedido:
        async def json(self):
            return {"titulo": "Convenção coletiva", "texto": "O reajuste entra em outubro."}

    monkeypatch.setattr(main, "_rh_conversa_escrever", escrever)
    r = asyncio.run(main.rh_mural_publicar(Pedido()))
    assert r.status_code == 200
    assert avisos.nao_lidos("MOT-A", dois) == 1
    assert avisos.nao_lidos("MOT-B", dois) == 1
    assert avisos.nao_lidos("MOT-X", dois) == 0


# ═══════════════════════════════════════════════════════ o relógio ═══════

def test_o_relogio_dos_avisos_NAO_sobe_numa_rodada_de_teste(monkeypatch):
    """Com a função REAL do gate. A varredura de threads vivas
    (`test_agendadores_sob_teste`) só pega a thread se algum teste tiver
    subido o startup antes dela — sozinha, ela passaria com o gate arrancado."""
    import threading

    from api.motorista import agendador
    monkeypatch.delenv("MOTORISTA_AVISOS", raising=False)
    monkeypatch.setattr(agendador, "_iniciado", False)
    antes = {t.name for t in threading.enumerate()}
    agendador.iniciar()
    assert "motorista-avisos" not in ({t.name for t in threading.enumerate()} - antes)


def test_fora_de_teste_o_relogio_SOBE_com_o_nome_da_varredura(monkeypatch):
    """O contrapeso: sem ele, o teste de cima passaria com `iniciar` vazia."""
    from api.motorista import agendador
    monkeypatch.delenv("MOTORISTA_AVISOS", raising=False)
    monkeypatch.setattr(agendador, "sob_teste", lambda: False)
    monkeypatch.setattr(agendador, "_iniciado", False)
    subidas = []
    monkeypatch.setattr(agendador.threading, "Thread", lambda **kw: type("T", (), {
        "start": lambda s: subidas.append(kw.get("name"))})())
    agendador.iniciar()
    assert subidas == ["motorista-avisos"]


# ═══════════════════════════════════════════════════════ o service worker ═

def test_o_service_worker_do_motorista_NAO_faz_cache():
    """`docs/APP_MOTORISTA.md` adiou o PWA porque service worker com cache
    serve versão velha para sempre. Este é só de notificação: sem `fetch`."""
    js = (RAIZ / "api" / "static" / "motorista-sw.js").read_text(encoding="utf-8")
    codigo = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    assert "addEventListener('push'" in codigo
    assert "addEventListener('notificationclick'" in codigo
    assert "fetch" not in codigo, "service worker com fetch é cache"


def test_o_service_worker_e_servido_da_RAIZ_sem_sessao():
    """Da raiz, para poder ter o escopo `/motorista`; público, porque o
    navegador o baixa sem cookie nenhum."""
    from fastapi.testclient import TestClient

    from api.main import app
    r = TestClient(app).get("/motorista-sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "notificationclick" in r.text
