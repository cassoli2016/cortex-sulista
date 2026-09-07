# -*- coding: utf-8 -*-
"""A nota dele na Gobrax, onde ele está pior que a frota, e o que fazer.

═══════════════════════════════════════════════════════════════════════════
O QUE É DELE E O QUE É DO VEÍCULO — a distinção que a tela não pode perder
═══════════════════════════════════════════════════════════════════════════
A Gobrax entrega DUAS coisas, em granularidades diferentes, e misturá-las é o
jeito mais fácil de este módulo mentir:

| | Fonte | Granularidade |
|---|---|---|
| nota e km do mês | `driversOverview` | **do MOTORISTA** |
| os 14 indicadores | `vehicle-performance` | **do VEÍCULO** |

Não existe indicador por motorista na API — foi medido, não suposto: o
`driversOverview` devolve `ID`, `Name`, `DocumentNumber`, `TotalKM` e `Score`,
e nada mais. Então "seu motor ficou 15% ligado parado" seria uma frase falsa:
o correto é "o veículo que você dirigiu ficou", e o payload carrega
`motoristas_no_mes` para a tela dizer quando o volante foi de mais gente.

Quando o veículo teve UM motorista no mês, os dois números coincidem na
prática — e é o caso comum: medido em 07/09/2026, 46 placas na competência
fechada e a maioria com um condutor só. Quando teve mais, o indicador continua
sendo mostrado, com a ressalva junto. Esconder seria pior: é o único sinal que
ele tem sobre a própria condução, e ele já ouve falar dele na conversa da
premiação.

═══════════════════════════════════════════════════════════════════════════
COMO O MOTORISTA CASA COM A GOBRAX
═══════════════════════════════════════════════════════════════════════════
**Pelo NOME normalizado**, e isso é uma heurística que se declara.

O `driversOverview` traz `DocumentNumber` (o CPF), que seria o casamento
exato — e ele é DESCARTADO na coleta de propósito, desde antes deste módulo:
o snapshot vai a disco e CPF não entra em arquivo que não precisa dele. O
`vehicle-performance`, que é a fonte dos indicadores, **nem devolve documento**:
só o nome do vínculo. Ou seja: mesmo com o CPF no snapshot, os indicadores
continuariam casando por nome. Uma exatidão que só vale para metade da tela
não paga o documento a mais em disco.

Medido em 07/09/2026 sobre os 80 vínculos ativos: **73 casam por CPF e 72 por
nome normalizado** — um de diferença. E o risco do nome (duas pessoas com o
mesmo) foi medido em vez de suposto: **zero nomes normalizados repetidos**
entre os 592 motoristas do ERP em doze meses, zero entre os 80 vínculos, zero
dentro do snapshot do mês. Mesmo assim há guarda: nome que casar com mais de
um registro NÃO casa com nenhum — errar para "não sei quem você é" é
recuperável; errar para o desempenho do colega, não.

A normalização é a mesma de `api/premiacao/coleta._norm` (tira o prefixo
"3781 - ", maiúscula, colapsa espaço), porque é a que já casa o cadastro da
Gobrax com o export dela.

═══════════════════════════════════════════════════════════════════════════
"O QUE MELHORAR" — de onde sai a lista, e por que ela é curta
═══════════════════════════════════════════════════════════════════════════
**A régua é a FROTA, não uma meta inventada.** Um número sozinho não decide
nada: "motor ligado parado em 15%" é muito? Só o resto da frota responde.
`performance.resumo_frota` já publica min/p25/mediana/p75/max, e é dele que sai
a comparação — a mesma referência que a tela da telemetria usa.

**MAS O CORTE DO CONSELHO É O QUARTO PIOR, NÃO A MEDIANA.** Pela mediana,
METADE da frota é cobrada em cada indicador por construção — e com catorze
indicadores praticamente todo mundo recebe três conselhos todo mês, o que
transforma a tela num ruído que se aprende a fechar. Pior: pega diferença que
não é diferença. Medido no primeiro motorista real (07/09/2026): freio motor
0,0% contra mediana 0,93% da frota — 0,93 ponto percentual num indicador que a
frota inteira quase não usa vira "melhore o freio motor" sem que haja o que
melhorar de fato.

Estar no QUARTO PIOR (pior que o `p75` onde menos é melhor, pior que o `p25`
onde mais é melhor) é um fato específico e explicável — "três em cada quatro
veículos da frota estão melhores que você nisto" — e sobra folga para quem já
está bem receber a resposta certa, que é **nenhum conselho**. Lista vazia aqui
é boa notícia e a tela diz isso; encher a tela de conselho para quem está bem é
como se ensina alguém a ignorar a tela.

**A NOTA DO FORNECEDOR NÃO ENTRA.** Medido sobre 108 veículos, seis dos
catorze indicadores vieram com `score` ZERO em 108 de 108 — régua que zera a
frota inteira não separa ninguém e não teria como ser explicada a um motorista
que perguntasse por que perdeu o prêmio. Aqui vale a distância até a mediana,
que é medida.

**SÓ ENTRA O QUE TEM AÇÃO DE MOTORISTA.** `movement` é 100 − `idle` (a mesma
torta contada do outro lado) e apareceria como um segundo conselho idêntico;
as pressões de pedal média e baixa não têm direção definida — mais pedal médio
é melhor que alto e pior que baixo, e a leitura depende do relevo. Aconselhar
sobre elas seria inventar. Elas continuam VISÍVEIS na lista completa, com o
número da frota ao lado; o que não fazem é virar cobrança.

**O TETO DE TRÊS** existe porque conselho em lista de dez é conselho que
ninguém segue. Sai o pior primeiro, medido pela distância até a mediana em
pontos percentuais.

O texto de cada conselho é conteúdo de domínio, escrito uma vez, aqui — não é
gerado, não vem de modelo de linguagem e não muda entre leitores. Motorista
que compara o próprio app com o do colega tem de ver a mesma frase.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from ..gobrax import performance as pf
from ..gobrax.motoristas import KM_PISO  # noqa: F401  (o piso é o da casa)
from ..premiacao import coleta as psnap

log = logging.getLogger("cortex.motorista.desempenho")

#: `KM_PISO` (500 km) vem IMPORTADO de `api/gobrax/motoristas.py`, e não
#: recopiado: é o piso do ranking da telemetria, e dois números iguais em dois
#: arquivos é um número que diverge. Nota de quem quase não rodou não compara
#: ninguém com ninguém — quem está abaixo aparece CONTADO, nunca escondido.

#: Quantos conselhos a tela publica. Ver o docstring: lista de dez não é lista.
TOPO_MELHORAR = 3

#: Diferença abaixo da qual não se cobra nada. Meio ponto percentual contra a
#: mediana é ruído de mês, não conduta — e um app que cobra ruído é um app que
#: se desliga. Mesma ideia do `trendChip` da casa, que chama de estável o que
#: varia menos de 1,5%.
FOLGA_PP = 0.5

#: Indicadores com ação clara de motorista. O resto continua na lista completa
#: (é dado dele), mas não vira conselho — ver o docstring.
ACIONAVEIS = ("idle", "greenRange", "speeding", "cruiseControl", "ecoRoll",
              "engineBrake", "leverage", "powerRange", "pedalPressureOnHig")

#: O QUE FAZER, por indicador. Conteúdo de domínio, escrito uma vez.
#:
#: Cada entrada tem `o_que` (o que o número mede, na língua de quem dirige) e
#: `como` (o que muda o número na prática). Nada aqui promete economia em
#: reais: o app não fala de dinheiro da empresa, e "isso te dá X% de diesel"
#: é uma promessa que depende de rota, carga e caminhão.
COMO_MELHORAR: dict[str, dict[str, str]] = {
    "idle": {
        "o_que": "Tempo com o motor ligado e o caminhão parado.",
        "como": ("Desligue o motor na fila, na doca e na espera de "
                 "documento. Motor em marcha lenta não carrega bateria de "
                 "verdade e conta contra você o tempo todo. Se for parada "
                 "longa com ar-condicionado, fale com a torre sobre o "
                 "procedimento da sua operação."),
    },
    "greenRange": {
        "o_que": "Tempo com o motor na faixa verde de rotação.",
        "como": ("Troque de marcha mais cedo, antes de o motor gritar. "
                 "Subida se vence com marcha certa e constante, não com giro "
                 "alto: acelerar até o fim do verde na subida gasta e não "
                 "adianta velocidade."),
    },
    "speeding": {
        "o_que": "Tempo acima da velocidade permitida.",
        "como": ("Excesso é a única coisa desta lista que vira multa e ponto "
                 "na sua CNH, além de nota. Ajuste a saída com a torre em vez "
                 "de recuperar atraso na estrada — o tempo que se ganha "
                 "correndo é minutos, e o que se perde é o dia inteiro."),
    },
    "cruiseControl": {
        "o_que": "Tempo com o piloto automático ligado.",
        "como": ("Em pista boa e plana, ligue o piloto. Ele segura a "
                 "velocidade com menos variação de pedal do que o pé — é o "
                 "jeito mais fácil de melhorar consumo sem mudar nada na "
                 "viagem. Em serra e chuva, o pé é melhor."),
    },
    "ecoRoll": {
        "o_que": "Tempo rodando de embalo, com o motor sem esforço.",
        "como": ("Tire o pé antes da descida e antes da curva, e deixe o "
                 "caminhão correr. Chegar acelerando até o ponto de frear "
                 "queima duas vezes: no diesel e na lona."),
    },
    "engineBrake": {
        "o_que": "Uso do freio motor.",
        "como": ("Use o freio motor na descida e ao reduzir, antes do pedal. "
                 "Ele segura o peso sem esquentar o freio de serviço e é o "
                 "que evita a descida com cheiro de lona queimada."),
    },
    "leverage": {
        "o_que": "Aproveitamento do embalo do caminhão.",
        "como": ("Leia a estrada à frente: soltar o acelerador cedo e usar o "
                 "peso do conjunto a favor rende mais que acelerar e frear. "
                 "Onde há subida logo após a descida, é aí que se ganha."),
    },
    "powerRange": {
        "o_que": "Tempo com o motor na faixa de potência (giro alto).",
        "como": ("Giro alto só é necessário em rampa forte e arrancada com "
                 "carga. Se o ponteiro vive lá, é marcha baixa demais para a "
                 "velocidade — subir uma marcha resolve."),
    },
    "pedalPressureOnHig": {
        "o_que": "Tempo com o acelerador afundado.",
        "como": ("Acelerador no fundo não faz o caminhão subir mais rápido "
                 "depois de certo ponto — só injeta mais diesel. Acelere "
                 "progressivo e segure o pé em três quartos."),
    },
}


def _norm(nome: str) -> str:
    """A mesma normalização de `api/premiacao/coleta._norm`.

    Não importada de lá porque é função privada de um módulo de COLETA, e este
    é de leitura — mas a regra é a mesma e está escrita nos dois: tira o
    prefixo numérico ("3781 - "), maiúscula, colapsa espaço.
    """
    s = re.sub(r"^\s*\d+\s*-\s*", "", nome or "")
    return " ".join(s.strip().upper().split())


def _competencias(hoje: date | None = None) -> tuple[str, str]:
    """(mês corrente, mês anterior) — as duas que o cache da Gobrax mantém.

    `scripts/coletar_telemetria.py` recoleta exatamente estas duas de 3 em 3
    horas; pedir uma terceira devolveria vazio e a tela diria "sem dado" sobre
    um mês que existe. O corrente é PARCIAL, e a tela diz isso.
    """
    hoje = hoje or date.today()
    corrente = hoje.strftime("%Y-%m")
    ant = hoje.replace(day=1)
    ant = (ant.replace(year=ant.year - 1, month=12) if ant.month == 1
           else ant.replace(month=ant.month - 1))
    return corrente, ant.strftime("%Y-%m")


def _placas_do_motorista(nome_norm: str, competencia: str) -> list[dict]:
    """As linhas de performance dos veículos que a GOBRAX vinculou a ele.

    O vínculo é o da própria Gobrax (`drivers` de cada registro de
    performance), não uma dedução nossa a partir da programação do ERP: se o
    fornecedor diz que o volante foi dele naquele veículo, é o dado dele que
    está no indicador.
    """
    saida = []
    for linha in pf.ler(competencia):
        nomes = {_norm(m.get("nome")) for m in (linha.get("motoristas") or [])}
        if nome_norm in nomes:
            saida.append({"linha": linha, "motoristas_no_mes": len(nomes)})
    return saida


def _placa_curta(placa: str) -> str:
    """"BCU6C04 - T3000" → "BCU6C04". O modelo vem colado no campo da Gobrax."""
    return (placa or "").split(" - ")[0].strip()


def _minha_nota(nome_norm: str, competencia: str) -> dict | None:
    """Nota, km e posição no ranking do mês, do snapshot da premiação.

    `so_cache` por construção: `ler_snapshot` lê arquivo. Fonte de tela do app
    JAMAIS dispara coleta externa — sair para a Gobrax aqui travaria a tela por
    dezenas de segundos no 4G de uma rodovia.
    """
    snap = psnap.ler_snapshot(competencia)
    if not snap or not isinstance(snap.get("drivers"), list):
        return None

    eu = [d for d in snap["drivers"] if _norm(d.get("driverName")) == nome_norm]
    # NOME AMBÍGUO NÃO CASA COM NINGUÉM. Medido: zero repetidos hoje — mas o
    # dia em que houver dois, mostrar o desempenho do colega é pior que dizer
    # "não te encontrei".
    if len(eu) != 1:
        if len(eu) > 1:
            log.warning("nome de motorista ambíguo no snapshot %s", competencia)
        return None
    eu = eu[0]

    #: O ranking tem PISO (500 km): quem quase não rodou não é ranqueado, e
    #: aparece contado em vez de escondido — a mesma regra da tela `telcond`.
    no_piso = sorted((d for d in snap["drivers"]
                      if d.get("nota") is not None
                      and float(d.get("km") or 0) >= KM_PISO),
                     key=lambda d: -float(d["nota"]))
    posicao = None
    for i, d in enumerate(no_piso, start=1):
        if _norm(d.get("driverName")) == nome_norm:
            posicao = i
            break
    notas = [float(d["nota"]) for d in no_piso]
    mediana = notas[len(notas) // 2] if notas else None

    return {
        "competencia": competencia,
        "parcial": bool(snap.get("parcial")),
        "nota": (float(eu["nota"]) if eu.get("nota") is not None else None),
        "km": round(float(eu.get("km") or 0)),
        "posicao": posicao,
        "ranqueados": len(no_piso),
        "abaixo_do_piso": len(snap["drivers"]) - len(no_piso),
        "km_piso": KM_PISO,
        "nota_mediana_frota": mediana,
        # Quem rodou pouco NÃO é ranqueado, e a tela diz por quê em vez de
        # mostrar um traço mudo.
        "sem_ranking_motivo": (None if posicao else
                               "Você rodou menos de %d km nesta competência — "
                               "abaixo disso a nota não entra no ranking."
                               % KM_PISO),
    }


def _evolucao(nome_norm: str) -> list[dict]:
    """A nota dele mês a mês, de todos os snapshots que existem em disco."""
    saida = []
    for idx in psnap.ler_index():
        snap = psnap.ler_snapshot(idx["month"])
        if not snap:
            continue
        eu = [d for d in snap["drivers"] if _norm(d.get("driverName")) == nome_norm]
        if len(eu) != 1 or eu[0].get("nota") is None:
            continue
        saida.append({"competencia": idx["month"],
                      "parcial": bool(idx.get("parcial")),
                      "nota": float(eu[0]["nota"]),
                      "km": round(float(eu[0].get("km") or 0))})
    saida.sort(key=lambda x: x["competencia"])
    return saida


def _distancia(pct: float, ref: float, menor_melhor: bool) -> float:
    """Quanto ele está PIOR que a referência, em pontos percentuais.

    Negativo = está melhor. O sinal é o que permite ordenar "o pior primeiro"
    sem um `if` em cada lugar que ordena.
    """
    return (pct - ref) if menor_melhor else (ref - pct)


def _indicadores(placas: list[dict], competencia: str) -> tuple[list, list]:
    """(lista completa, o que melhorar) — dos veículos dele, contra a frota."""
    resumo = {i["chave"]: i for i in pf.resumo_frota(competencia)["indicadores"]}
    if not placas:
        return [], []

    # Uma linha por indicador, MÉDIA PONDERADA PELA DURAÇÃO quando ele dirigiu
    # mais de um veículo. Média simples de percentual entre veículos daria o
    # mesmo peso a 600 h e a 8 h — e é assim que um dia de teste num caminhão
    # estranho passa a decidir o mês inteiro de alguém.
    completa, melhorar = [], []
    for chave in pf.ORDEM:
        num = den = 0.0
        motoristas = 0
        for p in placas:
            d = p["linha"].get(chave)
            if not isinstance(d, dict) or d.get("pct") is None:
                continue
            peso = float(d.get("h") or 0) or 1.0
            num += float(d["pct"]) * peso
            den += peso
            motoristas = max(motoristas, p["motoristas_no_mes"])
        if not den:
            continue
        pct = round(num / den, 2)
        ref = resumo.get(chave) or {}
        mediana = ref.get("mediana")
        menor_melhor = chave in pf.MENOR_MELHOR
        dist = (_distancia(pct, mediana, menor_melhor)
                if mediana is not None else None)
        # O QUARTO PIOR DA FROTA: acima do p75 onde menos é melhor, abaixo do
        # p25 onde mais é melhor. É este o corte do conselho — ver o docstring.
        corte = ref.get("p75") if menor_melhor else ref.get("p25")
        no_quarto_pior = bool(
            corte is not None
            and (_distancia(pct, corte, menor_melhor) > 0))
        item = {
            "chave": chave,
            "rotulo": pf.INDICADORES.get(chave, chave),
            "pct": pct,
            "menor_melhor": menor_melhor,
            "mediana_frota": mediana,
            "p25_frota": ref.get("p25"),
            "p75_frota": ref.get("p75"),
            "veiculos_na_frota": ref.get("veiculos"),
            "distancia_pp": (round(dist, 2) if dist is not None else None),
            "pior_que_a_frota": bool(dist is not None and dist > FOLGA_PP),
            "no_quarto_pior": no_quarto_pior,
            "motoristas_no_mes": motoristas,
        }
        completa.append(item)
        # AS TRÊS CONDIÇÕES, e cada uma corta uma coisa diferente: o quarto
        # pior (é desvio de verdade, não metade da frota), a folga em pontos
        # percentuais (não é ruído de décimo) e a lista de acionáveis (há o que
        # fazer a respeito). Tirar qualquer uma enche a tela.
        if (no_quarto_pior and item["pior_que_a_frota"]
                and chave in ACIONAVEIS):
            conselho = COMO_MELHORAR.get(chave) or {}
            melhorar.append({**item,
                             "o_que": conselho.get("o_que", ""),
                             "como": conselho.get("como", "")})

    melhorar.sort(key=lambda i: -(i["distancia_pp"] or 0))
    return completa, melhorar[:TOPO_MELHORAR]


def meu(sessao: dict) -> dict:
    """O desempenho de QUEM ESTÁ LOGADO. O nome sai da sessão.

    NÃO HÁ PARÂMETRO DE MOTORISTA, pela mesma razão de `viagem.minha`: um
    argumento que a rota pudesse preencher com o que veio do navegador seria a
    diferença entre um app e um buscador da operação alheia.
    """
    nome_norm = _norm(sessao.get("nome") or "")
    corrente, anterior = _competencias()

    if len(nome_norm) < 5:
        # Sem nome no vínculo não há como casar. Recusa DITA, não silêncio.
        return {"tem_dado": False,
                "motivo": ("Não consegui identificar você na telemetria. "
                           "Fale com a torre para conferir o seu cadastro."),
                "fonte": "Gobrax"}

    # A COMPETÊNCIA FECHADA VEM PRIMEIRO. O mês corrente é parcial por
    # construção e no dia 2 ele diz quase nada — um app que abre mostrando
    # "sua nota: 40" no dia 2 é um app que ninguém abre no dia 3.
    placas = _placas_do_motorista(nome_norm, anterior)
    competencia = anterior
    if not placas:
        placas = _placas_do_motorista(nome_norm, corrente)
        competencia = corrente if placas else anterior

    nota = _minha_nota(nome_norm, anterior) or _minha_nota(nome_norm, corrente)
    completa, melhorar = _indicadores(placas, competencia)
    evolucao = _evolucao(nome_norm)

    # A EVOLUÇÃO CONTA COMO DADO. Medido em 07/09/2026: 25 dos 80 vinculados
    # não aparecem no snapshot de agosto — não porque a Gobrax não os conheça
    # (73 dos 80 estão lá), mas porque não rodaram veículo equipado NAQUELE
    # mês. Fechar a tela para quem tem histórico de junho seria apagar o
    # passado dele por causa de um mês parado.
    if not nota and not completa and not evolucao:
        return {"tem_dado": False,
                "motivo": ("Ainda não há telemetria sua na Gobrax. Ela cobre os "
                           "veículos com equipamento instalado — se você roda "
                           "num deles, fale com a torre."),
                "fonte": "Gobrax"}

    return {
        "tem_dado": True,
        "nota": nota,
        "evolucao": evolucao,
        "competencia": competencia,
        "parcial": competencia == corrente,
        "placas": sorted({_placa_curta(p["linha"]["placa"]) for p in placas}),
        # A RESSALVA DA GRANULARIDADE, no payload e não na página: é o servidor
        # que sabe quantas pessoas dividiram o volante.
        "veiculo_compartilhado": any(p["motoristas_no_mes"] > 1 for p in placas),
        "indicadores": completa,
        "melhorar": melhorar,
        # O CRITÉRIO VIAJA COM A LISTA. Sem ele a página teria de repetir a
        # régua num texto próprio, e texto repetido diverge no dia em que
        # alguém mexer só num dos dois lados.
        "melhorar_criterio": ("Aparece aqui o que está no quarto pior da frota "
                              "na mesma competência — não o que está abaixo da "
                              "média."),
        # LISTA VAZIA TEM DOIS MOTIVOS, E ELES NÃO PODEM DIZER A MESMA COISA.
        # "Nada a apontar" é um elogio; dito sobre uma competência em que não
        # houve medição nenhuma, é um elogio sobre dado que não existe — e o
        # motorista tomaria por confirmação de que está bem. Zero que é
        # ausência não é desempenho, aqui como em qualquer tela da casa.
        "melhorar_vazio": (
            "Nada a apontar: em todos os indicadores você está dentro ou "
            "melhor que a maior parte da frota."
            if completa else
            "Não há indicadores do veículo nesta competência — sem eles não "
            "dá para dizer se há algo a melhorar."),
        "ressalva": ("Os indicadores abaixo são do VEÍCULO no mês, não só seus: "
                     "é assim que a Gobrax mede. A comparação é com a frota na "
                     "mesma competência."),
        "fonte": ("Gobrax · driversOverview (nota e km, por motorista) e "
                  "vehicle-performance (indicadores, por veículo) · cache local"),
    }
