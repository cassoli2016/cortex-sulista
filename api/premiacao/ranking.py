# -*- coding: utf-8 -*-
"""O ciclo montado: uma linha por motorista, com tudo que a tela mostra.

É AQUI QUE AS QUATRO FONTES VIRAM UMA LINHA. Cada uma é lida UMA VEZ para a
janela inteira — as ocorrências numa consulta ao ERP com o corte de ciclo
dentro do SQL, o GR numa consulta ao banco local, a Gobrax num arquivo por
ciclo. Seis ciclos × três fontes × 83 motoristas em consultas separadas seriam
centenas de idas ao banco para desenhar uma tela.

O QUE ESTA CAMADA NÃO FAZ: não paga e não grava. Ela calcula e devolve. O
pagamento (a etapa seguinte) congela o resultado num fechamento, porque mês
pago não se recalcula — a regra que a premiação antiga já segue.

O QUE ELA DIZ ALÉM DOS NÚMEROS: as PENDÊNCIAS. Código do ERP sem de-para, nome
da Gobrax que não casou, motorista sem filial, tipo ainda sugerido. Elas vão no
payload porque são o trabalho que falta para a régua ficar completa — e porque
número que sai de uma base com buraco precisa dizer o tamanho do buraco.
"""
from __future__ import annotations

import logging

from . import ciclo as ciclo_mod, identidade, parametros, pilares, reputacao

log = logging.getLogger("cortex.premiacao.ranking")


def montar(ciclo: str | None = None, dir_snapshots=None) -> dict:
    """O ciclo inteiro, pronto para a tela."""
    alvo = ciclo or ciclo_mod.atual()
    if not ciclo_mod.valido(alvo):
        raise ValueError(f"Ciclo inválido: {alvo!r}. Use 'AAAA-MM'.")

    cadastro = identidade.listar()
    por_grupo = {g: parametros.ler(alvo, g)["valores"] for g in parametros.GRUPOS}
    pesos_gr = parametros.pesos_gr(alvo)
    de_para = parametros.depara()

    conduta = pilares.comportamento_janela(alvo, ciclo_mod.JANELA_REPUTACAO, de_para)
    # O GR usa o piso e a régua do grupo RODOVIÁRIO para montar a janela: os
    # parâmetros de GR são do grupo, mas a consulta é uma só. A ficha traz as
    # CONTAGENS; quem precisa de outra régua recalcula a nota a partir delas —
    # e hoje os dois grupos usam a mesma, então a linha sai igual.
    base = por_grupo["RODOVIARIO"]
    gr = pilares.gr_janela(alvo, ciclo_mod.JANELA_REPUTACAO, pesos_gr,
                           base["gr_minimo_viagens"], base["gr_referencia"],
                           base["gr_queda"], base["gr_piso"])
    gobrax_ciclo = pilares.gobrax(alvo, cadastro=cadastro, dir_path=dir_snapshots)
    gobrax_janela = pilares.gobrax_janela(alvo, ciclo_mod.JANELA_REPUTACAO,
                                          cadastro=cadastro, dir_path=dir_snapshots)

    conduta_ciclo = (conduta["por_ciclo"].get(alvo) or {})
    gr_ciclo = (gr["por_ciclo"].get(alvo) or {})

    linhas = []
    for m in cadastro:
        cpf = m["cpf"]
        valores = por_grupo.get(m["tipo"], base)
        ficha_conduta = conduta_ciclo.get(cpf)
        nota_conduta = pilares.nota_comportamento(ficha_conduta)
        ficha_gr = gr_ciclo.get(cpf) or {}
        ficha_g = gobrax_ciclo["notas"].get(cpf) or {}
        comp = pilares.composta(ficha_g.get("nota"), nota_conduta,
                                ficha_gr.get("nota"), valores)
        rep = reputacao.calcular(alvo, cpf, conduta["por_ciclo"], gobrax_janela,
                                 gr["por_ciclo"], valores,
                                 primeiro_ciclo=_primeiro_ciclo(m))
        desvios_ciclo = (ficha_conduta or {}).get("desvios") or []
        medida = reputacao.sugerir_medida(
            desvios_ciclo,
            reputacao.janela_de_conduta(alvo, conduta["por_ciclo"], cpf, 3),
            reputacao.janela_de_conduta(alvo, conduta["por_ciclo"], cpf, 6))
        linhas.append({
            # A tela fala por CÓDIGO DO CADASTRO — o CPF é chave interna e não
            # sai daqui (é PII, e a regra vale para a premiação como vale para
            # o GR e para o portal do cliente).
            "motorista": m["cadastro_codigo"], "nome": m["nome"],
            "tipo": m["tipo"], "tipo_origem": m["tipo_origem"],
            "filial": m["filial"], "admissao": m["admissao"],
            "gobrax": ficha_g.get("nota"), "km": ficha_g.get("km"),
            "conduta": nota_conduta,
            "desvios": [{"cod": d["cod"], "nome": d["nome"], "grav": d["grav"],
                         "pts": d["pts"], "data": d["data"]} for d in desvios_ciclo],
            "meritos": len((ficha_conduta or {}).get("meritos") or []),
            "gr": ficha_gr.get("nota"),
            "gr_viagens": ficha_gr.get("viagens", 0),
            "gr_risco": ficha_gr.get("risco_por_viagem"),
            "gr_insuficiente": bool(ficha_gr.get("insuficiente")),
            "gr_contadores": ficha_gr.get("contadores") or {},
            "gr_informativos": ficha_gr.get("informativos") or {},
            "nota": comp["nota"], "pilares": comp["pilares"],
            "ausentes": comp["ausentes"],
            "status": pilares.status(comp["nota"], valores),
            "reputacao": rep["reputacao"], "categoria": rep["categoria"],
            "rep_conduta": rep["rep_conduta"], "ciclos_limpos": rep["ciclos_limpos"],
            "desvios_6": rep["desvios"], "meritos_6": rep["meritos"],
            "medida": medida,
        })
    # DO PIOR PARA O MELHOR: a tela existe para tratar quem está mal, e ordem
    # decrescente põe no topo quem não precisa de nada. Sem nota vai para o fim
    # — é pendência de cadastro ou de fonte, não desempenho ruim.
    linhas.sort(key=lambda x: (x["nota"] is None, x["nota"] if x["nota"] is not None else 0,
                               x["nome"]))
    return {
        "ciclo": alvo, "rotulo": ciclo_mod.rotulo(alvo),
        "mes_gobrax": gobrax_ciclo["mes_gobrax"],
        "linhas": linhas,
        "kpis": _kpis(linhas),
        "parametros": por_grupo,
        "fontes": {
            "gobrax": {"motivo": gobrax_ciclo["motivo"],
                       "coletado_em": gobrax_ciclo.get("coletado_em"),
                       "parcial": gobrax_ciclo.get("parcial"),
                       "com_nota": len(gobrax_ciclo["notas"])},
            "conduta": {"motivo": conduta["motivo"]},
            "gr": {"motivo": gr["motivo"], "com_viagem": len(gr_ciclo)},
        },
        "pendencias": {
            "codigos_sem_depara": conduta["nao_mapeados"],
            "ocorrencias_sem_codigo": conduta.get("sem_codigo", 0),
            "gobrax_ambiguos": gobrax_ciclo["ambiguos"],
            "gobrax_fora_do_cadastro": len(gobrax_ciclo["sem_cadastro"]),
            "sem_filial": sum(1 for m in cadastro if not m["filial"]),
            "tipo_sugerido": sum(1 for m in cadastro
                                 if m["tipo_origem"] == "sugerido"),
        },
    }


