"""Custo de folha por NATUREZA, e o que o total de proventos não é.

O DEFEITO QUE ISTO CONSERTA
===========================
A tela de Custo de Folha somava `tipoeven='P'` e chamava de custo. Medido, esse
número **não é o que a empresa gasta**: ele carrega eventos de CIRCULAÇÃO, que
saem como provento e voltam como desconto no mesmo mês.

    ADIANTAMENTO DE SALARI  (P)  R$ 3.460.109  em 12 meses
    ADIANTAMENTO QUINZENAL  (D)  R$ 3.463.158

São a MESMA quinzena, paga adiantada e descontada depois. Batem centavo a
centavo em 9 dos 13 meses e ficam a menos de R$ 2 mil nos outros. Somá-la ao
custo é contar o salário duas vezes — R$ 231 mil a R$ 345 mil por mês, ~14% do
total. `INSUFICIENCIA DE SALDO` tem a mesma natureza, em escala menor.

O QUE **NÃO** DÁ PARA CALCULAR, E POR QUE NÃO SE INVENTA
========================================================
O custo do empregador inclui ENCARGO, e o encargo não está na ficha: só as
BASES estão (BASE FGTS SALARIO R$ 14,16 mi, BASE INSS SALARIO R$ 14,13 mi em
12 meses).

- **FGTS é calculável**: 8% da base, alíquota fixada em lei e igual para todo
  regime. Entra, com a alíquota dita na tela.
- **INSS patronal NÃO é**: a alíquota depende do regime, e há eventos de
  SIMPLES na ficha (`BASE IRF S/ SAL SIMPL`, `DESC SIMPL MENS 13SAL`) — no
  Simples o patronal está dentro do DAS, não são 20%. Estimar 20% aqui somaria
  ~R$ 2,8 milhões inventados ao custo. A base aparece na tela como base, e a
  conta fica para quem conhece o enquadramento.

É a mesma regra das multas: dizer que não dá para medir é a resposta certa
quando não dá.

A DECOMPOSIÇÃO DA VARIAÇÃO
==========================
"O custo caiu" não decide nada: caiu porque há menos gente ou porque cada um
custa menos? A conta separa os dois — `Δ = Δpessoas × médio_anterior +
pessoas_atual × Δmédio` —, e as duas parcelas têm donos diferentes: a primeira
é dimensionamento, a segunda é composição salarial e hora extra.
"""
from __future__ import annotations

import re
import unicodedata

from api import queries_folha as qf

# ── eventos que CIRCULAM: saem como provento e voltam como desconto ─────────
#
# Casados pela medição, não pelo nome: cada par foi conferido mês a mês antes
# de entrar aqui. Acrescentar um par sem conferir é o caminho para subtrair
# custo de verdade.
CIRCULACAO = (
    "ADIANTAMENTO DE SALARI",
    "INSUFICIENCIA DE SALDO",
)

# ── as naturezas, em ordem de teste ────────────────────────────────────────
#
# A ORDEM IMPORTA: "DSR HORAS EXTRAS 50%" tem de cair em hora extra antes de
# qualquer regra de DSR, e "1/3 FERIAS" antes de "FERIAS". Uma lista de
# tuplas, e não um dicionário, exatamente por isso.
NATUREZAS = [
    ("Hora extra",        (r"^H\.?E", r"DSR H", r"HORAS? EXTRA")),
    ("Adicional noturno", (r"ADICIONAL NOTURNO", r"AD NOT")),
    ("Férias",            (r"FERIAS", r"1/3")),
    # O 13o EM MAIÚSCULA, e isso derrubou R$ 3,25 milhões em "Outros" na
    # primeira rodada: `_sem_acento` faz `.upper()`, então o "o" de "13o" chega
    # aqui como "O" e o padrão em minúscula não casava. O 13º inteiro — a maior
    # rubrica depois de salário e diárias — virava categoria sem nome.
    ("13º salário",       (r"(?<![0-9])13O(?![0-9A-Z])", r"13 SALARIO", r"DECIMO TERCEIRO")),
    ("Rescisão",          (r"AVISO PREVIO", r"SALDO DE SALARIO", r"INDENIZAD",
                           r"MULTA FGTS")),
    ("Diárias",           (r"DIARIA",)),
    ("Prêmio e PLR",      (r"PREMIO", r"PLR", r"PARTICIPACAO", r"COMISSAO",
                           r"^PTS")),
    ("Ajuda de custo",    (r"AJUDA DE CUSTO",)),
    ("Afastamento",       (r"ATESTADO", r"MATERNIDADE", r"AUXILIO",
                           r"AFASTAMENTO", r"INSS S/")),
    # `MEDIA` fica por ÚLTIMO de propósito: "MEDIA VALOR 13o" e "1/3 MEDIA DE
    # FERIAS" são média DE OUTRA RUBRICA, e têm de cair nela — a regra genérica
    # aqui é a rede, não a primeira peneira.
    ("Salário",           (r"SALARIO BASE", r"^SALARIO", r"HORAS? NORMA",
                           r"MEDIA")),
]


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def natureza(descricao: str) -> str:
    """A família do evento. `Outros` é resposta legítima e VISÍVEL.

    Evento novo cai em `Outros` e aparece na tela com o valor — em vez de ser
    empurrado para "Salário" e sumir dentro do maior balde, que é como uma
    rubrica nova deixa de ser notada.
    """
    d = _sem_acento(descricao)
    for nome, padroes in NATUREZAS:
        for p in padroes:
            if re.search(p, d):
                return nome
    return "Outros"


