"""Regras de envio POR MODELO — e a que NÃO pode ser por modelo.

Um aviso de ocorrência para o motorista e uma cobrança não têm o mesmo horário,
o mesmo tom nem o mesmo risco. Até aqui os dois obedeciam a uma configuração
única; agora cada modelo ajusta o que precisa e herda o resto.

O QUE ESTE ARQUIVO PROTEGE, e o primeiro item vale por todos os outros:

1. **O sub-limite do modelo NUNCA CRIA COTA.** O teto continua sendo o do
   NÚMERO, valendo para tudo somado; o do modelo só APERTA. O WhatsApp não sabe
   o que é um modelo — vê uma linha telefônica falando com N desconhecidos por
   dia. Dez modelos com 60 cada não são 600 disparos permitidos: são 600
   motivos para perder a conta.
2. **`None` é HERDA, não zero.** Sem isso, mudar a regra geral deixaria de
   valer para os modelos que já existem, e cada um carregaria uma cópia
   congelada da configuração do dia em que nasceu.
3. **A janela PODE ampliar**, porque alerta noturno para motorista é legítimo —
   e é decisão consciente de quem edita, avisada na tela.
"""
from __future__ import annotations

import pytest

from api.whatsapp import config as cfg
from api.whatsapp import envio, modelos as md, registro
from tests.whatsapp.conftest import gravar_config, http_falso

GERAL = {"limite_dia": 60, "janela_inicio": "08:00", "janela_fim": "20:00",
         "assinatura": "Sulista Transportes", "intervalo_seg": 5}


# ------------------------------------------------- combinação das regras

def test_sem_ajuste_o_modelo_herda_tudo():
    r = md.regras_efetivas(GERAL, {})
    assert r["limite_modelo"] is None            # sem sub-limite
    assert r["limite_numero"] == 60              # o teto do número
    assert r["janela_inicio"] == "08:00"
    assert r["assinatura"] == "Sulista Transportes"
    assert r["intervalo_seg"] == 5


def test_sub_limite_MAIOR_que_o_geral_nao_afrouxa():
    """O ponto central: modelo não cria cota. Pôr 999 no modelo não libera
    999 — o teto do número continua mandando."""
    r = md.regras_efetivas(GERAL, {"limite_dia": 999})
    assert r["limite_modelo"] == 60
    assert r["limite_numero"] == 60


def test_sub_limite_menor_manda():
    r = md.regras_efetivas(GERAL, {"limite_dia": 20})
    assert r["limite_modelo"] == 20 and r["limite_numero"] == 60


def test_janela_do_modelo_pode_ser_MAIOR_que_a_geral():
    """Alerta de ocorrência às 3h é legítimo para um motorista. Quem edita
    decide; a tela avisa."""
    r = md.regras_efetivas(GERAL, {"janela_inicio": "00:00",
                                   "janela_fim": "23:59"})
    assert (r["janela_inicio"], r["janela_fim"]) == ("00:00", "23:59")


def test_assinatura_tem_tres_estados():
    assert md.regras_efetivas(GERAL, {})["assinatura"] == "Sulista Transportes"
    assert md.regras_efetivas(GERAL, {"assinatura": None})["assinatura"] == \
        "Sulista Transportes"                      # None herda
    assert md.regras_efetivas(GERAL, {"assinatura": ""})["assinatura"] == ""
    assert md.regras_efetivas(GERAL, {"assinatura": "Operação"})["assinatura"] \
        == "Operação"


# ----------------------------------------------------------- validação

def test_campo_em_branco_e_herda_e_nao_zero():
    d = md.validar({"nome": "x", "contexto": "livre", "corpo": "oi",
                    "limite_dia": "", "intervalo_seg": ""})
    assert d["limite_dia"] is None and d["intervalo_seg"] is None


def test_meia_janela_e_recusada():
    """Metade herdada e metade própria é o que ninguém consegue prever ao ler
    a tela."""
    with pytest.raises(md.ModeloInvalido, match="DUAS pontas"):
        md.validar({"nome": "x", "contexto": "livre", "corpo": "oi",
                    "janela_inicio": "08:00"})


def test_hora_fora_do_formato_e_recusada():
    for ruim in ("8h", "25:00", "08:70", "0800"):
        with pytest.raises(md.ModeloInvalido, match="HH:MM"):
            md.validar({"nome": "x", "contexto": "livre", "corpo": "oi",
                        "janela_inicio": ruim, "janela_fim": "20:00"})


def test_intervalo_fora_da_faixa_da_zapi_e_recusado():
    with pytest.raises(md.ModeloInvalido, match="entre 1 e 15"):
        md.validar({"nome": "x", "contexto": "livre", "corpo": "oi",
                    "intervalo_seg": 60})


def test_numero_preferido_inexistente_e_recusado():
    with pytest.raises(md.ModeloInvalido, match="não existe"):
        md.validar({"nome": "x", "contexto": "livre", "corpo": "oi",
                    "instancia": "terceiro"})


# ------------------------------------------------------------ ponta a ponta

@pytest.fixture(autouse=True)
def base(esquema_pg, monkeypatch):
    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(md, "ESQUEMA", esquema_pg)
    return esquema_pg


def _modelo(**troca):
    d = {"nome": "Aviso", "contexto": "livre", "corpo": "Bom dia."}
    d.update(troca)
    return md.gravar(d, usuario="ana")


