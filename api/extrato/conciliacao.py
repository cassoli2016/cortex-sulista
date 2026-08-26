"""Conciliação lançamento a lançamento: extrato do banco × razão do ERP.

O QUE ISTO NÃO É
================
Não é a comparação de `comparacao.py`. Aquela confere AGREGADO do dia (crédito,
débito e saldo) contra `contacorrente_saldo`, e responde "o dia bate?". Esta
confere LINHA contra LINHA, contra `contacorrente` (o razão de caixa), e
responde "qual lançamento é este, e o que sobrou dos dois lados?". As duas
convivem: um dia pode bater no agregado e ainda ter dez linhas sem par.

O QUE OS DADOS REAIS DITARAM
============================
O desenho abaixo não é o desenho "completo" de um conciliador — é o que
sobreviveu à medição em agosto/2026, sobre 713 lançamentos bancários de seis
contas contra 4.306 linhas do razão.

  * Casamento exato (mesmo dia, mesmo valor com sinal) resolve **365**, metade
    do extrato. É de longe o estágio que paga.
  * Janela de data de ±3 dias acrescenta **4**. Parece desprezível no total e
    NÃO é: no Sicredi são exatamente as duas linhas que faltavam para a conta
    fechar 8 de 8 (um débito de R$ 1.431,61 que o banco lança em 07/08 e o ERP
    em 10/08, e um de R$ 16,00 com um dia de diferença). Estágio barato que
    zera uma conta inteira fica.
  * Busca de subconjunto (uma linha do banco == soma de N linhas do razão)
    acrescenta **9** em 713, ao custo de combinatória. NÃO ENTROU. O motivo de
    falhar é estrutural, não de ajuste: o razão é de 10 a 100 vezes mais
    granular que o extrato (na Caixa, 03/08 tem 15 linhas no banco contra 372
    no razão), então o subconjunto certo quase nunca cabe num limite de busca
    honesto.
  * `idconciliacaomultipla`, o campo do próprio ERP para "várias linhas do
    razão = um lançamento do banco", está preenchido em **0 de 4.306** linhas.
    O recurso existe e não é usado, então não há atalho por ali.

O RESÍDUO É A RESPOSTA, NÃO O RESTO
===================================
Como a granularidade dos dois lados é diferente por natureza, exigir par para
toda linha seria exigir o impossível e encher a tela de falso alarme. O que
decide é o RESÍDUO do dia: quanto sobrou de cada lado depois do casamento.

Na Caixa em 03/08 sobram 15 linhas do banco contra 372 do razão e o resíduo é
de **R$ 0,03** — não falta dinheiro, faltam pares; o dia está conciliado no
valor. Já no Bradesco em 26/08 o banco tem R$ 1,2 mi e o razão não tem UMA
linha: aí o ERP simplesmente não lançou o dia, que é outro problema, com outro
dono e outra ação.

Por isso cada dia sai classificado (`estado`), e é o estado que a tela ordena —
não a quantidade de linhas sem par.
"""
from __future__ import annotations

import collections
from datetime import date

TOLERANCIA = 0.01          # mesma do `comparacao.py`: um centavo
JANELA_PADRAO = 3          # dias, para trás e para frente


