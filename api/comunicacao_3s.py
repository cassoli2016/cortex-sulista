# -*- coding: utf-8 -*-
"""A curva da comunicação da frota — e o alerta diário da 3S.

O painel de TV responde "como está agora". Este módulo responde "está
melhorando?", que é outra pergunta e precisa de memória: o ERP guarda posição,
não guarda quantas carretas estavam mudas anteontem, e a carreta que voltar a
comunicar amanhã apaga o rastro de que estava muda hoje.

TRÊS DECISÕES QUE MUDAM O NÚMERO, todas deliberadas:

1. **O DIA É FECHADO.** A medição vai até 23:59 do dia anterior. O alerta sai
   às 09:00, e uma régua que medisse "hoje" contaria como muda toda carreta que
   ainda não reportou desde a meia-noite — o número da manhã não teria relação
   com o da tarde, e a série ficaria serrilhada por artefato de horário.

2. **"NUNCA" NÃO É "MUDO".** Quem jamais teve posição (142 das 223 carretas da
   3S, medido em 03/09/2026, contra 3,8 milhões de registros históricos) é
   coisa diferente de quem reportava e parou. A primeira é provisionamento,
   contrato ou equipamento que não existe; a segunda é falha. O alerta separa
   as duas porque a ação é diferente.

3. **O ALERTA TEM AS TRÊS RESPOSTAS.** Manda o número; cala quando não há o que
   dizer; e RECUSA dizendo o motivo quando não consegue ler. O caso que exige a
   terceira: se a integração de posições parar, a leitura crua diria "0
   comunicaram" — um alarme perfeito, verdadeiro e completamente enganoso, que
   culpa a 3S por um cano nosso. Por isso o frescor da COLETA se confere antes
   do conteúdo: se nem a frota com motor reportou, o problema é o cano.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import db, pglocal

log = logging.getLogger("cortex.comunicacao3s")

ESQUEMA: str | None = None

#: Quem o alerta acompanha. A régua é a razão social do cadastro do ERP, e o
#: casamento é pelo COMEÇO do nome — "3S DISTRIBUICAO E COMERCIALIZACAO DE
#: PRODUTOS LTDA" é como ela assina, "3S" é como se fala dela.
ALVO = "3S"

#: Abaixo disto, a frota COM MOTOR não reportou o suficiente para o dia ser
#: considerado lido. Os tratores comunicam em 82% num dia normal; 20% significa
#: que o cano parou, não que a frota emudeceu.
PISO_CANO_VIVO = 0.20

_SQL_DIA = """
WITH viagem AS (
  SELECT veiculo, sum(CASE WHEN dtchegada IS NULL THEN 1 ELSE 0 END)::int AS em_viagem
  FROM programacaoembarque
  WHERE dtcancelamento IS NULL AND semaforo = 1 AND dtsaida >= current_date - 120
  GROUP BY 1
), frota AS (
  SELECT v.placa, (v.possuimotor = 1) AS com_motor,
         coalesce(nullif(trim(c.razaosocial), ''), '') AS rastreadora
  FROM veiculo v
  LEFT JOIN viagem vg ON vg.veiculo = v.placa
  LEFT JOIN cadastro c ON c.codigo = v.cnpjcpfcodigorastreador
  WHERE v.ativoinativo = 1
    AND NOT (v.tipofrota = 2 AND coalesce(vg.em_viagem, 0) = 0)
), pos AS (
  -- a ÚLTIMA posição de cada veículo até o fim do dia medido. Ancorar no dia
  -- (e não em `ultimaposicao = 1`) é o que permite remedir um dia passado e
  -- obter o mesmo número — sem isso a série se reescreveria sozinha.
  SELECT f.placa,
         (SELECT max(vp.dt) FROM veiculo_posicao vp
           WHERE vp.veiculo = f.placa AND vp.dt < %s) AS ultima
  FROM frota f
)
SELECT f.rastreadora, f.com_motor, p.ultima
FROM frota f JOIN pos p ON p.placa = f.placa
"""


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def medir(dia: date | None = None) -> dict:
    """Mede UM dia fechado. `dia` é o dia medido; o padrão é ontem."""
    dia = dia or (date.today() - timedelta(days=1))
    limite = dia + timedelta(days=1)          # exclusivo: < 00:00 do dia seguinte
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(_SQL_DIA, (limite,))
        linhas = cur.fetchall()

    grupos: dict[tuple, dict] = {}
    for r in linhas:
        nome = (r["rastreadora"] or "").strip() or "(sem rastreadora)"
        curta = nome.split()[0] if nome != "(sem rastreadora)" else nome
        chave = (curta, bool(r["com_motor"]))
        g = grupos.setdefault(chave, {"rastreadora": curta,
                                      "com_motor": bool(r["com_motor"]),
                                      "frota": 0, "comunicou": 0,
                                      "mudo_15d": 0, "nunca": 0})
        g["frota"] += 1
        u = r["ultima"]
        if u is None:
            g["nunca"] += 1
        elif u.date() == dia:
            g["comunicou"] += 1
        elif (dia - u.date()).days > 15:
            g["mudo_15d"] += 1
    return {"dia": dia, "grupos": sorted(grupos.values(),
                                         key=lambda g: (-g["frota"], g["rastreadora"]))}


def gravar(medicao: dict, esquema: str | None = None) -> int:
    """Grava a foto do dia. Idempotente: rodar duas vezes atualiza."""
    dia = medicao["dia"]
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        for g in medicao["grupos"]:
            cur.execute(
                """INSERT INTO com_status_diario
                     (dia, rastreadora, com_motor, frota, comunicou, mudo_15d, nunca)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (dia, rastreadora, com_motor) DO UPDATE SET
                     frota = EXCLUDED.frota, comunicou = EXCLUDED.comunicou,
                     mudo_15d = EXCLUDED.mudo_15d, nunca = EXCLUDED.nunca,
                     medido_em = now()""",
                (dia, g["rastreadora"], g["com_motor"], g["frota"],
                 g["comunicou"], g["mudo_15d"], g["nunca"]))
        conn.commit()
    return len(medicao["grupos"])


def _totais(grupos: list[dict], alvo: str | None = None) -> dict:
    sel = [g for g in grupos if alvo is None or g["rastreadora"] == alvo]
    t = {k: sum(g[k] for g in sel)
         for k in ("frota", "comunicou", "mudo_15d", "nunca")}
    t["parou"] = t["frota"] - t["comunicou"] - t["nunca"] - t["mudo_15d"]
    return t


def historico(dias: int = 30, alvo: str = ALVO,
              esquema: str | None = None) -> list[dict]:
    """A série do alvo, do mais recente para trás."""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT dia, sum(frota)::int frota, sum(comunicou)::int comunicou,
                      sum(mudo_15d)::int mudo_15d, sum(nunca)::int nunca
                 FROM com_status_diario WHERE rastreadora = %s
                GROUP BY dia ORDER BY dia DESC LIMIT %s""", (alvo, dias))
        return [dict(r) for r in cur.fetchall()]


