# -*- coding: utf-8 -*-
"""As cinco telas novas — o escopo, e as regras que cada uma podia perder.

O QUE ESTE ARQUIVO GUARDA não é "a tela abre". É o conjunto de decisões que
custaram medição e que somem em silêncio quando alguém "simplifica":

- o escopo vem da SESSÃO, e não há parâmetro que a rota possa preencher;
- ponto de CNH só conta na penalidade, nunca na notificação;
- o conselho da Gobrax sai do QUARTO PIOR da frota, não da mediana;
- direção noturna não entra na conta de violação;
- e nenhuma delas devolve dinheiro da empresa.

Cada guard aqui foi conferido por sabotagem: mexer no alvo deixa vermelho.
"""
from __future__ import annotations

import inspect

import pytest

from api import queries
from api.gobrax import performance as pf
from api.motorista import (desempenho as mdesemp, jornada as mjor,
                           multas as mmultas, ocorrencias as mocor,
                           produtividade as mprod)


@pytest.fixture(autouse=True)
def cache_limpo():
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


class _PgFalso:
    """Um `pglocal` de mentira, POR MÓDULO.

    ISTO FOI UM DEFEITO DE VERDADE E VALE ESCRITO: a primeira versão destes
    testes fazia `monkeypatch.setattr(mmultas.pglocal, "query", ...)` — e
    `mmultas.pglocal` É o módulo `api.pglocal`, então o patch valia para a
    casa inteira. Quem quebrou foi o guard `producao_intocada` do
    `tests/conftest.py`, que conta linhas de produção com a mesma função e
    passou a receber a lista do dublê: sete testes acusaram "ESCREVEU em
    produção" sem ter escrito nada.

    Trocar o ATRIBUTO do módulo (`mmultas.pglocal`) em vez de mexer dentro do
    módulo compartilhado mantém o dublê onde ele pertence.
    """

    def __init__(self, linhas):
        self._linhas = linhas

    def query(self, *a, **k):
        return list(self._linhas)

    def um(self, *a, **k):
        return self._linhas[0] if self._linhas else None


# ============================================== o escopo vem da sessão =====

#: Cada função de leitura das telas novas, com o nome do parâmetro que ela
#: PODE ter além da sessão. Nenhuma delas aceita motorista.
LEITURAS = [(mmultas.minhas, "multas"), (mocor.minhas, "ocorrencias"),
            (mprod.minha, "produtividade"), (mjor.minha, "jornada"),
            (mdesemp.meu, "desempenho")]


@pytest.mark.parametrize("fn,nome", LEITURAS, ids=[n for _, n in LEITURAS])
def test_nenhuma_leitura_aceita_motorista_por_parametro(fn, nome):
    """Um argumento que a rota pudesse preencher com o que veio do navegador
    seria a diferença entre um app e um buscador da operação alheia.

    EM GUARD PARAMETRIZADO CADA PARÂMETRO É UM GUARD: sabotar um prova o
    mecanismo, não que os outros nomeiem alvo real. Por isso o teste seguinte
    confere que cada função existe e é chamável.
    """
    par = list(inspect.signature(fn).parameters)
    assert par[0] == "sessao", f"{nome}: o primeiro parâmetro tem de ser a sessão"
    assert set(par) <= {"sessao", "esquema"}, (
        f"{nome}: parâmetro a mais é por onde o escopo deixa de vir da sessão")


def test_as_cinco_leituras_existem_de_verdade():
    """O espelho do guard acima: lista de nomes leva um guard que prova que
    cada item aponta para alvo real. Uma varredura sobre função inexistente
    passaria por vacuidade — foi assim que a varredura de agendadores da casa
    ficou verde nomeando uma thread que não existia."""
    for fn, nome in LEITURAS:
        assert callable(fn), nome
        assert fn.__module__.startswith("api.motorista."), nome


# ===================================================== nada de dinheiro ====

