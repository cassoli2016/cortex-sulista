"""O serviço de chamados sobre um schema descartável: gravação, ownership,
transições, derivados com relógio injetado, leitura, indicadores."""
from __future__ import annotations

from datetime import timedelta

import pytest

from api import pglocal
from api.suporte import chamados, comum
from api.suporte.comum import TransicaoInvalida
from api.validacao import DadoInvalido
from tests.suporte.conftest import PAYLOAD


def _abrir(sup, **kw):
    p = {**PAYLOAD, **kw}
    return chamados.criar(sup["ana"], p)


def _audit(esq, acao):
    return pglocal.query("SELECT alvo, detalhe FROM audit_log WHERE acao=%s ORDER BY id", (acao,), esquema=esq)


def test_abrir_grava_codigo_anexo_mensagem_de_sistema_e_audit(sup):
    d = _abrir(sup)
    assert d["codigo"].startswith("SUP-") and d["codigo"].endswith("-0001")
    assert d["status"] == "aberto" and d["usuario_id"] == sup["ana"]["id"]
    assert d["avisar_email"] is True and d["avisar_whatsapp"] is True
    assert d["contexto"]["tela"] == "fluxo" and d["tela"] == "fluxo"
    assert len(d["anexos"]) == 1 and d["anexos"][0]["nome"] == "anexo-1.png" and "bytes" not in d["anexos"][0]
    assert d["mensagens_lista"][0]["papel"] == "sistema" and "aberto" in d["mensagens_lista"][0]["texto"]
    a = _audit(sup["esquema"], "sup_abrir")
    assert a and a[0]["alvo"] == d["codigo"] and "Saldo" not in a[0]["detalhe"]   # título nunca no audit
    d2 = _abrir(sup, titulo="Outro")
    assert d2["codigo"].endswith("-0002")


def test_whatsapp_sem_telefone_e_recusado_com_a_frase(sup):
    with pytest.raises(DadoInvalido) as e:
        chamados.criar(sup["beto"], {**PAYLOAD, "canais": {"whatsapp": True}})
    assert "telefone" in str(e.value)


def test_dono_ve_o_seu_e_o_alheio_e_none(sup):
    d = _abrir(sup)
    assert chamados.obter(d["id"], usuario_id=sup["ana"]["id"]) is not None
    assert chamados.obter(d["id"], usuario_id=sup["beto"]["id"]) is None
    assert chamados.obter(d["id"], suporte=True) is not None
    assert chamados.obter(99999, suporte=True) is None
    meus = chamados.listar_meus(sup["ana"]["id"])
    assert meus["kpis"]["abertos"] == 1 and len(meus["chamados"]) == 1
    assert "descricao" not in meus["chamados"][0]
    assert chamados.listar_meus(sup["beto"]["id"])["total"] == 0


def test_fluxo_completo_com_mensagens_de_sistema(sup):
    d = _abrir(sup)
    cid = d["id"]
    # suporte responde em aberto -> assume e vai a em_atendimento
    r = chamados.responder(cid, sup["beto"], "suporte", "Estou olhando.")
    assert r["eventos"] == ["em_atendimento", "resposta_suporte"]
    c = chamados.obter(cid, suporte=True)
    assert c["status"] == "em_atendimento" and c["atribuido_nome"] == "Beto Suporte"
    # pergunta ao usuário
    r = chamados.mudar_status(cid, sup["beto"], "suporte", "aguardando_usuario", texto="Qual filial?")
    assert r["para"] == "aguardando_usuario"
    # usuário responde -> volta sozinho ao suporte
    r = chamados.responder(cid, sup["ana"], "usuario", "Filial 1.")
    assert "de_volta_ao_suporte" in r["eventos"]
    assert chamados.obter(cid, suporte=True)["status"] == "em_atendimento"
    # nota interna não aparece para o dono
    chamados.responder(cid, sup["beto"], "suporte", "anotação", interna=True)
    assert any(m["interna"] for m in chamados.obter(cid, suporte=True)["mensagens_lista"])
    assert not any(m["interna"] for m in chamados.obter(cid, usuario_id=sup["ana"]["id"])["mensagens_lista"])
    with pytest.raises(DadoInvalido):
        chamados.responder(cid, sup["ana"], "usuario", "x", interna=True)
    # resolver exige texto; confirmar com avaliação encerra
    with pytest.raises(DadoInvalido):
        chamados.mudar_status(cid, sup["beto"], "suporte", "resolvido")
    chamados.mudar_status(cid, sup["beto"], "suporte", "resolvido", texto="Corrigido na v0.212.")
    r = chamados.mudar_status(cid, sup["ana"], "usuario", "fechado", avaliacao=5)
    c = chamados.obter(cid, suporte=True)
    assert c["status"] == "fechado" and c["avaliacao"] == 5
    # encerrado: responder é 409 (TransicaoInvalida), reabrir com texto volta a aberto
    with pytest.raises(TransicaoInvalida):
        chamados.responder(cid, sup["ana"], "usuario", "ainda quebrado")
    chamados.mudar_status(cid, sup["ana"], "usuario", "aberto", texto="Voltou a quebrar.")
    c = chamados.obter(cid, suporte=True)
    assert c["status"] == "aberto"
    sistemas = [m for m in c["mensagens_lista"] if m["papel"] == "sistema"]
    assert [m["status_para"] for m in sistemas if m["evento"] == "status"] == \
        ["aberto", "em_atendimento", "aguardando_usuario", "em_atendimento", "resolvido", "fechado", "aberto"]
    # 4 mudanças por mudar_status; as duas idas a em_atendimento vieram de responder()
    assert len(_audit(sup["esquema"], "sup_status")) == 4


