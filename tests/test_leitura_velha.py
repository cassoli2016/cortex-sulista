"""A última leitura boa, servida quando o ERP não responde.

O ERP é réplica de produção de TERCEIRO e tem dia ruim. Em 03/09/2026 ele
degradou das 05h às 05h40: `SELECT 1` respondia na hora e as consultas pesadas
estouravam o `statement_timeout`. A Visão Geral morria inteira e a manhã
começou sem painel.

Medido depois, com o ERP são: a consulta que não voltava em 120 s roda em
0,13 s. Não havia nada para otimizar — havia uma dependência externa fora do
nosso controle. O que dá para consertar do nosso lado é a tela não morrer.

A regra que estes testes guardam: um número de vinte minutos atrás, DITO na
tela, é honesto e serve para trabalhar; tela em branco não é nenhum dos dois.
O que não se faz é servir o número velho CALADO — quem serve carimba, e a tela
é obrigada a mostrar.
"""
from __future__ import annotations

import time

import pytest

from api import queries



@pytest.fixture(autouse=True)
def cache_limpo():
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


def _fonte(estado):
    """Uma função cacheável que obedece a `estado` — quebra quando mandado."""
    @queries.cached(ttl=0, velha_ate=3600)
    def consulta():
        if estado["quebrar"]:
            raise RuntimeError("canceling statement due to statement timeout")
        estado["chamadas"] += 1
        return {"saldo": estado["valor"]}
    return consulta


def test_a_leitura_boa_volta_quando_o_erp_cai(cache_limpo):
    estado = {"quebrar": False, "valor": 100.0, "chamadas": 0}
    consulta = _fonte(estado)
    assert consulta() == {"saldo": 100.0}

    estado["quebrar"] = True
    d = consulta()
    assert d["saldo"] == 100.0, "perdeu o número que já tinha"
    assert d["leitura_velha"] is True
    assert "leitura_em" in d and "leitura_idade_seg" in d


def test_a_leitura_velha_NUNCA_vai_calada(cache_limpo):
    """Número velho sem carimbo é pior que tela vazia: ninguém desconfia dele."""
    estado = {"quebrar": False, "valor": 7.0, "chamadas": 0}
    consulta = _fonte(estado)
    consulta()
    estado["quebrar"] = True
    assert consulta().get("leitura_velha") is True


def test_a_leitura_velha_e_uma_COPIA_do_que_esta_guardado(cache_limpo):
    """Devolve-se uma cópia, nunca o objeto do cache.

    ESTE TESTE NASCEU ERRADO e vale contar: a primeira versão afirmava que "o
    carimbo não gruda na próxima leitura boa" e passava mesmo com a cópia
    removida — porque a leitura boa seguinte SUBSTITUI a entrada do cache, e o
    objeto carimbado é descartado de qualquer jeito. Era verde que nunca
    ficaria vermelho.

    O que a cópia protege de verdade é o cache ser corrompido por quem RECEBE
    o dicionário: rota que acrescenta uma chave (a de auditoria faz isso) ou
    tela que ordena uma lista mexeriam no que está guardado. Então o que se
    afirma aqui é o que se pode provar: o objeto devolvido não é o do cache."""
    estado = {"quebrar": False, "valor": 1.0, "chamadas": 0}
    consulta = _fonte(estado)
    consulta()
    estado["quebrar"] = True
    d = consulta()
    guardado = next(iter(queries._RESP_CACHE.values()))[1]
    assert d is not guardado, "devolveu o proprio objeto do cache"
    assert "leitura_velha" not in guardado, "carimbou o que esta guardado"

    # e quem recebe pode mexer sem estragar o cache
    d["saldo"] = 999.0
    assert guardado["saldo"] == 1.0


def test_leitura_velha_DEMAIS_vira_erro(cache_limpo):
    """Número de meio período atrás não serve nem carimbado."""
    @queries.cached(ttl=0, velha_ate=60)
    def consulta():
        if getattr(consulta, "quebrar", False):
            raise RuntimeError("timeout")
        return {"x": 1}
    consulta()
    # envelhece a entrada do cache à mão
    chave = next(iter(queries._RESP_CACHE))
    velho, valor = queries._RESP_CACHE[chave]
    queries._RESP_CACHE[chave] = (velho - 3600, valor)
    consulta.quebrar = True
    with pytest.raises(RuntimeError):
        consulta()


