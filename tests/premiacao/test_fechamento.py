# -*- coding: utf-8 -*-
"""O fechamento: depois de pago, o ciclo mostra a FOTO e não o cálculo.

O teste central aqui é o da IMUNIDADE: fechar, mexer na fonte, ler de novo e
exigir o MESMO valor. É o defeito que o fechamento existe para evitar, e ele
não tem sintoma nenhum — o número muda sozinho semanas depois, sem erro, sem
log, e quem confere acha que conferiu errado.

Os outros três:

- não se fecha ciclo EM CURSO sem dizer por quê (fechar no dia 10 congelaria
  cinco dias de ocorrência que ainda vão chegar, e o valor sairia menor);
- não se fecha duas vezes: reabrir é explícito e fica registrado;
- a reabertura NÃO apaga a foto — apagar deixaria uma janela em que ninguém
  consegue dizer quanto a folha levou.
"""
from __future__ import annotations

from datetime import date

import pytest

from api import pglocal
from api.premiacao import (config, fechamento, identidade, parametros, premio,
                           ranking)

CICLO = "2026-09"
DEPOIS = date(2026, 9, 20)      # o ciclo 2026-09 fecha em 15/09
DENTRO = date(2026, 9, 10)


@pytest.fixture
def base(esquema_pg, monkeypatch):
    for mod in (premio, parametros, config, identidade, fechamento):
        monkeypatch.setattr(mod, "ESQUEMA", esquema_pg)
    pglocal.executar(
        "INSERT INTO prm_motorista(cpf, nome, cadastro_codigo, tipo,"
        " tipo_origem, filial, filial_origem, admissao, ativo)"
        " VALUES('11111111111','MOTORISTA UM','111','RODOVIARIO','manual',"
        "'SBC','folha','2020-01',1)", esquema=esquema_pg)
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    return esquema_pg


def _nota(monkeypatch, valor):
    def montar(c=None, dir_snapshots=None):
        return {"ciclo": CICLO, "rotulo": "16/08 a 15/09 de 2026",
                "linhas": [{"motorista": "111", "nome": "MOTORISTA UM",
                            "tipo": "RODOVIARIO", "filial": "SBC",
                            "admissao": "2020-01", "gobrax": 80.0,
                            "conduta": valor, "gr": 60.0, "nota": valor,
                            "status": "BOM", "categoria": "OURO"}],
                "fontes": {}, "pendencias": {}}
    monkeypatch.setattr(ranking, "montar", montar)


def test_depois_de_fechado_a_FONTE_pode_mudar_que_o_valor_NAO_muda(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    fechado = fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    assert fechado["total"] == 900.0

    _nota(monkeypatch, 50.0)            # a Gobrax reprocessou o mês
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 3000}},
                         autor="gestor")   # e a régua mudou
    lido = fechamento.pagamento(CICLO)
    assert lido["fechado"] is True and lido["fonte"] == "fotografia do fechamento"
    assert lido["linhas"][0]["valor"] == 900.0
    assert lido["kpis"]["a_pagar"] == 900.0


