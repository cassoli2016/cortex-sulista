# -*- coding: utf-8 -*-
"""Dublês do Radar: a rede, a TomTom e o relógio.

AS AMOSTRAS SÃO CORPOS REAIS, cortados do que cada fonte devolveu em
11/09/2026 (`tests/radar/dados/`): a planilha da ANP com o cabeçalho e as
seis últimas semanas, o gráfico do Yahoo com 45 pregões, a PTAX de jul–set e
três itens do RSS do Google Notícias. Nenhuma é montada a partir do código
que a lê — dublê derivado do leitor aprova o leitor por construção.

O RELÓGIO É FIXADO NO DIA DAS AMOSTRAS, e é o relógio que o código LÊ
(`coleta._agora`, `painel._agora`): as amostras têm data, e com o relógio de
verdade a janela de 30 dias das notícias as descartaria em outubro — o teste
passaria a acusar quem estivesse rodando a suíte naquele mês.

E NENHUM TESTE SAI PARA A REDE: a fixture automática troca as duas portas por
uma que reprova. Numa bancada com a TomTom configurada, uma chamada esquecida
gastaria cota de produção sem nada falhar.
"""
from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DADOS = Path(__file__).parent / "dados"

#: O "agora" das amostras: 11/09/2026, 12h de Brasília. O último pregão das
#: amostras do Yahoo é deste dia, e a notícia mais nova também.
AGORA = datetime(2026, 9, 11, 15, 0, tzinfo=timezone.utc)


def ler(nome: str) -> bytes:
    """Os bytes de uma amostra — e a planilha da ANP é REMONTADA aqui.

    A PLANILHA NÃO ESTÁ NO REPOSITÓRIO, e é de propósito: o `.gitignore` recusa
    todo `*.xlsx`, porque o repositório é público e planilha aqui costuma ser
    dado da empresa (o histórico já foi reescrito uma vez por isso). As células
    REAIS dela vivem em `anp_semanal_trecho.json` e a planilha é montada de
    novo, célula a célula, na hora do teste.

    Até 11/09/2026 a amostra era o próprio `.xlsx` — ignorado em silêncio pelo
    git, presente só na máquina de quem escreveu: 11 testes passavam lá e em
    nenhum outro lugar. `test_amostras_versionadas.py` segura a classe.
    """
    if nome == "anp_semanal_trecho.xlsx":
        return _planilha_anp()
    return (DADOS / nome).read_bytes()


