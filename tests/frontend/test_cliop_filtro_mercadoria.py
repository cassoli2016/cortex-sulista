"""O filtro de mercadoria da Minha Operação — NO NAVEGADOR.

No navegador porque os dois defeitos que importam aqui são MUDOS:

  1. o seletor existe, a pessoa escolhe, e a escolha não chega ao servidor —
     a tela devolve a operação inteira e quem filtrou acredita no número;
  2. o seletor some para quem é do cliente, que é justamente quem mais tem
     motivo para separar carga por tipo.

Nenhum dos dois quebra nada. Os dois passariam num teste de texto-fonte, e o
primeiro passaria até com o `fetch` dentro de um `if(false)`.

A tela cobra o servidor pelo que ele REALMENTE recebeu: as rotas do dublê
guardam a URL de cada chamada, e o teste lê o `merc=` de lá.
"""
from __future__ import annotations

import json
import urllib.parse

from tests.frontend.conftest import USUARIO

CASA = {**USUARIO, "admin": True, "perfil": "Administrador"}

MERCADORIAS = [
    {"chave": "CHASSI", "rotulo": "CHASSI", "cargas": 1551},
    {"chave": "EMBALAGEM", "rotulo": "EMBALAGENS", "cargas": 1395},
    {"chave": "RODA", "rotulo": "RODAS", "cargas": 773},
]

AGORA = {
    "cargas": [{
        "coleta": 20222, "emissao": "2026-09-09",
        "origem": "CIDADE A", "uf_origem": "SP",
        "destino": "CIDADE B", "uf_destino": "RJ",
        "destinatario": "MONTADORA - CIDADE B/RJ", "placa": "AAA1A11",
        "marco": "Em viagem", "marco_cod": 400, "marco_em": "",
        "marco_fonte": "apontamento",
        "janela_carga": "", "janela_entrega": "",
        "chegada": None, "chegada_fonte": None, "desvio_h": None,
        "pos": None, "eta": None, "eta_amostras": None,
    }],
    "em_curso": 1, "sem_apontamento": 0, "por_destinatario": [],
    "concluidas_na_janela": 0, "janela_dias": 45, "mercadoria": "",
    "mercadorias": MERCADORIAS,
    "posicao": {"com_posicao": 0, "frescas": 0, "fontes": {}, "veiculos": 1,
                "fresca_ate_min": 120},
    "travado": True, "cliente_raiz": "11222333",
    "cliente_nome": "CLIENTE DUBLÊ S.A.",
    "fonte": "Sistema de gestão · leitura",
}

# O payload da permanência com a FORMA nova: cada etapa traz `origens`, e a
# resposta é binária para quem tem cláusula. Copiado da forma real de
# 10/09/2026 (IOCHPE MAXION, 90 dias).
PERM = {
    "carga": {"mediana_h": 1.4, "n": 1372, "dentro": 1159, "zona": 0,
              "fora": 213, "sem_regua": 0, "dentro_pct": 84.5, "zona_pct": 0.0,
              "fora_pct": 15.5, "fora_da_regua": 12,
              "origens": {"mercadoria": 344, "generico": 1028, "sem_clausula": 0}},
    "descarga": {"mediana_h": 3.0, "n": 1254, "dentro": 632, "zona": 0,
                 "fora": 622, "sem_regua": 0, "dentro_pct": 50.4,
                 "zona_pct": 0.0, "fora_pct": 49.6, "fora_da_regua": 8,
                 "origens": {"mercadoria": 255, "generico": 999, "sem_clausula": 0}},
    "freetime": {
        "contratos": 4, "ambiguo": True,
        "carga_piso": 3.0, "carga_teto": 3.0,
        "descarga_piso": 3.0, "descarga_teto": 6.5,
        "linhas": [
            {"mercadoria": "", "ft_carga_h": 3.0, "ft_descarga_h": 3.0},
            {"mercadoria": "CONJUNTOS", "ft_carga_h": 3.0, "ft_descarga_h": 6.5},
            {"mercadoria": "ESCADAS", "ft_carga_h": 3.0, "ft_descarga_h": 6.5},
            {"mercadoria": "RODAS", "ft_carga_h": 3.0, "ft_descarga_h": 6.5},
        ]},
    "mercadoria": "", "cargas_no_periodo": 1413,
    "periodo": {"de": "2026-06-12", "ate": "2026-09-10"},
    "travado": True, "cliente_raiz": "11222333",
    "cliente_nome": "CLIENTE DUBLÊ S.A.",
    "fonte": "Sistema de gestão · leitura",
}


