"""Onde cada veículo está AGORA — juntando as duas fontes que a casa tem.

O QUE FOI MEDIDO (30/08/2026, 16h)
=================================
Havia a impressão de que a Gobrax era a fonte de posição e o rastreamento do
ERP seria um reforço. Os números dizem outra coisa:

    só na Gobrax .....    1 placa
    só no ERP ....... .. 177 placas
    nas duas .........   97 placas
    união ............  275 placas

E o frescor EMPATA: nas 97 que aparecem nas duas, a idade mediana da posição é
5 min na Gobrax e 4 min no ERP, com a Gobrax mais recente em 44% dos casos.

Ou seja: **o ERP não é o plano B, é a maior cobertura** — e a Gobrax acrescenta
exatamente UMA placa. São caminhos diferentes para o mesmo mundo: a Gobrax lê o
equipamento próprio dela; o ERP recebe do hub da Raster, que agrega ONIXSAT,
SASCAR, POSITRON e OMNILINK.

A REGRA QUE SAIU DISSO
======================
Vence a posição **MAIS RECENTE**, não uma fonte fixa. Precedência fixa por
Gobrax descartaria a leitura mais nova em 56% das placas que existem nas duas,
sem ganhar cobertura nenhuma — o resultado seria o mesmo conjunto de 275, só
que com posição mais velha. Quem quiser a precedência literal tem
`preferir="gobrax"`.

TODA POSIÇÃO DIZ DE ONDE VEIO E QUE IDADE TEM. Um mapa que mistura fontes sem
dizer qual é qual transforma "a Gobrax está fora" em "a frota sumiu" — e é
exatamente o tipo de coisa que esta casa já viu virar alarme falso.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from api import db

log = logging.getLogger(__name__)

# Acima disto a posição não responde "onde está agora". Não é descarte: a
# posição continua vindo, marcada como velha — sumir com ela faria o veículo
# desaparecer do mapa, que é pior que mostrá-lo com a idade à mostra.
FRESCA_MIN = 120

ERP_SQL = """
SELECT upper(trim(um.veiculo))                    AS placa,
       vp.latituderastreadora::float8             AS lat,
       vp.longituderastreadora::float8            AS lon,
       vp.dt                                      AS quando,
       greatest(coalesce(vp.velocidade,0),0)::int AS velocidade
  FROM rastreamento.veiculo_ultimaposicaomacro um
  JOIN veiculo_posicao vp
    ON vp.veiculo = um.veiculo
   AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
 WHERE vp.latituderastreadora IS NOT NULL
   AND vp.longituderastreadora IS NOT NULL
