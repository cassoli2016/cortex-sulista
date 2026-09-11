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

def _cl(merc, carga, desc, **kw):
    """Uma cláusula do contrato, na FORMA real de `FREETIME_SQL_TODAS`.

    Os valores são os da IOCHPE MAXION lidos do ERP em 11/09/2026: R$ 102,04
    a hora excedente, vigência desde 01/08/2024 sem término combinado, filial
    20, alterada pela mesma pessoa em 25/09/2025. Dublê que representa formato
    EXTERNO é literal copiado do real, nunca derivado do código que vai lê-lo.
    """
    base = {"mercadoria": merc, "ft_carga_h": carga, "ft_descarga_h": desc,
            "rh_coleta": 102.04, "rh_entrega": 102.04,
            "vig_de": "2024-08-01", "vig_ate": None, "filial": 20,
            "distingue": 1 if merc else 2, "mexido_em": "2025-09-25",
            "mexido_por": "PRISCILLA APARECIDA DINIZ", "confere": True}
    base.update(kw)
    return base


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
            _cl("", 3.0, 3.0), _cl("CONJUNTOS", 3.0, 6.5),
            _cl("ESCADAS", 3.0, 6.5), _cl("RODAS", 3.0, 6.5),
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


def _abrir_com(pg, base_url, perm, agora=None):
    """Abre a parede com um payload de permanência SOB MEDIDA.

    Os casos de contrato (preço que varia, cláusula com prazo, cadastro
    contraditório) não existem na amostra padrão — e é justamente deles que a
    tela precisa dar conta sem ninguém ter visto acontecer.
    """
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/portal/cliente" in u:
            corpo = perm if "aba=permanencia" in u else (agora or AGORA)
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#cliop")
    pg.wait_for_selector("#cliop-agora tr", state="attached", timeout=20000)


def _escolher(pg, mercs):
    """Abre o seletor, marca as mercadorias e aplica — como quem opera faz.

    Pelo MODAL, e não mexendo em `CLIOP_MERC` por `evaluate`: o que precisa
    funcionar é o caminho da pessoa. Um teste que escreve direto na variável
    passaria com o modal quebrado.
    """
    pg.click("#cliop-merc-chips .chip:last-child")
    pg.wait_for_selector("#cm-lista label", state="visible", timeout=20000)
    for m in mercs:
        pg.check("#cm-lista input[value=\"%s\"]" % m)
    pg.click("button.btn:has-text('Aplicar')")
    # `hidden`, e não `detached`: o modal da casa ESCONDE em vez de remover, e
    # esperar por "sumiu do DOM" fica esperando para sempre num modal que
    # fechou direito.
    pg.wait_for_selector("#cm-lista", state="hidden", timeout=20000)
    pg.wait_for_timeout(300)


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
    # nada escolhido: a barra diz "todas", que é o estado inicial e o mais comum
    assert "Todas as mercadorias" in pg.inner_text("#cliop-merc-chips")
    pg.click("#cliop-merc-chips .chip")
    pg.wait_for_selector("#cm-lista label", state="visible", timeout=20000)
    txt = pg.inner_text("#cm-lista")
    assert "CHASSI" in txt and "RODAS" in txt
    assert "1.551" in txt, "o volume de cada mercadoria sumiu da lista"


def test_o_seletor_FICA_para_quem_e_do_cliente(pagina):
    """São duas perguntas, e só a primeira é escopo.

    Quem é do cliente não escolhe DE QUEM é a operação — o vínculo decide, e o
    seletor de cliente some. Mas escolhe O QUE dela está olhando. Esconder a
    barra inteira quando `travado` (que é o que a tela fazia) tiraria o filtro
    justamente de quem tem mais motivo para usá-lo.
    """
    pg, base = pagina
    _abrir(pg, base)
    assert pg.is_visible("#cliop-merc-chips"), "o filtro sumiu para o cliente"
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
    _escolher(pg, ["RODAS"])
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
    _escolher(pg, ["RODAS"])
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
    _escolher(pg, ["RODAS"])
    pg.wait_for_timeout(200)
    pg.evaluate("CLIOP_RAIZ = ''; cliopTrocarCliente()")
    assert "Todas as mercadorias" in pg.inner_text("#cliop-merc-chips")
    assert pg.evaluate("CLIOP_MERC.size") == 0


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


