# -*- coding: utf-8 -*-
"""A escrita do espelho da 3S. Idempotente por construção.

Toda gravação é `ON CONFLICT … DO UPDATE` sobre a PLACA, que é a chave natural
da casa. Rodar a coleta duas vezes seguidas não duplica nada — e isso não é
zelo: o agendador do Windows repete quando a máquina acorda, e a segunda
execução do dia é regra, não exceção.
"""
from __future__ import annotations

import logging
from datetime import datetime

from api import pglocal

log = logging.getLogger("cortex.tress.armazenamento")

ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def gravar_veiculos(veiculos: list[dict], visto_em: datetime,
                    esquema: str | None = None) -> int:
    """Cadastro de veículos. Quem reaparece tem o `sumiu_em` LIMPO."""
    if not veiculos:
        return 0
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        for v in veiculos:
            cur.execute(
                """INSERT INTO tress_veiculo
                     (placa, frota, modelo, tipo, id_equipamento, id_veiculo,
                      num_serie, chassi, visto_em, sumiu_em)
                   VALUES (%(placa)s, %(frota)s, %(modelo)s, %(tipo)s,
                           %(id_equipamento)s, %(id_veiculo)s, %(num_serie)s,
                           %(chassi)s, %(visto_em)s, NULL)
                   ON CONFLICT (placa) DO UPDATE SET
                     frota = EXCLUDED.frota, modelo = EXCLUDED.modelo,
                     tipo = EXCLUDED.tipo,
                     id_equipamento = EXCLUDED.id_equipamento,
                     id_veiculo = EXCLUDED.id_veiculo,
                     num_serie = EXCLUDED.num_serie, chassi = EXCLUDED.chassi,
                     visto_em = EXCLUDED.visto_em,
                     -- reapareceu: deixa de estar sumido. Sem esta linha, a
                     -- carreta que volta ao contrato ficaria fora do painel
                     -- para sempre, e ninguém procuraria o motivo aqui.
                     sumiu_em = NULL""",
                {**v, "visto_em": visto_em})
        conn.commit()
    return len(veiculos)


def gravar_posicoes(posicoes: list[dict], esquema: str | None = None) -> int:
    """Última posição por placa.

    A posição só AVANÇA: se a 3S devolver uma leitura mais antiga que a
    guardada (acontece quando o equipamento reenvia um buffer atrasado), a
    antiga fica. Sem esse cuidado, o painel veria a comunicação "voltar no
    tempo" e uma carreta que comunicou hoje apareceria como muda.
    """
    if not posicoes:
        return 0
    agora = datetime.now()
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        for p in posicoes:
            cur.execute(
                """INSERT INTO tress_posicao
                     (placa, id_posicao, dt, latitude, longitude, velocidade,
                      ignicao, satelites, uf, cidade, bairro, endereco,
                      coletado_em)
                   VALUES (%(placa)s, %(id_posicao)s, %(dt)s, %(latitude)s,
                           %(longitude)s, %(velocidade)s, %(ignicao)s,
                           %(satelites)s, %(uf)s, %(cidade)s, %(bairro)s,
                           %(endereco)s, %(coletado_em)s)
                   ON CONFLICT (placa) DO UPDATE SET
                     id_posicao = EXCLUDED.id_posicao, dt = EXCLUDED.dt,
                     latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
                     velocidade = EXCLUDED.velocidade, ignicao = EXCLUDED.ignicao,
                     satelites = EXCLUDED.satelites, uf = EXCLUDED.uf,
                     cidade = EXCLUDED.cidade, bairro = EXCLUDED.bairro,
                     endereco = EXCLUDED.endereco,
                     coletado_em = EXCLUDED.coletado_em
                   WHERE EXCLUDED.dt >= tress_posicao.dt""",
                {**p, "coletado_em": agora})
        conn.commit()
    return len(posicoes)


def marcar_vistos(posicoes: list[dict], esquema: str | None = None) -> int:
    """Registra o DIA de cada posição lida.

    É o que permite responder "comunicou no dia 2?" — pergunta que a última
    posição sozinha não responde, porque no dia 3 ela já mudou. Idempotente:
    a mesma placa no mesmo dia entra uma vez só, e a coleta roda várias vezes
    por dia de propósito.
    """
    if not posicoes:
        return 0
    dias = {(p["placa"], p["dt"].date()) for p in posicoes if p.get("dt")}
    if not dias:
        return 0
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        for placa, dia in dias:
            cur.execute(
                "INSERT INTO tress_visto_dia (placa, dia) VALUES (%s, %s) "
                "ON CONFLICT (placa, dia) DO NOTHING", (placa, dia))
        conn.commit()
    return len(dias)


def primeira_leitura(esquema: str | None = None):
    """O dia em que NÓS começamos a ler a 3S, ou None.

    Não é `min(dia)` de `tress_visto_dia`: a primeira coleta lê a ÚLTIMA
    posição de cada veículo, e as datas dela são antigas por natureza — havia
    carreta com última posição de 2024. O que marca a fronteira é quando a
    leitura passou a existir, e isso está em `coletado_em`.
    """
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT min(coletado_em) AS m FROM tress_posicao")
        m = cur.fetchone()["m"]
        return m.date() if m else None


def vistos_no_dia(dia, esquema: str | None = None) -> set:
    """As placas que comunicaram com a 3S NAQUELE dia."""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT placa FROM tress_visto_dia WHERE dia = %s", (dia,))
        return {r["placa"] for r in cur.fetchall()}


def fechar_ausentes(inicio: datetime, esquema: str | None = None) -> int:
    """Marca como sumido quem a coleta COMPLETA não viu."""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE tress_veiculo SET sumiu_em = %s
                WHERE sumiu_em IS NULL AND visto_em < %s""", (inicio, inicio))
        n = cur.rowcount
        conn.commit()
    return n


def estado(esquema: str | None = None) -> dict:
    """O que a Saúde e o Copiloto perguntam. Só escalares."""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*)::int AS veiculos,
                      count(*) FILTER (WHERE sumiu_em IS NOT NULL)::int AS sumidos,
                      max(visto_em) AS ultima_coleta
                 FROM tress_veiculo""")
        v = dict(cur.fetchone())
        cur.execute(
            """SELECT count(*)::int AS com_posicao,
                      count(*) FILTER (WHERE dt::date = current_date)::int AS hoje,
                      count(*) FILTER (WHERE dt >= current_date - 1)::int AS ate_ontem,
                      max(dt) AS posicao_mais_nova,
                      max(coletado_em) AS lido_em
                 FROM tress_posicao p
                WHERE EXISTS (SELECT 1 FROM tress_veiculo t
                               WHERE t.placa = p.placa AND t.sumiu_em IS NULL)""")
        return {**v, **dict(cur.fetchone())}


def posicoes_por_placa(esquema: str | None = None) -> dict:
    """`{placa: datetime}` da última posição de quem está na conta.

    É por aqui que o painel funde a 3S com o ERP: quem tem leitura nos dois
    lados fica com a MAIS RECENTE, como já se faz com a Gobrax.
    """
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT p.placa, p.dt FROM tress_posicao p
                JOIN tress_veiculo t ON t.placa = p.placa
               WHERE t.sumiu_em IS NULL""")
        return {r["placa"]: r["dt"] for r in cur.fetchall()}
