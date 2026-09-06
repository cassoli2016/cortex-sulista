# -*- coding: utf-8 -*-
"""As janelas ruins do ERP, medidas em vez de lembradas.

O ERP é réplica de produção de TERCEIRO, compartilhada com um Power BI sem
`statement_timeout`. Ele derrubou a manhã em 03/09/2026 e de novo em
06/09/2026, e nas duas vezes o assunto chegou como impressão — "o sistema
estava lento hoje de manhã". Impressão não sustenta conversa com quem
administra o ERP; "24 janelas em 6 dias, 96% dos cancelamentos entre 04h e
09h, a pior de 56 minutos" sustenta.

O que estes testes protegem, em ordem de importância:

1. **Rajada é UM incidente.** Trinta linhas em quarenta segundos não são trinta
   janelas — e a contagem de janelas é justamente o número que alguém levaria
   para a conversa.
2. **O resgate conta como janela.** Desde que 31 consultas ganharam a rede, a
   degradação que antes virava timeout agora costuma virar leitura velha, e a
   linha de timeout DESAPARECE (a rede engole a exceção antes de a rota vê-la).
   Contar só cancelamento cegaria o cartão exatamente porque o portal melhorou.
3. **Janela velha não pinta vermelho.** Fato do passado não é problema de
   agora, e alarme que fica aceso treina a ignorar o cartão.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from api import erp_janelas, servidor

TO = ("2026-09-06 04:41:00,123 WARNING cortex.financeiro banco inacessivel: "
      "canceling statement due to statement timeout")
RG = ("2026-09-06 04:51:33,279 WARNING cortex.queries get_visao_geral falhou "
      "(QueryCanceled); servindo leitura de 259 s atras")


# AS LINHAS SÃO LITERAIS, COPIADAS DO LOG DE PRODUÇÃO — e isto é o guard do
# guard. A primeira versão montava a linha a partir de `erp_janelas.RESGATE`, e
# então sabotar a constante sabotava junto o que o teste fabricava: o dublê
# passava a falar a língua errada e o teste continuava verde. Um teste que não
# pode detectar a constante errada é exatamente o que ele deveria detectar.
_FMT = {
    "timeout": ("%s,000 WARNING cortex.financeiro banco inacessivel: "
                "canceling statement due to statement timeout"),
    "resgate": ("%s,000 WARNING cortex.queries get_visao_geral falhou "
                "(QueryCanceled); servindo leitura de 259 s atras"),
}


def _linha(quando, tipo="timeout"):
    return _FMT[tipo] % quando


def test_as_assinaturas_do_modulo_casam_com_o_LOG_REAL():
    """As duas linhas acima são cópias do `logs/api.log` desta máquina. Se
    alguém mudar o texto que o servidor escreve, ou a constante que o leitor
    procura, o cartão para de enxergar — e a falha dele é MUDA: um painel de
    monitoramento que diz "nenhuma janela" porque parou de reconhecer as
    linhas é pior que painel nenhum."""
    assert erp_janelas.TIMEOUT in _FMT["timeout"] % "2026-09-06 04:41:00"
    assert erp_janelas.RESGATE in _FMT["resgate"] % "2026-09-06 04:51:33"


# --------------------------------------------------------------------------
# a leitura de cada linha
# --------------------------------------------------------------------------
def test_le_o_instante_e_o_tipo_das_duas_assinaturas():
    evs = erp_janelas.eventos([TO, RG])
    assert [t for _, t in evs] == ["timeout", "resgate"]
    assert evs[0][0] == datetime(2026, 9, 6, 4, 41, 0)


def test_linha_que_nao_e_do_assunto_e_ignorada():
    assert erp_janelas.eventos([
        "2026-09-06 04:41:00,000 INFO cortex.push scheduler iniciado",
        "linha sem carimbo de tempo nenhum",
        "",
    ]) == []


def test_linha_com_a_assinatura_mas_SEM_data_nao_entra():
    """Sem instante ela não pertence a janela nenhuma — e entraria como
    `datetime` inventado, que é pior que não contar."""
    assert erp_janelas.eventos(["WARNING " + erp_janelas.TIMEOUT]) == []


# --------------------------------------------------------------------------
# rajada vira UMA janela
# --------------------------------------------------------------------------
def test_rajada_de_segundos_e_UM_incidente():
    evs = erp_janelas.eventos([_linha("2026-09-06 04:41:0%d" % i)
                               for i in range(9)])
    js = erp_janelas.agrupar(evs)
    assert len(js) == 1, "a rajada virou %d janelas" % len(js)
    assert js[0]["timeouts"] == 9


def test_silencio_longo_ABRE_janela_nova():
    evs = erp_janelas.eventos([_linha("2026-09-06 04:41:00"),
                               _linha("2026-09-06 05:30:00")])
    assert len(erp_janelas.agrupar(evs)) == 2


def test_silencio_CURTO_nao_parte_a_janela():
    """Nove minutos de quietude no meio de uma degradação de duas horas é
    normal; partir ali dobraria a contagem que alguém vai citar."""
    evs = erp_janelas.eventos([_linha("2026-09-06 04:41:00"),
                               _linha("2026-09-06 04:50:00")])
    assert len(erp_janelas.agrupar(evs)) == 1


def test_a_janela_conta_os_DOIS_efeitos_separados():
    evs = erp_janelas.eventos([_linha("2026-09-06 04:41:00", "timeout"),
                               _linha("2026-09-06 04:41:30", "resgate"),
                               _linha("2026-09-06 04:42:00", "resgate")])
    j = erp_janelas.agrupar(evs)[0]
    assert (j["timeouts"], j["resgates"]) == (1, 2)


def test_janela_SO_de_resgate_existe_e_conta():
    """Este é o caso que fica comum daqui para a frente. Quando a rede segura a
    consulta, a exceção não chega à rota e NÃO existe linha de timeout — o
    resgate é o único rastro do incidente."""
    evs = erp_janelas.eventos([_linha("2026-09-06 10:00:00", "resgate")])
    js = erp_janelas.agrupar(evs)
    assert len(js) == 1 and js[0]["timeouts"] == 0 and js[0]["resgates"] == 1


def test_janela_curta_nunca_dura_ZERO_minutos():
    """Zero leria como "não aconteceu" — e aconteceu."""
    evs = erp_janelas.eventos([_linha("2026-09-06 04:41:00"),
                               _linha("2026-09-06 04:41:20")])
    assert erp_janelas.agrupar(evs)[0]["minutos"] == 1


def test_a_duracao_arredonda_para_CIMA():
    """Os 8,5 min do meio são de propósito: o intervalo entre os dois eventos
    tem de caber DENTRO do `GAP_MIN`, senão eles viram duas janelas e a
    afirmação sobre duração não é sobre nada. Esta versão do teste nasceu com
    11,5 min e media a duração da primeira de duas janelas — verde ou vermelho
    por acidente."""
    evs = erp_janelas.eventos([_linha("2026-09-06 04:41:00"),
                               _linha("2026-09-06 04:49:30")])
    js = erp_janelas.agrupar(evs)
    assert len(js) == 1, "o intervalo do teste abriu janela nova"
    assert js[0]["minutos"] == 9


# --------------------------------------------------------------------------
# a medição sobre um arquivo
# --------------------------------------------------------------------------
def test_mede_um_log_inteiro(tmp_path):
    arq = tmp_path / "api.log"
    arq.write_text("\n".join([
        "2026-09-01 00:00:00,000 INFO cortex.push scheduler iniciado",
        _linha("2026-09-06 04:41:00"), _linha("2026-09-06 04:41:10"),
        _linha("2026-09-06 04:41:20", "resgate"),
        _linha("2026-09-06 08:00:00"),
        _linha("2026-09-05 14:00:00"),
    ]), encoding="utf-8")
    d = erp_janelas.medir(arq, agora=datetime(2026, 9, 6, 12, 0))
    assert d["legivel"] and d["desde"] == "2026-09-01 00:00:00"
    assert len(d["janelas"]) == 3
    assert d["timeouts"] == 4 and d["resgates"] == 1
    # 3 dos 4 cancelamentos entre 04h e 09h
    assert d["pct_manha"] == 75.0
    assert d["por_hora"] == {"04": 2, "08": 1, "14": 1}


def test_log_ausente_e_INFO_e_nao_erro(tmp_path):
    """Instalação sem log não é falha: é instalação sem log."""
    d = erp_janelas.medir(tmp_path / "nao-existe.log")
    assert d["legivel"] is False and d["motivo"]


def test_so_conta_como_RECENTE_o_que_esta_dentro_de_24h(tmp_path):
    arq = tmp_path / "api.log"
    arq.write_text(_linha("2026-09-01 04:41:00"), encoding="utf-8")
    d = erp_janelas.medir(arq, agora=datetime(2026, 9, 6, 12, 0))
    assert len(d["janelas"]) == 1 and d["janelas_24h"] == 0


# --------------------------------------------------------------------------
# o cartão
# --------------------------------------------------------------------------
def _cartao(**d):
    base = {"legivel": True, "janelas": [], "janelas_24h": 0,
            "desde": "2026-08-31 15:39:51", "timeouts": 0, "resgates": 0,
            "pct_manha": None, "ultima": None}
    return servidor._servico_janelas_erp({**base, **d})


UMA = {"inicio": "2026-09-06 04:41", "fim": "04:51", "minutos": 11,
       "timeouts": 12, "resgates": 1}


def test_janela_de_HOJE_pinta_alerta():
    assert _cartao(janelas=[UMA], janelas_24h=1, ultima=UMA)["status"] == "alerta"


def test_janela_ANTIGA_nao_pinta_alerta():
    """Fato do passado não é problema de agora. Alarme que fica aceso por algo
    de ontem treina a ignorar o cartão, que é o oposto do que ele existe para
    fazer."""
    assert _cartao(janelas=[UMA], janelas_24h=0, ultima=UMA)["status"] == "ok"


def test_sem_janela_nenhuma_o_cartao_diz_DESDE_QUANDO():
    """"Nenhuma janela" sobre duas horas de log e sobre seis dias são frases
    diferentes, e sem a data ninguém sabe qual está lendo."""
    assert "2026-08-31" in _cartao()["detalhe"]


def test_o_cartao_leva_a_CONCENTRACAO_por_hora():
    """É o achado que muda a conversa: "o ERP é lento" não leva a lugar nenhum;
    "96% entre 04h e 09h" aponta uma janela de carga com dono e horário."""
    d = _cartao(janelas=[UMA], ultima=UMA, pct_manha=96.0, timeouts=99)
    assert "96%" in d["detalhe"] and "04h" in d["detalhe"]


def test_janela_absorvida_pela_rede_NAO_diz_zero_cancelada():
    """O guard de uma frase que estava errada.

    A primeira versão escrevia sempre "N consulta(s) cancelada(s)" e produzia
    "0 consulta(s) cancelada(s)" na janela que a rede absorveu inteira. Esse
    zero não é ausência de nada — é o melhor desfecho possível —, e lido como
    número solto diz o contrário.
    """
    so_rede = {"inicio": "2026-09-06 10:00", "fim": "10:09", "minutos": 10,
               "timeouts": 0, "resgates": 4}
    t = _cartao(janelas=[so_rede], janelas_24h=1, ultima=so_rede,
                resgates=4)["detalhe"]
    assert "0 consulta" not in t, t
    assert "4 leitura(s) velha(s) servida(s)" in t


def test_log_ilegivel_e_INFO_e_nao_alarme():
    """Sem log não é "está tudo bem" nem "está tudo mal": é não sei."""
    c = servidor._servico_janelas_erp({"legivel": False, "motivo": "sem log"})
    assert c["status"] == "info"


def test_o_cartao_entra_na_lista_de_servicos_da_SAUDE(monkeypatch):
    """Cartão que ninguém monta é código morto com docstring bonito."""
    monkeypatch.setattr(servidor, "_janelas_erp",
                        lambda *a, **k: {"legivel": True, "janelas": [UMA],
                                         "janelas_24h": 1, "ultima": UMA,
                                         "desde": "2026-08-31 15:39",
                                         "timeouts": 12, "resgates": 1,
                                         "pct_manha": 96.0})
    nomes = [s.get("nome") for s in servidor._servicos()]
    assert "Janelas ruins do ERP" in nomes


def test_a_medicao_tem_TTL(monkeypatch):
    """A Saúde repinta de 5 em 5 s; varrer o log 60 vezes por minuto para um
    número que muda algumas vezes por dia é trabalho que não vira informação."""
    chamadas = []
    monkeypatch.setattr(servidor, "_janelas_cache", None)
    monkeypatch.setattr(erp_janelas, "medir",
                        lambda *a, **k: chamadas.append(1) or {"legivel": True})
    servidor._janelas_erp(forcar=True)
    servidor._janelas_erp()
    servidor._janelas_erp()
    assert len(chamadas) == 1, "leu o log %d vezes" % len(chamadas)