def _primeiro_ciclo(m: dict) -> str | None:
    """O ciclo em que a pessoa passou a existir para a régua: a admissão.

    Sem isso, quem foi admitido há dois meses ganharia bônus de ciclo limpo por
    quatro ciclos em que não trabalhava aqui.
    """
    adm = m.get("admissao")
    return adm if adm and ciclo_mod.valido(adm) else None


def _kpis(linhas: list[dict]) -> dict:
    com_nota = [x for x in linhas if x["nota"] is not None]
    por_status: dict[str, int] = {}
    for x in linhas:
        por_status[x["status"]] = por_status.get(x["status"], 0) + 1
    por_categoria: dict[str, int] = {}
    for x in linhas:
        por_categoria[x["categoria"]] = por_categoria.get(x["categoria"], 0) + 1
    notas = sorted(x["nota"] for x in com_nota)
    return {
        "motoristas": len(linhas),
        "com_nota": len(com_nota),
        "sem_nota": len(linhas) - len(com_nota),
        "nota_mediana": notas[len(notas) // 2] if notas else None,
        "por_status": por_status,
        "por_categoria": por_categoria,
        "com_desvio": sum(1 for x in linhas if x["desvios"]),
        "com_medida": sum(1 for x in linhas if x["medida"]),
        # A RENORMALIZAÇÃO NÃO É NOTA DE RODAPÉ: hoje metade da base não tem
        # nota da Gobrax, e o KPI diz quantas notas saíram com pilar faltando.
        "com_pilar_faltando": sum(1 for x in com_nota if x["ausentes"]),
    }
