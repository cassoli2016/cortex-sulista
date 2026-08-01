"""Alertas do extrato: divergência e extrato parado."""
from __future__ import annotations

from datetime import date

from api import alertas
from api.extrato.comparacao import comparar, farol


def _painel(contas):
    return {"kpis": {}, "contas": contas, "dias": [], "importacoes": []}


def test_divergencia_gera_alerta_critico():
    p = _painel([{"rotulo": "Itau 539349", "mapeada": True, "dias_divergentes": 2,
                  "farol": {"estado": "diverge", "dt": "2026-07-31", "delta": -1250.40,
                            "dias_sem_extrato": 1}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    nivel, titulo, texto = itens[0]
    assert nivel == "critico"
    assert "Itau 539349" in texto and "31/07/2026" in texto
    assert "1.250,40" in texto


def test_extrato_parado_gera_atencao():
    p = _painel([{"rotulo": "Bradesco 1239066", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "desatualizado", "dt": "2026-07-20", "delta": 0.0,
                            "dias_sem_extrato": 12}}])
    itens = alertas._alertas_extrato(p)
    assert itens and itens[0][0] == "atencao"
    assert "12 dias" in itens[0][2]


def test_conta_sem_vinculo_nao_alerta():
    p = _painel([{"rotulo": "CSV novo", "mapeada": False, "dias_divergentes": 0,
                  "farol": {"estado": "sem_mapa", "dt": None, "delta": None,
                            "dias_sem_extrato": None}}])
    assert alertas._alertas_extrato(p) == []


def test_tudo_ok_nao_alerta():
    p = _painel([{"rotulo": "Itau", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "ok", "dt": "2026-07-31", "delta": 0.0,
                            "dias_sem_extrato": 1}}])
    assert alertas._alertas_extrato(p) == []


def test_divergencia_do_mes_anterior_ainda_alerta_no_dia_1():
    """Regressão do FINDING 1 (fix round 1): no dia 1º de um mês, uma
    divergência do fechamento do mês ANTERIOR não pode desaparecer do digest.
    `_alertas_extrato` é pura e não sabe que dia é "hoje" - quem decidia (e
    apagava) essa divergência era a janela passada para `painel()` em
    `build_alertas()` (`hoje.replace(day=1)`, cobrida por `_janela_alerta`
    abaixo). Este teste documenta que, uma vez que o farol aponte para o
    último dia do mês anterior, o alerta crítico sai normalmente - a
    responsabilidade de INCLUIR essa data na consulta é da janela, não desta
    função."""
    p = _painel([{"rotulo": "Itau 539349", "mapeada": True, "dias_divergentes": 1,
                  "farol": {"estado": "diverge", "dt": "2026-07-31", "delta": -50.0,
                            "dias_sem_extrato": 1}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    nivel, _, texto = itens[0]
    assert nivel == "critico"
    assert "31/07/2026" in texto


def test_janela_alerta_atravessa_virada_de_mes():
    """`_janela_alerta` é o que de fato corrige o FINDING 1: 30 dias corridos
    terminando hoje, não `hoje.replace(day=1)`. No dia 1º de agosto, a janela
    tem de alcançar o fechamento de julho - "mês corrente" reduziria isso a
    um único dia (hoje) e apagaria a divergência mais recente e mais
    importante (a do fechamento do mês anterior)."""
    hoje = date(2026, 8, 1)
    dt_de, dt_ate = alertas._janela_alerta(hoje)
    assert dt_ate == "2026-08-01"
    # cobre pelo menos 30 dias corridos
    dias = (date.fromisoformat(dt_ate) - date.fromisoformat(dt_de)).days
    assert dias >= 30
    # e de fato atravessa a virada do mês - não é "desde o dia 1 do mês corrente"
    assert dt_de < "2026-08-01"
    assert dt_de.startswith("2026-07")


def test_janela_alerta_atravessa_virada_de_ano():
    """FINDING 2 (fix round 2, Minor): mesmo caso da virada de mês, um degrau
    acima - 1º de janeiro tem de alcançar o fechamento de dezembro do ano
    ANTERIOR, não só do mês anterior dentro do mesmo ano."""
    hoje = date(2026, 1, 1)
    dt_de, dt_ate = alertas._janela_alerta(hoje)
    assert dt_ate == "2026-01-01"
    assert dt_de.startswith("2025-12")
    assert dt_de < dt_ate


def test_janela_alerta_inclui_29_fevereiro_bissexto():
    """FINDING 2 (fix round 2, Minor): a janela é `timedelta(days=30)`, então
    tem de atravessar corretamente um 29/02 de ano bissexto (2024) sem
    estourar `ValueError` nem pular a data."""
    hoje = date(2024, 3, 1)
    dt_de, dt_ate = alertas._janela_alerta(hoje)
    assert dt_ate == "2024-03-01"
    assert dt_de == "2024-01-31"
    # a janela [dt_de, dt_ate] inclui o 29/02 do ano bissexto
    assert dt_de <= "2024-02-29" <= dt_ate


def test_alertas_extrato_origem_credito_sem_acima_abaixo():
    """FINDING 1 (fix round 2, Important): quando `delta_origem` é "credito"
    ou "debito", o texto não pode usar "acima"/"abaixo" - essa semântica de
    direção só existe para saldo (`d_debito` positivo empurra o saldo do
    extrato para BAIXO, o oposto do que "acima" diria)."""
    p = _painel([{"rotulo": "Bradesco X", "mapeada": True, "dias_divergentes": 1,
                  "farol": {"estado": "diverge", "dt": "2026-07-15", "delta": 300.0,
                            "delta_origem": "credito", "dias_sem_extrato": 1}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    texto = itens[0][2]
    assert "acima" not in texto and "abaixo" not in texto
    assert "300,00" in texto


def test_conta_mapeada_nunca_importada_gera_alerta_cego():
    """I2 (Important da revisao final): `dias_sem_extrato` e `None` para uma
    conta MAPEADA que nunca teve importacao nenhuma - situacao real, porque o
    fluxo CSV cria e mapeia a conta ANTES do primeiro upload (basta o
    primeiro import falhar - ex. mapa de colunas errado, 422 - para a conta
    ficar mapeada e cega para sempre), e tambem ocorre apos desfazer o unico
    upload. O bug antigo (`and f.get("dias_sem_extrato")`, truthiness sobre
    numero) tratava `None` como falso e gerava `[]` - a conta mais cega de
    todas saia SEM nenhum alerta."""
    p = _painel([{"rotulo": "Bradesco novo", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "desatualizado", "dt": None, "delta": None,
                            "delta_origem": None, "dias_sem_extrato": None,
                            "diverge_no_ultimo_dia": False}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    nivel, _, texto = itens[0]
    assert nivel == "atencao"
    assert "nunca" in texto and "Bradesco novo" in texto


def test_conta_desatualizada_com_zero_dias_nao_alerta():
    """I2: `dias_sem_extrato == 0` continua sem alerta - dizer "ha 0 dias sem
    extrato" seria absurdo. So chega nesse estado quando o ultimo upload e de
    HOJE mas nenhum dia deu para julgar (ex.: so dias SO_EXTRATO/SO_ERP)."""
    p = _painel([{"rotulo": "Itau zero", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "desatualizado", "dt": None, "delta": None,
                            "delta_origem": None, "dias_sem_extrato": 0,
                            "diverge_no_ultimo_dia": False}}])
    assert alertas._alertas_extrato(p) == []


def test_desatualizada_com_ultimo_dia_divergente_emite_os_dois_alertas():
    """I3 (Important da revisao final - mesma linha de I5): uma conta com
    extrato de 12 dias atras E divergencia real de R$ 50.000 no ultimo dia
    valido nao pode gerar so o "atencao: 12 dias sem extrato" - o alerta
    critico da divergencia tem que sair TAMBEM, mesmo com a cor do farol
    priorizando "desatualizado"."""
    dias = [{"dt": "2026-07-20", "estado": "DIVERGE", "d_saldo": -50000.0,
             "d_credito": None, "d_debito": None}]
    f = farol(dias, "2026-07-20", "2026-08-01")
    assert f["estado"] == "desatualizado"          # precedencia de cor intacta
    assert f["diverge_no_ultimo_dia"] is True

    p = _painel([{"rotulo": "Itau 539349", "mapeada": True, "dias_divergentes": 1, "farol": f}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 2
    niveis = {i[0] for i in itens}
    assert niveis == {"atencao", "critico"}
    critico = next(i for i in itens if i[0] == "critico")
    assert "50.000,00" in critico[2]
    atencao = next(i for i in itens if i[0] == "atencao")
    assert "12 dias" in atencao[2]


def test_alertas_extrato_cenario_csv_credito_sem_saldo_nunca_mostra_r0():
    """FINDING 1 (fix round 2, Important): reprodução exata do cenário do
    revisor. Conta CSV credita R$ 1.000 no dia, ERP registra R$ 500 -
    divergência real de R$ 500. `parser_csv` nunca traz saldo (`saldo=None`
    sempre) - o bug antigo (`delta = f.get("delta") or 0.0`, com `farol`
    preenchendo `delta` só a partir de `d_saldo`) fazia o digest mandar um
    alerta CRÍTICO dizendo "R$ 0,00", com direção arbitrária. Usa o pipeline
    real (`comparar` + `farol`), não um farol forjado à mão, para provar a
    correção ponta a ponta."""
    dias = comparar([{"dt": "2026-07-31", "valor": 1000.0, "tipo": "C"}], [],
                    [{"dt": "2026-07-31", "credito": 500.0, "debito": 0.0, "saldo": None}])
    f = farol(dias, "2026-07-31", "2026-08-01")
    assert f["estado"] == "diverge"
    p = _painel([{"rotulo": "Banco CSV Y", "mapeada": True, "dias_divergentes": 1, "farol": f}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    texto = itens[0][2]
    assert "500,00" in texto
    assert "R$ 0,00" not in texto
    assert "acima" not in texto and "abaixo" not in texto
