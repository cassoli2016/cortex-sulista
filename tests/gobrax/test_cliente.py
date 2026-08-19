"""Cliente da API Gobrax: autenticação, formatos de data e erros.

Os formatos aqui não são suposição: foram medidos contra a API em 19/08/2026.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.gobrax import cliente as cli


def test_mes_vira_mm_yyyy_com_fim_no_mes_seguinte():
    """A API devolve HTTP 400 quando startDate == endDate. Pedir março exige
    passar abril como fim — foi o primeiro erro da sondagem."""
    assert cli.mes_api("2026-03") == ("03-2026", "04-2026")


def test_virada_de_ano_no_mes_seguinte():
    assert cli.mes_api("2026-12") == ("12-2026", "01-2027")


def test_mes_invalido_e_recusado_antes_de_ir_na_rede():
    for ruim in ("2026-13", "26-03", "2026/03", "", None):
        with pytest.raises(ValueError):
            cli.mes_api(ruim)


def test_periodo_usa_o_formato_das_apis_de_veiculo():
    ini, fim = cli.periodo_api(date(2026, 7, 1), date(2026, 7, 31))
    assert ini == "2026-07-01 00:00:00"
    assert fim == "2026-07-31 23:59:59"


def test_token_vai_no_header_como_bearer():
    chamadas = []

    def http_falso(url, headers, timeout):
        chamadas.append((url, headers))
        return 200, b'{"ok": true}'

    c = cli.Cliente(token="TOKEN-DE-TESTE", http=http_falso)
    assert c.get("/api/v2/driversOverview") == {"ok": True}
    _url, headers = chamadas[0]
    assert headers["Authorization"] == "Bearer TOKEN-DE-TESTE"


def test_sem_token_levanta_erro_proprio():
    with pytest.raises(cli.GobraxNaoConfigurado):
        cli.Cliente(token="")


def test_erro_http_nao_vaza_o_token_na_mensagem():
    """Mensagem de erro vai para log e para a tela. O token não pode viajar."""
    def http_falso(url, headers, timeout):
        return 401, b'{"erro": "nao autorizado"}'

    c = cli.Cliente(token="SEGREDO-QUE-NAO-PODE-VAZAR", http=http_falso)
    with pytest.raises(cli.GobraxIndisponivel) as e:
        c.get("/api/v2/driversOverview")
    assert "SEGREDO" not in str(e.value)
    assert "401" in str(e.value)


def test_timeout_da_rede_vira_gobrax_indisponivel():
    """A API leva 73 s na frota inteira e estoura em período longo — timeout é
    comportamento esperado, não bug, e tem de virar erro tratável."""
    def http_falso(url, headers, timeout):
        raise TimeoutError("read timed out")

    c = cli.Cliente(token="X", http=http_falso)
    with pytest.raises(cli.GobraxIndisponivel):
        c.get("/api/v1/vehicle-statistics")


def test_resposta_nao_json_vira_gobrax_indisponivel():
    def http_falso(url, headers, timeout):
        return 200, b"<html>gateway</html>"

    c = cli.Cliente(token="X", http=http_falso)
    with pytest.raises(cli.GobraxIndisponivel):
        c.get("/api/v2/driversOverview")


def test_params_none_sao_omitidos_da_query():
    chamadas = []

    def http_falso(url, headers, timeout):
        chamadas.append(url)
        return 200, b"{}"

    c = cli.Cliente(token="X", http=http_falso)
    c.get("/x", {"a": "1", "b": None})
    assert "a=1" in chamadas[0]
    assert "b=" not in chamadas[0]
