# -*- coding: utf-8 -*-
"""Os três pilares do ciclo: Gobrax, comportamento e gerenciamento de risco.

A NOTA DE CADA PILAR VAI DE 0 A 100, e a composta é a média ponderada deles.
Quando um pilar não tem medição, o peso dele se REDISTRIBUI entre os que
existem — não vira zero. A diferença é o modelo inteiro: zero diz "foi mal",
ausência diz "não sei", e pagar sobre um zero que significa ausência é punir
alguém pela cobertura da telemetria. Hoje a Gobrax cobre 56 dos 83 motoristas
próprios e o GR cobre 69 (medido em 18/09/2026), então a renormalização é a
regra e não a exceção — decisão de quem opera no mesmo dia.

CADA PILAR DIZ DE ONDE VEIO, e o que não veio aparece como ausência com o
motivo. Uma nota composta de 92 tirada de dois pilares não é a mesma coisa que
92 tirada de três, e quem lê a tela precisa poder ver isso.
"""
from __future__ import annotations

import logging

from api import db as erp
from api import pglocal

from . import catalogo, ciclo as ciclo_mod, coleta, identidade, parametros

log = logging.getLogger("cortex.premiacao.pilares")

#: schema do banco local — os testes trocam por um descartavel (o GR e a
#: configuracao moram nele; o snapshot da Gobrax e arquivo).
ESQUEMA: str | None = None

#: As ocorrências do ciclo, por motorista. `dt` é a data do fato — e não
#: `dtinc`, que é quando alguém digitou: lançar hoje uma ocorrência de ontem
#: não pode mudar o ciclo a que ela pertence.
OCORRENCIAS_SQL = """
SELECT regexp_replace(o.cnpjcpfcodigo, '[^0-9]', '', 'g') AS cpf,
       o.ocorrenciamotorista                              AS codigo,
       to_char(o.dt, 'YYYY-MM-DD')                        AS data,
       coalesce(m.descricao, '')                          AS descricao
FROM cadastro_vinculo_motoristaocorrencia o
LEFT JOIN ocorrenciamotorista m ON m.codigo = o.ocorrenciamotorista
WHERE o.dt >= %(de)s::date AND o.dt < %(ate)s::date
"""

#: O GR do ciclo, por motorista: uma linha por CPF com as viagens e a soma de
#: cada contador de risco. A janela é a do CICLO (16 a 15), medida pelo FIM da
#: viagem — é quando o consolidado existe.
GR_SQL = """
SELECT cpf_motorista                              AS cpf,
       count(*)                                   AS viagens,
       coalesce(sum(eventos_velocidade), 0)       AS eventos_velocidade,
       coalesce(sum(paradas_area_risco), 0)       AS paradas_area_risco,
       coalesce(sum(desvios_rota), 0)             AS desvios_rota,
       -- `rodou_fora_horario` e BOOLEANO no fornecedor (uma marca por
       -- viagem), e nao um contador como os outros: `sum()` nele nao
       -- existe no Postgres e derruba a consulta inteira. Aqui ele vira
       -- a CONTAGEM de viagens marcadas, que e o que ele significa.
       sum(CASE WHEN rodou_fora_horario THEN 1 ELSE 0 END) AS rodou_fora_horario,
       coalesce(sum(violacao_painel), 0)          AS violacao_painel,
       coalesce(sum(violacao_antena), 0)          AS violacao_antena,
       coalesce(sum(desengate), 0)                AS desengate,
       coalesce(sum(botao_panico), 0)             AS botao_panico
FROM gr_viagem_fim
WHERE real_fim >= %(de)s::date AND real_fim < %(ate)s::date
  AND cpf_motorista IS NOT NULL AND cpf_motorista <> ''
GROUP BY 1
"""


