# -*- coding: utf-8 -*-
"""O PANORAMA do programa: a camada 1 que a tela `prem` não tinha.

A tela já respondia tudo em detalhe — o ranking do ciclo, a reputação, o GR, as
ocorrências, o cadastro, as categorias, a campanha. O que faltava era a
primeira camada do padrão da casa: *como está o programa numa olhada*, com
comparação e com o que exige ação.

═══════════════════════════════════════════════════════════════════════════
A DECISÃO QUE DEFINE ESTE MÓDULO: A COBERTURA VEM ANTES DA NOTA
═══════════════════════════════════════════════════════════════════════════
Medido no ciclo 2026-10 (19/09/2026, quarto dia do ciclo): mediana **98,5**,
66 motoristas em EXCELENTE, 36 em DIAMANTE — e **81 das 82 notas calculadas
com um pilar faltando**. Uma banda de KPIs com "98,5" e cinco cartões verdes
seria verdadeira e leria ao contrário do que os dados dizem: a nota está alta
porque falta pilar, não porque a frota está impecável.

É a regra da casa sobre zero-por-ausência, do outro lado do espelho — lá a
ausência vira um zero que parece desempenho ruim; aqui vira um CEM que parece
desempenho ótimo, porque a renormalização redistribui o peso do pilar ausente
entre os que sobraram. Por isso o payload publica `medicao` ANTES de `nota`, e
nenhuma nota sai daqui sem a cobertura ao lado.

═══════════════════════════════════════════════════════════════════════════
O QUE ESTE MÓDULO NÃO PUBLICA: DINHEIRO
═══════════════════════════════════════════════════════════════════════════
O valor do prêmio mora na aba Premiação, que é BLOQUEÁVEL por usuário
(`acessos.ABAS["prem.premiacao"]`) — existe para se dar a tela a quem
acompanha conduta sem dar a folha junto. O panorama é a primeira aba, que todo
mundo com a tela abre.

Então ele responde "o programa PODE pagar?" e nunca "quanto". Ele chega a ler
`premio.tabela()`, que traz valores em reais, e **conta as chaves sem olhar os
valores** — é a diferença entre saber que três filiais estão sem cadastro e
saber quanto cada uma paga.
"""
from __future__ import annotations

import logging

from api.queries import VELHA_ATE, cached

from . import ciclo as ciclo_mod, fechamento, parametros, premio, ranking

log = logging.getLogger("cortex.premiacao.panorama")

#: Os três pilares, na ordem em que a régua os lê, com o campo da linha.
PILARES = (
    ("gobrax", "Condução", "peso_gobrax"),
    ("conduta", "Comportamento", "peso_conduta"),
    ("gr", "Gerenciamento de risco", "peso_gr"),
)

#: Quantos ciclos a série mostra. É a MESMA janela da reputação: o modelo já
#: decidiu que seis ciclos são a memória do programa, e uma janela própria aqui
#: seria uma segunda decisão sobre a mesma pergunta.
JANELA = ciclo_mod.JANELA_REPUTACAO


@cached(ttl=300, velha_ate=VELHA_ATE)
def _montado(ciclo: str) -> dict:
    """O ciclo inteiro, com a última leitura boa guardada.

    O CACHE NÃO ESTÁ AQUI POR VELOCIDADE: montar o ciclo custa 0,12 s
    (mediana de 3, medido em 19/09/2026 com os 82 motoristas), e a aba carrega
    em paralelo com `/ciclo` — somar as duas não muda o relógio. Ele está aqui
    pelo `velha_ate`: no dia em que o ERP tem uma janela ruim, a aba serve a
    última leitura boa CARIMBADA em vez de ficar vazia, e a tarja de leitura
    velha aparece sozinha pelo cabeçalho HTTP.

    A leitura velha é admissível nesta tela pelo critério da casa — o critério
    é a RESOLUÇÃO do que ela publica, e a menor faixa aqui é um CICLO de um
    mês. Vinte minutos não mudam nada do que está escrito.
    """
    return ranking.montar(ciclo)


def _media(valores: list[float]) -> float | None:
    return round(sum(valores) / len(valores), 1) if valores else None


