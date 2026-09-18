# -*- coding: utf-8 -*-
"""A nota e a categoria DO REGULAMENTO — quatro faixas, pesos do documento.

O cálculo dos pilares é o da casa (`premiacao.pilares`): o que muda aqui são os
PESOS e as FAIXAS, que saem da campanha. É por isso que este arquivo é curto —
ele não calcula nada de novo, ele aplica outro documento sobre a mesma leitura.
"""
from __future__ import annotations

from api.premiacao import pilares


def composta(gobrax, conduta, gr, campanha: dict) -> dict:
    """A nota do regulamento: média ponderada dos pilares presentes.

    A renormalização continua existindo (a função é a mesma da casa), mas na
    campanha ela NÃO decide sozinha: quem está sem a Gobrax tem nota e fica
    fora do sorteio, porque a régua que vale para quem disputa tem de ser a
    mesma para todos. Ver `elegibilidade`.
    """
    return pilares.composta(gobrax, conduta, gr, {
        "peso_gobrax": campanha["peso_gobrax"],
        "peso_conduta": campanha["peso_conduta"],
        "peso_gr": campanha["peso_gr"],
    })


def categoria(nota, campanha: dict) -> str:
    """ELITE / OURO / PRATA / BRONZE — as QUATRO faixas do regulamento.

    Sem nota não há categoria: `PENDENTE` é uma resposta, BRONZE seria uma
    afirmação sobre alguém que ninguém mediu.
    """
    if nota is None:
        return "PENDENTE"
    if nota >= float(campanha["cat_elite"]):
        return "ELITE"
    if nota >= float(campanha["cat_ouro"]):
        return "OURO"
    if nota >= float(campanha["cat_prata"]):
        return "PRATA"
    return "BRONZE"


#: Cada motivo de exclusão, com o texto que a pessoa lê. O mais importante é
#: que NENHUM deles seja silêncio: quem não concorre precisa saber por quê
#: enquanto ainda dá tempo de mudar.
MOTIVOS = {
    "sem_nota": "sem nota no ciclo — nenhum dos três pilares foi medido",
    "sem_gobrax": "sem leitura da telemetria no ciclo — a nota de condução vale "
                  "metade do regulamento, e sem ela não dá para concorrer",
    "categoria": "a categoria do ciclo de encerramento não é Elite",
    "cnh": "CNH vencida",
    "inativo": "sem vínculo ativo no encerramento",
}


def elegibilidade(linha: dict, campanha: dict, *, encerramento: bool,
                  hoje=None) -> dict:
    """Pode concorrer ao sorteio? E, se não pode, POR QUÊ.

    `encerramento` diz se este é o ciclo que decide o sorteio: no meio do
    trimestre a categoria ainda vai mudar, e chamar alguém de inelegível por
    causa dela seria cravar um resultado que ainda não aconteceu. Os outros
    motivos — telemetria, CNH, vínculo — valem em qualquer ciclo, porque são o
    que a pessoa tem tempo de resolver.
    """
    from datetime import date
    hoje = hoje or date.today()
    faltas = []
    if linha.get("nota") is None:
        faltas.append("sem_nota")
    elif campanha.get("exige_gobrax") and "gobrax" not in (linha.get("pilares") or []):
        faltas.append("sem_gobrax")
    if not linha.get("ativo", True):
        faltas.append("inativo")
    venc = linha.get("venc_cnh")
    if venc and str(venc)[:10] < hoje.isoformat():
        faltas.append("cnh")
    if encerramento and linha.get("categoria") != "ELITE":
        faltas.append("categoria")
    return {
        "elegivel": not faltas,
        "faltas": faltas,
        # AS FALTAS DE MEDIÇÃO SÃO OUTRA COISA das faltas de cadastro: sem
        # medição não há categoria a afirmar; com CNH vencida há categoria, e
        # ela some do sorteio. Separar as duas é o que permite dizer a coisa
        # certa em cada linha.
        "faltas_de_medicao": [f for f in faltas if f in ("sem_nota", "sem_gobrax")],
        "motivo": " · ".join(MOTIVOS[f] for f in faltas),
    }