# --------------------------------------------------------------- Gobrax
def gobrax(ciclo: str, cadastro: list[dict] | None = None,
           dir_path=None) -> dict:
    """{cpf: {nota, km}} do snapshot da Gobrax, casado por NOME.

    A Gobrax não devolve documento (o `DocumentNumber` vem e é descartado na
    coleta, por ser PII que não precisamos guardar), então o casamento é pelo
    nome normalizado — com a guarda que a casa já usa: **nome que casa com mais
    de uma pessoa não casa com ninguém**, e entra em `ambiguos` para alguém
    olhar.

    O MÊS DA GOBRAX NÃO É O CICLO: ela fecha por mês civil, e o ciclo vai do 16
    ao 15. Vale o mês que responde pela maior parte do ciclo, e quem chama
    recebe `mes_gobrax` para a tela declarar isso em vez de deixar parecer que
    tudo veio da mesma janela.
    """
    mes = ciclo_mod.mes_da_gobrax(ciclo)
    snap = coleta.ler_snapshot(mes, dir_path)
    if not snap:
        return {"mes_gobrax": mes, "notas": {}, "ambiguos": [], "sem_cadastro": [],
                "motivo": f"sem leitura da Gobrax para {mes}"}
    pessoas = cadastro if cadastro is not None else identidade.listar()
    por_nome: dict[str, list[str]] = {}
    for p in pessoas:
        por_nome.setdefault(identidade.nome_chave(p["nome"]), []).append(p["cpf"])
    notas, ambiguos, sem = {}, [], []
    for d in snap.get("drivers") or []:
        chave = identidade.nome_chave(d.get("driverName"))
        donos = por_nome.get(chave) or []
        if len(donos) > 1:
            ambiguos.append(chave)
            continue
        if not donos:
            sem.append(chave)
            continue
        notas[donos[0]] = {"nota": _num(d.get("nota")), "km": _num(d.get("km")),
                           "driver_id": d.get("driverId")}
    return {"mes_gobrax": mes, "notas": notas, "ambiguos": sorted(set(ambiguos)),
            "sem_cadastro": sorted(set(sem)),
            "parcial": bool(snap.get("parcial")),
            "coletado_em": snap.get("coletado_em"), "motivo": ""}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------- comportamento
def comportamento(ciclo: str, depara: dict | None = None) -> dict:
    """{cpf: {nota, pontos, desvios[], meritos[]}} a partir das ocorrências.

    A nota do pilar é `100 − pontos dos desvios`, com piso em zero. O MÉRITO
    NÃO SOBE a nota do ciclo — ele conta na reputação de seis meses, que é
    onde história pesa. É assim no modelo, e a razão é boa: o ciclo mede o
    ciclo; elogio de março não conserta um desvio de setembro.

    Código do ERP sem de-para NÃO vira desvio: ele entra em `nao_mapeados` e a
    tela pede decisão. Penalizar por um código que ninguém classificou seria
    tirar dinheiro de alguém por causa de um cadastro novo do ERP.
    """
    de, ate = ciclo_mod.limites(ciclo)
    mapa = parametros.depara() if depara is None else depara
    try:
        linhas = erp.query(OCORRENCIAS_SQL, {"de": de, "ate": ate})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: ocorrencias indisponiveis (%s)", type(exc).__name__)
        return {"por_cpf": {}, "nao_mapeados": [], "motivo": "ERP indisponível"}
    por_cpf: dict[str, dict] = {}
    nao_mapeados: dict[int, dict] = {}
    sem_codigo = [0]
    for r in linhas:
        cpf = identidade.cpf(r["cpf"])
        if not cpf:
            continue
        codigo = r["codigo"]
        if codigo is None:
            # Ocorrencia gravada sem tipo no ERP. Nao e "codigo por decidir" —
            # nao ha o que decidir —, entao ela e contada a parte em vez de
            # virar uma linha com codigo `None` na tela de classificacao.
            sem_codigo[0] += 1
            continue
        alvo = mapa.get(codigo)
        if alvo is None:
            item = nao_mapeados.setdefault(
                codigo, {"codigo": codigo, "descricao": r["descricao"], "vezes": 0})
            item["vezes"] += 1
            continue
        if alvo == "IGNORAR":
            continue
        ficha = por_cpf.setdefault(cpf, {"desvios": [], "meritos": [], "pontos": 0.0})
        if catalogo.e_merito(alvo):
            m = catalogo.merito(alvo)
            if m:
                ficha["meritos"].append({"cod": alvo, "nome": m["nome"],
                                         "pts": m["pts"], "data": r["data"]})
            continue
        d = catalogo.desvio(alvo)
        if not d:
            # De-para aponta para um desvio que o catálogo não tem: é defeito
            # de configuração, e some da conta em vez de virar zero calado.
            nao_mapeados.setdefault(codigo, {"codigo": codigo,
                                             "descricao": r["descricao"], "vezes": 0})
            nao_mapeados[codigo]["vezes"] += 1
            continue
        ficha["desvios"].append({"cod": alvo, "nome": d["nome"], "grav": d["grav"],
                                 "pts": d["pts"], "data": r["data"]})
        ficha["pontos"] += float(d["pts"])
    for ficha in por_cpf.values():
        ficha["nota"] = max(0.0, 100.0 - ficha["pontos"])
    return {"por_cpf": por_cpf,
            "nao_mapeados": sorted(nao_mapeados.values(), key=lambda x: -x["vezes"]),
            "sem_codigo": sem_codigo[0],
            "motivo": ""}