#: O que não pode estar em consulta nenhuma das telas novas. Cada uma existe na
#: consulta de ALGUMA tela da casa que lê as mesmas tabelas — é de lá que elas
#: viriam num "reaproveitamento".
PROIBIDAS = ("valorfrete", "valorfretecompra", "valoradiantamento",
             "valorpedagiocompra", "custo", "margem")

CONSULTAS = {
    "produtividade._SQL": mprod._SQL,
    "produtividade._DESTINOS_SQL": mprod._DESTINOS_SQL,
    "ocorrencias._SQL": mocor._SQL,
    "multas._SQL": mmultas._SQL,
}


@pytest.mark.parametrize("nome", sorted(CONSULTAS))
def test_a_consulta_nao_tem_dinheiro_da_empresa(nome):
    sql = CONSULTAS[nome].lower()
    for proibida in PROIBIDAS:
        assert proibida not in sql, (
            f"`{proibida}` entrou em {nome} — o leitor vê a operação dele, "
            "não o resultado dela")


def test_a_excecao_do_valor_da_multa_e_deliberada():
    """`valor_a_pagar` ESTÁ na consulta de multas, e isso não é descuido: não é
    dinheiro da empresa, é o número do auto e do boleto dele. Decidido por quem
    opera em 07/09/2026 — este teste existe para a decisão não ser desfeita por
    engano por quem ler a regra geral."""
    assert "valor_a_pagar" in mmultas._SQL
    assert "valor de multa não é nenhum deles" in mmultas.__doc__.lower()


def test_o_km_da_produtividade_e_o_da_viagem_e_ele_e_dito(monkeypatch):
    """`kmfretecompra` é km CONTRATADO, não hodômetro (cobertura medida: 100%
    das viagens dos vinculados). Prometer hodômetro entregando contrato é o
    tipo de coisa que o motorista descobre antes de nós — e por isso a
    PROCEDÊNCIA vai no payload, não escrita na página: texto na página diverge
    do que o servidor faz no dia em que alguém mexer só num dos lados."""
    assert "kmfretecompra" in mprod._SQL
    monkeypatch.setattr(mprod, "_consultar",
                        lambda cod: {"linhas": {}, "destinos": []})
    d = mprod.minha({"motorista_codigo": "MOT-1"})
    assert "km contratado da viagem" in d["fonte"]


# ========================================================== as multas ======

def _linha_multa(**kw):
    """Dublê com o FORMATO da linha do banco, não derivado do código que a lê.

    Entrada de teste que representa formato externo é literal copiado do real —
    um dublê montado a partir da própria constante testada sabota junto com ela
    e segue verde.
    """
    base = {"identificador": "a3776f42-94d4-11f1-8b3c-4201ac115002",
            "especie": "multa", "placa": "TBA3C65",
            "data_infracao": None, "hora": "10:09:00",
            "descricao": "Velocidade - ate 20%", "codigo_infracao": "74550",
            "municipio": "ARUJA", "uf": "SP",
            "local_infracao": "SP 031 KM 037 METROS 000",
            "valor_a_pagar": 195.23, "valor_com_desconto": None,
            "pontuacao": 4, "vencimento": None, "prazo_indicacao": None,
            "em_aberto": True, "rota": "SAO PAULO/SP → ITU/SP",
            "candidatas": 1}
    base.update(kw)
    return base


def test_ponto_de_notificacao_nao_entra_na_conta(monkeypatch):
    """Medido no primeiro motorista real: 47 pontos, dos quais 12 vinham de
    NOTIFICAÇÕES em aberto — a autuação, estágio em que ainda cabe defesa e
    indicação. Contar as duas é a mesma armadilha de somar as espécies: conta o
    mesmo auto duas vezes, num campo que assusta."""
    linhas = [_linha_multa(especie="multa", pontuacao=4),
              _linha_multa(especie="notificacao", pontuacao=7,
                           identificador="outro")]
    monkeypatch.setattr(mmultas, "pglocal", _PgFalso(linhas))
    r = mmultas.minhas({"motorista_codigo": "MOT-1"})
    assert r["resumo"]["pontos"] == 4
    assert r["resumo"]["multas_abertas"] == 1
    assert r["resumo"]["notificacoes_abertas"] == 1
    # E a ressalva viaja junto: ponto só migra para uma CNH depois da
    # indicação de condutor, que é processo do órgão e não dedução nossa.
    assert "indicação de condutor" in r["pontos_ressalva"]


