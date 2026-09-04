# -*- coding: utf-8 -*-
"""O Parecer da DRE Gerencial: o número já estava na tela; aqui vem a CAUSA.

A tela tem Resultado (a cascata), Alavancas (quanto falta para virar) e
Panorama (o ranking conta a conta, com piso de materialidade e corte de
oscilação). Faltava a pergunta que o comitê faz depois de ver o ranking:
**por que essa conta se moveu, e isso é gestão ou é aritmética?**

Este módulo responde isso MEDINDO — nenhuma frase daqui é adjetivo. Ele nasceu
de uma análise feita à mão em 04/09/2026 cujo resultado mais valioso não foi
nenhum número novo: foi DESMONTAR as três maiores "pioras" do mês, que não eram
pioras. É essa desmontagem que virou código.

AS QUATRO COISAS QUE ELE FAZ, e por que cada uma existe

1. **Recorrente × não recorrente.** A linha "outras" desta casa já inverteu o
   sinal do resultado: R$ 11,2 milhões de venda de ativo e recuperação de
   crédito mascaravam prejuízo recorrente de R$ 1,10 milhão/mês. O parecer
   publica sempre os DOIS números e LISTA o que tirou, item a item, com o
   motivo — heurística escondida vira verdade do sistema.

2. **Par espelhado.** Duas contas que são as duas pontas do MESMO movimento
   caem em lados opostos do ranking, e quem lê uma só conclui o contrário do
   que aconteceu. Medido em ago/2026: DIESEL FROTA "piorou" R$ 484.529 e DIESEL
   AGREGADOS "melhorou" R$ 634.079 — é a mesma conta vista dos dois lados (a
   empresa compra todo o combustível e recupera o do agregado), e o combustível
   LÍQUIDO tinha melhorado R$ 149.551.

   A regra é estrutural, não uma lista de contas conhecidas: mesma conta do
   plano E **sinais opostos do próprio saldo** — uma ponta gasta, a outra
   recupera. O segundo teste não é decoração: sem ele, as três receitas de
   transporte (própria, municipal, agregados) caíam no mesmo balde por dividir
   a conta 3.1.1.01, e o módulo anunciava um "líquido" de R$ 1.004.805 que não
   quer dizer nada — são três receitas diferentes, não duas pontas de uma.

3. **A causa do movimento, pelo LANÇAMENTO.** Um delta de R$ 200 mil explicado
   por um lançamento só não é tendência, é evento — e sustenta outra decisão. A
   classificação sai da concentração real dos lançamentos do mês, nunca de
   adjetivo, e o denominador é o TOTAL DA CONTA no mês (o mesmo que a DRE
   publica), não a soma do que a consulta conseguiu trazer.

4. **Provisão em aberto.** O último mês do período sempre carrega provisão que
   ainda vai virar fatura; dizer o resultado dele sem essa ressalva é publicar
   estimativa como fato. E só conta como ressalva a provisão que CICLA — a que
   teve provisão e baixa no ciclo anterior. Provisão de 13º e de férias não
   cicla: ela acumula, e somá-la à ressalva inflaria o aviso com dinheiro que
   não vai virar fatura nenhuma no dia 4.

A ARMADILHA QUE ESTE MÓDULO EXISTE PARA NÃO REPETIR
---------------------------------------------------
A primeira apuração à mão errou a provisão de pedágio de agosto/2026 somando o
SALDO DO DIA 31/08 na conta de agregados (R$ 268.172,89) como se tudo fosse
provisão — quando a provisão era UM lançamento de R$ 255.844,76 e os outros 53
eram vale-pedágio diário, consumo efetivo. O erro tinha duas caudas: inflou a
ressalva em R$ 12.328,13 e, pior, fez a análise "desmentir" uma medição correta
da casa (a queda de R$ 120.503,76 na provisão de agregados, que reproduz EXATA
quando se compara o lançamento de provisão em vez do total do dia).

Por isso `provisoes()` acha a provisão pela CONTRAPARTIDA — a conta de passivo
que recebe o crédito — e devolve o LANÇAMENTO, com sequência e histórico.
**Saldo de dia não é provisão**, e nenhuma conta de custo entra nessa medida.
"""
from __future__ import annotations