def test_a_foto_guarda_POR_QUE_ele_recebeu_isto(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    linha = fechamento.ler(CICLO)["linhas"][0]
    assert (linha["gobrax"], linha["conduta"], linha["gr"]) == (80.0, 90.0, 60.0)
    assert linha["base"] == 1000.0 and linha["base_origem"] == "tabela"
    assert linha["pct"] == 90.0 and linha["categoria"] == "OURO"
    assert linha["motorista"] == "111"


def test_nao_se_fecha_ciclo_EM_CURSO_sem_dizer_por_que(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    with pytest.raises(fechamento.CicloEmCurso, match="só termina em 15/09"):
        fechamento.fechar(CICLO, autor="gestor", hoje=DENTRO)
    with pytest.raises(ValueError, match="exige o motivo"):
        fechamento.fechar(CICLO, autor="gestor", hoje=DENTRO, forcar=True)
    r = fechamento.fechar(CICLO, autor="gestor", hoje=DENTRO, forcar=True,
                          nota="feriado antecipou a folha")
    assert r["fechado"] is True
    assert fechamento.eventos(CICLO)[0]["motivo"] == "feriado antecipou a folha"


def test_o_ultimo_dia_do_ciclo_ainda_e_ciclo_em_curso(base, monkeypatch):
    """O ciclo vai até o dia 15 INTEIRO: fechar no próprio 15 perderia o dia."""
    _nota(monkeypatch, 90.0)
    with pytest.raises(fechamento.CicloEmCurso):
        fechamento.fechar(CICLO, autor="gestor", hoje=date(2026, 9, 15))
    assert fechamento.fechar(CICLO, autor="gestor", hoje=date(2026, 9, 16))


def test_nao_se_fecha_DUAS_vezes(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    with pytest.raises(fechamento.CicloFechado, match="já foi fechado"):
        fechamento.fechar(CICLO, autor="outro", hoje=DEPOIS)


def test_reabrir_EXIGE_motivo_e_deixa_registro(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    with pytest.raises(ValueError, match="motivo"):
        fechamento.reabrir(CICLO, autor="gestor", motivo="  ")
    fechamento.reabrir(CICLO, autor="rh", motivo="ocorrência lançada atrasada")
    evs = fechamento.eventos(CICLO)
    assert [e["acao"] for e in evs] == ["fechou", "reabriu"]
    assert evs[1]["autor"] == "rh" and "atrasada" in evs[1]["motivo"]


def test_reaberto_o_ciclo_VOLTA_a_calcular_e_a_foto_continua_la(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    fechamento.reabrir(CICLO, autor="rh", motivo="ocorrência atrasada")
    _nota(monkeypatch, 50.0)
    vivo = fechamento.pagamento(CICLO)
    assert vivo["fechado"] is False and vivo["fonte"] == "cálculo"
    assert vivo["linhas"][0]["valor"] == 500.0
    # a foto do que FOI pago continua inteira
    assert fechamento.ler(CICLO)["linhas"][0]["valor"] == 900.0


def test_fechar_de_novo_escreve_foto_NOVA_por_cima(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    fechamento.reabrir(CICLO, autor="rh", motivo="ocorrência atrasada")
    _nota(monkeypatch, 50.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    foto = fechamento.ler(CICLO)
    assert foto["linhas"][0]["valor"] == 500.0 and len(foto["linhas"]) == 1
    assert [e["acao"] for e in foto["eventos"]] == ["fechou", "reabriu", "fechou"]


def test_ciclo_nunca_fechado_calcula_e_diz_que_nao_ha_fechamento(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    r = fechamento.pagamento(CICLO)
    assert r["fechado"] is False and r["fechamento"] is None
    assert r["linhas"][0]["valor"] == 900.0


def test_fechar_recusa_ciclo_invalido_e_autor_vazio(base, monkeypatch):
    _nota(monkeypatch, 90.0)
    with pytest.raises(ValueError, match="Ciclo inválido"):
        fechamento.fechar("setembro", autor="gestor", hoje=DEPOIS)
    with pytest.raises(ValueError, match="quem está fechando"):
        fechamento.fechar(CICLO, autor="", hoje=DEPOIS)


def test_reabrir_um_ciclo_que_nunca_fechou_e_recusado(base):
    with pytest.raises(ValueError, match="nunca foi fechado"):
        fechamento.reabrir(CICLO, autor="rh", motivo="engano")


def test_o_CPF_nao_sai_na_foto(base, monkeypatch):
    import json
    _nota(monkeypatch, 90.0)
    fechamento.fechar(CICLO, autor="gestor", hoje=DEPOIS)
    assert "11111111111" not in json.dumps(fechamento.ler(CICLO))
