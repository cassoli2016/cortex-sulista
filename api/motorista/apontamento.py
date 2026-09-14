# -*- coding: utf-8 -*-
"""Apontamentos do motorista e a ÚLTIMA posição do celular (fase 2 do app).

Pedido de quem opera em 14/09/2026, com as duas finalidades na mesa: **ver
onde os agregados estão** e **comprovar a chegada e a saída no cliente**. As
decisões foram tomadas junto, e este módulo as executa:

1. **POSIÇÃO SÓ COM O APP ABERTO, E SÓ A ÚLTIMA.** O app é página web: com a
   tela apagada o celular suspende a página, e não há localização em segundo
   plano. Enquanto ele está aberto numa viagem, a página manda a posição a cada
   `INTERVALO_S`; o servidor guarda UMA linha por motorista (a chave de
   `mot_posicoes` é o motorista — não existe trajeto possível) e a apaga quando
   a viagem termina, quando ele sai, quando retira a autorização, e passadas
   `APAGAR_APOS_H` de qualquer jeito. Isto REVÊ o "sem rastreamento contínuo"
   de `docs/APP_MOTORISTA.md` §10 — por escrito lá.
2. **A LOCALIZAÇÃO É OBRIGATÓRIA PARA APONTAR.** Sem a autorização registrada
   (`mot_vinculos.loc_aceite_em`) e sem a coordenada, o apontamento é recusado.
   O resto do app funciona igual.
3. **APONTAMENTO É EVIDÊNCIA, NÃO COBRANÇA.** Não entra nas horas paradas: a
   torre o vê ao lado da ocorrência SAC do ERP (394/395 carregamento, 396/397
   descarga) até se medir quanto um bate com o outro.

A COORDENADA DO APONTAMENTO ENTRA E NÃO FICA — a regra do ponto certificado
(`api/pontocertificado/coleta.py`). Ela decide o veredito da cerca do cliente e
a distância até ela; `mot_apontamentos` não tem coluna de latitude nem de
longitude, e o guard lê o `information_schema`, não o texto do SQL.

A CERCA É A DO ERP. `cadastro_poligono` tipo 1 é o perímetro da planta do
cliente (1.573 clientes); medido em 14/09/2026 sobre as 2.573 viagens de 30
dias: 83% das coletas e 93% das entregas têm cerca. Sem cerca, a reserva é a
coordenada do cadastro (coleta) ou do destino da coleta (entrega), com um raio
DECLARADO (`RAIO_COORDENADA_M`) — e a torre vê qual das duas respondeu. Sem
nenhuma, `sem_cerca`; com o ERP fora do ar, `nao_conferida` — nunca "fora", que
afirmaria o que ninguém conferiu.

O VÉRTICE ESTÁ GRAVADO (LATITUDE, LONGITUDE) no `areapoligono` do ERP — a ordem
inversa da habitual em GIS (ver `api/poligonos/sql.py`). Lido ao contrário, não
dá erro: põe todo mundo "fora", a milhares de quilômetros.

O ACESSO MESTRE NÃO APONTA NEM ENVIA POSIÇÃO. Ele abre a conta de outra pessoa
para CONFERIR; registrar dali gravaria a localização de quem administra como se
fosse a do motorista.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime

from .. import db, pglocal

log = logging.getLogger("cortex.motorista.apontamento")

#: Os quatro apontamentos, na ordem da viagem. A ocorrência SAC do ERP que
#: responde a mesma pergunta vai junto — é por ela que a torre põe os dois lados
#: na mesma linha (`api/horas_paradas/fonte.py` lê as mesmas quatro).
TIPOS = {
    "chegou_coleta":  {"rotulo": "Cheguei para carregar",    "lado": "coleta",  "sac": 394},
    "saiu_coleta":    {"rotulo": "Saí carregado",            "lado": "coleta",  "sac": 395},
    "chegou_entrega": {"rotulo": "Cheguei para descarregar", "lado": "entrega", "sac": 396},
    "saiu_entrega":   {"rotulo": "Terminei a descarga",      "lado": "entrega", "sac": 397},
}

#: Raio em volta da COORDENADA do cliente quando ele não tem cerca no ERP. Não é
#: medida: é a reserva DECLARADA (uma planta industrial de porte médio), e a
#: torre vê "pelo endereço" sempre que foi ela que respondeu.
RAIO_COORDENADA_M = 500

#: A precisão que o celular declara. Acima disto, "dentro ou fora da cerca" vira
#: sorteio — a recusa pede um lugar aberto em vez de gravar veredito sem valor.
MAX_PRECISAO_APONTAMENTO_M = 1000
#: No mapa da torre a pergunta é "em que trecho da rodovia", e cabe mais.
MAX_PRECISAO_POSICAO_M = 5000

INTERVALO_S = 300          # a página manda a posição a cada 5 min
FRESCA_MIN = 120           # a mesma régua de `api/posicoes.FRESCA_MIN`
APAGAR_APOS_H = 24
DIAS_ERP = 60              # janela da programação ao reler a viagem no ERP
LIMITE_TORRE = 500         # linhas na aba da torre (7 dias; hoje, dezenas)

#: Caixa do Brasil com folga. Fora dela é GPS simulado, ou o (0, 0) de aparelho
#: que não achou satélite e respondeu mesmo assim.
_LAT = (-34.5, 5.5)
_LON = (-74.5, -32.0)


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota. Nunca 5xx: o Cloudflare troca o
    corpo de 5xx pela página dele e a mensagem não chega ao motorista."""


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _nao_mestre(sess: dict) -> None:
    if sess.get("mestre"):
        raise Recusa("No acesso de conferência o app não registra apontamento "
                     "nem envia localização.")


