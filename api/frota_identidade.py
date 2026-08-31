"""Quem é este veículo: número de frota E placa, sempre juntos.

O PROBLEMA
==========
O CÓRTEX estava dividido. Custos, pneus e manutenção chaveavam por
`numerofrota`; telemetria, premiação e tudo que vem da Gobrax, por `placa`. E
várias consultas faziam `coalesce(numerofrota, placa)`, que é o pior dos dois
mundos: a chave **muda de natureza** conforme o cadastro esteja preenchido ou
não, e ninguém percebe olhando a tela.

A DECISÃO
=========
**A chave interna é a PLACA; a identidade mostrada são as duas.** Placa porque
é única (1.973 distintas), está sempre preenchida e é o que todo fornecedor
externo devolve — Gobrax, rastreador, ANTT. Número de frota junto porque é
assim que a operação fala: ninguém no pátio diz "o JOK3003", diz "o 582".

POR QUE UM DE-PARA, E NÃO `frota` EM CADA CONSULTA
==================================================
São 132 pontos em `queries.py` que devolvem placa. Acrescentar uma coluna em
cada um seria uma varredura enorme, arriscada e que ainda deixaria de fora as
telas alimentadas pela Gobrax, que não conhece número de frota.

Um De-Para carregado UMA VEZ resolve os dois: a tela pede o mapa, e qualquer
lista de veículos ganha a identidade completa sem que a consulta dela mude.
São ~1.900 linhas de dois campos curtos — cabe folgado numa resposta.

O QUE O CADASTRO TEM DE ERRADO, E POR QUE ISSO APARECE EM VEZ DE SER CONSERTADO
==============================================================================
Medido em 30/08/2026 sobre os veículos ativos:

- **A cobertura útil é 46%, não 94%.** O campo está preenchido em 1.857 de
  1.973 — mas em **943 deles o valor É A PRÓPRIA PLACA**, copiada no campo.
  Descontando esses, o número de frota de verdade existe em 914 veículos:
  **99,8% da frota própria, 93,7% dos agregados e 4,2% dos terceiros** (45 de
  1.084). Faz sentido: a Sulista numera o que é dela; o cadastro de terceiro
  vem de fora.
- Chavear por frota faria mais da metade da frota sumir de relatório, ou pior:
  aparecer com a placa no lugar do número, o que parece número para quem lê.
- **8 números de frota repetidos**, e eles revelam outra coisa: `JOK3003` e
  `JOK3H03`, `AIZ1901` e `AIZ1J01` são o MESMO veículo cadastrado duas vezes,
  placa antiga e placa Mercosul, dividindo o número. Num caso (`ATR8G60`)
  alguém preencheu o campo frota com a própria placa.

Nada disso é desempatado em silêncio. O CÓRTEX **mostra** com a evidência ao
lado — as duas placas que dividem o número —, como faz com o plano de
manutenção cujo marcador está furado. Desempatar sozinho esconderia um
cadastro duplicado que vai voltar a doer noutro lugar.
"""
from __future__ import annotations

from . import db

# Placa Mercosul trocou o 4º caractere de dígito por letra: JOK3003 -> JOK3H03.
# É a assinatura do MESMO veículo cadastrado duas vezes, e é o que explica a
# maioria dos números de frota repetidos.
_SQL = """
SELECT trim(v.placa)                              AS placa,
       nullif(trim(v.numerofrota), '')            AS frota,
       -- SEM ACENTO E SEM TRAVESSAO NO SQL: o AVA e LATIN1 e o psycopg
       -- codifica a QUERY nessa codificacao antes de enviar. Um travessao
       -- aqui estoura com UnicodeEncodeError apontando para a posicao do
       -- caractere, nao para o SQL -- e o rotulo bonito vai no Python.
       CASE v.tipofrota WHEN 1 THEN 'Proprio' WHEN 2 THEN 'Terceiro'
                        WHEN 3 THEN 'Agregado' ELSE '' END AS tipo,
       v.atividadeveiculo                         AS atividade
  FROM veiculo v
 WHERE v.semaforo = 1 AND nullif(trim(v.placa), '') IS NOT NULL
 ORDER BY 1
"""


# o acento mora aqui, e nao no SQL
_TIPO = {"Proprio": "Próprio", "Terceiro": "Terceiro", "Agregado": "Agregado",
         "": "—"}


