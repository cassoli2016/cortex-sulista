"""As duas telas do Suporte e a conversa, contra o index.html real com a API
dublada: `#sup?chamado=N` abre a conversa e limpa o hash; responder manda o
texto; a bancada mostra fila, KPIs, "exige ação" e filtra; tudo o que a tela
diz vem CALCULADO do servidor (com quem, SLA, novas) — o teste só confere que
a tela repete o que recebeu e não inventa."""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

T = "2026-09-02T07:00:00-03:00"
C1 = {"id": 1, "codigo": "SUP-2026-0001", "titulo": "Saldo não bate", "tipo": "bug", "gravidade": "alta",
      "tela": "fluxo", "status": "aguardando_usuario", "esperando": "usuario", "usuario_id": 7,
      "usuario_nome": "Ana Silva", "atribuido_id": 2, "atribuido_nome": "Beto Suporte",
      "criado_em": T, "status_em": T, "atualizado_em": T, "avisar_email": True, "avisar_whatsapp": False,
      "novas_usuario": 2, "novas_suporte": 0, "horas_sem_resposta": None, "sla_horas": 8, "sla_estourado": False,
      "idade_h": 30.0, "status_ha_h": 3.0, "primeira_resposta_h": 1.5, "avaliacao": None, "github_numero": None,
      "github_url": None, "github_erro": None, "motivo_fechamento": ""}
C2 = {**C1, "id": 2, "codigo": "SUP-2026-0002", "titulo": "Exportar CSV do pedágio", "tipo": "melhoria",
      "gravidade": "baixa", "tela": "pedagio", "status": "aberto", "esperando": "suporte", "atribuido_id": None,
      "atribuido_nome": None, "novas_usuario": 0, "novas_suporte": 1, "horas_sem_resposta": 130.0,
      "sla_estourado": True, "sla_horas": 120}
DETALHE = {**C1, "descricao": "O total do card veio menor que a soma.",
           "contexto": {"tela": "fluxo", "tela_nome": "Fluxo de Caixa e Bancos", "filtros": "filial=1", "versao": "CX-x", "erros": []},
           "anexos": [{"id": 5, "chamado_id": 1, "mensagem_id": None, "nome": "anexo-1.png", "mime": "image/png", "tamanho": 1234, "github_url": None}],
           "mensagens_lista": [
               {"id": 1, "papel": "sistema", "autor_nome": "", "texto": "Chamado aberto por Ana Silva.", "evento": "status",
                "status_de": "", "status_para": "aberto", "interna": False, "origem": "sistema", "criado_em": T},
               {"id": 2, "papel": "suporte", "autor_nome": "Beto Suporte", "texto": "Qual filial você estava olhando?",
                "evento": "", "status_de": "", "status_para": "", "interna": False, "origem": "painel", "criado_em": T}],
           "avisos": [{"id": 1, "canal": "email", "lado": "usuario", "evento": "resposta_suporte", "destinatario": "a***@x",
                       "resultado": "enviado", "detalhe": "", "criado_em": T}]}
MEUS = {"chamados": [C1], "total": 1, "kpis": {"abertos": 1, "aguardando_voce": 1, "novas": 2, "resolvidos_30d": 0},
        "primeira_resposta_mediana_h": {"n": 3, "mediana_h": 2.5, "p90_h": 6.0}, "sla": {"alta": 8, "media": 48, "baixa": 120}}
PAINEL = {"kpis": {"abertos": 2, "com_suporte": 1, "sla_estourados": 1, "aguardando_usuario": 1, "resolvidos_a_confirmar": 0,
                   "sem_atendente": 1, "novas_para_suporte": 1, "primeira_resposta": {"n": 3, "mediana_h": 2.5, "p90_h": 6.0},
                   "avaliacao_media": 4.5, "avaliacoes": 2, "espelho_com_erro": 0},
          "fila": {"chamados": [C2, C1], "mostrando": 2, "total": 5}, "atendentes": [{"id": 2, "nome": "Beto Suporte"}],
          "espelho": {"pulou": True}, "config": {},
          "status": [{"valor": s, "rotulo": r} for s, r in (("aberto", "Recebido"), ("em_atendimento", "Em atendimento"),
                                                            ("aguardando_usuario", "Aguardando usuário"), ("resolvido", "Resolvido"), ("fechado", "Encerrado"))],
          "motivos": []}