def _placa(p: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(p or "").upper())


# ═══════════════════════════════════════════════════════════════ geometria ═══

_NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
_PAR = re.compile(r"\(\s*" + _NUM + r"\s*,\s*" + _NUM + r"\s*\)")


def poligono(texto: str | None) -> list[tuple[float, float]]:
    """O `polygon` do PostgreSQL em texto — `((lat,lon),(lat,lon),...)` — em
    [(lat, lon), ...], NA ORDEM DO ERP (latitude primeiro)."""
    return [(float(a), float(b)) for a, b in _PAR.findall(texto or "")]


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine, em metros."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _plano(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Metros num plano tangente em (lat0, lon0). Na escala de uma planta o erro
    é de centímetros — e é o que permite medir até a ARESTA, não só ao vértice."""
    return ((lon - lon0) * 111320.0 * math.cos(math.radians(lat0)),
            (lat - lat0) * 110574.0)


def dentro(lat: float, lon: float, pts: list[tuple[float, float]]) -> bool:
    """Raio para leste contando cruzamentos com as arestas: ímpar = dentro."""
    ok, j = False, len(pts) - 1
    for i in range(len(pts)):
        (yi, xi), (yj, xj) = pts[i], pts[j]
        if (yi > lat) != (yj > lat):
            if lon < xi + (lat - yi) * (xj - xi) / (yj - yi):
                ok = not ok
        j = i
    return ok


def ate_a_borda_m(lat: float, lon: float, pts: list[tuple[float, float]]) -> float:
    """Distância do ponto até a aresta mais próxima do polígono, em metros."""
    q = [_plano(a, b, lat, lon) for a, b in pts]
    melhor = math.inf
    for i in range(len(q)):
        (x1, y1), (x2, y2) = q[i], q[(i + 1) % len(q)]
        dx, dy = x2 - x1, y2 - y1
        tam = dx * dx + dy * dy
        t = 0.0 if tam == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / tam))
        melhor = min(melhor, math.hypot(x1 + t * dx, y1 + t * dy))
    return melhor


def veredito(lat: float, lon: float, alvo: dict | None) -> dict:
    """Dentro ou fora da cerca do cliente, com a distância e QUEM respondeu.

    `alvo is None` = o ERP não respondeu: `nao_conferida`, nunca "fora".
    """
    if alvo is None:
        return {"cerca": "nao_conferida", "referencia": "", "distancia_m": None}
    pts = alvo.get("poligono") or []
    if len(pts) >= 3:
        if dentro(lat, lon, pts):
            return {"cerca": "dentro", "referencia": "poligono", "distancia_m": 0}
        return {"cerca": "fora", "referencia": "poligono",
                "distancia_m": int(round(ate_a_borda_m(lat, lon, pts)))}
    c = alvo.get("coordenada")
    if c:
        d = distancia_m(lat, lon, c[0], c[1])
        return {"cerca": "dentro" if d <= RAIO_COORDENADA_M else "fora",
                "referencia": "coordenada", "distancia_m": int(round(d))}
    return {"cerca": "sem_cerca", "referencia": "", "distancia_m": None}


def _coord(lat, lon) -> tuple[float, float] | None:
    """Coordenada do cadastro do ERP, ou None. Zero e vazio são AUSÊNCIA — o ERP
    grava 0 onde ninguém geocodificou, e (0, 0) é o golfo da Guiné."""
    try:
        a, b = float(str(lat).strip()), float(str(lon).strip())
    except (TypeError, ValueError):
        return None
    if not (_LAT[0] <= a <= _LAT[1] and _LON[0] <= b <= _LON[1]):
        return None
    return a, b


# ═════════════════════════════════════════════════════════════════════ ERP ═══
# SEM `FILTER`: o AVA é PostgreSQL 9.3. `cast(... AS text)` onde a tabela é de
# terceiro e o tipo pode mudar (a `agrupadorgerencial` trocou de integer para
# varchar em 02/09/2026 e matou cinco telas); a janela de data segura o custo.

_VIAGEM_COLETA = """
FROM programacaoembarque p
JOIN coleta co ON co.grupo = p.grupo AND co.empresa = p.empresa
  AND co.filial = p.filialdocumentoorigem
  AND co.unidade = p.unidadedocumentoorigem
  AND co.diferenciadornumero = p.diferenciadornumerodocumentoorigem
  AND co.numero = p.numerodocumentoorigem"""

ALVO_SQL = """
SELECT (SELECT cast(cp.areapoligono AS text) FROM cadastro_poligono cp
         WHERE cp.tipo = 1
           AND trim(cast(cp.cnpjcpfcodigo AS text)) = trim(cast(co.remetente AS text))
         ORDER BY cp.id LIMIT 1)                        AS pol_coleta,
       (SELECT cast(cp.areapoligono AS text) FROM cadastro_poligono cp
         WHERE cp.tipo = 1
           AND trim(cast(cp.cnpjcpfcodigo AS text)) = trim(cast(co.destinatario AS text))
         ORDER BY cp.id LIMIT 1)                        AS pol_entrega,
       cast(cr.latitude AS text)         AS lat_coleta,
       cast(cr.longitude AS text)        AS lon_coleta,
       cast(co.latitudedestino AS text)  AS lat_entrega,
       cast(co.longitudedestino AS text) AS lon_entrega
