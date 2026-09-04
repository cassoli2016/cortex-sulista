"""A tela de Avaliação de Desempenho, renderizada com dado CHEIO.

A régua da casa (`medir_paineis`) dubla a API com `{}` e mede a tela vazia.
Para uma matriz nine box isso mede nove caixas em branco — e uma caixa com
onze nomes dentro tem outra altura. O mesmo falso verde já deixou a aba "Onde
atacar" subir ao ar com 1.111px contra a régua de 900, sem um teste vermelho.

O que estes guards cobram:

1. **A matriz é 3×3 e o eixo se escreve.** Sem rótulo de eixo ninguém sabe se
   a linha de cima é potencial alto ou desempenho alto, e as duas leituras
   levam a decisões opostas sobre a mesma pessoa.
2. **A caixa 9 fica em cima à direita.** Nine box desenhado ao contrário é
   pior que nenhum: ele parece certo.
3. **Quem não foi avaliado NÃO aparece na matriz** — aparece como pendente, e
   a cobertura fica no topo.
4. **Cabe em uma tela**, com onze nomes na maior caixa.
5. **Gestor sem mapa vê a explicação**, não uma matriz vazia que se lê como
   "ninguém foi avaliado".
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

# `des` é a tela; `desrh` é a permissão de administração (sem menu).
GESTOR = {**USUARIO, "admin": False, "perfil": "Gestor", "telas": ["des"]}
RH = {**USUARIO, "admin": False, "perfil": "RH", "telas": ["des", "desrh"]}

ALTURA_UTIL = 900

CAIXAS_NOME = {1: "Insuficiente", 2: "Eficaz", 3: "Especialista",
               4: "Em desenvolvimento", 5: "Mantenedor", 6: "Forte desempenho",
               7: "Enigma", 8: "Alto potencial", 9: "Estrela"}


def _pessoa(i, n=None):
    return {"codintfunc": 100 + i, "chapa": "%04d" % i,
            "nome": n or "PESSOA DE NOME COMPRIDO %d" % i,
            "cargo": "ANALISTA DE ALGUMA COISA", "area": "ADMINISTRATIVO",
            "secao": "CONTABILIDADE"}


def _matriz(por_caixa=11):
    i = 0
    caixas = []
    for n in sorted(CAIXAS_NOME, reverse=True):
        gente = []
        for _ in range(por_caixa):
            i += 1
            gente.append({**_pessoa(i), "caixa": n, "desempenho": 2,
                          "potencial": 2})
        caixas.append({"n": n, "nome": CAIXAS_NOME[n], "cor": "atencao",
                       "conduta": "Uma conduta escrita, do tamanho que elas "
                                  "têm de verdade no módulo.",
                       "pessoas": gente, "quantos": len(gente), "pct": 11.1})
    return {"ciclo_id": 1, "caixas": caixas,
            "pendentes": [_pessoa(900 + k) for k in range(7)],
            "kpis": {"pessoas": por_caixa * 9 + 7, "avaliados": por_caixa * 9,
                     "pendentes": 7, "cobertura": 93.4},
            "alcance": "ADMINISTRATIVO", "sem_escopo": False,
            "ver_tudo": False, "fonte": "notas do gestor no ciclo"}


def _equipe(n=60):
    return {"linhas": [{"codintfunc": 100 + i, "chapafunc": "%04d" % i,
                        "nomefunc": "PESSOA DE NOME COMPRIDO %d" % i,
                        "cargo": "ANALISTA DE ALGUMA COISA",
                        "area": "ADMINISTRATIVO", "secao": "CONTABILIDADE",
                        "desempenho": 2 if i % 3 else None,
                        "potencial": 2 if i % 3 else None,
                        "justificativa": "entregou o combinado" if i % 3 else None}
                       for i in range(n)],
            "ciclo": {"id": 1, "nome": "1º semestre 2026", "estado": "aberto"},
            "alcance": "ADMINISTRATIVO", "sem_escopo": False, "ver_tudo": False}


ALTURA = """() => {
  const c = document.getElementById('content');
  const b = c.querySelector('#banner');
  const fora = (b && b.offsetParent !== null)
    ? Math.round(b.getBoundingClientRect().height) + 14 : 0;
  return Math.round(c.scrollHeight) - fora;
}"""
LARGURA = ("() => Math.max(0, document.documentElement.scrollWidth"
           " - document.documentElement.clientWidth)")


def _abre(pagina, usuario=GESTOR, matriz=None, equipe=None):
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo = usuario
        elif "/api/desempenho/matriz" in url:
            corpo = matriz if matriz is not None else _matriz()
        elif "/api/desempenho/equipe" in url:
            corpo = equipe if equipe is not None else _equipe()
        elif "/api/desempenho/ciclos" in url:
            corpo = {"linhas": [{"id": 1, "nome": "1º semestre 2026",
                                 "inicio": "2026-01-01", "fim": "2026-06-30",
                                 "estado": "aberto"}], "aberto": {"id": 1}}
        elif "/api/desempenho/gestores" in url:
            corpo = {"linhas": [{"id": 1, "email": "gestor@sulista.com.br",
                                 "escopo_tipo": "area",
                                 "escopo_valor": "ADMINISTRATIVO"}]}
        else:
            corpo = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base + "/static/index.html#des")
    pg.wait_for_timeout(1200)
    return pg


def test_a_matriz_e_3x3_com_o_eixo_escrito(pagina):
    pg = _abre(pagina)
    pg.wait_for_selector("#des-matriz .nbcx")
    assert pg.eval_on_selector_all("#des-matriz .nbcx", "es => es.length") == 9
    txt = pg.inner_text("#des-matriz").lower()
    assert "potencial" in txt, "a matriz não diz qual eixo é qual"
    assert "desempenho" in txt
    # E OS ROTULOS FICAM NA BORDA, nao dentro da grade: sem `grid-row: span 3`
    # no eixo, a auto-colocacao empurra os nove quadros uma posicao e os
    # rodapes sobem para dentro da matriz. Nao da erro — so fica torto.
    alturas = pg.eval_on_selector_all(
        "#des-matriz .nbrod", "es => es.map(e => e.offsetHeight)")
    assert len(alturas) == 3 and max(alturas) < 40,         "os rótulos do eixo X caíram dentro da grade: %r" % alturas


def test_a_caixa_9_fica_em_cima_a_direita(pagina):
    """Nine box desenhado ao contrário é pior que nenhum: ele parece certo."""
    pg = _abre(pagina)
    pg.wait_for_selector("#des-matriz .nbcx")
    nomes = pg.eval_on_selector_all(
        "#des-matriz .nbcx .nbnome", "es => es.map(e => e.textContent.trim())")
    # a grade lê da esquerda para a direita, de cima para baixo
    assert nomes[0] == "Enigma" and nomes[2] == "Estrela", nomes
    assert nomes[6] == "Insuficiente" and nomes[8] == "Especialista", nomes


def test_a_cobertura_fica_no_topo(pagina):
    """Uma matriz com 12 de 47 avaliados e uma com 47 de 47 se parecem na
    tela e dizem coisas muito diferentes."""
    pg = _abre(pagina)
    pg.wait_for_selector("#kpis-des .kpi")
    txt = pg.inner_text("#kpis-des")
    assert "Cobertura" in txt and "93,4%" in txt
    assert "Pendentes" in txt and "7" in txt


def test_quem_nao_foi_avaliado_NAO_aparece_na_matriz(pagina):
    pg = _abre(pagina)
    pg.wait_for_selector("#des-matriz .nbcx")
    dentro = pg.inner_text("#des-matriz")
    assert "PESSOA DE NOME COMPRIDO 901" not in dentro, \
        "um pendente entrou numa caixa da matriz"


def test_a_tela_cabe_em_uma_tela_com_a_matriz_cheia(pagina):
    """Onze nomes na maior caixa — a régua da casa mede nove caixas VAZIAS."""
    pg = _abre(pagina)
    pg.wait_for_selector("#des-matriz .nbcx")
    alt, larg = pg.evaluate(ALTURA), pg.evaluate(LARGURA)
    assert alt <= ALTURA_UTIL, "a matriz cheia mede %dpx" % alt
    assert larg == 0, "a matriz empurra a página para o lado"


def test_a_aba_avaliar_cheia_tambem_cabe(pagina):
    pg = _abre(pagina)
    pg.wait_for_selector("#des-matriz .nbcx")
    pg.evaluate("([g,q]) => abaTrocar(g,q)", ["des", "ava"])
    pg.wait_for_timeout(600)
    n = pg.eval_on_selector_all("#des-equipe tbody tr", "es => es.length")
    assert n == 60, "o guard mediria uma lista mais curta que a real (%d)" % n
    alt, larg = pg.evaluate(ALTURA), pg.evaluate(LARGURA)
    assert alt <= ALTURA_UTIL, "a aba Avaliar cheia mede %dpx" % alt
    assert larg == 0


def test_gestor_sem_mapa_ve_a_EXPLICACAO_e_nao_uma_matriz_vazia(pagina):
    """Matriz vazia se lê como "ninguém foi avaliado", que é outra coisa."""
    pg = _abre(pagina, matriz={"sem_escopo": True, "caixas": [],
                               "pendentes": [], "kpis": {}, "alcance": ""})
    pg.wait_for_selector("#des-matriz .avisofaixa")
    txt = pg.inner_text("#des-matriz")
    assert "área" in txt.lower() and "RH" in txt
    assert pg.eval_on_selector_all("#des-matriz .nbcx", "es => es.length") == 0


def test_sem_ciclo_a_tela_diz_o_que_falta(pagina):
    pg = _abre(pagina, matriz={"sem_ciclo": True, "caixas": [],
                               "pendentes": [], "kpis": {}})
    pg.wait_for_timeout(400)
    assert "ciclo" in pg.inner_text("#des-matriz").lower()


def test_quem_so_avalia_NAO_ve_a_aba_de_administracao(pagina):
    """`desrh` é permissão, não tela de menu: quem só avalia não administra
    ciclo nem mexe no mapa de quem avalia quem.

    Dois testes e não um: a fixture `pagina` dá UMA página, e reabrir com outro
    usuário na mesma URL (mesmo fragmento) não recarrega — o teste mediria duas
    vezes o mesmo estado e o segundo caso passaria por vacuidade.
    """
    pg = _abre(pagina, usuario=GESTOR)
    pg.wait_for_selector("#des-matriz .nbcx")
    assert pg.eval_on_selector("#tabdes-adm", "e => e.hidden") is True


def test_com_desrh_a_aba_de_administracao_aparece(pagina):
    pg = _abre(pagina, usuario=RH)
    pg.wait_for_selector("#des-matriz .nbcx")
    assert pg.eval_on_selector("#tabdes-adm", "e => e.hidden") is False
    pg.evaluate("([g,q]) => abaTrocar(g,q)", ["des", "adm"])
    pg.wait_for_selector("#des-gestores table")
    txt = pg.inner_text("#aba-des-adm")
    assert "ADMINISTRATIVO" in txt and "gestor@sulista.com.br" in txt