# ════════════ o detalhe que permite VALIDAR a cláusula (11/09/2026) ═════════
#
# Quem opera pediu: "precisamos de mais detalhes para validar". Ler "RODAS
# 6,5h" não valida nada — valida quem vê desde quando vale, quanto custa a
# hora excedente, de qual filial é o cadastro e quem mexeu por último.

def test_a_clausula_diz_DESDE_QUANDO_vale(pagina):
    """Toda conferência de contrato começa por "desde quando".

    E "sem data de fim" não é "indefinido": é "sem término combinado", que é o
    normal destes contratos — dizer "indefinido" sugeriria um buraco no
    cadastro onde não há.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    txt = pg.inner_text("#cliop-ft-linhas")
    assert "01/08/2024" in txt, "a vigência não apareceu: %s" % txt
    assert "sem término combinado" in txt.lower(), txt


def test_a_clausula_QUE_VAI_ACABAR_aparece_antes_de_acabar(pagina):
    """Cláusula com data de fim precisa aparecer ANTES de vencer, não depois.

    É o defeito que a VOLVO tem no ERP hoje, do outro lado: uma cláusula que
    acabou em 31/08/2024 e continua marcada como ativa. A tela deixou de
    aplicá-la; aqui ela garante que uma cláusula COM prazo é visível enquanto
    ainda vale, para alguém renovar a tempo.
    """
    pg, base = pagina
    com_fim = {**PERM, "freetime": {**PERM["freetime"], "linhas": [
        _cl("RODAS", 3.0, 6.5, vig_ate="2026-12-31")]}}
    _abrir_com(pg, base, com_fim)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    assert "31/12/2026" in pg.inner_text("#cliop-ft-linhas")


def test_o_PRECO_da_hora_excedente_aparece(pagina):
    """A tabela sem o preço mostra a régua e esconde o que ela cobra.

    E com os CENTAVOS: a taxa da Maxion é R$ 102,04/h, e o formatador padrão
    da casa arredonda para R$ 102 — some justamente o centavo que multiplica
    milhares de horas.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    rod = pg.inner_text("#cliop-ftlinhas-hint")
    assert "102,04" in rod, "o preço sumiu ou perdeu os centavos: %s" % rod


def test_o_PRECO_vira_COLUNA_quando_varia_entre_as_clausulas(pagina):
    """Coluna constante sai da tabela e vira referência no rodapé — regra da
    casa. Mas "constante hoje" não é "constante": nos 16 contratos vigentes o
    preço é único por cliente, e no dia em que duas cláusulas cobrarem
    diferente a coluna tem de VOLTAR, em vez de a tela escolher uma das duas
    para o rodapé e esconder a outra.
    """
    pg, base = pagina
    varia = {**PERM, "freetime": {**PERM["freetime"], "linhas": [
        _cl("RODAS", 3.0, 6.5, rh_entrega=102.04),
        _cl("ESCADAS", 3.0, 6.5, rh_entrega=150.00)]}}
    _abrir_com(pg, base, varia)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    assert pg.is_visible("#cliop-ft-th-rh"), (
        "os preços divergem e a coluna não apareceu — o rodapé mostraria um só")
    txt = pg.inner_text("#cliop-ft-linhas")
    assert "102,04" in txt and "150,00" in txt, txt
    assert "hora excedente a" not in pg.inner_text("#cliop-ftlinhas-hint"), (
        "o rodapé afirmou um preço único com dois preços na tabela")