def test_o_valor_em_aberto_tambem_ignora_a_notificacao(monkeypatch):
    linhas = [_linha_multa(valor_a_pagar=100.0),
              _linha_multa(especie="notificacao", valor_a_pagar=900.0,
                           identificador="outro")]
    monkeypatch.setattr(mmultas, "pglocal", _PgFalso(linhas))
    r = mmultas.minhas({"motorista_codigo": "MOT-1"})
    assert r["resumo"]["valor_aberto"] == 100.0


def test_toda_multa_sai_marcada_como_hipotese(monkeypatch):
    """Não há caminho aqui que devolva `hipotese: false`. "A viagem estava com o
    Fulano" não é "o Fulano cometeu a infração" — e o leitor é a pessoa
    acusada."""
    monkeypatch.setattr(mmultas, "pglocal", _PgFalso([_linha_multa()]))
    r = mmultas.minhas({"motorista_codigo": "MOT-1"})
    assert all(i["hipotese"] for i in r["itens"])
    assert "indicação de condutor" in r["atribuicao"].lower()


def test_municipio_nao_informado_nao_vira_nome_de_cidade(monkeypatch):
    """O órgão manda o literal "NAO INFORMADO" no município, com a UF cheia.
    Mostrá-lo como se fosse o nome de uma cidade é o mesmo defeito de "código
    sem domínio virando rótulo": o campo tem valor, e o valor não é
    informação."""
    monkeypatch.setattr(mmultas, "pglocal",
                        _PgFalso([_linha_multa(municipio="NAO INFORMADO")]))
    r = mmultas.minhas({"motorista_codigo": "MOT-1"})
    assert r["itens"][0]["onde"] == "SP"


def test_o_codigo_do_orgao_sem_dominio_nao_vai_para_a_tela(monkeypatch):
    """`desdobramento` é um código do órgão ("2") sem tabela de domínio nossa.
    Ele não chega ao payload — código sem domínio não vira rótulo inventado nem
    número solto na tela de quem não tem como decifrá-lo.

    O guard é sobre o PAYLOAD e não sobre o texto da consulta: o dublê traz o
    campo (é assim que a linha do banco vem), então um `item["desdobramento"]`
    que voltasse a ser montado deixaria isto vermelho.
    """
    monkeypatch.setattr(mmultas, "pglocal",
                        _PgFalso([_linha_multa(desdobramento="2")]))
    r = mmultas.minhas({"motorista_codigo": "MOT-1"})
    assert "desdobramento" not in r["itens"][0]


# ======================================================= o desempenho ======

def _indicador(pct, h=100.0):
    return {"pct": pct, "h": h, "nota": 0.0}


def _monta_frota(monkeypatch, meu_pct, p25, mediana, p75, chave="idle",
                 menor_melhor=True):
    linha = {"placa": "ABC1D23 - T3000",
             "motoristas": [{"nome": "3190 - FULANO DE TAL"}],
             chave: _indicador(meu_pct)}
    monkeypatch.setattr(pf, "ler", lambda comp, path=None: [linha])
    monkeypatch.setattr(pf, "resumo_frota", lambda comp, path=None: {
        "competencia": comp, "veiculos": 46,
        "indicadores": [{"chave": chave, "rotulo": pf.INDICADORES[chave],
                         "menor_melhor": menor_melhor, "min": 0.0, "p25": p25,
                         "mediana": mediana, "p75": p75, "max": 99.0,
                         "veiculos": 46, "nota_zerada": False}]})
    monkeypatch.setattr(mdesemp.psnap, "ler_snapshot", lambda mes, d=None: None)
    monkeypatch.setattr(mdesemp.psnap, "ler_index", lambda d=None: [])


