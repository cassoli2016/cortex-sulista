"""Vai chegar na hora? — ETA com trânsito contra a previsão do ERP.

O QUE ESTA CAMADA RESPONDE, E O QUE ELA NÃO INVENTA
==================================================
A Torre já mostrava "atrasada: sim/não", comparando a previsão de chegada do
ERP com o relógio. Isso só percebe o atraso **depois que ele aconteceu**. O que
falta é a pergunta que dá tempo de agir: *com o trânsito de agora, daqui até o
destino, ele chega na hora?*

A conta é `agora + tempo de viagem da TomTom` contra `dtprevisaochegadaviagem`.
Nada mais: não há aqui estimativa de parada para descanso, de fila na doca nem
de pernoite. Uma viagem que precisa parar 11h por interjornada vai aparecer
"chegando adiantado" e **isso está dito na tela** — inventar a parada seria
fabricar um número que a fonte não dá, e a jornada é outro módulo, com regra
própria.

TRÊS RECORTES, E TODOS SÃO ECONOMIA *E* SENTIDO
===============================================
Medido em 30/08/2026, nas viagens em trânsito:

    em trânsito ......................... 70
    com coordenada de destino ........... 57   (13 sem: cadastro)
    com previsão de chegada ............. 59
    com as duas ......................... 57
    prometidas nas próximas 24 h ........ 47   <- o recorte
    já vencidas ......................... 6

Viagem prometida para a semana que vem não precisa de ETA ao vivo: o trânsito
de agora não diz nada sobre terça-feira. Sem coordenada não há rota — e isso é
**cadastro**, dito como tal, não "sem previsão".

MODO CAMINHÃO, e ele muda o número: Joinville → Curitiba deu 2h00 de carro e
2h16 de caminhão nos mesmos 132,6 km. Usar a rota de carro erraria 16 minutos
numa viagem de duas horas, e ignoraria restrição de via, altura e peso.

TTL PRÓPRIO, MAIOR QUE O DO FLUXO
=================================
O fluxo tem TTL de 10 min porque a condição do trecho muda rápido. A previsão
de chegada de uma viagem de horas não melhora sendo recalculada a cada dez
minutos, e cada recálculo custa ~47 chamadas. 30 minutos é o que equilibra —
e o consumo continua contado em `tt_chamadas`, porque o limite do plano não é
observável na resposta.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from api import db
from api.tomtom import cliente, coleta

log = logging.getLogger(__name__)

TTL_S = 1800          # 30 min: previsão de viagem de horas não muda em minutos
# TRES, e nao os oito do fluxo: MEDIDO que o Routing recusa a partir de
# ~6 req/s enquanto o Traffic aguenta ~14. Com oito, 15 de 47 chamadas
# voltaram 429 -- 32% da tela viraria "sem estimativa", indistinguivel de
# falta de cadastro.
TRABALHADORES = 3
HORIZONTE_H = 24      # prometida para além disso não precisa de ETA ao vivo

# Minutos de folga a partir dos quais a chegada deixa de ser "no prazo". Não é
# zero de propósito: um ETA que bate a previsão no minuto exato é ruído, e
# pintar de vermelho quem está 2 minutos "atrasado" ensina a ignorar a cor.
APERTADO_MIN = 15

VIAGENS_SQL = """
SELECT p.numero, p.filial,
       upper(trim(p.veiculo))                       AS placa,
       co.latitudedestino::float8                   AS lat_destino,
       co.longitudedestino::float8                  AS lon_destino,
       co.dtprevisaochegadaviagem                   AS previsao,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||
         coalesce(p.ufdestino,'?')                  AS destino
  FROM programacaoembarque p
  JOIN coleta co ON co.grupo = p.grupo AND co.empresa = p.empresa
   AND co.filial = p.filialdocumentoorigem
   AND co.unidade = p.unidadedocumentoorigem
   AND co.diferenciadornumero = p.diferenciadornumerodocumentoorigem
   AND co.numero = p.numerodocumentoorigem
 WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
   AND p.dtsaida IS NOT NULL AND p.dtchegada IS NULL
   AND p.dtsaida >= current_date - 15
   AND co.dtprevisaochegadaviagem IS NOT NULL
   AND co.dtprevisaochegadaviagem <= current_timestamp + (%(horas)s * interval '1 hour')
 ORDER BY co.dtprevisaochegadaviagem
