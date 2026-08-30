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


def _get(caminho: str, params: dict) -> dict:
    """GET com a chave anexada. Levanta `TomTomIndisponivel` já sanitizado."""
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


def fluxo(lat: float, lon: float, zoom: int = 10) -> dict:
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


def rota(origem: tuple[float, float], destino: tuple[float, float],
         *, caminhao: bool = True) -> dict:
    """Tempo até o destino COM o trânsito do momento.

    `travelMode=truck` muda a rota de verdade (restrição de via, altura, peso),
    e não só o tempo. Se o plano não liberar, a API recusa — e é isso que o
    script de descoberta mede, em vez de este módulo afirmar.
    """
    pontos = "%s,%s:%s,%s" % (origem[0], origem[1], destino[0], destino[1])
    p = {"traffic": "true", "routeType": "fastest", "computeTravelTimeFor": "all"}
    if caminhao:
        p["travelMode"] = "truck"
    return _get("/routing/1/calculateRoute/%s/json" % pontos, p)