def test_o_conselho_sai_do_QUARTO_PIOR_e_nao_da_mediana(monkeypatch):
    """Pela mediana, METADE da frota é cobrada em cada indicador por
    construção — com catorze indicadores, todo mundo recebe três conselhos todo
    mês e a tela vira ruído que se aprende a fechar.

    Aqui ele está pior que a mediana (14 > 12) e MELHOR que o p75 (14 < 21):
    não é o quarto pior, então não vira conselho.
    """
    _monta_frota(monkeypatch, meu_pct=14.0, p25=6.0, mediana=12.0, p75=21.0)
    d = mdesemp.meu({"nome": "FULANO DE TAL", "motorista_codigo": "MOT-1"})
    assert d["tem_dado"]
    ind = [i for i in d["indicadores"] if i["chave"] == "idle"][0]
    assert ind["pior_que_a_frota"] is True     # está acima da mediana
    assert ind["no_quarto_pior"] is False      # mas não no quarto pior
    assert d["melhorar"] == []
    assert "quarto pior" in d["melhorar_criterio"]


def test_no_quarto_pior_o_conselho_aparece_com_o_texto(monkeypatch):
    """A outra ponta: sem ela, um `melhorar = []` fixo passaria no teste acima
    e o app nunca aconselharia ninguém."""
    _monta_frota(monkeypatch, meu_pct=35.0, p25=6.0, mediana=12.0, p75=21.0)
    d = mdesemp.meu({"nome": "FULANO DE TAL", "motorista_codigo": "MOT-1"})
    assert [i["chave"] for i in d["melhorar"]] == ["idle"]
    conselho = d["melhorar"][0]
    assert conselho["como"] and conselho["o_que"]
    assert conselho["como"] == mdesemp.COMO_MELHORAR["idle"]["como"]


def test_a_folga_impede_cobranca_de_ruido(monkeypatch):
    """Décimo de ponto percentual contra a frota é ruído de mês, não conduta —
    e um app que cobra ruído é um app que se desliga."""
    _monta_frota(monkeypatch, meu_pct=12.2, p25=6.0, mediana=12.0, p75=12.1)
    d = mdesemp.meu({"nome": "FULANO DE TAL", "motorista_codigo": "MOT-1"})
    assert d["melhorar"] == []


def test_todo_acionavel_tem_texto_escrito():
    """Lista de chaves leva um guard que prova que cada item existe na fonte:
    uma chave em `ACIONAVEIS` sem entrada em `COMO_MELHORAR` viraria um cartão
    de conselho VAZIO na tela de alguém."""
    for chave in mdesemp.ACIONAVEIS:
        assert chave in pf.INDICADORES, f"{chave} não é indicador da Gobrax"
        texto = mdesemp.COMO_MELHORAR.get(chave)
        assert texto and texto.get("como") and texto.get("o_que"), chave


def test_indicador_do_veiculo_e_dito_como_do_veiculo(monkeypatch):
    """Não existe indicador por motorista na API — foi medido, não suposto. A
    ressalva viaja no payload; sem ela a tela diria "seu motor ficou 15%
    ligado parado", que é uma frase falsa."""
    _monta_frota(monkeypatch, meu_pct=35.0, p25=6.0, mediana=12.0, p75=21.0)
    d = mdesemp.meu({"nome": "FULANO DE TAL", "motorista_codigo": "MOT-1"})
    assert "VEÍCULO" in d["ressalva"]
    assert "veiculo_compartilhado" in d


def test_nome_ambiguo_nao_casa_com_ninguem(monkeypatch):
    """Medido: zero nomes repetidos hoje entre os 592 motoristas do ERP. No dia
    em que houver dois, mostrar o desempenho do colega é pior que dizer "não te
    encontrei"."""
    monkeypatch.setattr(mdesemp.psnap, "ler_snapshot", lambda mes, d=None: {
        "month": mes, "parcial": False,
        "drivers": [{"driverName": "1 - FULANO DE TAL", "km": 900, "nota": 80},
                    {"driverName": "2 - FULANO DE TAL", "km": 800, "nota": 60}]})
    assert mdesemp._minha_nota("FULANO DE TAL", "2026-08") is None