def test_sem_leitura_anterior_o_erro_sobe(cache_limpo):
    """Primeira consulta do dia com o ERP fora: não há o que servir, e inventar
    zero seria pior."""
    @queries.cached(ttl=0, velha_ate=3600)
    def consulta():
        raise RuntimeError("timeout")
    with pytest.raises(RuntimeError):
        consulta()


def test_quem_nao_pediu_a_leitura_velha_continua_quebrando(cache_limpo):
    """`velha_ate` é opt-in: o comportamento antigo é o padrão, e uma consulta
    que não declarou nada não passa a servir número velho por tabela."""
    estado = {"quebrar": False}

    @queries.cached(ttl=0)
    def consulta():
        if estado["quebrar"]:
            raise RuntimeError("timeout")
        return {"x": 1}

    consulta()
    estado["quebrar"] = True
    with pytest.raises(RuntimeError):
        consulta()


def test_o_ttl_normal_continua_valendo(cache_limpo):
    """Com o ERP são, nada muda: dentro do TTL não se consulta de novo."""
    estado = {"quebrar": False, "valor": 5.0, "chamadas": 0}

    @queries.cached(ttl=300, velha_ate=3600)
    def consulta():
        estado["chamadas"] += 1
        return {"saldo": estado["valor"]}

    consulta(); consulta(); consulta()
    assert estado["chamadas"] == 1


def test_a_visao_geral_declara_a_janela_de_duas_horas():
    """A tela que quebrou é a que mais custa ficar sem — e a janela é escolha
    registrada, não acidente."""
    import inspect
    fonte = inspect.getsource(queries)
    assert "@cached(ttl=60, velha_ate=2 * 3600)\ndef get_visao_geral" in fonte


# ==========================================================================
# QUEM RECEBE A REDE, E QUEM NÃO PODE RECEBER
#
# Em 06/09/2026 o ERP degradou entre 04:41 e 04:51. A Visão Geral sobreviveu
# (serviu a leitura de 259 s antes, carimbada) e o resto do portal mostrou
# "banco inacessível" — duas telas tinham a rede e trinta e seis não tinham.
# A rede foi então estendida por um critério, e o critério é o que estes
# testes guardam.
# ==========================================================================

# Telas que publicam MINUTOS ou a palavra "agora". Servir leitura velha aqui
# não é conforto, é perigo: a tarja avisa, mas a decisão que a pessoa toma
# olhando uma posição de vinte minutos atrás já foi tomada.
TEMPO_REAL = ("get_torre", "get_seguranca", "get_portaria", "get_programacao")