def _mediana(valores: list[float]) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    return round(v[len(v) // 2], 1)


def _pilares(linhas: list[dict], pesos: dict) -> list[dict]:
    """Média e COBERTURA de cada pilar.

    A média sozinha esconde o que importa: o pilar de condução pode marcar 90
    com cinquenta motoristas medidos de oitenta e dois, e a nota da casa toda
    depende dessa diferença. Pilar sem NENHUMA medição devolve `media: None`
    com motivo — nunca zero, que na tela viraria uma barra no chão e se leria
    como desempenho péssimo.
    """
    total = len(linhas)
    saida = []
    for chave, rotulo, peso_campo in PILARES:
        medidos = [float(x[chave]) for x in linhas if x.get(chave) is not None]
        saida.append({
            "chave": chave, "rotulo": rotulo,
            "peso": pesos.get(peso_campo),
            "com_nota": len(medidos),
            "de": total,
            "media": _media(medidos),
            "motivo": "" if medidos else "nenhum motorista medido neste pilar",
        })
    return saida


def _serie(alvo: str, kpis_do_ciclo: dict) -> dict:
    """A nota por ciclo: os FECHADOS mais o ciclo em curso.

    O intervalo de ciclos é GERADO (`ciclo_mod.janela`), nunca colhido do
    banco: colhendo, um ciclo sem fechamento não apareceria e a linha emendaria
    por cima do buraco — agosto encostaria em outubro como se nada tivesse
    acontecido no meio.

    O ciclo em curso entra marcado `em_curso`, para a tela hachurá-lo: ele é
    parcial por construção até o dia 15, e comparar um ciclo de quatro dias com
    um fechado é comparar coisas diferentes.
    """
    ciclos = ciclo_mod.janela(alvo, JANELA)
    fechados = fechamento.historico(ciclos)
    linhas = []
    for c in ciclos:
        f = fechados.get(c)
        linhas.append({
            "ciclo": c, "rotulo": ciclo_mod.rotulo(c),
            "em_curso": c == alvo,
            "fechado": bool(f),
            "mediana": (f["mediana"] if f else
                        (kpis_do_ciclo.get("nota_mediana") if c == alvo else None)),
            "motoristas": (f["motoristas"] if f else
                           (kpis_do_ciclo.get("motoristas") if c == alvo else None)),
        })
    n = sum(1 for x in linhas if x["fechado"])
    return {
        "linhas": linhas,
        "fechados": n,
        # SEM CICLO FECHADO NÃO HÁ SÉRIE, e dizer isso é a resposta honesta:
        # um único ponto desenhado como linha sugere uma tendência que ninguém
        # mediu. O programa ainda não fechou nenhum ciclo.
        "motivo": ("" if n else
                   "nenhum ciclo fechado ainda — a série começa no primeiro "
                   "fechamento"),
    }


def _pagar(alvo: str) -> dict:
    """O programa pode pagar este ciclo? — e o que falta, quando não pode.

    NENHUM VALOR EM REAIS SAI DAQUI. A tabela é lida e só as CHAVES são
    contadas; os valores são descartados sem serem olhados. Ver o cabeçalho do
    módulo: a aba do dinheiro é bloqueável, esta não.
    """
    tab = premio.tabela(alvo)
    base = tab.get("base") or {}
    filiais = {g: sorted(v.keys()) for g, v in base.items()}
    quantas = sum(len(v) for v in filiais.values())
    if tab.get("motivo"):
        pode, falta = False, tab["motivo"]
    elif not quantas:
        pode, falta = False, ("nenhuma filial com valor base cadastrado — a "
                              "régua calcula tudo e não paga nada")
    else:
        pode, falta = True, ""
    return {"pode": pode, "motivo": falta, "filiais_com_valor": quantas,
            "grupos": {g: len(v) for g, v in filiais.items()},
            "versao": tab.get("versao"), "vigente_de": tab.get("vigente_de")}


def _grupo_agregado(alvo: str) -> dict:
    """O LADO DO AGREGADO, medido com a mesma leitura e dito separado.

    Frota e agregado se olham SEPARADOS — é a regra do programa (na campanha
    eles nem competem entre si), e juntá-los numa média só produziria um número
    que não descreve nenhum dos dois.

    O que dá para medir aqui e o que NÃO dá:

    - **a cobertura e a nota de cada PILAR dão**, e são as mesmas contas: a
      leitura da Gobrax, as ocorrências do ERP e os contadores do GR não sabem
      quem é CLT e quem é fornecedor, elas casam por CPF;
    - **a nota COMPOSTA não dá**, e é por isso que ela não sai daqui. A régua
      da premiação mensal pesa 40/40/20 e sai da FOLHA; a do agregado é a do
      regulamento da campanha, 50/30/20, e vive dentro de uma campanha
      cadastrada. Publicar uma nota composta do agregado pela régua da folha
      seria inventar uma régua que ninguém aprovou — e ela apareceria ao lado
      da nota da frota como se fossem comparáveis.

    Sem campanha criada, portanto, o agregado tem TAMANHO e COBERTURA, e a
    nota dele diz o que falta para existir.
    """
    from api.campanha import base as cbase
    from . import parametros, pilares

    try:
        pessoas = cbase.agregados_do_ciclo(alvo)
    except Exception:  # noqa: BLE001
        return {"rotulo": "Agregados", "motoristas": None,
                "motivo": "ERP indisponível — não foi possível contar",
                "pilares": [], "nota": None}

    if not pessoas:
        return {"rotulo": "Agregados", "motoristas": 0,
                "motivo": "nenhum agregado com viagem neste ciclo",
                "pilares": [], "nota": None}

    # A MESMA LEITURA DA CAMPANHA, e de propósito: a Gobrax casa por NOME (o
    # `vehicle-performance` não devolve documento), então o cadastro que vai
    # para ela precisa ser o do grupo que se quer medir.
    gbx = pilares.gobrax(alvo, cadastro=pessoas)
    de_para = parametros.depara()
    cond = pilares.comportamento_janela(alvo, 1, de_para)
    base_gr = parametros.ler(alvo, "RODOVIARIO")["valores"]
    gr = pilares.gr_janela(alvo, 1, parametros.pesos_gr(alvo),
                           base_gr["gr_minimo_viagens"], base_gr["gr_referencia"],
                           base_gr["gr_queda"], base_gr["gr_piso"])
    cond_ciclo = (cond["por_ciclo"].get(alvo) or {})
    gr_ciclo = (gr["por_ciclo"].get(alvo) or {})

    linhas = []
    for m in pessoas:
        cpf = m["cpf"]
        linhas.append({
            "gobrax": (gbx["notas"].get(cpf) or {}).get("nota"),
            "conduta": pilares.nota_comportamento(cond_ciclo.get(cpf)),
            "gr": (gr_ciclo.get(cpf) or {}).get("nota"),
        })
    return {
        "rotulo": "Agregados", "motoristas": len(pessoas), "motivo": "",
        "pilares": _pilares(linhas, {}),
        # Ver o docstring: a composta do agregado é da campanha, não daqui.
        "nota": None,
        "nota_motivo": ("a nota do agregado é a do regulamento da campanha "
                        "(50/30/20), não a da folha"),
    }


def _agregados(alvo: str) -> dict:
    """De quem a régua MENSAL não está falando, e por quê.

    A premiação mensal sai da FOLHA — `identidade.listar()` lê o Globus, e
    agregado não tem folha: ele é fornecedor, não empregado, e o prêmio dele
    não passa por folha de pagamento. Então o cadastro da GMA é frota própria,
    e só.

    Isso é uma decisão do modelo, não um esquecimento — mas um painel que
    mostrasse "82 motoristas" sem dizer o recorte estaria escondendo os **104
    agregados que rodaram no mesmo ciclo** (19/09/2026: são MAIS que os
    próprios). Quem lê "82" e conhece a operação conclui que o sistema perdeu
    gente.

    Onde eles entram é a CAMPANHA trimestral, e lá frota e agregado competem
    separados, cada um com o ranking do seu grupo.
    """
    from api.campanha import base as cbase
    d = cbase.quantos_agregados(alvo)
    return {
        "com_viagem": d.get("com_viagem"),
        "motivo": d.get("motivo") or "",
        "onde": ("fora da premiação mensal, que sai da folha — agregado "
                 "concorre na campanha trimestral"),
    }


def _campanha(alvo: str) -> dict:
    """A campanha trimestral, se houver uma vigente."""
    from api.campanha import armazenamento as arm
    try:
        camp = arm.vigente()
    except Exception as exc:  # noqa: BLE001
        log.warning("panorama: campanha indisponivel (%s)", type(exc).__name__)
        return {"existe": False, "motivo": "não foi possível ler a campanha"}
    if not camp:
        return {"existe": False,
                "motivo": "nenhuma campanha cadastrada — a aba Campanha cria"}
    return {"existe": True, "motivo": "", "id": camp["id"],
            "nome": camp.get("nome"), "ate_ciclo": camp.get("ate_ciclo"),
            "sorteio_em": camp.get("sorteio_em")}


#: O que vira linha de "o que falta decidir". Cada uma nomeia a AÇÃO, porque
#: contagem sem ação é um número que ninguém sabe o que fazer com.
def _pendencias(p: dict, pagar: dict, camp: dict) -> list[dict]:
    itens = []

    def junta(chave, quantos, rotulo, acao):
        if quantos:
            itens.append({"chave": chave, "quantos": int(quantos),
                          "rotulo": rotulo, "acao": acao})

    junta("depara", len(p.get("codigos_sem_depara") or []),
          "códigos de ocorrência sem de-para",
          "aba Ocorrências: dizer o que cada código significa na régua")
    junta("sem_codigo", p.get("ocorrencias_sem_codigo"),
          "ocorrências sem código no ERP",
          "não entram em nenhum pilar — corrigir no lançamento do ERP")
    junta("sem_filial", p.get("sem_filial"),
          "motoristas sem filial",
          "aba Motoristas: sem filial não há valor base, logo não há prêmio")
    junta("tipo_sugerido", p.get("tipo_sugerido"),
          "com o tipo apenas SUGERIDO",
          "aba Motoristas: confirmar rodoviário ou manobrista")
    junta("gobrax_fora", p.get("gobrax_fora_do_cadastro"),
          "nomes da Gobrax fora do cadastro",
          "aba Motoristas: sincronizar a folha ou ajustar o de-para")
    junta("gobrax_ambiguo", len(p.get("gobrax_ambiguos") or []),
          "nomes da Gobrax ambíguos",
          "dois cadastros casam com o mesmo nome — desempatar")
    if not pagar["pode"]:
        itens.append({"chave": "valores", "quantos": None,
                      "rotulo": "o ciclo não tem como pagar",
                      "acao": pagar["motivo"]})
    if not camp["existe"]:
        itens.append({"chave": "campanha", "quantos": None,
                      "rotulo": "campanha trimestral", "acao": camp["motivo"]})
    return itens


def montar(ciclo: str | None = None) -> dict:
    """O panorama do ciclo, pronto para a primeira aba da tela."""
    alvo = ciclo or ciclo_mod.atual()
    if not ciclo_mod.valido(alvo):
        raise ValueError(f"Ciclo inválido: {alvo!r}. Use 'AAAA-MM'.")

    d = _montado(alvo)
    linhas, kpis = d["linhas"], d["kpis"]
    pesos = (d["parametros"].get("RODOVIARIO") or {})
    sit = fechamento.situacao(alvo)
    pagar = _pagar(alvo)
    camp = _campanha(alvo)

    com_nota = kpis["com_nota"]
    completos = com_nota - kpis["com_pilar_faltando"]
    return {
        "ciclo": alvo,
        "rotulo": ciclo_mod.rotulo(alvo),
        # O RECORTE, dito no payload e não só no título: a régua mensal é de
        # FROTA PRÓPRIA. Ver `_agregados` e `_grupo_agregado`.
        "recorte": "frota própria (cadastro da folha)",
        "agregados": _agregados(alvo),
        # OS DOIS GRUPOS, SEPARADOS — nunca somados. A régua de cada um é
        # diferente (folha 40/40/20 × regulamento 50/30/20), e uma média
        # juntando os dois não descreveria nenhum dos dois.
        "grupos": {
            "FROTA": {
                "rotulo": "Frota própria", "motoristas": kpis["motoristas"],
                "motivo": "", "pilares": _pilares(linhas, pesos),
                "nota": kpis["nota_mediana"], "nota_motivo": "",
            },
            "AGREGADO": _grupo_agregado(alvo),
        },
        "fechado": bool(sit and sit.get("fechado")),
        # PARCIAL É DO CICLO, não da Gobrax: enquanto o ciclo não terminou,
        # toda leitura dele é de um pedaço. A tela hachura por isto.
        "em_curso": alvo == ciclo_mod.atual(),
        "medicao": {
            "motoristas": kpis["motoristas"],
            "com_nota": com_nota,
            "sem_nota": kpis["sem_nota"],
            "completos": completos,
            "com_pilar_faltando": kpis["com_pilar_faltando"],
            "pilares": _pilares(linhas, pesos),
        },
        "nota": {
            "mediana": kpis["nota_mediana"],
            # A NOTA NÃO SE PUBLICA SOZINHA: quem lê 98,5 precisa ler, no mesmo
            # cartão, que 81 de 82 saíram com pilar faltando.
            "completos": completos, "de": com_nota,
        },
        "categorias": kpis["por_categoria"],
        "status": kpis["por_status"],
        "serie": _serie(alvo, kpis),
        "pagar": pagar,
        "campanha": camp,
        "pendencias": _pendencias(d["pendencias"], pagar, camp),
        "fontes": d["fontes"],
    }