""" + _VIAGEM_COLETA + """
LEFT JOIN cadastro cr ON cr.codigo = co.remetente
WHERE trim(cast(p.motorista AS text)) = %(mot)s
  AND cast(p.numero AS text) = %(num)s
  AND p.dtcancelamento IS NULL
  AND p.dtsaida >= current_date - %(dias)s
LIMIT 1
"""

# A PRIMEIRA ocorrência de cada código na ordem de lançamento — a mesma regra
# do Monitoramento SAC que a planilha de horas paradas reproduz.
SAC_SQL = """
SELECT DISTINCT ON (p.numero, p.motorista, oc.ocorrencia)
       cast(p.numero AS text)            AS viagem,
       trim(cast(p.motorista AS text))   AS mot,
       oc.ocorrencia,
       to_char(oc.dtocorrencia, 'YYYY-MM-DD HH24:MI') AS em
""" + _VIAGEM_COLETA + """
JOIN coleta_ocorrencia oc ON oc.grupo = co.grupo AND oc.empresa = co.empresa
  AND oc.filial = co.filial AND oc.unidade = co.unidade
  AND oc.diferenciadornumero = co.diferenciadornumero
  AND oc.serie = co.serie AND oc.numero = co.numero
WHERE cast(p.numero AS text) = ANY(%(nums)s)
  AND trim(cast(p.motorista AS text)) = ANY(%(mots)s)
  AND p.dtcancelamento IS NULL
  AND p.dtsaida >= current_date - %(dias)s
  AND oc.ocorrencia IN (394, 395, 396, 397)
