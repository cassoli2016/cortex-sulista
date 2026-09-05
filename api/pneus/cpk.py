# -*- coding: utf-8 -*-
"""CPK — custo por quilômetro do pneu. O número que decide compra.

CPK = custo da VIDA CORRENTE ÷ km rodado nesta vida. As duas metades vêm de
lugares diferentes e cada uma traz a sua armadilha.

**O CUSTO É O DA VIDA, não o da compra.** Um pneu na segunda vida não custou o
preço do pneu novo: custou a RECAPAGEM. Usar o preço de compra em toda vida faz
o recapado parecer caro e o novo parecer barato — exatamente ao contrário do
que a operação decide. Medido no cadastro: pneu novo tem mediana de R$ 1.500;
recapagem, R$ 610. Trocar um pelo outro erra o CPK em 2,5×.

**FAIXA FÍSICA NO CUSTO.** O campo tem R$ 0,01 e tem R$ 1.300.001,10 — os dois
são digitação, não pneu. Percentis medidos em 8.376 cadastros: p01 R$ 103,
mediana R$ 1.500, p95 R$ 2.180, p99 R$ 2.405. Fora de R$ 300–5.000 o custo não
vira CPK zero nem CPK astronômico: vira `n/d` com o bruto do lado e uma
contagem no aviso. Zero que é cadastro furado não é pneu barato.

**PISO DE MATERIALIDADE NO KM.** Um pneu montado há três semanas com 1.242 km
sai com CPK de R$ 1,20/km e encabeça a lista dos piores — sem ter nada de
errado. Ele só não rodou ainda. Ranking sem piso mente, e a mentira aqui é
sempre contra o pneu novo, que é o que acabou de ser comprado. Abaixo de
`KM_MINIMO` o pneu não é avaliado: fica "em formação", e a tela DIZ quantos são.

**O KM VEM DE `api/pneus/km.py`**, e leia o cabeçalho dele antes de mexer:
tração pelo odômetro do abastecimento, implemento pelo engate do manifesto, com
dedução de dia repetido que já custou 78% de inflação plausível.
"""
from __future__ import annotations

import logging

from api import pglocal, queries

from . import km as kmmod

log = logging.getLogger("cortex.pneus.cpk")

#: Faixa física do custo de um pneu de carga. Fora dela é cadastro, não preço.
#: A folga é grande de propósito: o objetivo é cortar o R$ 0,01 e o R$ 1,3
#: milhão, não discutir se um pneu premium custa R$ 2.400 ou R$ 2.600.
CUSTO_MIN, CUSTO_MAX = 300.0, 5000.0

#: Abaixo disto o pneu não rodou o bastante para o CPK dizer alguma coisa. Uma
#: vida de pneu de carga dá 100–150 mil km; 15 mil é ~10% dela — cedo para
#: julgar, tarde o bastante para o número parar de oscilar.
KM_MINIMO = 15000.0

#: Quantos dias para trás o km é medido. Amarra com a janela de `km.py`.
JANELA_DIAS = 365

# A INSTALAÇÃO MAIS RECENTE é a que abre a vida corrente. `DISTINCT ON` seria o
# idioma da casa, mas aqui o LATERAL sai mais barato: são 3.222 pneus e o
# índice `pne_evento_pneu` já está por (pneu_id, ocorrido_em).
BASE_SQL = """
SELECT p.id, upper(trim(p.placa_atual)) AS placa, p.posicao_atual,
       p.vida_atual, p.custo_aquisicao, p.filial, p.status,
       m.marca, m.modelo, m.medida, m.desenho,
       e.ocorrido_em AS instalado_em,
       v.custo       AS custo_recapagem
FROM pne_pneu p
LEFT JOIN pne_modelo m ON m.id = p.modelo_id
LEFT JOIN pne_vida   v ON v.pneu_id = p.id AND v.numero = p.vida_atual
JOIN LATERAL (
  SELECT ocorrido_em FROM pne_evento
  WHERE pneu_id = p.id AND tipo = 'instalacao'
  ORDER BY ocorrido_em DESC LIMIT 1) e ON true
WHERE p.placa_atual IS NOT NULL AND trim(p.placa_atual) <> ''
"""


def _custo_da_vida(linha: dict) -> tuple[float | None, str, str | None]:
    """(custo, de onde veio, motivo da recusa). Nunca inventa."""
    vida = int(linha.get("vida_atual") or 1)
    if vida > 1:
        # SEGUNDA VIDA EM DIANTE: quem pagou foi a recapagem.
        c = linha.get("custo_recapagem")
        if c is None:
            return None, "recapagem", ("vida %d sem custo de recapagem "
                                       "registrado" % vida)
        origem = "recapagem"
    else:
        c = linha.get("custo_aquisicao")
        if c is None:
            return None, "aquisicao", "sem custo de aquisição no cadastro"
        origem = "aquisicao"

    c = float(c)
    if not (CUSTO_MIN <= c <= CUSTO_MAX):
        # FORA DA FAIXA FÍSICA. O bruto vai junto: quem for corrigir o cadastro
        # precisa ver o que está lá, e esconder o valor esconde o defeito.
        return None, origem, ("custo fora da faixa física (R$ %.2f)" % c)
    return c, origem, None


