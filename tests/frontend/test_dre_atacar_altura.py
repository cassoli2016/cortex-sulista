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

def _causa(i: int) -> dict:
    tipo = ("evento único", "concentrado", "espalhado", "provisão")[i % 4]
    return {"tipo": tipo, "lancamentos": 40 + i, "bruto": 223_750.0,
            "liquido": -223_750.0,
            "motivo": "%d lançamentos explicam 85%% do movimento do mês, e o "
                      "maior deles sozinho responde por 41%% — o texto desta "
                      "coluna tem o tamanho que tem em produção." % (3 + i),
            "maiores": [{"valor": -214_800.0, "fracao": 0.96,
                         "historico": "VLR REF PROV PEDAGIO FAT 00000000000 "
                                      "- SEM PARAR / AGREGADOS",
                         "data": "2026-08-31", "sequencia": 11_039_540}]}


def _prov(i: int) -> dict:
    return {"conta": "Provisao para Fornecedores %d" % i, "grupo": 1,
            "reduzido": 213_104 + i, "sequencia": i + 1, "dia": "2026-08-31",
            "historico": "VLR REF PROV PEDAGIO FAT 00000000000 - SEM PARAR "
                         "/ AGREGADOS E FROTA",
            "valor": 368_099.24 - i * 1_000, "cicla": i % 3 != 0,
            "baixada": i % 5 == 0}


def _nrec(i: int) -> dict:
    return {"conta": "RECEITA DE VENDA ATIVO IMOBILIZADO %d" % i, "grupo": 1,
            "reduzido": 391_101 + i, "linha": "RESULTADO NAO OPERACIONAL",
            "agrupador": "RECEITA - VENDA", "total": 3_060_986.43 - i * 1_000,
            "motivo": "linha não operacional da DRE", "meses": {}}


PARECER = {
    "periodo": {"de": "2026-01", "ate": "2026-08",
                "meses": ["2026-0%d" % i for i in range(1, 9)],
                "mes_referencia": "2026-08"},
    "cascata": [],
    "recorrencia": {
        "meses": ["2026-0%d" % i for i in range(1, 9)],
        "publicado": {}, "nao_recorrente": {}, "recorrente": {},
        "total_publicado": -4_907_443.27, "total_nao_recorrente": 2_882_810.33,
        "total_recorrente": -7_790_253.60, "media_publicado": -613_430.41,
        "media_recorrente": -973_781.70,
        "itens": [_nrec(i) for i in range(9)],
        "criterio": "Não recorrente = tudo na linha RESULTADO NAO "
                    "OPERACIONAL, mais conta cujo nome contém Recuperacao De "
                    "Custo, Recuperacao De Despesa, Recuperacao De Credito, "
                    "Venda De Sucata, Reembolso. É critério declarado sobre o "
                    "NOME da conta, não campo do ERP."},
    "panorama": PANORAMA,
    "espelhos": [{"conta_do_plano": "4.1.1.0%d" % i,
                  "liquido": 149_550.81,
                  "leitura": "Uma ponta gasta e a outra recupera.",
                  "pontas": [
                      {"conta": "DIESEL FROTA", "grupo": 1, "reduzido": 411_101,
                       "agrupador": "CV - COMBUSTIVEL",
                       "delta_rs": -484_528.57, "valor_ultimo": -2_368_825.0},
                      {"conta": "DIESEL AGREGADOS", "grupo": 1,
                       "reduzido": 411_108, "agrupador": "CV - COMBUSTIVEL",
                       "delta_rs": 634_079.38, "valor_ultimo": 1_868_702.0}]}
                 for i in range(2)],
    # doze contas com causa: o mesmo tamanho que o ranking real entrega
    "causas": {"1|%d" % (411_000 + i): _causa(i) for i in range(12)},
    "provisoes": {"mes": "2026-08", "dia": "2026-08-31",
                  "itens": [_prov(i) for i in range(10)],
                  "abertas": [_prov(i) for i in range(4)],
                  "total": 499_974.90, "total_aberto": 424_649.92,
                  "razao_ate": "2026-09-04",
                  "fonte": "contas de passivo com PROV no histórico lançadas "
                           "em 31/08/2026, casadas com as baixas do ciclo "
                           "anterior. A provisão é o LANÇAMENTO, nunca o saldo "
                           "do dia."},
    "regras": {"piso": 15_000.0, "cv_instavel": 0.5, "concentracao": 0.6,
               "contas_com_drill": 6},
    "frases": ["Frase de parecer com o comprimento que estas frases têm de "
               "verdade, porque medir com texto curto é medir outra coisa "
               "%d." % i for i in range(8)],
}

