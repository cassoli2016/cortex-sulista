# -*- coding: utf-8 -*-
"""O prêmio no app: o que ele vê, o que ele NÃO vê, e de quem é o número.

As decisões que este arquivo guarda são as que somem em silêncio quando
alguém "simplifica" a tela:

- o escopo vem da SESSÃO, e não existe parâmetro de motorista que a rota possa
  preencher com o que veio do navegador;
- ciclo ABERTO sai marcado como PRÉVIA, e ciclo fechado sai com o valor PAGO
  (a fotografia) — número de premiação errado na mão do premiado é discussão
  de salário;
- a MEDIDA disciplinar sugerida não trafega: ele vê as ocorrências (fatos
  dele), nunca o nível proposto, porque quem aplica é o RH;
- a única comparação é a POSIÇÃO, sem nome nem nota de colega;
- o CPF não sai daqui;
- quem está fora da régua (agregado) recebe `fora_do_escopo`, para a tela não
  desenhar um cartão vazio.
"""
from __future__ import annotations

import inspect
import json

import pytest

from api import queries
from api.motorista import premiacao as mprem
from api.premiacao import fechamento, ranking

CICLO = "2026-09"
EU = {"motorista_codigo": "111", "motorista_id": 7, "nome": "MOTORISTA UM",
      "telefone": "", "sessao_id": 1, "mestre": False}


@pytest.fixture(autouse=True)
def cache_limpo():
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


def _linha(codigo, nome, nota, **extra):
    base = {
        "motorista": codigo, "nome": nome, "tipo": "RODOVIARIO",
        "tipo_origem": "manual", "filial": "SBC", "admissao": "2020-01",
        "gobrax": 80.0, "km": 5000.0, "conduta": 88.0,
        "desvios": [{"cod": "D07", "nome": "Excesso de velocidade",
                     "grav": "MODERADA", "pts": 7, "data": "2026-09-02"}],
        "meritos": 1, "gr": 60.0, "gr_viagens": 12, "gr_risco": 30.0,
        "gr_insuficiente": False, "gr_contadores": {}, "gr_informativos": {},
        "nota": nota, "pilares": ["gobrax", "conduta", "gr"], "ausentes": [],
        "status": "BOM", "reputacao": 96.0, "categoria": "OURO",
        "rep_conduta": 96.0, "ciclos_limpos": 5, "desvios_6": 1, "meritos_6": 1,
        "medida": {"nivel": "N4", "medida": "Suspensão (RH)",
                   "porque": "4 desvios em 6 ciclos", "sugerida": True},
    }
    base.update(extra)
    return base


@pytest.fixture
def fontes(monkeypatch):
    """O ciclo montado e o pagamento sob controle do teste."""
    estado = {
        "ciclo": {
            "ciclo": CICLO, "rotulo": "16/08 a 15/09 de 2026",
            "mes_gobrax": "2026-08",
            "linhas": [_linha("111", "MOTORISTA UM", 78.4),
                       _linha("222", "COLEGA MELHOR", 95.0),
                       _linha("333", "COLEGA PIOR", 60.0),
                       _linha("444", "SEM NOTA", None)],
            "kpis": {}, "parametros": {"RODOVIARIO": {
                "peso_gobrax": 40, "peso_conduta": 40, "peso_gr": 20}},
            "fontes": {}, "pendencias": {},
        },
        "pagamento": {
            "fechado": False, "fonte": "cálculo",
            "linhas": [{"motorista": "111", "base": 1000.0, "pct": 78.4,
                        "valor": 784.0, "motivo": "", "base_origem": "tabela"},
                       {"motorista": "222", "base": 1000.0, "pct": 95.0,
                        "valor": 950.0, "motivo": "", "base_origem": "tabela"}],
        },
    }
    monkeypatch.setattr(ranking, "montar", lambda c=None, **k: estado["ciclo"])
    monkeypatch.setattr(fechamento, "pagamento",
                        lambda c=None, **k: estado["pagamento"])
    monkeypatch.setattr(mprem, "_historico", lambda codigo: [
        {"ciclo": "2026-08", "rotulo": "16/07 a 15/08 de 2026",
         "nota": 91.0, "valor": 910.0}])
    return estado