def nota_comportamento(ficha: dict | None) -> float:
    """Sem ocorrência no ciclo a nota é 100 — e isso NÃO é ausência de medição.

    A diferença importa: o pilar da Gobrax sem leitura é "não sei"; o
    comportamento sem ocorrência é "nada aconteceu", que é o esperado. Medido
    em 18/09/2026: em 6 meses, só 125 motoristas tiveram ao menos uma
    ocorrência — a maioria dos ciclos é limpa, e tratá-los como ausência
    deixaria o pilar de comportamento fora da conta quase sempre.
    """
    if not ficha:
        return 100.0
    return float(ficha.get("nota", 100.0))


# ------------------------------------------------------------------- GR
def gr(ciclo: str, pesos: dict | None = None, minimo_viagens: float = 5,
       referencia: float = 10, queda: float = 40, piso: float = 20) -> dict:
    """{cpf: {nota, viagens, pontos, risco_por_viagem, contadores}} do GR.

    A conta é a do modelo, com os contadores no lugar dos ~70 tipos de exceção:

        risco por viagem = soma(contador × peso) / viagens
        nota = 100 − queda × (risco por viagem / referência), com piso

    O PISO DE VIAGENS existe porque uma viagem com um evento daria o mesmo
    índice de dez viagens com dez, e a primeira é ruído. Abaixo do piso o ciclo
    fica SEM nota de GR (`insuficiente`), e o peso se redistribui — não vira
    nota baixa.
    """
    de, ate = ciclo_mod.limites(ciclo)
    pesos = pesos or catalogo.pesos_gr_padrao()
    try:
        linhas = pglocal.query(GR_SQL, {"de": de, "ate": ate}, esquema=ESQUEMA)
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: GR indisponivel (%s)", type(exc).__name__)
        return {"por_cpf": {}, "motivo": "gerenciamento de risco indisponível"}
    por_cpf = {}
    for r in linhas:
        cpf = identidade.cpf(r["cpf"])
        if not cpf:
            continue
        viagens = int(r["viagens"] or 0)
        contadores = {c["campo"]: int(r.get(c["campo"]) or 0)
                      for c in catalogo.CONTADORES_GR}
        pontos = sum(qtd * float(pesos.get(campo, 0)) for campo, qtd in contadores.items())
        ficha = {"viagens": viagens, "pontos": round(pontos, 2),
                 "contadores": contadores,
                 # O que a tela mostra ao lado da nota sem entrar nela:
                 # desengate (operação de carreta), pânico (pedido de socorro)
                 # e o que o fornecedor não preenche. Some da CONTA, não da
                 # vista — quem opera perguntou por eles.
                 "informativos": {c["campo"]: int(r.get(c["campo"]) or 0)
                                  for c in catalogo.SO_INFORMATIVOS},
                 "panico": int(r.get("botao_panico") or 0),
                 "insuficiente": viagens < minimo_viagens,
                 "nota": None, "risco_por_viagem": None}
        if viagens and not ficha["insuficiente"]:
            idx = pontos / viagens
            nota = 100.0 - float(queda) * (idx / float(referencia or 1))
            ficha["risco_por_viagem"] = round(idx, 3)
            ficha["nota"] = round(max(float(piso), min(100.0, nota)), 1)
        por_cpf[cpf] = ficha
    return {"por_cpf": por_cpf, "motivo": ""}


# ------------------------------------------------------------- composta
def composta(nota_gobrax, nota_conduta, nota_gr, pesos: dict) -> dict:
    """A média ponderada dos pilares PRESENTES, com o peso do ausente diluído.

    Devolve também de que pilares ela saiu — a tela precisa dizer "sem Gobrax"
    ao lado de uma nota, senão 92 de dois pilares e 92 de três parecem a mesma
    coisa. Sem nenhum pilar, a nota é `None`: não existe nota de quem não foi
    medido em nada, e zero seria uma afirmação que ninguém fez.
    """
    partes = [
        ("gobrax", nota_gobrax, float(pesos.get("peso_gobrax", 0))),
        ("conduta", nota_conduta, float(pesos.get("peso_conduta", 0))),
        ("gr", nota_gr, float(pesos.get("peso_gr", 0))),
    ]
    presentes = [(nome, valor, peso) for nome, valor, peso in partes
                 if valor is not None and peso > 0]
    if not presentes:
        return {"nota": None, "pilares": [], "ausentes": [n for n, _v, _p in partes],
                "renormalizado": False}
    soma_pesos = sum(peso for _n, _v, peso in presentes)
    nota = sum(valor * peso for _n, valor, peso in presentes) / soma_pesos
    ausentes = [nome for nome, valor, peso in partes if valor is None and peso > 0]
    return {"nota": round(nota, 1),
            "pilares": [n for n, _v, _p in presentes],
            "ausentes": ausentes,
            "renormalizado": bool(ausentes)}