def e_circulacao(descricao: str) -> bool:
    d = _sem_acento(descricao)
    return any(d.startswith(_sem_acento(c)) for c in CIRCULACAO)


EVENTOS_SQL = """
SELECT TO_CHAR(competficha,'YYYY-MM') comp, desceven ev, tipoeven tipo,
       ROUND(SUM(valorficha),2) tot, COUNT(DISTINCT codfunc) pessoas
  FROM vw_fichafinaneventos
 WHERE codigoempresa = :emp
   AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:meses)
 GROUP BY TO_CHAR(competficha,'YYYY-MM'), desceven, tipoeven
"""

BASES_SQL = """
SELECT TO_CHAR(competficha,'YYYY-MM') comp, desceven ev,
       ROUND(SUM(valorficha),2) tot
  FROM vw_fichafinaneventos
 WHERE codigoempresa = :emp AND tipoeven = 'B'
   AND (desceven LIKE 'BASE FGTS%' OR desceven LIKE 'BASE INSS SALARIO')
   AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:meses)
 GROUP BY TO_CHAR(competficha,'YYYY-MM'), desceven
"""

PESSOAS_SQL = """
SELECT TO_CHAR(competficha,'YYYY-MM') comp, COUNT(DISTINCT codfunc) pessoas
  FROM vw_fichafinaneventos
 WHERE codigoempresa = :emp AND tipoeven = 'P'
   AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:meses)
 GROUP BY TO_CHAR(competficha,'YYYY-MM')
"""

# Alíquota do FGTS: 8%, fixada em lei e igual para todo regime. É a ÚNICA que
# este módulo aplica — ver o cabeçalho sobre o INSS patronal.
FGTS_ALIQUOTA = 0.08


def _v(linha: dict, *nomes):
    """O Oracle devolve a chave em maiúscula ou minúscula conforme o driver.
    Ler pelos dois evita um `KeyError` que só apareceria em produção."""
    for n in nomes:
        for k in (n, n.upper(), n.lower()):
            if k in linha:
                return linha[k]
    return None


