# -*- coding: utf-8 -*-
"""Quando cada pneu chega no limite — desgaste medido, não calendário.

O QUE ESTE MÓDULO RESPONDE. "Este pneu dura mais quanto tempo?" Pneu não se
mede em meses: dois pneus montados no mesmo dia, um num cavalo que faz 200 mil
km/ano e outro numa carreta parada, chegam ao limite com meio ano de diferença.
A régua é o quilômetro, e o quilômetro vem de `api/pneus/km.py`.

COMO A TAXA É MEDIDA. Duas medições de sulco do MESMO pneu na MESMA placa, e o
km rodado por aquela placa entre as duas datas. O sulco que vale é o MENOR dos
quatro — é ele que a lei mede e é ele que tira o pneu de circulação, não a
média dos sulcos, que esconde o ombro gasto de um pneu desalinhado.

O PISO DUPLO, e ele é o que separa taxa de ruído: menos de 5.000 km rodados ou
menos de 0,5 mm de diferença não vira taxa. Medido em produção: sem os pisos, a
mediana da frota dava ZERO — mais da metade dos pares tinha as duas medições
perto demais para o sulco mudar, e dividir um arredondamento por um km pequeno
produz qualquer número. Com os pisos, 78 pneus qualificam e a mediana dá
0,0967 mm por 1.000 km — uma vida implícita de 134 mil km de 16 mm até 3 mm,
que é a ordem de grandeza certa para pneu de carga.

A PROCEDÊNCIA DA TAXA VIAJA COM A PREVISÃO. Um pneu com série própria usa a
dele; sem série, usa a do MODELO; sem modelo com base, a da frota. As três
respondem à mesma pergunta com confianças muito diferentes, e apresentá-las
iguais faria alguém programar a troca de um pneu com base na média de outros.

O QUE ELE NÃO FAZ: não prevê quando NÃO HÁ base. Pneu sem taxa própria, de
modelo sem base e numa frota que ainda não acumulou série volta como `n/d` com
o motivo — inventar uma data aqui é pior que não responder, porque data de
troca vira ordem de compra.
"""
from __future__ import annotations

import datetime
import logging

from api import pglocal, queries

from . import km as kmmod

log = logging.getLogger("cortex.pneus.desgaste")

#: Onde o pneu sai de circulação. 1,6 mm é o mínimo legal (CONTRAN); 3 mm é
#: onde a operação tira para recapar — abaixo disso a carcaça já sofre, e o
#: pneu que passa do ponto não volta como recapagem, vira sucata.
LIMITE_LEGAL_MM = 1.6
LIMITE_RECAPE_MM = 3.0

#: O piso duplo. Ver o cabeçalho: sem ele a mediana da frota dá zero.
KM_MINIMO_PAR = 5000.0
DESGASTE_MINIMO_MM = 0.5

#: Quantos pneus um modelo precisa para a taxa dele valer como referência.
MODELO_MINIMO = 5

#: Sulco que SOBE entre duas medições não é desgaste negativo: é rodízio,
#: recapagem ou dedo trocado na digitação. Sai da conta em vez de virar taxa
#: negativa, que projetaria um pneu ficando novo com o uso.
TOLERANCIA_SUBIDA_MM = 0.3

JANELA_DIAS = 365

SERIE_SQL = """
SELECT i.pneu_id, upper(trim(i.placa)) AS placa, i.medido_em::date AS d,
       i.sulcos_mm, i.km_veiculo, p.modelo_id, p.vida_atual,
       upper(trim(p.placa_atual)) AS placa_atual, p.posicao_atual, p.status,
       m.marca, m.modelo, m.medida
FROM pne_inspecao i
JOIN pne_pneu p   ON p.id = i.pneu_id
LEFT JOIN pne_modelo m ON m.id = p.modelo_id
WHERE i.sulcos_mm IS NOT NULL
  AND i.placa IS NOT NULL AND trim(i.placa) <> ''
  AND i.medido_em >= now() - make_interval(days => %(dias)s)
ORDER BY i.pneu_id, i.medido_em, i.id
"""


def _menor(sulcos) -> float | None:
    """O MENOR dos quatro sulcos.

    É ele que a lei mede e é ele que tira o pneu de circulação. A média
    esconderia o ombro gasto de um pneu desalinhado — que é justamente o caso
    em que a troca é urgente.
    """
    vs = [float(x) for x in (sulcos or []) if x is not None]
    return min(vs) if vs else None