import calendar
import datetime
import logging
import re

from . import db, dre_alavancas, dre_exclusoes, queries

log = logging.getLogger("cortex.dre_parecer")

#: Linhas da DRE cujo conteúdo é não recorrente por NATUREZA. Vem do
#: `DRE_MODELO` de `queries`, não de palpite.
LINHAS_NAO_RECORRENTES = ("RESULTADO NAO OPERACIONAL",)

#: Termos que marcam conta não recorrente DENTRO de linha operacional. É
#: heurística sobre o NOME da conta — por isso ela se declara na resposta
#: (`recorrencia.criterio`) e o resultado sai publicado das duas formas.
TERMOS_NAO_RECORRENTES = (
    "RECUPERACAO DE CUSTO", "RECUPERACAO DE DESPESA", "RECUPERACAO DE CREDITO",
    "VENDA DE SUCATA", "REEMBOLSO",
)

#: Fração do movimento do mês que um punhado de lançamentos precisa explicar
#: para o movimento deixar de ser "espalhado". 60% é onde a conversa muda de "a
#: operação inteira mudou" para "foi aquele lançamento ali".
CONCENTRACAO = 0.60

#: Quantos lançamentos ainda contam como "poucos".
POUCOS_LANCAMENTOS = 3

#: Quantas contas de cada lado do ranking recebem drill.
CONTAS_COM_DRILL = 6

#: Provisão no ERP desta casa: o histórico abre com "VLR REF PROV" e a baixa
#: com "VLR REF BAIXA PROV". Medido no razão, não suposto.
RE_PROVISAO = re.compile(r"\bPROV\b|PROVIS", re.IGNORECASE)


def _ultimo_dia(mes: str) -> datetime.date:
    a, m = int(mes[:4]), int(mes[5:7])
    return datetime.date(a, m, calendar.monthrange(a, m)[1])


def _mes_seguinte(mes: str) -> str:
    return (_ultimo_dia(mes) + datetime.timedelta(days=1)).strftime("%Y-%m")


def _mes_anterior(mes: str) -> str:
    primeiro = datetime.date(int(mes[:4]), int(mes[5:7]), 1)
    return (primeiro - datetime.timedelta(days=1)).strftime("%Y-%m")


def _brl(v: float) -> str:
    return dre_alavancas._brl(v)


# --------------------------------------------------------------------------
# 1. recorrente x nao recorrente
# --------------------------------------------------------------------------
def _e_nao_recorrente(linha: str, conta: str) -> str:
    """O MOTIVO da exclusão, ou "" quando a conta é recorrente."""
    if linha in LINHAS_NAO_RECORRENTES:
        return "linha não operacional da DRE"
    nome = (conta or "").upper()
    for termo in TERMOS_NAO_RECORRENTES:
        if termo in nome:
            return "nome da conta contém %r" % termo.title()
    return ""