def test_o_sub_limite_recusa_ANTES_do_teto_do_numero():
    """E a mensagem diz que foi o do modelo: o número ainda tem cota, então
    "limite atingido" sem qualificar mandaria esperar à toa."""
    gravar_config(limite_dia=60)
    m = _modelo(limite_dia=1)
    assert envio.enviar_modelo("47999998888", m["chave"], {},
                               http=http_falso())["ok"] is True
    r = envio.enviar_modelo("11988887777", m["chave"], {}, http=http_falso())
    assert r["ok"] is False
    assert "modelo" in r["erro"].lower() and "ainda tem cota" in r["erro"]


def test_o_teto_do_NUMERO_vale_mesmo_com_sub_limite_alto():
    """Modelo com o limite no máximo permitido não passa do teto do número. É a
    regra que impede dez modelos de virarem dez vezes o limite."""
    gravar_config(limite_dia=1)
    m = _modelo(limite_dia=md.LIMITE_MAX)
    envio.enviar_modelo("47999998888", m["chave"], {}, http=http_falso())
    r = envio.enviar_modelo("11988887777", m["chave"], {}, http=http_falso())
    assert r["ok"] is False
    assert "no número" in r["erro"]          # foi o teto do número, não o do modelo


def test_dois_modelos_dividem_a_cota_do_mesmo_numero():
    """A prova de que sub-limite não soma: dois modelos com 5 cada, num número
    com teto 2, param no segundo destinatário."""
    gravar_config(limite_dia=2)
    a, b = _modelo(nome="A", limite_dia=5), _modelo(nome="B", limite_dia=5)
    assert envio.enviar_modelo("47999998888", a["chave"], {}, http=http_falso())["ok"]
    assert envio.enviar_modelo("11988887777", b["chave"], {}, http=http_falso())["ok"]
    r = envio.enviar_modelo("11955554444", b["chave"], {}, http=http_falso())
    assert r["ok"] is False and "no número" in r["erro"]


def test_janela_propria_deixa_sair_fora_do_horario_geral(monkeypatch):
    """O caso que motivou o recurso: alerta para o motorista de madrugada."""
    from datetime import datetime
    gravar_config(janela_inicio="08:00", janela_fim="20:00")
    m = _modelo(janela_inicio="00:00", janela_fim="23:59")

    # finge que são 3 da manhã
    real = cfg.dentro_da_janela
    monkeypatch.setattr(cfg, "dentro_da_janela",
                        lambda agora=None, **kw: real(datetime(2026, 8, 28, 3, 0), **kw))

    assert envio.enviar_modelo("47999998888", m["chave"], {},
                               http=http_falso())["ok"] is True
    # e a mensagem avulsa, que segue a janela geral, continua barrada às 3h
    r = envio.enviar("11988887777", "oi", http=http_falso())
    assert r["ok"] is False and "Fora da janela" in r["erro"]


def test_assinatura_propria_do_modelo_vai_no_texto():
    gravar_config(assinatura="Sulista Transportes")
    m = _modelo(assinatura="Operação Sulista")
    http = http_falso()
    envio.enviar_modelo("47999998888", m["chave"], {}, http=http)
    import json
    texto = json.loads(http.chamadas[-1]["dados"])["message"]
    assert "Operação Sulista" in texto and "Sulista Transportes" not in texto


def test_modelo_sem_assinatura_manda_o_texto_puro():
    """Aviso interno para motorista não precisa da assinatura comercial."""
    gravar_config(assinatura="Sulista Transportes")
    m = _modelo(assinatura="")
    http = http_falso()
    envio.enviar_modelo("47999998888", m["chave"], {}, http=http)
    import json
    assert json.loads(http.chamadas[-1]["dados"])["message"] == "Bom dia."


def test_numero_preferido_do_modelo_e_usado_mas_quem_chama_tem_a_ultima_palavra():
    """Preferência que não desse para sobrepor viraria uma trava escondida."""
    from tests.whatsapp.conftest import CLIENT_TOKEN, INSTANCIA, TOKEN
    from api.whatsapp import cliente
    import pytest as _pytest
    _pytest.MonkeyPatch().setattr(cliente, "_cred", lambda nome: {
        "ZAPI_INSTANCIA": INSTANCIA, "ZAPI_TOKEN": TOKEN,
        "ZAPI_CLIENT_TOKEN": CLIENT_TOKEN,
        "ZAPI2_INSTANCIA": "77AA11BB22CC3344", "ZAPI2_TOKEN": "99DD88EE77FF6655",
    }.get(nome, ""))
    cliente.limpar_cache()
    try:
        gravar_config()
        m = _modelo(instancia="backup")
        envio.enviar_modelo("47999998888", m["chave"], {}, http=http_falso())
        assert registro.listar(1)[0]["instancia"] == "backup"

        envio.enviar_modelo("11988887777", m["chave"], {}, instancia="principal",
                            http=http_falso())
        assert registro.listar(1)[0]["instancia"] == "principal"
    finally:
        cliente.limpar_cache()


def test_o_resumo_diz_so_o_que_o_modelo_MUDA():
    """A lista não pode obrigar a abrir cada modelo para descobrir o que ele
    faz de diferente — e "segue a regra geral" não precisa de enfeite."""
    assert _modelo(nome="Padrao")["chave"]
    padrao = md.obter("padrao")
    assert padrao["regras_resumo"] == []

    _modelo(nome="Ajustado", limite_dia=20, assinatura="",
            janela_inicio="00:00", janela_fim="23:59")
    r = md.obter("ajustado")["regras_resumo"]
    assert "máx. 20/dia" in r and "00:00–23:59" in r and "sem assinatura" in r
