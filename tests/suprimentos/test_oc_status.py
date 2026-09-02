"""A classificação de uma OC — UMA regra para tela, Visão Geral e Copiloto.

O que o teste antigo deixava passar: ele recebia booleanos prontos
(`sem_aprovacao`, `previsao_vencida`) e só conhecia quatro estados. Com isso,
`dtaprovador IS NULL` rotulava como "em aprovação" 965 OCs de 2023/24 com
aprovado=1 (cadastro), 33 rascunhos nunca encaminhados e a fila real de 60 —
tudo junto —, e "previsão vencida" era verdadeira no dia seguinte à emissão em
80% das OCs (a previsão padrão do ERP é o próprio dia da emissão).

Cada caso abaixo é um estado que o ERP realmente grava (medido em 01/09/2026).
"""
from __future__ import annotations

import itertools

import pytest

from api import suprimentos_oc as oc


def _r(**kw):
    base = {"aprovado": 1, "suspensa": False, "encaminhada": True, "tem_nf": False,
            "prazo_informado": False, "prazo_vencido": False, "dias_aberta": 3,
            "valor": 1000.0, "valor_pendente": 1000.0}
    base.update(kw)
    return base


@pytest.mark.parametrize("linha, esperado", [
    # reprovada vence tudo: o ERP também suspende a reprovada
    (_r(aprovado=3, suspensa=True, tem_nf=True), "reprovada"),
    # suspensa com dtaprovador gravado e sem usuário (649 casos): NÃO é aprovada
    (_r(aprovado=2, suspensa=True, encaminhada=False), "suspensa"),
    (_r(aprovado=1, suspensa=True, tem_nf=True), "suspensa"),
    # aprovado=2 sem encaminhamento: rascunho — quem age é o criador
    (_r(aprovado=2, encaminhada=False), "rascunho"),
    # aprovado=2 encaminhada: a fila real do aprovador
    (_r(aprovado=2, encaminhada=True), "aprovacao"),
    # nota vinculada: recebida, mesmo com dias ou prazo vencido
    (_r(tem_nf=True, dias_aberta=400, prazo_vencido=True), "recebida"),
    # legada 2023/24: aprovado=1 sem data de aprovação, com nota — recebida, não fila
    (_r(sem_data_aprovacao=True, tem_nf=True), "recebida"),
    # sem nota, prazo INFORMADO vencido: atrasada
    (_r(prazo_informado=True, prazo_vencido=True, dias_aberta=5), "atrasada"),
    # sem nota, sem prazo informado, mais de 30 dias da aprovação: atrasada
    (_r(dias_aberta=31), "atrasada"),
    # sem nota, dentro dos 30 dias, previsão igual à emissão (não é prazo): aguardando
    (_r(dias_aberta=30), "aguardando"),
    (_r(dias_aberta=0), "aguardando"),
])
def test_estado_da_oc(linha, esperado):
    assert oc.oc_status(linha) == esperado


def test_aprovado_nulo_cai_na_regra_da_data():
    """`coalesce(aprovado, …)` no SQL: sem o campo, dtaprovador decide."""
    assert oc.oc_status(_r(aprovado=None, tem_nf=True)) == "recebida"
    assert oc.oc_status(_r(aprovado=None, dias_aberta=2)) == "aguardando"


def test_todo_estado_possivel_esta_no_registro_canonico():
    """`STATUS_TODOS` é o que a rota valida e a tela conhece; um estado que a
    função devolva fora dele viraria 422 no filtro e badge sem rótulo."""
    vistos = set()
    for aprovado, suspensa, enc, nf, prazo_v, dias in itertools.product(
            (1, 2, 3, None), (True, False), (True, False), (True, False), (True, False), (0, 31)):
        vistos.add(oc.oc_status(_r(aprovado=aprovado, suspensa=suspensa, encaminhada=enc,
                                   tem_nf=nf, prazo_informado=prazo_v, prazo_vencido=prazo_v,
                                   dias_aberta=dias)))
    assert vistos == set(oc.STATUS_TODOS)


def test_parcial_so_com_nota_e_saldo_material():
    assert not oc.oc_parcial(_r(tem_nf=False, valor_pendente=500.0))
    assert not oc.oc_parcial(_r(tem_nf=True, valor=1000.0, valor_pendente=0.5))
    assert not oc.oc_parcial(_r(tem_nf=True, valor=100000.0, valor_pendente=900.0))   # < 1%
    assert oc.oc_parcial(_r(tem_nf=True, valor=1000.0, valor_pendente=200.0))


@pytest.mark.parametrize("dias, vencido, acao", [
    (2, False, "cobrar"), (30, False, "cobrar"), (31, False, "validar"),
    (5, True, "validar"), (90, False, "validar"), (91, False, "suspender"), (440, True, "suspender"),
])
def test_acao_graduada(dias, vencido, acao):
    """Chip igual para 2 e para 440 dias não prioriza nada."""
    assert oc.acao_sugerida(dias, vencido) == acao


def test_percentil_sem_percentile_cont():
    """O AVA é 9.3: o percentil sai em Python, por posição."""
    assert oc.percentil([], 0.5) is None
    assert oc.percentil([None, 4.0], 0.5) == 4.0
    v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert oc.percentil(v, 0.5) == 6
    assert oc.percentil(v, 0.9) == 9
    assert oc.percentil(v, 1.0) == 10
    assert oc.percentil(v, 0.0) == 1


def test_dias_parada_e_dez_vezes_o_p90_medido():
    """Mediana aprovação→nota: 1 dia em material, 3 em serviço; p90 5 e 11.
    Trinta dias é folga de sobra — e é o número que a tela, a Visão Geral e
    o alerta citam. Mudar aqui muda todos."""
    assert oc.DIAS_PARADA == 30