def recorrencia(dre: dict) -> dict:
    """Separa o resultado publicado do RECORRENTE, mês a mês.

    Devolve a lista do que foi tirado, com valor e motivo: quem discorda da
    classificação precisa ver o item, não só o total.
    """
    meses = dre["meses"]
    publicado = {m: 0.0 for m in meses}
    nao_rec = {m: 0.0 for m in meses}
    itens: dict = {}

    for l in dre["linhas"]:
        if l["rotulo"] == "RESULTADO DO EXERCICIO":
            publicado = {m: l["meses"].get(m, 0.0) for m in meses}

    for l in dre["linhas"]:
        # linha de fórmula repete valor já contado no detalhe: entrar aqui
        # dobraria o total
        if l.get("tipo") == "formula":
            continue
        for a in (l.get("detalhe") or []):
            for c in (a.get("contas") or []):
                motivo = _e_nao_recorrente(l["rotulo"], c.get("conta") or "")
                if not motivo:
                    continue
                chave = "%s|%s" % (c["grupo"], c["reduzido"])
                total = 0.0
                for m in meses:
                    v = c["meses"].get(m, 0.0)
                    nao_rec[m] += v
                    total += v
                itens[chave] = {
                    "conta": c.get("conta"), "grupo": c["grupo"],
                    "reduzido": c["reduzido"], "linha": l["rotulo"],
                    "agrupador": a["agrupador"], "motivo": motivo,
                    "total": round(total, 2),
                    "meses": {m: round(c["meses"].get(m, 0.0), 2)
                              for m in meses},
                }

    recorrente = {m: publicado[m] - nao_rec[m] for m in meses}
    n = len(meses) or 1
    return {
        "meses": meses,
        "publicado": {m: round(publicado[m], 2) for m in meses},
        "nao_recorrente": {m: round(nao_rec[m], 2) for m in meses},
        "recorrente": {m: round(recorrente[m], 2) for m in meses},
        "total_publicado": round(sum(publicado.values()), 2),
        "total_nao_recorrente": round(sum(nao_rec.values()), 2),
        "total_recorrente": round(sum(recorrente.values()), 2),
        "media_publicado": round(sum(publicado.values()) / n, 2),
        "media_recorrente": round(sum(recorrente.values()) / n, 2),
        "itens": sorted(itens.values(), key=lambda x: -abs(x["total"])),
        "criterio": (
            "Não recorrente = tudo na linha %s, mais conta cujo nome contém %s. "
            "É critério declarado sobre o NOME da conta, não campo do ERP: o "
            "resultado sai publicado nas duas formas e a lista mostra o que foi "
            "tirado." % (" ou ".join(LINHAS_NAO_RECORRENTES),
                         ", ".join(t.title() for t in TERMOS_NAO_RECORRENTES))),
    }


# --------------------------------------------------------------------------
# 2. par espelhado: duas pontas do mesmo movimento
# --------------------------------------------------------------------------
def _conta_do_plano(estrutural: str) -> str:
    """A conta do PLANO (4.1.1.01), sem o item — o nível em que duas pontas do
    mesmo movimento moram: diesel comprado e diesel recuperado."""
    partes = (estrutural or "").split(".")
    return ".".join(partes[:4]) if len(partes) >= 4 else (estrutural or "")


def espelhos(pan: dict) -> list[dict]:
    """Contas em lados OPOSTOS do ranking que são o mesmo movimento.

    DOIS testes, e o segundo é o que separa o par verdadeiro do falso:
      (a) mesma conta do plano;
      (b) SINAIS OPOSTOS DO SALDO — uma ponta gasta, a outra recupera.

    Sem (b), três receitas irmãs viram um "par" de três pontas e o líquido
    anunciado não significa nada.
    """
    por_conta: dict = {}
    for lado in ("piorou", "melhorou"):
        for it in (pan.get(lado) or []):
            chave = _conta_do_plano(it.get("estrutural") or "")
            if not chave:
                continue
            por_conta.setdefault(chave, []).append(it)

    fora = []
    for chave, pontas in por_conta.items():
        if len(pontas) < 2:
            continue
        # (a) lados opostos do ranking
        if not (any(p["delta_rs"] < 0 for p in pontas)
                and any(p["delta_rs"] > 0 for p in pontas)):
            continue
        # (b) sinais opostos do SALDO: uma gasta, a outra recupera
        if not (any(p["valor_ultimo"] < 0 for p in pontas)
                and any(p["valor_ultimo"] > 0 for p in pontas)):
            continue
        liquido = sum(p["delta_rs"] for p in pontas)
        fora.append({
            "conta_do_plano": chave,
            "pontas": [{"conta": p["nome"], "grupo": p["grupo"],
                        "reduzido": p["reduzido"], "agrupador": p["agrupador"],
                        "delta_rs": round(p["delta_rs"], 2),
                        "valor_ultimo": round(p["valor_ultimo"], 2)}
                       for p in sorted(pontas, key=lambda x: x["delta_rs"])],
            "liquido": round(liquido, 2),
            "leitura": (
                "Uma ponta gasta e a outra recupera, na mesma conta do plano "
                "%s. O líquido é %s — ler qualquer ponta sozinha inverte a "
                "conclusão." % (chave, _brl(liquido))),
        })
    fora.sort(key=lambda x: -abs(x["liquido"]))
    return fora