INDIC = {"dias": 84, "total": 5, "semanas": [{"semana": "2026-08-24", "abertos": 2, "resolvidos": 1, "parcial": False},
                                             {"semana": "2026-08-31", "abertos": 3, "resolvidos": 1, "parcial": True}]}


def _mockar(pg):
    posts: list[tuple[str, dict]] = []

    def rota(route):
        u, m = route.request.url, route.request.method
        corpo, status = {}, 200
        if "/api/auth/me" in u:
            corpo = {**USUARIO, "admin": True, "telas": list(USUARIO.get("telas") or []) + ["supfila"]}
        elif "/api/suporte/meus/config" in u:
            corpo = {"ativo": True, "canais": {"email": {"disponivel": True, "destino": "a***@x", "motivo": ""},
                                                "whatsapp": {"disponivel": True, "destino": "5547*****01", "motivo": ""}},
                     "ultima_escolha": {"email": True, "whatsapp": True}, "sou_suporte": True}
        elif "/api/suporte/meus?situacao=ativos" in u:
            corpo = MEUS
        elif "/api/suporte/meus?situacao=encerrados" in u:
            corpo = {**MEUS, "chamados": []}
        elif "/api/suporte/atendimento/painel" in u:
            corpo = PAINEL
        elif "/api/suporte/atendimento/indicadores" in u:
            corpo = INDIC
        elif m == "POST" and "/api/suporte/" in u:
            try:
                posts.append((u.split("/api/suporte/")[1], json.loads(route.request.post_data or "{}")))
            except ValueError:
                posts.append((u.split("/api/suporte/")[1], {}))
            corpo = {"ok": True, "mensagem_id": 3, "id": 7, "codigo": "SUP-2026-0007", "url": "#sup?chamado=7"}
        elif "/chamados/1" in u or "/chamados/7" in u:
            corpo = DETALHE
        route.fulfill(status=status, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    return posts


def _ir(pg, base, hash_):
    posts = _mockar(pg)
    pg.goto(f"{base}/static/index.html{hash_}")
    pg.wait_for_function("() => window.USER !== null", timeout=20000)
    return posts


def test_meus_chamados_kpis_lista_e_a_url_abre_a_conversa(pagina):
    pg, base = pagina
    posts = _ir(pg, base, "#sup?chamado=1")
    pg.wait_for_selector("#modalBox .sup-thread", timeout=10000)
    # o hash ficou limpo: F5 não reabre o modal
    assert pg.evaluate("location.hash") == "#sup"
    kpis = pg.inner_text("#kpis-sup")
    assert "Aguardando você" in kpis and "Respostas novas" in kpis
    linha = pg.inner_text("#sup-meus tr")
    assert "SUP-2026-0001" in linha and "Aguardando você" in linha and "você" in linha
    modal = pg.inner_text("#modalBox")
    assert "Qual filial você estava olhando?" in modal and "Beto Suporte" in modal
    assert "anexo-1.png" in modal and "O suporte precisa de uma resposta sua" in modal
    # abrir É ler
    assert any(p[0] == "meus/chamados/1/lido" for p in posts)
    # o dono não vê a trilha de avisos nem nota interna
    assert "Avisos" not in modal and pg.query_selector("#sup-interna") is None


def test_responder_manda_o_texto_e_recarrega_a_conversa(pagina):
    pg, base = pagina
    posts = _ir(pg, base, "#sup?chamado=1")
    pg.wait_for_selector("#sup-texto", timeout=10000)
    pg.click("#sup-enviar")
    pg.wait_for_timeout(150)
    assert "Escreva a mensagem" in pg.inner_text("#m-err")
    pg.fill("#sup-texto", "Filial 1.")
    pg.click("#sup-enviar")
    pg.wait_for_function("() => document.querySelector('#sup-texto') && document.querySelector('#sup-texto').value === ''",
                         timeout=5000)
    env = [p for p in posts if p[0] == "meus/chamados/1/mensagens"]
    assert env and env[0][1] == {"texto": "Filial 1.", "anexos": []}


def test_canais_do_chamado_sao_editaveis_pela_conversa(pagina):
    pg, base = pagina
    posts = _ir(pg, base, "#sup?chamado=1")
    pg.wait_for_selector(".sup-canais", timeout=10000)
    pg.click(".sup-canais input >> nth=1")     # WhatsApp
    pg.wait_for_timeout(300)
    assert ("meus/chamados/1/canais", {"whatsapp": True}) in posts


def test_bancada_kpis_fila_prioridade_exige_acao_e_filtro(pagina):
    pg, base = pagina
    _ir(pg, base, "#supfila")
    # o gráfico de semanas nasce na aba aberta (Painel) e desenha antes de qualquer clique
    pg.wait_for_selector("#chartSupSemanas svg", timeout=15000)
    pg.wait_for_selector("#supfila-fila tr", state="attached", timeout=10000)
    pg.click("#tabsupfila-fila")                       # a fila é sub-aba; a régua abre pelo botão
    pg.wait_for_selector("#supfila-fila tr", timeout=5000)
    kpis = pg.inner_text("#kpis-supfila")
    assert "Fora do SLA" in kpis and "Sem atendente" in kpis
    linhas = pg.query_selector_all("#supfila-fila tr")
    assert len(linhas) == 2
    primeira = linhas[0].inner_text()
    assert "SUP-2026-0002" in primeira and "suporte" in primeira and "5 d" in primeira   # 130 h sem resposta
    acao = pg.inner_text("#supfila-acao")
    assert "sem atendente" in acao and "fora do SLA" in acao
    assert "2 de 2 em aberto" in pg.inner_text("#hintSupFila")
    pg.select_option("#fSupGrav", "baixa")
    assert len(pg.query_selector_all("#supfila-fila tr")) == 1
    pg.fill("#fSupBusca", "saldo")
    assert "Nenhum chamado com esses filtros" in pg.inner_text("#supfila-fila")


def test_bancada_abre_a_conversa_com_acoes_nota_interna_e_avisos(pagina):
    pg, base = pagina
    posts = _ir(pg, base, "#supfila?chamado=1")
    pg.wait_for_selector("#modalBox .sup-thread", timeout=10000)
    assert pg.evaluate("location.hash") == "#supfila"
    modal = pg.inner_text("#modalBox")
    assert "Ana Silva" in modal and "Avisos" in modal and "Perguntar ao usuário" in modal
    assert pg.query_selector("#sup-interna") is not None
    assert any(p[0] == "atendimento/chamados/1/lido" for p in posts)
    pg.fill("#sup-texto", "Vou olhar.")
    pg.check("#sup-interna")
    pg.click("#sup-enviar")
    pg.wait_for_timeout(400)
    env = [p for p in posts if p[0] == "atendimento/chamados/1/mensagens"]
    assert env and env[0][1]["interna"] is True and env[0][1]["texto"] == "Vou olhar."


def test_tela_sup_e_de_todo_usuario_e_a_bancada_nao(pagina):
    """`sup` aparece no menu de quem não tem tela nenhuma; `supfila` só de quem tem."""
    pg, base = pagina

    def rota(route):
        u = route.request.url
        corpo = {}
        if "/api/auth/me" in u:
            corpo = {**USUARIO, "admin": False, "telas": ["home"]}
        elif "/api/suporte/meus/config" in u:
            corpo = {"ativo": True, "canais": {}, "ultima_escolha": {}}
        elif "/api/suporte/meus" in u:
            corpo = {**MEUS, "chamados": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#supfila")
    pg.wait_for_function("() => window.USER !== null", timeout=20000)
    pg.wait_for_timeout(300)
    assert pg.evaluate("podeVer('sup')") is True
    assert pg.evaluate("podeVer('supfila')") is False
    assert pg.evaluate("currentView()") != "supfila"
    # o menu esconde por style.display (o grupo Administração nasce recolhido,
    # então is_visible não serve): o link de sup fica, o de supfila some, e o
    # grupo aparece para quem só tem o Suporte
    mostra = lambda sel: pg.eval_on_selector(sel, "e=>e.style.display!=='none'")
    assert mostra("#sidebar a[data-view=sup]") is True
    assert mostra("#sidebar a[data-view=supfila]") is False
    assert mostra("#grpAdm") is True
