# -*- coding: utf-8 -*-
"""Os três pilares e a nota composta.

O que cada bloco segura:

- **Gobrax**: casa por nome, e nome ambíguo não casa com ninguém. Sem leitura
  do mês, o pilar fica AUSENTE com o motivo — nunca zero;
- **comportamento**: código sem de-para não vira desvio (a tela pede decisão),
  IGNORAR não conta, mérito NÃO sobe a nota do ciclo, e ciclo sem ocorrência é
  100 — que é medição, não ausência;
- **GR**: a conta do modelo com os contadores, o piso de viagens, e o
  `rodou_fora_horario`, que é BOOLEANO no fornecedor e derrubava a consulta
  inteira com `sum()`;
- **composta**: o peso do pilar ausente se redistribui, e sem nenhum pilar a
  nota é `None` — zero seria uma afirmação que ninguém fez.
"""
from __future__ import annotations

import json

import pytest

from api import pglocal
from api.premiacao import catalogo, parametros, pilares

CICLO = "2026-09"          # 16/08 a 15/09
P = parametros.defaults()


# ------------------------------------------------------------------ Gobrax
def _snapshot(tmp_path, mes, drivers, parcial=False):
    (tmp_path / f"premiacao-{mes}.json").write_text(json.dumps(
        {"month": mes, "parcial": parcial, "coletado_em": "2026-09-01T00:00:00",
         "drivers": drivers}), encoding="utf-8")
    return tmp_path


def test_a_gobrax_casa_por_nome_e_diz_de_que_mes_veio(tmp_path):
    cad = [{"cpf": "11111111111", "nome": "JOAO DA SILVA"},
           {"cpf": "22222222222", "nome": "MARIA SOUZA"}]
    _snapshot(tmp_path, "2026-08", [
        {"driverId": 7, "driverName": "3781 - João da Silva", "nota": 83.0, "km": 5000.0},
        {"driverId": 9, "driverName": "MARIA SOUZA", "nota": 91.0, "km": 4000.0}])
    r = pilares.gobrax(CICLO, cadastro=cad, dir_path=tmp_path)
    assert r["mes_gobrax"] == "2026-08"
    assert r["notas"]["11111111111"]["nota"] == 83.0
    assert r["notas"]["22222222222"]["driver_id"] == 9


def test_nome_AMBIGUO_nao_casa_com_ninguem(tmp_path):
    """Dois motoristas com o mesmo nome normalizado: premiar o errado é pior
    que não premiar — a linha vira pendência para alguém olhar."""
    cad = [{"cpf": "11111111111", "nome": "JOSE SANTOS"},
           {"cpf": "22222222222", "nome": "José Santos"}]
    _snapshot(tmp_path, "2026-08", [
        {"driverId": 7, "driverName": "JOSE SANTOS", "nota": 83.0, "km": 1.0}])
    r = pilares.gobrax(CICLO, cadastro=cad, dir_path=tmp_path)
    assert r["notas"] == {} and r["ambiguos"] == ["JOSE SANTOS"]


def test_motorista_da_gobrax_fora_do_cadastro_e_LISTADO_e_nao_some(tmp_path):
    """São 45 assim hoje (agregados rodando veículo com telemetria). Sumir
    calado esconderia que a conta olha um universo diferente."""
    _snapshot(tmp_path, "2026-08", [
        {"driverId": 7, "driverName": "ALGUEM DE FORA", "nota": 83.0, "km": 1.0}])
    r = pilares.gobrax(CICLO, cadastro=[], dir_path=tmp_path)
    assert r["sem_cadastro"] == ["ALGUEM DE FORA"] and r["notas"] == {}


def test_sem_leitura_do_mes_o_pilar_fica_AUSENTE_com_o_motivo(tmp_path):
    r = pilares.gobrax(CICLO, cadastro=[], dir_path=tmp_path)
    assert r["notas"] == {} and "sem leitura da Gobrax" in r["motivo"]


# ---------------------------------------------------------- comportamento
def _ocorrencias(monkeypatch, linhas):
    monkeypatch.setattr(pilares.erp, "query", lambda sql, p=None: linhas)


def _oc(cpf, codigo, data="2026-09-01", descricao="X"):
    return {"cpf": cpf, "codigo": codigo, "data": data, "descricao": descricao}


DEPARA = {1: "D01", 12: "D04", 19: "IGNORAR", 201: "M01"}


def test_o_desvio_tira_os_pontos_do_catalogo(monkeypatch):
    _ocorrencias(monkeypatch, [_oc("11111111111", 1), _oc("11111111111", 12)])
    r = pilares.comportamento(CICLO, depara=DEPARA)
    ficha = r["por_cpf"]["11111111111"]
    assert ficha["pontos"] == 12 + 8          # D01 + D04
    assert ficha["nota"] == 80.0
    assert [d["cod"] for d in ficha["desvios"]] == ["D01", "D04"]