# --------------------------------------------------------------------------
# 3. a causa, pelo lancamento — TODAS as contas numa consulta so
# --------------------------------------------------------------------------
#: Uma consulta por conta custava 12 idas ao ERP e trinta segundos de tela. A
#: janela move os três maiores de CADA conta de uma vez, e de quebra some com o
#: teto de 500 do drill: aqui a contagem e o total são exatos.
SQL_CAUSAS = """
WITH lanc AS (
  SELECT l.grupo, l.reduzido, l.sequencia, l.dtlancamento,
         l.historicodescricao,
         (coalesce(l.valordebito,0) - coalesce(l.valorcredito,0))::float8 AS v
  FROM lancamento l
  JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
    AND p.ativoinativo = 1
  WHERE l.dtlancamento >= %%(de)s::date AND l.dtlancamento < %%(ate)s::date
    AND coalesce(l.historico, 0) <> 18
    AND p.estrutural ~ '^[34]'
    AND (%s)%s
),
ord AS (
  SELECT grupo, reduzido, sequencia, dtlancamento, historicodescricao, v,
         row_number() OVER (PARTITION BY grupo, reduzido
                            ORDER BY abs(v) DESC, sequencia) AS rn,
         count(*)     OVER (PARTITION BY grupo, reduzido) AS n,
         sum(abs(v))  OVER (PARTITION BY grupo, reduzido) AS bruto,
         sum(v)       OVER (PARTITION BY grupo, reduzido) AS liquido
  FROM lanc
)
SELECT * FROM ord WHERE rn <= %%(top)s
ORDER BY grupo, reduzido, rn
"""


def causas(alvos: list[tuple[int, int]], mes: str) -> dict:
    """Classifica o movimento de VÁRIAS contas no mês, numa consulta só.

    `alvos` são pares (grupo, reduzido). A chave da resposta é "grupo|reduzido".
    """
    if not alvos:
        return {}
    de = "%s-01" % mes
    ate = "%s-01" % _mes_seguinte(mes)

    ors, params = [], {"de": de, "ate": ate, "top": POUCOS_LANCAMENTOS}
    for i, (g, r) in enumerate(alvos):
        ors.append("(l.grupo = %%(g%d)s AND l.reduzido = %%(r%d)s)" % (i, i))
        params["g%d" % i] = int(g)
        params["r%d" % i] = int(r)

    # a exclusão gerencial vale aqui também: lançamento tirado do resultado não
    # pode reaparecer explicando um movimento que ele não causou
    chs = dre_exclusoes.chaves(de, ate)
    fexc = dre_exclusoes.filtro_sql("l", len(chs))
    params.update(dre_exclusoes.filtro_params(chs))

    sql = SQL_CAUSAS % (" OR ".join(ors), fexc)
    try:
        linhas = db.query(sql, params)
    except Exception as exc:
        log.warning("causas falhou: %s", type(exc).__name__)
        return {}

    por_conta: dict = {}
    for r in linhas:
        chave = "%s|%s" % (r["grupo"], r["reduzido"])
        por_conta.setdefault(chave, []).append(r)

    fora = {}
    for chave, rs in por_conta.items():
        n = int(rs[0]["n"])
        bruto = float(rs[0]["bruto"]) or 1.0
        maior = rs[0]
        top = sum(abs(float(x["v"])) for x in rs[:POUCOS_LANCAMENTOS])
        frac_maior = abs(float(maior["v"])) / bruto
        frac_top = top / bruto

        hist = (maior["historicodescricao"] or "").strip()
        data = maior["dtlancamento"]
        e_prov = bool(RE_PROVISAO.search(hist)) and data == _ultimo_dia(mes)

        if e_prov:
            tipo = "provisão"
            motivo = ("o maior lançamento (%s) é provisão do último dia do "
                      "mês — parte deste número é estimativa: %s"
                      % (_brl(float(maior["v"])), hist[:90]))
        elif frac_maior >= CONCENTRACAO:
            tipo = "evento único"
            motivo = ("1 lançamento de %s explica %.0f%% do movimento do mês "
                      "(%d lançamentos no total) — não é tendência"
                      % (_brl(float(maior["v"])), 100 * frac_maior, n))
        elif frac_top >= CONCENTRACAO:
            tipo = "concentrado"
            motivo = ("%d lançamentos explicam %.0f%% do movimento, de %d no "
                      "mês" % (min(POUCOS_LANCAMENTOS, n), 100 * frac_top, n))
        else:
            tipo = "espalhado"
            motivo = ("%d lançamentos, o maior com %.0f%% do movimento — é a "
                      "operação inteira, não um lançamento"
                      % (n, 100 * frac_maior))

        fora[chave] = {
            "tipo": tipo, "motivo": motivo, "lancamentos": n,
            "bruto": round(bruto, 2), "liquido": round(float(rs[0]["liquido"]), 2),
            "maiores": [{
                "valor": round(float(x["v"]), 2),
                "fracao": round(abs(float(x["v"])) / bruto, 4),
                "historico": (x["historicodescricao"] or "").strip()[:160],
                "data": x["dtlancamento"].isoformat()
                if hasattr(x["dtlancamento"], "isoformat")
                else x["dtlancamento"],
                "sequencia": x["sequencia"],
            } for x in rs],
        }
    return fora


