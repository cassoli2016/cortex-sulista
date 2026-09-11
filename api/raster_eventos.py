# -*- coding: utf-8 -*-
"""Os eventos da Raster (macros) e o deslocamento do veículo, para o cliente.

MEDIDO EM 11/09/2026, antes de desenhar:

  `ocorrenciarastreamento`  20.630 eventos/30d · 98 placas · macro em TEXTO no
                            `parametrorecebimento` · **100% com coordenada**
                            · vivo ao minuto
  `rastreamentoevento_posicao`  568.603 posições/90d · 100% com coordenada ·
                            46,7 posições por evento de viagem · vivo hoje
  `coleta.latitude/longitude origem|destino`  96,2% e 97,6% preenchidas

E uma fonte que NÃO serve, para ninguém tentar de novo: as tabelas
`sulista.raster_risk_*` (posições, mensagens, viagens) têm a forma certa —
`nr_macro`, texto, lat/lon em 100% — e estão MORTAS desde 25/04/2025. São 3
dias de importação de 17 meses atrás que nunca mais foram alimentados. Uma
tela construída sobre elas mostraria abril de 2025 com cara de hoje.

═══════════════════════════════════════════════════════════════════════════
O QUE O MACRO COBRE, E POR QUE ELE NÃO SUBSTITUI O APONTAMENTO
═══════════════════════════════════════════════════════════════════════════

57% das coletas de 30 dias estão numa placa que mandou macro no período — e a
dispersão entre clientes é o que decide: SCHULZ 21%, TUPY 36%, ADIENT 37%,
MAXION 76%, LEAR 82%. Uma linha do tempo feita SÓ de macro deixaria 43% das
cargas sem evento nenhum, e num painel que o cliente lê isso não se lê como
"este veículo não tem macro" — lê-se como "a Sulista não sabe onde está minha
carga".

Então o macro COMPLEMENTA o apontamento do SAC (decisão de quem opera,
11/09/2026): cada evento diz DE ONDE veio, e a tela mostra o que existir. É o
mesmo padrão que a coluna "Situação" já usa para separar apontamento, manifesto
e programação — precisão diferente, dito em vez de escondido.

═══════════════════════════════════════════════════════════════════════════
O ELO É A PLACA E A JANELA, E ISSO É DECLARADO
═══════════════════════════════════════════════════════════════════════════

O macro APONTA para um documento em 93,7% dos casos, mas o documento é o
MANIFESTO (59%), o CT-e (33%) e a COLETA em apenas **1,3%**. Casar pela coleta
cobriria quase nada; casar pelo manifesto ou pelo CT-e exige um segundo
mapeamento cuja confiabilidade eu não medi.

O que se usa aqui é PLACA + JANELA DA CARGA — o mesmo elo que a tela já usa
para mostrar a posição do veículo. E a consequência tem de aparecer no rótulo:
são os eventos do VEÍCULO QUE LEVA a carga, não os eventos da carga. Um
caminhão leva vários CT-es, então o mesmo macro aparece para todas as cargas
que ele carrega naquele momento — o que é verdade, e é diferente de dizer que
aquele evento foi da carga de um cliente específico.
"""
from __future__ import annotations

import logging

from api import db
from api.queries import cached

log = logging.getLogger(__name__)

def separar(bruto: str | None) -> tuple[str, str | None]:
    """(rótulo, detalhe) de um macro cru.

    O hub manda o formulário do motorista COLADO no rótulo, separado por `|`:

        "CHEGADA NO CLIENTE"              -> sem detalhe
        "PARADA TRANSITO||"               -> sem detalhe (campos em branco)
        "DESBLOQUEAR VEICULO||3114|8176"  -> "3114 · 8176"
        "INICIO JORNADA|11/09/26  08:03"  -> "11/09/26  08:03"

    Em PYTHON e não no SQL, e isto foi uma CORREÇÃO: a primeira versão fazia
    `regexp_replace('^[^|]*\\|', '')` no banco, que NÃO casa quando não há barra
    nenhuma — e aí o "detalhe" saía repetindo o rótulo inteiro ("PARADA POSTO
    FISCAL" nos dois campos). Visto na primeira execução contra dado real.
    Aqui a regra se lê, e se testa sem banco.
    """
    partes = [p.strip() for p in (bruto or "").split("|")]
    rotulo = partes[0]
    detalhe = " · ".join(p for p in partes[1:] if p)
    return rotulo, (detalhe or None)


