"""Os parâmetros que valem para um mês são os DAQUELE mês.

O DEFEITO QUE ISTO CONSERTA
==========================
A premiação tinha DOIS armazéns de parâmetro convivendo, e só um chegava ao
número da tela:

- `data/premiacao_params.json` — o antigo, valor único, sem histórico. Era o
  que `obter()` e `serie()` liam.
- `prem_versoes`/`prem_parametros` — o versionado por competência, que entrou
  em 0.146.0 junto com a tela de configuração.

Os dois guardam as MESMAS três chaves com os MESMOS padrões, então enquanto
ninguém editasse nada eles concordavam por coincidência. É o pior formato de
defeito que existe: a tela de configuração abria, salvava, dizia "salvo" — e
o prêmio exibido não mudava um centavo.

E no comparativo o efeito era outro, mais discreto: a série recalculava todo
mês passado com o parâmetro de HOJE. Subir o valor por km em setembro
reescreveria o prêmio de março, que já foi pago com outro valor.
"""
from __future__ import annotations

import pytest

from api.premiacao import config, servico


@pytest.fixture
def esq(esquema_pg):
    config.ESQUEMA = esquema_pg
    try:
        yield esquema_pg
    finally:
        config.ESQUEMA = None


def _salvar(comp, valor_km, esq):
    config.salvar(comp, {**config.defaults(), "valor_por_km": valor_km},
                  {k: {"peso": float(v["peso"]), "ativo": 1}
                   for k, v in config.EIXOS.items()},
                  autor="teste", nota="t", esquema=esq)


def test_o_mes_usa_a_versao_VIGENTE_nele(esq):
    _salvar("2026-01", 0.10, esq)
    _salvar("2026-07", 0.25, esq)
    assert servico.params_da_competencia("2026-03")["valor_por_km"] == 0.10
    assert servico.params_da_competencia("2026-07")["valor_por_km"] == 0.25
    assert servico.params_da_competencia("2026-09")["valor_por_km"] == 0.25


def test_mudar_HOJE_nao_reescreve_o_passado(esq):
    """A parte que decide dinheiro: o prêmio de março foi pago com o valor de
    março. Configurar setembro não pode mudá-lo."""
    _salvar("2026-01", 0.10, esq)
    antes = servico.params_da_competencia("2026-03")["valor_por_km"]
    _salvar("2026-09", 0.40, esq)
    assert servico.params_da_competencia("2026-03")["valor_por_km"] == antes


def test_sem_versao_nenhuma_valem_os_PADROES(esq):
    """Sem configuração a tela abre com o padrão marcado como tal — travar por
    falta de configuração esconderia justamente a configuração que falta."""
    assert (servico.params_da_competencia("2026-03")["valor_por_km"]
            == config.defaults()["valor_por_km"])


def test_banco_fora_CAI_NO_ARQUIVO_em_vez_de_derrubar_a_tela(monkeypatch):
    """Fallback: a tela ter número é melhor que a tela não abrir, e os padrões
    dos dois armazéns são os mesmos."""
    def explode(*a, **k):
        raise RuntimeError("banco local fora")
    monkeypatch.setattr(config, "ler", explode)
    p = servico.params_da_competencia("2026-03")
    assert p["valor_por_km"] > 0 and "nota_minima" in p