ORDER BY p.numero, p.motorista, oc.ocorrencia, oc.sequenciaocorrencia
"""


def _alvo_do_erp(motorista_codigo: str, numero: str, lado: str) -> dict:
    """A cerca do cliente do `lado` ('coleta' ou 'entrega'). LEVANTA se o ERP
    não responder — quem chama decide que isso é `nao_conferida`."""
    linhas = db.query(ALVO_SQL, {"mot": str(motorista_codigo), "num": str(numero),
                                 "dias": DIAS_ERP})
    if not linhas:
        return {}
    r = linhas[0]
    return {"poligono": poligono(r["pol_" + lado]),
            "coordenada": _coord(r["lat_" + lado], r["lon_" + lado])}


def _sac_do_erp(pares: set[tuple[str, str]]) -> dict[tuple[str, str, int], str]:
    """{(motorista_codigo, viagem, ocorrência): 'AAAA-MM-DD HH:MM'}."""
    if not pares:
        return {}
    linhas = db.query(SAC_SQL, {"nums": sorted({v for _, v in pares}),
                                "mots": sorted({m for m, _ in pares}),
                                "dias": DIAS_ERP})
    return {(r["mot"], r["viagem"], int(r["ocorrencia"])): r["em"]
            for r in linhas if (r["mot"], r["viagem"]) in pares}


def _viagem(sess: dict) -> dict | None:
    """A viagem em curso de quem está logado — a mesma do cartão do app."""
    from . import viagem
    return (viagem.minha(sess) or {}).get("viagem")


# ═══════════════════════════════════════════════════════════ autorização ═══

def aceite(sess: dict, esquema: str | None = None) -> dict:
    r = pglocal.um("SELECT loc_aceite_em FROM mot_vinculos WHERE motorista_codigo = %(m)s",
                   {"m": sess["motorista_codigo"]}, _esq(esquema))
    em = r["loc_aceite_em"] if r else None
    return {"aceita": bool(em), "em": em.isoformat() if em else None}


def autorizar(sess: dict, aceito: bool, esquema: str | None = None) -> dict:
    """Registra (ou retira) a autorização. Retirar APAGA a última posição na
    mesma transação: autorização retirada com a posição ainda no mapa seria a
    retirada que não retirou nada."""
    _nao_mestre(sess)
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        if aceito:
            cur.execute("""UPDATE mot_vinculos SET loc_aceite_em = coalesce(loc_aceite_em, now())
                            WHERE motorista_codigo = %(m)s""", {"m": sess["motorista_codigo"]})
        else:
            cur.execute("UPDATE mot_vinculos SET loc_aceite_em = NULL WHERE motorista_codigo = %(m)s",
                        {"m": sess["motorista_codigo"]})
            cur.execute("DELETE FROM mot_posicoes WHERE motorista_codigo = %(m)s",
                        {"m": sess["motorista_codigo"]})
    return aceite(sess, esquema)


# ════════════════════════════════════════════════════════════ entrada ═══════

def _posicao(dados: dict, max_precisao: int) -> tuple[float, float, int | None]:
    try:
        lat, lon = float(dados.get("lat")), float(dados.get("lon"))
    except (TypeError, ValueError):
        raise Recusa("Não chegou a localização do celular. Tente de novo.") from None
    if not (math.isfinite(lat) and math.isfinite(lon)
            and _LAT[0] <= lat <= _LAT[1] and _LON[0] <= lon <= _LON[1]):
        raise Recusa("A localização recebida não é válida. Tente de novo.")
    prec = dados.get("precisao")
    try:
        prec = int(round(float(prec))) if prec is not None else None
    except (TypeError, ValueError):
        prec = None
    if prec is not None and prec > max_precisao:
        raise Recusa("A localização está imprecisa (±%d m). Vá para um lugar "
                     "aberto e tente de novo." % prec)
    return lat, lon, prec


def _quando(txt) -> datetime | None:
    """A hora do APARELHO, ou None. Ilegível não recusa o apontamento: ela é
    explicação, não decisão (quem decide é a do servidor)."""
    try:
        d = datetime.fromisoformat(str(txt).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else None


def _gravar_posicao(cur, sess: dict, viagem: str, placa: str, lat: float,
                    lon: float, prec: int | None, em_ap: datetime | None) -> None:
    cur.execute(
        """INSERT INTO mot_posicoes (motorista_codigo, viagem, placa, lat, lon,
                                     precisao_m, em_aparelho, em_servidor)
                VALUES (%(m)s, %(v)s, %(p)s, %(lat)s, %(lon)s, %(prec)s, %(ap)s, now())
           ON CONFLICT (motorista_codigo) DO UPDATE SET
                viagem = EXCLUDED.viagem, placa = EXCLUDED.placa,
                lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                precisao_m = EXCLUDED.precisao_m, em_aparelho = EXCLUDED.em_aparelho,
                em_servidor = now()""",
        {"m": sess["motorista_codigo"], "v": viagem, "p": _placa(placa),
         "lat": lat, "lon": lon, "prec": prec, "ap": em_ap})


# ═════════════════════════════════════════════════════════════ apontar ══════

def registrar(sess: dict, dados: dict, esquema: str | None = None) -> dict:
    """Grava UM apontamento da viagem em curso. Levanta `Recusa`."""
    _nao_mestre(sess)
    tipo = str(dados.get("tipo") or "")
    if tipo not in TIPOS:
        raise Recusa("Apontamento desconhecido.")
    if not aceite(sess, esquema)["aceita"]:
        raise Recusa("Autorize a localização para registrar a chegada e a saída.")
    lat, lon, prec = _posicao(dados, MAX_PRECISAO_APONTAMENTO_M)
    v = _viagem(sess)
    if not v:
        raise Recusa("Você não tem viagem em curso agora.")
    if v.get("vazio"):
        raise Recusa("Viagem vazia não tem carregamento nem descarga para registrar.")
    numero = str(v.get("numero") or "")
    try:
        alvo = _alvo_do_erp(sess["motorista_codigo"], numero, TIPOS[tipo]["lado"])
    except Exception as exc:  # noqa: BLE001
        log.warning("apontamento: cerca do cliente indisponivel (%s)", type(exc).__name__)
        alvo = None
    ver = veredito(lat, lon, alvo)
    em_ap = _quando(dados.get("em_aparelho"))
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO mot_apontamentos (motorista_codigo, viagem, placa, tipo,
                                             em_aparelho, cerca, referencia,
                                             distancia_m, precisao_m)
                    VALUES (%(m)s, %(v)s, %(p)s, %(t)s, %(ap)s, %(c)s, %(r)s, %(d)s, %(prec)s)
               ON CONFLICT (motorista_codigo, viagem, tipo) DO NOTHING
               RETURNING to_char(em_servidor, 'YYYY-MM-DD HH24:MI') AS em""",
            {"m": sess["motorista_codigo"], "v": numero, "p": _placa(v.get("placa")),
             "t": tipo, "ap": em_ap, "c": ver["cerca"], "r": ver["referencia"],
             "d": ver["distancia_m"], "prec": prec})
        novo = cur.fetchone()
        if not novo:
            cur.execute("""SELECT to_char(em_servidor, 'DD/MM HH24:MI') AS h
                             FROM mot_apontamentos
                            WHERE motorista_codigo = %(m)s AND viagem = %(v)s AND tipo = %(t)s""",
                        {"m": sess["motorista_codigo"], "v": numero, "t": tipo})
            antes = cur.fetchone()
            raise Recusa("“%s” já foi registrado nesta viagem (%s)."
                         % (TIPOS[tipo]["rotulo"], antes["h"] if antes else "antes"))
        # O apontamento É uma posição fresca — e para a torre ela vale mais que
        # a de cinco minutos atrás.
        _gravar_posicao(cur, sess, numero, v.get("placa"), lat, lon, prec, em_ap)
    return {"tipo": tipo, "rotulo": TIPOS[tipo]["rotulo"], "viagem": numero,
            "em": novo["em"], **ver}


