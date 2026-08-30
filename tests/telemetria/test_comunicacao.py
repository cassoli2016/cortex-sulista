"""Veículo sem comunicar com a Gobrax — e o denominador que torna isso legível.

A ARMADILHA QUE ESTES TESTES GUARDAM
====================================
"N veículos sem comunicar" é um número que engana com facilidade. Na
Comunicação Rastreadora, 664 de 836 apareciam sem sinal e 79% disso era
cadastro — terceiro que não integra, implemento que não emite. O alarme parecia
crise e era ruído, e ruído todo dia ensina a ignorar o alarme.

Aqui o universo é **quem a Gobrax conhece na competência**. Veículo sem
equipamento não entra na conta porque não tem como cumprir a regra.

E há uma distinção que a fonte impõe: `/api/v2/positions` devolve as **últimas
20 posições de cada veículo e ignora a janela pedida** (medido: 2 e 7 dias
devolveram os mesmos 1.960 pontos). Logo, quem não aparece na resposta está
calado há mais tempo do que dá para medir — e isso é PIOR que um atraso
medido, não igual. Dizer "há mais de 7 dias" a partir da ausência seria
afirmar o que a fonte não disse.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api.gobrax import armazenamento, comunicacao


@pytest.fixture
def cache(tmp_path):
    p = tmp_path / "telemetria.db"
    armazenamento.init_db(p)
    return p


def _povoar(p, placas_conhecidas, posicoes, comp="2026-08"):
    armazenamento.gravar("estatisticas", comp,
                         [{"placa": x, "km": 100.0} for x in placas_conhecidas], p)
    if posicoes:
        armazenamento.gravar(comunicacao.COLECAO, comp, posicoes, p)


AGORA = datetime(2026, 8, 30, 12, 0, 0)


def _pos(placa, horas):
    return {"placa": placa,
            "ultima": (AGORA - timedelta(hours=horas)).isoformat(timespec="seconds"),
            "posicoes": 20}


# ── o denominador ───────────────────────────────────────────────────────────


def test_o_universo_e_quem_a_GOBRAX_CONHECE_nao_a_frota(cache):
    """Veículo sem equipamento não pode cumprir a regra e não entra na conta."""
    _povoar(cache, ["AAA1A11", "BBB2B22"], [_pos("AAA1A11", 1), _pos("BBB2B22", 2)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert e["universo"] == 2 and e["em_dia"] == 2 and e["a_olhar"] == 0


def test_placa_com_posicao_mas_desconhecida_no_mes_e_DITA_nao_escondida(cache):
    """Não é falha nossa nem do fornecedor: é veículo que rodou sem gerar
    estatística no mês. Sumir com ela esconderia um descasamento real."""
    _povoar(cache, ["AAA1A11"], [_pos("AAA1A11", 1), _pos("ZZZ9Z99", 1)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert e["universo"] == 1
    assert e["fora_do_universo"] == ["ZZZ9Z99"]


# ── os três grupos ──────────────────────────────────────────────────────────


def test_dentro_do_limite_e_em_dia(cache):
    _povoar(cache, ["AAA1A11"], [_pos("AAA1A11", 23.9)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert e["em_dia"] == 1 and not e["atrasados"]


def test_acima_do_limite_vira_ATRASADO_com_o_ha_quanto(cache):
    _povoar(cache, ["AAA1A11"], [_pos("AAA1A11", 38.2)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert len(e["atrasados"]) == 1
    assert e["atrasados"][0]["horas"] == pytest.approx(38.2, abs=0.2)


def test_conhecida_e_SEM_POSICAO_e_um_grupo_a_parte(cache):
    """A API só mostra as últimas 20 posições: quem não aparece está calado há
    mais tempo do que dá para medir. Somar com os atrasados apagaria justamente
    o caso mais grave, e inventar um número de horas seria afirmar o que a
    fonte não disse."""
    _povoar(cache, ["AAA1A11", "SUMIU99"], [_pos("AAA1A11", 1)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert [s["placa"] for s in e["sem_posicao"]] == ["SUMIU99"]
    assert e["sem_posicao"][0]["horas"] is None
    assert not e["atrasados"]
    assert e["a_olhar"] == 1


def test_a_olhar_soma_os_DOIS_grupos_que_exigem_acao(cache):
    _povoar(cache, ["A1", "A2", "A3", "A4"],
            [_pos("A1", 1), _pos("A2", 30), _pos("A3", 50)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert e["em_dia"] == 1 and len(e["atrasados"]) == 2
    assert len(e["sem_posicao"]) == 1 and e["a_olhar"] == 3


def test_o_mais_calado_vem_primeiro(cache):
    """É a ordem em que alguém age."""
    _povoar(cache, ["A1", "A2", "A3"],
            [_pos("A1", 25), _pos("A2", 90), _pos("A3", 40)])
    e = comunicacao.estado(agora=AGORA, path=cache)
    assert [a["placa"] for a in e["atrasados"]] == ["A2", "A3", "A1"]


# ── o limite é parâmetro ────────────────────────────────────────────────────


def test_o_limite_e_configuravel(cache):
    """Veículo em manutenção programada não comunica e não é problema: a régua
    do que é "parado" muda com a operação."""
    _povoar(cache, ["A1"], [_pos("A1", 30)])
    assert len(comunicacao.estado(agora=AGORA, path=cache)["atrasados"]) == 1
    e = comunicacao.estado(agora=AGORA, limite_h=48, path=cache)
    assert not e["atrasados"] and e["limite_h"] == 48


# ── a coleta ────────────────────────────────────────────────────────────────


class ClienteFalso:
    def __init__(self, resp):
        self.resp = resp
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        self.chamadas.append((caminho, params))
        return self.resp


def test_a_coleta_guarda_a_ULTIMA_posicao_de_cada_veiculo():
    resp = {"data": [{"identification": "AAA1A11", "positions": [
        {"date": "2026-08-30 08:00:00"},
        {"date": "2026-08-30 11:30:00"},
        {"date": "2026-08-30 09:15:00"},
    ]}]}
    linhas = comunicacao.coletar(cliente=ClienteFalso(resp))
    assert linhas[0]["ultima"] == "2026-08-30T11:30:00"
    assert linhas[0]["posicoes"] == 3


def test_veiculo_sem_data_valida_nao_entra():
    """Posição sem data não diz quando ele falou — e entrar como se dissesse
    faria o veículo parecer em dia."""
    resp = {"data": [{"identification": "AAA1A11",
                      "positions": [{"date": None}, {"date": "xx"}]}]}
    assert comunicacao.coletar(cliente=ClienteFalso(resp)) == []