def test_o_cadastro_QUE_SE_CONTRADIZ_leva_marca(pagina):
    """O ERP tem DUAS fontes para "esta cláusula é genérica" — a observação
    vazia e o `distingueoperacao`. Elas concordam em 24 de 24 linhas hoje.

    Divergir é cadastro furado, e a tela DIZ em vez de escolher em silêncio
    qual das duas tem razão: escolher calado é como um total inflado por join
    passa meses sem ninguém notar.
    """
    pg, base = pagina
    furado = {**PERM, "freetime": {**PERM["freetime"], "linhas": [
        _cl("RODAS", 3.0, 6.5, distingue=2, confere=False)]}}
    _abrir_com(pg, base, furado)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    assert "conferir" in pg.inner_text("#cliop-ft-linhas").lower(), (
        "o cadastro contraditório passou sem marca")


def test_a_clausula_diz_QUEM_mexeu_por_ultimo(pagina):
    """É com quem se fala quando o número surpreende."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    txt = pg.inner_text("#cliop-ft-linhas")
    assert "PRISCILLA" in txt.upper(), txt
    assert "25/09/2025" in txt, txt


# ═══════════ escolher VÁRIAS mercadorias, e a parede herdar (11/09/2026) ════

def test_da_para_escolher_MAIS_DE_UMA(pagina):
    """O pedido de quem opera: "preciso conseguir selecionar mais de uma".

    Duas cargas diferentes com perguntas parecidas — "como está a minha
    espuma e a minha embalagem de espuma" — eram duas leituras separadas, e
    nenhuma delas era a soma.
    """
    pg, base = pagina
    pedidos, _ = _abrir(pg, base)
    _escolher(pg, ["RODAS", "CHASSI"])
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(pedidos[-1]).query)
    assert sorted(q.get("merc", [])) == ["CHASSI", "RODAS"], pedidos[-1]


def test_cada_mercadoria_vira_uma_CHAVE_e_nao_uma_lista_com_virgula(pagina):
    """`?merc=A&merc=B`, e não `?merc=A,B`.

    O cadastro de mercadoria do ERP é texto livre: uma vírgula no nome
    quebraria a separação em silêncio, e o filtro passaria a pedir duas
    mercadorias que não existem.
    """
    pg, base = pagina
    pedidos, _ = _abrir(pg, base)
    _escolher(pg, ["RODAS", "CHASSI"])
    assert "merc=RODAS&merc=CHASSI" in pedidos[-1] \
        or "merc=CHASSI&merc=RODAS" in pedidos[-1], pedidos[-1]
    assert "%2C" not in pedidos[-1], "as mercadorias foram juntadas por vírgula"


def test_o_chip_TIRA_a_mercadoria_do_filtro(pagina):
    """Tirar uma da lista é o ajuste mais frequente — obrigar a reabrir o
    modal para isso é atrito em cima do caminho curto."""
    pg, base = pagina
    pedidos, _ = _abrir(pg, base)
    _escolher(pg, ["RODAS", "CHASSI"])
    pg.click("#cliop-merc-chips .chip.active")
    pg.wait_for_timeout(400)
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(pedidos[-1]).query)
    assert len(q.get("merc", [])) == 1, pedidos[-1]


def test_CANCELAR_o_modal_nao_mexe_no_filtro(pagina):
    """O modal trabalha numa CÓPIA.

    Mexendo no conjunto direto, "Cancelar" deixaria a escolha pela metade: os
    chips já teriam mudado e os números não, e a barra passaria a descrever um
    recorte que a tela não tem.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#cliop-merc-chips .chip")
    pg.wait_for_selector("#cm-lista label", state="visible", timeout=20000)
    pg.check("#cm-lista input[value=\"RODAS\"]")
    pg.click("button.ghost:has-text('Cancelar')")
    pg.wait_for_timeout(300)
    assert pg.evaluate("CLIOP_MERC.size") == 0, "Cancelar aplicou a escolha"
    assert "Todas as mercadorias" in pg.inner_text("#cliop-merc-chips")


