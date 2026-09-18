# -*- coding: utf-8 -*-
"""A campanha DELE: a categoria do mês, o que falta e quanto tempo resta.

═══════════════════════════════════════════════════════════════════════════
POR QUE ESTE MÓDULO NÃO CALCULA NADA
═══════════════════════════════════════════════════════════════════════════
Ele chama `api/campanha/servico.montar` — a MESMA função da tela da gestão — e
recorta a linha de quem está logado. A campanha vai divulgar categoria no
quadro e no aplicativo ao mesmo tempo; se os dois calculassem por conta
própria, a primeira divergência viraria "o app diz que sou Ouro e o quadro diz
Prata" na véspera de um sorteio.

═══════════════════════════════════════════════════════════════════════════
O QUE ELE VÊ, E O QUE NÃO VÊ
═══════════════════════════════════════════════════════════════════════════
Vê: a nota dele, os três pilares com o peso de cada um, a categoria, a posição
no grupo DELE, se está concorrendo e — quando não está — o que exatamente
falta. Vê também quantos estão em cada categoria no grupo, porque isso é o
tamanho da disputa e não é sobre ninguém em particular.

NÃO VÊ: nome de colega, nota de colega, e o CPF (a chave da campanha é opaca).
Frota e agregado competem separados, então o painel do grupo é o DELE — o do
outro grupo não é assunto dele nem ajuda a decidir nada.

═══════════════════════════════════════════════════════════════════════════
O PRAZO É PARTE DA RESPOSTA
═══════════════════════════════════════════════════════════════════════════
"Faltam 2 ciclos" muda o que a pessoa faz hoje; "você está em Prata" sozinho,
não. Por isso o payload leva o ciclo de encerramento, quantos ciclos faltam e a
data do sorteio — e, para quem está fora por falta de telemetria, isso é a
diferença entre reclamar em dezembro e resolver em outubro.
"""
from __future__ import annotations

import logging

from api.campanha import armazenamento as arm, base, servico
from api.premiacao import ciclo as ciclo_mod
from api.queries import VELHA_ATE, cached

log = logging.getLogger("cortex.motorista.campanha")


@cached(ttl=300, velha_ate=VELHA_ATE)
def _ciclo_montado(campanha_id: int, ciclo: str) -> dict:
    """A campanha inteira, uma vez a cada cinco minutos para todo mundo.

    A janela da leitura velha é a da casa (`VELHA_ATE`): a menor faixa que esta
    tela publica é um CICLO, e um número de vinte minutos atrás não muda nada
    do que está escrito ali.
    """
    return servico.montar(campanha_id, ciclo)


def _faltam(ciclo: str, ate_ciclo: str) -> int:
    a = int(ciclo[:4]) * 12 + int(ciclo[5:7])
    b = int(ate_ciclo[:4]) * 12 + int(ate_ciclo[5:7])
    return max(0, b - a)


def minha(sessao: dict) -> dict:
    """A campanha de QUEM ESTÁ LOGADO — sem parâmetro de motorista, como o
    resto do app."""
    codigo = str(sessao.get("motorista_codigo") or "")
    try:
        camp = arm.vigente()
    except Exception as exc:  # noqa: BLE001
        log.warning("motorista: campanha indisponivel (%s)", type(exc).__name__)
        camp = None
    if not camp:
        # SEM CAMPANHA NÃO É FALHA: é o intervalo entre um trimestre e outro.
        return {"tem_dado": False, "fora_do_escopo": True,
                "motivo": "Não há campanha em andamento agora.",
                "fonte": "Programa de desempenho"}

    alvo = ciclo_mod.atual()
    if alvo > camp["ate_ciclo"]:
        alvo = camp["ate_ciclo"]      # depois do fim, a tela mostra o resultado
    elif alvo < camp["de_ciclo"]:
        alvo = camp["de_ciclo"]

    try:
        d = _ciclo_montado(camp["id"], alvo)
    except Exception as exc:  # noqa: BLE001
        log.warning("motorista: ciclo da campanha indisponivel (%s)",
                    type(exc).__name__)
        return {"tem_dado": False, "fora_do_escopo": False,
                "motivo": "Não consegui ler a campanha agora. Tente de novo "
                          "daqui a pouco.", "fonte": "Programa de desempenho"}

    # A CHAVE É OPACA e é calculada aqui: o app manda o código do cadastro na
    # sessão, e o CPF não trafega em lugar nenhum.
    from api.premiacao import identidade
    cpf = None
    try:
        cpf = identidade.cpf_do_cadastro(codigo)
    except Exception as exc:  # noqa: BLE001
        log.warning("motorista: cadastro indisponivel (%s)", type(exc).__name__)
    # O agregado não está no cadastro da folha: para ele, o código do ERP JÁ é
    # o CPF (11 dígitos em 279 de 279, medido em 18/09/2026).
    chave_frota = base.chave(camp["id"], cpf) if cpf else None
    chave_agreg = base.chave(camp["id"], codigo)

    for grupo, bloco in d["grupos"].items():
        for x in bloco["linhas"]:
            if x["chave"] in (chave_frota, chave_agreg):
                return _payload(x, grupo, bloco, d, camp)

    return {"tem_dado": False, "fora_do_escopo": True,
            "motivo": "Você não está participando desta campanha.",
            "fonte": "Programa de desempenho"}


def _payload(linha: dict, grupo: str, bloco: dict, d: dict, camp: dict) -> dict:
    from api.campanha.nota import MOTIVOS
    pesos = {"gobrax": camp["peso_gobrax"], "conduta": camp["peso_conduta"],
             "gr": camp["peso_gr"]}
    rotulos = {"gobrax": "Condução", "conduta": "Comportamento",
               "gr": "Gerenciamento de risco"}
    return {
        "tem_dado": True, "fora_do_escopo": False,
        "campanha": {"nome": camp["nome"], "premio": camp["premio"],
                     "onde": camp["onde"], "sorteio_em": camp["sorteio_em"],
                     "ate_ciclo": camp["ate_ciclo"],
                     "cat_elite": camp["cat_elite"]},
        "ciclo": d["ciclo"], "rotulo": d["rotulo"],
        "encerramento": d["encerramento"],
        "faltam_ciclos": _faltam(d["ciclo"], camp["ate_ciclo"]),
        "grupo": grupo,
        "grupo_rotulo": "frota" if grupo == "FROTA" else "agregados",
        "nota": linha["nota"], "categoria": linha["categoria"],
        "posicao": linha["posicao"], "de": bloco["kpis"]["elegiveis"],
        "concorre": linha["elegivel"],
        "motivo": linha["motivo"],
        # O QUE FALTA, item a item — a frase inteira é o que permite agir. Uma
        # lista de códigos ("sem_gobrax") não diz nada a quem dirige.
        "faltas": [MOTIVOS[f] for f in linha["faltas"]],
        "pilares": [{"chave": c, "rotulo": rotulos[c], "peso": pesos[c],
                     "nota": linha[c], "entrou": c in (linha["pilares"] or [])}
                    for c in ("gobrax", "conduta", "gr")],
        # O TAMANHO DA DISPUTA, sem nome de ninguém: é o que diz se a categoria
        # dele é comum ou rara no grupo.
        "no_grupo": {"participantes": bloco["kpis"]["participantes"],
                     "concorrendo": bloco["kpis"]["elegiveis"],
                     "por_categoria": bloco["kpis"]["por_categoria"]},
        "fonte": "Programa de desempenho · " + (
            "resultado do trimestre" if d["encerramento"] else "ciclo em curso"),
    }