def status(nota, valores: dict) -> str:
    """EXCELENTE / BOM / ATENCAO / ALERTA / CRITICO — ou PENDENTE sem nota."""
    if nota is None:
        return "PENDENTE"
    if nota >= valores["status_excelente"]:
        return "EXCELENTE"
    if nota >= valores["status_bom"]:
        return "BOM"
    if nota >= valores["status_atencao"]:
        return "ATENCAO"
    if nota >= valores["status_alerta"]:
        return "ALERTA"
    return "CRITICO"


def categoria(reputacao, valores: dict) -> str:
    """ELITE / DIAMANTE / OURO / PRATA / BRONZE — ou PENDENTE sem reputação."""
    if reputacao is None:
        return "PENDENTE"
    if reputacao >= valores["cat_elite"]:
        return "ELITE"
    if reputacao >= valores["cat_diamante"]:
        return "DIAMANTE"
    if reputacao >= valores["cat_ouro"]:
        return "OURO"
    if reputacao >= valores["cat_prata"]:
        return "PRATA"
    return "BRONZE"


# ------------------------------------------------------- a janela inteira
#
# UMA consulta para os seis ciclos, e não seis. O corte do ciclo vai DENTRO do
# SQL, com a mesma regra do `ciclo.de_data`: do dia 16 em diante, o mês
# seguinte. A tentação é fazer `data + 15 dias` e cortar pelo mês — e ela erra
# em mês de 31 dias (16 + 15 = 31, ainda o mesmo mês) e em mês de 30 (15 + 16 =
# 31, que vira o mês seguinte). `date_trunc` + um mês condicional não tem borda.
_CICLO_SQL = ("to_char(date_trunc('month', {col}) + (CASE WHEN extract(day FROM {col})"
              " >= 16 THEN interval '1 month' ELSE interval '0' END), 'YYYY-MM')")

OCORRENCIAS_JANELA_SQL = """
SELECT regexp_replace(o.cnpjcpfcodigo, '[^0-9]', '', 'g') AS cpf,
       o.ocorrenciamotorista                              AS codigo,
       to_char(o.dt, 'YYYY-MM-DD')                        AS data,
       coalesce(m.descricao, '')                          AS descricao,
       """ + _CICLO_SQL.format(col="o.dt") + """          AS ciclo
FROM cadastro_vinculo_motoristaocorrencia o
LEFT JOIN ocorrenciamotorista m ON m.codigo = o.ocorrenciamotorista
WHERE o.dt >= %(de)s::date AND o.dt < %(ate)s::date
"""

GR_JANELA_SQL = """
SELECT """ + _CICLO_SQL.format(col="real_fim") + """     AS ciclo,
       cpf_motorista                              AS cpf,
       count(*)                                   AS viagens,
       coalesce(sum(eventos_velocidade), 0)       AS eventos_velocidade,
       coalesce(sum(paradas_area_risco), 0)       AS paradas_area_risco,
       coalesce(sum(desvios_rota), 0)             AS desvios_rota,
       sum(CASE WHEN rodou_fora_horario THEN 1 ELSE 0 END) AS rodou_fora_horario,
       coalesce(sum(violacao_painel), 0)          AS violacao_painel,
       coalesce(sum(violacao_antena), 0)          AS violacao_antena,
       coalesce(sum(desengate), 0)                AS desengate,
       coalesce(sum(botao_panico), 0)             AS botao_panico
FROM gr_viagem_fim
WHERE real_fim >= %(de)s::date AND real_fim < %(ate)s::date
  AND cpf_motorista IS NOT NULL AND cpf_motorista <> ''
GROUP BY 1, 2
"""


def _janela_limites(ciclo: str, n: int) -> tuple[str, str]:
    ciclos = ciclo_mod.janela(ciclo, n)
    de = ciclo_mod.limites(ciclos[0])[0]
    ate = ciclo_mod.limites(ciclos[-1])[1]
    return de, ate


