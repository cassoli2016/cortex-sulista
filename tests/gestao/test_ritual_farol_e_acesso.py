# -*- coding: utf-8 -*-
"""O farol do Ritual e a separação de acesso do cadastro.

DUAS COISAS QUE ESTE ARQUIVO GUARDA, E POR QUÊ
==============================================

**1. Quem preenche o ritual não configura a régua pela qual é cobrado.**
A unidade de RBAC desta casa é a TELA, e sub-aba HERDA o acesso da tela que a
contém — então enquanto o cadastro era uma aba de `gesrit`, qualquer gerente
que recebesse a tela poderia criar, editar e EXCLUIR indicador. Não era uma
falha de tela: as rotas aceitavam.

**2. A cor sai da meta, não da opinião.**
Medido em 08/09/2026: os 12 indicadores estavam com meta NULA, então o desvio
nunca aparecia e o verde/amarelo/vermelho era escolha livre. Número objetivo
com veredito subjetivo é o pior dos dois mundos, porque é a cor que a reunião
discute e que a regra de fechamento usa.
"""
from __future__ import annotations

import pytest

from api import auth
from api.gestao import ritual


# ─────────────────────────────────────────────────── o acesso, no middleware

def _tela_da_rota(rota: str):
    """O que o middleware exigiria desta rota. A ordem de `ROTA_TELAS` importa:
    ele casa por PREFIXO e para no primeiro."""
    return next((t for r, t in auth.ROTA_TELAS if rota.startswith(r)), None)


@pytest.mark.parametrize("rota", ["/api/ritual/indicador",
                                  "/api/ritual/gerencia",
                                  "/api/ritual/config"])
def test_o_cadastro_do_ritual_NAO_e_alcancavel_por_quem_so_preenche(rota):
    """`gesrit` (preencher) não pode abrir o cadastro.

    Este é o teste que existe por pedido explícito de quem opera: gestor não
    tem acesso à aba de indicadores. Sem ele, um `/api/ritual` genérico
    reposto por engano devolveria o acesso sem ninguém notar — a regressão é
    invisível até alguém apagar um indicador.
    """
    exige = _tela_da_rota(rota)
    assert exige is not None, f"{rota} nao esta mapeada — o middleware e fail-closed, mas a rota some do mapa"
    assert "gesrit" not in exige, (
        f"{rota} aceita quem so preenche o ritual: exige {sorted(exige)}")
    assert exige == frozenset({"gesind"}), sorted(exige)


@pytest.mark.parametrize("rota", ["/api/ritual/painel", "/api/ritual/apontar",
                                  "/api/ritual/cadastro", "/api/ritual/fechar"])
def test_o_que_o_GERENTE_usa_continua_na_tela_dele(rota):
    """O espelho, e ele não é decoração.

    Mover a rota de cadastro inteira para a tela nova teria quebrado o modal de
    preenchimento, que lê `/api/ritual/cadastro` para listar as ações — ou
    seja, teria tirado do gerente justamente o produto da reunião. Guard que só
    sabe proibir aprova a tela quebrada.
    """
    assert _tela_da_rota(rota) == frozenset({"gesrit"})


def test_a_ordem_do_mapa_impede_a_generica_de_engolir_as_especificas():
    """`/api/ritual` casaria com tudo se viesse antes.

    O middleware para no primeiro prefixo que casa. Uma reordenação inocente
    devolveria o cadastro ao gerente sem mudar uma linha de permissão.
    """
    rotas = [r for r, _ in auth.ROTA_TELAS]
    generica = rotas.index("/api/ritual")
    for especifica in ("/api/ritual/indicador", "/api/ritual/gerencia",
                       "/api/ritual/config"):
        assert rotas.index(especifica) < generica, (
            f"{especifica} vem DEPOIS de /api/ritual e nunca sera alcancada")


def test_a_tela_nova_existe_no_registro():
    """Lista escrita à mão se confere contra o código."""
    assert "gesind" in auth.TELAS
    assert auth.TELAS["gesind"][1] == "Gestão"


# ───────────────────────────────────────────────────────────────── o farol

@pytest.mark.parametrize("desvio,esperado", [
    (12.0, "verde"), (0.0, "verde"),      # na meta ou melhor
    (-0.1, "amarelo"), (-10.0, "amarelo"),  # dentro da tolerância
    (-10.1, "vermelho"), (-80.0, "vermelho"),
])
def test_a_cor_sai_do_desvio_contra_a_meta(desvio, esperado):
    assert ritual.farol(desvio, 0, -10) == esperado


def test_sem_desvio_NAO_e_verde():
    """Linha sem régua não é linha sem problema.

    Pintar de verde faria o painel ficar mais bonito exatamente onde ninguém
    mediu nada — e são 12 de 12 indicadores hoje.
    """
    assert ritual.farol(None, 0, -10) is None


def test_a_faixa_e_POR_INDICADOR_e_nao_da_casa():
    """Receita 8% abaixo da meta é grave; retorno vazio 8% acima pode ser uma
    semana ruim. Uma faixa única alarmaria demais num e de menos no outro."""
    assert ritual.farol(-8.0, 0, -5) == "vermelho"    # tolerância curta
    assert ritual.farol(-8.0, 0, -20) == "amarelo"    # tolerância longa


def test_o_desvio_e_orientado_pelo_que_e_BOM():
    """Positivo é sempre melhor que a meta, nos dois sentidos de indicador.

    Sem isso o painel poria lado a lado um -8% ótimo (multa abaixo da meta) e
    um -8% péssimo (receita abaixo da meta).
    """
    # receita 90 contra meta 100: 10% PIOR
    assert ritual._desvio(100, 90, "maior_melhor") == pytest.approx(-10)
    # multa 90 contra meta 100: 10% MELHOR
    assert ritual._desvio(100, 90, "menor_melhor") == pytest.approx(10)


# ─────────────────────────────────── a discordância é ato, não estado normal

def test_faixa_invertida_e_recusada():
    """Vermelho acima do verde não deixa faixa para o amarelo — o painel teria
    duas cores e ninguém entenderia por quê.

    A gerência vem de verdade do banco: a validação dela acontece ANTES da das
    faixas, então um id inventado faria o teste passar pela recusa errada — e
    um teste que passa pelo motivo errado não guarda nada. (Foi o que
    aconteceu na primeira versão: `gerencia_id: 0` era recusado por "escolha a
    gerência", nunca chegando à regra das faixas.)

    A exceção estoura antes de qualquer INSERT, então nada é gravado.
    """
    gers = ritual.gerencias()
    if not gers:
        pytest.skip("nenhuma gerência cadastrada nesta instalação")
    with pytest.raises(ritual.DadoInvalido, match="MENOR"):
        ritual.salvar_indicador({"nome": "prova de faixa invertida",
                                 "gerencia_id": gers[0]["id"],
                                 "tol_verde": "-20", "tol_vermelho": "0"})


def test_o_catalogo_de_fontes_continua_executavel():
    """Chave de fonte errada NÃO levanta erro: `ler_fonte` captura e devolve
    `None`, e o indicador fica vazio para sempre. Por isso o guard EXECUTA em
    vez de conferir a grafia — foi assim que três fontes nasceram mudas."""
    mudas = [c for c in ritual.FONTES if ritual.ler_fonte(c) is None]
    assert not mudas, f"fontes que nao devolvem numero: {mudas}"