def test_dono_nao_transita_chamado_alheio_nem_fecha_sem_resolver(sup):
    d = _abrir(sup)
    assert chamados.mudar_status(d["id"], sup["beto"], "usuario", "fechado") == {}
    with pytest.raises(DadoInvalido):
        chamados.mudar_status(d["id"], sup["ana"], "usuario", "resolvido", texto="x")
    chamados.mudar_status(d["id"], sup["ana"], "usuario", "fechado")     # desistiu: permitido
    assert chamados.obter(d["id"], suporte=True)["status"] == "fechado"


def test_assumir_e_atribuir(sup):
    d = _abrir(sup)
    r = chamados.assumir(d["id"], sup["chefe"], atribuido_id=sup["beto"]["id"])
    assert r["eventos"] == ["status_em_atendimento"]
    c = chamados.obter(d["id"], suporte=True)
    assert c["atribuido_id"] == sup["beto"]["id"] and c["status"] == "em_atendimento"
    with pytest.raises(DadoInvalido):
        chamados.assumir(d["id"], sup["chefe"], atribuido_id=99999)


def test_derivados_com_relogio_injetado(sup):
    d = _abrir(sup)
    c = chamados.obter(d["id"], suporte=True)
    assert c["esperando"] == "suporte" and c["primeira_resposta_h"] is None   # n/d, nunca zero
    assert c["sla_horas"] == 8 and c["sla_estourado"] is False
    depois = comum.agora() + timedelta(hours=9)
    c9 = chamados.obter(d["id"], suporte=True, hoje=depois)
    assert c9["horas_sem_resposta"] >= 9 and c9["sla_estourado"] is True
    chamados.responder(d["id"], sup["beto"], "suporte", "Vendo.")
    c2 = chamados.obter(d["id"], suporte=True, hoje=depois)
    assert c2["horas_sem_resposta"] is None and c2["sla_estourado"] is False
    assert c2["primeira_resposta_h"] is not None and c2["primeira_resposta_h"] < 1
    # novas: o dono ainda não leu a resposta
    c_dono = chamados.obter(d["id"], usuario_id=sup["ana"]["id"])
    assert c_dono["novas_usuario"] >= 1
    chamados.marcar_lido(d["id"], "usuario", sup["ana"]["id"])
    assert chamados.obter(d["id"], usuario_id=sup["ana"]["id"])["novas_usuario"] == 0
    assert chamados.marcar_lido(d["id"], "usuario", sup["beto"]["id"]) is False   # alheio


def test_canais_edicao_parcial(sup):
    d = _abrir(sup, canais={"email": False, "whatsapp": False})
    assert chamados.obter(d["id"], suporte=True)["avisar_email"] is False
    chamados.canais(d["id"], sup["ana"], {"email": True})
    c = chamados.obter(d["id"], suporte=True)
    assert c["avisar_email"] is True and c["avisar_whatsapp"] is False   # ausente = não mexe
    assert chamados.canais(d["id"], sup["beto"], {"email": False}) == {}   # alheio


def test_fila_ordena_por_prioridade_derivada(sup):
    baixa = _abrir(sup, gravidade="baixa", titulo="baixa")
    alta = _abrir(sup, gravidade="alta", titulo="alta")
    chamados.mudar_status(baixa["id"], sup["beto"], "suporte", "aguardando_usuario", texto="?")
    f = chamados.listar_fila({})
    assert [c["id"] for c in f["chamados"]][:2] == [alta["id"], baixa["id"]]
    assert f["mostrando"] == 2 and f["total"] == 2
    assert chamados.listar_fila({"busca": "alta"})["mostrando"] == 1
    assert chamados.listar_fila({"gravidade": "baixa"})["mostrando"] == 1


def test_indicadores_resumo_diagnostico_so_escalares(sup):
    d = _abrir(sup)
    chamados.responder(d["id"], sup["beto"], "suporte", "ok")
    ind = chamados.indicadores(30)
    assert ind["total"] == 1 and ind["semanas"][-1]["parcial"] is True and ind["semanas"][-1]["abertos"] == 1
    assert all(s["abertos"] == 0 for s in ind["semanas"][:-1])
    r = chamados.resumo()
    for k, v in r.items():
        assert not isinstance(v, (list, str)), k
        if isinstance(v, dict):
            assert all(not isinstance(x, (list, str)) for x in v.values())
    assert r["abertos"] == 1 and r["com_suporte"] == 1
    dg = chamados.diagnostico()
    assert dg["ok"] and dg["kpis"]["abertos"] == 1


def test_anexo_e_do_dono_ou_do_suporte(sup):
    d = _abrir(sup)
    aid = d["anexos"][0]["id"]
    a = chamados.anexo(aid, usuario_id=sup["ana"]["id"])
    assert a and a["bytes"].startswith(b"\x89PNG") and a["mime"] == "image/png"
    assert chamados.anexo(aid, usuario_id=sup["beto"]["id"]) is None
    assert chamados.anexo(aid, suporte=True) is not None


def test_atendentes_sao_quem_tem_a_tela_ou_admin(sup):
    nomes = {a["nome"] for a in chamados.atendentes()}
    assert nomes == {"Beto Suporte", "Chefe Admin"}
