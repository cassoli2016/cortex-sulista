"""O alarme do feed da ANTT: 45 dias sem autuação EMITIDA acende.

Em 16/09/2026 a Smartec estava havia dois meses sem trazer autuação da ANTT
(última emissão 11/07), com a coleta verde duas vezes por dia, e os autos de
Piso Mínimo chegavam por fora — advogado e quem opera. Nada acendia, porque a
coleta estava sã: o que parou foi o FEED, e só a data de emissão mede isso.

Três coisas que o guard segura, cada uma com assert próprio:
  · a fronteira (45 não acende, 46 acende), medida pela EMISSÃO e não pela
    infração — trocar as duas já fez a casa declarar a fonte morta à toa;
  · o alarme é da EMPRESA: com placa filtrada ele não se recorta;
  · no cartão da Saúde ele SOMA com o SNE vencendo, em vez de um calar o outro,
    e não passa na frente do vermelho de coleta falhando.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from api import servidor as sv
from api.smartec import armazenamento as arm
from api.smartec import cliente as scli
from api.smartec import leitura as lei

from .test_armazenamento import ANTT


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(lei, "ESQUEMA", esquema_pg)
    return esquema_pg


def _gravar(esq, dias_emissao: int, placa: str = "BAB9I77",
            ait: str = "FELVP00450622026", dias_infracao: int = 200) -> None:
    hoje = date.today()
    arm.gravar_antt([dict(ANTT, AIT=ait, PLACA=placa,
                          DATA_EMISSAO=_br(hoje - timedelta(days=dias_emissao)),
                          DATA_INFRACAO=_br(hoje - timedelta(days=dias_infracao)))],
                    esq)


def test_o_limite_e_45_dias():
    """A decisão de quem opera (16/09/2026). Mudar o número é mudar a regra —
    e o texto do cartão e o comentário da constante vão junto."""
    assert lei.ANTT_SEM_LOTE_DIAS == 45


def test_sem_autuacao_nenhuma_nao_acende(esq):
    f = lei.antt_feed(esq)
    assert f["ultima_emissao"] is None
    assert f["dias_sem_lote"] is None
    assert f["parada"] is False


def test_45_dias_ainda_nao_acende(esq):
    _gravar(esq, 45)
    f = lei.antt_feed(esq)
    assert f["dias_sem_lote"] == 45
    assert f["parada"] is False


def test_46_dias_acende(esq):
    _gravar(esq, 46)
    f = lei.antt_feed(esq)
    assert f["dias_sem_lote"] == 46
    assert f["limite_dias"] == 45
    assert f["parada"] is True


def test_quem_manda_e_a_EMISSAO_nao_a_infracao(esq):
    """Infração de 200 dias atrás emitida há 10: o feed está VIVO. Medir pela
    infração acenderia aqui — foi o erro de 10/09/2026."""
    _gravar(esq, 10, dias_infracao=200)
    f = lei.antt_feed(esq)
    assert f["dias_sem_lote"] == 10
    assert f["parada"] is False


def test_vale_a_emissao_MAIS_RECENTE_de_qualquer_autuacao(esq):
    _gravar(esq, 90, ait="FELTF00000012026")
    _gravar(esq, 5, ait="FELTF00000022026")
    assert lei.antt_feed(esq)["parada"] is False


def test_com_placa_filtrada_o_alarme_nao_se_recorta(esq):
    """Placa A com autuação velha, placa B com lote recente: o feed da empresa
    está vivo, e a placa A filtrada NÃO pode acender o alarme."""
    _gravar(esq, 90, placa="AAA1A11", ait="FELTF00000012026")
    _gravar(esq, 5, placa="BBB2B22", ait="FELTF00000022026")
    # a base: o recorte da placa existe de fato (senão o teste passa vazio)
    so_a = lei.kpis(esq, placa="AAA1A11")
    assert so_a["antt"]["n"] == 1
    assert so_a["antt"]["ultima"] == str(date.today() - timedelta(days=90))
    assert so_a["antt_feed"]["dias_sem_lote"] == 5
    assert so_a["antt_feed"]["parada"] is False


def test_o_estado_da_saude_leva_o_feed(esq):
    _gravar(esq, 60)
    assert lei.estado(esq)["antt_feed"]["parada"] is True


# ═══════════════════════════════════════════════ o cartão da Saúde
def _estado(feed: dict | None = None, acessos=None, falhando=None) -> dict:
    return {
        "ultima_coleta": datetime.now(timezone.utc) - timedelta(hours=2),
        "recursos": [{"recurso": "antt", "status": "ok", "itens": 209}],
        "falhando": falhando or [],
        "acessos": acessos or [],
        "antt_feed": feed or {"ultima_emissao": None, "dias_sem_lote": None,
                              "limite_dias": 45, "parada": False},
    }


PARADA = {"ultima_emissao": "2026-07-11", "dias_sem_lote": 67,
          "limite_dias": 45, "parada": True}


@pytest.fixture
def saude(monkeypatch):
    monkeypatch.setattr(scli, "configurado", lambda: True)

    def com(estado: dict) -> dict:
        monkeypatch.setattr(lei, "estado", lambda *a, **k: estado)
        return sv._servico_smartec()
    return com


def test_saude_feed_vivo_fica_verde(saude):
    assert saude(_estado())["status"] == "ok"


def test_saude_feed_parado_fica_amarelo_e_diz_a_data(saude):
    r = saude(_estado(PARADA))
    assert r["status"] == "alerta"
    assert "ANTT" in r["detalhe"]
    assert "67 dias" in r["detalhe"]
    assert "11/07/2026" in r["detalhe"]


def test_saude_SNE_vencendo_NAO_esconde_a_ANTT_parada(saude):
    sne = [{"servico": "sne", "cnpj": "76104397000123", "dias": 12}]
    r = saude(_estado(PARADA, acessos=sne))
    assert r["status"] == "alerta"
    assert "SNE vence em 12 dias" in r["detalhe"]
    assert "ANTT" in r["detalhe"]


def test_saude_coleta_da_ANTT_falhando_continua_vermelha_sem_falar_do_feed(saude):
    """Se a nossa coleta da ANTT falha, a idade do feed não prova nada."""
    r = saude(_estado(PARADA, falhando=[{"recurso": "antt"}]))
    assert r["status"] == "erro"
    assert "emitida há" not in r["detalhe"]


def test_saude_vermelho_de_OUTRO_recurso_NAO_esconde_a_ANTT_parada(saude):
    """O caso de 16/09/2026: `restricoes` falhando deixava o cartão vermelho,
    e o return seco escondia a ANTT parada havia 67 dias."""
    r = saude(_estado(PARADA, falhando=[{"recurso": "restricoes"}]))
    assert r["status"] == "erro"
    assert "restricoes falhou" in r["detalhe"]
    assert "ANTT emitida há 67 dias" in r["detalhe"]