def test_o_prefixo_de_matricula_da_gobrax_nao_atrapalha():
    """A Gobrax escreve "3781 - ROBSON …" e o ERP escreve só o nome. A
    normalização é a mesma da coleta da premiação, que é a que já casa os dois
    lados."""
    assert mdesemp._norm("3781 - Robson  da Silva") == "ROBSON DA SILVA"
    assert mdesemp._norm("ROBSON DA SILVA") == "ROBSON DA SILVA"


# ========================================================== a jornada ======

def test_direcao_noturna_nao_entra_na_conta_de_violacao():
    """35% dos eventos, e não é violação de nada: é trabalho noturno, legal e
    com adicional. Somá-la faria a contagem subir um terço por causa de um
    evento que ninguém precisa corrigir — e seria susto gratuito na tela de
    quem trabalha à noite por escala."""
    from api.jornada.leitura import _classe
    assert _classe("DIRECAO NOTURNA") == "fora"
    assert _classe("DIRECAO ININTERRUPTA") == "tempo"


def test_a_jornada_nao_promete_saldo_do_dia():
    """O rascunho do app pedia "quanto ainda posso dirigir?". A fonte é a
    apuração fechada por DIA: um app que somasse as horas de ontem para dizer
    "faltam 2h10" inventaria o saldo de hoje a partir de dado que não é de
    hoje, e o motorista pararia (ou não) com base nisso."""
    # O AVISO É DO PAYLOAD, não escrito na página: texto na página diverge do
    # que o servidor faz no dia em que alguém mexer só num dos dois lados.
    # A fonte é lida com as quebras de linha colapsadas: a frase do aviso está
    # partida em três literais no código, e procurá-la linha a linha só
    # encontraria pedaços.
    fonte = " ".join(w for w in inspect.getsource(mjor).replace('"', " ").split())
    assert "quem diz isso é o equipamento na cabine" in fonte
    assert "Ela não diz quanto você ainda pode dirigir agora" in fonte, (
        "o aviso saiu do payload — sem ele a tela vira um saldo de jornada "
        "inventado a partir de dado que não é de hoje")


def test_quem_nao_tem_jornada_nao_ve_tela_vazia(monkeypatch):
    """Dois terços dos motoristas são agregados e nunca terão linha aqui. Uma
    aba que abre e diz "sem dados" para quem nunca vai ter dado ensina a pessoa
    a não confiar no resto da tela."""
    monkeypatch.setattr(mjor, "pglocal", _PgFalso([{"ultima": None, "total": 0}]))
    d = mjor.minha({"motorista_codigo": "12345678901"})
    assert d["tem_dado"] is False and d["motivo"]
    assert "kpis" not in d


def test_o_documento_da_jornada_e_so_digito():
    """`jor_jornadas.documento` guarda só dígito; o ERP grava o código como
    veio. Medido: 78 dos 80 vinculados casam assim."""
    assert mjor._doc("123.456.789-01") == "12345678901"


# ====================================================== as ocorrências =====

def test_o_texto_livre_da_ocorrencia_nao_sai():
    """`observacao`, `reclamacao` e `acaoimediataconterproblema` são escritos
    por gente, sem revisão, para consumo interno — podem carregar nome de
    terceiro, opinião e a versão de um lado só de uma discussão."""
    sql = mocor._SQL.lower()
    for campo in ("observacao", "reclamacao", "acaoimediata"):
        assert campo not in sql, f"`{campo}` entrou na consulta de ocorrências"


