"""Casa a infração da Smartec com a VIAGEM que a placa fazia naquele instante.

De quem era a carga quando a multa aconteceu? O AVA sabe: a
`programacaoembarque` tem a placa (`veiculo`), a janela (`dtsaida` →
`dtchegada`) e, via coleta → agrupamento, o cliente pagador do frete — o
MESMO join da ficha do veículo (VEICF_VIAGENS_SQL), que é a fonte já validada.

Regras que importam:

- Roda NA COLETA, nunca na leitura do painel. A tela abre só com o banco
  local; se o AVA estiver fora, o vínculo fica como estava (de ontem), e a
  trilha `smt_carga` registra a falha do passo `viagens` sem derrubar a
  coleta das multas — são recursos independentes.
- O casamento é por CONTINÊNCIA: `dtsaida <= infração <= dtchegada` (com a
  hora da infração, que a Smartec preenche em 100% das linhas). Viagem sem
  chegada lançada vale até +3 dias da saída — janela aberta para sempre
  casaria multa de hoje com viagem esquecida de 2024.
- Janelas SOBREPOSTAS existem no ERP (chegada lançada depois da saída
  seguinte). Vence a de MENOR duração — a mais específica —, e `candidatas`
  registra o empate: a tela mostra o vínculo como hipótese, não veredito.
  É a mesma regra do detector de duplicidade da frota: nada se desempata em
  silêncio.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from api import db, pglocal
from api.smartec import armazenamento as arm

log = logging.getLogger("cortex.smartec.viagem")

_esq = arm._esq

# Uma consulta por COLETA, não por infração: placas em aberto viram um ANY e
# a janela é [min(data)−3d, max(data)+3d] das próprias infrações. O DISTINCT ON
# espelha o VEICF_VIAGENS_SQL (a programação duplica linha por documento).
_VIAGENS_SQL = """
SELECT * FROM (
  SELECT DISTINCT ON (p.grupo,p.empresa,p.filial,p.diferenciadornumero,p.numero)
         p.veiculo AS placa,
         p.dtsaida::date  AS dt_saida,
         p.dtchegada::date AS dt_chegada,
         coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''),
                  nullif(trim(cp.razaosocial),'')) AS cliente,
         coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?')
           ||' → '||
         coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?')
           AS rota
  FROM programacaoembarque p
  LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
    AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
    AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
    AND co.numero=p.numerodocumentoorigem
  LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
  LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
  LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
  WHERE p.veiculo = ANY(%(placas)s)
    AND p.dtcancelamento IS NULL AND p.semaforo = 1
    AND p.dtsaida IS NOT NULL
    AND p.dtsaida >= %(de)s::date AND p.dtsaida <= %(ate)s::date
  ORDER BY p.grupo,p.empresa,p.filial,p.diferenciadornumero,p.numero
) v WHERE v.cliente IS NOT NULL
"""

# Viagem sem chegada lançada: vale por até 3 dias — a mediana das viagens da
# casa fecha em 1-2 dias, e uma janela aberta para sempre casaria qualquer
# multa futura com a viagem que ninguém deu baixa.
_SEM_CHEGADA_DIAS = 3


def _instante(inf: dict) -> datetime | None:
    d = inf.get("data_infracao")
    if not d:
        return None
    h = (inf.get("hora") or "").strip() or "12:00:00"
    try:
        return datetime.fromisoformat(f"{d} {h}")
    except ValueError:
        return datetime.fromisoformat(f"{d} 12:00:00")


def casar(esquema: str | None = None) -> dict:
    """Recasa TODAS as infrações em aberto. Idempotente por construção.

    Recasar é o caso normal (a mesma regra da coleta): a chegada da viagem é
    lançada com atraso no ERP, então o vínculo de ontem pode estar incompleto
    hoje. O custo é uma consulta ao AVA e um UPSERT local.
    """
    esq = _esq(esquema)
    infracoes = [dict(r) for r in pglocal.query(
        """SELECT identificador, placa, data_infracao::text AS data_infracao, hora
             FROM smt_infracoes
            WHERE sumiu_em IS NULL AND placa IS NOT NULL AND data_infracao IS NOT NULL""",
        esquema=esq)]
    if not infracoes:
        return {"recurso": "viagens", "itens": 0, "chamadas": 0}

    placas = sorted({i["placa"] for i in infracoes})
    datas = sorted(i["data_infracao"] for i in infracoes)
    # A busca traz saídas de até 15 dias ANTES da infração mais antiga: uma
    # viagem longa começada dias antes ainda pode conter o instante. O teto
    # dos 3 dias vale só para viagem SEM chegada lançada, não para a busca.
    de = (datetime.fromisoformat(datas[0]) - timedelta(days=15)).date()
    ate = datetime.fromisoformat(datas[-1]).date()

    viagens = db.query(_VIAGENS_SQL, {"placas": placas, "de": de.isoformat(),
                                      "ate": ate.isoformat()})
    por_placa: dict[str, list[dict]] = {}
    for v in viagens:
        por_placa.setdefault(v["placa"], []).append(v)

    casadas = 0
    for inf in infracoes:
        alvo = _instante(inf)
        if alvo is None:
            continue
        candidatas = []
        for v in por_placa.get(inf["placa"], []):
            ini = v["dt_saida"]
            fim = v["dt_chegada"] or (ini + timedelta(days=_SEM_CHEGADA_DIAS))
            if ini <= alvo.date() <= fim:
                candidatas.append((v, (fim - ini).days))
        if not candidatas:
            continue
        candidatas.sort(key=lambda par: par[1])   # a janela mais curta vence
        v = candidatas[0][0]
        pglocal.executar(
            """INSERT INTO smt_infracao_viagem
                   (identificador, cliente, rota, dt_saida, dt_chegada,
                    candidatas, casada_em)
               VALUES (%s,%s,%s,%s,%s,%s, now())
               ON CONFLICT (identificador) DO UPDATE SET
                   cliente = EXCLUDED.cliente, rota = EXCLUDED.rota,
                   dt_saida = EXCLUDED.dt_saida, dt_chegada = EXCLUDED.dt_chegada,
                   candidatas = EXCLUDED.candidatas, casada_em = now()""",
            (inf["identificador"], v["cliente"], v["rota"], v["dt_saida"],
             v["dt_chegada"], len(candidatas)), esquema=esq)
        casadas += 1
    return {"recurso": "viagens", "itens": casadas, "chamadas": 1}