def test_o_codigo_IGNORAR_nao_conta(monkeypatch):
    """É o código mais frequente do ERP (30% das ocorrências) e o modelo manda
    ignorar: reentrega pedida pelo cliente não é conduta do motorista."""
    _ocorrencias(monkeypatch, [_oc("11111111111", 19)])
    r = pilares.comportamento(CICLO, depara=DEPARA)
    assert r["por_cpf"] == {}


def test_codigo_SEM_de_para_nao_vira_desvio_e_pede_decisao(monkeypatch):
    """Tirar dinheiro de alguém por causa de um código que ninguém classificou
    é o defeito que esta guarda existe para impedir."""
    _ocorrencias(monkeypatch, [_oc("11111111111", 999, descricao="CODIGO NOVO"),
                               _oc("22222222222", 999)])
    r = pilares.comportamento(CICLO, depara=DEPARA)
    assert r["por_cpf"] == {}
    assert r["nao_mapeados"] == [{"codigo": 999, "descricao": "CODIGO NOVO", "vezes": 2}]


def test_ocorrencia_SEM_codigo_e_contada_a_parte(monkeypatch):
    """Existem no ERP (2 no ciclo medido). Não são "código a decidir": não há
    o que decidir, e elas não podem virar uma linha de código `None` na tela."""
    _ocorrencias(monkeypatch, [_oc("11111111111", None)])
    r = pilares.comportamento(CICLO, depara=DEPARA)
    assert r["sem_codigo"] == 1 and r["nao_mapeados"] == []


def test_o_MERITO_nao_sobe_a_nota_do_ciclo(monkeypatch):
    """Ele conta na reputação de seis meses. O ciclo mede o ciclo."""
    _ocorrencias(monkeypatch, [_oc("11111111111", 201), _oc("11111111111", 1)])
    ficha = pilares.comportamento(CICLO, depara=DEPARA)["por_cpf"]["11111111111"]
    assert ficha["nota"] == 88.0                     # só o D01 desconta
    assert [m["cod"] for m in ficha["meritos"]] == ["M01"]


def test_ciclo_sem_ocorrencia_e_100_e_NAO_e_ausencia():
    """Medido: em 6 meses só 125 motoristas tiveram alguma ocorrência. Tratar
    ciclo limpo como 'sem medição' deixaria o pilar fora da conta quase sempre."""
    assert pilares.nota_comportamento(None) == 100.0
    assert pilares.nota_comportamento({"nota": 74.0}) == 74.0


def test_a_nota_de_conduta_tem_piso_em_zero(monkeypatch):
    muitos = [_oc("11111111111", 1) for _ in range(20)]     # 240 pontos
    _ocorrencias(monkeypatch, muitos)
    assert pilares.comportamento(CICLO, depara=DEPARA)["por_cpf"]["11111111111"]["nota"] == 0.0