MACRO_BRUTO = "coalesce(o.parametrorecebimento,'')"

# JANELA ESTREITA E COLUNA INDEXADA. A tabela tem 1,0 mi de linhas e o AVA é 9.3
# com `statement_timeout` de 60 s: uma subconsulta correlacionada por coleta
# estourou o tempo na primeira tentativa. Aqui é uma varredura só, por placa,
# com `dtinc` (indexada) recortando antes de qualquer outra coisa.
MACROS_SQL = """
SELECT trim(o.veiculo)                                   AS placa,
       """ + MACRO_BRUTO + """                           AS bruto,
       to_char(o.dtrecebimento, 'YYYY-MM-DD HH24:MI')    AS quando,
       o.latitudeposicaoveiculo::float8                  AS lat,
       o.longitudeposicaoveiculo::float8                 AS lon,
       nullif(btrim(coalesce(o.cidadeposicaoveiculo,'')), '')  AS cidade,
       nullif(btrim(coalesce(o.ufposicaoveiculo,'')), '')      AS uf
FROM ocorrenciarastreamento o
WHERE o.dtinc >= current_timestamp - (%(dias)s || ' days')::interval
  AND o.sentido = 2
  AND trim(o.veiculo) = ANY(%(placas)s)
  AND o.latitudeposicaoveiculo IS NOT NULL
  AND o.latitudeposicaoveiculo <> 0
ORDER BY o.dtrecebimento DESC
"""

# O DESLOCAMENTO. Uma viagem rende ~47 posições, e o que a tela precisa é o
# CAMINHO, não cada ponto: a redução por distância acontece no Python (ver
# `_ralear`), porque mandar 47 mil pontos para um mapa de parede é gastar rede
# para desenhar o mesmo traço.
TRILHA_SQL = """
SELECT trim(e.veiculo)                                AS placa,
       p.latitude::float8                             AS lat,
       p.longitude::float8                            AS lon,
       to_char(p.dtevento, 'YYYY-MM-DD HH24:MI')      AS quando
FROM rastreamentoevento e
JOIN rastreamentoevento_posicao p ON p.idrastreamentoevento = e.id
WHERE e.dtinc >= current_timestamp - (%(dias)s || ' days')::interval
  AND trim(e.veiculo) = ANY(%(placas)s)
  AND p.latitude IS NOT NULL AND p.latitude <> 0
ORDER BY p.dtevento
"""


def _ralear(pontos: list[dict], passo_km: float = 2.0) -> list[dict]:
    """Tira do traço os pontos que não mudam o desenho.

    Um veículo parado manda posição do mesmo jeito, e uma viagem de 47 pontos
    vira 40 pontos empilhados no pátio mais 7 na estrada. A régua é DISTÂNCIA
    no chão, não contagem: pular "um a cada N" tiraria justamente a curva e
    manteria a fila parada.

    O primeiro e o ÚLTIMO ponto ficam sempre — o último é onde o veículo está,
    e perdê-lo faria o traço terminar antes do caminhão.
    """
    if len(pontos) <= 2:
        return pontos
    saida = [pontos[0]]
    for p in pontos[1:-1]:
        if _km(saida[-1], p) >= passo_km:
            saida.append(p)
    saida.append(pontos[-1])
    return saida