# --------------------------------------------------------------------------
# 4. provisao aberta no ultimo mes
# --------------------------------------------------------------------------
#: A provisão se acha pela CONTRAPARTIDA — a conta de PASSIVO que recebe o
#: crédito — nunca somando o dia de uma conta de custo: no mesmo dia convivem a
#: provisão e o consumo efetivo, e somá-los infla a ressalva.
SQL_PROVISAO = """
SELECT l.grupo, l.reduzido, l.sequencia, l.dtlancamento::date AS dia,
       p.descricao AS conta, l.historicodescricao AS historico,
       coalesce(l.valorcredito, 0)::float8 AS valor
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
WHERE l.dtlancamento = %(dia)s::date
  AND p.estrutural ~ '^2'
  AND strpos(upper(coalesce(l.historicodescricao, '')), 'PROV') > 0
  AND coalesce(l.valorcredito, 0) > 0
ORDER BY coalesce(l.valorcredito, 0) DESC
LIMIT 60
"""

#: As baixas de provisão por conta numa JANELA. Serve duas perguntas com a
#: mesma consulta: "a baixa deste mês já entrou?" e "esta conta CICLA?".
SQL_BAIXAS = """
SELECT l.grupo, l.reduzido, count(*) AS n,
       sum(coalesce(l.valordebito, 0))::float8 AS debito
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
WHERE l.dtlancamento > %(de)s::date AND l.dtlancamento <= %(ate)s::date
  AND p.estrutural ~ '^2'
  AND strpos(upper(coalesce(l.historicodescricao, '')), 'BAIXA PROV') > 0
GROUP BY l.grupo, l.reduzido
"""

#: Até onde a Contabilidade lançou. Limitado a hoje DE PROPÓSITO: o razão tem
#: lançamento com data futura (parcela programada), e `max(dtlancamento)` sem
#: teto respondia "dezembro" para a pergunta "até quando já foi lançado".
SQL_RAZAO_ATE = """
SELECT max(l.dtlancamento)::date AS ultimo FROM lancamento l
WHERE l.dtlancamento <= current_date
"""


