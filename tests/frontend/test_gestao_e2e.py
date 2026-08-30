"""As telas de Gestão no navegador.

O backend tem 42 testes próprios. O que só se prova AQUI:

1. **A tela abre nos ABERTOS.** O chip default é "Abertas". Se um dia alguém
   trocar para "Todas", uma lista com 200 ações concluídas e 3 em andamento
   volta a enterrar o que precisa de ação — foi assim que o CRM escondia os 9
   projetos vivos atrás de 135 entregues.
2. **O atraso aparece com o TEMPO decorrido, não só a data.** "05/09" e
   "05/07" parecem a mesma coisa numa lista lida de manhã.
3. **Excluir uma ata avisa que as ações sobrevivem.** É a consequência que não
   se vê ao clicar, e nenhum teste de backend prova que a tela conta isso.
4. **A tela não estoura no boot.** `pageerror` vazio: o `index.html` é um
   script só, e um erro na avaliação derruba o app inteiro, não só a tela.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

USER = {**USUARIO, "admin": False, "perfil": "Gestor",
        "telas": ["gesacao", "gesata"], "id": 7}

_HOJE = "2026-08-28"


def _acao(i, o_que, prazo, **kw):
    d = {"id": i, "o_que": o_que, "por_que": "", "como": "", "onde": "",
         "quanto": None, "reuniao_id": None, "reuniao_codigo": None,
         "reuniao_titulo": None, "responsavel_id": None,
         "responsavel_nome": "Ana", "responsavel": "Ana", "prazo": prazo,
         "area": "Financeiro", "prioridade": "media", "status": "aberta",
         "percentual": 0, "concluida_em": None, "andamentos": 1,
         "ultimo_andamento": _HOJE + "T09:00:00", "prorrogacoes": 0,
         "atrasada": False, "dias_atraso": 0, "dias_para_prazo": 30,
         "vence_em_7": False, "farol": "ok", "parada_dias": 0,
         "criado_em": _HOJE + "T09:00:00", "historico": []}
    d.update(kw)
    return d


ATRASADA = _acao(1, "Levantar limite do Bradesco", "2026-08-10",
                 atrasada=True, dias_atraso=18, dias_para_prazo=None,
                 farol="critico", prioridade="critica", prorrogacoes=2)
NO_PRAZO = _acao(2, "Revisar contrato de agregados", "2026-09-30")

RESUMO = {"abertas": 2, "atrasadas": 1, "vence_7": 0, "concluidas": 5,
          "canceladas": 1, "total": 8, "atrasadas_criticas": 1,
          "concluidas_mes": 3, "valor_atrasado": 0.0, "com_valor": 0,
          "em_dia": 1, "pct_atrasadas": 0.5, "ciclo_n": 5,
          "ciclo_medio": 12.4, "ciclo_mediano": 9.0, "pontual_n": 5,
          "pct_no_prazo": 0.8, "ref": _HOJE}

PAINEL = {
    "resumo": RESUMO,
    "por_responsavel": [
        {"responsavel": "Ana", "responsavel_id": None, "email": None,
         "setor": "", "total": 6, "abertas": 2, "atrasadas": 1,
         "concluidas": 4, "pior_atraso": 18, "base_fraca": False,
         "pct_concluidas": 0.66, "pct_atrasadas": 0.5},
        {"responsavel": "Bruno", "responsavel_id": None, "email": None,
         "setor": "", "total": 1, "abertas": 0, "atrasadas": 0,
         "concluidas": 1, "pior_atraso": None, "base_fraca": True,
         "pct_concluidas": 1.0, "pct_atrasadas": None},
    ],
    "por_area": [{"area": "Financeiro", "total": 8, "abertas": 2,
                  "atrasadas": 1, "concluidas": 5}],
    "evolucao": [{"mes": f"2026-{m:02d}", "criadas": m, "concluidas": 1}
                 for m in range(1, 13)],
    "paradas": [_acao(9, "Cobrar SEFAZ-SC", "2026-07-01", parada_dias=45,
                      atrasada=True, dias_atraso=58, farol="critico")],
    "atrasadas": [ATRASADA], "atrasadas_total": 1,
    "proximas": [ATRASADA, NO_PRAZO],
    "usuarios": [{"id": 7, "nome": "Ana Souza", "email": "ana@x",
                  "cargo": "", "setor": ""}],
    "areas": ["Financeiro", "Comercial"],
    "minhas": {"acoes": [], "abertas": 0, "atrasadas": 0, "vence_7": 0},
    "atualizado_em": _HOJE + "T20:00:00", "fonte": "CÓRTEX",
}

ATA = {"id": 3, "ano": 2026, "sequencia": 7, "codigo": "ATA-2026-007",
       "titulo": "Diretoria — fechamento de agosto", "tipo": "diretoria",
       "area": "Diretoria", "data": "2026-08-31", "hora_inicio": "09:00",
       "hora_fim": "10:30", "local": "Matriz", "pauta": "Caixa",
       "discussao": "", "decisoes": "Levantar limites", "observacoes": "",
       "status": "publicada", "criado_por": "ana", "criado_em": _HOJE,
       "alterado_por": "ana", "alterado_em": _HOJE,
       "participantes": 3, "presentes": 2, "acoes": 4, "acoes_abertas": 2,
       "acoes_atrasadas": 1}

ATAS = {"atas": [ATA], "total": 1, "mostrando": 1,
        "usuarios": PAINEL["usuarios"], "areas": PAINEL["areas"],
        "tipos": [{"chave": "diretoria", "rotulo": "Diretoria"},
                  {"chave": "outra", "rotulo": "Outra"}]}


def _rota(posts=None, acoes=None):
    def rota(route):
        u, req = route.request.url, route.request
        if req.method == "POST" and posts is not None:
            try:
                posts.append((u, json.loads(req.post_data or "{}")))
            except ValueError:                       # pragma: no cover
                posts.append((u, {}))
        if "/api/auth/me" in u:
            corpo = USER
        elif "/gestao/painel" in u:
            corpo = PAINEL
        elif "/gestao/atas/" in u:
            corpo = {**ATA, "lista_participantes": [
                {"id": 1, "usuario_id": 7, "nome": "Ana Souza", "papel": "",
                 "presente": 1, "email": "ana@x", "cargo": ""},
                {"id": 2, "usuario_id": None, "nome": "Contador", "papel": "",
                 "presente": 0, "email": None, "cargo": ""}],
                "lista_acoes": [ATRASADA]}
        elif "/gestao/atas" in u:
            corpo = ATAS
        elif "/gestao/acoes/" in u and "andamento" not in u:
            corpo = {**ATRASADA, "historico": [
                {"id": 1, "ts": _HOJE + "T09:00:00", "usuario": "ana",
                 "texto": "Ação criada.", "status_de": None,
                 "status_para": "aberta", "percentual": 0}]}
        elif "/gestao/acoes" in u:
            lista = acoes if acoes is not None else [ATRASADA, NO_PRAZO]
            corpo = {"acoes": lista, "total": len(lista),
                     "mostrando": len(lista), "usuarios": PAINEL["usuarios"],
                     "areas": PAINEL["areas"]}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    return rota


def _abrir(pg, base_url, vista, espera, posts=None, acoes=None):
    pg.route("**/api/**", _rota(posts, acoes))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#{vista}")
    pg.wait_for_selector(espera, timeout=20000)
    return erros


# ------------------------------------------------------------ planos de ação

def test_a_tela_de_acoes_abre_sem_erro_de_script(pagina):
    pg, base = pagina
    assert _abrir(pg, base, "gesacao", "#ga-lista .gx-item") == []


def test_abre_no_recorte_de_abertas(pagina):
    """Lista dominada por registro encerrado enterra o que precisa de ação."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-chips .gx-chip")
    ligado = pg.inner_text("#ga-chips .gx-chip.on")
    assert "Abertas" in ligado


