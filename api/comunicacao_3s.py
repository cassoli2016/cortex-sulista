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
import re
from datetime import date, datetime, time, timedelta

from . import db, frota_identidade, pglocal

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
  SELECT v.placa, v.numerofrota, (v.possuimotor = 1) AS com_motor,
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
SELECT f.placa, f.numerofrota, f.rastreadora, f.com_motor, p.ultima
FROM frota f JOIN pos p ON p.placa = f.placa
"""


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def medir(dia: date | None = None, esquema: str | None = None) -> dict:
    """Mede UM dia fechado. `dia` é o dia medido; o padrão é ontem."""
    dia = dia or (date.today() - timedelta(days=1))
    limite = dia + timedelta(days=1)          # exclusivo: < 00:00 do dia seguinte
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(_SQL_DIA, (limite,))
        linhas = [dict(r) for r in cur.fetchall()]

    # A MESMA FUSÃO DO PAINEL, e pelo mesmo motivo: o ERP é uma fonte de
    # posição, não A fonte. Sem isto o aviso da 3S mediria o cano do ERP e
    # chamaria de "3S muda" carreta que reportou àquela mesma 3S no dia.
    #
    # DUAS LEITURAS DIFERENTES, e confundi-las foi o primeiro desenho errado:
    #
    #   `vistos_no_dia` responde "comunicou NAQUELE dia?" — exato, porque a
    #   coleta registra o dia de cada posição que leu.
    #
    #   `posicoes_por_placa` responde "quando falou pela última vez?" — serve
    #   para as faixas de silêncio, e NÃO serve para o dia: às 09:00 de hoje a
    #   última posição da maioria já é de hoje, o que prova que a carreta está
    #   viva mas não prova que ela falou ontem. Usar isso como "comunicou"
    #   daria por comunicante justamente a que voltou hoje depois de uma
    #   semana muda — a única que interessa.
    vistos, pos3s = set(), {}
    try:
        from api.tress import armazenamento as _tress
        vistos = _tress.vistos_no_dia(dia, esquema=esquema)
        pos3s = _tress.posicoes_por_placa(esquema=esquema)
    except Exception as exc:  # noqa: BLE001 — sem espelho o aviso segue com o ERP
        log.warning("aviso da 3S sem o espelho direto: %s", type(exc).__name__)
    if vistos or pos3s:
        limpa = lambda p: re.sub(r"[^A-Z0-9]", "", (p or "").upper())
        for r in linhas:
            chave = limpa(r.get("placa"))
            if chave in vistos:
                # comunicou NO dia, provado: carimba a data do próprio dia
                r["ultima"] = datetime.combine(dia, time(23, 59))
                continue
            nova = pos3s.get(chave)
            if nova and nova.date() < dia and (
                    r["ultima"] is None or nova > r["ultima"]):
                r["ultima"] = nova

    grupos: dict[tuple, dict] = {}
    placas: list[dict] = []
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
            situacao = "nunca"
        elif u.date() == dia:
            g["comunicou"] += 1
            situacao = "comunicou"
        elif (dia - u.date()).days > 15:
            g["mudo_15d"] += 1
            situacao = "mudo15"
        else:
            situacao = "parou"
        placas.append({
            "placa": r["placa"],
            "frota": frota_identidade.rotulo(r["numerofrota"], r["placa"]),
            "rastreadora": curta, "com_motor": bool(r["com_motor"]),
            "situacao": situacao, "ultima": u.date() if u else None,
        })
    return {"dia": dia,
            "grupos": sorted(grupos.values(),
                             key=lambda g: (-g["frota"], g["rastreadora"])),
            "placas": placas}


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
        # As placas do MESMO dia são reescritas por inteiro antes de entrar:
        # se uma placa sair da frota, a linha velha dela não pode sobreviver
        # ao ON CONFLICT e continuar contando para sempre.
        cur.execute("DELETE FROM com_placa_diaria WHERE dia = %s", (dia,))
        for p in medicao.get("placas") or []:
            cur.execute(
                """INSERT INTO com_placa_diaria
                     (dia, placa, rastreadora, com_motor, situacao, ultima)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (dia, p["placa"], p["rastreadora"], p["com_motor"],
                 p["situacao"], p["ultima"]))
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