"""

_cache: tuple[float, dict] | None = None
_lock = threading.Lock()


def classificar(folga_min: float | None, vencida_ha_min: float = 0) -> dict:
    """`folga_min` = minutos entre a chegada estimada e a prometida.

    JÁ VENCIDA É CATEGORIA PRÓPRIA, e essa distinção não é cosmética. Na
    primeira rodada real, seis viagens saíram como "chega atrasado" com folga
    de **-8.702 minutos** — a prometida era 24/08 e o dia era 30/08. Uma viagem
    seis dias além do prazo não é um problema de ETA: ou é registro que ninguém
    fechou (o `dtchegada` nunca preenchido, irmão do marcador de manutenção
    parado em 77.534 km), ou é uma ocorrência que a operação já conhece.

    Misturá-las com o que ainda dá para salvar estraga as duas leituras: o
    "maior atraso previsto" vira -8.702 min e ninguém acredita mais no número,
    e as que vão atrasar DAQUI A POUCO — as únicas em que dá para agir — ficam
    embaixo de seis casos velhos.
    """
    if vencida_ha_min > 0:
        return {"situacao": "vencida", "rotulo": "Prazo já vencido"}
    if folga_min is None:
        return {"situacao": "nd", "rotulo": "Sem estimativa"}
    if folga_min < 0:
        return {"situacao": "atrasado", "rotulo": "Chega atrasado"}
    if folga_min < APERTADO_MIN:
        return {"situacao": "apertado", "rotulo": "No limite"}
    return {"situacao": "no_prazo", "rotulo": "No prazo"}


def _destino(v: dict) -> tuple[tuple[float, float] | None, bool]:
    """A coordenada de destino e se ela é APROXIMADA.

    O ERP é a fonte boa (`latitudedestino` é o ponto de entrega). Quando ele
    não tem — 13 das 70 viagens —, cai no centro da cidade geocodificado, que
    é melhor que ETA nenhum e PIOR que o ponto real: num município grande a
    diferença até a doca chega a vinte minutos. Daí o segundo valor de retorno,
    que a tela é obrigada a mostrar.
    """
    if v.get("lat_destino") is not None and v.get("lon_destino") is not None:
        return (v["lat_destino"], v["lon_destino"]), False
    from api.tomtom import geo
    c = geo.coordenada(v.get("destino") or "")
    return ((c["lat"], c["lon"]), True) if c else (None, True)


def _uma(item) -> dict:
    v, pos, agora = item
    vencida_ha = round((agora.timestamp() - v["previsao"].timestamp()) / 60.0, 1)
    base = {"numero": v["numero"], "filial": v["filial"], "placa": v["placa"],
            "destino": v["destino"],
            "previsao": v["previsao"].strftime("%Y-%m-%d %H:%M"),
            "vencida_ha_min": vencida_ha if vencida_ha > 0 else None}
    if vencida_ha > 0:
        # NÃO GASTA CHAMADA. O ETA não muda o fato de o prazo ter passado, e
        # eram 6 de 47 — 13% da varredura indo para uma pergunta já respondida.
        return {**base, "ok": True, "chamou": False,
                **classificar(None, vencida_ha)}
    alvo, aproximado = _destino(v)
    base["destino_aproximado"] = aproximado
    if alvo is None:
        # SEM COORDENADA NEM GEOCODIFICADA: é cadastro, e é dito como tal —
        # "sem estimativa" faria parecer falha da consulta.
        # CADASTRO, NAO FALHA DA API — e nao gastou chamada nenhuma.
        return {**base, "ok": False, "chamou": False, "motivo": "cadastro",
                "erro": "destino sem coordenada no ERP e não localizado",
                **classificar(None)}
    try:
        r = cliente.rota((pos["lat"], pos["lon"]), alvo, caminhao=True)
    except cliente.TomTomIndisponivel as exc:
        return {**base, "ok": False, "chamou": True, "motivo": "api",
                "erro": str(exc), **classificar(None)}
    rotas = r.get("routes") or []
    if not rotas:
        return {**base, "ok": False, "chamou": True, "motivo": "api",
                "erro": "a TomTom não devolveu rota", **classificar(None)}
    s = rotas[0].get("summary") or {}
    seg = s.get("travelTimeInSeconds")
    if seg is None:
        return {**base, "ok": False, "chamou": True, "motivo": "api",
                "erro": "rota sem tempo de viagem", **classificar(None)}
    chegada = agora.timestamp() + int(seg)
    folga = round((v["previsao"].timestamp() - chegada) / 60.0, 1)
    return {
        **base, "ok": True, "chamou": True,
        "chegada_estimada": datetime.fromtimestamp(chegada).strftime("%Y-%m-%d %H:%M"),
        "minutos_ate_chegar": round(int(seg) / 60.0),
        "folga_min": folga,
        # Quanto do tempo é TRÂNSITO, e não distância. É o número que separa
        # "saiu tarde" de "pegou fila" — dois problemas com donos diferentes.
        "atraso_transito_min": (round(int(s["trafficDelayInSeconds"]) / 60.0)
                                if s.get("trafficDelayInSeconds") is not None
                                else None),
        "km": (round(int(s["lengthInMeters"]) / 1000.0)
               if s.get("lengthInMeters") is not None else None),
        **classificar(folga),
    }


def previsoes(*, forcar: bool = False, agora: datetime | None = None,
              viagens=None, posicoes_atuais=None, so_cache: bool = False) -> dict:
    """Chegada estimada × prometida, para as viagens que ainda dá para salvar.

    `so_cache=True` nunca sai para a rede — mesma trava do snapshot do
    Copiloto: são ~47 chamadas por varredura.
    """
    global _cache
    t = time.monotonic()
    if not forcar and _cache and (t - _cache[0]) < TTL_S:
        return {**_cache[1], "do_cache": True}
    if so_cache:
        return {"configurado": cliente.configurado(), "sem_cache": True,
                "viagens": [], "resumo": _resumo([])}

    with _lock:
        if not forcar and _cache and (time.monotonic() - _cache[0]) < TTL_S:
            return {**_cache[1], "do_cache": True}
        if not cliente.configurado():
            return {"configurado": False, "viagens": [], "resumo": _resumo([]),
                    "mensagem": "Chave da TomTom não configurada "
                                "(Gestão › Integrações)."}

        agora = agora or datetime.now()
        if viagens is None:
            viagens = [dict(r) for r in
                       db.query(VIAGENS_SQL, {"horas": HORIZONTE_H})]
        if posicoes_atuais is None:
            from api import posicoes as _pos
            posicoes_atuais = _pos.atuais()
        mapa = posicoes_atuais.get("posicoes") or {}

        alvos = [(v, mapa[v["placa"]], agora) for v in viagens
                 if v["placa"] in mapa]
        # SEM POSIÇÃO não é "sem atraso": sai da conta e é contado à parte.
        sem_posicao = [v["placa"] for v in viagens if v["placa"] not in mapa]

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=TRABALHADORES) as pool:
            linhas = list(pool.map(_uma, alvos))
        # O CONTADOR MEDIA A COLETA, NAO O CONSUMO — e conflava duas coisas
        # com donos diferentes. `n=len(linhas)` cobrava como chamada a viagem
        # ja VENCIDA (que sai sem perguntar nada, de proposito) e a que nao tem
        # coordenada no ERP; e `erros` somava "a TomTom recusou" com "o cadastro
        # esta incompleto". Medido em 30/08/2026: 295 "chamadas" com 33 "erros"
        # num dia em que boa parte nem tocou na API.
        #
        # E o alarme errado ensina a ignorar o alarme: erro de CADASTRO num
        # painel de integracao manda procurar defeito na integracao.
        chamadas = sum(1 for l in linhas if l.get("chamou"))
        erros_api = sum(1 for l in linhas
                        if not l.get("ok") and l.get("motivo") == "api")
        sem_cadastro = sum(1 for l in linhas if l.get("motivo") == "cadastro")
        coleta.registrar("rota", n=chamadas, erros=erros_api)
        erros = erros_api + sem_cadastro

        fora = {
            "configurado": True,
            "viagens": sorted(linhas, key=lambda l: (
                _PESO.get(l["situacao"], 9), l.get("folga_min") or 0)),
            "resumo": _resumo(linhas),
            "consideradas": len(viagens),
            "consultadas": len(alvos),
            "sem_posicao": sem_posicao,
            "erros": erros,
            # separados na resposta porque os consertos sao em lugares
            # diferentes: um e a TomTom, o outro e o cadastro do ERP
            "erros_api": erros_api,
            "sem_cadastro": sem_cadastro,
            "chamadas": chamadas,
            "horizonte_h": HORIZONTE_H,
            "segundos": round(time.time() - t0, 1),
            "colhido_em": agora.isoformat(timespec="seconds"),
            "do_cache": False,
        }
        _cache = (time.monotonic(), fora)
        return fora


_PESO = {"atrasado": 0, "apertado": 1, "vencida": 2, "no_prazo": 3, "nd": 4}


def _resumo(linhas: list[dict]) -> dict:
    """O DENOMINADOR SÃO AS ESTIMADAS. Contar as sem estimativa como "no
    prazo" diria que está tudo bem por falta de dado."""
    c = {k: 0 for k in _PESO}
    for l in linhas:
        c[l.get("situacao", "nd")] = c.get(l.get("situacao", "nd"), 0) + 1
    # O DENOMINADOR SÃO AS QUE AINDA DÁ PARA SALVAR: as já vencidas saem, e as
    # sem estimativa também. Contá-las diluiria o percentual de risco com casos
    # em que não há decisão a tomar.
    vivas = c["atrasado"] + c["apertado"] + c["no_prazo"]
    atrasos = [l["folga_min"] for l in linhas
               if l.get("folga_min") is not None and l["folga_min"] < 0]
    aprox = sum(1 for l in linhas if l.get("destino_aproximado")
                and l.get("ok"))
    return {"contagem": c, "estimadas": vivas,
            # QUANTAS dependem do centro da cidade em vez do ponto de entrega.
            # Sem este número, um ETA aproximado seria lido como exato.
            "com_destino_aproximado": aprox,
            "sem_estimativa": c["nd"],
            "vencidas": c["vencida"],
            "em_risco": c["atrasado"] + c["apertado"],
            "pct_risco": (round(100.0 * (c["atrasado"] + c["apertado"])
                                / vivas, 1) if vivas else None),
            # O pior caso PREVISTO, em minutos. Só das que ainda não venceram:
            # com as vencidas dentro, este número era -8.702 e não dizia nada.
            "maior_atraso_min": round(min(atrasos)) if atrasos else 0,
            }