def test_o_codigo_de_situacao_nao_vira_rotulo_inventado(monkeypatch):
    """Medido sobre 24 meses: situação 3 tem 92,8% com `dtsolucao` e situação 1
    tem 6,8%. A leitura óbvia é "3 = encerrada", e ela é uma INFERÊNCIA — não
    há tabela que diga isso. A tela diz "tratada em DD/MM", que é fato."""
    monkeypatch.setattr(mocor, "_consultar", lambda cod: {"linhas": [
        {"data": None, "solucao": None, "codigo": 2,
         "tipo": "MULTA DE TRANSITO (INFRACAO LEVE)", "veiculo": "TBA3C65",
         "situacao": 3}]})
    monkeypatch.setattr(mocor, "_meritos", lambda esq: set())
    d = mocor.minhas({"motorista_codigo": "MOT-1"})
    item = d["itens"][0]
    assert item["situacao_codigo"] == 3
    assert "encerrada" not in repr(item).lower()
    assert "situacao" not in {k for k in item if k != "situacao_codigo"}


def test_merito_so_quando_uma_PESSOA_classificou():
    """Medido em 07/09/2026: 40 dos 54 tipos ainda estão com a proposta
    automática. Um rascunho nosso que vira elogio na tela é tão errado quanto
    um que vira demérito — só é menos perigoso."""
    fonte = inspect.getsource(mocor._meritos)
    assert "atualizado_por LIKE" in fonte and "@" in fonte
    assert "classe = 'merito'" in fonte


# ===================================================== a produtividade =====

def test_a_comparacao_e_com_ele_mesmo(monkeypatch):
    """A referência óbvia seria a média da frota, e ela está proibida: o leitor
    não é gestor, é a pessoa medida. A régua são os 30 dias anteriores DELE."""
    monkeypatch.setattr(mprod, "_consultar", lambda cod: {
        "linhas": {"atual": {"viagens": 20, "km": 2000, "dias_com_viagem": 11},
                   "anterior": {"viagens": 25, "km": 1000,
                                "dias_com_viagem": 10}},
        "destinos": []})
    d = mprod.minha({"motorista_codigo": "MOT-1"})
    assert d["variacao"]["viagens"] == -20.0
    assert d["variacao"]["km"] == 100.0
    assert "frota" not in repr(d).lower()


def test_sem_periodo_anterior_a_variacao_e_None_e_nao_zero(monkeypatch):
    """Motorista que entrou agora não teve variação de 0% — ele não tem com o
    que comparar, e "0%" ali seria uma afirmação falsa com cara de medida."""
    monkeypatch.setattr(mprod, "_consultar", lambda cod: {
        "linhas": {"atual": {"viagens": 20, "km": 2000, "dias_com_viagem": 11}},
        "destinos": []})
    d = mprod.minha({"motorista_codigo": "MOT-1"})
    assert d["variacao"]["viagens"] is None and d["variacao"]["km"] is None


def test_o_topN_de_destinos_leva_contador(monkeypatch):
    """Cinco linhas somando 12 viagens em cima de um total de 30 lêem-se como o
    total. Top-N sem contador vira total falso."""
    monkeypatch.setattr(mprod, "_consultar", lambda cod: {
        "linhas": {"atual": {"viagens": 30, "km": 100, "dias_com_viagem": 5}},
        "destinos": [{"cidade": "ITU", "uf": "SP", "viagens": 7},
                     {"cidade": "JUNDIAI", "uf": "SP", "viagens": 5}]})
    d = mprod.minha({"motorista_codigo": "MOT-1"})
    assert d["destinos_viagens"] == 12 and d["atual"]["viagens"] == 30


def test_a_media_e_por_dia_COM_viagem(monkeypatch):
    """Dia de folga no denominador mede escala, não produtividade — a mesma
    escolha da jornada, onde 45% das linhas do relatório são dias zerados."""
    monkeypatch.setattr(mprod, "_consultar", lambda cod: {
        "linhas": {"atual": {"viagens": 10, "km": 1000, "dias_com_viagem": 5}},
        "destinos": []})
    d = mprod.minha({"motorista_codigo": "MOT-1"})
    assert d["atual"]["km_por_dia"] == 200