def rotulo(frota: str | None, placa: str | None) -> str:
    """Como o veículo se chama na tela.

    Com número: `582 · JOK3003`. Sem número: a placa sozinha — e NÃO um
    travessão nem "sem frota", que poluiriam toda linha de uma tabela de 1.084
    terceiros para dizer o que já se vê.
    """
    p = (placa or "").strip()
    f = (frota or "").strip()
    if not p:
        return f or "—"
    # FROTA IGUAL A PLACA NAO E NUMERO DE FROTA -- e a placa copiada no campo,
    # e sao 943 dos 1.857 preenchidos (926 deles em terceiro, quase certamente
    # por importacao). Mostrar "AAW7D10 · AAW7D10" seria absurdo, e pior: faria
    # metade da frota PARECER ter numero quando nao tem.
    if not f or f.upper() == p.upper():
        return p
    return f"{f} · {p}"


def linhas() -> list[dict]:
    """A consulta, uma vez. `mapa()` e `pendencias()` partem daqui em vez de
    consultarem cada um — são a mesma leitura, e duas idas ao AVA para montar
    um cartão só é desperdício que a tela paga em segundos."""
    return db.query(_SQL)


def mapa(linhas_: list[dict] | None = None) -> dict[str, dict]:
    """Placa -> identidade. É o De-Para que as telas carregam uma vez."""
    fora: dict[str, dict] = {}
    for r in (linhas_ if linhas_ is not None else db.query(_SQL)):
        placa = (r["placa"] or "").strip()
        if not placa:
            continue
        fora[placa] = {"frota": r["frota"],
                       "tipo": _TIPO.get(r["tipo"], r["tipo"] or "—"),
                       "rotulo": rotulo(r["frota"], placa)}
    return fora


def pendencias(linhas: list[dict] | None = None) -> dict:
    """O que está errado no cadastro, com a evidência ao lado.

    Duas famílias, e a separação importa porque o conserto é diferente:

    - **número repetido** — duas placas dividindo o mesmo número. Quase sempre
      é o mesmo veículo cadastrado duas vezes (placa antiga + Mercosul), e o
      conserto é encerrar um dos cadastros.
    - **sem número** — veículo que não tem como ser chamado pelo nome que a
      operação usa. Quase todo em terceiro, onde a Sulista não controla o
      cadastro; por isso é PENDÊNCIA e não erro.
    """
    linhas = linhas if linhas is not None else db.query(_SQL)
    por_frota: dict[str, list[dict]] = {}
    sem: list[dict] = []
    copiada: list[dict] = []
    for r in linhas:
        f = (r.get("frota") or "").strip()
        p = (r.get("placa") or "").strip()
        # o acento entra AQUI tambem, e nao so no `mapa()`: o SQL devolve
        # "Proprio" sem acento por causa do LATIN1 do AVA, e a tela mostrava
        # "1 proprio" no meio de um painel todo acentuado
        tipo = _TIPO.get(r.get("tipo"), r.get("tipo") or "—")
        if not f:
            sem.append({"placa": p, "tipo": tipo})
            continue
        # CAMPO PREENCHIDO COM A PLACA e o caso DOMINANTE (943 de 1.857) e
        # merece contagem propria: somado aos "sem numero" viraria um total
        # que nao distingue "ninguem preencheu" de "preencheram errado", que
        # tem consertos diferentes.
        if f.upper() == p.upper():
            copiada.append({"placa": p, "tipo": tipo})
            continue
        por_frota.setdefault(f, []).append(r)

    repetidos = []
    for f, rs in sorted(por_frota.items()):
        if len(rs) < 2:
            continue
        placas = sorted((x.get("placa") or "").strip() for x in rs)
        repetidos.append({
            "frota": f, "placas": placas,
            "tipos": [_TIPO.get(x.get("tipo"), x.get("tipo") or "—")
                      for x in rs],
            # a leitura provável, dita como HIPÓTESE e não como veredito: quem
            # decide encerrar cadastro é quem cuida do cadastro
            "provavel": _provavel(f, placas),
        })

    # o terceiro domina a lista dos sem número e isso PRECISA estar dito: sem
    # a quebra, "113 sem número" parece descuido nosso quando é cadastro de
    # terceiro, que a Sulista não controla
    por_tipo: dict[str, int] = {}
    for s in sem:
        por_tipo[s["tipo"] or "—"] = por_tipo.get(s["tipo"] or "—", 0) + 1

    por_tipo_copiada: dict[str, int] = {}
    for c in copiada:
        por_tipo_copiada[c["tipo"] or "—"] =             por_tipo_copiada.get(c["tipo"] or "—", 0) + 1

    uteis = len(linhas) - len(sem) - len(copiada)
    return {
        "total": len(linhas),
        # `com_frota` conta o que TEM NUMERO DE VERDADE, nao o campo
        # preenchido: a diferenca entre os dois e 943 veiculos, e chamar isso
        # de cobertura seria mentir por um fator de dois.
        "com_frota": uteis,
        "campo_preenchido": len(linhas) - len(sem),
        "cobertura": round(100.0 * uteis / len(linhas), 1) if linhas else None,
        "repetidos": repetidos,
        # AS LISTAS SAO CORTADAS, e o total vai junto. `frota_igual_placa`
        # tem 947 linhas: manda-las inteiras engordaria a resposta em ~90 KB
        # para desenhar uma tabela que rola internamente de qualquer jeito. E
        # o corte NUNCA vai sozinho -- top-N sem contador vira total falso.
        "sem_frota": _corte(sem),
        "sem_frota_total": len(sem),
        "sem_frota_por_tipo": por_tipo,
        "frota_igual_placa": _corte(copiada),
        "frota_igual_placa_total": len(copiada),
        "frota_igual_placa_por_tipo": por_tipo_copiada,
    }