# ─────────────────────────────────────────────────────────── o escopo
def test_NAO_existe_parametro_de_motorista(fontes):
    """A mesma regra do resto do app: um argumento que a rota pudesse
    preencher com o que veio do navegador seria a diferença entre um app e um
    buscador da folha alheia."""
    assinatura = inspect.signature(mprem.meu)
    assert list(assinatura.parameters) == ["sessao"]


def test_o_payload_traz_SO_o_numero_dele(fontes):
    d = mprem.meu(EU)
    texto = json.dumps(d, ensure_ascii=False)
    assert d["premio"]["valor"] == 784.0
    for proibido in ("COLEGA MELHOR", "COLEGA PIOR", "950", "222", "333"):
        assert proibido not in texto, proibido


def test_o_CPF_nao_sai_daqui(fontes, monkeypatch):
    sessao = {**EU, "cpf": "11111111111"}     # nem se alguém puser na sessão
    assert "11111111111" not in json.dumps(mprem.meu(sessao))


# ──────────────────────────────────────────────────── prévia × pago
def test_ciclo_ABERTO_sai_marcado_como_PREVIA(fontes):
    d = mprem.meu(EU)
    assert d["previa"] is True and d["fechado"] is False
    assert "em curso" in d["fonte"]


def test_ciclo_FECHADO_traz_o_valor_PAGO_e_nao_o_calculo(fontes):
    fontes["pagamento"] = {
        "fechado": True, "fonte": "fotografia do fechamento",
        "linhas": [{"motorista": "111", "base": 1000.0, "pct": 78.4,
                    "valor": 784.0, "motivo": "", "base_origem": "tabela"}]}
    d = mprem.meu(EU)
    assert d["fechado"] is True and d["previa"] is False
    assert "fotografia" in d["fonte"]


def test_sem_valor_a_linha_diz_o_MOTIVO_e_nao_paga_zero(fontes):
    fontes["pagamento"]["linhas"] = [
        {"motorista": "111", "base": None, "pct": None, "valor": None,
         "motivo": "filial sem valor na tabela", "base_origem": "sem_tabela"}]
    d = mprem.meu(EU)
    assert d["premio"]["valor"] is None
    assert d["premio"]["motivo"] == "filial sem valor na tabela"


# ─────────────────────────────────────────── o que NÃO chega ao app
def test_a_MEDIDA_disciplinar_NAO_trafega(fontes):
    """Medida é rito trabalhista e quem aplica é o RH. O app dar a notícia
    antes da conversa inverte a ordem e cria o conflito que a régua existe
    para evitar."""
    d = mprem.meu(EU)
    texto = json.dumps(d, ensure_ascii=False)
    assert "medida" not in d
    for proibido in ("N4", "Suspensão", "4 desvios em 6 ciclos"):
        assert proibido not in texto, proibido


def test_mas_os_DESVIOS_aparecem_com_o_que_cada_um_tirou(fontes):
    """Os fatos são dele: sem eles a nota vira um número que caiu do céu."""
    d = mprem.meu(EU)
    assert d["desvios"] == [{"nome": "Excesso de velocidade", "grav": "MODERADA",
                             "pts": 7, "data": "2026-09-02"}]
    assert d["meritos"] == 1


# ─────────────────────────────────────────────── a única comparação
def test_a_POSICAO_conta_do_melhor_para_o_pior_e_ignora_quem_nao_tem_nota(fontes):
    """Quem está sem nota não está em último: está fora da conta. '4º de 4'
    diria uma coisa que não aconteceu."""
    d = mprem.meu(EU)
    assert (d["posicao"], d["de"]) == (2, 3)


