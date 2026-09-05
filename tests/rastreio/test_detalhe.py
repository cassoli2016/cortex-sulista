# -*- coding: utf-8 -*-
"""O detalhe da carga na página pública.

DOIS DEFEITOS QUE SÓ O DADO REAL MOSTROU, e que viraram os guards centrais:

1. **O carimbo do ERP vem ingênuo e em horário local.** Tratá-lo como UTC soma
   três horas em UTC-3. O efeito não era um erro pequeno: com o teto de 180
   minutos, TODA posição nascia com 181 minutos de idade e a página nunca
   mostrava veículo ao vivo. Três cargas seguidas, todas com posição de menos
   de dois minutos, todas lidas como 181.

2. **O veículo pode não estar mais nesta carga.** O CT-e guarda a placa que
   levou a mercadoria, e o caminhão segue viagem: entrega, engata outra
   carreta, pega outro frete. Medido: CT-e 94446, Joinville -> Sorocaba,
   "faltam 711 km de 342". Prender o progresso entre 0 e 100 transformava isso
   num 0% plausível — e 0% é um número que quem espera a carga lê e acredita.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.rastreio import detalhe


# Joinville -> Porto Alegre, ~470 km em linha reta
COLETA = (-26.30, -48.85)
ENTREGA = (-30.03, -51.23)


def _linha(**kw) -> dict:
    base = {"placa": "AAA1A11", "dtemissao": "2026-09-01T08:00:00",
            "dtprevisaoentrega": None, "dtentrega": None,
            "dtagendamentoentrega": None, "dtiniciodescarga": None,
            "lat_coleta": COLETA[0], "lng_coleta": COLETA[1],
            "lat_entrega": ENTREGA[0], "lng_entrega": ENTREGA[1]}
    base.update(kw)
    return base


@pytest.fixture
def cenario(monkeypatch):
    def _montar(lat, lng, minutos_atras=0, km_rota=None, ingenuo=True):
        if ingenuo:
            quando = datetime.now() - timedelta(minutes=minutos_atras)
        else:
            quando = (datetime.now(timezone.utc)
                      - timedelta(minutes=minutos_atras))
        monkeypatch.setattr(detalhe, "_posicao",
                            lambda p: {"lat": lat, "lng": lng,
                                       "quando": quando})
        monkeypatch.setattr(detalhe, "_km_rota", lambda p: km_rota)
    return _montar


# --------------------------------------------------------------------------
# o fuso
# --------------------------------------------------------------------------
def test_carimbo_INGENUO_e_lido_como_hora_local():
    """O guard que impedia a página de mostrar veículo ao vivo. Com o carimbo
    lido como UTC, uma posição de agora nascia com 180 minutos."""
    agora_ingenuo = datetime.now()
    assert detalhe._idade_min(agora_ingenuo) == 0


def test_carimbo_COM_fuso_continua_certo():
    assert detalhe._idade_min(datetime.now(timezone.utc)) == 0


def test_a_idade_cresce_como_deve():
    assert detalhe._idade_min(datetime.now() - timedelta(minutes=45)) == 45


# --------------------------------------------------------------------------
# a posição velha
# --------------------------------------------------------------------------
def test_posicao_velha_NAO_se_apresenta_como_agora(cenario):
    """Rastreamento falha e veículo entra em área sem sinal. Um ponto de
    ontem exibido como atual é pior que ponto nenhum — quem lê decide nele."""
    cenario(-28.0, -50.0, minutos_atras=detalhe.IDADE_MAX_MIN + 10)
    a = detalhe._andamento(_linha())
    assert a["tem_posicao"] is False
    assert a["posicao_velha_min"] >= detalhe.IDADE_MAX_MIN
    assert "progresso_pct" not in a


def test_posicao_fresca_vira_progresso(cenario):
    cenario(-28.0, -50.0, minutos_atras=2)
    a = detalhe._andamento(_linha())
    assert a["tem_posicao"] is True
    assert 0 < a["progresso_pct"] < 100
    assert a["falta_km"] > 0


# --------------------------------------------------------------------------
# o veículo que já está noutra viagem
# --------------------------------------------------------------------------
def test_veiculo_FORA_DA_ROTA_e_declarado_e_nao_vira_zero(cenario):
    """O guard central. 0% é um número que quem espera a carga lê e acredita;
    'não localizamos nesta viagem' é a verdade."""
    # veículo no Nordeste, rota é Joinville -> Porto Alegre
    cenario(-8.05, -34.9, minutos_atras=1)
    a = detalhe._andamento(_linha())
    assert a.get("fora_da_rota") is True
    assert a.get("tem_posicao") is not True
    assert "progresso_pct" not in a, (
        "posição de outra viagem virou progresso — é o defeito de novo")


def test_desvio_normal_de_estrada_NAO_e_fora_da_rota(cenario):
    """A folga existe para o desvio real: a reta é sempre menor que a
    estrada, e um veículo pode se afastar um pouco sem estar noutra viagem."""
    # ligeiramente ao lado da reta, ainda entre origem e destino
    cenario(-28.5, -50.6, minutos_atras=1)
    a = detalhe._andamento(_linha())
    assert not a.get("fora_da_rota")
    assert a["tem_posicao"] is True


def test_chegou_quando_esta_no_raio(cenario):
    cenario(ENTREGA[0], ENTREGA[1], minutos_atras=1)
    a = detalhe._andamento(_linha())
    assert a["chegou"] is True
    assert a["progresso_pct"] == 100


# --------------------------------------------------------------------------
# o que o detalhe NÃO publica
# --------------------------------------------------------------------------
def test_a_posicao_publicada_e_ARREDONDADA_e_nao_a_exata(cenario):
    """A página mostra um mapa, e o mapa precisa de coordenada — mas da REGIÃO,
    nunca do ponto. A regra não é "não mandar lat/lng": é não mandar a lat/lng
    DE VERDADE.

    Uma casa decimal é ~11 km. Diz onde o veículo está sem servir para
    interceptá-lo numa rodovia, e o mapa desenha um círculo desse raio em vez
    de um alfinete — alfinete promete precisão que este número não tem.
    """
    cenario(-28.123456, -50.987654, minutos_atras=1)
    a = detalhe._andamento(_linha())
    area = a["area"]
    # cai na grade do círculo, e a grade NÃO é a coordenada de verdade
    passo = detalhe.AREA_PASSO_GRAU
    assert abs(area["lat"] / passo - round(area["lat"] / passo)) < 1e-6
    assert abs(area["lng"] / passo - round(area["lng"] / passo)) < 1e-6
    assert area["lat"] != -28.123456 and area["lng"] != -50.987654
    # e a coordenada CHEIA nao aparece em lugar nenhum do payload
    texto = repr(a)
    assert "28.123456" not in texto and "50.987654" not in texto


def test_o_circulo_e_do_TAMANHO_da_incerteza():
    """O invariante que substituiu "o raio não pode ser menor que 10 km".

    Aquele teste acendeu quando o raio caiu de 12 para 5 km — e acendeu certo,
    porque forçou a conversa. Mas o número fixo era a regra errada: o que não
    pode acontecer é o CÍRCULO PROMETER MAIS PRECISÃO QUE A COORDENADA TEM.
    Desenhar 2 km em cima de um valor arredondado a 11 km é uma mentira
    desenhada, e quem olha acredita no desenho.

    Então os dois andam juntos: o raio tem de cobrir o passo do
    arredondamento. Encolher um sem o outro acende aqui.
    """
    passo_km = detalhe.AREA_PASSO_GRAU * 111.0      # 1 grau ~ 111 km
    assert detalhe.AREA_RAIO_KM >= passo_km * 0.8, (
        "o círculo (%s km) é menor que a incerteza da coordenada (%.1f km)"
        % (detalhe.AREA_RAIO_KM, passo_km))


def test_a_coordenada_publicada_nunca_e_a_original():
    """A regra que não muda com o tamanho do círculo."""
    for lat, lng in ((-23.6794267, -46.3554193), (-22.375943, -47.547378)):
        assert detalhe._arredondar(lat) != lat
        assert detalhe._arredondar(lng) != lng


def test_sem_coordenada_de_entrega_nao_inventa_progresso(cenario):
    cenario(-28.0, -50.0, minutos_atras=1)
    a = detalhe._andamento(_linha(lat_entrega=None, lng_entrega=None))
    assert "progresso_pct" not in a
    assert "distancia_total_km" not in a


def test_sem_placa_nao_ha_andamento(monkeypatch):
    monkeypatch.setattr(detalhe, "_posicao", lambda p: None)
    monkeypatch.setattr(detalhe, "_km_rota", lambda p: None)
    a = detalhe._andamento(_linha(placa=None))
    assert a["tem_posicao"] is False


# --------------------------------------------------------------------------
# o segundo fator, de novo
# --------------------------------------------------------------------------
def test_o_detalhe_REPROVA_o_segundo_fator(monkeypatch):
    """Um link de detalhe encaminhado num grupo de WhatsApp não pode abrir
    nada sozinho: o identificador escolhe qual carga, nunca prova direito."""
    monkeypatch.setattr(detalhe.consulta, "buscar_cru",
                        lambda t, c: ([], None))
    r = detalhe.obter("51283", "0051", "qualquer-id")
    assert r["ok"] is True and r["carga"] is None


def test_sem_os_dois_campos_o_detalhe_recusa():
    assert detalhe.obter("51283", "", "id")["ok"] is False
    assert detalhe.obter("", "0051", "id")["ok"] is False
