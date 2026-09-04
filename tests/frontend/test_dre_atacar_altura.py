"""A régua da casa mede a aba VAZIA. Estas duas medem a aba CHEIA.

`scripts/medir_paineis.py` dubla toda a API com `{}` e mede o que sobra —
para 70 telas isso basta, porque o esqueleto delas já está no HTML. Não para
as abas que só existem depois da resposta: "Onde atacar" e "Conta a conta"
montam TUDO em JavaScript, e vazias medem 300px e passam.

Com dado real elas mediam 1.111px e 1.540px. Nenhum teste ficou vermelho,
nenhum erro apareceu no console: a tela simplesmente rolava, e painel que rola
é painel que ninguém lê inteiro. O falso verde foi encontrado medindo no
navegador com o payload de produção, não confiando na régua.

Por isso estes guards trazem o payload CHEIO — seis alavancas, doze contas em
cada lista do panorama — e cobram os mesmos 900px. Encolher o dado de teste
para fazer o número fechar é reproduzir exatamente o defeito que eles existem
para pegar.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# A régua da casa: altura útil de uma tela 1080p com a barra do navegador.
ALTURA_UTIL = 900


def _alavanca(i: int) -> dict:
    return {
        "chave": "alav%d" % i, "titulo": "ALAVANCA DE TÍTULO COMPRIDO %d" % i,
        "valor_mes": 2_650_000.0 - i * 10_000,
        "certeza": "confirmar" if i % 2 else "medido",
        "o_que_e": "Descrição com o tamanho que estas frases têm de verdade "
                   "no painel, porque medir com texto curto é medir outra "
                   "coisa e o cartão cresce com a linha que sobra.",
        "o_que_fazer": "A recomendação, também no tamanho real: duas linhas "
                       "de texto corrido mais o que vem depois delas.",
        "fonte": "razão × operação, período escolhido",
    }


def _conta(i: int, receita: bool = False) -> dict:
    return {"nome": "CONTA COM NOME BEM COMPRIDO PARA MEDIR %d" % i,
            "agrupador": "CV - ALGUMA COISA COMPRIDA", "linha": "CUSTO VARIAVEL",
            "receita": receita, "delta_rs": -600_000.0 + i * 1_000,
            "pct_medio": -0.5276, "pct_ultimo": -0.5904,
            "media_anterior": 2_529_695.0, "cv": 0.19}


ALAVANCAS = {"meses": 8, "falta_por_mes": 1_100_000.0, "resultado_mes": 1_100_000.0,
             "alavancas": [_alavanca(i) for i in range(6)],
             "nao_e": [{"titulo": "Retorno vazio", "texto": "17,9%, abaixo do "
                        "limite de 20% que a casa usa para frota lotação."},
                       {"titulo": "Receita", "texto": "cresceu 17,3% no período."}]}

PANORAMA = {"meses": ["2026-0%d" % i for i in range(1, 9)],
            "mes_referencia": "2026-08", "nivel": "conta",
            "receita_ultimo": 9_704_416.0, "piso": 15_000.0,
            "piorou": [_conta(i) for i in range(12)],
            "melhorou": [_conta(i, i % 3 == 0) for i in range(12)],
            "oscila": [_conta(i) for i in range(8)]}

# O BANNER DE ERRO NÃO ENTRA NA RÉGUA: com a API dublada, as chamadas que não
# interceptamos devolvem `{}` e acendem a faixa vermelha. Ela é estado de
# exceção, não o estado em que a tela é lida — a régua da casa desconta igual.
ALTURA = """() => {
  const c = document.getElementById('content');
  const b = c.querySelector('#banner');
  const fora = (b && b.offsetParent !== null)
    ? Math.round(b.getBoundingClientRect().height) + 14 : 0;
  return Math.round(c.scrollHeight) - fora;
}"""
LARGURA = ("() => Math.max(0, document.documentElement.scrollWidth"
           " - document.documentElement.clientWidth)")


def _abre(pagina):
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo = ADMIN
        elif "/api/dre/alavancas" in url:
            corpo = ALAVANCAS
        elif "/api/dre/panorama" in url:
            corpo = PANORAMA
        else:
            corpo = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base + "/static/index.html#dre")
    pg.wait_for_timeout(900)
    return pg


def _mede(pg, aba: str) -> tuple[int, int]:
    pg.evaluate("([g,q]) => abaTrocar(g,q)", ["dre", aba])
    pg.wait_for_timeout(1000)
    return pg.evaluate(ALTURA), pg.evaluate(LARGURA)


def test_onde_atacar_cabe_em_uma_tela_com_as_alavancas_todas(pagina):
    pg = _abre(pagina)
    alt, larg = _mede(pg, "atk")
    n = pg.evaluate("() => document.querySelectorAll('#dre-atk-lista .card').length")
    assert n == 6, "o guard mediria uma aba mais vazia que a de produção (%d)" % n
    assert alt <= ALTURA_UTIL, "a aba 'Onde atacar' cheia mede %dpx" % alt
    assert larg == 0, "a aba 'Onde atacar' empurra a página para o lado"


def test_conta_a_conta_cabe_em_uma_tela_com_as_tres_listas(pagina):
    pg = _abre(pagina)
    alt, larg = _mede(pg, "pano")
    n = pg.evaluate("() => document.querySelectorAll('#dre-atk-pano tr').length")
    assert n == 32, "o guard mediria um panorama menor que o real (%d linhas)" % n
    assert alt <= ALTURA_UTIL, "a aba 'Conta a conta' cheia mede %dpx" % alt
    assert larg == 0, "a aba 'Conta a conta' empurra a página para o lado"


def test_o_panorama_tem_aba_propria_e_carrega_ao_abrir(pagina):
    """Ele nasceu dentro de "Onde atacar" e levava a aba a 1.540px. O que não
    cabe vai para aba, nunca para o fim da rolagem — e a aba só chama a
    consulta quando é aberta."""
    pg = _abre(pagina)
    assert pg.evaluate(
        "() => document.getElementById('aba-dre-pano').dataset.aoAbrir"
    ) == "loadDrePano"
    # e a aba "Onde atacar" não dispara mais o panorama por tabela
    assert pg.evaluate(
        "() => document.getElementById('aba-dre-atk')"
        ".querySelector('#dre-atk-pano') === null")