def _taxa_do_par(placa, d0, s0, d1, s1, dias_janela, odo0=None, odo1=None):
    """mm por 1.000 km entre duas medições, ou None com o motivo.

    O HODÔMETRO DA INSPEÇÃO MANDA quando existe nas duas pontas. Ele é uma
    subtração entre duas leituras do MESMO painel — não depende de a placa
    casar com o cadastro do ERP, nem do engate do manifesto, nem da janela de
    365 dias. A derivação de `api/pneus/km.py` continua como plano B para o par
    que não tem as duas leituras, e é ela que atende as carretas, que não têm
    hodômetro nenhum.

    Devolve (taxa, motivo, origem_do_km) — e a origem viaja junto porque as
    duas medem a mesma coisa com confianças diferentes.
    """
    if s1 > s0 + TOLERANCIA_SUBIDA_MM:
        return None, "sulco subiu (rodízio, recapagem ou leitura trocada)", None
    gasto = s0 - s1
    if gasto < DESGASTE_MINIMO_MM:
        return None, "desgaste abaixo do piso de medição", None

    k, origem = None, None
    if odo0 is not None and odo1 is not None:
        direto = float(odo1) - float(odo0)
        # HODÔMETRO QUE ANDA PARA TRÁS é troca de painel, não km negativo.
        if direto > 0:
            k, origem = direto, "hodômetro"
    if k is None:
        r = kmmod.no_periodo(placa, d0, d1, dias_janela=dias_janela)
        k, origem = r.get("km"), "derivado"
    if not k or k < KM_MINIMO_PAR:
        return None, "km rodado abaixo do piso", None
    return gasto / (k / 1000.0), None, origem


def _pares(obs):
    """Os pares candidatos a sustentar a taxa, do mais confiável ao mais largo.

    AS PONTAS NÃO SÃO SEMPRE A MELHOR EVIDÊNCIA, e isso custou uma medição
    errada: a ponta mais antiga da série costuma ser uma FOTO do instantâneo,
    que não tem hodômetro. Pegar as pontas cegamente jogava para a derivação
    968 pneus que já tinham o par completo com hodômetro nas duas leituras.

    Mas trocar um pelo outro também não serve: o par com hodômetro tem janela
    mais curta e cai nos pisos com mais frequência — medido, ele ganhava 26
    medições diretas e perdia 43 pneus por completo.

    Então saem os dois, nesta ordem. Quem consome tenta o primeiro e cai no
    segundo se ele não qualificar.
    """
    com_km = [o for o in obs if o[2] is not None]
    if len(com_km) >= 2 and (com_km[0], com_km[-1]) != (obs[0], obs[-1]):
        yield com_km[0], com_km[-1]
    yield obs[0], obs[-1]


