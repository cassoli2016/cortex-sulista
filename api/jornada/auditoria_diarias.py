"""Auditoria das diárias de motorista — o que dá para AFIRMAR sobre o pagamento.

O QUE ESTE MÓDULO NÃO FAZ, E É A PRIMEIRA COISA A DIZER
======================================================
Ele **não julga se o motorista tinha direito a meia ou a inteira**. Essa regra
é da empresa e depende de pernoite, distância e acordo — nada disso está nas
fontes que a casa tem. Foi medido antes de desistir: nos 2.526 dias em que a
carga granular e a jornada coexistem, meia e inteira NÃO se separam por tempo
de direção (mediana de 13 min contra 336 min, mas com p05 zero nas duas e as
faixas se sobrepondo em todo o miolo) nem por km (p50 de 0 contra 173, idem).
Um classificador sobre isso erraria em silêncio, e a tela passaria a acusar
gente por um palpite.

O que ele faz é procurar o que é **verificável sem saber a regra**: pagamento
que não fecha com a tarifa, pagamento sem dia que o sustente, pagamento em
semana de ausência, duplicidade e valor zero. Cada achado traz a evidência e o
denominador; nenhum traz veredito.

A TARIFA É DERIVADA DO PRÓPRIO PAGAMENTO, E ISSO É DELIBERADO
=============================================================
Não existe cadastro de tarifa de diária que a casa possa ler — nem no ERP nem
aqui. O que existe é uma regularidade forte, medida: **a inteira é exatamente
o dobro da meia, em todas as filiais** (61,02/122,04 · 53,72/107,44 ·
40,00/80,00 · 50,00/100,00 · 47,00/94,00), e por isso todo pagamento é um
múltiplo inteiro da meia. Então a tarifa se descobre pelo **MDC dos pagamentos
da filial no mês** — e o resultado é limpo: R$ 57,48 em CRZ, R$ 42,50 em JOI,
R$ 61,02 → 66,45 em SBC, R$ 50,00 → 55,00 na MTZ.

Derivar em vez de fixar no código tem motivo prático: a tarifa MUDA (duas
mudanças só em 2026), e tabela escrita à mão envelhece em silêncio — no mês do
reajuste ela acusaria a filial inteira. Uma taxa só entra no catálogo quando
aparece em **dois meses ou mais**: assim o reajuste entra sozinho no mês
seguinte, e um mês estranho não vira tarifa.

O catálogo derivado VAI NO PAYLOAD, para quem conhece a tabela real conferir.
Heurística escondida vira verdade do sistema.

O RETROATIVO DE REAJUSTE É UM LOTE, NÃO TRINTA E UM ACHADOS
===========================================================
Em 09/06/2026 trinta e uma pessoas da FILIAL SBC receberam valores que não
fecham com tarifa nenhuma. Em 21/07/2026, dez da MTZ — e ali o MDC dos desvios
é **R$ 5,00 exatamente, que é 55,00 − 50,00**: é o pagamento RETROATIVO da
diferença de tarifa sobre diárias já pagas pela antiga.

Trinta e uma pessoas com o mesmo desvio, na mesma filial, no mesmo dia, não são
trinta e um erros — são UM evento de folha. O módulo agrupa por (filial, dia) e
devolve um achado de LOTE, com quantas pessoas entraram e o MDC do desvio, que
é o que permite reconhecer o reajuste. É a mesma lição da recompra de peça:
repetição dentro do MESMO documento não é recorrência.

A JANELA CURTA ACUSA A PESSOA ERRADA
====================================
A competência da folha não é a data do trabalho. Isso foi MEDIDO contra o teto
físico (ninguém recebe mais de duas meias por dia trabalhado), variando um
fator de cada vez:

    janela de  7 dias terminando no pagamento → 33,5% acima do teto
    janela de  8 dias                          → 16,7%
    janela de 10 dias                          →  8,0%
    janela de 14 dias                          →  3,7%

Trinta e três por cento não é achado, é a janela errada — a semana da folha e a
semana do trabalho não são a mesma semana, e deslocar o início (1, 2, 3 e 7
dias) não conserta. Por isso a régua do teto usa **14 dias** e é conservadora
de propósito: só acusa o que nenhuma defasagem plausível explica.

O QUE FALTA, E QUE NENHUMA CONSULTA CONSERTA
============================================
A auditoria por DIA — "esta diária, deste dia, está certa?" — depende do
registro por dia, e ele **não está sendo coletado desde 12/02/2026**. Ver
`DIAGNOSTICO_FONTES`: a tela mostra as alimentações mortas com a data de cada
uma, porque integração parada se disfarça de dado que não existe.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from math import gcd

from api import db, pglocal

log = logging.getLogger(__name__)

ESQUEMA: str | None = None       # os testes redirecionam

# Duas meias por dia trabalhado é o teto FÍSICO: uma inteira. Acima disso o
# pagamento não tem dia que o sustente, seja qual for a regra da empresa.
MEIAS_POR_DIA = 2

# Ver "A JANELA CURTA ACUSA A PESSOA ERRADA" no topo. 14 dias saiu de medição,
# não de gosto — e a medição fica escrita para que quem quiser apertar a régua
# saiba o que ganha e quanta gente passa a acusar errado.
JANELA_TETO_DIAS = 14

# Uma taxa só vira tarifa quando aparece em DOIS meses. Com um só, o mês do
# reajuste (onde a mistura das duas derruba o MDC para centavos) viraria tarifa
# e passaria a inocentar exatamente o que a régua existe para achar.
MESES_PARA_VIRAR_TARIFA = 2

# Quantos pagamentos uma filial precisa ter no mês para o MDC dela valer.
# O MDC de UM valor é o próprio valor: uma filial com um pagamento no mês
# "descobriria" uma tarifa igual ao que foi pago, e ela explicaria aquele
# pagamento sozinha — a régua se inocentaria pelo dado que devia julgar. Com
# cinco, um múltiplo comum acidental já é improvável. (As filiais reais têm de
# 10 a 151 por mês; o piso protege a filial pequena e o mês de borda.)
PAGAMENTOS_PARA_MDC = 5

# Quantas pessoas da MESMA filial no MESMO dia transformam desvios individuais
# num lote de folha. Três é demais para coincidência e baixo o bastante para
# não engolir um erro que atingiu duas pessoas.
LOTE_MINIMO = 3

# As alimentações que morreram, com a data em que cada uma parou, e o que a
# morte de cada uma CUSTA — que é o que separa "sumiu e não faz falta" de
# "sumiu e a auditoria por dia foi junto". A tela diz a DATA, nunca "faz
# tempo": é a lição da RasterJOR que ficou 136 dias fora sem ninguém notar.
DIAGNOSTICO_FONTES = [
    {"fonte": "sulista.integracao_diarias_rasterjor", "parou": "2026-02-12",
     "era": "a diária por DIA e por motorista, com meia/inteira e cidade-base",
     "custo": "sem ela não há auditoria por dia — só por pagamento semanal",
     "grave": True},
    {"fonte": "sulista.rasterjor_anomalies", "parou": "2025-05-27",
     "era": "as anomalias que a própria RasterJOR aponta",
     "custo": "a régua do fornecedor não chega, e não há substituto coletado",
     "grave": True},
    {"fonte": "sulista.rasterjor_unconformities", "parou": "2026-04-15",
     "era": "as inconformidades apuradas pela RasterJOR, dentro do ERP",
     "custo": "nenhum aqui: o CÓRTEX coleta as suas em jor_inconformidades",
     "grave": False},
    {"fonte": "sulista.rasterjor_productivity_report", "parou": "2026-04-15",
     "era": "a produtividade por motorista e dia, dentro do ERP",
     "custo": "nenhum aqui: o CÓRTEX coleta a sua em jor_jornadas",
     "grave": False},
    {"fonte": "sulista.rasterjor_produtividade", "parou": "2026-05-18",
     "era": "a segunda cópia da produtividade, dentro do ERP",
     "custo": "nenhum aqui, pelo mesmo motivo",
     "grave": False},
]

# ── as consultas ────────────────────────────────────────────────────────────

# O PAGAMENTO É O SEMANAL, nunca a folha mensal: as duas são a MESMA diária em
# granularidades diferentes (ver `diarias._consolidar`), e aqui só a semanal
# serve — é a única com data fina o bastante para cruzar com a jornada.
PAGAMENTOS_SQL = """
SELECT data_competencia::date                   AS pago_em,
       upper(trim(nome_funcionario))            AS nome,
       max(trim(matricula))                     AS matricula,
       max(trim(cargo))                         AS cargo,
       sum(valor_total)::float8                 AS valor,
       count(*)                                 AS lancamentos
  FROM sulista.diariaspagas_globus
 WHERE data_competencia >= %(de)s AND data_competencia < %(ate)s
   AND nome_funcionario IS NOT NULL
   -- `IS DISTINCT FROM` e nao `<> 1`: linha de tipo NULO sairia da auditoria
   -- em silencio, e pagamento nao auditado e pior que pagamento com achado.
   AND tipo_folha IS DISTINCT FROM 1
 GROUP BY 1, 2