# quantas linhas de cada pendencia vao para a tela. 200 e mais do que alguem
# percorre numa sentada, e o cartao diz "200 de 947".
LIMITE_LISTA = 200


def _corte(linhas: list[dict]) -> list[dict]:
    return sorted(linhas,
                  key=lambda x: (x["tipo"] or "", x["placa"]))[:LIMITE_LISTA]


# Placa Mercosul: LLLNLNN. O caractere que muda de dígito para letra é o
# QUINTO (índice 4), não o quarto — JOK3003 -> JOK3H03, AIZ1901 -> AIZ1J01.
# Errar o índice faz o detector devolver a hipótese genérica justamente nos
# casos em que ele tinha algo a dizer.
_MERCOSUL_POS = 4


def _provavel(frota: str, placas: list[str]) -> str:
    """A hipótese, não o veredito — quem encerra cadastro é quem o mantém."""
    if frota in placas:
        return "o campo de frota foi preenchido com a própria placa"
    if len(placas) != 2 or len(placas[0]) != 7 or len(placas[1]) != 7:
        return "dois cadastros dividindo o mesmo número"
    a, b = placas
    difs = [i for i in range(7) if a[i] != b[i]]
    if len(difs) != 1:
        return "dois cadastros dividindo o mesmo número"
    i = difs[0]
    if i == _MERCOSUL_POS and (a[i].isalpha() != b[i].isalpha()):
        return ("mesmo veículo cadastrado duas vezes — placa antiga e "
                "Mercosul (o 5º caractere vira letra)")
    # UM caractere de diferença, mas SEM ser a troca do Mercosul: é digitação
    # errada numa das duas, e isso é pior que cadastro duplicado — significa
    # que uma das placas não existe, e tudo que for lançado nela some.
    return (f"as duas placas diferem só no {i+1}º caractere "
            f"({a[i]} × {b[i]}) e não é a troca do Mercosul — provável erro de "
            "digitação em uma delas")


# ── modalidade do veículo, por extenso ──────────────────────────────────────
#
# `veiculo.utilizacaoveiculo` é o código do ERP, e ele vazava CRU para a tela em
# várias partes do painel: "AGR", "TER", "LOC", "TRA". Quem opera sabe de cor;
# quem lê o painel uma vez por mês, não — e num card que decide dinheiro a
# sigla obriga a perguntar em vez de ler.
#
# Medido em 31/08/2026 sobre os 1.975 veículos com `semaforo = 1`:
#     TER 1.086 · TRA 373 · AGR 295 · LOC 215 · PREV 3 · nulo 3
#
# `PREV` NÃO GANHA RÓTULO INVENTADO. São três veículos, não há tabela de
# domínio na réplica e traduzir por palpite é pior que mostrar o código — é a
# mesma regra da coluna "Tipo (cód.)" da Manutenção. Código desconhecido volta
# como veio, e é assim que ele aparece no dia em que virar trinta.
MODALIDADE = {
    "TRA": "Frota própria",
    "AGR": "Agregado",
    "TER": "Terceiro",
    "LOC": "Locação",
}


def modalidade(codigo: str | None) -> str:
    """O nome por extenso da modalidade; o próprio código quando não se conhece.

    Vazio vira "sem cadastro" e não travessão: a diferença entre "este veículo
    não tem modalidade cadastrada" e "não se aplica" é justamente a que faz
    alguém ir arrumar o cadastro.
    """
    c = (codigo or "").strip().upper()
    if not c:
        return "sem cadastro"
    return MODALIDADE.get(c, c)