def provisoes(mes: str) -> dict:
    """As provisões do ÚLTIMO DIA de `mes`, e se a baixa já entrou.

    Só entra na ressalva a provisão que CICLA — a que teve provisão e baixa no
    ciclo anterior. Provisão de 13º e férias acumula em vez de ciclar; contá-la
    aqui infla o aviso com dinheiro que não vira fatura nenhuma.
    """
    dia = _ultimo_dia(mes)
    anterior = _ultimo_dia(_mes_anterior(mes))
    fim_seguinte = _ultimo_dia(_mes_seguinte(mes))
    try:
        linhas = db.query(SQL_PROVISAO, {"dia": dia.isoformat()})
        baixas_agora = db.query(SQL_BAIXAS, {
            "de": dia.isoformat(), "ate": fim_seguinte.isoformat()})
        baixas_antes = db.query(SQL_BAIXAS, {
            "de": anterior.isoformat(), "ate": dia.isoformat()})
        razao_ate = (db.query(SQL_RAZAO_ATE) or [{}])[0].get("ultimo")
    except Exception as exc:
        log.warning("provisoes falhou: %s", type(exc).__name__)
        return {"erro": "não foi possível ler as provisões do ERP",
                "itens": [], "abertas": [], "total": 0.0,
                "total_aberto": 0.0, "mes": mes}

    def _mapa(rs):
        return {"%s|%s" % (r["grupo"], r["reduzido"]):
                {"n": int(r["n"]), "debito": float(r["debito"])} for r in rs}

    agora, antes = _mapa(baixas_agora), _mapa(baixas_antes)

    itens = []
    for r in linhas:
        chave = "%s|%s" % (r["grupo"], r["reduzido"])
        cicla = chave in antes
        baixada = chave in agora
        itens.append({
            "conta": r["conta"], "grupo": r["grupo"],
            "reduzido": r["reduzido"], "sequencia": r["sequencia"],
            "dia": r["dia"].isoformat() if hasattr(r["dia"], "isoformat")
            else r["dia"],
            "historico": (r["historico"] or "").strip()[:160],
            "valor": round(float(r["valor"]), 2),
            "cicla": cicla, "baixada": baixada,
        })

    abertas = [i for i in itens if i["cicla"] and not i["baixada"]]
    return {
        "mes": mes, "dia": dia.isoformat(),
        "itens": itens, "abertas": abertas,
        "total": round(sum(i["valor"] for i in itens), 2),
        "total_aberto": round(sum(i["valor"] for i in abertas), 2),
        "razao_ate": razao_ate.isoformat()
        if hasattr(razao_ate, "isoformat") else razao_ate,
        "fonte": (
            "contas de passivo com PROV no histórico lançadas em %s, casadas "
            "com as baixas do ciclo anterior. A provisão é o LANÇAMENTO, nunca "
            "o saldo do dia: no mesmo dia convivem a provisão e o consumo "
            "efetivo." % dia.strftime("%d/%m/%Y")),
    }


