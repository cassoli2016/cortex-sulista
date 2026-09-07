# -*- coding: utf-8 -*-
"""O mural: um comunicado para todos, e o que impede ele de virar 300 conversas.

O canal (0063) recusa comunicado em massa por escrito, e a razão continua
valendo: 300 conversas de uma vez destroem os dois números que fazem a caixa
ser uma FILA — a ordem por mais parado e o "paradas há 3+ dias". Este módulo é
o OUTRO objeto que aquele comentário já nomeava: **um mural, sem fila e sem
resposta**.

O que este arquivo guarda é o que separa os dois. Cada peça abaixo parece
simplificável, e simplificar qualquer uma devolve o mural à forma que o canal
recusou:

- o público é FOTOGRAFADO na publicação (o denominador é um fato daquele dia);
- publicar é ATÔMICO (comunicado sem destinatário é comunicado para ninguém);
- "abriu" e "confirmou" são campos diferentes;
- encerrar PARA DE COBRAR sem apagar;
- e nada disto entra na fila do canal.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.motorista import conversas as mc
from api.motorista import mural as mu

from .conftest import cadastrar


@pytest.fixture
def publico(esq):
    """Três motoristas ativos e um desligado — o desligado é o ponto."""
    cadastrar(esq, "MOT-A", "5547999990001", "ANA MOTORISTA")
    cadastrar(esq, "MOT-B", "5547999990002", "BRUNO MOTORISTA")
    cadastrar(esq, "MOT-C", "5547999990003", "CARLA MOTORISTA")
    cadastrar(esq, "MOT-D", "5547999990004", "DAVI DESLIGADO", ativo=False)
    return esq


def _sessao(codigo="MOT-A", nome="ANA MOTORISTA"):
    return {"motorista_codigo": codigo, "nome": nome, "motorista_id": 1}


# ═══════════════════════════════════════════════ o público fotografado ═════

def test_publica_para_os_ATIVOS_e_so_para_eles(publico):
    """Desligado não recebe: ele não é mais público da empresa, e mantê-lo no
    denominador faria "3 de 4" ser uma cobrança que nunca fecha."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    assert r["destinatarios"] == 3

    quem = pglocal.query(
        "SELECT motorista_codigo FROM mot_comunicado_ciencia "
        "WHERE comunicado_id = %(id)s", {"id": r["id"]}, publico)
    assert {q["motorista_codigo"] for q in quem} == {"MOT-A", "MOT-B", "MOT-C"}


def test_quem_entra_DEPOIS_nao_deve_ciencia_do_que_e_anterior(publico):
    """A razão de fotografar em vez de calcular na leitura.

    Calculando "todos os ativos" na hora de ler, o contratado em novembro
    passaria a dever ciência de um comunicado de setembro — sobre uma convenção
    que não o alcança — e a fração mudaria de DENOMINADOR sozinha a cada
    admissão. Um número que anda para trás sem ninguém fazer nada é um número
    que ninguém acredita na segunda vez.
    """
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    assert mu.listar(publico)["comunicados"][0]["destinatarios"] == 3

    cadastrar(publico, "MOT-E", "5547999990005", "ELIAS NOVATO")
    assert mu.listar(publico)["comunicados"][0]["destinatarios"] == 3, (
        "o denominador andou sozinho com uma admissão")
    assert mu.meus(_sessao("MOT-E", "ELIAS"), publico)["comunicados"] == []


def test_publicar_e_ATOMICO(publico, monkeypatch):
    """Comunicado e lista de destinatários nascem na MESMA transação. Em duas,
    uma falha no meio deixaria um comunicado publicado para NINGUÉM — visível
    na tela do RH com "0 de 0" e invisível no app de todo mundo."""
    real = pglocal.get_conn

    class CxQuebrado:
        def __init__(self, cx): self._cx = cx
        def __enter__(self): return self
        def __exit__(self, *a): return self._cx.__exit__(*a)
        def cursor(self):
            cur = self._cx.__enter__().cursor() if False else None
            raise RuntimeError("banco caiu no meio")
        def commit(self): pass

    with pytest.raises(Exception):
        monkeypatch.setattr(pglocal, "get_conn",
                            lambda esq=None: CxQuebrado(real(esq)))
        mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    monkeypatch.setattr(pglocal, "get_conn", real)
    assert mu.listar(publico)["comunicados"] == [], (
        "sobrou um comunicado publicado para ninguém")


