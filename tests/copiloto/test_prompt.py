"""O prompt do sistema — o que o Copiloto sabe sobre si mesmo.

Defeito que isto corrige: a lista de telas estava escrita à mão no prompt e
envelheceu. Perguntas sobre ANTT, Telemetria, Orçamento ou Extrato recebiam
"não existe" — o painel tinha a tela, o modelo não sabia.
"""
from __future__ import annotations

from api import copiloto


def test_a_lista_de_telas_vem_do_rbac_nao_do_texto():
    from api import auth
    telas = copiloto._telas_do_painel()
    # o RBAC é a fonte real do que existe no painel
    assert len(telas) >= len(auth.TELAS) - 5
    for rotulo in ("Piso Mínimo de Frete", "RNTRC dos Transportadores",
                   "Consumo e Estatísticas", "Orçamento", "Extrato Bancário"):
        assert rotulo in telas, rotulo


def test_o_prompt_montado_cita_as_telas_novas():
    p = copiloto.prompt_sistema()
    assert "Piso Mínimo de Frete" in p
    assert "Telemetria" in p or "Consumo e Estatísticas" in p


def test_o_prompt_manda_dizer_de_quando_e_o_dado():
    """O snapshot tem até 10 minutos e é um retrato: sem isso o modelo fala
    como se fosse tempo real."""
    p = copiloto.prompt_sistema().lower()
    assert "minutos" in p or "retrato" in p


def test_o_prompt_proibe_afirmar_tendencia_de_um_retrato_so():
    p = copiloto.prompt_sistema().lower()
    assert "tend" in p


def test_o_prompt_mantem_o_contrato_das_sugestoes():
    """As sugestões viram botões clicáveis: mudar o formato quebra o front."""
    assert "SUGESTOES:" in copiloto.prompt_sistema()


def test_o_prompt_mantem_a_regra_de_nao_inventar_numero():
    p = copiloto.prompt_sistema().lower()
    assert "invent" in p


def test_o_prompt_nao_cresceu_demais():
    """Prompt gigante come contexto e piora a resposta. Teto generoso, só para
    pegar crescimento acidental."""
    assert len(copiloto.prompt_sistema()) < 6000