def _dias(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _cent(v: float) -> int:
    """Chave de casamento em CENTAVOS INTEIROS.

    Comparar float por igualdade encontraria 1234.5599999999999 != 1234.56 num
    índice de dicionário, e o par certo passaria batido justamente nos valores
    quebrados - que são a maioria de um extrato.
    """
    return int(round(v * 100))


def _ordem_banco(x: dict) -> tuple:
    """Ordem determinística de processamento.

    Não é cosmética: o casamento é guloso, então a ordem em que as linhas do
    banco pegam candidatos do razão decide QUEM fica com quem quando há
    empate. Sem uma ordem fixa, a mesma conciliação daria pares diferentes a
    cada execução e a tela mudaria sozinha entre dois cliques.
    """
    return (x["dt"], _cent(x["valor"]), str(x.get("historico") or ""), x.get("ref") or "")


def _ordem_erp(x: dict) -> tuple:
    return (x["dt"], _cent(x["valor"]), x.get("ref") or "")


def casar(banco: list[dict], erp: list[dict], *, janela: int = JANELA_PADRAO,
          tolerancia: float = TOLERANCIA) -> dict:
    """Casa lançamentos do extrato com linhas do razão.

    Cada item dos dois lados precisa de `dt` (ISO), `valor` (float COM SINAL:
    crédito positivo, débito negativo) e `ref` (identificador estável do lado
    de origem). `historico` é opcional e só viaja para a exibição.

    Dois estágios, nesta ordem, e nenhum item é casado duas vezes:

      1. mesmo dia e mesmo valor;
      2. mesmo valor a até `janela` dias de distância, preferindo o candidato
         mais próximo no tempo.

    O sinal entra na chave de propósito: um crédito de R$ 500 e um débito de
    R$ 500 no mesmo dia não são o mesmo lançamento, e casá-los esconderia
    exatamente o erro de sentido que a conciliação existe para achar.
    """
    b_livre = sorted(banco, key=_ordem_banco)
    e_livre = sorted(erp, key=_ordem_erp)

    casados: list[dict] = []
    usados: set[int] = set()

    # (1) mesmo dia, mesmo valor
    por_dia_valor: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
    for j, e in enumerate(e_livre):
        por_dia_valor[(e["dt"], _cent(e["valor"]))].append(j)

    resto_banco: list[dict] = []
    for b in b_livre:
        fila = por_dia_valor.get((b["dt"], _cent(b["valor"])))
        alvo = next((j for j in fila if j not in usados), None) if fila else None
        if alvo is None:
            resto_banco.append(b)
            continue
        usados.add(alvo)
        casados.append({"banco": b, "erp": e_livre[alvo], "distancia": 0,
                        "criterio": "dia_valor"})

    # (2) mesmo valor, dentro da janela
    por_valor: dict[int, list[int]] = collections.defaultdict(list)
    for j, e in enumerate(e_livre):
        if j not in usados:
            por_valor[_cent(e["valor"])].append(j)

    sobra_banco: list[dict] = []
    for b in resto_banco:
        cand = [j for j in por_valor.get(_cent(b["valor"]), [])
                if j not in usados and _dias(b["dt"], e_livre[j]["dt"]) <= janela]
        if not cand:
            sobra_banco.append(b)
            continue
        # mais próximo no tempo; empate resolvido pela ordem já determinística
        alvo = min(cand, key=lambda j: (_dias(b["dt"], e_livre[j]["dt"]), j))
        usados.add(alvo)
        casados.append({"banco": b, "erp": e_livre[alvo],
                        "distancia": _dias(b["dt"], e_livre[alvo]["dt"]),
                        "criterio": "valor_janela"})

    sobra_erp = [e for j, e in enumerate(e_livre) if j not in usados]
    dias = _por_dia(banco, erp, sobra_banco, sobra_erp, tolerancia)
    return {
        "casados": casados,
        "sobra_banco": sobra_banco,
        "sobra_erp": sobra_erp,
        "dias": dias,
        "resumo": _resumo(banco, erp, casados, sobra_banco, sobra_erp, dias),
    }


def _por_dia(banco: list[dict], erp: list[dict], sobra_banco: list[dict],
             sobra_erp: list[dict], tolerancia: float) -> list[dict]:
    """Um registro por dia, com o resíduo e o diagnóstico.

    O diagnóstico olha o dia INTEIRO, não só o que sobrou: "o ERP não lançou
    este dia" e "o ERP lançou, mas em outra granularidade" são conclusões
    diferentes, e a segunda é indistinguível da primeira se só se olha a
    sobra.
    """
    tot_b = collections.Counter()
    tot_e = collections.Counter()
    val_b: dict[str, float] = collections.defaultdict(float)
    val_e: dict[str, float] = collections.defaultdict(float)
    for x in banco:
        tot_b[x["dt"]] += 1
        val_b[x["dt"]] += x["valor"]
    for x in erp:
        tot_e[x["dt"]] += 1
        val_e[x["dt"]] += x["valor"]

    sb_n, se_n = collections.Counter(), collections.Counter()
    sb_v: dict[str, float] = collections.defaultdict(float)
    se_v: dict[str, float] = collections.defaultdict(float)
    for x in sobra_banco:
        sb_n[x["dt"]] += 1
        sb_v[x["dt"]] += x["valor"]
    for x in sobra_erp:
        se_n[x["dt"]] += 1
        se_v[x["dt"]] += x["valor"]

    saida = []
    for dt in sorted(set(tot_b) | set(tot_e)):
        residuo = round(sb_v[dt] - se_v[dt], 2)
        fecha = abs(residuo) <= tolerancia
        if not sb_n[dt] and not se_n[dt]:
            estado = "conciliado"          # todo lançamento do dia achou par
        elif tot_e[dt] == 0:
            estado = "erp_nao_lancou"      # o dia inteiro falta no razão
        elif tot_b[dt] == 0:
            estado = "so_no_erp"           # o razão tem dia que o extrato não cobre
        elif fecha:
            estado = "granularidade"       # sobra dos dois lados, mas o valor fecha
        else:
            estado = "diverge"
        # Materialidade RELATIVA, ao lado do valor absoluto. Sem ela a tela
        # trata igual o dia da Caixa em que sobram R$ 0,03 sobre R$ 885 mil
        # movimentados (3 centavos em 387 linhas: divergência real, mas de
        # centavo) e o dia do Itaú em que faltam R$ 292 mil. Os dois são
        # `diverge` - o estado não mente - mas quem lê precisa saber qual
        # abrir primeiro, e ordenar só pelo valor absoluto esconderia um
        # resíduo pequeno num dia pequeno.
        base = max(abs(val_b[dt]), abs(val_e[dt]))
        saida.append({
            "dt": dt, "estado": estado, "residuo": residuo, "fecha": fecha,
            "residuo_pct": round(abs(residuo) / base * 100, 4) if base else None,
            "banco_linhas": tot_b[dt], "banco_valor": round(val_b[dt], 2),
            "erp_linhas": tot_e[dt], "erp_valor": round(val_e[dt], 2),
            "sobra_banco_linhas": sb_n[dt], "sobra_banco_valor": round(sb_v[dt], 2),
            "sobra_erp_linhas": se_n[dt], "sobra_erp_valor": round(se_v[dt], 2),
        })
    return saida


A_TRATAR = ("diverge", "erp_nao_lancou", "so_no_erp")


def _resumo(banco: list[dict], erp: list[dict], casados: list[dict],
            sobra_banco: list[dict], sobra_erp: list[dict],
            dias: list[dict]) -> dict:
    n = len(banco)
    ruins = [d for d in dias if d["estado"] in A_TRATAR]
    return {
        "banco_linhas": n,
        "erp_linhas": len(erp),
        "casados": len(casados),
        "casados_pct": round(len(casados) / n * 100, 1) if n else 0.0,
        "por_janela": sum(1 for c in casados if c["criterio"] == "valor_janela"),
        "sobra_banco": len(sobra_banco),
        "sobra_erp": len(sobra_erp),
        "dias_total": len(dias),
        "dias_por_estado": dict(collections.Counter(d["estado"] for d in dias)),
        "dias_a_tratar": len(ruins),
        # O dinheiro que de fato ficou sem explicação: só o resíduo dos dias que
        # NÃO fecham. Somar o resíduo de todos os dias diluiria o número, porque
        # os dias de granularidade trazem ruído de centavos com os dois sinais -
        # e um total que some por compensação é pior que total nenhum.
        "valor_sem_explicacao": round(sum(d["residuo"] for d in ruins), 2),
    }
