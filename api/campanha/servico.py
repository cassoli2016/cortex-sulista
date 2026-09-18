# -*- coding: utf-8 -*-
"""O ciclo da campanha montado, a fotografia mensal e o sorteio.

AS FONTES SÃO LIDAS UMA VEZ para os dois grupos: frota e agregado saem da mesma
leitura de Gobrax, ocorrências e GR — separá-las dobraria o custo para produzir
exatamente os mesmos números. O que separa os grupos é o RANKING, não a
consulta.
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime

from api import pglocal
from api.premiacao import ciclo as ciclo_mod, parametros, pilares

from . import armazenamento as arm, base, nota as nota_mod

log = logging.getLogger("cortex.campanha.servico")

ESQUEMA: str | None = None


def _esq():
    from . import ESQUEMA as padrao
    return ESQUEMA or padrao


def montar(campanha_id: int, ciclo: str | None = None,
           dir_snapshots=None) -> dict:
    """O ciclo da campanha: dois rankings, com a nota do regulamento."""
    camp = arm.ler(campanha_id)
    if not camp:
        raise ValueError(f"Campanha {campanha_id} não existe.")
    alvo = ciclo or ciclo_mod.atual()
    if not ciclo_mod.valido(alvo):
        raise ValueError(f"Ciclo inválido: {alvo!r}. Use 'AAAA-MM'.")

    p = base.participantes(campanha_id, alvo)
    todos = [x for g in p["por_grupo"].values() for x in g]

    # UMA leitura para os dois grupos. A Gobrax casa por NOME (ela não devolve
    # documento no `vehicle-performance`), e por isso o cadastro que vai para
    # ela é o de TODO MUNDO — agregado que não estiver na lista não casa, e é
    # exatamente essa a ausência que tira do sorteio.
    gbx = pilares.gobrax(alvo, cadastro=todos, dir_path=dir_snapshots)
    de_para = parametros.depara()
    cond = pilares.comportamento_janela(alvo, 1, de_para)
    base_gr = parametros.ler(alvo, "RODOVIARIO")["valores"]
    gr = pilares.gr_janela(alvo, 1, parametros.pesos_gr(alvo),
                           base_gr["gr_minimo_viagens"], base_gr["gr_referencia"],
                           base_gr["gr_queda"], base_gr["gr_piso"])
    cond_ciclo = (cond["por_ciclo"].get(alvo) or {})
    gr_ciclo = (gr["por_ciclo"].get(alvo) or {})
    encerra = alvo == camp["ate_ciclo"]

    grupos = {}
    for grupo, pessoas in p["por_grupo"].items():
        linhas = []
        for m in pessoas:
            cpf = m["cpf"]
            ficha_c = cond_ciclo.get(cpf)
            n_gbx = (gbx["notas"].get(cpf) or {}).get("nota")
            n_cond = pilares.nota_comportamento(ficha_c)
            n_gr = (gr_ciclo.get(cpf) or {}).get("nota")
            comp = nota_mod.composta(n_gbx, n_cond, n_gr, camp)
            linha = {
                "chave": m["chave"], "nome": m["nome"], "grupo": grupo,
                "gobrax": n_gbx, "conduta": n_cond, "gr": n_gr,
                "nota": comp["nota"], "pilares": comp["pilares"],
                "ausentes": comp["ausentes"],
                "viagens": m["viagens"], "venc_cnh": m["venc_cnh"],
                "ativo": m["ativo"],
                "desvios": len((ficha_c or {}).get("desvios") or []),
            }
            linha.update(nota_mod.elegibilidade(linha, camp,
                                                encerramento=False))
            # CATEGORIA SÓ PARA QUEM FOI MEDIDO, e isto veio do ensaio com dado
            # real (18/09/2026): quem não tem telemetria NEM ocorrência fica com
            # a nota de conduta em 100 — sem desvio, sem desconto — e aparecia
            # em primeiro lugar como ELITE. É o espelho da regra da casa sobre
            # o zero: 100 por ausência de medição não é excelência, e "ELITE
            # que não concorre" é a leitura que faz o programa perder a
            # credibilidade no primeiro mês.
            linha["categoria"] = (
                nota_mod.categoria(comp["nota"], camp)
                if not linha["faltas_de_medicao"] else "PENDENTE")
            if encerra:
                # No ciclo que decide o sorteio, a categoria entra na conta da
                # elegibilidade — antes dele, não: cravar "não é Elite" no meio
                # do trimestre seria decidir um resultado que ainda vai mudar.
                linha.update(nota_mod.elegibilidade(linha, camp,
                                                    encerramento=True))
            linhas.append(linha)
        # DO MELHOR PARA O PIOR: esta tela é de campanha, e campanha se lê de
        # cima. (O ranking operacional ordena ao contrário, porque existe para
        # tratar quem está mal — são perguntas diferentes.) Sem nota vai para o
        # fim: é ausência de medição, não desempenho.
        # QUEM DISPUTA VEM PRIMEIRO. Ordenar só pela nota punha no pódio quem
        # não foi medido (nota 100 de um pilar só) na frente de quem tem os
        # três — e o pódio é a primeira coisa que se lê numa campanha.
        linhas.sort(key=lambda x: (not x["elegivel"], x["nota"] is None,
                                   -(x["nota"] or 0), x["nome"]))
        pos = 0
        for x in linhas:
            # POSIÇÃO É DE QUEM DISPUTA. Numerar quem está fora do sorteio
            # produziria um "12º lugar" que não concorre a nada.
            if x["elegivel"]:
                pos += 1
            x["posicao"] = pos if x["elegivel"] else None
        grupos[grupo] = {
            "linhas": linhas,
            "motivo": p["motivos"][grupo],
            "kpis": _kpis(linhas),
        }

    return {
        "campanha": camp, "ciclo": alvo, "rotulo": ciclo_mod.rotulo(alvo),
        "encerramento": encerra,
        "ciclos": ciclo_mod.janela(camp["ate_ciclo"],
                                   _quantos(camp["de_ciclo"], camp["ate_ciclo"])),
        "grupos": grupos,
        "fontes": {"gobrax": {"motivo": gbx["motivo"], "mes": gbx["mes_gobrax"],
                              "com_nota": len(gbx["notas"])},
                   "conduta": {"motivo": cond["motivo"]},
                   "gr": {"motivo": gr["motivo"]}},
    }


def _quantos(de_ciclo: str, ate_ciclo: str) -> int:
    a = int(de_ciclo[:4]) * 12 + int(de_ciclo[5:7])
    b = int(ate_ciclo[:4]) * 12 + int(ate_ciclo[5:7])
    return max(1, b - a + 1)


def _kpis(linhas: list[dict]) -> dict:
    por_cat: dict[str, int] = {}
    for x in linhas:
        por_cat[x["categoria"]] = por_cat.get(x["categoria"], 0) + 1
    com_nota = [x for x in linhas if x["nota"] is not None]
    notas = sorted(x["nota"] for x in com_nota)
    return {
        "participantes": len(linhas),
        "com_nota": len(com_nota),
        # O NÚMERO QUE A CAMPANHA PRECISA DIZER TODO MÊS: quantos estão fora do
        # sorteio por falta de telemetria. Ele é a medida do que dá para
        # consertar antes do fim do trimestre.
        "sem_gobrax": sum(1 for x in linhas if "sem_gobrax" in x["faltas"]),
        "elegiveis": sum(1 for x in linhas if x["elegivel"]),
        "por_categoria": por_cat,
        "nota_mediana": notas[len(notas) // 2] if notas else None,
    }


def fotografar(campanha_id: int, ciclo: str, autor: str,
               dir_snapshots=None) -> dict:
    """Congela a categoria do ciclo — é o que o regulamento manda divulgar.

    Mesma razão do fechamento da premiação: as fontes continuam se mexendo, e a
    categoria de outubro não pode mudar em dezembro, porque é ela que decide
    quem concorre.
    """
    if not autor:
        raise ValueError("Informe quem está fechando (trilha de auditoria).")
    d = montar(campanha_id, ciclo, dir_snapshots=dir_snapshots)
    arm.gravar_foto(campanha_id, ciclo, d["grupos"], esquema=_esq())
    return {"campanha": campanha_id, "ciclo": ciclo, "autor": autor,
            "linhas": sum(len(g["linhas"]) for g in d["grupos"].values())}


def sortear(campanha_id: int, grupo: str, autor: str, *, semente: str = "",
            excluidos: dict | None = None, ata: str = "") -> dict:
    """Sorteia entre os ELEGÍVEIS da fotografia do ciclo de encerramento.

    A LISTA VEM DA FOTO, nunca do cálculo de agora: sortear sobre um ranking
    vivo significaria que o resultado depende do minuto em que se clicou.

    `excluidos` é {chave: motivo} — o que só a gestão sabe (pendência
    financeira, documento que não está em sistema nenhum, descredenciamento em
    andamento). O sistema exclui o que MEDE; isto aqui é o resto, e ele fica na
    ata com nome de quem excluiu.

    A SEMENTE é registrada. Com ela e a lista, qualquer pessoa refaz o sorteio
    e chega no mesmo nome — é o que transforma "foi sorteado" em algo que se
    confere.
    """
    if not autor:
        raise ValueError("Informe quem está conduzindo o sorteio.")
    camp = arm.ler(campanha_id)
    if not camp:
        raise ValueError(f"Campanha {campanha_id} não existe.")
    if grupo not in ("FROTA", "AGREGADO"):
        raise ValueError(f"Grupo inválido: {grupo!r}")
    excluidos = excluidos or {}

    foto = arm.ler_foto(campanha_id, camp["ate_ciclo"], grupo, esquema=_esq())
    if not foto:
        raise ValueError(
            "O ciclo de encerramento ainda não foi fotografado. Feche o mês "
            "antes de sortear — a lista do sorteio é a do fechamento.")
    elegiveis = [x for x in foto if x["elegivel"] and x["chave"] not in excluidos]
    if not elegiveis:
        raise ValueError("Nenhum participante elegível neste grupo.")

    semente = semente or datetime.now().strftime("%Y%m%d%H%M%S")
    # O SORTEIO É DETERMINÍSTICO A PARTIR DA SEMENTE. `random.Random(semente)`
    # com a lista ORDENADA pela chave: sem a ordenação, a mesma semente daria
    # nomes diferentes conforme a ordem em que o banco devolveu as linhas — e
    # aí a auditoria não fecharia.
    ordem = sorted(elegiveis, key=lambda x: x["chave"])
    rnd = random.Random(hashlib.sha256(semente.encode("utf-8")).hexdigest())
    sorteados = rnd.sample(ordem, min(2, len(ordem)))
    ganhador = sorteados[0]
    suplente = sorteados[1] if len(sorteados) > 1 else {"chave": "", "nome": ""}

    agora = datetime.now().isoformat(timespec="seconds")
    pglocal.executar(
        "INSERT INTO cmp_sorteio(campanha_id, grupo, ciclo, elegiveis, semente,"
        " ganhador, ganhador_nome, suplente, suplente_nome, ata, realizado_em,"
        " realizado_por) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (campanha_id, grupo, camp["ate_ciclo"], len(ordem), semente,
         ganhador["chave"], ganhador["nome"], suplente["chave"],
         suplente["nome"], ata, agora, autor), esquema=_esq())
    return {"campanha": campanha_id, "grupo": grupo, "ciclo": camp["ate_ciclo"],
            "elegiveis": len(ordem), "semente": semente,
            "ganhador": ganhador["nome"], "suplente": suplente["nome"],
            "excluidos_a_mao": len(excluidos), "realizado_em": agora,
            "autor": autor}