def levantar(meses: int = 12) -> dict:
    p = {"emp": qf.EMPRESA, "meses": meses}
    eventos = qf._q(EVENTOS_SQL, p)
    bases = qf._q(BASES_SQL, p)
    pessoas = {_v(r, "comp"): _v(r, "pessoas") for r in qf._q(PESSOAS_SQL, p)}

    por_mes: dict[str, dict] = {}
    for r in eventos:
        comp, ev = _v(r, "comp"), _v(r, "ev") or ""
        tipo, tot = _v(r, "tipo"), float(_v(r, "tot") or 0)
        b = por_mes.setdefault(comp, {
            "comp": comp, "proventos": 0.0, "descontos": 0.0,
            "circulacao": 0.0, "naturezas": {}, "pessoas": pessoas.get(comp, 0)})
        if tipo == "P":
            b["proventos"] += tot
            if e_circulacao(ev):
                b["circulacao"] += tot
            else:
                nat = natureza(ev)
                b["naturezas"][nat] = b["naturezas"].get(nat, 0.0) + tot
        elif tipo == "D":
            b["descontos"] += tot

    for r in bases:
        comp, ev, tot = _v(r, "comp"), _v(r, "ev") or "", float(_v(r, "tot") or 0)
        b = por_mes.setdefault(comp, {"comp": comp, "proventos": 0.0,
                                      "descontos": 0.0, "circulacao": 0.0,
                                      "naturezas": {}, "pessoas": pessoas.get(comp, 0)})
        if ev.upper().startswith("BASE FGTS"):
            b["base_fgts"] = b.get("base_fgts", 0.0) + tot
        else:
            b["base_inss"] = b.get("base_inss", 0.0) + tot

    fora = []
    for comp in sorted(por_mes):
        b = por_mes[comp]
        # CUSTO EFETIVO = proventos MENOS o que só circula. Ver o cabeçalho.
        efetivo = b["proventos"] - b["circulacao"]
        base_f = b.get("base_fgts") or 0.0
        fora.append({
            "comp": comp,
            "proventos": round(b["proventos"], 2),
            "descontos": round(b["descontos"], 2),
            "circulacao": round(b["circulacao"], 2),
            "custo_efetivo": round(efetivo, 2),
            "pessoas": b["pessoas"],
            "custo_medio": round(efetivo / b["pessoas"], 2) if b["pessoas"] else None,
            "base_fgts": round(base_f, 2) or None,
            "base_inss": round(b.get("base_inss") or 0.0, 2) or None,
            "fgts": round(base_f * FGTS_ALIQUOTA, 2) if base_f else None,
            "naturezas": {k: round(v, 2) for k, v in sorted(
                b["naturezas"].items(), key=lambda x: -x[1])},
        })
    return {"meses": fora, "fgts_aliquota": FGTS_ALIQUOTA}


def variacao(meses: list[dict]) -> dict | None:
    """Quanto da variação é GENTE e quanto é CUSTO MÉDIO.

    `Δ = Δpessoas × médio_anterior + pessoas_atual × Δmédio`. As duas parcelas
    têm donos diferentes: a primeira é dimensionamento, a segunda é composição
    salarial e hora extra. "O custo caiu" sem essa quebra não decide nada.

    Compara o último mês FECHADO com o mesmo mês do ano anterior quando existe;
    senão, com o mês anterior — e diz qual comparação usou, porque a leitura
    muda: mês contra mês carrega sazonalidade (13º em nov/dez).
    """
    validos = [m for m in meses if m["pessoas"] and m["custo_medio"] is not None]
    if len(validos) < 2:
        return None
    atual = validos[-1]
    ano, mes = int(atual["comp"][:4]), atual["comp"][5:]
    alvo = "%04d-%s" % (ano - 1, mes)
    base = next((m for m in validos if m["comp"] == alvo), None)
    tipo = "ano anterior"
    if base is None:
        base = validos[-2]
        tipo = "mês anterior"
    d_pessoas = atual["pessoas"] - base["pessoas"]
    d_medio = atual["custo_medio"] - base["custo_medio"]
    return {
        "de": base["comp"], "para": atual["comp"], "comparacao": tipo,
        "delta": round(atual["custo_efetivo"] - base["custo_efetivo"], 2),
        "por_pessoas": round(d_pessoas * base["custo_medio"], 2),
        "por_custo_medio": round(atual["pessoas"] * d_medio, 2),
        "pessoas_de": base["pessoas"], "pessoas_para": atual["pessoas"],
        "medio_de": base["custo_medio"], "medio_para": atual["custo_medio"],
    }


def resumo(dados: dict) -> dict:
    meses = dados["meses"]
    if not meses:
        return {"sem_dado": True}
    total = sum(m["custo_efetivo"] for m in meses)
    circ = sum(m["circulacao"] for m in meses)
    fgts = sum(m["fgts"] or 0 for m in meses)
    ult = meses[-1]
    nat: dict[str, float] = {}
    for m in meses:
        for k, v in m["naturezas"].items():
            nat[k] = nat.get(k, 0.0) + v
    return {
        "meses": len(meses),
        "custo_efetivo": round(total, 2),
        # O QUE FOI TIRADO, sempre visível: o número da tela antiga era este
        # mais a circulação, e quem comparar os dois precisa ver a diferença.
        "circulacao": round(circ, 2),
        "proventos_brutos": round(total + circ, 2),
        "pct_circulacao": round(100.0 * circ / (total + circ), 1) if total + circ else None,
        "fgts": round(fgts, 2),
        "base_inss": round(sum(m["base_inss"] or 0 for m in meses), 2),
        "ultimo_mes": ult["comp"],
        "custo_medio": ult["custo_medio"],
        "pessoas": ult["pessoas"],
        "naturezas": dict(sorted(nat.items(), key=lambda x: -x[1])),
        "variacao": variacao(meses),
    }