def da_viagem(sess: dict, numero: str, esquema: str | None = None) -> list[dict]:
    """Os QUATRO apontamentos da viagem, na ordem, feitos ou não — o rótulo sai
    daqui para a página e o painel dizerem a mesma coisa."""
    feitos = {r["tipo"]: r for r in pglocal.query(
        """SELECT tipo, to_char(em_servidor, 'YYYY-MM-DD HH24:MI') AS em,
                  cerca, referencia, distancia_m
             FROM mot_apontamentos
            WHERE motorista_codigo = %(m)s AND viagem = %(v)s""",
        {"m": sess["motorista_codigo"], "v": str(numero)}, _esq(esquema))}
    saida = []
    for t, d in TIPOS.items():
        f = feitos.get(t)
        item = {"tipo": t, "rotulo": d["rotulo"], "feito": bool(f)}
        if f:
            item.update({"em": f["em"], "cerca": f["cerca"],
                         "referencia": f["referencia"], "distancia_m": f["distancia_m"]})
        saida.append(item)
    return saida


# ═════════════════════════════════════════════════════ a última posição ═════

def posicao(sess: dict, dados: dict, esquema: str | None = None) -> dict:
    """A posição periódica do app aberto. Sem viagem, APAGA e manda parar."""
    _nao_mestre(sess)
    if not aceite(sess, esquema)["aceita"]:
        raise Recusa("A localização não está autorizada neste app.")
    lat, lon, prec = _posicao(dados, MAX_PRECISAO_POSICAO_M)
    v = _viagem(sess)
    if not v:
        apagar_posicao(sess["motorista_codigo"], esquema)
        return {"viagem": False}
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        _gravar_posicao(cur, sess, str(v.get("numero") or ""), v.get("placa"),
                        lat, lon, prec, _quando(dados.get("em_aparelho")))
    return {"viagem": True, "proxima_s": INTERVALO_S}