def test_a_escolha_SOBREVIVE_ao_recarregar(pagina):
    """Ela fica lembrada no navegador — e é essa mesma memória que a parede lê.

    Sem isso, quem prepara o mural escolheria as mercadorias e perderia a
    escolha no primeiro F5.
    """
    pg, base = pagina
    _abrir(pg, base)
    _escolher(pg, ["RODAS"])
    pg.reload()
    pg.wait_for_selector("#cliop-agora tr", state="attached", timeout=20000)
    pg.wait_for_timeout(400)
    assert pg.evaluate("[...CLIOP_MERC]") == ["RODAS"]
    assert "RODAS" in pg.inner_text("#cliop-merc-chips")


def test_a_mercadoria_que_o_cliente_NAO_TEM_sai_da_escolha(pagina):
    """"ASSENTOS" é da LEAR e não existe na Maxion.

    Uma escolha que sobrevivesse à troca faria a tela nascer vazia com o filtro
    apontando para algo que aquela operação não tem — e tela vazia se lê como
    cliente sem carga, não como filtro errado.
    """
    pg, base = pagina
    _abrir(pg, base)
    pg.evaluate("CLIOP_MERC = new Set(['ASSENTOS']); cliopMercGravar();")
    pg.reload()
    pg.wait_for_selector("#cliop-agora tr", state="attached", timeout=20000)
    pg.wait_for_timeout(400)
    assert pg.evaluate("CLIOP_MERC.size") == 0, (
        "o filtro ficou apontando para mercadoria que este cliente não tem")


# ═════════════ a régua, com payload CHEIO (a do script mede o esqueleto) ════

def test_as_abas_NOVAS_cabem_na_tela_com_dado_de_verdade(pagina):
    """`scripts/medir_paineis.py` dubla a API com `{}` e mede o ESQUELETO.

    Tabela vazia, aviso mudo: aba que só enche com dado passa lá e estoura na
    tela de quem usa. A aba Decidir do fluxcon passava com 854px e ia a
    1.303px com os doze meses reais; a aba "O dia" da frequência deu 381px na
    régua e 1.060px com o payload real (outra sessão, 11/09/2026). Por isso a
    regra da casa manda medir aba NOVA no e2e, com dado.

    As duas que esta entrega criou são a Permanência (que ganhou um segundo
    card) e a Freetime contratado. O payload aqui é o da IOCHPE MAXION lido do
    ERP: 4 cláusulas de contrato com vigência, preço, filial e autoria.

    O QUE ESTE GUARD NÃO AFIRMA: que as OUTRAS abas da tela cabem. Medido em
    11/09/2026, Agora dá 1.156px e Histórico 1.096px com dado real — as duas
    acima do limite, as duas ASSIM DESDE ANTES desta entrega (conferido
    medindo o mesmo payload contra o index.html de c9a9255). São dívida
    anterior, e entram aqui como registro para quem for mexer nelas, não como
    verde emprestado.
    """
    pg, base = pagina
    _abrir(pg, base)
    alt = ("() => { const c = document.getElementById('content');"
           " const b = c.querySelector('#banner');"
           " const fora = (b && b.offsetParent !== null)"
           "   ? Math.round(b.getBoundingClientRect().height) + 14 : 0;"
           " return Math.round(c.scrollHeight) - fora; }")
    larg = ("() => Math.max(0, document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth)")
    pg.set_viewport_size({"width": 1500, "height": 1000})
    for aba, rot in (("perm", "Permanência"), ("ft", "Freetime contratado")):
        pg.evaluate("(q) => abaTrocar('cliop', q)", aba)
        pg.wait_for_timeout(600)
        a, w = pg.evaluate(alt), pg.evaluate(larg)
        assert a <= 900, "a aba %s foi a %d px com dado real (limite 900)" % (rot, a)
        assert w == 0, "a aba %s empurrou a página %d px para o lado" % (rot, w)


