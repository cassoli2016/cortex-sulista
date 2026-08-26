# api/poligonos/sql.py
"""Permanencia em poligonos mapeados dentro da planta do cliente.

FONTE: veiculo_posicao (viva - a ultima posicao chega em minutos) cruzada com
cadastro_poligono pelo operador nativo `@>` do PostgreSQL. Sem PostGIS.

NAO usa sulista.valida_poligono_tupy: aquela tabela e um retrato estatico que
parou em 11/07/2026 e so cobre 12 dos 18 poligonos - faltam justamente a
Portaria 1 (a mais movimentada, 64 placas) e o PERIMETRO da planta, que e o que
permite separar tempo em ponto de tempo em fila.

GOTCHA que nao da erro, so devolve vazio: os vertices em cadastro_poligono
estao gravados como (LATITUDE, LONGITUDE). O `point()` do teste tem de seguir a
mesma ordem - `point(lat, lon)`, nao o `point(x=lon, y=lat)` habitual em GIS.
"""
from __future__ import annotations

# Tupy Joinville. O cliente entra por CNPJ e nao por nome porque
# cadastro_poligono so guarda o codigo.
CNPJ_TUPY_JOINVILLE = "84683374000300"

# Caixa do sitio, um filtro barato que roda ANTES do teste de contencao (que e
# caro por linha). Folga de ~1,5 km em volta do perimetro cadastrado.
BBOX = {"lat1": -26.3010, "lat2": -26.2860, "lon1": -48.8140, "lon2": -48.7985}

# MEDIDO em agosto/26 dentro da planta: 77,3% das leituras vem de 3 a 5 min da
# anterior e 94,7% em ate 5 min; so 0,6% passam de 15 min. O corte de 15 min
# separa visita de visita sem partir uma parada normal ao meio.
GAP_VISITA = "15 min"

# Teto da extensao do tempo (ver PERMANENCIA abaixo). Meia cadencia tipica.
EXTENSAO_MAX = "3 min"

# PERMANENCIA - por que nao e simplesmente ultima menos primeira leitura:
#
# com cadencia de 3 a 5 min, o veiculo entrou ANTES da primeira leitura dentro
# e saiu DEPOIS da ultima. Uma visita com uma unica leitura mede ZERO minuto, e
# na amostra de 9 dias isso acontecia em 8 de 25 visitas - a tela diria que
# ninguem para em lugar nenhum.
#
# A estimativa estende ate o meio do caminho para a leitura de FORA de cada
# lado, com TETO: sem o teto, uma placa cuja leitura anterior foi ha 40 min
# ganharia 20 minutos de portaria que nao existiram (medido: a BCL8C26 ia de
# 2 min vistos para 22 estimados).
#
# As duas leituras vao juntas na resposta: `vista` (piso, so o observado) e
# `permanencia` (a estimativa). Quem audita quer a primeira; quem decide quer
# a segunda.

# Desempate DETERMINISTICO: 2 pares de poligonos internos se sobrepoem
# (Almox Ligas / Ligas II e Expedicao Perfis / Almox Granalhas). Sem ORDER BY
# o `LIMIT 1` escolhe qualquer um e o mesmo ponto trocaria de poligono entre
# execucoes - o ranking mudaria sozinho.
_POL_DO_PONTO = """
        (SELECT cp.id FROM cadastro_poligono cp
          WHERE cp.cnpjcpfcodigo = %(cnpj)s AND cp.tipo = 4
            AND cp.areapoligono @> point(vp.latituderastreadora,
                                         vp.longituderastreadora)
          ORDER BY cp.id LIMIT 1)"""

_DENTRO_DA_PLANTA = """
        EXISTS (SELECT 1 FROM cadastro_poligono cp2
                 WHERE cp2.cnpjcpfcodigo = %(cnpj)s AND cp2.tipo = 1
                   AND cp2.areapoligono @> point(vp.latituderastreadora,
                                                 vp.longituderastreadora))"""

# limites da visita, com o teto da extensao aplicado dos dois lados.
# min(dt_ant) e max(dt_prox) sao mesmo as leituras de FORA que ladeiam a visita:
# dt_ant = lag(dt) e monotonica dentro da particao, entao a menor e a da
# primeira linha da sessao (a unica cujo anterior esta fora); idem para
# max(dt_prox) e a ultima.
_ENTRADA = ("min(s.dt) - least(coalesce((min(s.dt) - min(s.dt_ant)) / 2, "
            "'0'::interval), %(ext)s::interval)")