def status_alerta(dia: date | None = None, alvo: str = ALVO,
                  esquema: str | None = None) -> dict:
    """O que o alerta diário precisa saber — inclusive quando NÃO deve falar.

    Devolve `{"erro": ...}` quando não dá para SABER. Silenciar aqui seria
    afirmar que a 3S está muda quando a verdade é que ninguém está olhando.
    """
    dia = dia or (date.today() - timedelta(days=1))
    try:
        med = medir(dia)
    except Exception as exc:  # noqa: BLE001
        return {"erro": "não foi possível ler o ERP (%s)" % type(exc).__name__}

    grupos = med["grupos"]
    if not grupos:
        return {"erro": "o ERP não devolveu frota nenhuma para %s"
                        % dia.strftime("%d/%m")}

    # FRESCOR DO CANO, antes do conteúdo. Se nem os tratores reportaram, o
    # problema é a integração de posições — e culpar a 3S por isso seria um
    # alarme verdadeiro no número e falso na conclusão.
    motor = _totais([g for g in grupos if g["com_motor"]])
    if motor["frota"] and (motor["comunicou"] / motor["frota"]) < PISO_CANO_VIVO:
        return {"erro": "a integração de posições parece parada — só %d de %d "
                        "veículos COM MOTOR reportaram em %s; sem isso não dá "
                        "para dizer nada sobre a 3S"
                        % (motor["comunicou"], motor["frota"],
                           dia.strftime("%d/%m"))}

    hoje_t = _totais(grupos, alvo)
    if not hoje_t["frota"]:
        return {"erro": "nenhum veículo com rastreadora “%s” no cadastro do ERP"
                        % alvo}

    gravar(med, esquema=esquema)
    serie = historico(30, alvo, esquema=esquema)
    anterior = next((x for x in serie if x["dia"] < dia), None)
    return {"dia": dia, "alvo": alvo, "hoje": hoje_t, "anterior": anterior,
            "com_motor": motor}
