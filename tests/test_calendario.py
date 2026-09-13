# -*- coding: utf-8 -*-
"""O calendário de feriados (`api/calendario.py`).

A WEB POPULA, A LEI DECIDE A FOLGA. O corpo abaixo é o da BrasilAPI COPIADO do
real (12/09/2026) — dublê de fornecedor copia o corpo real, e é nele que se vê
o Carnaval e o Corpus Christi chamados de "national". Nenhum teste vai à web.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from api import agendamento, calendario, pglocal

#: GET https://brasilapi.com.br/api/feriados/v1/2026, em 12/09/2026, literal.
CORPO_2026 = [
    {"date": "2026-01-01", "name": "Confraternização mundial", "type": "national", "weekday": "quinta-feira"},
    {"date": "2026-02-16", "name": "Carnaval", "type": "national", "weekday": "segunda-feira"},
    {"date": "2026-02-17", "name": "Carnaval", "type": "national", "weekday": "terça-feira"},
    {"date": "2026-04-03", "name": "Sexta-feira Santa", "type": "national", "weekday": "sexta-feira"},
    {"date": "2026-04-05", "name": "Páscoa", "type": "national", "weekday": "domingo"},
    {"date": "2026-04-21", "name": "Tiradentes", "type": "national", "weekday": "terça-feira"},
    {"date": "2026-05-01", "name": "Dia do trabalho", "type": "national", "weekday": "sexta-feira"},
    {"date": "2026-06-04", "name": "Corpus Christi", "type": "national", "weekday": "quinta-feira"},
    {"date": "2026-09-07", "name": "Independência do Brasil", "type": "national", "weekday": "segunda-feira"},
    {"date": "2026-10-12", "name": "Nossa Senhora Aparecida", "type": "national", "weekday": "segunda-feira"},
    {"date": "2026-11-02", "name": "Finados", "type": "national", "weekday": "segunda-feira"},
    {"date": "2026-11-15", "name": "Proclamação da República", "type": "national", "weekday": "domingo"},
    {"date": "2026-11-20", "name": "Dia da consciência negra", "type": "national", "weekday": "sexta-feira"},
    {"date": "2026-12-25", "name": "Natal", "type": "national", "weekday": "sexta-feira"},
]


#: GET https://brasilapi.com.br/api/feriados/v1/2027, em 12/09/2026, literal.
CORPO_2027 = [
    {"date": "2027-01-01", "name": "Confraternização mundial", "type": "national", "weekday": "sexta-feira"},
    {"date": "2027-02-08", "name": "Carnaval", "type": "national", "weekday": "segunda-feira"},
    {"date": "2027-02-09", "name": "Carnaval", "type": "national", "weekday": "terça-feira"},
    {"date": "2027-03-26", "name": "Sexta-feira Santa", "type": "national", "weekday": "sexta-feira"},
    {"date": "2027-03-28", "name": "Páscoa", "type": "national", "weekday": "domingo"},
    {"date": "2027-04-21", "name": "Tiradentes", "type": "national", "weekday": "quarta-feira"},
    {"date": "2027-05-01", "name": "Dia do trabalho", "type": "national", "weekday": "sábado"},
    {"date": "2027-05-27", "name": "Corpus Christi", "type": "national", "weekday": "quinta-feira"},
    {"date": "2027-09-07", "name": "Independência do Brasil", "type": "national", "weekday": "terça-feira"},
    {"date": "2027-10-12", "name": "Nossa Senhora Aparecida", "type": "national", "weekday": "terça-feira"},
    {"date": "2027-11-02", "name": "Finados", "type": "national", "weekday": "terça-feira"},
    {"date": "2027-11-15", "name": "Proclamação da República", "type": "national", "weekday": "segunda-feira"},
    {"date": "2027-11-20", "name": "Dia da consciência negra", "type": "national", "weekday": "sábado"},
    {"date": "2027-12-25", "name": "Natal", "type": "national", "weekday": "sábado"},
]


@pytest.fixture
def cal(esquema_pg, monkeypatch):
    monkeypatch.setattr(calendario, "ESQUEMA", esquema_pg)
    calendario._invalidar()
    yield esquema_pg
    calendario._invalidar()


def _web(corpo):
    return lambda ano: [dict(x) for x in corpo]


# ═══════════════════════════════════════════════════════ a lei ═══════════

@pytest.mark.parametrize("ano,esperado", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                          (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))])
def test_a_pascoa(ano, esperado):
    assert calendario.pascoa(ano) == esperado


def test_a_lista_da_lei_tem_a_consciencia_negra_SO_desde_2024():
    lei26 = calendario.nacionais_da_lei(2026)
    assert len(lei26) == 10
    assert date(2026, 4, 3) in lei26 and date(2026, 11, 20) in lei26
    assert date(2023, 11, 20) not in calendario.nacionais_da_lei(2023)
    for facultativo in (date(2026, 2, 16), date(2026, 2, 17), date(2026, 6, 4)):
        assert facultativo not in lei26, "ponto facultativo não é feriado da lei"


# ═══════════════════════════════════════════════════════ a web ═══════════

def test_o_corpo_REAL_da_web_e_classificado_pela_lei():
    linhas, div = calendario.classificar(CORPO_2026, 2026)
    por = {(l["data"], l["nome"]): l for l in linhas}
    assert por[(date(2026, 2, 16), "Carnaval")]["tipo"] == "facultativo"
    assert por[(date(2026, 2, 16), "Carnaval")]["folga"] is False
    assert por[(date(2026, 6, 4), "Corpus Christi")]["folga"] is False
    assert por[(date(2026, 4, 5), "Páscoa")]["tipo"] == "comemorativa"
    assert por[(date(2026, 9, 7), "Independência do Brasil")]["folga"] is True
    assert sum(1 for l in linhas if l["folga"]) == 10
    assert div == [], div


def test_a_web_NUNCA_cria_folga_sozinha():
    """Um erro da fonte não pode calar um e-mail."""
    corpo = CORPO_2026 + [{"date": "2026-03-10", "name": "Dia Inventado", "type": "national"}]
    linhas, div = calendario.classificar(corpo, 2026)
    extra = [l for l in linhas if l["data"] == date(2026, 3, 10)][0]
    assert extra["tipo"] == "a_conferir" and extra["folga"] is False
    assert any("Dia Inventado" in d for d in div)


def test_a_LEI_cobre_o_que_a_web_nao_trouxe():
    corpo = [x for x in CORPO_2026 if x["name"] != "Natal"]
    linhas, div = calendario.classificar(corpo, 2026)
    natal = [l for l in linhas if l["data"] == date(2026, 12, 25)][0]
    assert natal["fonte"] == "lei" and natal["folga"] is True
    assert any("Natal" in d for d in div)


# ═══════════════════════════════════════════════════════ o banco ═════════

def test_popular_grava_e_a_decisao_de_alguem_SOBREVIVE_a_proxima_busca(cal):
    r = calendario.popular(2026, baixar_fn=_web(CORPO_2026))
    assert r == {"ano": 2026, "itens": 14, "folgas": 10, "divergencias": []}
    carnaval = [x for x in calendario.estado(2026)["itens"]
                if x["data"] == "2026-02-17"][0]
    calendario.marcar_folga(carnaval["id"], True, "financeiro@exemplo.test")
    assert not calendario.dia_util(date(2026, 2, 17))
    calendario.popular(2026, baixar_fn=_web(CORPO_2026))
    assert not calendario.dia_util(date(2026, 2, 17)), "a busca desfez a decisão"
    assert calendario.dia_util(date(2026, 2, 16)), "a segunda de Carnaval ninguém marcou"


def test_sem_busca_vale_a_LEI_e_o_manual_SOMA(cal):
    assert not calendario.dia_util(date(2026, 9, 7))
    assert calendario.dia_util(date(2026, 9, 8))
    calendario.gravar_manual({"data": "2026-03-09", "nome": "Aniversário da cidade",
                              "tipo": "municipal", "uf": "sc", "municipio": "Cidade Dublê"},
                             "rh@exemplo.test")
    assert not calendario.dia_util(date(2026, 3, 9))
    assert not calendario.dia_util(date(2026, 9, 7)), "o manual não apaga a lei"


def test_a_web_FORA_fica_registrada_sem_apagar_o_ultimo_sucesso(cal):
    calendario.popular(2026, baixar_fn=_web(CORPO_2026))

    def fora(ano):
        raise TimeoutError("sem resposta")
    with pytest.raises(TimeoutError):
        calendario.popular(2026, baixar_fn=fora)
    c = calendario.estado(2026)["coleta"]
    assert c["ok_em"] and "TimeoutError" in c["erro"]
    assert len(calendario.estado(2026)["itens"]) == 14


def test_so_o_MANUAL_se_remove(cal):
    calendario.popular(2026, baixar_fn=_web(CORPO_2026))
    natal = [x for x in calendario.estado(2026)["itens"] if x["data"] == "2026-12-25"][0]
    with pytest.raises(ValueError, match="Desmarque"):
        calendario.remover_manual(natal["id"])
    m = calendario.gravar_manual({"data": "2026-12-24", "nome": "Véspera de Natal",
                                  "tipo": "empresa"}, "rh@exemplo.test")
    calendario.remover_manual(m["id"])
    assert calendario.dia_util(date(2026, 12, 24))


@pytest.mark.parametrize("dados,msg", [
    ({"data": "2026-03-09", "nome": "X", "tipo": "municipal"}, "nome"),
    ({"data": "2026-03-09", "nome": "Aniversário", "tipo": "nacional"}, "Tipo"),
    ({"data": "2026-03-09", "nome": "Aniversário", "tipo": "municipal", "uf": "SC"}, "município"),
    ({"data": "", "nome": "Aniversário", "tipo": "empresa"}, "data"),
])
def test_o_manual_invalido_e_RECUSADO_com_motivo(dados, msg):
    with pytest.raises(ValueError, match=msg):
        calendario._validar_manual(dados)


def test_garantir_busca_o_que_falta_UMA_vez_por_dia_e_nunca_levanta(cal):
    chamadas = []

    def web(ano):
        chamadas.append(ano)
        if ano == 2027:
            raise TimeoutError("fora")
        return [dict(x) for x in CORPO_2026]
    saida = calendario.garantir(date(2026, 9, 12), baixar_fn=web)
    assert chamadas == [2026, 2027]
    assert any("2027: busca falhou" in s for s in saida)
    calendario.garantir(date(2026, 9, 12), baixar_fn=web)
    assert chamadas == [2026, 2027], "2026 já está buscado e 2027 tentou há menos de um dia"


def test_numa_rodada_de_teste_SEM_esquema_o_banco_de_producao_nao_e_lido(monkeypatch):
    """Conta as idas ao banco em vez de fazê-las explodir: `folgas()` engole a
    falha do banco e cai na lei (é o que protege o "dia útil" em produção), e
    uma explosão aqui seria engolida junto — o teste passaria com o gate
    arrancado. Visto na sabotagem de 12/09/2026."""
    idas = []
    # O `context()` DESFAZ o dublê do `pglocal` ANTES da limpeza dos fixtures:
    # o `producao_intocada` (tests/conftest.py) lê o banco na limpeza, e com o
    # dublê ainda posto ele leria "nada" e acusaria escrita que não houve.
    with monkeypatch.context() as m:
        m.setattr(calendario, "ESQUEMA", None)
        m.setattr(pglocal, "query", lambda *a, **k: idas.append(a[0]) or [])
        m.setattr(pglocal, "um", lambda *a, **k: idas.append(a[0]))
        calendario._invalidar()
        util = calendario.dia_util(date(2026, 9, 7))
    calendario._invalidar()
    assert not util
    assert idas == [], "a rodada de teste leu o banco de produção"


# ═══════════════════════════════════════════════════════ quem usa ════════

def test_o_agendamento_de_dia_util_NAO_sai_no_feriado_e_DIZ_qual():
    ag = {"id": 1, "relatorio": "inadimplencia", "frequencia": "diario", "hora": "13:00",
          "dias_uteis": True, "ativo": True, "ultima_execucao": None}
    pode, porque = agendamento.deve_rodar(ag, datetime(2026, 9, 7, 13, 5))
    assert not pode and porque.startswith("feriado: Independência do Brasil")
    assert agendamento.deve_rodar(ag, datetime(2026, 9, 8, 13, 5))[0]
    assert agendamento.deve_rodar({**ag, "dias_uteis": False}, datetime(2026, 9, 7, 13, 5))[0], \
        "quem não marcou 'só dias úteis' continua saindo todo dia"
    assert agendamento.proxima(ag, datetime(2026, 9, 4, 14, 0)) == "2026-09-08 13:00"


def _rotina(monkeypatch, argv):
    """O script dos relatórios agendados, carregado de verdade, com a agenda
    vazia — o que se observa é só a manutenção do calendário."""
    import importlib.util
    import sys
    from pathlib import Path
    caminho = Path(__file__).resolve().parents[1] / "scripts" / "enviar_agendados.py"
    spec = importlib.util.spec_from_file_location("enviar_agendados_teste", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.agenda, "listar", lambda: [])
    monkeypatch.setattr(sys, "argv", ["enviar_agendados.py"] + argv)
    return mod


def test_a_rotina_dos_relatorios_MANTEM_o_calendario_e_nao_cai_com_ele(monkeypatch):
    chamadas = []
    monkeypatch.setattr(calendario, "garantir", lambda: chamadas.append(1) or ["ok"])
    assert _rotina(monkeypatch, []).main() == 0 and chamadas == [1]
    assert _rotina(monkeypatch, ["--ensaio"]).main() == 0 and chamadas == [1], \
        "o ensaio não busca na web nem grava"

    def explode():
        raise RuntimeError("banco fora")
    monkeypatch.setattr(calendario, "garantir", explode)
    assert _rotina(monkeypatch, []).main() == 0, "o calendário derrubou o envio"


def test_o_Copiloto_recebe_os_dias_uteis_do_mes():
    r = calendario.resumo_copiloto(date(2026, 9, 1))
    assert r["proximo_feriado"] == "2026-09-07"
    assert r["dias_uteis_no_mes"] == 21, "setembro/2026: 22 dias de semana menos o 7"
    assert r["dias_uteis_restantes_no_mes"] == 21


def test_o_cartao_da_Saude(cal, monkeypatch):
    from api import servidor
    hoje = date(2026, 9, 12)
    assert servidor._calendario(hoje)["status"] == "info"
    calendario.popular(2026, baixar_fn=_web(CORPO_2026))
    calendario.popular(2027, baixar_fn=_web(CORPO_2027))
    c = servidor._calendario(hoje)
    assert c["status"] == "ok" and "próximo: 12/10" in c["detalhe"], c
    assert calendario.classificar(CORPO_2027, 2027)[1] == [], \
        "o corpo real de 2027 bate com a lei — a Paixão de 2027 é 26/03"
    calendario.popular(2026, baixar_fn=_web(CORPO_2026 + [
        {"date": "2026-03-10", "name": "Dia Inventado", "type": "national"}]))
    c = servidor._calendario(hoje)
    assert c["status"] == "alerta" and "Dia Inventado" in c["detalhe"]