def test_o_ERP_fora_do_ar_nao_inventa_conduta(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(pilares.erp, "query", explode)
    r = pilares.comportamento(CICLO, depara=DEPARA)
    assert r["por_cpf"] == {} and "ERP" in r["motivo"]


# -------------------------------------------------------------------- GR
def _viagem(esquema, cpf, fim, **contadores):
    campos = {"eventos_velocidade": 0, "paradas_area_risco": 0, "desvios_rota": 0,
              "violacao_painel": 0, "violacao_antena": 0, "desengate": 0,
              "botao_panico": 0, "rodou_fora_horario": False}
    campos.update(contadores)
    # `placa` é NOT NULL na tabela real — a viagem do dublê tem de ser uma
    # viagem possível, senão o teste passa a exercitar um schema que não existe.
    # `placa`, `status` e a chave sao NOT NULL na tabela real, e `status='F'` e
    # a viagem FINALIZADA — a unica que carrega consolidado. O duble tem de ser
    # uma viagem possivel, senao o teste exercita um schema que nao existe.
    cols = ", ".join(["cod_solicitacao", "placa", "status", "cpf_motorista",
                      "real_fim"] + list(campos))
    vals = ", ".join(["%s"] * (5 + len(campos)))
    _viagem.seq = getattr(_viagem, "seq", 0) + 1
    pglocal.executar(
        f"INSERT INTO gr_viagem_fim({cols}) VALUES({vals})",
        tuple([str(_viagem.seq), "ABC1D23", "F", cpf, fim] + list(campos.values())),
        esquema=esquema)


@pytest.fixture
def gr_base(esquema_pg):
    pilares.ESQUEMA = esquema_pg
    yield esquema_pg
    pilares.ESQUEMA = None


def test_a_nota_de_GR_cai_com_o_risco_por_viagem(gr_base):
    # 10 viagens, 58 pontos de risco por viagem = a referência => queda cheia
    for _ in range(10):
        _viagem(gr_base, "00012345678901", "2026-09-01", eventos_velocidade=58)
    r = pilares.gr(CICLO, minimo_viagens=5, referencia=58, queda=40, piso=20)
    ficha = r["por_cpf"]["12345678901"]
    assert ficha["viagens"] == 10
    assert ficha["risco_por_viagem"] == 58.0
    assert ficha["nota"] == 60.0                      # 100 - 40


def test_o_CPF_do_GR_vem_com_zeros_a_esquerda(gr_base):
    """14 dígitos no fornecedor. Comparado cru, o cruzamento com a folha dava
    ZERO em 15.235 viagens."""
    for _ in range(5):
        _viagem(gr_base, "00012345678901", "2026-09-01")
    assert "12345678901" in pilares.gr(CICLO, minimo_viagens=5)["por_cpf"]


def test_abaixo_do_piso_de_viagens_o_ciclo_fica_SEM_nota(gr_base):
    """Uma viagem com um evento daria o mesmo índice de dez com dez."""
    _viagem(gr_base, "00012345678901", "2026-09-01", eventos_velocidade=99)
    ficha = pilares.gr(CICLO, minimo_viagens=5)["por_cpf"]["12345678901"]
    assert ficha["insuficiente"] is True and ficha["nota"] is None


def test_a_nota_de_GR_respeita_o_piso(gr_base):
    for _ in range(6):
        _viagem(gr_base, "00012345678901", "2026-09-01", eventos_velocidade=5000)
    assert pilares.gr(CICLO, minimo_viagens=5, referencia=58, piso=20)["por_cpf"]["12345678901"]["nota"] == 20.0


def test_DESENGATE_e_PANICO_aparecem_e_NAO_pesam(gr_base):
    """Desengate é operação de carreta (5,5 por viagem); pânico é pedido de
    socorro. Os dois entram na linha, nenhum na nota."""
    for _ in range(5):
        _viagem(gr_base, "00012345678901", "2026-09-01", desengate=10, botao_panico=2)
    ficha = pilares.gr(CICLO, minimo_viagens=5)["por_cpf"]["12345678901"]
    assert ficha["nota"] == 100.0
    assert ficha["informativos"]["desengate"] == 50 and ficha["panico"] == 10


def test_rodou_fora_do_horario_e_BOOLEANO_e_nao_derruba_a_consulta(gr_base):
    """`sum()` num booleano não existe no Postgres: a consulta inteira morria
    com UndefinedFunction, e o pilar de GR voltava vazio para todo mundo."""
    for _ in range(5):
        _viagem(gr_base, "00012345678901", "2026-09-01", rodou_fora_horario=True)
    ficha = pilares.gr(CICLO, minimo_viagens=5)["por_cpf"]["12345678901"]
    assert ficha["informativos"]["rodou_fora_horario"] == 5
    assert ficha["nota"] == 100.0                      # marcado, mas não pesa


def test_a_viagem_de_FORA_do_ciclo_nao_entra(gr_base):
    for _ in range(5):
        _viagem(gr_base, "00012345678901", "2026-08-15")   # véspera do ciclo
    assert pilares.gr(CICLO, minimo_viagens=5)["por_cpf"] == {}


def test_os_pesos_do_catalogo_sao_os_calibrados_no_dado_real():
    """Se alguém devolver o peso 10 ao desengate ou 6 à velocidade, a nota de
    GR volta a pôr todo mundo no piso — foi medido."""
    pesos = catalogo.pesos_gr_padrao()
    assert "desengate" not in pesos and "rodou_fora_horario" not in pesos
    assert pesos["eventos_velocidade"] == 1
    assert pesos["violacao_painel"] == 10 and pesos["paradas_area_risco"] == 3


# -------------------------------------------------------------- composta
def test_a_composta_e_a_media_ponderada_dos_tres():
    r = pilares.composta(80, 100, 60, P)
    assert r["nota"] == 84.0 and r["renormalizado"] is False


def test_o_peso_do_pilar_AUSENTE_se_redistribui():
    """Metade dos motoristas não tem nota da Gobrax. Zerar o pilar seria punir
    alguém pela cobertura da telemetria."""
    r = pilares.composta(None, 100, 60, P)
    assert r["nota"] == 86.7                      # (40×100 + 20×60) / 60
    assert r["ausentes"] == ["gobrax"] and r["renormalizado"] is True


def test_sem_nenhum_pilar_a_nota_e_NONE_e_nao_zero():
    r = pilares.composta(None, None, None, P)
    assert r["nota"] is None and r["pilares"] == []


def test_a_composta_diz_de_que_pilares_saiu():
    """92 de dois pilares não é a mesma coisa que 92 de três."""
    assert pilares.composta(90, 90, None, P)["pilares"] == ["gobrax", "conduta"]


@pytest.mark.parametrize("nota, esperado", [
    (95, "EXCELENTE"), (92, "EXCELENTE"), (85, "BOM"), (80, "ATENCAO"),
    (70, "ALERTA"), (50, "CRITICO"), (None, "PENDENTE")])
def test_o_status_segue_as_faixas(nota, esperado):
    assert pilares.status(nota, P) == esperado


@pytest.mark.parametrize("rep, esperado", [
    (110, "ELITE"), (100, "DIAMANTE"), (90, "OURO"), (75, "PRATA"),
    (50, "BRONZE"), (None, "PENDENTE")])
def test_a_categoria_segue_as_faixas(rep, esperado):
    assert pilares.categoria(rep, P) == esperado
