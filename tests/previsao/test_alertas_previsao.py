from __future__ import annotations

from api.alertas import _alertas_previsao


FONTES_OK = [{"nome": "razao contabil (AVA)", "ok": True, "driver": True},
             {"nome": "meta diaria / faturamento fiscal", "ok": True, "driver": True}]
FONTES_DEGRADADAS = [{"nome": "razao contabil (AVA)", "ok": True, "driver": True},
                     {"nome": "meta diaria / faturamento fiscal", "ok": False,
                      "driver": True}]


def _payload(prev, orc, avisos=(), fontes=None):
    return {"mes": "2026-08", "kpis": {"resultado_previsto": prev,
                                       "resultado_orcado": orc},
            "avisos": list(avisos), "fontes": list(fontes or [])}


def test_previsto_negativo_e_critico():
    itens = _alertas_previsao(_payload(-50000.0, 100000.0))
    assert itens[0][0] == "critico" and "negativo" in itens[0][1].lower()


def test_abaixo_do_orcado_e_atencao():
    itens = _alertas_previsao(_payload(80000.0, 100000.0))
    assert itens[0][0] == "atencao" and "orçado" in itens[0][1].lower()


def test_acima_do_orcado_sem_alerta_de_resultado():
    assert _alertas_previsao(_payload(120000.0, 100000.0)) == []


def test_aviso_de_divergencia_vira_info():
    itens = _alertas_previsao(_payload(120000.0, 100000.0,
                                       ["Combustivel diverge do cartao: os abastecimentos sao 45% "
                                        "do diesel bruto do razao"]))
    assert itens[0][0] == "info" and "combust" in itens[0][2].lower()


# --- degradacao de fonte: o digest/push e' o unico canal que chega ao celular
# do gestor, e era o unico sem nenhum sinal de que a previsao estava capenga.

def test_todas_as_fontes_ok_mantem_o_comportamento_de_hoje_regressao():
    assert _alertas_previsao(_payload(-50000.0, 100000.0, fontes=FONTES_OK)) == \
        _alertas_previsao(_payload(-50000.0, 100000.0))
    itens = _alertas_previsao(_payload(-50000.0, 100000.0, fontes=FONTES_OK))
    assert len(itens) == 1 and itens[0][0] == "critico"
    assert "degradada" not in itens[0][2].lower()


def test_fonte_fora_com_resultado_negativo_rebaixa_e_nomeia():
    itens = _alertas_previsao(_payload(-50000.0, 100000.0,
                                       fontes=FONTES_DEGRADADAS))
    niveis = [i[0] for i in itens]
    assert "critico" not in niveis                      # nao acorda ninguem
    degradacao = next(i for i in itens if "fonte degradada" in i[1].lower())
    assert degradacao[0] == "atencao"
    assert "meta diaria / faturamento fiscal" in degradacao[2]
    negativo = next(i for i in itens if "negativo" in i[1].lower())
    assert negativo[0] == "atencao"
    assert "meta diaria / faturamento fiscal" in negativo[2]


def test_fonte_fora_com_resultado_saudavel_emite_so_o_item_proprio():
    itens = _alertas_previsao(_payload(120000.0, 100000.0,
                                       fontes=FONTES_DEGRADADAS))
    assert len(itens) == 1
    assert itens[0][0] == "atencao" and "fonte degradada" in itens[0][1].lower()
    assert "meta diaria / faturamento fiscal" in itens[0][2]


def test_orcamento_ausente_nao_rebaixa_o_alerta_de_resultado():
    """O orcado nao entra em previsto nenhum (driver=False) — ano sem versao
    cadastrada e' estado normal e nao pode calar o alerta critico todo dia."""
    fontes = FONTES_OK + [{"nome": "orcamento (sem versao do ano)", "ok": False,
                           "driver": False}]
    itens = _alertas_previsao(_payload(-50000.0, None, fontes=fontes))
    assert len(itens) == 1 and itens[0][0] == "critico"
