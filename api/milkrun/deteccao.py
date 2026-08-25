"""Detecta chegada e saída de um veículo num ponto, a partir do rastro.

Por que existe: os horários de chegada/saída nos fornecedores da MWM são
DIGITADOS hoje, e o dado prova que isso erra. Nos últimos 30 dias havia 1.462
viagens entre cidades diferentes com duração menor que 15 minutos — São Paulo
a Limeira em 1 minuto — e 46% das chegadas terminam com segundo `:00`, que é
a assinatura de quem digita: o rastreador sempre traz o segundo do ping.

O rastro suporta a automação: `veiculo_posicao` tem ~250 posições por veículo
por dia (uma a cada ~6 minutos), então a chegada é detectável com erro de
poucos minutos — melhor do que qualquer apontamento manual.

DECISÕES QUE IMPORTAM:

- **Chegada é a PRIMEIRA posição dentro do raio; saída é a última de uma
  permanência CONTÍNUA.** Um veículo que passa em frente ao fornecedor a
  caminho de outro lugar entra e sai do raio em um ou dois pings: por isso
  existe `min_permanencia`, abaixo do qual a passagem não conta como visita.

- **Uma lacuna longa no rastro não encerra a visita.** O rastreador dorme, o
  caminhão entra em galpão coberto, o sinal cai. Fechar a visita no primeiro
  ping ausente marcaria saída no meio do carregamento; por isso a visita só
  termina quando aparece posição FORA do raio.

- **Distância pela fórmula de Haversine**, não por diferença de graus: um grau
  de longitude vale ~102 km no equador e ~92 km em Porto Alegre. Com raio de
  300 m, a diferença de graus erraria a cerca em dezenas de metros conforme a
  latitude do ponto.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

# Raio padrão da cerca. 300 m cobre o pátio de uma fábrica média sem invadir a
# via. Ponto grande (montadora) precisa de mais, e por isso é por ponto.
RAIO_PADRAO_M = 300

# Abaixo disso é passagem, não visita: o caminhão cruzou a região a caminho de
# outro lugar. 10 min é menos que qualquer carregamento real e mais que
# qualquer passagem por via expressa.
MIN_PERMANENCIA_MIN = 10

# ...MAS permanencia sozinha descarta parada real. Caso medido (viagem 175882,
# Sao Bernardo): o veiculo chegou a 209 m do ponto — dentro do raio — e a
# visita sumiu porque so houve um ping la dentro antes de o rastreador calar.
# O sinal que separa PARAR de PASSAR nao e o tempo, e a VELOCIDADE, e o rastro
# ja a traz.
VEL_PARADO_KMH = 5

RAIO_TERRA_M = 6_371_000


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos (Haversine)."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_M * asin(min(1.0, sqrt(a)))


@dataclass
class Visita:
    """Uma permanência contínua dentro do raio do ponto."""
    chegada: datetime
    saida: datetime | None          # None = ainda está lá
    posicoes: int
    minutos: float
    distancia_min_m: float
    # houve ao menos uma posicao com o veiculo PARADO dentro do raio
    parou: bool = False

    @property
    def em_andamento(self) -> bool:
        return self.saida is None


def _ok(p) -> bool:
    lat, lng = p.get("lat"), p.get("lng")
    return (lat is not None and lng is not None
            and not (lat == 0 and lng == 0) and p.get("dt") is not None)


def _parado(p) -> bool:
    """Veiculo parado nesta posicao. Velocidade AUSENTE nao conta como parado:
    supor imobilidade a partir de campo vazio transformaria rastreador com
    defeito em coleta que nunca houve."""
    v = p.get("velocidade")
    return v is not None and float(v) <= VEL_PARADO_KMH


def detectar(posicoes: list[dict], lat: float, lng: float, *,
             raio_m: float = RAIO_PADRAO_M,
             min_permanencia_min: float = MIN_PERMANENCIA_MIN) -> list[Visita]:
    """Visitas do veículo ao ponto, na ordem em que aconteceram.

    `posicoes`: [{'dt': datetime, 'lat': float, 'lng': float}, ...]. Não
    precisa vir ordenada — a ordenação é feita aqui, porque rastro que chega
    por lotes diferentes vem fora de ordem e uma visita partida ao meio viraria
    duas.
    """
    pts = sorted((p for p in posicoes if _ok(p)), key=lambda p: p["dt"])
    if not pts or lat is None or lng is None:
        return []

    visitas: list[Visita] = []
    atual: dict | None = None

    for p in pts:
        d = distancia_m(lat, lng, p["lat"], p["lng"])
        dentro = d <= raio_m
        if dentro:
            if atual is None:
                atual = {"chegada": p["dt"], "ultima": p["dt"], "n": 1,
                         "dmin": d, "parou": _parado(p)}
            else:
                atual["ultima"] = p["dt"]
                atual["n"] += 1
                atual["dmin"] = min(atual["dmin"], d)
                atual["parou"] = atual["parou"] or _parado(p)
        elif atual is not None:
            # so uma posicao FORA fecha a visita; lacuna de sinal nao fecha,
            # senao o caminhao "sairia" toda vez que o rastreador dormisse
            visitas.append(_fechar(atual, p["dt"]))
            atual = None

    if atual is not None:
        # ainda dentro do raio na ultima posicao conhecida: visita ABERTA.
        # Marcar saida = ultima posicao diria "ja saiu" sobre um caminhao que
        # esta carregando agora.
        visitas.append(Visita(chegada=atual["chegada"], saida=None,
                              posicoes=atual["n"],
                              minutos=_min(atual["chegada"], atual["ultima"]),
                              distancia_min_m=round(atual["dmin"], 1),
                              parou=atual["parou"]))

    return [v for v in visitas
            if v.em_andamento or v.parou or v.minutos >= min_permanencia_min]


def _min(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 60, 1)


def _fechar(atual: dict, primeira_fora: datetime) -> Visita:
    """Fecha a visita. A saída fica no MEIO do intervalo entre a última
    posição dentro e a primeira fora: o veículo saiu em algum momento entre as
    duas, e o ponto médio erra menos que qualquer das pontas — com ping de 6
    min, o erro máximo cai de 6 para 3 minutos."""
    meio = atual["ultima"] + (primeira_fora - atual["ultima"]) / 2
    return Visita(chegada=atual["chegada"], saida=meio, posicoes=atual["n"],
                  minutos=_min(atual["chegada"], meio),
                  distancia_min_m=round(atual["dmin"], 1),
                  parou=atual["parou"])


def visita_da_janela(visitas: list[Visita], previsto: datetime | None, *,
                     tolerancia_h: float = 6.0) -> Visita | None:
    """Escolhe a visita que corresponde ao agendamento.

    Um veículo pode passar duas vezes no mesmo fornecedor no dia (coleta e
    retorno). Pegar a primeira marcaria a passagem errada; pega-se a mais
    PRÓXIMA do horário combinado, dentro de uma tolerância — fora dela, não há
    visita correspondente e dizer que houve seria inventar.
    """
    if not visitas:
        return None
    if previsto is None:
        return visitas[0]
    limite = timedelta(hours=tolerancia_h)
    candidatas = [v for v in visitas if abs(v.chegada - previsto) <= limite]
    if not candidatas:
        return None
    return min(candidatas, key=lambda v: abs(v.chegada - previsto))


def classificar(visita: Visita | None, previsto: datetime | None, *,
                tolerancia_min: float = 30.0) -> dict:
    """Semáforo do ponto. Sem horário combinado NÃO inventa atraso — devolve
    'sem janela', porque julgar pontualidade contra uma referência que não
    existe produz alarme falso."""
    if visita is None:
        return {"estado": "aguardando", "atraso_min": None,
                "rotulo": "não chegou"}
    if visita.em_andamento:
        base = {"estado": "no_local", "rotulo": "no local"}
    else:
        base = {"estado": "concluido", "rotulo": "coletado"}
    if previsto is None:
        return {**base, "atraso_min": None, "pontualidade": "sem janela"}
    atraso = round((visita.chegada - previsto).total_seconds() / 60)
    if atraso <= -tolerancia_min:
        pont = "adiantado"
    elif atraso <= tolerancia_min:
        pont = "no prazo"
    else:
        pont = "atrasado"
    return {**base, "atraso_min": atraso, "pontualidade": pont}