def test_o_ava_e_93_entao_nada_de_FILTER():
    """O AVA é PostgreSQL 9.3: `FILTER (WHERE …)` não existe lá e o erro aponta
    para o meio do agregado, não para a versão — meia hora de procura no lugar
    errado."""
    for nome, sql in (("produtividade", mprod._SQL),
                      ("destinos", mprod._DESTINOS_SQL),
                      ("ocorrências", mocor._SQL)):
        assert "filter (where" not in sql.lower(), nome


# ============================================ a rede da leitura velha =====
#
# ESTE BLOCO NASCEU DE DOIS DEFEITOS MEUS, e eles valem escritos porque a
# classe é a mais perigosa deste app — a proteção fica DESLIGADA e nada acusa:
#
# 1. `cached(velha_ate=)` CARIMBA o dicionário que ele guardou, e `minhas()` /
#    `minha()` montam OUTRO por cima. Sem repassar as três chaves, a rede
#    existe no servidor e a tarja NUNCA aparece na tela: número velho servido
#    CALADO, que é pior que tela vazia, porque ninguém desconfia dele.
# 2. `cached` só serve o velho quando o guardado é um `dict`
#    (`isinstance(hit[1], dict)`). `ocorrencias._consultar` devolvia uma LISTA
#    e a rede simplesmente não existia — no dia ruim do ERP a exceção subia e a
#    tela morria, sem nada dizer que a proteção nunca esteve ligada.

def _uma_vez_e_quebra(bom):
    """Responde a primeira e falha dali em diante — é o dia ruim do ERP."""
    estado = {"n": 0}

    def fn(*a, **k):
        estado["n"] += 1
        if estado["n"] > 1:
            raise RuntimeError("ERP fora")
        return bom
    return fn


TELAS_COM_REDE = [
    ("ocorrencias", mocor, mocor.minhas, {"linhas": []}),
    ("produtividade", mprod, mprod.minha, {"linhas": {}, "destinos": []}),
]


@pytest.mark.parametrize("nome,mod,chamar,bom", TELAS_COM_REDE,
                         ids=[t[0] for t in TELAS_COM_REDE])
def test_a_tarja_de_leitura_velha_ATRAVESSA_ate_o_payload(nome, mod, chamar,
                                                          bom, monkeypatch):
    """Quem carimba é o `cached`; quem TEM de repassar é a função da tela.

    O `JSONResponse` da casa lê `leitura_velha` do CORPO para escrever o
    cabeçalho `X-Leitura-Velha`, e é o cabeçalho que a página desenha. Perdida
    a chave aqui, a corrente inteira se desliga sem sintoma.
    """
    if nome == "ocorrencias":
        monkeypatch.setattr(mod, "_meritos", lambda esq: set())
    # `ttl=0` força a segunda chamada a consultar de novo; `velha_ate` alto
    # mantém a rede ligada. É o `cached` de verdade — um dublê dele testaria o
    # dublê.
    monkeypatch.setattr(mod, "_consultar",
                        queries.cached(ttl=0, velha_ate=3600)(_uma_vez_e_quebra(bom)))

    sessao = {"motorista_codigo": "MOT-1"}
    primeira = chamar(sessao)
    assert "leitura_velha" not in primeira, (
        "a leitura BOA saiu marcada de velha — tarja grudada some com a "
        "confiança na tela inteira")

    segunda = chamar(sessao)
    assert segunda.get("leitura_velha") is True, (
        "a rede existe no servidor e a tarja não chega à tela: número velho "
        "servido CALADO")
    assert segunda.get("leitura_idade_seg") is not None
    assert segunda.get("leitura_em")


@pytest.mark.parametrize("nome,mod,chamar,bom", TELAS_COM_REDE,
                         ids=[t[0] for t in TELAS_COM_REDE])