def _mediana(vs):
    v = sorted(vs)
    return v[len(v) // 2] if v else None


def _calcular(dias_janela: int = JANELA_DIAS) -> dict:
    linhas = pglocal.query(SERIE_SQL, {"dias": dias_janela})

    # A SÉRIE É POR (PNEU, PLACA): trocar de veículo troca o km e o desgaste,
    # e emendar os dois trechos misturaria dois regimes de uso.
    series: dict = {}
    ficha: dict = {}
    for r in linhas:
        s = _menor(r["sulcos_mm"])
        if s is None:
            continue
        series.setdefault((r["pneu_id"], r["placa"]), []).append(
            (r["d"], s, r.get("km_veiculo")))
        ficha.setdefault(r["pneu_id"], r)

    taxas_pneu: dict = {}
    por_modelo: dict = {}
    recusas: dict = {}
    origens: dict = {}
    for (pid, placa), obs in series.items():
        if len(obs) < 2:
            recusas["série com uma medição só"] = \
                recusas.get("série com uma medição só", 0) + 1
            continue
        # DOIS PARES, NESTA ORDEM, e o segundo NÃO é redundância. O par com
        # hodômetro mede direto mas costuma ter janela curta, e janela curta cai
        # nos pisos; as pontas têm janela larga mas km atribuído. Tentar só o
        # primeiro perdia 43 pneus para ganhar 26; tentar só o segundo deixava
        # 968 medições diretas sem uso. Tentar os dois fica com o melhor de
        # cada série, e a origem sai declarada.
        taxa = motivo = origem_km = None
        for (d0, s0, k0), (d1, s1, k1) in _pares(obs):
            taxa, motivo, origem_km = _taxa_do_par(placa, d0, s0, d1, s1,
                                                   dias_janela, k0, k1)
            if taxa is not None:
                break
        if taxa is None:
            recusas[motivo] = recusas.get(motivo, 0) + 1
            continue
        origens[origem_km] = origens.get(origem_km, 0) + 1
        # UM PNEU PODE TER RODADO EM DUAS PLACAS na janela. Fica a MAIOR taxa:
        # ela é a que chega ao limite primeiro, e é sobre ela que se programa.
        if taxa > taxas_pneu.get(pid, 0):
            taxas_pneu[pid] = taxa
        f = ficha.get(pid) or {}
        chave = "%s|%s|%s" % (f.get("marca") or "?", f.get("modelo") or "?",
                              f.get("medida") or "?")
        por_modelo.setdefault(chave, []).append(taxa)

    taxa_frota = _mediana(list(taxas_pneu.values()))
    taxa_modelo = {k: _mediana(v) for k, v in por_modelo.items()
                   if len(v) >= MODELO_MINIMO}

    return {
        "taxas_pneu": taxas_pneu,
        "taxa_modelo": taxa_modelo,
        "taxa_frota": round(taxa_frota, 4) if taxa_frota else None,
        "pneus_com_taxa": len(taxas_pneu),
        "modelos_com_taxa": len(taxa_modelo),
        "modelos_medidos": len(por_modelo),
        "recusas": recusas,
        # DE ONDE VEIO O KM DE CADA PAR. Hodômetro é medição direta; derivado é
        # atribuição. Ver o quanto de cada um sustenta a taxa da frota é o que
        # separa "a curva está boa" de "a curva está inteira em cima do plano B".
        "km_origens": origens,
        "piso_km": KM_MINIMO_PAR,
        "piso_mm": DESGASTE_MINIMO_MM,
        "janela_dias": dias_janela,
        "vida_implicita_km": (round(13.0 / taxa_frota * 1000)
                              if taxa_frota else None),
    }


obter = queries.cached(1800, velha_ate=6 * 3600)(_calcular)

ATUAIS_SQL = """
SELECT p.id, upper(trim(p.placa_atual)) AS placa, p.posicao_atual, p.vida_atual,
       p.filial, m.marca, m.modelo, m.medida,
       i.sulcos_mm, i.medido_em::date AS medido_em
FROM pne_pneu p
LEFT JOIN pne_modelo m ON m.id = p.modelo_id
JOIN LATERAL (
  SELECT sulcos_mm, medido_em FROM pne_inspecao
  WHERE pneu_id = p.id AND sulcos_mm IS NOT NULL
  ORDER BY medido_em DESC LIMIT 1) i ON true
WHERE p.placa_atual IS NOT NULL AND trim(p.placa_atual) <> ''
"""


def previsao(dias_janela: int = JANELA_DIAS) -> dict:
    """Quantos km e quantos dias faltam para cada pneu chegar ao limite.

    DOIS LIMITES, e a diferença decide coisas diferentes: 3 mm é quando o pneu
    tem de SAIR para recapar (passar disso perde a carcaça, que vale mais que
    o pneu), 1,6 mm é quando ele fica ILEGAL. Quem programa oficina olha o
    primeiro; quem responde por autuação olha o segundo.

    O DIA SAI DO KM DA PLACA, não do calendário: um pneu na carreta parada e
    outro no cavalo de dupla pegada, com o mesmo sulco, têm datas muito
    diferentes — e é essa diferença que o módulo existe para mostrar.
    """
    d = obter(dias_janela)
    km = kmmod.obter(dias_janela)
    hoje = datetime.date.today()

    itens, sem_taxa = [], 0
    for r in pglocal.query(ATUAIS_SQL, {}):
        sulco = _menor(r["sulcos_mm"])
        chave = "%s|%s|%s" % (r["marca"] or "?", r["modelo"] or "?",
                              r["medida"] or "?")
        # A ORDEM É A DA CONFIANÇA: a própria série, depois o modelo, depois a
        # frota. E a origem VAI JUNTO — três confianças diferentes apresentadas
        # iguais fariam alguém programar a troca de um pneu pela média de
        # outros sem saber.
        taxa, origem = d["taxas_pneu"].get(r["id"]), "própria"
        if taxa is None:
            taxa, origem = d["taxa_modelo"].get(chave), "modelo"
        if taxa is None:
            taxa, origem = d["taxa_frota"], "frota"

        item = {"id": r["id"], "placa": r["placa"], "posicao": r["posicao_atual"],
                "vida": r["vida_atual"], "filial": r["filial"],
                "marca": r["marca"], "modelo": r["modelo"], "medida": r["medida"],
                "sulco_mm": sulco,
                "medido_em": r["medido_em"].isoformat() if r["medido_em"] else None,
                "taxa_mm_1000km": round(taxa, 4) if taxa else None,
                "taxa_origem": origem if taxa else None,
                "km_ate_recape": None, "km_ate_legal": None,
                "dias_ate_recape": None, "data_recape": None, "motivo": None}

        if sulco is None:
            item["motivo"] = "sem medição de sulco"
        elif not taxa:
            # NÃO INVENTA DATA. Data de troca vira ordem de compra.
            item["motivo"] = ("sem taxa de desgaste medida — nem do pneu, nem "
                              "do modelo, nem da frota")
            sem_taxa += 1
        else:
            for alvo, campo in ((LIMITE_RECAPE_MM, "km_ate_recape"),
                                (LIMITE_LEGAL_MM, "km_ate_legal")):
                falta_mm = sulco - alvo
                item[campo] = (0 if falta_mm <= 0
                               else round(falta_mm / taxa * 1000))
            # JA PASSOU nao e PREVISAO. Um pneu abaixo do limite nao "vai
            # chegar la em zero dias": ele ja esta la, e o que ele precisa e
            # oficina hoje, nao entrar no planejamento da semana que vem.
            # Misturar os dois faz a lista de urgentes virar a lista dos
            # vencidos, e a previsao — que e o motivo deste modulo existir —
            # some embaixo deles.
            item["vencido"] = sulco <= LIMITE_RECAPE_MM
            item["ilegal"] = sulco <= LIMITE_LEGAL_MM
            v = (km.get("veiculos") or {}).get(r["placa"]) or {}
            km_dia = (v.get("km") or 0) / max(1, dias_janela)
            if km_dia > 0:
                dias = round(item["km_ate_recape"] / km_dia)
                item["dias_ate_recape"] = dias
                item["data_recape"] = (
                    hoje + datetime.timedelta(days=min(dias, 3650))).isoformat()
            else:
                item["motivo"] = "sem km rodado na janela para virar data"
        itens.append(item)

    # ORDEM: quem chega primeiro no limite aparece primeiro. Sem data vai para
    # o fim — é lacuna, não urgência.
    vencidos = [i for i in itens if i.get("vencido")]
    com = [i for i in itens
           if i["dias_ate_recape"] is not None and not i.get("vencido")]
    com.sort(key=lambda i: i["dias_ate_recape"])
    vencidos.sort(key=lambda i: i["sulco_mm"] or 0)
    sem = [i for i in itens
           if i["dias_ate_recape"] is None and not i.get("vencido")]

    urgentes = [i for i in com if i["dias_ate_recape"] <= 30]
    return {"itens": com + sem, "vencidos": vencidos,
            "total": len(itens), "com_previsao": len(com),
            "sem_taxa": sem_taxa, "urgentes_30d": len(urgentes),
            "vencidos_n": len(vencidos),
            "ilegais_n": sum(1 for i in vencidos if i.get("ilegal")),
            "taxa_frota_mm_1000km": d["taxa_frota"],
            "vida_implicita_km": d["vida_implicita_km"],
            "pneus_com_taxa_propria": d["pneus_com_taxa"],
            "modelos_com_taxa": d["modelos_com_taxa"],
            "limite_recape_mm": LIMITE_RECAPE_MM,
            "limite_legal_mm": LIMITE_LEGAL_MM,
            "recusas": d["recusas"],
            "ressalva": ("a taxa é medida sobre pares de medição com pelo menos "
                         "%s km e %s mm de diferença; a série ainda está "
                         "crescendo" % (int(KM_MINIMO_PAR), DESGASTE_MINIMO_MM)),
            "leitura_velha": d.get("leitura_velha")}