def test_atraso_mostra_o_tempo_decorrido_nao_so_a_data(pagina):
    """"05/09" e "05/07" parecem a mesma coisa numa lista lida de manhã."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-lista .gx-item")
    primeira = pg.inner_text("#ga-lista .gx-item:nth-child(1)")
    assert "18d de atraso" in primeira
    assert "10/08/2026" in primeira


def test_acao_adiada_mostra_o_contador_de_prorrogacoes(pagina):
    """Sem ele, a ação adiada duas vezes é igual à que nasceu ontem."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-lista .gx-item")
    assert "adiada 2x" in pg.inner_text("#ga-lista .gx-item:nth-child(1)")


def test_a_linha_atrasada_leva_o_farol_critico(pagina):
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-lista .gx-item")
    classe = pg.get_attribute("#ga-lista .gx-item:nth-child(1)", "class")
    assert "critico" in classe


def test_kpi_de_atrasadas_traz_a_quebra(pagina):
    """"84 abertas" não diz se são 84 em dia ou 60 atrasadas."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-kpis .kpi")
    assert "de 2 abertas" in pg.inner_text("#ga-kpis")


def test_ciclo_sem_base_diz_nao_informado(pagina):
    """Zero em verde faria parecer velocidade perfeita onde nada concluiu."""
    pg, base = pagina
    vazio = {**PAINEL, "resumo": {**RESUMO, "ciclo_mediano": None,
                                  "ciclo_n": 0, "pct_no_prazo": None}}
    def rota(route):
        u = route.request.url
        corpo = USER if "/api/auth/me" in u else (
            vazio if "/gestao/painel" in u else
            {"acoes": [], "total": 0, "mostrando": 0, "usuarios": [], "areas": []})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#gesacao")
    pg.wait_for_selector("#ga-kpis .kpi", timeout=20000)
    texto = pg.inner_text("#ga-kpis")
    assert "não informado" in texto
    assert "0 dias" not in texto


def test_responsavel_com_pouca_base_fica_marcado(pagina):
    """Atenuado e rotulado, nunca escondido."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-resp-tab table")
    assert "base fraca" in pg.inner_text("#ga-resp-tab")