def test_a_consulta_com_rede_devolve_DICIONARIO(nome, mod, chamar, bom,
                                                monkeypatch):
    """O guard do segundo defeito. `cached` confere `isinstance(hit[1], dict)`
    antes de servir a leitura velha: uma consulta que devolvesse lista teria a
    rede desligada, e o teste acima passaria a falhar por um motivo que ninguém
    ligaria a este."""
    assert "isinstance(hit[1], dict)" in inspect.getsource(queries.cached), (
        "o `cached` mudou de regra — este guard e o de cima precisam ser "
        "relidos juntos")
    monkeypatch.setattr(mod, "db", type("X", (), {
        "query": staticmethod(lambda *a, **k: [])}))
    if nome == "ocorrencias":
        monkeypatch.setattr(mod, "_meritos", lambda esq: set())
    assert isinstance(mod._consultar("MOT-1"), dict)


def test_lista_vazia_por_AUSENCIA_nao_vira_elogio(monkeypatch):
    """Zero que é ausência não é desempenho — nem quando o zero é a lista de
    conselhos. "Nada a apontar" dito sobre uma competência sem medição nenhuma
    é um elogio sobre dado que não existe, e o motorista tomaria por
    confirmação de que está bem."""
    monkeypatch.setattr(pf, "ler", lambda comp, path=None: [])
    monkeypatch.setattr(pf, "resumo_frota", lambda comp, path=None: {
        "competencia": comp, "veiculos": 0, "indicadores": []})
    monkeypatch.setattr(mdesemp.psnap, "ler_index", lambda d=None: [])
    monkeypatch.setattr(mdesemp.psnap, "ler_snapshot", lambda mes, d=None: {
        "month": mes, "parcial": False,
        "drivers": [{"driverName": "FULANO DE TAL", "km": 900, "nota": 80}]})

    d = mdesemp.meu({"nome": "FULANO DE TAL", "motorista_codigo": "MOT-1"})
    assert d["tem_dado"] and d["indicadores"] == [] and d["melhorar"] == []
    assert "Nada a apontar" not in d["melhorar_vazio"], (
        "a tela elogiou sobre dado que não existe")
    assert "Não há indicadores" in d["melhorar_vazio"]


def test_a_janela_da_rede_e_a_MESMA_da_casa_em_todo_o_modulo():
    """`tests/test_leitura_velha.py` guarda isso para `api/queries.py`, e os
    módulos do app estão FORA do alcance dele — guard não mora
    necessariamente ao lado do código que ele guarda.

    Uma janela escrita à mão aqui seria uma decisão que ninguém tomou: a do
    `viagem.py` já foi 6 h antes da v0.258.0, escolhida sozinha, e uma viagem
    pode começar e terminar dentro de seis horas.
    """
    import pathlib
    import re
    raiz = pathlib.Path(mmultas.__file__).parent
    soltos = {}
    for arq in sorted(raiz.glob("*.py")):
        fonte = arq.read_text(encoding="utf-8")
        for valor in re.findall(r"velha_ate=(?!VELHA_ATE)([^,)]+)", fonte):
            soltos.setdefault(arq.name, []).append(valor.strip())
    assert not soltos, (
        "janela de leitura velha escrita à mão no app do motorista: %s — a "
        "janela da casa é `queries.VELHA_ATE`" % soltos)


def test_a_tela_que_le_SO_O_BANCO_DA_CASA_nao_tem_a_rede():
    """A rede existe porque o ERP é réplica de produção de TERCEIRO e tem dia
    ruim. `multas` lê só `smt_*`, que é banco NOSSO: falha ali é falha nossa, e
    servir leitura velha esconderia um defeito que temos de consertar em vez de
    contornar. O casamento com o AVA já aconteceu antes, na coleta."""
    import inspect as _i
    fonte = _i.getsource(mmultas)
    assert "cached" not in fonte, (
        "multas ganhou cache com rede — ela lê o banco da casa, e falha nossa "
        "não se disfarça de dia ruim de terceiro")
    assert "db.query" not in fonte and "from .. import db" not in fonte, (
        "multas passou a ler o ERP na abertura da tela; o casamento com o AVA "
        "acontece na COLETA (api/smartec/viagem.py), não no celular de ninguém")