"""

# A carga granular que morreu em 12/02/2026. Continua consultada porque é a
# ÚNICA fonte com a diária por dia: enquanto o recorte tocar o período em que
# ela viveu, duas réguas a mais existem (duplicidade no dia e valor zero). Fora
# dele elas não somem caladas — o payload diz que não se aplicam e por quê.
GRANULAR_SQL = """
SELECT data_diaria::date                        AS dia,
       upper(trim(motorista))                   AS nome,
       trim(filial)                             AS filial,
       trim(tipo_diaria)                        AS tipo,
       valor::float8                            AS valor,
       count(*)                                 AS vezes
  FROM sulista.integracao_diarias_rasterjor
 WHERE data_diaria >= %(de)s AND data_diaria < %(ate)s
 GROUP BY 1, 2, 3, 4, 5
"""

JORNADA_SQL = """
SELECT upper(trim(nome))                        AS nome,
       data,
       filial,
       min_total
  FROM jor_jornadas
 WHERE data >= %(de)s AND data < %(ate)s AND nome IS NOT NULL
"""

AUSENCIAS_SQL = """
SELECT upper(trim(nome))                        AS nome,
       tipo,
       inicio,
       fim
  FROM jor_ausencias
 WHERE inicio IS NOT NULL AND inicio < %(ate)s
   AND coalesce(fim, inicio) >= %(de)s