def _km(a: dict, b: dict) -> float:
    """Distância em km entre dois pontos (haversine)."""
    from math import asin, cos, radians, sin, sqrt

    la1, lo1, la2, lo2 = (radians(a["lat"]), radians(a["lon"]),
                          radians(b["lat"]), radians(b["lon"]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * asin(min(1.0, sqrt(h)))


# QUANTO CABE NUM PAYLOAD QUE A PAREDE RECARREGA POR MINUTO.
#
# A primeira versão mandava tudo: 698,8 KB por carregamento, 97% disso macros e
# trilha (294 macros e 251 pontos para uma placa só, em 30 dias). Numa TV que
# recarrega de minuto em minuto isso é 40 MB por hora para desenhar um traço
# que não muda.
#
# O raleamento foi MEDIDO em vez de chutado — o que se perde é FORMA, e forma
# é o que o traço existe para mostrar. Sobre 11.851 pontos reais de 22 placas
# em 7 dias (15.301 km de traço):
#
#     passo    pontos      KB    perda de comprimento
#     bruto    11.851   813,7          —
#      2 km       812    53,2        0,6%
#      5 km       524    34,3        2,3%
#     10 km       320    21,1        4,3%
#     20 km       206    13,6        7,0%
#
# 2 km tira 94% do peso e custa 0,6% da forma: não há razão para ir além.
PASSO_KM = 2.0
MACROS_NO_MAPA = 6          # o que o mapa desenha como pino, por placa
JANELA_MAPA_D = 7           # a viagem corrente, não o mês


# ═══════════ O MACRO FALA A MESMA LÍNGUA DOS MARCOS DA OPERAÇÃO ═══════════
#
# Não é coincidência: o formulário do computador de bordo foi desenhado sobre o
# mesmo fluxo que o apontamento do SAC descreve. Medido em 30 dias, os seis
# macros mais frequentes são exatamente as seis transições que a tela já mostra:
#
#     CHEGADA NO CLIENTE              4.924   -> 396 Chegada para descarga
#     REINICIO DE VIAGEM              3.698   -> 400 Em viagem
#     FIM DE CARGA E/OU DESCARGA      2.149   -> 397 Fim de descarga
#     INICIO DE VIAGEM                1.793   -> 400 Em viagem
#     FIM DE VIAGEM                   1.557   -> 401 Viagem finalizada
#     INICIO DE CARGA E/OU DESCARGA   1.292   -> 398 Aguardando carregamento
#
# POR QUE "INICIO DE CARGA E/OU DESCARGA" VIRA 398 E NÃO 399: o macro não
# distingue carga de descarga — o "E/OU" está no nome. Mapeá-lo para o estado
# de DESCARGA afirmaria uma coisa que o motorista não disse. O 398 é o começo
# da operação de pátio, e é o mais fraco dos dois: quando o apontamento existir,
# ele é mais fino e ganha (ver `_estado`). Errar para o lado que diz MENOS é a
# única direção segura quando a fonte é ambígua.
#
# O QUE NÃO TEM MARCO CORRESPONDENTE fica de fora do estado de propósito —
# PARADA TRANSITO, PARADA PARA REFEIÇÃO, DESBLOQUEAR VEICULO, INICIO JORNADA.
# São ações do veículo que não movem a carga de etapa, e promovê-las a estado
# faria a tela dizer "Parada para refeição" onde o cliente pergunta "onde está
# minha carga". Elas continuam no payload, para quem quiser a trilha completa.
MACRO_MARCO = {
    "INICIO DE VIAGEM": 400,
    "REINICIO DE VIAGEM": 400,
    "CHEGADA NO CLIENTE": 396,
    "INICIO DE CARGA E/OU DESCARGA": 398,
    "FIM DE CARGA E/OU DESCARGA": 397,
}

# O QUE FICOU DE FORA, e por quê — esta lista vale tanto quanto a de cima.
#
# "FIM DE VIAGEM" e "CHEGADA NA MATRIZ OU FILIAL" descrevem a viagem do
# VEÍCULO, não a etapa da CARGA. Mapeados (a primeira versão mapeava), a tela
# passava a dizer "Viagem finalizada" para 8 das 26 cargas em curso da Maxion
# — caminhões que o `em_curso` mantém na lista justamente porque o fim de
# descarga não foi apontado. Ou seja: "concluída" para o caminhão parado no
# pátio do cliente, que é o defeito que esta tela corrigiu em 09/09/2026 e
# que custou as ~3h de pátio sumirem do painel.
#
# O motorista encerrando a viagem DELE não é a carga entregue. Esses macros
# continuam no payload e na trilha; o que eles não fazem é virar ESTADO.
_FORA_DO_ESTADO = ("FIM DE VIAGEM", "CHEGADA NA MATRIZ OU FILIAL",
                   "PARADA TRANSITO", "PARADA PARA REFEICAO",
                   "PARADA PARA PERNOITE", "PARADA PARA ABASTECIMENTO",
                   "PARADA PARA DESCANSO", "PARADA POSTO FISCAL",
                   "DESBLOQUEAR VEICULO", "INICIO JORNADA", "ENTREGA DO VEICULO")


def marco_do(rotulo: str | None) -> int | None:
    """O marco que este macro representa, ou `None` se ele não move a carga."""
    return MACRO_MARCO.get((rotulo or "").strip().upper())


@cached(ttl=120, velha_ate=7200)
def por_placa(placas: tuple, dias: int = 7, macros_por_placa: int = 0) -> dict:
    """Macros e deslocamento das placas pedidas, na janela pedida.

    Recebe TUPLA e não lista por causa do cache: a chave do `cached` da casa é
    `repr(args)`, e lista é mutável — quem mutasse depois da chamada faria o
    cache passar a responder por uma pergunta que ninguém fez.

    FALHA NÃO DERRUBA A TELA. Macro e trilha são acréscimo sobre uma tela que
    já funciona sem eles; `ocorrenciarastreamento` é a tabela mais pesada que
    esta casa consulta, e num dia ruim do ERP ela é a primeira a estourar o
    tempo. O que volta é `{}` com o motivo, e quem chama segue sem o mapa.
    """
    if not placas:
        return {"macros": {}, "trilhas": {}, "placas": 0}
    p = {"placas": list(placas), "dias": int(dias)}
    macros: dict[str, list] = {}
    trilhas: dict[str, list] = {}
    try:
        for r in db.query(MACROS_SQL, p):
            rotulo, detalhe = separar(r["bruto"])
            if not rotulo:
                continue          # macro sem rótulo não vira linha em branco
            macros.setdefault(r["placa"], []).append({
                "macro": rotulo, "detalhe": detalhe,
                "quando": r["quando"], "lat": r["lat"], "lon": r["lon"],
                "cidade": r["cidade"], "uf": r["uf"],
            })
        if macros_por_placa:
            # O TETO É POR PLACA, e o corte é pelos MAIS RECENTES: a consulta
            # já vem em ordem decrescente, e o que interessa a quem olha uma
            # carga em curso é o que acabou de acontecer, não o mês passado.
            macros = {pl: ms[:macros_por_placa] for pl, ms in macros.items()}
        brutas: dict[str, list] = {}
        for r in db.query(TRILHA_SQL, p):
            brutas.setdefault(r["placa"], []).append(
                {"lat": r["lat"], "lon": r["lon"], "quando": r["quando"]})
        trilhas = {pl: _ralear(pts, PASSO_KM) for pl, pts in brutas.items()}
    except Exception as exc:  # noqa: BLE001
        # TIPO da exceção, nunca o texto: a mensagem do psycopg carrega trecho
        # da consulta, e consulta com placa dentro é dado de cliente no log.
        log.warning("eventos da Raster indisponíveis: %s", type(exc).__name__)
        return {"macros": {}, "trilhas": {}, "placas": len(placas),
                "indisponivel": True}
    return {
        "macros": macros,
        "trilhas": trilhas,
        "placas": len(placas),
        # A COBERTURA VAI JUNTO e é o que impede a leitura errada: numa amostra
        # em que metade das placas não manda macro, um mapa com metade dos
        # traços parece frota parada, não cobertura parcial.
        "placas_com_macro": len(macros),
        "placas_com_trilha": len(trilhas),
        "janela_dias": int(dias),
        "macros_por_placa": int(macros_por_placa) or None,
    }
