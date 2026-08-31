"""Cliente da API da TomTom — trânsito, incidentes e ETA.

A CHAVE VAI NA URL, E ISSO MUDA O QUE PODE SER REGISTRADO
========================================================
Gobrax, Monkey e Prolog mandam token em CABEÇALHO — registrar a URL era
inofensivo. A TomTom é `?key=...`: a **URL é a credencial**, exatamente como na
Z-API. `str(exc)` de `urllib` traz a URL, e a mensagem de erro vai para a tela,
para o log e para a trilha. Nada aqui devolve exceção crua: tudo passa por
`_sanitizar`, e há teste reproduzindo o `URLError` com a URL dentro.

DUAS CHAVES, E O MOTIVO É UMA ARMADILHA
=======================================
O overlay de trânsito dos painéis carrega os tiles DIRETO do navegador (proxiar
tile é caro), então a chave dele é pública por construção e a defesa é
restringi-la por domínio no painel da TomTom — que é o que o código do overlay
já recomendava.

Só que **chave restrita por domínio não funciona chamada pelo servidor**: a
coleta volta 403, e 403 lê-se como "chave errada", mandando conferir o que está
certo. Daí `TOMTOM_API_KEY_SERVIDOR`, opcional: sem ela a coleta usa a do mapa
e o diagnóstico DIZ que, se aquela estiver restrita, vai falhar por isso — em
vez de deixar a pessoa descobrir pelo 403.

O QUE ESTE MÓDULO NÃO FAZ
=========================
Não afirma o que o plano gratuito inclui. `scripts/tomtom_descobrir.py` PERGUNTA
à API com a chave real e imprime o que cada recurso respondeu — inclusive o
limite, que só aparece nos cabeçalhos da resposta. Escrever aqui "o gratuito dá
2.500 chamadas/dia" seria repetir documentação que envelhece; a lição dos
"~17 s por chamada" da Gobrax, que estavam 20x errados num comentário, é
recente.

TUDO AQUI É LEITURA. Nenhum endpoint desta API muda estado do lado deles, e
nenhum deve ser acrescentado sem isso valer: a lição do `/api/v2/drivers` da
Gobrax, que era um endpoint de ESCRITA sondado por engano, custou um susto.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from api import credenciais, tls as _tls

log = logging.getLogger(__name__)

BASE = "https://api.tomtom.com"
TIMEOUT = 20


class TomTomNaoConfigurado(Exception):
    """Sem chave. NÃO é falha: é instalação incompleta, e a Saúde marca `info`
    dizendo qual campo falta. Vermelho aqui ensinaria a ignorar o vermelho."""


class TomTomIndisponivel(Exception):
    """A API não respondeu, ou respondeu erro. A mensagem já vem sanitizada."""


def chave_mapa() -> str | None:
    """A que vai para o NAVEGADOR. Cofre primeiro, ambiente depois — é o que
    `credenciais.ler` faz, e é a mesma ordem do resto da casa."""
    return credenciais.ler("TOMTOM_API_KEY")


def chave_servidor() -> str | None:
    """A que o CÓRTEX usa. Cai na do mapa quando não há uma própria."""
    return credenciais.ler("TOMTOM_API_KEY_SERVIDOR") or chave_mapa()


def configurado() -> bool:
    return bool(chave_servidor())


def usando_a_chave_do_mapa() -> bool:
    """True quando a coleta está usando a chave pública. Não é erro — mas é o
    que explica um 403 quando ela estiver restrita por domínio, e por isso a
    tela precisa poder dizer isso ANTES de o 403 aparecer."""
    return bool(chave_mapa()) and not credenciais.ler("TOMTOM_API_KEY_SERVIDOR")


def _sanitizar(texto) -> str:
    """Tira as DUAS chaves de qualquer texto que vá para tela, log ou trilha.

    As duas sempre, não só a da vez: com dois valores possíveis o mesmo texto
    passa por caminhos diferentes, e limpar só um é a brecha que ninguém
    revisaria. E o `key=` genérico fica como rede embaixo, para o caso de a URL
    trazer uma chave que este processo não conhece.
    """
    fora = str(texto or "")
    for k in (credenciais.ler("TOMTOM_API_KEY_SERVIDOR"), chave_mapa()):
        if k and len(k) >= 8:
            fora = fora.replace(k, "***")
    return _mascarar_key_na_url(fora)


def _mascarar_key_na_url(texto: str) -> str:
    """`?key=<qualquer coisa>` vira `?key=***`.

    Existe porque `_sanitizar` só conhece as chaves DESTE processo. Uma URL
    montada com outra chave (teste, ambiente errado, chave de outra conta)
    passaria inteira — e o vazamento que importa é justamente o que ninguém
    previu.
    """
    fora, i = texto, 0
    while True:
        i = fora.lower().find("key=", i)
        if i < 0:
            return fora
        j = i + 4
        fim = len(fora)
        for k in range(j, len(fora)):
            if fora[k] in "&\" '\n\t>":
                fim = k
                break
        if fim > j:
            fora = fora[:j] + "***" + fora[fim:]
            i = j + 3
        else:
            i = j


# LIMITE DE TAXA: EXISTE, É POR FAMÍLIA DE ENDPOINT, E SÓ APARECE COMO RECUSA.
#
# Eu tinha registrado que "o limite não é observável" porque nenhuma resposta
# traz cabeçalho de cota. Estava incompleto: ele aparece como **HTTP 429**
# depois de estourado, e — o que muda o desenho — **cada família tem o seu**.
# Medido em 30/08/2026, 12 chamadas por rodada:
#
#     rota   1 trab. → 1,1 req/s  ok
#            3 trab. → 3,2 req/s  ok
#            6 trab. → 6,5 req/s  **2 de 12 com 429**
#     fluxo  6 trab. → 13,8 req/s ok
#
# Ou seja: o Traffic aguenta o dobro do Routing. Uma varredura de ETA com os
# mesmos 8 trabalhadores do fluxo perdeu 15 de 47 chamadas — 32% de buraco na
# tela, que apareceria como "sem estimativa" e passaria por falta de cadastro.
#
# 30 chamadas EM SÉRIE não batem no limite. Não é cota diária: é ritmo.
RETENTATIVA_429_S = 1.5


def _get(caminho: str, params: dict, _tentativa: int = 0) -> dict:
    """GET com a chave anexada. Levanta `TomTomIndisponivel` já sanitizado.

    UMA retentativa no 429, e só uma: o limite é de ritmo, então esperar um
    segundo e meio resolve o caso normal (um pico de concorrência). Insistir
    além disso transformaria um freio do fornecedor numa fila nossa, e a tela
    ficaria esperando em vez de dizer o que já sabe.
    """
    k = chave_servidor()
    if not k:
        raise TomTomNaoConfigurado(
            "Chave da TomTom não configurada — Gestão › Integrações › TomTom.")
    url = "%s%s?%s" % (BASE, caminho,
                       urllib.parse.urlencode({**params, "key": k}))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_tls.contexto()) as r:
            bruto = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        corpo = ""
        try:
            corpo = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        # 403 com a chave do mapa é o caso previsível, e a mensagem tem de
        # dizer isso: senão manda conferir uma chave que está correta.
        extra = ""
        if exc.code == 403 and usando_a_chave_do_mapa():
            extra = (" — a coleta está usando a chave do MAPA; se ela estiver "
                     "restrita por domínio no painel da TomTom, o servidor não "
                     "pode usá-la. Configure a chave da coleta.")
        if exc.code == 429 and _tentativa == 0:
            time.sleep(RETENTATIVA_429_S)
            return _get(caminho, params, _tentativa + 1)
        if exc.code == 429:
            extra = (" — é limite de RITMO, não de cota diária: o Routing "
                     "aguenta menos que o Traffic (medido: 429 a partir de "
                     "~6 req/s contra ~14). Reduza os trabalhadores.")
        raise TomTomIndisponivel(
            "A TomTom respondeu HTTP %s.%s %s"
            % (exc.code, extra, _sanitizar(corpo))) from None
    except (urllib.error.URLError, OSError) as exc:
        raise TomTomIndisponivel(
            "Não foi possível falar com a TomTom (%s)." % type(exc).__name__
        ) from None
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        raise TomTomIndisponivel(
            "A TomTom respondeu algo que não é JSON.") from None


# ── trânsito no ponto ────────────────────────────────────────────────────────


# ZOOM 14, E ISSO É CORREÇÃO DE MEDIDA, NÃO PREFERÊNCIA.
#
# O `zoom` define o TAMANHO DO TRECHO que a API agrega. Medido em 30/08/2026,
# no mesmo ponto:
#
#     zoom 10 → trecho de 1.293 s (~21 min de estrada), 766 pontos,
#               30/38 km/h, roadClosure = TRUE
#     zoom 14 → trecho de   112 s (~2 min), 45 pontos,
#               27/27 km/h, roadClosure = FALSE
#
# Ou seja: em zoom 10 a leitura era de dezenas de quilômetros de rodovia e
# HERDAVA um bloqueio que estava longe do caminhão. Quatro dos cinco "problemas"
# da primeira varredura da frota eram isso — 80% de falso positivo, com os
# veículos ANDANDO a 28–30 km/h numa via marcada como fechada.
#
# E a prova de que não é o zoom "escondendo" problema: o veículo com
# congestionamento de verdade (23 km/h onde o livre é 80) aparece IGUAL em
# todos os zooms. O zoom alto tira o ruído distante, não o fato local.
ZOOM = 14


def fluxo(lat: float, lon: float, zoom: int = ZOOM) -> dict:
    """Velocidade atual × de fluxo livre no trecho onde está aquele ponto.

    É o que responde "a estrada onde este caminhão está agora está livre?".
    Devolve o bruto da API; quem interpreta é `api/tomtom/transito.py` — misturar
    leitura e regra faz a regra virar refém do formato do fornecedor.
    """
    return _get("/traffic/services/4/flowSegmentData/absolute/%d/json" % zoom,
                {"point": "%s,%s" % (lat, lon), "unit": "KMPH"})


# MEDIDO em 30/08/2026, não lido em documentação: a API RECUSA `pt-BR` e
# `pt` com HTTP 400 ("Unsupported language parameter value"). O único
# português aceito é `pt-PT`. Uma constante nomeada porque o valor "óbvio" é o
# errado, e quem for ajustar isso vai tentar `pt-BR` primeiro.
IDIOMA = "pt-PT"


def incidentes(sul: float, oeste: float, norte: float, leste: float,
               idioma: str = IDIOMA) -> dict:
    """Obra, acidente, bloqueio e lentidão dentro de uma caixa geográfica.

    A ordem do `bbox` da TomTom é `oeste,sul,leste,norte` (lon,lat,lon,lat) —
    trocar lat com lon devolve uma caixa no meio do oceano e ZERO incidentes,
    que é indistinguível de "não há incidente". Os parâmetros aqui são nomeados
    por isso.
    """
    campos = ("{incidents{type,geometry{type,coordinates},"
              "properties{iconCategory,magnitudeOfDelay,events{description,code},"
              "startTime,endTime,from,to,length,delay,roadNumbers}}}")
    return _get("/traffic/services/5/incidentDetails",
                {"bbox": "%s,%s,%s,%s" % (oeste, sul, leste, norte),
                 "fields": campos, "language": idioma,
                 "categoryFilter": "0,1,2,3,4,5,6,7,8,9,10,11,14",
                 "timeValidityFilter": "present"})


def geocodificar(cidade: str, uf: str = "") -> dict | None:
    """Cidade/UF → coordenada. `None` quando a TomTom não resolve.

    `countrySet=BR` é o que impede a resposta certa para a pergunta errada:
    sem ele, "IMIGRANTE/RS" pode voltar como um lugar em outro país com nome
    parecido, e o ETA sairia calculado para o outro lado do mundo sem que nada
    reclamasse.

    `limit=1` porque quem chama quer UM ponto; ranquear alternativas seria
    inventar critério que não temos.
    """
    consulta = (cidade + (", " + uf if uf else "") + ", Brasil").strip()
    d = _get("/search/2/geocode/%s.json" % urllib.parse.quote(consulta),
             {"countrySet": "BR", "limit": 1})
    res = (d.get("results") or [])
    if not res:
        return None
    pos = res[0].get("position") or {}
    if pos.get("lat") is None or pos.get("lon") is None:
        return None
    return {"lat": float(pos["lat"]), "lon": float(pos["lon"]),
            "rotulo": (res[0].get("address") or {}).get("freeformAddress")}


# PERFIL DA CARRETA PADRAO DA CASA. Bitrem/carreta de 6 eixos: 40 t de PBT,
# 18,6 m, 4,40 m de altura, 90 km/h de velocidade máxima regulada.
#
# POR QUE ISTO NAO E ENFEITE, e a medição está aqui porque comentário de
# desempenho envelhece (esta casa já descartou um caminho por uma premissa 20x
# errada num comentário). Medido em 30/08/2026, mesma origem e destino, só
# `travelMode=truck` contra o perfil completo:
#
#   Joinville -> Curitiba      132,6 km / 121 min   ->   133,2 / 126   (+5 min)
#   Joinville -> São Paulo     520,9 / 448          ->   521,2 / 468   (+20 min)
#   Curitiba -> Pouso Alegre   616,7 / 586          ->   622,1 / 601   (+15 min)
#   Joinville -> Betim/MG     1081,2 / 868          ->  1081,8 / 896   (+28 min)
#
# São 5 a 28 minutos, num painel cujo limiar de "chegada apertada" é 15. Sem os
# parâmetros o ETA é sistematicamente OTIMISTA, e o erro cai justamente no lado
# que faz a torre não avisar.
#
# O perfil é FIXO e isso é uma escolha declarada: o ERP tem os dados por
# veículo, mas ligá-los aqui é outro trabalho. Fixo, ele erra para o lado da
# chegada MAIS TARDE num caminhão menor — que é o erro seguro num painel de
# risco de atraso. A tela diz que o cálculo usa a carreta padrão.
CARRETA_PADRAO = {
    "vehicleCommercial": "true",
    "vehicleWeight": 40000,       # PBT em kg
    "vehicleAxleWeight": 10000,   # kg por eixo
    "vehicleNumberOfAxles": 6,
    "vehicleLength": 18.6,
    "vehicleWidth": 2.6,
    "vehicleHeight": 4.4,
    "vehicleMaxSpeed": 90,
}


def rota(origem: tuple[float, float], destino: tuple[float, float],
         *, caminhao: bool = True, perfil: dict | None = None) -> dict:
    """Tempo até o destino COM o trânsito do momento.

    `travelMode=truck` sozinho muda pouco; o que muda a ROTA de verdade —
    restrição de via, ponte, altura, peso por eixo — é o PERFIL do veículo.
    Ver `CARRETA_PADRAO` para a medição que justifica mandá-lo.

    `perfil={}` volta ao comportamento antigo (só o modo), para quem quiser
    comparar.
    """
    pontos = "%s,%s:%s,%s" % (origem[0], origem[1], destino[0], destino[1])
    p = {"traffic": "true", "routeType": "fastest", "computeTravelTimeFor": "all"}
    if caminhao:
        p["travelMode"] = "truck"
        p.update(CARRETA_PADRAO if perfil is None else perfil)
    return _get("/routing/1/calculateRoute/%s/json" % pontos, p)