def test_paradas_mostra_ha_quantos_dias(pagina):
    """O alerta que o status não dá."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-par-tab table")
    assert "45d" in pg.inner_text("#ga-par-tab")


def test_grafico_hachura_o_mes_corrente(pagina):
    """Período incompleto nunca é barra cheia.

    Mede a REGRA e não a marcação: a asserção anterior procurava `gaHx`, o id
    do `<pattern>` que a versão desenhada à mão criava, e quebrou na conversão
    para ECharts sem que a hachura tivesse sumido. O que importa é que exista
    hachura e que ela caia SÓ no mês corrente — as duas barras dele (criadas e
    concluídas), nenhuma das outras.
    """
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-evo svg")
    r = pg.evaluate("""() => {
        const barras = [...document.querySelectorAll('#ga-evo path, #ga-evo rect')]
          .map(x => x.getAttribute('fill') || '')
          .filter(f => f && f !== 'none' && f !== 'transparent');
        return {hachuradas: barras.filter(f => f.startsWith('url(')).length,
                padroes: document.querySelectorAll('#ga-evo pattern').length};
    }""")
    assert r["padroes"] >= 1, "nenhuma hachura definida no gráfico"
    assert r["hachuradas"] == 2, (
        "o mês corrente tem duas barras (criadas e concluídas) e as duas saem "
        f"hachuradas; achei {r['hachuradas']}")
    # a hachura SEM legenda e um enigma -- quem olha nao sabe se e outra
    # categoria. Esta linha ja cobrou o rotulo de volta uma vez.
    assert "parcial" in pg.inner_text("#ga-evo")


def test_concordancia_de_plural(pagina):
    """`'ação' + 'ões'` dava "açãoões" na tela — a forma plural vai inteira.
    Mesma classe do "1 dias" da Comunicação Rastreadora."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-hint")
    assert pg.inner_text("#ga-hint") == "2 ações no recorte"
    assert "açãoões" not in pg.inner_text("#view-gesacao")


