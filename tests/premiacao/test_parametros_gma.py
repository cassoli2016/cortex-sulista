# -*- coding: utf-8 -*-
"""Os parâmetros da régua nova: vigência, validação e convivência com a antiga.

O teste que mais importa aqui é o da CONVIVÊNCIA: a premiação antiga ainda
paga, e a régua nova compartilha a mesma linha do tempo de versões
(`prem_versoes`). Gravar a régua nova não pode apagar os parâmetros nem os
eixos da antiga — `config.salvar` apaga os dois antes de regravá-los, e foi por
isso que esta camada escreve a versão por conta própria.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.premiacao import catalogo, config, parametros


@pytest.fixture
def base(esquema_pg):
    parametros.ESQUEMA = esquema_pg
    config.ESQUEMA = esquema_pg
    yield esquema_pg
    parametros.ESQUEMA = None
    config.ESQUEMA = None


def test_sem_versao_valem_os_PADROES(base):
    v = parametros.ler("2026-09", "RODOVIARIO")
    assert v["versao"] is None
    assert v["valores"]["peso_gobrax"] == 40 and v["valores"]["peso_gr"] == 20


def test_a_referencia_do_GR_e_a_CALIBRADA_no_dado_real(base):
    """58 é o p90 medido do risco por viagem. O 10 do modelo original valia
    para outra escala e punha todo mundo no piso."""
    assert parametros.defaults()["gr_referencia"] == 58


def test_cada_GRUPO_tem_a_sua_regua(base):
    parametros.salvar("2026-09", "MANOBRA",
                      {"peso_gobrax": 0, "peso_conduta": 70, "peso_gr": 30},
                      autor="gestor")
    manobra = parametros.ler("2026-09", "MANOBRA")["valores"]
    rodo = parametros.ler("2026-09", "RODOVIARIO")["valores"]
    assert manobra["peso_gobrax"] == 0 and manobra["peso_conduta"] == 70
    assert rodo["peso_gobrax"] == 40, "o outro grupo não pode ter mudado junto"


def test_a_regua_do_ciclo_e_a_VIGENTE_e_o_passado_nao_muda(base):
    parametros.salvar("2026-01", "RODOVIARIO",
                      {"peso_gobrax": 50, "peso_conduta": 30, "peso_gr": 20},
                      autor="gestor")
    parametros.salvar("2026-09", "RODOVIARIO",
                      {"peso_gobrax": 20, "peso_conduta": 60, "peso_gr": 20},
                      autor="gestor")
    assert parametros.ler("2026-05", "RODOVIARIO")["valores"]["peso_gobrax"] == 50
    assert parametros.ler("2026-09", "RODOVIARIO")["valores"]["peso_gobrax"] == 20
    assert parametros.ler("2026-12", "RODOVIARIO")["valores"]["peso_gobrax"] == 20


def test_os_tres_pesos_TEM_de_somar_100(base):
    """Pesos que somam 90 dão uma nota que não é comparável com a de quem somou
    100 — sem erro nenhum, e com o ranking inteiro deslocado."""
    with pytest.raises(ValueError, match="somam 90"):
        parametros.salvar("2026-09", "RODOVIARIO",
                          {"peso_gobrax": 40, "peso_conduta": 30, "peso_gr": 20},
                          autor="gestor")


def test_parametro_desconhecido_e_valor_negativo_sao_RECUSADOS(base):
    with pytest.raises(ValueError, match="desconhecido"):
        parametros.salvar("2026-09", "RODOVIARIO", {"peso_do_chapeu": 1}, autor="x")
    with pytest.raises(ValueError, match="negativo"):
        parametros.salvar("2026-09", "RODOVIARIO", {"gr_piso": -1}, autor="x")
    with pytest.raises(ValueError, match="Informe quem"):
        parametros.salvar("2026-09", "RODOVIARIO", {"gr_piso": 10}, autor="")
    with pytest.raises(ValueError, match="Grupo inválido"):
        parametros.salvar("2026-09", "PILOTO", {"gr_piso": 10}, autor="x")


def test_salvar_a_regua_NOVA_nao_apaga_a_configuracao_que_AINDA_PAGA(base):
    """A premiação antiga (valor por km × nota) continua no ar. `config.salvar`
    apaga parâmetros e eixos da versão antes de regravá-los; se a régua nova
    passasse por ela, a antiga perderia a configuração e pararia de pagar."""
    config.salvar("2026-09", {"valor_por_km": 0.12, "nota_minima": 75},
                  {e: {"peso": 10, "ativo": 1} for e in config.EIXOS},
                  autor="gestor", nota="regua antiga", esquema=base)
    antes = config.ler("2026-09", base)

    parametros.salvar("2026-09", "RODOVIARIO",
                      {"peso_gobrax": 40, "peso_conduta": 40, "peso_gr": 20},
                      autor="gestor")

    depois = config.ler("2026-09", base)
    assert depois["params"]["valor_por_km"] == antes["params"]["valor_por_km"]
    assert depois["eixos"] == antes["eixos"], "a régua antiga perdeu os eixos"
    assert parametros.ler("2026-09", "RODOVIARIO")["valores"]["peso_conduta"] == 40


def test_salvar_duas_vezes_no_mesmo_ciclo_ATUALIZA_a_mesma_versao(base):
    parametros.salvar("2026-09", "RODOVIARIO",
                      {"peso_gobrax": 40, "peso_conduta": 40, "peso_gr": 20}, autor="a")
    parametros.salvar("2026-09", "RODOVIARIO",
                      {"peso_gobrax": 30, "peso_conduta": 50, "peso_gr": 20}, autor="b")
    versoes = pglocal.query("SELECT id FROM prem_versoes WHERE vigente_de = %s",
                            ("2026-09",), esquema=base)
    assert len(versoes) == 1
    assert parametros.ler("2026-09", "RODOVIARIO")["valores"]["peso_gobrax"] == 30


def test_o_de_para_do_modelo_ja_vem_na_migration(base):
    """Sem ele nenhuma ocorrência viraria desvio no primeiro ciclo, e a régua
    nasceria dizendo que está todo mundo impecável."""
    mapa = parametros.depara()
    assert mapa[19] == "IGNORAR"        # o código mais frequente do ERP
    assert mapa[65] == "D12"            # multa média
    assert mapa[201] == "M01"
    assert len(mapa) >= 45


def test_o_peso_do_GR_sai_do_catalogo_e_a_versao_pode_trocar(base):
    padrao = parametros.pesos_gr("2026-09")
    assert padrao == catalogo.pesos_gr_padrao()
    versao = parametros._versao_para("2026-09", "gestor", "")
    pglocal.executar(
        "INSERT INTO prm_gr_peso(versao_id, contador, peso) VALUES(%s,%s,%s)",
        (versao, "eventos_velocidade", 2), esquema=base)
    assert parametros.pesos_gr("2026-09")["eventos_velocidade"] == 2


def test_contador_que_o_fornecedor_NAO_manda_nao_tem_peso(base):
    """`desengate` e `rodou_fora_horario` ficaram fora da conta por medição —
    um é operação de carreta, o outro vem sempre vazio. Peso neles daria a
    impressão de que pesam."""
    pesos = parametros.pesos_gr("2026-09")
    assert "desengate" not in pesos and "rodou_fora_horario" not in pesos
    informativos = {c["campo"] for c in catalogo.informativos()}
    assert {"desengate", "rodou_fora_horario", "botao_panico"} <= informativos


def test_o_banco_fora_do_ar_cai_nos_PADROES_em_vez_de_derrubar(base, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(parametros.config, "versao_de", explode)
    v = parametros.ler("2026-09", "RODOVIARIO")
    assert v["valores"] == parametros.defaults() and v["versao"] is None


def test_o_catalogo_publico_traz_o_que_a_tela_desenha(base):
    cat = parametros.catalogo_publico()
    assert {"parametros", "grupos", "desvios", "meritos", "contadores_gr",
            "so_informativos"} <= set(cat)
    assert len(cat["desvios"]) == 14 and len(cat["meritos"]) == 10
    assert all("explica" in p for p in cat["parametros"])