"""


def _idade_min(quando: datetime, agora: datetime) -> float | None:
    if not isinstance(quando, datetime):
        return None
    # A Gobrax devolve data COM fuso e o ERP sem. Subtrair um do outro estoura
    # `TypeError`, e o ramo que estoura é o que só acontece com uma das fontes
    # — o tipo de defeito que passa em teste e aparece em produção.
    if quando.tzinfo is not None:
        quando = quando.replace(tzinfo=None)
    return round((agora - quando).total_seconds() / 60.0, 1)


def do_erp(agora: datetime | None = None) -> dict[str, dict]:
    """Última posição de cada placa no rastreamento do ERP."""
    agora = agora or datetime.now()
    fora: dict[str, dict] = {}
    for r in db.query(ERP_SQL):
        placa = r["placa"]
        if not placa:
            continue
        fora[placa] = {"placa": placa, "lat": r["lat"], "lon": r["lon"],
                       "quando": r["quando"], "velocidade": r["velocidade"],
                       "fonte": "erp",
                       "idade_min": _idade_min(r["quando"], agora)}
    return fora


def da_gobrax(cliente=None, agora: datetime | None = None) -> dict[str, dict]:
    """Última posição de cada placa na Gobrax.

    NÃO reaproveita `gobrax.comunicacao.coletar`, e não é duplicação: aquele
    módulo joga LAT E LON FORA de propósito — ele responde "há quanto tempo
    esta placa não comunica", e para isso a coordenada é peso morto. Aqui a
    coordenada é o produto.
    """
    from api.gobrax import cliente as gbx
    from api.gobrax.comunicacao import CAMINHO, _quando, periodo_api

    agora = agora or datetime.now()
    if not gbx.configurado():
        return {}
    c = cliente or gbx.Cliente()
    hoje = agora.date()
    ini, fim = periodo_api(hoje - timedelta(days=2), hoje)
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim}, timeout=180)
    fora: dict[str, dict] = {}
    for v in (corpo.get("data") or []):
        placa = (v.get("identification") or "").strip().upper()
        if not placa:
            continue
        melhor = None
        for p in (v.get("positions") or []):
            d = _quando(p.get("date"))
            if d and (melhor is None or d > melhor[0]):
                melhor = (d, p)
        if not melhor:
            continue
        d, p = melhor
        if p.get("lat") is None or p.get("lon") is None:
            continue
        fora[placa] = {"placa": placa, "lat": float(p["lat"]),
                       "lon": float(p["lon"]), "quando": d,
                       "velocidade": int(p.get("speed") or 0),
                       "fonte": "gobrax", "idade_min": _idade_min(d, agora)}
    return fora


def atuais(cliente=None, agora: datetime | None = None,
           preferir: str = "recente") -> dict:
    """As duas fontes juntas, com a procedência de cada placa.

    `preferir`:
      "recente" (padrão) — vence a leitura mais nova. Medido: precedência fixa
                           por Gobrax descartaria a posição mais recente em 56%
                           das placas que existem nas duas, sem ganhar
                           cobertura nenhuma.
      "gobrax"           — precedência literal: Gobrax quando houver, ERP no
                           resto. Fica disponível porque a escolha é de quem
                           opera, não do código.

    FALHA DE UMA FONTE NÃO DERRUBA A OUTRA. Com a Gobrax fora, o mapa continua
    com as 274 do ERP e o payload DIZ que a Gobrax não respondeu — em vez de a
    tela parecer uma frota que sumiu.
    """
    agora = agora or datetime.now()
    erp, gob = {}, {}
    falhas = []
    try:
        erp = do_erp(agora)
    except Exception as exc:  # noqa: BLE001
        falhas.append("erp")
        log.warning("posições do ERP indisponíveis: %s", type(exc).__name__)
    try:
        gob = da_gobrax(cliente, agora)
    except Exception as exc:  # noqa: BLE001
        falhas.append("gobrax")
        log.warning("posições da Gobrax indisponíveis: %s", type(exc).__name__)

    fora: dict[str, dict] = dict(erp)
    for placa, p in gob.items():
        atual = fora.get(placa)
        if atual is None:
            fora[placa] = p
        elif preferir == "gobrax":
            fora[placa] = p
        elif (p["quando"].replace(tzinfo=None) if p["quando"].tzinfo
              else p["quando"]) > (atual["quando"].replace(tzinfo=None)
                                   if atual["quando"].tzinfo else atual["quando"]):
            fora[placa] = p

    por_fonte = {"erp": 0, "gobrax": 0}
    frescas = 0
    for p in fora.values():
        por_fonte[p["fonte"]] = por_fonte.get(p["fonte"], 0) + 1
        if p["idade_min"] is not None and p["idade_min"] <= FRESCA_MIN:
            frescas += 1
    return {
        "posicoes": fora,
        "total": len(fora),
        "frescas": frescas,
        "por_fonte": por_fonte,
        # O que CADA fonte tinha, e não só quem venceu: é o que permite ver a
        # Gobrax encolher sem que o total mude, que é como uma integração
        # morre em silêncio.
        "cobertura": {"erp": len(erp), "gobrax": len(gob)},
        "fontes_fora": falhas,
        "agora": agora.isoformat(timespec="seconds"),
    }
