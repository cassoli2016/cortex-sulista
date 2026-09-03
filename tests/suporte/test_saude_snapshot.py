"""O sensor da Saúde é função pura sobre o diagnóstico; o snapshot do
Copiloto só leva escalares. Cada limiar sabotado fica vermelho."""
from __future__ import annotations

from api import copiloto, servidor


def _d(**k):
    base = {"ok": True, "kpis": {"abertos": 3, "com_suporte": 2, "aguardando_usuario": 1, "sla_estourados": 0,
                                 "sem_atendente": 0}, "ultimo_aviso_em": "2026-09-02T10:00:00",
            "adiados_vencidos": 0, "github_ultimo": None}
    base.update(k)
    return base


def test_sem_tabela_e_erro_com_instrucao():
    r = servidor._servico_suporte_de({"ok": False, "sem_tabela": True})
    assert r["status"] == "erro" and "0037" in r["detalhe"]


def test_vazio_e_ok_pronto_para_uso():
    r = servidor._servico_suporte_de(_d(kpis={"abertos": 0, "com_suporte": 0, "aguardando_usuario": 0}))
    assert r["status"] == "ok" and "pronto" in r["detalhe"]


def test_normal_e_ok_com_os_numeros():
    r = servidor._servico_suporte_de(_d())
    assert r["status"] == "ok" and "3 aberto" in r["detalhe"] and "último aviso" in r["detalhe"]


def test_sla_estourado_e_sem_atendente_sao_alerta():
    r = servidor._servico_suporte_de(_d(kpis={"abertos": 3, "com_suporte": 2, "aguardando_usuario": 0, "sla_estourados": 1, "sem_atendente": 2}))
    assert r["status"] == "alerta" and "fora do SLA" in r["detalhe"] and "sem atendente" in r["detalhe"]


def test_ultima_chamada_ao_github_recusada_e_alerta_e_desligado_e_info_no_texto():
    r = servidor._servico_suporte_de(_d(github_ultimo={"resultado": "recusado", "detalhe": "GitHub respondeu 401: Bad credentials"}))
    assert r["status"] == "alerta" and "401" in r["detalhe"]
    r = servidor._servico_suporte_de(_d(github_ultimo={"resultado": "sem_canal", "detalhe": "sem token"}))
    assert r["status"] == "ok" and "desligado" in r["detalhe"]


def test_whatsapp_adiado_parado_e_alerta():
    r = servidor._servico_suporte_de(_d(adiados_vencidos=2))
    assert r["status"] == "alerta" and "4 h" in r["detalhe"]


def test_copiloto_declara_a_fonte_e_ela_e_escalar(sup):
    assert copiloto._FONTES_ROTULO["suporte"] == "Suporte — chamados"
    fontes = copiloto._fontes_do_snapshot()
    r = fontes["suporte"]()
    assert isinstance(r, dict) and "abertos" in r
    for k, v in r.items():
        assert not isinstance(v, (list, str)), k