# --------------------------------------------------------------------------
# o parecer
# --------------------------------------------------------------------------
def frases(p: dict) -> list[str]:
    """A narrativa DETERMINÍSTICA, montada do que foi medido.

    Ela é a base, não o rascunho: é ela que aparece quando o modelo local está
    fora do ar, e é ela que o modelo recebe para redigir por cima. Nenhum
    número desta casa passa por um modelo de linguagem antes de virar texto.
    """
    fora: list[str] = []
    rec = p.get("recorrencia") or {}
    per = p.get("periodo") or {}
    mes_ref = per.get("mes_referencia")
    meses = rec.get("meses") or []

    pub, recorr = rec.get("total_publicado"), rec.get("total_recorrente")
    if pub is not None and recorr is not None:
        if abs(pub - recorr) < 1.0:
            fora.append(
                "O resultado do período é %s, e ele é todo recorrente: não há "
                "venda de ativo nem recuperação de crédito sustentando o "
                "número." % _brl(pub))
        else:
            fora.append(
                "O resultado publicado do período é %s. Tirando o que não se "
                "repete (%s), o resultado RECORRENTE é %s — %s por mês. A "
                "diferença é o que não vai acontecer de novo."
                % (_brl(pub), _brl(rec.get("total_nao_recorrente") or 0),
                   _brl(recorr), _brl(rec.get("media_recorrente") or 0)))

    # a muleta que sumiu: mês de referência sem o não recorrente que os
    # outros meses tinham é a notícia, e ela não aparece em nenhum total
    serie = rec.get("nao_recorrente") or {}
    if mes_ref in serie and len(meses) > 1:
        antes = [serie[m] for m in meses[:-1]]
        media_antes = sum(antes) / len(antes) if antes else 0.0
        if abs(media_antes) > 1000 and abs(serie[mes_ref]) < abs(media_antes) / 4:
            fora.append(
                "Em %s o não recorrente foi %s, contra média de %s nos meses "
                "anteriores: o mês de referência não teve a muleta que os "
                "outros tiveram." % (mes_ref, _brl(serie[mes_ref]),
                                     _brl(media_antes)))

    # tendência do recorrente, por metades da série
    vals = [(rec.get("recorrente") or {}).get(m) for m in meses]
    vals = [v for v in vals if v is not None]
    if len(vals) >= 4:
        meio = len(vals) // 2
        a = sum(vals[:meio]) / meio
        b = sum(vals[meio:]) / (len(vals) - meio)
        if abs(b - a) < abs(a) * 0.05:
            fora.append("O recorrente é lateral: %s por mês na primeira "
                        "metade do período e %s na segunda."
                        % (_brl(a), _brl(b)))
        else:
            fora.append("O recorrente %s: de %s por mês na primeira metade do "
                        "período para %s na segunda."
                        % ("melhorou" if b > a else "piorou", _brl(a), _brl(b)))

    for e in (p.get("espelhos") or []):
        nomes = " e ".join(x["conta"] for x in e["pontas"])
        fora.append(
            "%s são as duas pontas do mesmo movimento (conta %s do plano): uma "
            "gasta, a outra recupera. O líquido é %s — ler qualquer uma delas "
            "sozinha inverte a conclusão."
            % (nomes, e["conta_do_plano"], _brl(e["liquido"])))

    pan = p.get("panorama") or {}
    cau = p.get("causas") or {}
    por_chave = {"%s|%s" % (it["grupo"], it["reduzido"]): it
                 for lado in ("piorou", "melhorou")
                 for it in (pan.get(lado) or [])}
    for chave, c in cau.items():
        it = por_chave.get(chave)
        if not it or c["tipo"] not in ("evento único", "provisão"):
            continue
        fora.append("%s (%s): %s." % (it["nome"], _brl(it["delta_rs"]),
                                      c["motivo"]))

    osc = pan.get("oscila") or []
    if osc:
        peso = sum(abs(o["delta_rs"]) for o in osc)
        fora.append(
            "%d contas saíram das listas por oscilar (coeficiente de variação "
            "acima de %.1f), somando %s de variação que não é alvo: atacá-las "
            "é perseguir ruído."
            % (len(osc), pan.get("cv_instavel") or CV_INSTAVEL, _brl(peso)))

    prov = p.get("provisoes") or {}
    if prov.get("erro"):
        fora.append("Não foi possível medir a provisão em aberto de %s: %s."
                    % (mes_ref, prov["erro"]))
    elif prov.get("abertas"):
        maior = max(prov["abertas"], key=lambda x: x["valor"])
        fora.append(
            "%s é o último mês e ainda carrega %s de provisão em aberto — a "
            "maior é %s na conta %s (sequência %s), e a baixa dela ainda não "
            "entrou. Parte deste mês é estimativa."
            % (mes_ref, _brl(prov["total_aberto"]), _brl(maior["valor"]),
               maior["conta"], maior["sequencia"]))
    elif prov.get("itens"):
        fora.append("As provisões de %s já foram baixadas: o mês não tem "
                    "estimativa pendurada." % mes_ref)
    return fora


#: O modelo REDIGE, não calcula. Ele recebe os fatos já medidos e formatados, e
#: a única liberdade que tem é a ordem e a prosa. Um parecer que inventa um
#: número não é um parecer ruim: é um documento perigoso, porque parece bom.
SISTEMA_NARRATIVA = """Você é o Controller de uma transportadora e escreve o \
parecer mensal da DRE Gerencial para o comitê de diretoria.

REGRAS ABSOLUTAS:
- Use SOMENTE os fatos e números da lista abaixo. NUNCA calcule, estime, \
arredonde ou invente um número que não esteja escrito ali.
- Se um fato não está na lista, ele não existe para você. Não preencha lacuna \
com suposição.
- Não dê conselho que a lista não sustente. Não prometa economia.
- Português do Brasil, tom direto e seco, sem adjetivo de entusiasmo.
- No máximo 5 parágrafos curtos. Comece pela conclusão.
- Se dois fatos forem as duas pontas do mesmo movimento, diga isso \
explicitamente: é o erro de leitura mais caro desta casa."""