# ONDE ESTE GUARD PROCURA — E POR QUE A LISTA SAI DO DISCO.
#
# Até 09/09/2026 este arquivo varria só `queries`, porque era lá que morava
# toda leitura cara do ERP. Deixou de ser: a projeção de caixa nasceu em
# `api/financeiro/projecao.py`, e a varredura do disco mostrou mais TREZE
# módulos com `@cached` que este guard nunca tinha olhado (faturamento, crm,
# milkrun, monkey, motorista, rasterintegra, portal_cliente…).
#
# Uma lista escrita à mão aqui ia envelhecer do mesmo jeito, e o modo de falha
# é o pior que existe: o guard aprova por AUSÊNCIA. Ele não olha, não reclama,
# e uma tela de tempo real nasce com a rede — servindo posição de duas horas
# atrás para quem precisa saber onde o veículo está agora. É a mesma armadilha
# do guard do EXISTS, que não varria justamente o módulo que define o
# `left_join()` (crônica em `docs/LICOES.md`).
#
# Então a lista SAI DO DISCO, e o único jeito de um módulo escapar é não ter
# `@cached` nenhum.
def _modulos_com_cache():
    import importlib
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parent.parent / "api"
    achados = []
    for arq in sorted(raiz.rglob("*.py")):
        txt = arq.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^@cached\(", txt, re.M):
            continue
        rel = arq.relative_to(raiz.parent).as_posix()[:-3].replace("/", ".")
        achados.append(importlib.import_module(rel.removesuffix(".__init__")))
    return tuple(achados)


MODULOS = _modulos_com_cache()


def test_a_varredura_acha_os_modulos_com_cache():
    """Varredura que não acha nada passa por vacuidade — e passaria calada no
    dia em que alguém renomeasse o decorador."""
    nomes = {m.__name__ for m in MODULOS}
    assert len(nomes) >= 10, sorted(nomes)
    # os dois que os testes abaixo nomeiam PRECISAM estar aí, senão os
    # `_decorador_de` deste arquivo levantariam "não existe mais"
    assert {"api.queries", "api.financeiro.projecao"} <= nomes, sorted(nomes)


def _decorador_de(nome):
    """O `@cached(...)` que está imediatamente acima de `def <nome>`."""
    import inspect
    import re
    for mod in MODULOS:
        linhas = inspect.getsource(mod).split("\n")
        for i, l in enumerate(linhas):
            if re.match(r"def %s\b" % nome, l):
                for j in range(i - 1, max(i - 4, -1), -1):
                    m = re.match(r"@cached\((.*)\)$", linhas[j].strip())
                    if m:
                        return m.group(1)
                return None
    raise AssertionError(
        "%s não existe mais em nenhum de %s"
        % (nome, ", ".join(m.__name__ for m in MODULOS)))


@pytest.mark.parametrize("nome", TEMPO_REAL)
def test_tela_de_TEMPO_REAL_nao_pode_ter_a_rede(nome):
    """O guard mais importante deste arquivo, e o único que protege de um erro
    que NÃO aparece na tela de quem o cometeu.

    Estender a rede é tentador e parece sempre uma melhoria: a tela para de
    morrer. Numa torre de controle ela para de morrer MENTINDO — a posição de
    duas horas atrás, com tarja e tudo, é a que alguém vai usar para dizer onde
    o veículo está. Quem acrescentar `velha_ate` aqui vai fazê-lo de boa fé,
    achando que está fazendo o mesmo que foi feito no DRE.
    """
    dec = _decorador_de(nome)
    assert dec is not None, "%s perdeu o @cached" % nome
    assert "velha_ate" not in dec, (
        "%s publica minutos ('onde está agora'): leitura velha aqui vira "
        "decisão tomada sobre posição que não existe mais. Se a tela mudou de "
        "resolução e hoje só publica dias, mude ESTA lista e diga por quê."
        % nome)


@pytest.mark.parametrize("nome", [
    "get_dre", "get_overview", "get_contabil", "get_comercial", "get_cobranca",
    "get_fluxo_consolidado", "get_manutencao", "get_combustivel", "get_multas",
    "get_veiculos", "get_rh", "get_qualidade", "get_comunicacao_rastreadora",
])
def test_painel_de_resolucao_DIARIA_tem_a_rede(nome):
    """O outro lado: sem isto a rede some numa refatoração e ninguém percebe
    até o próximo dia ruim do ERP, que é quando ela seria útil.

    `comrast` está aqui de propósito. Ele ficou de fora na primeira versão por
    soar "operacional", enquanto o painel de TV do MESMO assunto já tinha a
    rede — os dois agrupam por dias sem posição. O critério é a menor faixa que
    a tela publica, não o grupo do menu.
    """
    dec = _decorador_de(nome)
    assert dec and "velha_ate" in dec, (
        "%s perdeu a rede: no próximo dia ruim do ERP esta tela morre de novo"
        % nome)


def test_a_janela_e_a_MESMA_para_todo_mundo():
    """Uma constante, não trinta números soltos: janelas diferentes por tela
    seriam trinta decisões que ninguém tomou."""
    import inspect
    import re
    fonte = inspect.getsource(queries)
    soltos = set(re.findall(r"@cached\([^)]*velha_ate=(?!VELHA_ATE)([^,)]+)",
                            fonte))
    # a Visão Geral e o painel de TV vieram antes da constante e escrevem
    # o mesmo valor à mão; qualquer valor NOVO fora disso é o que se proíbe
    assert soltos <= {"2 * 3600"}, (
        "janela escrita à mão fora da constante VELHA_ATE: %s" % soltos)
    assert queries.VELHA_ATE == 2 * 3600


# ==========================================================================
# O CARIMBO QUE ATRAVESSA A REDE
#
# A ponte entre o `cached` e a tela é um CABEÇALHO, e não o corpo. O corpo já
# trazia o carimbo, mas ler o corpo obrigaria cada tela a lembrar de olhar —
# e foi assim que a segunda tarja da casa nasceu lendo `leitura_idade_s`, um
# campo que nunca existiu, e dizendo "0 min atrás" para sempre.
#
# O cabeçalho vale para toda rota que exista hoje ou venha a existir, sem que
# ninguém precise lembrar de nada. E aparece no `curl` e no DevTools, o que
# torna o estado visível DURANTE o incidente — que foi o que faltou em
# 06/09/2026, quando a única forma de saber que a rede tinha agido era achar
# uma linha no log do servidor.
# ==========================================================================

def test_a_resposta_velha_sai_CARIMBADA_no_cabecalho():
    from api.main import JSONResponse
    r = JSONResponse({"saldo": 10.0, "leitura_velha": True,
                      "leitura_em": "2026-09-06 04:47:00",
                      "leitura_idade_seg": 259})
    assert r.headers.get("X-Leitura-Velha") == "1"
    assert r.headers.get("X-Leitura-Em") == "2026-09-06 04:47:00"
    assert r.headers.get("X-Leitura-Idade") == "259"


def test_a_resposta_BOA_nao_leva_carimbo_nenhum():
    """Se o carimbo saísse sempre, a tarja apareceria sempre e não
    significaria nada — que é o mesmo que não existir."""
    from api.main import JSONResponse
    r = JSONResponse({"saldo": 10.0})
    assert r.headers.get("X-Leitura-Velha") is None


def test_o_carimbo_nao_atrapalha_o_resto_da_resposta():
    """O `JSONResponse` da casa já fazia duas coisas (converter tipo do banco,
    não estourar no `render`). Acrescentar a terceira não pode custar as duas
    primeiras nem mexer no status."""
    from decimal import Decimal

    from api.main import JSONResponse
    r = JSONResponse({"v": Decimal("1.5"), "leitura_velha": True,
                      "leitura_idade_seg": 60}, status_code=200)
    assert r.body == b'{"v":1.5,"leitura_velha":true,"leitura_idade_seg":60}'
    assert JSONResponse([1, 2, 3]).body == b"[1,2,3]"
    assert JSONResponse({"erro": "x"}, status_code=409).status_code == 409


def test_o_valor_do_cabecalho_e_ASCII():
    """Header com acento é campo minado entre proxies, e o Cloudflare está no
    caminho. A tela é que formata o texto; o servidor manda dado."""
    from api.main import JSONResponse
    r = JSONResponse({"leitura_velha": True, "leitura_em": "2026-09-06 04:47:00",
                      "leitura_idade_seg": 259})
    for k, v in r.headers.items():
        if k.startswith("x-leitura"):
            v.encode("ascii")   # levanta se alguém puser texto humano aqui


def test_a_tela_le_o_CABECALHO_e_nao_o_corpo():
    """Guard do desenho. Voltar a ler o corpo obrigaria a clonar e reparsear
    cada resposta — uma tabela de mil linhas parseada duas vezes em toda
    consulta — e devolveria a cada tela a chance de esquecer."""
    import pathlib
    html = (pathlib.Path("api/static/index.html").read_text(encoding="utf-8"))
    assert "velhaRegistrar(u, r)" in html, "o gancho do fetch foi desligado"
    assert "X-Leitura-Velha" in html and "X-Leitura-Idade" in html
    # e ninguém pode ter ressuscitado o campo que não existe
    assert "leitura_idade_s " not in html and "leitura_idade_s'" not in html
    assert "leitura_idade_s |" not in html and "leitura_idade_s||" not in html


def test_existe_UMA_tarja_na_casa():
    """Duas telas desenhando a mesma tarja à mão foi como uma delas ficou
    dizendo '0 min atrás' sem que ninguém notasse. A terceira cópia seria a
    próxima a divergir."""
    import pathlib
    import re
    html = pathlib.Path("api/static/index.html").read_text(encoding="utf-8")
    criadores = re.findall(r"className\s*=\s*'avisofaixa'", html)
    assert len(criadores) <= 1, (
        "mais de um lugar cria a faixa de aviso à mão: %d" % len(criadores))