def apagar_posicao(motorista_codigo: str, esquema: str | None = None) -> None:
    pglocal.executar("DELETE FROM mot_posicoes WHERE motorista_codigo = %(m)s",
                     {"m": motorista_codigo}, _esq(esquema))


def posicoes_celular(placas: set[str], esquema: str | None = None) -> list[dict]:
    """As posições de celular FRESCAS das placas em viagem, para o mapa da torre.

    Antes de ler, apaga o que passou de `APAGAR_APOS_H` — a regra de retenção
    roda no caminho de quem lê, e não numa rotina que um dia deixa de rodar.
    """
    esq = _esq(esquema)
    pglocal.executar("DELETE FROM mot_posicoes WHERE em_servidor < now() - make_interval(hours => %(h)s)",
                     {"h": APAGAR_APOS_H}, esq)
    alvo = {_placa(p) for p in placas if p}
    if not alvo:
        return []
    linhas = pglocal.query(
        """SELECT placa, lat, lon, precisao_m,
                  to_char(em_servidor, 'YYYY-MM-DD HH24:MI') AS em,
                  floor(extract(epoch FROM now() - em_servidor) / 60)::int AS idade_min
             FROM mot_posicoes
            WHERE em_servidor > now() - make_interval(mins => %(f)s)""",
        {"f": FRESCA_MIN}, esq)
    return [{"placa": _placa(r["placa"]), "lat": float(r["lat"]), "lng": float(r["lon"]),
             "precisao_m": r["precisao_m"], "posicao_em": r["em"],
             "idade_min": int(r["idade_min"]), "fonte": "celular do motorista"}
            for r in linhas if _placa(r["placa"]) in alvo]


# ═══════════════════════════════════════════════════════════════ a torre ═════