def _calcular(janela_dias: int = JANELA_DIAS) -> dict:
    linhas = pglocal.query(BASE_SQL, {})
    itens: list = []
    fora_da_faixa = sem_custo = sem_km = em_formacao = 0

    for L in linhas:
        custo, origem, motivo = _custo_da_vida(dict(L))
        r = kmmod.no_periodo(L["placa"], L["instalado_em"],
                             dias_janela=janela_dias)
        item = {
            "id": L["id"], "placa": L["placa"], "posicao": L["posicao_atual"],
            "vida": L["vida_atual"], "filial": L["filial"],
            "marca": L["marca"], "modelo": L["modelo"], "medida": L["medida"],
            "instalado_em": (L["instalado_em"].isoformat()
                             if L["instalado_em"] else None),
            "km": r.get("km"), "km_metodo": r.get("metodo"),
            "km_dias": r.get("dias_com_dado"),
            "km_parcial": bool(r.get("truncado_em")),
            "custo": custo, "custo_origem": origem,
            "custo_bruto": (float(L["custo_aquisicao"])
                            if L.get("custo_aquisicao") is not None else None),
            "cpk": None, "motivo": None,
        }

        if custo is None:
            item["motivo"] = motivo
            if motivo and "faixa" in motivo:
                fora_da_faixa += 1
            else:
                sem_custo += 1
        elif r.get("km") is None:
            item["motivo"] = r.get("motivo") or "sem km na janela"
            sem_km += 1
        elif r["km"] < KM_MINIMO:
            # EM FORMAÇÃO, não "ruim". Um pneu de três semanas com CPK alto não
            # tem defeito nenhum — ele só não rodou. Rankeá-lo puniria sempre o
            # pneu recém-comprado.
            item["motivo"] = ("rodou %s km — abaixo do piso de %s km para "
                              "avaliar" % (format(int(r["km"]), ","),
                                           format(int(KM_MINIMO), ",")))
            em_formacao += 1
        else:
            item["cpk"] = round(custo / r["km"], 4)
        itens.append(item)

    # A LISTA JA SAI ORDENADA, e os sem CPK vão para o fim. Ordenar só uma
    # cópia interna deixava o consumidor com a lista crua e a ordenação virava
    # código morto — quem lesse `itens` acharia que estava ordenado.
    avaliados = [i for i in itens if i["cpk"] is not None]
    avaliados.sort(key=lambda i: i["cpk"])
    itens = avaliados + [i for i in itens if i["cpk"] is None]
    return {
        "itens": itens,
        "total": len(itens),
        "avaliados": len(avaliados),
        "em_formacao": em_formacao,
        "sem_km": sem_km,
        "sem_custo": sem_custo,
        "custo_fora_da_faixa": fora_da_faixa,
        "cpk_mediano": (avaliados[len(avaliados) // 2]["cpk"]
                        if avaliados else None),
        "piso_km": KM_MINIMO,
        "faixa_custo": [CUSTO_MIN, CUSTO_MAX],
        "janela_dias": janela_dias,
    }


# TTL de meia hora: o km por baixo já é cacheado por uma hora, e o cadastro de
# pneu muda algumas vezes por dia — não a cada abertura de tela.
obter = queries.cached(1800, velha_ate=6 * 3600)(_calcular)


def por_modelo(janela_dias: int = JANELA_DIAS) -> dict:
    """CPK por MODELO — é aqui que a compra se decide, não pneu a pneu.

    MEDIANA, nunca média: um pneu com CPK de 70× move a média o bastante para
    se inocentar, e a régua passa a caber em cima do próprio outlier. E modelo
    com poucos pneus avaliados não é avaliado: a tela diz a cobertura em vez de
    chamar de "melhor" o que mediu em três pneus.
    """
    d = obter(janela_dias)
    grupos: dict = {}
    for i in d["itens"]:
        if i["cpk"] is None:
            continue
        chave = "%s|%s|%s" % (i["marca"] or "?", i["modelo"] or "?",
                              i["medida"] or "?")
        g = grupos.setdefault(chave, {"marca": i["marca"], "modelo": i["modelo"],
                                      "medida": i["medida"], "cpks": [],
                                      "kms": [], "km": 0.0})
        g["cpks"].append(i["cpk"])
        g["kms"].append(i["km"] or 0.0)
        g["km"] += i["km"] or 0.0

    fora = []
    for g in grupos.values():
        v = sorted(g["cpks"])
        ks = sorted(g["kms"])
        fora.append({"marca": g["marca"], "modelo": g["modelo"],
                     "medida": g["medida"], "pneus": len(v),
                     "cpk_mediano": v[len(v) // 2],
                     # A MATURIDADE VAI JUNTO DO CPK, e não é enfeite: ver a
                     # ressalva no fim desta função.
                     "km_mediano": round(ks[len(ks) // 2], 0),
                     "km_total": round(g["km"], 0),
                     # MATERIALIDADE DECLARADA, não filtro escondido: a tela
                     # mostra os poucos com badge em vez de sumir com eles.
                     "suficiente": len(v) >= 5})
    fora.sort(key=lambda x: x["cpk_mediano"])
    return {"modelos": fora,
            "com_base": sum(1 for x in fora if x["suficiente"]),
            "total": len(fora), "minimo_pneus": 5,
            "avaliados": d["avaliados"], "piso_km": d["piso_km"],
            # A RESSALVA VIAJA COM O NÚMERO. Este CPK é ACUMULADO ATÉ HOJE, não
            # o da vida inteira: um pneu com 40 mil dos 120 mil km que ele vai
            # dar mostra um CPK três vezes maior que o final. Isso não impede
            # comparar modelos — impede comparar modelos de MATURIDADES
            # diferentes. Por isso `km_mediano` sai ao lado de `cpk_mediano`:
            # dois modelos com km medianos parecidos comparam-se direto; com km
            # medianos muito distantes, quem tem menos km aparece pior sem ser.
            "ressalva": ("CPK acumulado até hoje, não da vida inteira — "
                         "compare modelos com km mediano parecido"),
            "acumulado": True}