_SAIDA = ("max(s.dt) + least(coalesce((max(s.dt_prox) - max(s.dt)) / 2, "
          "'0'::interval), %(ext)s::interval)")


def _ramo(chave: str, escopo: str, filtro: str, ident: str) -> str:
    """Sessionizacao de um dos dois escopos, sobre o MESMO `bruto`.

    Escrito como funcao porque os dois ramos sao identicos a menos da coluna
    que define "mudou de lugar" (`pol` para ponto, `planta` para o perimetro).
    """
    return f"""
{escopo}_viz AS (
  SELECT veiculo, dt, pol, planta,
         lag({chave}) OVER w AS chave_ant,
         lag(dt)      OVER w AS dt_ant,
         lead(dt)     OVER w AS dt_prox
  FROM bruto
  WINDOW w AS (PARTITION BY veiculo ORDER BY dt)
),
{escopo}_marc AS (
  SELECT veiculo, dt, pol, planta, dt_ant, dt_prox,
         CASE WHEN dt_ant IS NULL THEN 1
              WHEN {chave} IS DISTINCT FROM chave_ant THEN 1
              WHEN dt - dt_ant > %(gap)s::interval THEN 1
              ELSE 0 END AS nova
  FROM {escopo}_viz
),
{escopo}_sess AS (
  SELECT veiculo, dt, pol, planta, dt_ant, dt_prox,
         sum(nova) OVER (PARTITION BY veiculo ORDER BY dt
                         ROWS UNBOUNDED PRECEDING) AS visita
  FROM {escopo}_marc
),
{escopo}_out AS (
  SELECT '{escopo}'::text AS escopo, s.veiculo, {ident},
         min(s.dt) AS primeira, max(s.dt) AS ultima,
         count(*)::int AS leituras,
         {_ENTRADA} AS entrada,
         {_SAIDA} AS saida
  FROM {escopo}_sess s
  {filtro}
  GROUP BY s.veiculo, s.visita{', s.pol' if escopo == 'ponto' else ''}
)"""


# UMA passagem so. O caro aqui e o teste de contencao por linha (duas
# subconsultas correlacionadas em ~67 mil posicoes/mes); rodar as duas
# sessionizacoes em consultas separadas pagava esse custo DUAS vezes - medido,
# 4,1 s + 3,9 s. Com o `bruto` compartilhado paga-se uma.
VISITAS_SQL = f"""
WITH bruto AS (
  SELECT vp.veiculo, vp.dt,{_POL_DO_PONTO} AS pol,{_DENTRO_DA_PLANTA} AS planta
  FROM veiculo_posicao vp
  WHERE vp.dt >= %(de)s AND vp.dt < %(ate)s
    AND vp.latituderastreadora BETWEEN %(lat1)s AND %(lat2)s
    AND vp.longituderastreadora BETWEEN %(lon1)s AND %(lon2)s
),
{_ramo('pol', 'ponto', 'WHERE s.pol IS NOT NULL', 's.pol AS poligono_id')},
{_ramo('planta', 'planta', 'WHERE s.planta', 'NULL::integer AS poligono_id')}
SELECT * FROM ponto_out
UNION ALL
SELECT * FROM planta_out
ORDER BY entrada
"""

# Inventario dos poligonos do cliente, para a tela nomear o que existe mas nao
# teve movimento no periodo (poligono sem visita e informacao: ou o ponto
# parou de ser usado, ou o cadastro esta sobrando).
POLIGONOS_SQL = """
SELECT cp.id, cp.tipo, cp.observacao AS nome,
       cp.areapoligono::text AS geometria
FROM cadastro_poligono cp
WHERE cp.cnpjcpfcodigo = %(cnpj)s
ORDER BY cp.tipo, cp.observacao
"""

# Modalidade da placa: 48 das 70 que entram na planta sao de AGREGADO, 12 de
# tracao propria, 7 de locacao e 3 de terceiro. Sem esta quebra o tempo perdido
# aparece como se fosse todo da frota propria.
FROTA_SQL = """
SELECT v.placa, coalesce(v.utilizacaoveiculo, '') AS uso
FROM veiculo v
WHERE v.placa IS NOT NULL
"""