def test_concordancia_no_singular(pagina):
    """Página nova: um segundo `goto` para a MESMA url+hash não recarrega, e o
    dublê antigo continuaria respondendo."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-hint", acoes=[ATRASADA])
    assert pg.inner_text("#ga-hint") == "1 ação no recorte"


def test_lista_vazia_nao_fica_em_branco(pagina):
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-lista", acoes=[])
    assert "Nenhuma ação aqui" in pg.inner_text("#ga-lista")


def test_ficha_da_acao_abre_com_historico(pagina):
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-lista .gx-item")
    pg.click("#ga-lista .gx-item:nth-child(1)")
    pg.wait_for_selector("#gaa-txt", timeout=10000)
    corpo = pg.inner_text("#modalBox")
    assert "Ação criada." in corpo
    assert "Atrasada há 18 dias" in corpo


def test_andamento_manda_texto_status_e_percentual(pagina):
    pg, base = pagina
    posts = []
    _abrir(pg, base, "gesacao", "#ga-lista .gx-item", posts=posts)
    pg.click("#ga-lista .gx-item:nth-child(1)")
    pg.wait_for_selector("#gaa-txt", timeout=10000)
    pg.fill("#gaa-txt", "Gerente retorna dia 3.")
    pg.select_option("#gaa-st", "em_andamento")
    pg.fill("#gaa-pct", "40")
    pg.click("#modalBox button:has-text('Registrar andamento')")
    pg.wait_for_timeout(600)
    enviados = [c for u, c in posts if "andamento" in u]
    assert enviados and enviados[0]["texto"] == "Gerente retorna dia 3."
    assert enviados[0]["status"] == "em_andamento"
    assert enviados[0]["percentual"] == "40"


def test_formulario_usa_texto_e_nao_number_no_valor(pagina):
    """<input type=number> DESCARTA a vírgula: 1234,56 viraria 123456."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-nova")
    pg.click("#ga-nova")
    pg.wait_for_selector("#gf-quanto", timeout=10000)
    assert pg.get_attribute("#gf-quanto", "type") == "text"
    assert pg.get_attribute("#gf-quanto", "inputmode") == "decimal"


def test_escolher_usuario_desabilita_o_nome_livre(pagina):
    """Um OU outro — nunca ação com dois donos aparentes."""
    pg, base = pagina
    _abrir(pg, base, "gesacao", "#ga-nova")
    pg.click("#ga-nova")
    pg.wait_for_selector("#gf-resp", timeout=10000)
    assert pg.is_enabled("#gf-respn")
    pg.select_option("#gf-resp", "7")
    assert not pg.is_enabled("#gf-respn")


# -------------------------------------------------------------------- atas

def test_a_tela_de_atas_abre_sem_erro_de_script(pagina):
    pg, base = pagina
    assert _abrir(pg, base, "gesata", "#gt-lista .gx-ata") == []


def test_cartao_da_ata_mostra_codigo_e_execucao(pagina):
    """A ata sem plano de ação e a ata com ação atrasada são estados
    diferentes, e é isso que o cartão precisa dizer de relance."""
    pg, base = pagina
    _abrir(pg, base, "gesata", "#gt-lista .gx-ata")
    cartao = pg.inner_text("#gt-lista .gx-ata:nth-child(1)")
    assert "ATA-2026-007" in cartao
    assert "2/3 presentes" in cartao
    assert "1 atrasada" in cartao


def test_kpi_de_ata_com_acao_atrasada(pagina):
    """O indicador de que a reunião decidiu e a decisão não andou."""
    pg, base = pagina
    _abrir(pg, base, "gesata", "#gt-kpis .kpi")
    assert "decisão sem execução" in pg.inner_text("#gt-kpis")


def test_ficha_da_ata_separa_decisoes_e_lista_ausentes(pagina):
    pg, base = pagina
    _abrir(pg, base, "gesata", "#gt-lista .gx-ata")
    pg.click("#gt-lista .gx-ata:nth-child(1)")
    # `#modalBox` existe SEMPRE no DOM: esperar por ele casa o estado
    # "Carregando…". A espera é pelo conteúdo que só a resposta traz.
    pg.wait_for_selector("#modalBox h4:has-text('Participantes')", timeout=10000)
    corpo = pg.inner_text("#modalBox")
    assert "Decisões" in corpo and "Levantar limites" in corpo
    assert "(ausente)" in corpo            # convocado ≠ presente
    assert "Plano de ação" in corpo


def test_excluir_ata_avisa_que_as_acoes_sobrevivem(pagina):
    """A consequência que não se vê ao clicar."""
    pg, base = pagina
    _abrir(pg, base, "gesata", "#gt-lista .gx-ata")
    dialogos = []
    pg.on("dialog", lambda d: (dialogos.append(d.message), d.dismiss()))
    pg.click("#gt-lista .gx-ata:nth-child(1)")
    pg.wait_for_selector("#modalBox h4:has-text('Participantes')", timeout=10000)
    # escopo no modal: `button:has-text('Editar')` solto casa o #btnCredEdit,
    # que existe escondido noutra tela e nunca fica clicável
    pg.click("#modalBox button:has-text('Editar')")
    pg.wait_for_selector("#gt-tit", timeout=10000)
    pg.click("#modalBox button:has-text('Excluir')")
    pg.wait_for_timeout(400)
    assert dialogos and "NÃO serão apagadas" in dialogos[0]
