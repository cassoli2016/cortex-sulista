"""A tela do Ritual Semanal, contra o index.html real.

O que se protege aqui é o que faz o painel ser confiável de relance:

1. **Automático e manual não se confundem.** O indicador que vem de uma fonte
   do CÓRTEX não pode oferecer campo de digitação — e a tela tem de DIZER de
   onde o número sai. Número automático e número digitado não têm a mesma
   qualidade, e apresentá-los iguais é o que faz um herdar a confiança do outro.

2. **O desvio é orientado pelo que é bom.** Positivo é sempre "melhor que a
   meta", inclusive onde menos é melhor. Sem isso a coluna põe lado a lado um
   −8% ótimo e um −8% péssimo e deixa de poder ser lida de relance, que é a
   única coisa que ela precisa fazer.

3. **As regras que o servidor aplica se distinguem das que dependem das
   pessoas.** Pintar as cinco iguais faria o sistema prometer o que não
   entrega — ninguém obriga a direção a destravar.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO


def _linha(nome, ger, gern, **kw):
    """Uma linha do painel, no formato que `ritual.painel()` publica.

    LITERAL, e não montado a partir do módulo: é formato de resposta de rota, e
    derivá-lo do código que o produz faria o teste provar que o dublê concorda
    com o dublê.
    """
    return {
        "indicador_id": kw.get("id", 1), "nome": nome, "unidade": kw.get("un", "R$"),
        "direcao": kw.get("dir", "maior_melhor"), "fonte": kw.get("fonte", "manual"),
        "casas": kw.get("casas", 0), "meta_padrao": None, "ordem": 0,
        "gerencia": ger, "gerencia_nome": gern, "gestor_nome": kw.get("gestor"),
        "apont_id": kw.get("apont"), "meta": kw.get("meta"), "realizado": None,
        "realizado_auto": None, "status": kw.get("status", ""),
        "desvio": kw.get("desvio", ""), "acao_id": kw.get("acao_id"),
        "prioridade": kw.get("prio"), "preenchido_por": kw.get("por", ""),
        "preenchido_em": "", "acao_o_que": kw.get("acao"),
        "acao_prazo": kw.get("prazo"), "acao_status": "aberta",
        "acao_percentual": 20, "acao_resp_nome": kw.get("resp"),
        "acao_resp_usuario": None,
        "automatico": kw.get("fonte", "manual") != "manual",
        "fonte_onde": kw.get("onde", ""), "fonte_orfa": kw.get("orfa", False),
        "realizado_agora": kw.get("valor"), "valor": kw.get("valor"),
        "meta_valor": kw.get("meta"), "desvio_pct": kw.get("pct"),
        "preenchido": bool(kw.get("status")),
        "acao_atrasada": kw.get("atras", False),
        "exige_acao": kw.get("status") in ("amarelo", "vermelho") and not kw.get("acao_id"),
    }


PAINEL = {
    "ciclo": {"id": 7, "ano": 2026, "semana": 37, "data_reuniao": "2026-09-08",
              "status": "aberto", "observacoes": "", "prazo_preenchimento": ""},
    "gerencias": [
        {"chave": "comercial", "nome": "Comercial", "gestor": "Ana Prado", "linhas": [
            _linha("Receita faturada no mês", "comercial", "Comercial", id=1,
                   fonte="receita_faturada_mes",
                   onde="Visão Geral · faturamento do mês",
                   valor=2148300, meta=2400000, pct=-10.5, status="amarelo",
                   acao_id=3, acao="Retomar os 8 clientes parados",
                   prazo="2026-09-15", resp="Ana Prado", prio=1)]},
        {"chave": "operacao", "nome": "Operação", "gestor": "Carlos Melo", "linhas": [
            # menor_melhor ABAIXO da meta: o desvio tem de sair POSITIVO
            _linha("Custo de manutenção", "operacao", "Operação", id=2,
                   fonte="manutencao_mes", onde="Visão Geral",
                   dir="menor_melhor", valor=16415, meta=22000, pct=25.4,
                   status="verde"),
            # vermelho SEM ação: é o que trava o fechamento
            _linha("Retorno vazio", "operacao", "Operação", id=3, un="%",
                   fonte="manual", dir="menor_melhor", casas=1,
                   valor=20.8, meta=18.0, pct=-15.6, status="vermelho")]},
    ],
    "resumo": {"indicadores": 3, "verde": 1, "amarelo": 1, "vermelho": 1,
               "sem_status": 0, "sem_acao": 1, "automaticos": 2},
    "pendencias": [],
    "bloqueios": [{"tipo": "desvio_sem_acao", "indicador": "Retorno vazio",
                   "gerencia": "Operação",
                   "mensagem": "Retorno vazio (Operação) está vermelho e não tem ação."}],
    "prioridades": [], "fonte": "banco do CÓRTEX",
    "ciclos": [{"id": 7, "ano": 2026, "semana": 37,
                "data_reuniao": "2026-09-08", "status": "aberto"}],
    "cobranca": {"anterior": {"id": 6, "ano": 2026, "semana": 36,
                              "data_reuniao": "2026-09-01"},
                 "itens": [{"id": 3, "o_que": "Retomar os 8 clientes parados",
                            "prazo": "2026-09-08", "status": "concluida",
                            "percentual": 100, "responsavel": "Ana Prado",
                            "indicador": "Receita faturada no mês",
                            "gerencia": "Comercial", "cumpriu": True}],
                 "resumo": {"prometidas": 1, "cumpridas": 1, "abertas": 0,
                            "taxa": 1.0}},
}

SEM_PROMESSA = {**PAINEL, "cobranca": {"anterior": None, "itens": [], "resumo": {}}}

CADASTRO = {
    "gerencias": [{"id": 1, "chave": "comercial", "nome": "Comercial"}],
    "indicadores": [
        {"id": 1, "nome": "Receita faturada no mês", "gerencia_id": 1,
         "gerencia_nome": "Comercial", "unidade": "R$", "direcao": "maior_melhor",
         "fonte": "receita_faturada_mes", "meta_padrao": None, "casas": 0,
         "ordem": 1, "ativo": 1, "automatico": True,
         "fonte_onde": "Visão Geral · faturamento do mês", "fonte_orfa": False}],
    "fontes": [{"chave": "receita_faturada_mes", "rotulo": "Receita faturada no mês",
                "gerencia": "comercial", "unidade": "R$", "casas": 0,
                "direcao": "maior_melhor",
                "onde": "Visão Geral · faturamento do mês (notas emitidas)"}],
    "acoes": [{"id": 3, "o_que": "Retomar os 8 clientes parados",
               "prazo": "2026-09-15", "status": "aberta", "percentual": 20,
               "responsavel": "Ana Prado"}],
    "usuarios": [],
}


def _abrir(pg, base_url, painel=None):
    enviados = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = USUARIO
        elif "/api/ritual/painel" in u:
            corpo = painel or PAINEL
        elif "/api/ritual/cadastro" in u:
            corpo = CADASTRO
        elif "/api/ritual/" in u:
            enviados.append(json.loads(route.request.post_data or "{}"))
            corpo = {"ok": True}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#gesrit")
    pg.wait_for_selector("#rit-painel tr", timeout=20000)
    return enviados, erros


# ============================================================ o painel

def test_a_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_o_painel_agrupa_por_gerencia_e_nomeia_o_gestor(pagina):
    """A linha da gerência não é enfeite: o painel é lido gerência a gerência,
    dois minutos cada, e sem o nome do gestor a cobrança não tem endereço."""
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#rit-painel")
    assert "Comercial" in txt and "Ana Prado" in txt
    assert "Operação" in txt and "Carlos Melo" in txt


def test_o_DESVIO_e_orientado_pelo_que_e_bom(pagina):
    """Custo ABAIXO da meta tem de sair POSITIVO (é bom), e receita abaixo da
    meta, negativo. Sem isso a coluna não pode ser lida de relance."""
    pg, base = pagina
    _abrir(pg, base)
    linhas = pg.locator("#rit-painel tr").all_inner_texts()
    custo = next(l for l in linhas if "Custo de manutenção" in l)
    receita = next(l for l in linhas if "Receita faturada" in l)
    assert "+25,4%" in custo, custo
    assert "-10,5%" in receita, receita


def test_a_linha_DIZ_se_o_numero_e_automatico_ou_digitado(pagina):
    """Número automático e número digitado não têm a mesma qualidade, e
    mostrá-los iguais é o que faz um herdar a confiança do outro."""
    pg, base = pagina
    _abrir(pg, base)
    linhas = pg.locator("#rit-painel tr").all_inner_texts()
    assert "AUTOMÁTICO" in next(l for l in linhas if "Receita faturada" in l).upper()
    assert "MANUAL" in next(l for l in linhas if "Retorno vazio" in l).upper()


def test_desvio_sem_acao_aparece_como_BLOQUEIO_e_na_linha(pagina):
    """A regra central do quadro precisa estar visível ANTES de alguém tentar
    fechar — recusa que só aparece no clique é recusa que surpreende."""
    pg, base = pagina
    _abrir(pg, base)
    banner = pg.inner_text("#rit-bloqueios")
    assert "não fecha pauta" in banner
    assert "Retorno vazio" in banner
    linhas = pg.locator("#rit-painel tr").all_inner_texts()
    assert "falta ação" in next(l for l in linhas if "Retorno vazio" in l)


def test_o_kpi_separa_PREENCHIDO_de_verde(pagina):
    pg, base = pagina
    _abrir(pg, base)
    k = pg.inner_text("#rit-kpis")
    assert "1 / 1 / 1" in k, "o semáforo mostra os três estados"
    assert "3 de 3" in k, "preenchimento é contagem própria, não 'tudo verde'"


# ============================================== o bloco de 2 minutos

def test_o_modal_do_indicador_AUTOMATICO_nao_tem_campo_de_realizado(pagina):
    """Se tivesse, a pessoa acharia que mandou no número — e a próxima pintura,
    que relê a fonte, desfaria na cara dela."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click('#rit-painel button[data-ind="1"]')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    assert pg.locator("#rit-realizado").count() == 0
    txt = pg.inner_text("#modalBox")
    assert "Visão Geral" in txt, "o modal tem de dizer de ONDE vem o número"
    assert "não se digita" in txt.lower()