def _dif_min(a: str | None, b: str | None) -> int | None:
    """`a − b` em minutos, entre dois 'AAAA-MM-DD HH:MM' do mesmo fuso."""
    if not a or not b:
        return None
    f = "%Y-%m-%d %H:%M"
    return int((datetime.strptime(a, f) - datetime.strptime(b, f)).total_seconds() // 60)


def para_torre(dias: int = 7, esquema: str | None = None) -> dict:
    """Os apontamentos recentes, cada um ao lado da ocorrência SAC do ERP.

    O `motorista_codigo` NÃO SAI daqui: para pessoa física ele é o CPF. A linha
    leva o nome do vínculo, que é o que a torre já mostra nas viagens.
    """
    dias = max(1, min(30, int(dias or 7)))
    linhas = pglocal.query(
        """SELECT a.motorista_codigo, a.viagem, a.placa, a.tipo, a.cerca,
                  a.referencia, a.distancia_m, a.precisao_m,
                  to_char(a.em_servidor, 'YYYY-MM-DD HH24:MI') AS em,
                  round(extract(epoch FROM a.em_aparelho - a.em_servidor) / 60) AS dif_ap,
                  coalesce(v.nome, '') AS motorista
             FROM mot_apontamentos a
             LEFT JOIN mot_vinculos v ON v.motorista_codigo = a.motorista_codigo
            WHERE a.em_servidor > now() - make_interval(days => %(d)s)
            ORDER BY a.em_servidor DESC
            LIMIT %(lim)s""", {"d": dias, "lim": LIMITE_TORRE}, _esq(esquema))
    erp, erp_ok = {}, True
    if linhas:
        try:
            erp = _sac_do_erp({(r["motorista_codigo"], r["viagem"]) for r in linhas})
        except Exception as exc:  # noqa: BLE001
            # ERP fora do ar: a coluna vira "não sei", nunca "sem registro" —
            # zero afirmaria que alguém conferiu e o ERP não tinha nada.
            log.warning("torre: ocorrencias SAC indisponiveis (%s)", type(exc).__name__)
            erp_ok = False
    itens = []
    for r in linhas:
        erp_em = erp.get((r["motorista_codigo"], r["viagem"], TIPOS[r["tipo"]]["sac"]))
        itens.append({
            "em": r["em"], "motorista": r["motorista"], "placa": r["placa"],
            "viagem": r["viagem"], "tipo": r["tipo"], "rotulo": TIPOS[r["tipo"]]["rotulo"],
            "cerca": r["cerca"], "referencia": r["referencia"],
            "distancia_m": r["distancia_m"], "precisao_m": r["precisao_m"],
            "aparelho_dif_min": int(r["dif_ap"]) if r["dif_ap"] is not None else None,
            "erp_em": erp_em, "erp_dif_min": _dif_min(r["em"], erp_em),
        })
    cont = Counter(i["cerca"] for i in itens)
    return {"itens": itens, "janela_dias": dias, "limite": LIMITE_TORRE,
            "erp_ok": erp_ok,
            "resumo": {"total": len(itens), "dentro": cont["dentro"], "fora": cont["fora"],
                       "sem_cerca": cont["sem_cerca"],
                       "nao_conferida": cont["nao_conferida"],
                       "com_erp": sum(1 for i in itens if i["erp_em"])},
            "raio_coordenada_m": RAIO_COORDENADA_M,
            "fonte": "app do motorista (mot_apontamentos) × ERP AVA · coleta_ocorrencia 394–397"}


def contagem(esquema: str | None = None) -> dict:
    """Só contagens — para a Saúde do Servidor e o snapshot do Copiloto."""
    r = pglocal.um(
        """SELECT (SELECT count(*) FROM mot_apontamentos
                    WHERE em_servidor > now() - interval '7 days') AS ap_7d,
                  (SELECT count(*) FROM mot_apontamentos
                    WHERE em_servidor > now() - interval '7 days' AND cerca = 'dentro') AS dentro_7d,
                  (SELECT count(*) FROM mot_apontamentos
                    WHERE em_servidor > now() - interval '7 days' AND cerca = 'fora') AS fora_7d,
                  (SELECT count(*) FROM mot_posicoes
                    WHERE em_servidor > now() - interval '120 minutes') AS posicoes_frescas,
                  (SELECT count(*) FROM mot_vinculos
                    WHERE ativo AND loc_aceite_em IS NOT NULL) AS autorizados,
                  (SELECT max(em_servidor) FROM mot_apontamentos) AS ultimo""",
        None, _esq(esquema)) or {}
    return {k: (int(r.get(k) or 0)) for k in ("ap_7d", "dentro_7d", "fora_7d",
                                              "posicoes_frescas", "autorizados")} | {
        "ultimo": r.get("ultimo")}