def test_a_lista_de_mercadorias_rola_DENTRO_do_seletor(pagina):
    """Com MUITAS mercadorias — que é quando o mecanismo importa.

    A Maxion tem doze tipos e eles cabem folgados: com esse payload, tirar o
    `max-height` do `.pk-lista` não mudava um pixel e este guard aprovava a
    remoção. Payload que não exercita o limite não prova limite nenhum.

    O dublê sai do TETO DO CADASTRO, e não do maior caso de hoje: 91 tipos
    distintos de mercadoria no ERP em 365 dias (o maior cliente de hoje, a
    TUPY, tem 29). Um cliente novo, no pior caso, não passa dos 91 — e é
    contra o pior caso que o mecanismo precisa segurar.

    Se a lista crescesse a página, o modal viraria uma tela de rolagem e o
    botão Aplicar sairia de vista.
    """
    pg, base = pagina
    muitas = {**AGORA, "mercadorias": [
        {"chave": "MERCADORIA DE TESTE %02d" % i,
         "rotulo": "MERCADORIA DE TESTE %02d" % i, "cargas": 500 - i}
        for i in range(91)]}
    _abrir_com(pg, base, PERM, agora=muitas)
    pg.click("#cliop-merc-chips .chip")
    pg.wait_for_selector("#cm-lista label", state="visible", timeout=20000)
    caixa = pg.eval_on_selector(
        "#cm-lista", "e => [Math.round(e.getBoundingClientRect().height),"
        " e.scrollHeight > e.clientHeight + 4]")
    assert caixa[1], (
        "com 40 mercadorias a lista NÃO rola por dentro — ela cresceu a página")
    assert caixa[0] <= 360, "a lista do seletor tem %d px de altura" % caixa[0]
    assert pg.is_visible("button.btn:has-text('Aplicar')"), (
        "o botão Aplicar saiu de vista")


def test_a_tabela_do_contrato_rola_DENTRO_do_card(pagina):
    """Os contratos de hoje têm no máximo 4 cláusulas, e 4 cabem sem
    mecanismo nenhum — foi assim que a sabotagem que tirava o `.tabroll`
    passou verde aqui.

    Um contrato pode crescer: a tabela do ERP tem 24 linhas vigentes hoje e
    nada impede um cliente de ter vinte. Com vinte, sem `.tabroll`, a aba
    passa do limite da tela. O payload deste guard tem vinte.
    """
    pg, base = pagina
    muitas = {**PERM, "freetime": {**PERM["freetime"], "linhas": [
        _cl("MERCADORIA %02d" % i, 3.0, 6.5) for i in range(20)]}}
    _abrir_com(pg, base, muitas)
    pg.click("#tabcliop-ft")
    pg.wait_for_selector("#cliop-ft-linhas tr", state="visible", timeout=20000)
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.wait_for_timeout(400)
    # AS VINTE CHEGARAM? Sem esta linha o teste passa por VACUIDADE: se a
    # tabela renderizasse duas linhas, a aba caberia em qualquer régua e o
    # verde não diria nada sobre rolagem. Hoje quem pega isso é um teste
    # VIZINHO deste arquivo — e guard que depende do vizinho morre no dia em
    # que alguém mexer no vizinho.
    linhas = pg.eval_on_selector_all("#cliop-ft-linhas tr", "e => e.length")
    assert linhas == 20, "chegaram %d cláusulas na tela, não 20" % linhas
    rola = pg.eval_on_selector(
        "#cliop-ft-linhas", "e => { const w = e.closest('.tablewrap');"
        " return [w ? w.className : '', w ? (w.scrollHeight > w.clientHeight + 4) : false]; }")
    assert "tabroll" in rola[0], (
        "a tabela do contrato perdeu o .tabroll: %r" % rola[0])
    assert rola[1], (
        "com 20 cláusulas a tabela NÃO rola por dentro — ou o conteúdo não "
        "chegou, ou a rolagem saiu")
    alt = pg.evaluate(
        "() => { const c = document.getElementById('content');"
        " const b = c.querySelector('#banner');"
        " const fora = (b && b.offsetParent !== null)"
        "   ? Math.round(b.getBoundingClientRect().height) + 14 : 0;"
        " return Math.round(c.scrollHeight) - fora; }")
    assert alt <= 900, (
        "com 20 cláusulas a aba foi a %d px — a tabela não está rolando por "
        "dentro do card" % alt)
