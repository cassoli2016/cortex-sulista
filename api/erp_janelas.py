# -*- coding: utf-8 -*-
"""As JANELAS RUINS DO ERP, medidas em vez de lembradas.

O ERP é réplica de produção de TERCEIRO, compartilhada com um Power BI que roda
sem `statement_timeout`. Ele degrada em janelas: `SELECT 1` responde na hora e
as consultas pesadas estouram o teto. Isso já derrubou a manhã duas vezes
(03/09/2026 e 06/09/2026) e o assunto sempre voltava como impressão — "o
sistema estava lento hoje de manhã" —, que é o pior insumo possível para uma
conversa com quem administra o ERP.

O QUE ESTE MÓDULO NÃO FAZ, e é de propósito: não coleta nada, não escreve em
lugar nenhum e não abre conexão. Ele LÊ O LOG QUE JÁ EXISTE. Um coletor novo
seria mais uma coisa para falhar em silêncio, e justamente no dia ruim; o log
é escrito pelo caminho que já falha, então ele não pode estar mudo enquanto
houver falha.

A CONTRAPARTIDA HONESTA é a cobertura: o log rotaciona em 5 MB, então o que se
mede é a janela que o arquivo corrente alcança — e o cartão DIZ desde quando,
em vez de deixar quem lê supor que "3 janelas" é o total da história.

Duas coisas são contadas, e elas são COMPLEMENTARES, não redundantes — o que
as separa é quem pegou a queda:

- **timeout**: a consulta foi cancelada e ninguém aparou. A tela mostrou erro.
- **resgate**: a `cached(velha_ate=)` serviu a última leitura boa e a tela
  seguiu de pé, com a tarja. Aqui NÃO existe linha de timeout: a rede engole a
  exceção antes de a rota vê-la, então este é o único rastro do incidente.

A razão entre os dois é quanto do estrago o portal absorveu sozinho.

UMA IMPRECISÃO CONHECIDA, dita aqui porque quem lê o número precisa saber: a
API de produção e qualquer script rodado desta árvore escrevem no MESMO
arquivo de log. Uma bateria de testes que exercite o caminho da rede soma
"resgates" que nenhum usuário viu. O número de janelas e de timeouts é robusto
a isso (teste não cancela consulta do ERP); o de resgates é o que pode inflar,
e por isso ele não é o destaque do cartão.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

# As duas assinaturas, tal como o servidor as escreve.
TIMEOUT = "canceling statement due to statement timeout"
RESGATE = "servindo leitura de"

# Silêncio que FECHA uma janela. Dez minutos: as janelas medidas duraram de 10
# min a 2 h e vinham em rajadas de segundos; um intervalo menor partiria a
# mesma janela em várias e inflaria a contagem, que é justamente o número que
# alguém levaria para a conversa.
GAP_MIN = 10

# Prefixo `AAAA-MM-DD HH:MM:SS` — o formato do handler em api/main.py.
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

_LOG = Path(__file__).resolve().parent.parent / "logs" / "api.log"

# Teto de leitura. O arquivo rotaciona em 5 MB; ler mais que isso significaria
# que alguém mudou a rotação, e aí o certo é medir menos e dizer, não engolir
# um arquivo de tamanho desconhecido dentro de uma tela que repinta sozinha.
MAX_BYTES = 8 * 1024 * 1024


def eventos(linhas) -> list[tuple[datetime, str]]:
    """(instante, tipo) de cada linha que interessa. Puro: recebe as linhas."""
    fora: list[tuple[datetime, str]] = []
    for l in linhas:
        tipo = ("timeout" if TIMEOUT in l else
                "resgate" if RESGATE in l else None)
        if not tipo:
            continue
        m = _TS.match(l)
        if not m:
            continue
        try:
            fora.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"),
                         tipo))
        except ValueError:                      # pragma: no cover
            continue
    return fora


def agrupar(evs: list[tuple[datetime, str]],
            gap_min: int = GAP_MIN) -> list[dict]:
    """Eventos viram JANELAS. Rajada de segundos é UM incidente, não trinta."""
    janelas: list[dict] = []
    for quando, tipo in sorted(evs):
        atual = janelas[-1] if janelas else None
        if atual is None or (quando - atual["_fim"]) > timedelta(minutes=gap_min):
            janelas.append({"_ini": quando, "_fim": quando,
                            "timeouts": 0, "resgates": 0})
            atual = janelas[-1]
        atual["_fim"] = quando
        atual["timeouts" if tipo == "timeout" else "resgates"] += 1
    for j in janelas:
        j["inicio"] = j["_ini"].strftime("%Y-%m-%d %H:%M")
        j["fim"] = j["_fim"].strftime("%H:%M")
        # Duração ARREDONDADA PARA CIMA: uma janela inteira dentro do mesmo
        # minuto é "1 min", nunca "0 min" — zero leria como "não aconteceu".
        seg = (j["_fim"] - j["_ini"]).total_seconds()
        j["minutos"] = max(1, int(seg // 60 + (1 if seg % 60 else 0)))
        j.pop("_ini"), j.pop("_fim")
    return janelas


def medir(caminho: Path | None = None, agora: datetime | None = None) -> dict:
    """Lê o log e devolve as janelas, a distribuição por hora e a cobertura."""
    arq = Path(caminho) if caminho else _LOG
    agora = agora or datetime.now()
    try:
        if not arq.exists():
            return {"legivel": False, "motivo": "o log da API não existe"}
        tam = arq.stat().st_size
        with arq.open("r", encoding="utf-8", errors="replace") as fh:
            if tam > MAX_BYTES:
                fh.seek(tam - MAX_BYTES)
                fh.readline()               # descarta a linha partida
            linhas = fh.readlines()
    except OSError as exc:
        return {"legivel": False, "motivo": "não deu para ler o log (%s)"
                                            % type(exc).__name__}

    evs = eventos(linhas)
    # A COBERTURA SAI DO PRÓPRIO ARQUIVO, não da suposição de que ele é antigo:
    # depois de uma rotação recente ele cobre horas, e "3 janelas" sobre duas
    # horas de log significa outra coisa que sobre seis dias.
    desde = None
    for l in linhas:
        m = _TS.match(l)
        if m:
            desde = m.group(1)
            break

    janelas = agrupar(evs)
    por_hora: dict[str, int] = {}
    por_dia: dict[str, int] = {}
    for quando, tipo in evs:
        if tipo != "timeout":
            continue
        por_hora[quando.strftime("%H")] = por_hora.get(quando.strftime("%H"), 0) + 1
        dia = quando.strftime("%Y-%m-%d")
        por_dia[dia] = por_dia.get(dia, 0) + 1

    corte = agora - timedelta(hours=24)
    recentes = [j for j in janelas
                if datetime.strptime(j["inicio"], "%Y-%m-%d %H:%M") >= corte]
    total_to = sum(por_hora.values())
    manha = sum(n for h, n in por_hora.items() if "04" <= h <= "09")
    return {
        "legivel": True,
        "desde": desde,
        "janelas": janelas,
        "janelas_24h": len(recentes),
        "ultima": janelas[-1] if janelas else None,
        "timeouts": total_to,
        "resgates": sum(j["resgates"] for j in janelas),
        # A concentração é o achado que muda a conversa: 86% entre 04h e 09h
        # não é "o ERP é lento", é "o ERP tem horário de funcionamento".
        "pct_manha": round(100.0 * manha / total_to, 1) if total_to else None,
        "por_hora": por_hora,
        "por_dia": por_dia,
    }