NARRATIVA = {
    "origem": "gemma4 (local)",
    "frases": PARECER["frases"],
    "texto": "\n\n".join(
        "Parágrafo %d do parecer, no tamanho em que o modelo local escreve de "
        "verdade: três ou quatro linhas de texto corrido explicando a causa do "
        "movimento e o que ela sustenta como decisão." % i for i in range(5)),
}


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
        # A MAIS ESPECIFICA ANTES: "/api/dre/parecer" casa dentro de
        # "/api/dre/parecer/narrativa", e invertido o dublê devolveria o
        # payload de medição no lugar da redação — a aba montaria sozinha e o
        # guard mediria uma tela que não existe.
        elif "/api/dre/parecer/narrativa" in url:
            corpo = NARRATIVA
        elif "/api/dre/parecer" in url:
            corpo = PARECER
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


def test_parecer_cabe_em_uma_tela_com_as_evidencias_todas(pagina):
    """A aba monta TUDO em JavaScript: vazia ela mede 300px e passa em
    qualquer régua. Cheia — doze causas, dez provisões, nove não recorrentes e
    a redação do modelo — ela tem de continuar cabendo, e é para isso que os
    dois `.tabroll` com altura máxima existem."""
    pg = _abre(pagina)
    alt, larg = _mede(pg, "par")
    n = pg.evaluate("() => document.querySelectorAll('#dre-par-evid tr').length")
    assert n >= 30, "o guard mediria uma aba mais vazia que a real (%d linhas)" % n
    assert alt <= ALTURA_UTIL, "a aba 'Parecer' cheia mede %dpx" % alt
    assert larg == 0, "a aba 'Parecer' empurra a página para o lado"


def test_parecer_mostra_a_leitura_medida_sem_o_modelo(pagina):
    """Sem Ollama a aba não fica sem parecer: ela mostra a leitura MEDIDA e
    DIZ que não houve redação. Número servido calado é pior que tela vazia;
    aqui o que estaria calado seria a ausência do modelo."""
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo, status = ADMIN, 200
        elif "/api/dre/parecer/narrativa" in url:
            corpo, status = {"erro": "erro_consulta"}, 500
        elif "/api/dre/parecer" in url:
            corpo, status = PARECER, 200
        else:
            corpo, status = {}, 200
        r.fulfill(status=status, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base + "/static/index.html#dre")
    pg.wait_for_timeout(900)
    pg.evaluate("([g,q]) => abaTrocar(g,q)", ["dre", "par"])
    pg.wait_for_timeout(1200)

    texto = pg.evaluate("() => document.getElementById('dre-par-texto').innerText")
    origem = pg.evaluate("() => document.getElementById('dre-par-origem').innerText")
    assert "medir com texto curto" in texto, "a leitura medida sumiu da aba"
    assert "não respondeu" in origem, "a aba não disse que ficou sem redação"


def test_parecer_carrega_so_ao_abrir(pagina):
    """Consulta que custa ERP não dispara em aba fechada."""
    pg = _abre(pagina)
    assert pg.evaluate(
        "() => document.getElementById('aba-dre-par').dataset.aoAbrir"
    ) == "loadDrePar"