def test_sem_nota_no_ciclo_nao_ha_posicao(fontes):
    fontes["ciclo"]["linhas"][0] = _linha("111", "MOTORISTA UM", None)
    d = mprem.meu(EU)
    assert d["posicao"] is None and d["de"] == 2


# ───────────────────────────────────────────────── os três pilares
def test_os_pilares_saem_com_PESO_e_dizem_quem_nao_entrou(fontes):
    fontes["ciclo"]["linhas"][0] = _linha(
        "111", "MOTORISTA UM", 78.4, gobrax=None,
        pilares=["conduta", "gr"], ausentes=["gobrax"])
    d = mprem.meu(EU)
    por = {x["chave"]: x for x in d["pilares"]}
    assert por["gobrax"]["entrou"] is False and por["gobrax"]["peso"] == 40
    assert por["conduta"]["entrou"] is True and por["conduta"]["nota"] == 88.0
    assert d["ausentes"] == ["gobrax"]


# ────────────────────────────────────────── quem está fora da régua
def test_agregado_recebe_FORA_DO_ESCOPO_para_a_tela_nao_desenhar_nada(fontes):
    d = mprem.meu({**EU, "motorista_codigo": "999"})
    assert d["tem_dado"] is False and d["fora_do_escopo"] is True
    assert "próprios" in d["motivo"]


def test_fonte_fora_do_ar_NAO_e_fora_do_escopo(fontes, monkeypatch):
    """Um é 'esta régua não é sua', o outro é 'não consegui ler agora'. A tela
    desenha o segundo e cala o primeiro — trocá-los diria ao motorista próprio
    que ele não tem premiação."""
    def explode(*a, **k):
        raise RuntimeError("erp fora")
    monkeypatch.setattr(ranking, "montar", explode)
    d = mprem.meu(EU)
    assert d["tem_dado"] is False and d["fora_do_escopo"] is False
    assert "Tente de novo" in d["motivo"]


# ──────────────────────────────────────────────────────── o histórico
def test_o_historico_entra_no_payload(fontes):
    d = mprem.meu(EU)
    assert d["historico"][0]["valor"] == 910.0
    assert d["historico"][0]["rotulo"] == "16/07 a 15/08 de 2026"


def test_o_historico_e_o_que_FOI_PAGO_e_so_de_ciclo_FECHADO(esquema_pg,
                                                            monkeypatch):
    """Ele sai das FOTOGRAFIAS do fechamento, contra o banco de verdade —
    histórico que se recalcula muda de valor depois de pago, que é o que o
    fechamento existe para impedir. E é só dele: a foto guarda a frota
    inteira."""
    from api import pglocal
    monkeypatch.setattr(mprem, "ESQUEMA", esquema_pg)
    for ciclo, codigo, nota, valor in (("2026-07", "111", 84.0, 840.0),
                                       ("2026-08", "111", 91.0, 910.0),
                                       ("2026-08", "222", 99.0, 990.0)):
        pglocal.executar(
            "INSERT INTO prm_fechamento_linha(ciclo, cpf, motorista, nome,"
            " grupo, nota, valor) VALUES(%s,%s,%s,%s,'RODOVIARIO',%s,%s)",
            (ciclo, "cpf" + codigo + ciclo, codigo, "NOME", nota, valor),
            esquema=esquema_pg)
    h = mprem._historico("111")
    assert [x["ciclo"] for x in h] == ["2026-08", "2026-07"], "do mais novo"
    assert [x["valor"] for x in h] == [910.0, 840.0], "só os dele"


def test_o_historico_indisponivel_nao_derruba_a_tela(monkeypatch):
    """Sem banco o prêmio do ciclo continua na tela: o histórico é o apoio,
    não a resposta. (Sem a fixture `fontes` de propósito: ela substitui o
    próprio `_historico`, e o teste passaria sem tocar no alvo.)"""
    monkeypatch.setattr(mprem, "ESQUEMA", "esquema_que_nao_existe")
    assert mprem._historico("111") == []