def narrar(p: dict) -> dict:
    """A prosa do parecer, escrita pelo modelo LOCAL sobre o que foi medido.

    NUNCA cai para modelo externo. O payload tem nome de conta, de centro de
    custo e de fornecedor — o que permite o fallback externo do Copiloto é o
    snapshot dele ser escalar e anônimo, e este não é. Sem Ollama, devolve a
    narrativa determinística DIZENDO que o modelo não respondeu.
    """
    base = frases(p)
    texto_base = "\n".join("- %s" % f for f in base)
    if not base:
        return {"texto": "", "origem": "sem dados", "frases": []}

    from . import copiloto
    st = copiloto.ollama_status()
    if not st.get("ok"):
        return {"texto": texto_base, "origem": "medição (modelo local fora do "
                                               "ar)", "frases": base,
                "aviso": "O modelo local (%s) não respondeu; o parecer abaixo "
                         "é a leitura medida, sem redação."
                         % (st.get("modelo") or "ollama")}
    try:
        r = copiloto._chat_ollama([
            {"role": "system", "content": SISTEMA_NARRATIVA},
            {"role": "user", "content":
                "Fatos medidos no período %s a %s (mês de referência %s):\n\n%s"
                "\n\nEscreva o parecer."
                % ((p.get("periodo") or {}).get("de"),
                   (p.get("periodo") or {}).get("ate"),
                   (p.get("periodo") or {}).get("mes_referencia"),
                   texto_base)},
        ])
        return {"texto": r["resposta"], "origem": r["modelo"], "frases": base}
    except Exception as exc:  # noqa: BLE001
        log.warning("narrativa local falhou: %s", type(exc).__name__)
        return {"texto": texto_base, "origem": "medição (modelo local falhou)",
                "frases": base,
                "aviso": "O modelo local falhou ao redigir; o parecer abaixo é "
                         "a leitura medida, sem redação."}


@queries.cached(ttl=900, velha_ate=6 * 3600)
def parecer(comp_de: str, comp_ate: str) -> dict:
    """O parecer completo do período. Tudo medido; nada aqui é adjetivo."""
    dre = queries.get_dre(comp_de, comp_ate)
    meses = dre.get("meses") or []
    if len(meses) < 2:
        return {"erro": "o parecer precisa de ao menos dois meses para "
                        "comparar", "meses": meses}

    pan = dre_alavancas.panorama(comp_de, comp_ate, nivel="conta")
    mes_ref = meses[-1]
    rec = recorrencia(dre)
    esp = espelhos(pan)

    # conta já explicada por um par espelhado não precisa de drill: a causa
    # dela é o par, e gastar consulta ali é pagar para reconfirmar
    explicadas = {"%s|%s" % (p["grupo"], p["reduzido"])
                  for e in esp for p in e["pontas"]}
    alvos = []
    for lado in ("piorou", "melhorou"):
        restantes = [it for it in (pan.get(lado) or [])
                     if "%s|%s" % (it["grupo"], it["reduzido"])
                     not in explicadas]
        alvos.extend((it["grupo"], it["reduzido"])
                     for it in restantes[:CONTAS_COM_DRILL])

    cau = causas(alvos, mes_ref)
    prov = provisoes(mes_ref)

    cascata = [{"rotulo": l["rotulo"],
                "total": round(l.get("total") or 0.0, 2),
                "total_aa": round(l.get("total_aa") or 0.0, 2)}
               for l in dre["linhas"] if l.get("nivel") == 0]

    saida = {
        "periodo": {"de": comp_de, "ate": comp_ate, "meses": meses,
                    "mes_referencia": mes_ref},
        "cascata": cascata,
        "recorrencia": rec,
        "panorama": pan,
        "espelhos": esp,
        "causas": cau,
        "provisoes": prov,
        "regras": {
            "piso": dre_alavancas.PISO_MATERIALIDADE,
            "cv_instavel": dre_alavancas.CV_INSTAVEL,
            "concentracao": CONCENTRACAO,
            "contas_com_drill": CONTAS_COM_DRILL,
        },
        "fonte": (
            "DRE Gerencial (ERP AVA) · cascata de queries.get_dre, ranking de "
            "dre_alavancas.panorama, causa pelos lançamentos do mês de "
            "referência, provisão pela contrapartida no razão"),
    }
    # a narrativa MEDIDA vai junto: a aba tem texto no primeiro quadro, sem
    # depender de o modelo local estar de pé
    saida["frases"] = frases(saida)
    return saida