def test_titulo_e_texto_vazios_sao_recusados_com_MOTIVO(publico):
    for titulo, texto in (("", "x"), ("t", ""), ("  ", "x")):
        with pytest.raises(mu.Recusa):
            mu.publicar(titulo, texto, esquema=publico)
    with pytest.raises(mu.Recusa):
        mu.publicar("t", "x" * (mu.MAX_TEXTO + 1), esquema=publico)


# ═══════════════════════════════════════════ abriu × confirmou ═════════════

def test_ABRIU_e_CONFIRMOU_sao_campos_diferentes(publico):
    """"Viu e não confirmou" e "nunca abriu" são duas conversas diferentes com
    a pessoa. Um campo só as fundiria num "não leu" que não separa quem ignorou
    de quem nem soube."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    s = _sessao()

    mu.marcar_visto(s, r["id"], publico)
    c = mu.listar(publico)["comunicados"][0]
    assert c["confirmaram"] == 0 and c["viram_sem_confirmar"] == 1

    mu.dar_ciencia(s, r["id"], publico)
    c = mu.listar(publico)["comunicados"][0]
    assert c["confirmaram"] == 1 and c["viram_sem_confirmar"] == 0
    assert c["faltam"] == 2


def test_a_ciencia_e_IDEMPOTENTE_e_vale_o_PRIMEIRO_carimbo(publico):
    """Dois toques não viram duas ciências, e o instante que vale é o do
    primeiro — é ele que responde "quando ele leu?"."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    s = _sessao()
    assert mu.dar_ciencia(s, r["id"], publico)["ja_tinha"] is False
    quando = pglocal.um(
        "SELECT ciencia_em FROM mot_comunicado_ciencia "
        "WHERE comunicado_id=%(i)s AND motorista_codigo='MOT-A'",
        {"i": r["id"]}, publico)["ciencia_em"]

    assert mu.dar_ciencia(s, r["id"], publico)["ja_tinha"] is True
    de_novo = pglocal.um(
        "SELECT ciencia_em FROM mot_comunicado_ciencia "
        "WHERE comunicado_id=%(i)s AND motorista_codigo='MOT-A'",
        {"i": r["id"]}, publico)["ciencia_em"]
    assert de_novo == quando, "o segundo toque reescreveu a data da leitura"
    assert mu.listar(publico)["comunicados"][0]["confirmaram"] == 1


def test_quem_NAO_e_destinatario_nao_da_ciencia(publico):
    """O dono entra no WHERE junto do id — mesma regra de `conversas._minha`."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    cadastrar(publico, "MOT-Z", "5547999990009", "ZECA DEPOIS")
    for acao in (mu.dar_ciencia, mu.marcar_visto):
        with pytest.raises(mu.Recusa):
            acao(_sessao("MOT-Z", "ZECA"), r["id"], publico)


# ═══════════════════════════════════════════════════════════ encerrar ══════

def test_encerrar_TIRA_DO_APP_e_mantem_no_historico(publico):
    """Um comunicado de março que segue pedindo "li e entendi" para sempre
    ensina a pessoa a ignorar o pedido — inclusive no de hoje."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    s = _sessao()
    assert mu.meus(s, publico)["pendentes"] == 1

    mu.encerrar(r["id"], autor_nome="rh@x", esquema=publico)
    assert mu.meus(s, publico)["comunicados"] == []
    assert mu.listar(publico)["comunicados"][0]["encerrado"] is True
    with pytest.raises(mu.Recusa):
        mu.dar_ciencia(s, r["id"], publico)


def test_encerrar_duas_vezes_nao_reescreve_a_data(publico):
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    assert mu.encerrar(r["id"], esquema=publico)["encerrado"] is True
    assert mu.encerrar(r["id"], esquema=publico)["encerrado"] is False


# ═══════════════════════════════════════ o mural NÃO entra na fila ═════════

def test_publicar_NAO_cria_conversa_nenhuma(publico):
    """O guard central deste arquivo, e a razão de o mural existir.

    Se publicar abrisse conversas, a caixa do RH ganharia três linhas (trezentas
    em produção) e os dois números que fazem dela uma fila — a ordem por mais
    parado e o "paradas há 3+ dias" — morreriam no mesmo instante.
    """
    antes = mc.caixa(esquema=publico)["resumo"]["total"]
    mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    depois = mc.caixa(esquema=publico)
    assert depois["resumo"]["total"] == antes
    assert depois["conversas"] == []


