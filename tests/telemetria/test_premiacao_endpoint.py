"""O endpoint da premiação tem de capturar as exceções do cliente NOVO.

Defeito real, visto em produção em 19/08/2026: as rotas importavam
GobraxIndisponivel de api.premiacao.gobrax (o cliente antigo, do login Kratos),
enquanto o serviço já levantava a de api.gobrax.cliente. Sendo classes
diferentes, o except não pegava e toda falha da Gobrax virava HTTP 500
"Erro ao atualizar a premiação" — sem dizer o que houve.
"""
from __future__ import annotations

import inspect
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "api" / "main.py"
S = MAIN.read_text(encoding="utf-8")


def test_nenhuma_rota_importa_o_cliente_antigo():
    assert "from api.premiacao.gobrax import" not in S


def test_as_duas_rotas_da_premiacao_importam_o_cliente_novo():
    for rota in ("def premiacao(", "async def premiacao_atualizar"):
        bloco = S.split(rota, 1)[1].split("@app.", 1)[0]
        assert "from api.gobrax.cliente import" in bloco, rota


def test_o_servico_e_o_endpoint_falam_da_mesma_excecao():
    """A garantia que o teste de string não dá: as classes são as mesmas."""
    from api.gobrax import cliente as novo
    from api.premiacao import servico
    fonte = inspect.getsource(servico)
    assert "gbx.GobraxIndisponivel" in fonte
    assert servico.gbx.GobraxIndisponivel is novo.GobraxIndisponivel


def test_gobrax_indisponivel_vira_503_e_nao_500():
    """503 diz 'a Gobrax não respondeu'; 500 diz 'o Córtex quebrou'. A tela
    mostra mensagens diferentes, e o usuário age diferente."""
    bloco = S.split("async def premiacao_atualizar", 1)[1].split("@app.", 1)[0]
    assert "GobraxIndisponivel" in bloco
    assert "status_code=503" in bloco


def test_serie_mensal_nao_usa_campos_da_regra_extinta():
    """Defeito visto em produção: serie() lia calc["kpis"]["media_frota"], que a
    regra nova não produz, e a tela mostrava "não foi possível carregar a série
    mensal" sem dizer por quê."""
    from api.premiacao import servico
    fonte = inspect.getsource(servico.serie)
    assert "media_frota" not in fonte
    assert 'calc["kpis"]' not in fonte
    assert '"premio_total": calc["premio_total"]' in fonte


def test_serie_marca_o_mes_calculado_pela_regra_antiga():
    from api.premiacao import servico
    assert '"regra"' in inspect.getsource(servico.serie)


def test_a_tela_nao_fala_mais_de_litros_na_descricao_da_regra():
    HTML = (Path(__file__).resolve().parent.parent.parent / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert "litros economizados × meta de consumo" not in HTML
    # a menção que PODE ficar é a que explica um mês antigo
    assert "regra antiga (litros economizados)" in HTML
