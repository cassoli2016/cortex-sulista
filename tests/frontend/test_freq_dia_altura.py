# -*- coding: utf-8 -*-
"""A aba "O dia" da Frequência cabe na tela — COM O DIA CHEIO, não com o de hoje.

POR QUE ESTE GUARD EXISTE, E POR QUE ELE NÃO PODE USAR O DIA DE HOJE
====================================================================
A régua da casa (`scripts/medir_paineis.py`) dubla a API com `{}`. Tabela
vazia não tem altura: ela mediu **381px** para esta aba e aprovou. Medida com
o dia real, a aba dava **1.060px**, e com o dia de ontem inteiro (82 pessoas,
284 batidas) **933px** — contra o limite de 900. Foi só por isso que a banda de
KPIs saiu, a faixa de lugares entrou para dentro do card e a tabela ficou com
a rolagem `curta`.

E um segundo degrau, que veio da sessão do portal do cliente em 11/09/2026 e
vale para cá: **payload real não é payload no limite**. Um teste que mede o
dia de hoje prova que hoje cabe; ele NÃO prova que o mecanismo que faz caber
está lá. Se a lista rola por dentro, o payload do teste precisa ser maior que
a rolagem — senão o teste aprova alguém REMOVENDO a rolagem, porque sem ela o
conteúdo do dia de hoje também caberia.

Por isso o dublê daqui é o TETO que a base comporta, medido nela em
11/09/2026:

    pessoas com ponto no cadastro ....... 92  (`frequencia.publico()`)
    batidas por pessoa num dia, máximo ....  6  (média 3,2)
    cercas cadastradas .................... 9  (`pc_cerca`)
    pico diário já visto ................. 83 pessoas · 306 batidas · 8 lugares

São 92 × 6 = 552 batidas e 19 selos de lugar (as 9 cercas como destino, as 9
como "longe de", mais o "sem GPS"), acima de qualquer dia que a operação já
teve. Sabotagens conferidas: tirar `tabroll` da tabela leva a aba a 5.000px, e
tirar a classe `curta` a leva a 1.000px — as duas reprovam aqui.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CASA = {**USUARIO, "admin": True, "perfil": "Administrador"}

#: As nove cercas são as do cadastro real (`pc_cerca`, 11/09/2026) — nome de
#: lugar é formato EXTERNO, e dublê de formato externo se copia, não se
#: inventa.
CERCAS = ["PIRAQUARA", "AUDI", "TUPY", "MAXION CRZ", "SBC OPERACIONAL",
          "SBC ADMINSTRATIVO", "VOLVO", "GARUVA", "CRUZEIRO"]

#: Nome comprido de propósito: a coluna da pessoa é a que empurra a linha, e
#: nome curto esconderia quebra de linha na célula.
NOME = "MARIA APARECIDA DOS SANTOS OLIVEIRA"


def _batida(i: int, hora: str) -> dict:
    """Uma batida em cada uma das três situações, em rodízio.

    As três têm rótulos de tamanhos bem diferentes ("sem GPS" contra
    "11,3 km de SBC ADMINSTRATIVO"), e é a maior que decide quantas linhas o
    selo ocupa dentro da célula.
    """
    cerca = CERCAS[i % len(CERCAS)]
    if i % 3 == 0:
        return {"hora": hora, "situacao": "dentro", "lugar": cerca,
                "local": cerca, "cerca": cerca, "distancia_m": 38,
                "relogio": "00003.19001.112923", "relogio_pessoas": 1,
                "atividade": "ENTRADA"}
    if i % 3 == 1:
        return {"hora": hora, "situacao": "fora",
                "lugar": f"11,3 km de {cerca}", "local": "FORA DE CERCA",
                "cerca": cerca, "distancia_m": 11266,
                "relogio": "00003.19001.114089", "relogio_pessoas": 1,
                "atividade": None}
    return {"hora": hora, "situacao": "sem_coordenada", "lugar": "sem GPS",
            "local": "FORA DE CERCA", "cerca": None, "distancia_m": None,
            "relogio": "00000.31900.997904", "relogio_pessoas": 42,
            "atividade": None}


def _dia_cheio() -> dict:
    horas = ["06:00", "08:31", "12:00", "13:12", "17:45", "23:58"]
    pessoas = []
    for p in range(92):
        batidas = [_batida(p + h, horas[h]) for h in range(6)]
        pessoas.append({
            "matricula": f"{3700 + p:06d}",
            "nome": f"{NOME} {p:02d}",
            "filial": ["FILIAL CURITIBA", "FILIAL SBC", "MATRIZ",
                       "FILIAL CRUZEIRO", "MATRIZ - CONTABILIDA"][p % 5],
            "funcao": "ANALISTA OPERACIONAL PLENO",
            "situacao_cad": "A",
            "batidas": batidas, "n": len(batidas),
            "dentro": 2, "fora": 2, "sem_coordenada": 2,
            "locais": [CERCAS[p % len(CERCAS)]],
            "primeira": horas[0], "ultima": horas[-1],
        })
    # 19 selos: as nove cercas como destino, as nove como "longe de", e o sem
    # GPS. Mais lugares do que a operação já teve num dia (o pico foi 8).
    locais = ([{"local": c, "situacao": "dentro", "batidas": 40,
                "pessoas": 20, "distancia_m": 38} for c in CERCAS]
              + [{"local": f"longe de {c}", "situacao": "fora", "batidas": 30,
                  "pessoas": 15, "distancia_m": 11266} for c in CERCAS]
              + [{"local": "sem GPS", "situacao": "sem_coordenada",
                  "batidas": 184, "pessoas": 92, "distancia_m": None}])
    # O PIOR CASO DOS AUSENTES E REAL: um feriado que o Globus ainda nao
    # importou faz o padrao do dia da semana esperar as ~79 pessoas de sempre
    # e NENHUMA bater. E o teto da lista, e e ele que o teto de 12 selos da
    # faixa existe para conter.
    ausentes = {
        "dia": "2026-09-11", "em_curso": False, "modo": "padrao",
        "esperados": 79, "bateram": 0, "ferias": 10, "erp_ate": "2026-09-06",
        # O guard mede o pior caso COM LISTA: o dia atípico (metade do quadro
        # fora) nem lista nomes, então ele não é o teto de altura — o teto é o
        # maior número de ausentes que ainda merece nomes.
        "atipico": False,
        "janela_dias": 28, "minimo_dias": 3,
        "ausentes": [{"chapa": f"{3700 + i:06d}", "nome": f"{NOME} {i:02d}",
                      "filial": "FILIAL CURITIBA",
                      "funcao": "ANALISTA OPERACIONAL PLENO",
                      "vistos": 4, "registro_erp": None} for i in range(79)],
    }
    return {
        "configurado": True, "dia": "hoje", "data": "2026-09-11",
        "em_curso": True, "ausentes": ausentes,
        "kpis": {"pessoas": 92, "batidas": 552, "dentro": 184, "fora": 184,
                 "sem_coordenada": 184, "primeira": "06:00", "ultima": "23:58"},
        "pessoas": pessoas, "locais": locais,
        "fonte": "CÓRTEX · pc_marcacao (Ponto Certificado, coleta de 10 em 10 min)",
    }


ALTURA = """() => {
  const c = document.getElementById('content');
  const b = c.querySelector('#banner');
  const fora = (b && b.offsetParent !== null)
    ? Math.round(b.getBoundingClientRect().height) + 14 : 0;
  return Math.round(c.scrollHeight) - fora;
}"""


def _abrir(pg, base_url):
    """Abre a tela `freq` e troca para a aba do dia, com o dia CHEIO."""
    dia = _dia_cheio()

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/rh/frequencia/dia" in u:
            corpo = dia
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo, ensure_ascii=False))

    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#freq")
    pg.wait_for_selector("#aba-freq-dia", state="attached", timeout=20000)
    pg.evaluate("abaTrocar('freq','dia')")
    pg.wait_for_selector("#freq-dia-pessoas tbody tr", state="attached",
                         timeout=20000)
    return dia


def test_o_dublê_do_dia_CHEGA_na_tela(pagina):
    """Sem isto o resto passa por vacuidade: aba vazia cabe em qualquer régua,
    e foi exatamente assim que a régua da casa aprovou esta aba com 381px."""
    pg, base = pagina
    _abrir(pg, base)
    linhas = pg.eval_on_selector_all("#freq-dia-pessoas tbody tr", "e => e.length")
    selos = pg.eval_on_selector_all("#freq-dia-locais .badge", "e => e.length")
    sem = pg.eval_on_selector_all("#freq-dia-pessoas .b-warn", "e => e.length")
    # 92 que bateram + 79 sem batida: os ausentes sao LINHAS da mesma tabela,
    # e e por isso que eles nao custam altura nenhuma.
    assert linhas == 171, f"a tabela pintou {linhas} linhas, esperado 171"
    assert sem == 79, f"{sem} linhas de 'sem batida', esperado 79"
    assert selos == 19, f"a faixa pintou {selos} selos, esperado 19"


def test_a_aba_do_dia_cabe_na_tela_com_o_dia_CHEIO(pagina):
    """900px é a régua da casa: painel se lê sem rolar a página.

    Com 92 pessoas, 552 batidas e mais 79 linhas de quem não bateu, o
    conteúdo da tabela passa de 5.000px — é a
    rolagem interna que faz a aba caber, e é ela que este número protege.
    """
    pg, base = pagina
    _abrir(pg, base)
    alt = pg.evaluate(ALTURA)
    assert alt <= 900, (
        f"a aba O dia mede {alt}px com o dia cheio — a regua da casa e 900. "
        "Conferir a rolagem interna da tabela (`tabroll curta`) e a faixa de "
        "lugares antes de acrescentar qualquer coisa aqui.")


def test_a_aba_do_dia_nao_empurra_a_pagina_para_o_LADO(pagina):
    """A régua também mede largura: card que nasce fora da tela não dá erro
    nenhum, e o selo de lugar é texto que cresce com o nome da cerca."""
    pg, base = pagina
    _abrir(pg, base)
    estouro = pg.evaluate("() => document.documentElement.scrollWidth"
                          " - document.documentElement.clientWidth")
    assert estouro == 0, f"a pagina passou {estouro}px da viewport"


def test_a_tabela_do_dia_rola_por_DENTRO(pagina):
    """O mecanismo, medido em vez de lido no CSS.

    Guard de altura sozinho não basta: ele reprova quando o mecanismo cai,
    mas não diz o que caiu. Aqui a afirmação é direta — o conteúdo é MAIOR
    que a caixa, e a caixa rola.
    """
    pg, base = pagina
    _abrir(pg, base)
    caixa = pg.eval_on_selector(
        "#freq-dia-pessoas",
        "e => ({ altura: Math.round(e.getBoundingClientRect().height),"
        "        conteudo: Math.round(e.scrollHeight),"
        "        overflow: getComputedStyle(e).overflowY })")
    assert caixa["overflow"] == "auto", caixa
    assert caixa["conteudo"] > caixa["altura"] * 3, (
        f"o dublê não exercita a rolagem: conteúdo {caixa['conteudo']}px numa "
        f"caixa de {caixa['altura']}px. Um payload que caberia sem a rolagem "
        "aprova quem remover a rolagem.")