def test_o_modal_do_indicador_MANUAL_tem_campo_de_realizado(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click('#rit-painel button[data-ind="3"]')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    assert pg.locator("#rit-realizado").count() == 1


def test_o_modal_segue_a_ordem_do_quadro(pagina):
    """Resultado, entrega, desvio, ação, compromisso — é assim que a reunião
    anda, e um formulário em outra ordem faz a pessoa procurar."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click('#rit-painel button[data-ind="3"]')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    txt = pg.inner_text("#modalBox")
    for i, marca in enumerate(["1 · Resultado", "2 · Entrega", "3 · Desvio",
                               "4 · Ação", "5 · Compromisso"]):
        assert marca in txt, marca
    assert txt.index("1 · Resultado") < txt.index("3 · Desvio") < txt.index("4 · Ação")


def test_criar_acao_nova_e_possivel_DENTRO_do_ritual(pagina):
    """Criar ação é rota de admin, e quem tem o desvio é o gerente. Sem este
    caminho a regra do jogo dependeria de terceiro para ser cumprida — e regra
    assim não se cumpre."""
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    pg.click('#rit-painel button[data-ind="3"]')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    pg.select_option("#rit-acao", "nova")
    assert pg.locator("#rit-acao-nova").is_visible()
    pg.fill("#rit-acao-oque", "Renegociar as rotas de retorno")
    pg.fill("#rit-acao-resp", "Carlos Melo")
    pg.click("#modalBox .btn")
    pg.wait_for_timeout(600)
    apont = next(e for e in enviados if "indicador_id" in e)
    assert apont["acao_nova"]["o_que"] == "Renegociar as rotas de retorno"
    assert apont["acao_nova"]["responsavel_nome"] == "Carlos Melo"
    assert apont["acao_nova"]["prazo"], "compromisso sem data não é compromisso"


# ============================================== o que ficou combinado

def test_a_cobranca_mostra_o_que_saiu_e_o_que_nao(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabgesrit-cobr")
    txt = pg.inner_text("#rit-cobr")
    assert "Retomar os 8 clientes parados" in txt
    assert "saiu" in txt


def test_sem_promessa_a_taxa_e_ND_e_nao_zero(pagina):
    """0% diria "ninguém cumpriu nada" numa semana em que nada foi pedido."""
    pg, base = pagina
    _abrir(pg, base, painel=SEM_PROMESSA)
    pg.click("#tabgesrit-cobr")
    k = pg.inner_text("#rit-cobr-kpis")
    assert "n/d" in k
    assert "0%" not in k


def test_as_regras_separam_o_que_o_SISTEMA_aplica(pagina):
    """Pintar as cinco iguais faria o sistema prometer o que não entrega:
    ninguém obriga a direção a destravar, e uma tela que sugere que sim é uma
    tela em que a próxima regra também não vale nada."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabgesrit-cobr")
    txt = pg.inner_text("#rit-regras").lower()
    assert "aplicada pelo sistema" in txt
    assert "combinado entre nós" in txt
    # e a regra central está entre as aplicadas
    linhas = pg.locator("#rit-regras li").all_inner_texts()
    central = next(l for l in linhas if "não fecha pauta" in l)
    assert "aplicada pelo sistema" in central.lower()
