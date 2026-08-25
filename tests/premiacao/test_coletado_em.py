"""O carimbo de tempo do snapshot tem dois formatos vivos no disco.

`coleta.py` grava `isoformat(timespec="seconds")` -> '2026-08-19T14:41:36'.
Os arquivos antigos trazem '2026-07-27 16:48'. O leitor conhecia so o segundo,
entao no dia em que a coleta agendada reescreveu o snapshot de agosto a tela
inteira passou a responder 500 com ValueError — e o unico uso desse valor e
decidir se recoleta.
"""
from datetime import datetime

import pytest

from api.premiacao.servico import _coletado_ha_mais_de_1h, _parse_coletado

AGORA = datetime(2026, 8, 25, 12, 0, 0)


@pytest.mark.parametrize("valor,esperado", [
    ("2026-08-19T14:41:36", datetime(2026, 8, 19, 14, 41, 36)),   # escritor de hoje
    ("2026-07-27 16:48", datetime(2026, 7, 27, 16, 48)),          # arquivos antigos
    ("2026-07-27 16:48:09", datetime(2026, 7, 27, 16, 48, 9)),    # variante com segundos
])
def test_aceita_os_formatos_que_existem_no_disco(valor, esperado):
    assert _parse_coletado(valor) == esperado


def test_data_ilegivel_nao_derruba_a_tela():
    """Trocar dado velho por NENHUM dado e o pior negocio possivel: valor
    estranho e tratado como 'muito velho', que so faz recoletar."""
    assert _parse_coletado("ontem de tarde") is None
    assert _coletado_ha_mais_de_1h({"coletado_em": "ontem de tarde"}, AGORA) is True


def test_snapshot_sem_carimbo_pede_recoleta():
    assert _coletado_ha_mais_de_1h({}, AGORA) is True


def test_o_formato_do_escritor_e_lido_pelo_leitor():
    """Guarda de contrato: se alguem trocar o formato em coleta.py de novo,
    este teste falha aqui em vez de a tela cair em producao."""
    from api.premiacao import coleta
    fonte = __import__("inspect").getsource(coleta)
    assert 'isoformat(timespec="seconds")' in fonte
    assert _parse_coletado(AGORA.isoformat(timespec="seconds")) == AGORA