"""


def _norm(nome: str) -> str:
    """Nome sem acento, em MAIÚSCULA e com espaço simples.

    É a mesma chave de `diarias._norm`, e a igualdade entre as duas tem guard:
    duas normalizações diferentes fariam a tela de diárias e a auditoria dela
    discordarem sobre quem é a mesma pessoa, que é a pior discordância possível
    entre duas telas que se citam.
    """
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def _mdc_reais(valores) -> float:
    """MDC dos valores, em reais, calculado em CENTAVOS.

    Em centavos porque MDC é de inteiros: em float ele acumularia erro de
    representação e devolveria tarifas como R$ 57,479999999.
    """
    g = 0
    for v in valores:
        if v and v > 0:
            g = gcd(g, int(round(v * 100)))
    return g / 100 if g else 0.0


def derivar_tarifas(pagamentos: list[dict], filial_de) -> dict[str, dict]:
    """O catálogo de tarifas-meia por filial, DERIVADO dos pagamentos.

    Uma taxa entra quando aparece como MDC do mês em `MESES_PARA_VIRAR_TARIFA`
    meses ou mais. Devolve, por filial, as taxas, em que meses cada uma
    apareceu e as DESCARTADAS — porque um MDC de um mês só é quase sempre o mês
    do reajuste, que é justamente onde a régua precisa ser lida com cuidado.
    """
    por_mes: dict[tuple[str, str], list[float]] = defaultdict(list)
    for p in pagamentos:
        f = filial_de(p["nome"])
        if f and p["valor"] > 0:
            por_mes[(f, p["pago_em"].strftime("%Y-%m"))].append(p["valor"])

    visto: dict[str, dict[float, list[str]]] = defaultdict(lambda: defaultdict(list))
    for (f, m), vs in por_mes.items():
        if len(vs) < PAGAMENTOS_PARA_MDC:
            continue
        t = _mdc_reais(vs)
        if t > 0:
            visto[f][t].append(m)

    fora: dict[str, dict] = {}
    for f, taxas in sorted(visto.items()):
        boas = sorted(t for t, ms in taxas.items()
                      if len(ms) >= MESES_PARA_VIRAR_TARIFA)
        fora[f] = {
            "taxas": boas,
            "meses": {("%.2f" % t): sorted(taxas[t]) for t in boas},
            "descartadas": sorted(t for t, ms in taxas.items()
                                  if len(ms) < MESES_PARA_VIRAR_TARIFA),
        }
    return fora


def _unidades(valor: float, taxas: list[float]) -> tuple[float | None, int | None]:
    """A tarifa que EXPLICA o valor e quantas meias ele vale, ou (None, None).

    Explicar = ser múltiplo inteiro. A tolerância é de meio centavo porque o
    valor chega como float do Postgres; comparar float por igualdade aqui
    reprovaria pagamento certo por causa do último bit. Testa da MAIOR para a
    menor porque uma tarifa que é múltiplo de outra (50,00 e 100,00) explicaria
    tudo pela menor e esconderia a diferença.
    """
    for t in sorted(taxas, reverse=True):
        if t <= 0:
            continue
        u = valor / t
        if abs(u - round(u)) < 5e-3 and round(u) >= 1:
            return t, int(round(u))
    return None, None


def _dias_de_ausencia(linhas: list[dict]) -> dict[str, dict[date, str]]:
    """Ausência vira CONJUNTO DE DIAS, e não intervalo.

    Cruzar intervalo com intervalo dá certo e é difícil de ler; cruzar dia com
    dia é trivialmente auditável — e a pergunta que se faz é "neste dia ele
    estava ausente?", que é uma pergunta sobre dias.

    O teto de 200 dias existe porque afastamento sem `fim` preenchido apareceria
    como ausência ETERNA e engoliria o ano inteiro do motorista. Sem o teto,
    um único registro mal fechado calaria todas as outras réguas para ele.
    """
    fora: dict[str, dict[date, str]] = defaultdict(dict)
    for r in linhas:
        ini = r["inicio"]
        if not ini:
            continue
        a = ini.date() if hasattr(ini, "date") else ini
        f = r["fim"] or ini
        b = f.date() if hasattr(f, "date") else f
        if b < a or (b - a).days > 200:
            b = a
        x = a
        while x <= b:
            fora[_norm(r["nome"])][x] = r["tipo"]
            x += timedelta(days=1)
    return fora


def levantar(de: date, ate: date, *, esquema: str | None = None) -> dict:
    """Lê as quatro fontes do recorte. `ate` é EXCLUSIVO.

    A jornada é lida com folga para trás (`JANELA_TETO_DIAS`): a régua do teto
    olha os catorze dias ANTERIORES ao pagamento, e sem a folga o primeiro
    pagamento do recorte seria julgado contra uma janela vazia — acusando
    exatamente quem só teve o azar de estar na borda.
    """
    esq = esquema or ESQUEMA
    de_jor = de - timedelta(days=JANELA_TETO_DIAS)
    pagamentos = [dict(r) for r in db.query(
        PAGAMENTOS_SQL, {"de": de, "ate": ate})]
    granular = [dict(r) for r in db.query(
        GRANULAR_SQL, {"de": de, "ate": ate})]
    jornada = [dict(r) for r in pglocal.query(
        JORNADA_SQL, {"de": de_jor, "ate": ate}, esquema=esq)]
    ausencias = [dict(r) for r in pglocal.query(
        AUSENCIAS_SQL, {"de": de_jor, "ate": ate}, esquema=esq)]
    return {"pagamentos": pagamentos, "granular": granular,
            "jornada": jornada, "ausencias": ausencias,
            "de": de, "ate": ate}


# ── as réguas ───────────────────────────────────────────────────────────────
#
# CADA RÉGUA DEVOLVE UM ACHADO COM EVIDÊNCIA, e nenhuma devolve veredito. A
# ordem aqui é a ordem de confiança: as primeiras afirmam um FATO aritmético
# (o valor não fecha com tarifa nenhuma, a pessoa estava de atestado), as
# últimas apontam uma IMPROBABILIDADE que a defasagem da folha ainda pode
# explicar. A tela mostra a severidade, e "revisar" nunca é pintado de erro.
#
# "Trabalhou e não recebeu" NÃO está aqui de propósito: já existe na aba
# Diárias, com o ⓘ dela. O mesmo número em dois lugares é o defeito que faz
# alguém corrigir num e conferir no outro.

SEVERIDADES = ("erro", "revisar", "info")


def _achado(tipo, severidade, titulo, **campos) -> dict:
    if severidade not in SEVERIDADES:
        raise ValueError("severidade desconhecida: %r" % (severidade,))
    return {"tipo": tipo, "severidade": severidade, "titulo": titulo, **campos}


def _lista_tarifas(tarifas: dict, filial: str) -> str:
    taxas = tarifas.get(filial, {}).get("taxas", [])
    return ", ".join("R$ %.2f" % t for t in taxas) or "nenhuma derivada"


def auditar(dados: dict) -> dict:
    """Aplica as réguas e devolve os achados com o que sustenta cada um."""
    pagamentos = dados["pagamentos"]
    de, ate = dados["de"], dados["ate"]

    # ── a filial de cada motorista, pela jornada ────────────────────────────
    # A filial da FOLHA não serve: ela é a do contrato, e a tarifa segue a base
    # OPERACIONAL, que é a que a RasterJOR conhece. Fica com a MAIS RECENTE do
    # recorte porque motorista transferido tem duas, e a antiga julgaria o
    # pagamento de hoje pela tarifa de onde ele não está mais.
    vista: dict[str, tuple] = {}
    dias_trab: dict[str, set] = defaultdict(set)
    for j in dados["jornada"]:
        n = _norm(j["nome"])
        if j["filial"]:
            ant = vista.get(n)
            if ant is None or j["data"] > ant[0]:
                vista[n] = (j["data"], j["filial"])
        if (j["min_total"] or 0) > 0:
            dias_trab[n].add(j["data"])
    filial = {n: v[1] for n, v in vista.items()}

    def filial_de(nome: str):
        return filial.get(_norm(nome))

    tarifas = derivar_tarifas(pagamentos, filial_de)
    ausencia = _dias_de_ausencia(dados["ausencias"])

    achados: list[dict] = []
    # Estes dois se agrupam DEPOIS do laço: um vira lote da filial, o outro
    # vira um achado por pessoa. Emitir um achado por pagamento faria os dois
    # somarem 298 linhas e enterrarem as outras réguas.
    fora_da_tarifa: list[dict] = []
    sem_filial: list[dict] = []
    n_conferidos = n_sem_filial = 0
    valor_total = 0.0

    for p in pagamentos:
        n = _norm(p["nome"])
        f = filial_de(p["nome"])
        quando = p["pago_em"]
        valor_total += p["valor"]

        # ── R0: valor ZERO na folha ─────────────────────────────────────────
        # Lançamento de R$ 0,00 não é pagamento nem estorno: é linha que existe
        # e não diz nada. Sai como info porque não custa dinheiro — mas some do
        # relatório se ninguém a nomear, e aí ninguém pergunta o que era.
        if p["valor"] == 0:
            achados.append(_achado(
                "valor_zero", "info", "Lançamento de diária com valor zero",
                quando=quando, nome=p["nome"], matricula=p["matricula"],
                cargo=p["cargo"], filial=f, valor=0.0,
                detalhe="a folha gravou o evento com R$ 0,00 — não é pagamento "
                        "nem estorno, e não se sabe o que era"))
            continue

        # ── R1: sem filial conhecida ────────────────────────────────────────
        # AUSÊNCIA COM ALARME: sem a filial não há tarifa, e sem tarifa NENHUMA
        # das réguas seguintes roda. Se isso ficasse calado, a pessoa sairia do
        # relatório inteiro parecendo conferida.
        if not f:
            n_sem_filial += 1
            sem_filial.append({
                "quando": quando, "nome": p["nome"],
                "matricula": p["matricula"], "cargo": p["cargo"],
                "valor": round(p["valor"], 2)})
            continue

        n_conferidos += 1
        taxas = tarifas.get(f, {}).get("taxas", [])
        tarifa, meias = _unidades(p["valor"], taxas)

        # ── R2: o valor não fecha com tarifa nenhuma ────────────────────────
        if tarifa is None:
            fora_da_tarifa.append({
                "quando": quando, "nome": p["nome"], "filial": f,
                "matricula": p["matricula"], "cargo": p["cargo"],
                "valor": round(p["valor"], 2)})
            continue

        # ── R3: pagou em janela só de AUSÊNCIA ──────────────────────────────
        # A régua mais dura daqui, e a única que não depende de estimativa
        # nenhuma: sete dias sem UM dia de jornada, com ausência registrada
        # (atestado, falta, afastamento) — e mesmo assim pagou.
        semana = [quando - timedelta(days=i) for i in range(7)]
        aus_na_semana = [d for d in semana if d in ausencia.get(n, {})]
        trab_na_semana = [d for d in semana if d in dias_trab.get(n, ())]
        if aus_na_semana and not trab_na_semana:
            achados.append(_achado(
                "ausencia", "erro", "Diária paga em semana só de ausência",
                quando=quando, nome=p["nome"], matricula=p["matricula"],
                cargo=p["cargo"], filial=f, valor=round(p["valor"], 2),
                meias=meias, tarifa=tarifa,
                detalhe="nos 7 dias até o pagamento há %d dia(s) de %s e "
                        "NENHUM dia de jornada trabalhada"
                        % (len(aus_na_semana), ausencia[n][aus_na_semana[0]])))
            continue

        # ── R4: sem nenhum dia, ou acima do teto físico ─────────────────────
        # Janela de 14 dias, e o motivo está no topo do módulo: com 7 dias a
        # régua acusa um terço da folha, que é a defasagem da competência e não
        # erro de ninguém.
        janela = [quando - timedelta(days=i) for i in range(JANELA_TETO_DIAS)]
        dias = sum(1 for d in janela if d in dias_trab.get(n, ()))
        if dias == 0:
            achados.append(_achado(
                "sem_jornada", "erro", "Diária paga sem nenhum dia de jornada",
                quando=quando, nome=p["nome"], matricula=p["matricula"],
                cargo=p["cargo"], filial=f, valor=round(p["valor"], 2),
                meias=meias, tarifa=tarifa, dias=0,
                detalhe="%d meia(s) de diária e nenhum dia trabalhado nos %d "
                        "dias até o pagamento" % (meias, JANELA_TETO_DIAS)))
        elif meias > MEIAS_POR_DIA * dias:
            achados.append(_achado(
                "teto", "revisar", "Mais diárias do que dias trabalhados",
                quando=quando, nome=p["nome"], matricula=p["matricula"],
                cargo=p["cargo"], filial=f, valor=round(p["valor"], 2),
                meias=meias, tarifa=tarifa, dias=dias,
                detalhe="%d meia(s) para %d dia(s) trabalhado(s) em %d dias — "
                        "o teto é %d por dia (uma inteira)"
                        % (meias, dias, JANELA_TETO_DIAS, MEIAS_POR_DIA)))

    achados.extend(_agrupar_fora_da_tarifa(
        fora_da_tarifa, tarifas, _semana_tipica(pagamentos, filial_de)))
    achados.extend(_juntar_sem_filial(sem_filial))
    achados.extend(semanas_duplicadas(pagamentos))
    achados.extend(_reguas_da_granular(dados["granular"]))

    ordem = {"erro": 0, "revisar": 1, "info": 2}
    achados.sort(key=lambda a: (ordem[a["severidade"]], -(a.get("valor") or 0)))
    return {
        "achados": achados,
        "tarifas": tarifas,
        "fontes": DIAGNOSTICO_FONTES,
        "resumo": _resumo(achados, pagamentos, n_conferidos, n_sem_filial,
                          valor_total, dados),
        "de": de.isoformat(), "ate": ate.isoformat(),
    }


def _agrupar_fora_da_tarifa(fora: list[dict], tarifas: dict,
                            tipica: dict) -> list[dict]:
    """Desvio de tarifa vira LOTE quando a filial inteira desviou no mesmo dia.

    Ver "O RETROATIVO DE REAJUSTE É UM LOTE" no topo. O MDC dos desvios do lote
    vai no achado porque é ele que permite reconhecer o retroativo sem
    adivinhar: em 21/07/2026, na MTZ, ele deu R$ 5,00 — que é exatamente
    55,00 − 50,00. Quando o MDC bate com a diferença entre duas tarifas
    conhecidas da filial, o achado DIZ isso, e a pergunta para a folha deixa de
    ser "o que é isto?" e passa a ser "confirma que é o retroativo?".
    """
    porgrupo: dict[tuple, list[dict]] = defaultdict(list)
    for x in fora:
        porgrupo[(x["filial"], x["quando"])].append(x)

    achados = []
    for (f, quando), xs in sorted(porgrupo.items(), key=lambda z: str(z[0])):
        if len(xs) < LOTE_MINIMO:
            for x in xs:
                achados.append(_achado(
                    "tarifa", "erro", "Valor não fecha com a tarifa da filial",
                    quando=quando, nome=x["nome"], matricula=x["matricula"],
                    cargo=x["cargo"], filial=f, valor=x["valor"],
                    detalhe="R$ %.2f não é múltiplo de nenhuma tarifa vigente "
                            "de %s (%s)"
                            % (x["valor"], f, _lista_tarifas(tarifas, f))))
            continue

        total = sum(x["valor"] for x in xs)
        mdc = _mdc_reais(x["valor"] for x in xs)
        taxas = tarifas.get(f, {}).get("taxas", [])
        difs = {round(abs(a - b), 2) for a in taxas for b in taxas if a != b}
        reajuste = mdc > 0 and mdc in difs
        achados.append(_achado(
            "tarifa_lote", "revisar" if reajuste else "erro",
            "Lote da filial fora da tarifa"
            + (" (parece o retroativo do reajuste)" if reajuste else ""),
            quando=quando, nome=None, filial=f,
            valor=round(total, 2),
            pessoas=len(xs), mdc=mdc, tipica=round(tipica.get(f, 0.0), 2),
            vezes_a_tipica=(round(total / tipica[f], 2)
                            if tipica.get(f) else None),
            nomes=sorted(x["nome"] for x in xs)[:40],
            detalhe="%d pessoas de %s receberam no mesmo dia valores que não "
                    "fecham com a tarifa. O MDC deles é R$ %.2f, que é %s.%s"
                    % (len(xs), f, mdc,
                       "exatamente a diferença entre duas tarifas da filial — "
                       "é o retroativo do reajuste, e para a folha resta só "
                       "confirmar" if reajuste else
                       "uma tarifa que a casa não conhece",
                       # O TAMANHO DO LOTE CONTRA A SEMANA NORMAL da filial é o
                       # que separa "reajuste retroativo" de "semana paga em
                       # dobro": o retroativo é uma fração da semana, e um
                       # múltiplo dela é outra coisa.
                       "" if not tipica.get(f) else
                       " O lote soma R$ %.2f, %.1fx a semana típica da filial "
                       "(R$ %.2f)." % (total, total / tipica[f], tipica[f]))))
    return achados


def _reguas_da_granular(granular: list[dict]) -> list[dict]:
    """As duas réguas que só existem enquanto a carga por DIA existir.

    Elas não somem caladas quando o recorte não toca o período em que a carga
    viveu: `_resumo` publica `granular_aplicavel`, e a tela diz que não rodaram
    e por quê. Régua que desaparece sem dizer nada se lê como régua que passou.
    """
    achados = []
    porchave: dict[tuple, list[dict]] = defaultdict(list)
    for g in granular:
        porchave[(g["nome"], g["dia"])].append(g)

    for (nome, dia), gs in sorted(porchave.items(), key=lambda z: str(z[0])):
        vezes = sum(g["vezes"] for g in gs)
        if vezes > 1:
            achados.append(_achado(
                "duplicado_no_dia", "erro",
                "Mais de uma diária lançada no mesmo dia",
                quando=dia, nome=nome, filial=gs[0]["filial"],
                valor=round(sum(g["valor"] * g["vezes"] for g in gs), 2),
                vezes=vezes,
                detalhe="%d lançamentos de diária para o mesmo motorista no "
                        "mesmo dia (%s)"
                        % (vezes, ", ".join(sorted(g["tipo"] or "n/d"
                                                   for g in gs)))))
        for g in gs:
            if g["valor"] == 0:
                achados.append(_achado(
                    "granular_zero", "info", "Diária lançada com valor zero",
                    quando=dia, nome=nome, filial=g["filial"], valor=0.0,
                    detalhe="tipo %s com valor R$ 0,00 na carga por dia"
                            % (g["tipo"] or "n/d")))
    return achados


def _resumo(achados, pagamentos, n_conferidos, n_sem_filial, valor_total,
            dados) -> dict:
    """Os números do cabeçalho, cada um com o denominador que o sustenta."""
    porsev: dict[str, int] = defaultdict(int)
    portipo: dict[str, int] = defaultdict(int)
    for a in achados:
        porsev[a["severidade"]] += 1
        portipo[a["tipo"]] += 1

    # A COBERTURA DA CARGA POR DIA. Sem isto, "nenhuma duplicidade encontrada"
    # se leria como "está tudo certo" quando o certo é "não há o que olhar".
    dias_granular = {g["dia"] for g in dados["granular"]}
    return {
        "pagamentos": len(pagamentos),
        "valor": round(valor_total, 2),
        "conferidos": n_conferidos,
        "sem_filial": n_sem_filial,
        "achados": len(achados),
        "erro": porsev["erro"],
        "revisar": porsev["revisar"],
        "info": porsev["info"],
        "por_tipo": dict(portipo),
        # O DINHEIRO NÃO SE CONTA DUAS VEZES. A semana repetida de 31/07 e os
        # lotes de filial CONTÊM os achados individuais daquela data — somar
        # tudo devolveria um total inflado exatamente como a folha inflava o
        # dela. O achado individual coberto por um lote continua na lista (é
        # ele que nomeia a pessoa); só não entra na conta.
        "valor_em_erro": round(_dinheiro_sem_repetir(achados), 2),
        "granular_dias": len(dias_granular),
        "granular_de": min(dias_granular).isoformat() if dias_granular else None,
        "granular_ate": max(dias_granular).isoformat() if dias_granular else None,
        # As duas réguas por dia rodam ou não rodam — e a tela DIZ qual dos dois.
        "granular_aplicavel": bool(dias_granular),
    }


def semanas_duplicadas(pagamentos: list[dict]) -> list[dict]:
    """Competência que REPETE outra, pessoa por pessoa, centavo por centavo.

    A régua mais valiosa daqui, e a mais simples: se duas datas de pagamento
    têm exatamente o mesmo conjunto de (pessoa, valor), a segunda é a primeira
    lançada de novo. Não é semelhança nem "parecido" — é identidade.

    Achado real: **2026-07-31 é cópia exata de 2026-07-07**, as MESMAS 78
    pessoas com o MESMO valor ao centavo, R$ 32.063,63. Setenta e oito pessoas
    coincidirem ao centavo não acontece: uma semana em que cada motorista
    trabalha dias diferentes produz valores diferentes, e o próprio módulo
    mostra isso — as outras semanas de julho da mesma filial variam de
    R$ 331 a R$ 412 por pessoa.

    É a ÚNICA repetição exata de 2026, o que também diz que a régua não é
    barulhenta: ela não acusa semanas parecidas, só a idêntica.

    Por que a competência mensal fica de fora: ela É a soma das semanais por
    construção (`diarias._consolidar`), então compará-la com uma semanal seria
    reencontrar a duplicidade que aquele módulo já resolve — e a régua acusaria
    todo mês.
    """
    porcomp: dict = defaultdict(dict)
    for p in pagamentos:
        if p["valor"] > 0:
            porcomp[p["pago_em"]][_norm(p["nome"])] = round(p["valor"], 2)

    vistos: dict[tuple, object] = {}
    achados = []
    for quando in sorted(porcomp):
        pessoas = porcomp[quando]
        # ASSINATURA = o conjunto inteiro (pessoa, valor). Comparar só o TOTAL
        # acusaria duas semanas que por acaso somam igual, que é coincidência
        # plausível; comparar o conjunto inteiro não tem coincidência possível.
        chave = tuple(sorted(pessoas.items()))
        anterior = vistos.get(chave)
        if anterior is not None:
            achados.append(_achado(
                "competencia_duplicada", "erro",
                "Semana de pagamento repetida por inteiro",
                quando=quando, nome=None, filial=None,
                valor=round(sum(pessoas.values()), 2),
                pessoas=len(pessoas), copia_de=anterior.isoformat(),
                detalhe="a competência %s tem as MESMAS %d pessoas com o MESMO "
                        "valor ao centavo da competência %s — não é semelhança, "
                        "é o mesmo lançamento duas vezes"
                        % (quando.isoformat(), len(pessoas),
                           anterior.isoformat())))
        else:
            vistos[chave] = quando
    return achados


def _semana_tipica(pagamentos: list[dict], filial_de) -> dict[str, float]:
    """A mediana do total semanal de cada filial — a régua de comparação.

    Mediana e não média: uma semana de retroativo (que é justamente o que se
    quer medir) puxaria a média e passaria a se inocentar. É a mesma lição da
    régua de desvio de preço da recompra de peça.
    """
    por: dict[tuple, float] = defaultdict(float)
    for p in pagamentos:
        f = filial_de(p["nome"])
        if f and p["valor"] > 0:
            por[(f, p["pago_em"])] += p["valor"]
    porfil: dict[str, list[float]] = defaultdict(list)
    for (f, _), v in por.items():
        porfil[f].append(v)
    fora = {}
    for f, vs in porfil.items():
        vs.sort()
        n = len(vs)
        fora[f] = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    return fora


def _juntar_sem_filial(soltos: list[dict]) -> list[dict]:
    """Um achado por PESSOA, não um por pagamento.

    São 12 pessoas e 267 pagamentos em 2026: uma linha por pagamento
    transformaria o relatório numa parede em que os outros achados somem. A
    pergunta também é uma só por pessoa — "por que este motorista não está na
    RasterJOR?" —, e a resposta vale para os 36 pagamentos dele de uma vez.

    Mesma lição do lote de retroativo, e da recompra de peça antes dele:
    repetição do MESMO fato não é recorrência.
    """
    por: dict[str, dict] = {}
    for x in soltos:
        b = por.setdefault(_norm(x["nome"]), {
            "nome": x["nome"], "matricula": x["matricula"],
            "cargo": x["cargo"], "valor": 0.0, "pagamentos": 0,
            "primeiro": x["quando"], "ultimo": x["quando"]})
        b["valor"] += x["valor"]
        b["pagamentos"] += 1
        b["primeiro"] = min(b["primeiro"], x["quando"])
        b["ultimo"] = max(b["ultimo"], x["quando"])
    return [_achado(
        "sem_filial", "revisar", "Recebeu diária e não aparece na jornada",
        quando=b["ultimo"], nome=b["nome"], matricula=b["matricula"],
        cargo=b["cargo"], filial=None, valor=round(b["valor"], 2),
        pagamentos=b["pagamentos"],
        detalhe="%d pagamentos entre %s e %s, e o nome não casa com nenhum "
                "motorista da jornada — a tarifa não pode ser conferida, e "
                "NENHUMA outra régua roda para ele"
                % (b["pagamentos"], b["primeiro"].isoformat(),
                   b["ultimo"].isoformat()))
        for b in sorted(por.values(), key=lambda z: -z["valor"])]


# Os tipos que englobam outros achados da mesma data: o valor deles já contém o
# das linhas individuais que caem ali dentro.
TIPOS_QUE_ENGLOBAM = ("competencia_duplicada", "tarifa_lote")


def _dinheiro_sem_repetir(achados: list[dict]) -> float:
    """Soma o valor dos erros SEM contar duas vezes o que está dentro de um lote.

    A semana repetida de 31/07 traz R$ 32.063,63 e, dentro dela, os achados
    individuais daquela mesma data. Somar os dois seria cometer, no relatório
    de auditoria, exatamente o erro que ele existe para achar.

    O critério é a DATA (e a filial, quando o lote tem uma), não o valor: dois
    achados podem coincidir em valor por acaso, mas um achado individual na
    data de um lote da filial dele está, por construção, dentro do lote.
    """
    lotes = {(a["quando"], a.get("filial")) for a in achados
             if a["tipo"] in TIPOS_QUE_ENGLOBAM}
    datas_gerais = {q for q, f in lotes if f is None}

    total = 0.0
    for a in achados:
        if a["severidade"] != "erro":
            continue
        if a["tipo"] not in TIPOS_QUE_ENGLOBAM:
            if a["quando"] in datas_gerais:
                continue
            if (a["quando"], a.get("filial")) in lotes:
                continue
        total += a.get("valor") or 0
    return total