def _abrir(pg, base_url):
    """Abre a tela e guarda as URLs que ela pediu."""
    pedidos = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/portal/cliente" in u:
            pedidos.append(u)
            corpo = PERM if "aba=permanencia" in u else AGORA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#cliop")
    pg.wait_for_selector("#cliop-agora tr", state="attached", timeout=20000)
    return pedidos, erros


def _merc_da_url(url: str) -> str:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return (q.get("merc") or [""])[0]


def test_a_tela_abre_sem_erro_com_o_filtro_novo(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_o_seletor_nasce_com_as_mercadorias_da_OPERACAO(pagina):
    """A lista sai da operação do cliente, não do contrato.

    O contrato tem quatro cláusulas e a operação tem doze tipos de carga — e é
    entre os doze que quem lê quer escolher. A contagem vai junto porque lista
    de trinta itens sem volume não diz por onde começar.
    """
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#fCliopMerc")
    assert "CHASSI" in txt and "RODAS" in txt
    assert "1.551" in txt, "o volume de cada mercadoria sumiu da lista"
    assert "Todas" in txt, "não dá para voltar a ver a operação inteira"


def test_o_seletor_FICA_para_quem_e_do_cliente(pagina):
    """São duas perguntas, e só a primeira é escopo.

    Quem é do cliente não escolhe DE QUEM é a operação — o vínculo decide, e o
    seletor de cliente some. Mas escolhe O QUE dela está olhando. Esconder a
    barra inteira quando `travado` (que é o que a tela fazia) tiraria o filtro
    justamente de quem tem mais motivo para usá-lo.
    """
    pg, base = pagina
    _abrir(pg, base)
    assert pg.is_visible("#fCliopMerc"), "o filtro sumiu para o cliente"
    assert not pg.is_visible("#fCliopCliente"), (
        "o seletor de CLIENTE apareceu para quem tem vínculo — isso é escopo")


def test_escolher_a_mercadoria_CHEGA_ao_servidor(pagina):
    """O defeito que este arquivo existe para pegar.

    Seletor que muda e não refaz a busca deixa a tela com o rótulo novo e os
    números velhos: a forma mais silenciosa de um painel mentir, porque tudo
    na tela parece ter respondido.
    """
    pg, base = pagina
    pedidos, _ = _abrir(pg, base)
    antes = len(pedidos)
    pg.select_option("#fCliopMerc", "RODAS")
    pg.wait_for_function("document.querySelectorAll('#cliop-agora tr').length > 0",
                         timeout=20000)
    pg.wait_for_timeout(300)
    assert len(pedidos) > antes, "trocar a mercadoria não refez busca nenhuma"
    assert _merc_da_url(pedidos[-1]) == "RODAS", pedidos[-1]


def test_o_filtro_acompanha_a_troca_de_ABA(pagina):
    """Uma escolha, a tela inteira — inclusive a aba que abrir depois.

    Filtro que só vale na aba em que foi escolhido faz a Permanência dizer
    "RODAS" e o Histórico responder pela operação toda, lado a lado.
    """
    pg, base = pagina
    pedidos, _ = _abrir(pg, base)
    pg.select_option("#fCliopMerc", "RODAS")
    pg.wait_for_timeout(300)
    pg.click("#tabcliop-perm")
    pg.wait_for_selector("#cliop-perm-tab tr", state="attached", timeout=20000)
    perm = [u for u in pedidos if "aba=permanencia" in u]
    assert perm, "a aba Permanência não buscou nada"
    assert _merc_da_url(perm[-1]) == "RODAS", perm[-1]


def test_trocar_de_CLIENTE_zera_a_mercadoria(pagina):
    """"ASSENTOS" é da LEAR e não existe na Maxion.

    Um filtro que sobrevivesse à troca faria a tela nascer vazia com o seletor
    apontando para algo que aquela operação não tem — e tela vazia se lê como
    cliente sem carga, não como filtro errado.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.select_option("#fCliopMerc", "RODAS")
    pg.wait_for_timeout(200)
    pg.evaluate("CLIOP_RAIZ = ''; cliopTrocarCliente()")
    assert pg.eval_on_selector("#fCliopMerc", "e => e.value") == ""
    assert pg.evaluate("CLIOP_MERC") == ""


def test_a_permanencia_diz_QUAL_clausula_respondeu(pagina):
    """"3h para RODAS" e "3h porque não há cláusula" são afirmações diferentes.

    Sem essa contagem as duas viram o mesmo número na tela, e a segunda — a
    única que alguém precisa levar ao comercial — deixa de existir.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabcliop-perm")
    pg.wait_for_selector("#cliop-perm-tab tr", state="attached", timeout=20000)
    hint = pg.inner_text("#cliop-ft-hint")
    assert "clausula da propria mercadoria" in hint.lower(), hint
    assert "20%" in hint or "80%" in hint, (
        "a repartição por origem não apareceu: %s" % hint)


def test_as_clausulas_do_contrato_aparecem_com_as_horas(pagina):
    """O pedido era validar o freetime contratado contra o SAC.

    Validar exige ver o contrato: quatro cláusulas, uma genérica de 3h e três
    de 6,5h na descarga. Sem a tabela, a tela afirma um número e não mostra a
    régua que o produziu.

    A aba é CLICADA, e a leitura é do que está VISÍVEL. Ler `inner_text` de um
    painel escondido devolve o texto do mesmo jeito — o teste passaria com a
    sub-aba inalcançável, que é exatamente o defeito que ele existe para pegar.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    assert pg.is_visible("#aba-cliop-ft"), "a sub-aba do contrato não abriu"
    txt = pg.inner_text("#cliop-ft-linhas")
    assert "RODAS" in txt and "CONJUNTOS" in txt
    assert "6,5 h" in txt, "as horas da cláusula não saíram: %s" % txt
    assert "generica" in txt.lower(), "a cláusula genérica não foi rotulada"
    # e o contador da aba diz quantas cláusulas o contrato tem — é por ele que
    # alguém percebe que o contrato mudou sem abrir a aba
    assert pg.inner_text("#abancliopFt").strip() == "4"


def test_sem_contrato_a_aba_diz_ZERO_e_nao_UM(pagina):
    """A linha "sem freetime cadastrado" é uma linha de tabela.

    O contador automático das abas conta linhas de `tbody`, e sem esse cuidado
    um cliente SEM contrato nenhum apareceria com "1" na aba — como se tivesse
    uma cláusula. É um número plausível e falso sobre um contrato comercial.
    """
    pg, base = pagina
    vazio = {**PERM, "freetime": {"contratos": 0, "ambiguo": False,
                                  "carga_piso": None, "carga_teto": None,
                                  "descarga_piso": None, "descarga_teto": None,
                                  "linhas": []}}

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/portal/cliente" in u:
            corpo = vazio if "aba=permanencia" in u else AGORA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(base + "/static/index.html#cliop")
    pg.wait_for_selector("#cliop-agora tr", state="attached", timeout=20000)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    pg.wait_for_timeout(400)   # o contador automático roda com atraso de 200ms
    assert pg.inner_text("#abancliopFt").strip() == "", (
        "sem contrato a aba mostrou um número: %r"
        % pg.inner_text("#abancliopFt"))
    assert "Sem freetime" in pg.inner_text("#cliop-ft-linhas")


def test_a_sub_aba_do_contrato_carrega_SOZINHA(pagina):
    """Abrir a aba do contrato sem passar pela Permanência tem de funcionar.

    Sub-aba que só se preenche se outra foi aberta antes é uma tabela vazia
    para quem entra direto nela — e vazia se lê como "não há contrato", que é
    a conclusão errada mais cara desta tela.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    assert "RODAS" in pg.inner_text("#cliop-ft-linhas")
