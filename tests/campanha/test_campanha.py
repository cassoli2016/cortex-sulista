# -*- coding: utf-8 -*-
"""O programa de desempenho: régua do regulamento, dois grupos e o sorteio.

O que este arquivo guarda são as decisões que somem em silêncio:

- a régua da campanha é a do REGULAMENTO (50/30/20, quatro faixas) e não a
  operacional (40/40/20, cinco faixas) — e ela fica congelada na campanha,
  porque o trimestre em curso não pode mudar de régua no meio;
- FROTA e AGREGADO competem separados, cada um com o seu ranking;
- a chave que sai daqui é OPACA: o código do motorista agregado no ERP é o CPF;
- **categoria só para quem foi medido** — quem não tem telemetria fica com nota
  parcial e sem categoria, porque 100 por ausência de medição não é excelência;
- o sorteio sai da FOTO, com semente registrada, e refaz igual.
"""
from __future__ import annotations

import pytest

from api import campanha
from api.campanha import armazenamento as arm, base, nota as nota_mod, servico

CAMP = {"nome": "3º trimestre", "de_ciclo": "2026-10", "ate_ciclo": "2026-12",
        "premio": "Moto elétrica", "onde": "Matriz"}


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(campanha, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(arm, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(servico, "ESQUEMA", esquema_pg)
    return esquema_pg


# ─────────────────────────────────────────────────────────── a régua
def test_a_regua_do_regulamento_e_OUTRA_e_fica_congelada_na_campanha(esq):
    c = arm.criar(CAMP, autor="gestor")
    assert (c["peso_gobrax"], c["peso_conduta"], c["peso_gr"]) == (50, 30, 20)
    assert (c["cat_elite"], c["cat_ouro"], c["cat_prata"]) == (90, 85, 75)
    from api.premiacao import parametros
    # a operacional é outra, e é isso que faz as duas notas diferirem
    assert parametros.defaults()["peso_gobrax"] == 40


def test_pesos_que_nao_somam_100_sao_recusados(esq):
    with pytest.raises(ValueError, match="somam"):
        arm.criar({**CAMP, "peso_gobrax": 50, "peso_conduta": 30,
                   "peso_gr": 30}, autor="gestor")


def test_faixas_fora_de_ordem_sao_recusadas(esq):
    with pytest.raises(ValueError, match="decrescentes"):
        arm.criar({**CAMP, "cat_elite": 80, "cat_ouro": 85}, autor="gestor")


def test_ciclo_invalido_e_autor_vazio_sao_recusados(esq):
    with pytest.raises(ValueError, match="Ciclo inválido"):
        arm.criar({**CAMP, "de_ciclo": "outubro"}, autor="gestor")
    with pytest.raises(ValueError, match="quem está criando"):
        arm.criar(CAMP, autor="")


@pytest.mark.parametrize("nota, esperado", [
    (95, "ELITE"), (90, "ELITE"), (89.9, "OURO"), (85, "OURO"),
    (84.9, "PRATA"), (75, "PRATA"), (74.9, "BRONZE"), (0, "BRONZE"),
    (None, "PENDENTE"),
])
def test_as_QUATRO_faixas_do_regulamento(nota, esperado):
    c = {"cat_elite": 90, "cat_ouro": 85, "cat_prata": 75}
    assert nota_mod.categoria(nota, c) == esperado


def test_a_nota_usa_os_pesos_da_campanha_e_nao_os_da_casa():
    c = {"peso_gobrax": 50, "peso_conduta": 30, "peso_gr": 20}
    # 50% de 100 + 30% de 50 + 20% de 0 = 65
    assert nota_mod.composta(100, 50, 0, c)["nota"] == 65.0


# ──────────────────────────────────────────────────── a chave opaca
def test_a_chave_NAO_e_o_cpf_e_muda_entre_campanhas():
    """O código do motorista agregado no ERP é o CPF (11 dígitos em 279 de 279).
    Chave estável entre campanhas viraria um identificador de pessoa."""
    cpf = "11122233344"
    k1, k2 = base.chave(1, cpf), base.chave(2, cpf)
    assert cpf not in k1 and len(k1) == 12
    assert k1 != k2
    assert base.chave(1, cpf) == k1, "a mesma campanha dá sempre a mesma chave"
    assert base.chave(1, "111.222.333-44") == k1, "pontuação não muda a chave"


# ──────────────────────────────────────── elegibilidade e categoria
def _linha(**extra):
    d = {"nota": 92.0, "pilares": ["gobrax", "conduta", "gr"], "ativo": True,
         "venc_cnh": "2030-01-01", "categoria": "ELITE"}
    d.update(extra)
    return d


CAMPANHA = {"exige_gobrax": True, "cat_elite": 90, "cat_ouro": 85,
            "cat_prata": 75}


def test_sem_TELEMETRIA_nao_concorre_e_a_linha_diz_por_que():
    r = nota_mod.elegibilidade(_linha(pilares=["conduta", "gr"]), CAMPANHA,
                               encerramento=False)
    assert r["elegivel"] is False and r["faltas"] == ["sem_gobrax"]
    assert "metade do regulamento" in r["motivo"]
    assert r["faltas_de_medicao"] == ["sem_gobrax"]


def test_CNH_vencida_tira_do_sorteio_mas_NAO_e_falta_de_medicao():
    """Com CNH vencida há categoria (ele foi medido); o que some é a
    elegibilidade. São coisas diferentes e a linha diz cada uma."""
    r = nota_mod.elegibilidade(_linha(venc_cnh="2020-05-01"), CAMPANHA,
                               encerramento=False)
    assert r["elegivel"] is False and r["faltas"] == ["cnh"]
    assert r["faltas_de_medicao"] == []


def test_a_CATEGORIA_so_pesa_no_ciclo_de_ENCERRAMENTO():
    """No meio do trimestre a categoria ainda vai mudar — cravar 'não é Elite'
    em outubro seria decidir um resultado que ainda não aconteceu."""
    meio = nota_mod.elegibilidade(_linha(categoria="PRATA"), CAMPANHA,
                                  encerramento=False)
    fim = nota_mod.elegibilidade(_linha(categoria="PRATA"), CAMPANHA,
                                 encerramento=True)
    assert meio["elegivel"] is True
    assert fim["elegivel"] is False and fim["faltas"] == ["categoria"]


def test_quem_nao_tem_nota_nenhuma_nao_concorre():
    r = nota_mod.elegibilidade(_linha(nota=None, pilares=[]), CAMPANHA,
                               encerramento=False)
    assert r["faltas"] == ["sem_nota"] and "nenhum dos três" in r["motivo"]


def test_campanha_que_NAO_exige_telemetria_deixa_concorrer():
    r = nota_mod.elegibilidade(_linha(pilares=["conduta", "gr"]),
                               {**CAMPANHA, "exige_gobrax": False},
                               encerramento=False)
    assert r["elegivel"] is True


# ────────────────────────────────────────────────────── o sorteio
def _foto(esq, campanha_id, ciclo, grupo, linhas):
    arm.gravar_foto(campanha_id, ciclo, {grupo: {"linhas": linhas}}, esquema=esq)


def _p(chave, nome, elegivel=True, nota=95.0):
    return {"chave": chave, "nome": nome, "gobrax": 90.0, "conduta": 100.0,
            "gr": 90.0, "nota": nota, "categoria": "ELITE",
            "elegivel": elegivel, "motivo": "" if elegivel else "x"}


def test_o_sorteio_sai_da_FOTO_e_a_mesma_semente_da_o_mesmo_nome(esq):
    c = arm.criar(CAMP, autor="gestor")
    _foto(esq, c["id"], "2026-12", "AGREGADO",
          [_p(f"k{i:02d}", f"MOTORISTA {i}") for i in range(10)])
    r1 = servico.sortear(c["id"], "AGREGADO", autor="gestor", semente="abc")
    r2 = servico.sortear(c["id"], "AGREGADO", autor="gestor", semente="abc")
    assert r1["ganhador"] == r2["ganhador"] and r1["elegiveis"] == 10
    assert r1["suplente"] and r1["suplente"] != r1["ganhador"]
    # SEMENTE DIFERENTE SORTEIA DE NOVO. Com dez elegíveis, cair no mesmo nome
    # por acaso seria 1 em 10 — então o guard compara o CONJUNTO das duas
    # ordens, que é o que prova que a semente manda, sem depender de sorte.
    outra = servico.sortear(c["id"], "AGREGADO", autor="gestor", semente="xyz")
    assert (outra["ganhador"], outra["suplente"]) != (r1["ganhador"], r1["suplente"])


def test_so_ELEGIVEIS_entram_no_sorteio(esq):
    c = arm.criar(CAMP, autor="gestor")
    _foto(esq, c["id"], "2026-12", "FROTA",
          [_p("k1", "PODE"), _p("k2", "NAO PODE", elegivel=False)])
    r = servico.sortear(c["id"], "FROTA", autor="gestor", semente="s")
    assert r["elegiveis"] == 1 and r["ganhador"] == "PODE"
    assert r["suplente"] == "", "com um elegível não há suplente a inventar"


def test_a_gestao_pode_EXCLUIR_a_mao_e_isso_fica_registrado(esq):
    """Pendência financeira e documento que não está em sistema nenhum: o
    sistema exclui o que MEDE, e este é o resto."""
    c = arm.criar(CAMP, autor="gestor")
    _foto(esq, c["id"], "2026-12", "FROTA", [_p("k1", "UM"), _p("k2", "DOIS")])
    r = servico.sortear(c["id"], "FROTA", autor="gestor", semente="s",
                        excluidos={"k1": "pendência financeira"},
                        ata="conferido com o financeiro")
    assert r["ganhador"] == "DOIS" and r["excluidos_a_mao"] == 1
    reg = arm.sorteios(c["id"], esquema=esq)[0]
    assert reg["ata"] == "conferido com o financeiro"
    assert reg["semente"] == "s" and reg["elegiveis"] == 1


def test_sem_FOTO_do_encerramento_o_sorteio_e_RECUSADO(esq):
    """Sortear sobre o cálculo vivo faria o resultado depender do minuto em que
    se clicou."""
    c = arm.criar(CAMP, autor="gestor")
    with pytest.raises(ValueError, match="fotografado"):
        servico.sortear(c["id"], "FROTA", autor="gestor")


def test_sem_elegivel_o_sorteio_e_RECUSADO_e_nao_sorteia_o_inelegivel(esq):
    c = arm.criar(CAMP, autor="gestor")
    _foto(esq, c["id"], "2026-12", "FROTA", [_p("k1", "UM", elegivel=False)])
    with pytest.raises(ValueError, match="Nenhum participante elegível"):
        servico.sortear(c["id"], "FROTA", autor="gestor")


def test_sorteio_exige_autor_e_grupo_valido(esq):
    c = arm.criar(CAMP, autor="gestor")
    with pytest.raises(ValueError, match="conduzindo"):
        servico.sortear(c["id"], "FROTA", autor="")
    with pytest.raises(ValueError, match="Grupo inválido"):
        servico.sortear(c["id"], "TERCEIRO", autor="gestor")


def test_a_foto_e_REGRAVAVEL_e_nao_duplica(esq):
    c = arm.criar(CAMP, autor="gestor")
    _foto(esq, c["id"], "2026-11", "FROTA", [_p("k1", "UM")])
    _foto(esq, c["id"], "2026-11", "FROTA", [_p("k1", "UM", nota=80.0)])
    foto = arm.ler_foto(c["id"], "2026-11", "FROTA", esquema=esq)
    assert len(foto) == 1 and foto[0]["nota"] == 80.0