def test_quem_quiser_FALAR_do_comunicado_abre_um_pedido(publico):
    """A outra ponta: o mural não tem resposta, e isso não deixa o motorista
    mudo — ele abre um pedido normal, que aí sim entra na fila com dono."""
    mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    c = mc.abrir(_sessao(), "outro", "Não entendi o comunicado da convenção.",
                 esquema=publico)
    assert mc.caixa(esquema=publico)["resumo"]["vivas"] == 1
    assert c["id"]


# ══════════════════════════════════════════════════ quem falta, e o PII ════

def test_faltam_lista_os_nomes_e_marca_quem_ABRIU(publico):
    """"45 de 80" sem os nomes não vira ação nenhuma. E quem ABRIU vem
    primeiro: essa pessoa viu e escolheu não confirmar."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    mu.marcar_visto(_sessao("MOT-B", "BRUNO"), r["id"], publico)

    f = mu.faltam(r["id"], publico)
    assert f["n"] == 3
    assert f["faltam"][0]["nome"] == "BRUNO MOTORISTA"
    assert f["faltam"][0]["abriu"] is True
    assert all(not x["abriu"] for x in f["faltam"][1:])


def test_o_codigo_do_ERP_nao_sai_em_lugar_nenhum(publico):
    """Ele é o CPF para pessoa física. Vale para as três saídas do módulo."""
    cadastrar(publico, "12345678901", "5547999990007", "COM CPF NO CODIGO")
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=publico)
    mu.dar_ciencia(_sessao(), r["id"], publico)
    for payload in (repr(mu.listar(publico)), repr(mu.faltam(r["id"], publico)),
                    repr(mu.meus(_sessao(), publico))):
        assert "12345678901" not in payload and "MOT-A" not in payload
        assert "motorista_codigo" not in payload


# ══════════════════════════════════════════════════════ o percentual ═══════

def test_sem_destinatario_o_percentual_e_None_e_nao_zero(esq):
    """Zero que é ausência não é desempenho. "0%" sobre nenhum destinatário
    seria uma medida sobre nada — e a tela mostraria um comunicado "com 0% de
    leitura" quando o que houve foi ninguém vinculado ao app."""
    r = mu.publicar("Convenção", "texto", autor_nome="rh@x", esquema=esq)
    assert r["destinatarios"] == 0
    c = mu.listar(esq)["comunicados"][0]
    assert c["destinatarios"] == 0 and c["pct"] is None


# ═════════════════════════════════════════════════════════ as rotas ════════

def test_as_rotas_do_mural_exigem_sessao():
    """Elas entram no guard geral (`test_rotas.py`); este confirma que estão
    lá — uma rota de mural em `SEM_SESSAO` deixaria qualquer um dar ciência
    no comunicado de outra pessoa."""
    from .test_rotas import rotas_do_app
    caminhos = {c for c, _ in rotas_do_app()}
    for esperada in ("/api/motorista/mural",
                     "/api/motorista/mural/{cid}/visto",
                     "/api/motorista/mural/{cid}/ciencia"):
        assert esperada in caminhos, esperada


def test_a_tela_do_RH_e_do_painel(esq):
    from api import auth
    assert not auth._rota_publica("/api/rh/motorista/mural")
    assert auth._telas_da_rota("/api/rh/motorista/mural") == frozenset({"rhmot"})


def test_a_recusa_do_mural_chega_LEGIVEL_pela_rota_do_painel():
    """`mural.Recusa` é outra classe que `conversas.Recusa`. Com só a do canal
    no `except` da rota, "Escreva um título." cairia no `except Exception` e
    chegaria ao RH como "Não consegui salvar agora" — uma recusa legível
    virando erro genérico, que é o oposto do que o `HTTP_RECUSA` existe para
    fazer."""
    import inspect

    from api import main
    fonte = inspect.getsource(main._rh_conversa_escrever)
    assert "mmural.Recusa" in fonte and "mconv.Recusa" in fonte
    fonte_app = inspect.getsource(main._mot_escrever)
    assert "mmural.Recusa" in fonte_app and "mconv.Recusa" in fonte_app