#: As situações que a lista de cobrança contém. "comunicou" fica de fora: o
#: anexo existe para cobrar quem NÃO comunica, e uma lista que traz todo mundo
#: não é lista, é o cadastro.
SITUACOES_COBRANCA = ("nunca", "mudo15", "parou")


def placas_do_dia(dia: date, alvo: str = ALVO,
                  esquema: str | None = None) -> list[dict]:
    """As placas do alvo naquele dia, já na ordem em que o anexo as mostra."""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT placa, situacao, ultima FROM com_placa_diaria
                WHERE dia = %s AND rastreadora = %s
                ORDER BY CASE situacao WHEN 'nunca' THEN 0 WHEN 'mudo15' THEN 1
                                       WHEN 'parou' THEN 2 ELSE 3 END,
                         ultima NULLS FIRST, placa""", (dia, alvo))
        return [dict(r) for r in cur.fetchall()]


def diferenca(dia: date, anterior: date | None, alvo: str = ALVO,
              esquema: str | None = None) -> dict:
    """O que ENTROU e SAIU da lista de cobrança entre dois dias.

    Por que isto não se responde com a contagem: 142 ontem e 142 hoje pode ser
    a mesma lista parada ou três carretas que voltaram e três que caíram. A
    segunda é notícia, e some inteira num número que não mudou.
    """
    def conj(d):
        if d is None:
            return None
        return {p["placa"] for p in placas_do_dia(d, alvo, esquema)
                if p["situacao"] in SITUACOES_COBRANCA}

    hoje, ontem = conj(dia), conj(anterior)
    if ontem is None:
        return {"primeira": True, "entraram": [], "sairam": [], "mudou": True}
    entraram, sairam = sorted(hoje - ontem), sorted(ontem - hoje)
    return {"primeira": False, "entraram": entraram, "sairam": sairam,
            "mudou": bool(entraram or sairam)}


def status_alerta(dia: date | None = None, alvo: str = ALVO,
                  esquema: str | None = None) -> dict:
    """O que o alerta diário precisa saber — inclusive quando NÃO deve falar.

    Devolve `{"erro": ...}` quando não dá para SABER. Silenciar aqui seria
    afirmar que a 3S está muda quando a verdade é que ninguém está olhando.
    """
    dia = dia or (date.today() - timedelta(days=1))
    try:
        med = medir(dia, esquema=esquema)
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
    dif = diferenca(dia, anterior["dia"] if anterior else None, alvo, esquema)
    # A RÉGUA MUDOU NO MEIO? No dia em que a coleta direta da 3S começou, o
    # número salta — 54 para 128, medido em 03/09/2026 — e isso NÃO é a frota
    # melhorando: é o CÓRTEX passando a enxergar. Comparar os dois lados dessa
    # fronteira e chamar de evolução seria a mentira mais fácil deste aviso,
    # ainda por cima uma que agrada. O aviso diz que a régua mudou e não
    # apresenta variação nenhuma naquele dia.
    troca_de_regua = False
    if anterior:
        try:
            from api.tress import armazenamento as _tress
            # a fronteira é a PRIMEIRA LEITURA nossa, não o dia mais antigo
            # com registro: a primeira coleta traz posições velhas por
            # natureza, e uma delas caindo em ontem apagaria o aviso
            primeira = _tress.primeira_leitura(esquema=esquema)
            troca_de_regua = bool(primeira and anterior["dia"] < primeira
                                  and dia >= primeira)
        except Exception:  # noqa: BLE001
            troca_de_regua = False
    return {"dia": dia, "alvo": alvo, "hoje": hoje_t, "anterior": anterior,
            "troca_de_regua": troca_de_regua,
            "com_motor": motor, "diferenca": dif,
            "placas": placas_do_dia(dia, alvo, esquema)}