def comportamento_janela(ciclo: str, n: int = 6, depara: dict | None = None) -> dict:
    """{ciclo: {cpf: ficha}} para a janela inteira, numa consulta só."""
    de, ate = _janela_limites(ciclo, n)
    mapa = parametros.depara() if depara is None else depara
    try:
        linhas = erp.query(OCORRENCIAS_JANELA_SQL, {"de": de, "ate": ate})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: ocorrencias da janela indisponiveis (%s)",
                    type(exc).__name__)
        return {"por_ciclo": {}, "nao_mapeados": [], "sem_codigo": 0,
                "motivo": "ERP indisponível"}
    por_ciclo: dict[str, dict] = {}
    nao_mapeados: dict[int, dict] = {}
    sem_codigo = 0
    for r in linhas:
        cpf = identidade.cpf(r["cpf"])
        if not cpf:
            continue
        if r["codigo"] is None:
            sem_codigo += 1
            continue
        alvo = mapa.get(r["codigo"])
        if alvo is None:
            item = nao_mapeados.setdefault(
                r["codigo"], {"codigo": r["codigo"], "descricao": r["descricao"],
                              "vezes": 0})
            item["vezes"] += 1
            continue
        if alvo == "IGNORAR":
            continue
        ficha = por_ciclo.setdefault(r["ciclo"], {}).setdefault(
            cpf, {"desvios": [], "meritos": [], "pontos": 0.0})
        if catalogo.e_merito(alvo):
            m = catalogo.merito(alvo)
            if m:
                ficha["meritos"].append({"cod": alvo, "nome": m["nome"],
                                         "pts": m["pts"], "data": r["data"]})
            continue
        d = catalogo.desvio(alvo)
        if not d:
            continue
        ficha["desvios"].append({"cod": alvo, "nome": d["nome"], "grav": d["grav"],
                                 "pts": d["pts"], "data": r["data"]})
        ficha["pontos"] += float(d["pts"])
    for fichas in por_ciclo.values():
        for ficha in fichas.values():
            ficha["nota"] = max(0.0, 100.0 - ficha["pontos"])
    return {"por_ciclo": por_ciclo,
            "nao_mapeados": sorted(nao_mapeados.values(), key=lambda x: -x["vezes"]),
            "sem_codigo": sem_codigo, "motivo": ""}


def gr_janela(ciclo: str, n: int = 6, pesos: dict | None = None,
              minimo_viagens: float = 5, referencia: float = 58,
              queda: float = 40, piso: float = 20) -> dict:
    """{ciclo: {cpf: ficha}} do GR para a janela inteira, numa consulta só."""
    de, ate = _janela_limites(ciclo, n)
    pesos = pesos or catalogo.pesos_gr_padrao()
    try:
        linhas = pglocal.query(GR_JANELA_SQL, {"de": de, "ate": ate}, esquema=ESQUEMA)
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: GR da janela indisponivel (%s)", type(exc).__name__)
        return {"por_ciclo": {}, "motivo": "gerenciamento de risco indisponível"}
    por_ciclo: dict[str, dict] = {}
    for r in linhas:
        cpf = identidade.cpf(r["cpf"])
        if not cpf:
            continue
        por_ciclo.setdefault(r["ciclo"], {})[cpf] = _ficha_gr(
            r, pesos, minimo_viagens, referencia, queda, piso)
    return {"por_ciclo": por_ciclo, "motivo": ""}


def _ficha_gr(r, pesos, minimo_viagens, referencia, queda, piso) -> dict:
    viagens = int(r["viagens"] or 0)
    contadores = {c["campo"]: int(r.get(c["campo"]) or 0)
                  for c in catalogo.CONTADORES_GR}
    pontos = sum(qtd * float(pesos.get(campo, 0)) for campo, qtd in contadores.items())
    ficha = {"viagens": viagens, "pontos": round(pontos, 2),
             "contadores": contadores,
             "informativos": {c["campo"]: int(r.get(c["campo"]) or 0)
                              for c in catalogo.SO_INFORMATIVOS},
             "panico": int(r.get("botao_panico") or 0),
             "insuficiente": viagens < minimo_viagens,
             "nota": None, "risco_por_viagem": None}
    if viagens and not ficha["insuficiente"]:
        idx = pontos / viagens
        ficha["risco_por_viagem"] = round(idx, 3)
        ficha["nota"] = round(max(float(piso),
                                  min(100.0, 100.0 - float(queda) * (idx / float(referencia or 1)))), 1)
    return ficha


def gobrax_janela(ciclo: str, n: int = 6, cadastro: list[dict] | None = None,
                  dir_path=None) -> dict:
    """{ciclo: {cpf: {nota, km}}} lendo um snapshot por ciclo da janela."""
    pessoas = cadastro if cadastro is not None else identidade.listar()
    por_ciclo = {}
    for c in ciclo_mod.janela(ciclo, n):
        r = gobrax(c, cadastro=pessoas, dir_path=dir_path)
        por_ciclo[c] = r["notas"]
    return por_ciclo