def _planilha_anp() -> bytes:
    import io
    import json

    import openpyxl
    d = json.loads((DADOS / "anp_semanal_trecho.json").read_text(encoding="utf-8"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = d["aba"]
    for linha in d["linhas"]:
        ws.append([datetime.fromisoformat(c["data"]) if isinstance(c, dict) and "data" in c
                   else c for c in linha])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


#: A amostra de incidentes da TomTom de `tests/test_tomtom.py` (`AMOSTRA`):
#: dois relevantes (BR-101 fechada, BR-116 lenta moderada) e dois de rua, que
#: o filtro tem de tirar.
TOMTOM = {"incidents": [
    {"properties": {"iconCategory": 8, "magnitudeOfDelay": 4, "delay": None,
                    "from": "PR-423", "to": "Rua São Luiz", "roadNumbers": [],
                    "events": [{"description": "Encerrado/a"}]}},
    {"properties": {"iconCategory": 8, "magnitudeOfDelay": 4, "delay": None,
                    "from": "BR-101", "to": "BR-101", "roadNumbers": ["BR-101"],
                    "events": [{"description": "Encerrado/a"}]}},
    {"properties": {"iconCategory": 6, "magnitudeOfDelay": 2, "delay": 300,
                    "from": "BR-116", "to": "BR-116", "roadNumbers": ["BR-116"],
                    "events": [{"description": "Trânsito lento"}]}},
    {"properties": {"iconCategory": 9, "magnitudeOfDelay": 1, "delay": 60,
                    "from": "Rua X", "to": "Rua Y", "roadNumbers": [],
                    "events": [{"description": "Obras"}]}},
]}

#: Trecho da URL × amostra que responde por ela.
ROTAS = (
    ("gov.br/anp", "anp_semanal_trecho.xlsx"),
    ("BZ%3DF", "yahoo_brent_trecho.json"),
    ("BRL%3DX", "yahoo_dolar_trecho.json"),
    ("bcdata.sgs", "bcb_ptax_trecho.json"),
    ("news.google.com", "gnews_diesel_trecho.xml"),
)


class Rede:
    """`baixar(url, timeout)` de mentira. `falhar` recebe trechos de URL que
    devem responder HTTP 503; `trocar` substitui o corpo de uma rota."""

    def __init__(self):
        self.pedidos: list[str] = []
        self.falhar: set[str] = set()
        self.trocar: dict[str, bytes] = {}

    def __call__(self, url: str, timeout: float = 60) -> bytes:
        self.pedidos.append(url)
        for trecho, arquivo in ROTAS:
            if trecho in url:
                if trecho in self.falhar:
                    raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
                return self.trocar.get(trecho) or ler(arquivo)
        raise AssertionError("URL sem dublê: " + url)


class TomTom:
    def __init__(self, corpo=None, falhar: bool = False):
        self.corpo = TOMTOM if corpo is None else corpo
        self.falhar = falhar
        self.chamadas = 0

    def __call__(self, oeste, sul, leste, norte):
        self.chamadas += 1
        if self.falhar:
            from api.tomtom.cliente import TomTomIndisponivel
            raise TomTomIndisponivel("A TomTom respondeu HTTP 503.")
        return self.corpo


@pytest.fixture(autouse=True)
def _sem_rede_de_verdade(monkeypatch):
    from api.radar import fontes, rodovias

    def _proibido(*a, **k):
        raise AssertionError("um teste do Radar tentou sair para a rede de verdade")

    monkeypatch.setattr(fontes, "baixar", _proibido)
    monkeypatch.setattr(rodovias, "_consultar_tomtom", _proibido)
    # O TRÂNSITO LIGADO é o caminho que estes testes descrevem. O desligado
    # por decisão (`cliente.TRAFEGO_DESLIGADO`, 11/09/2026) tem os testes dele,
    # que o ligam explicitamente — sem esta linha a suíte mudaria de resultado
    # no dia em que alguém religasse o trânsito.
    from api.tomtom import cliente
    monkeypatch.setattr(cliente, "TRAFEGO_DESLIGADO", None)
    # A FROTA É DO ERP, e nenhum teste do Radar consulta o ERP: a coleta de
    # toda passada lê este dublê — um caminhão andando e um lento em Curitiba,
    # um parado em Joinville. Quem testa a leitura de verdade chama `frota.ler`
    # com as entradas na mão (test_frota.py).
    from api.radar import frota
    viagens = [{"placa": "RAD0A01"}, {"placa": "RAD0A02"}, {"placa": "RAD0A03"}]
    posicoes = {"posicoes": {
        "RAD0A01": {"lat": -25.43, "lon": -49.27, "fonte": "erp", "idade_min": 2.0},
        "RAD0A02": {"lat": -25.50, "lon": -49.20, "fonte": "erp", "idade_min": 2.0},
        "RAD0A03": {"lat": -26.30, "lon": -48.85, "fonte": "erp", "idade_min": 3.0}}}
    velocidades = {"RAD0A01": (70, 72, 75), "RAD0A02": (30, 22, 18), "RAD0A03": (0, 0, 0)}

    def serie(placas, agora):
        return {pl: [(agora - timedelta(minutes=m), float(v))
                     for m, v in zip((12, 6, 1), velocidades[pl])] for pl in placas}
    monkeypatch.setattr(frota, "_entradas", lambda: (viagens, posicoes))
    monkeypatch.setattr(frota, "_serie", serie)


class Relogio:
    def __init__(self, monkeypatch):
        from api.radar import coleta, painel
        self.agora = AGORA
        monkeypatch.setattr(coleta, "_agora", lambda: self.agora)
        monkeypatch.setattr(painel, "_agora", lambda: self.agora)

    def andar(self, **kw):
        self.agora = self.agora + timedelta(**kw)


@pytest.fixture
def relogio(monkeypatch) -> Relogio:
    return Relogio(monkeypatch)


@pytest.fixture
def rede() -> Rede:
    return Rede()


@pytest.fixture
def tomtom() -> TomTom:
    return TomTom()
