# -*- coding: utf-8 -*-
"""O canal RH ↔ motorista — a fila, e o que impede ela de virar chat.

DOIS GRUPOS DE GUARD, e eles protegem coisas diferentes:

**Escopo.** Esta é a primeira coisa do app em que o navegador manda um
IDENTIFICADOR DE LINHA. Até aqui todo escopo saía da sessão e não havia o que
forjar. O `motorista_codigo` da sessão entra na cláusula `WHERE` junto do id —
nunca uma busca por id seguida de um `if` conferindo o dono, porque o `if` é a
linha que alguém apaga numa refatoração e o sintoma é ler a conversa de outra
pessoa.

**A forma da fila.** O escopo do app (`docs/APP_MOTORISTA.md` §10) excluía chat
com uma razão que continua boa: "um canal que ninguém lê e uma expectativa de
resposta que ninguém atende". O que responde a isso é o ASSUNTO de lista
fechada, o ESTADO, o DONO e a ordem por MAIS PARADO. Cada uma dessas peças tem
guard aqui, porque cada uma parece um detalhe que se pode simplificar — e
simplificar qualquer uma devolve o canal ao que o escopo previa.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import pglocal
from api.motorista import conversas as mc
from api.motorista import sessao as msessao

from .conftest import cadastrar


@pytest.fixture
def dois(esq):
    """Dois motoristas vinculados — o segundo existe para provar o escopo."""
    a = cadastrar(esq, "MOT-A", "5547999990001", "ANA MOTORISTA")
    b = cadastrar(esq, "MOT-B", "5547999990002", "BRUNO MOTORISTA")
    return ({"motorista_codigo": "MOT-A", "motorista_id": a, "nome": "ANA MOTORISTA"},
            {"motorista_codigo": "MOT-B", "motorista_id": b, "nome": "BRUNO MOTORISTA"},
            esq)


# ═══════════════════════════════════════════════════════════════ escopo ════

def test_um_motorista_NAO_le_a_conversa_do_outro(dois):
    """O guard mais importante deste arquivo."""
    ana, bruno, esq = dois
    c = mc.abrir(ana, "ferias", "Quando vencem minhas férias?", esquema=esq)
    assert mc.ler(ana, c["id"], esquema=esq)["conversa"]["id"] == c["id"]
    with pytest.raises(mc.Recusa):
        mc.ler(bruno, c["id"], esquema=esq)


def test_a_recusa_e_a_MESMA_para_inexistente_e_para_alheia(dois):
    """Distinguir as duas transformaria a rota num contador de conversas
    alheias: quem quisesse saber quantas existem bastava varrer os ids."""
    ana, bruno, esq = dois
    c = mc.abrir(ana, "ferias", "texto", esquema=esq)
    with pytest.raises(mc.Recusa) as alheia:
        mc.ler(bruno, c["id"], esquema=esq)
    with pytest.raises(mc.Recusa) as inexistente:
        mc.ler(bruno, 999999, esquema=esq)
    assert str(alheia.value) == str(inexistente.value)


def test_escrever_na_conversa_alheia_tambem_e_recusado(dois):
    """LER e ESCREVER passam pelo mesmo `_minha()`. Sem este guard, uma das
    duas portas poderia perder a conferência sem a outra perceber."""
    ana, bruno, esq = dois
    c = mc.abrir(ana, "ferias", "texto", esquema=esq)
    for acao in (lambda: mc.responder(bruno, c["id"], "oi", esquema=esq),
                 lambda: mc.dar_ciencia(bruno, c["id"], esquema=esq)):
        with pytest.raises(mc.Recusa):
            acao()


def test_o_dono_entra_na_CLAUSULA_e_nao_num_if():
    """Um `if` conferindo o dono depois da busca é a linha que alguém apaga.

    Teste de texto-fonte é exceção na casa, e ela se justifica pelo mesmo
    motivo da consulta sem dinheiro do `viagem.py`: o que se garante é a
    presença de uma cláusula, e um teste de comportamento provaria só que ela
    funcionou NESTE caso.
    """
    import inspect
    fonte = inspect.getsource(mc._minha)
    assert "motorista_codigo = %(mot)s" in fonte
    assert "WHERE c.id = %(id)s AND c.motorista_codigo" in fonte


# ═════════════════════════════════════════════ a lista fechada de assuntos ══

def test_assunto_fora_da_lista_e_recusado_no_SERVIDOR(dois):
    """A tela só oferece o que pode, mas quem garante é isto — um `assunto`
    livre chegando pelo corpo do pedido é a mesma coisa que não ter lista."""
    ana, _b, esq = dois
    with pytest.raises(mc.Recusa):
        mc.abrir(ana, "qualquer-coisa", "texto", esquema=esq)


def test_o_motorista_nao_abre_assunto_que_e_do_RH(dois):
    """`comunicado` é `quem_abre='rh'`: o motorista não pode se auto-comunicar
    (e a ciência dele viraria prova de leitura de um texto que ele escreveu)."""
    ana, _b, esq = dois
    assert "comunicado" not in [a["chave"] for a in mc.assuntos("motorista", esq)]
    with pytest.raises(mc.Recusa):
        mc.abrir(ana, "comunicado", "texto", esquema=esq)


def test_o_assunto_de_AMBOS_vale_dos_dois_lados(dois):
    """`documento` é `quem_abre='ambos'` — sem ele, o guard acima passaria com
    uma lista que separa os lados por acidente em vez de por regra."""
    do_mot = {a["chave"] for a in mc.assuntos("motorista", dois[2])}
    do_rh = {a["chave"] for a in mc.assuntos("rh", dois[2])}
    assert "documento" in do_mot and "documento" in do_rh


def test_a_ajuda_do_assunto_vai_junto(dois):
    """É ela que resolve metade dos pedidos ANTES de virar fila."""
    for a in mc.assuntos("motorista", dois[2]):
        assert a["ajuda"], "%s sem texto de ajuda" % a["chave"]


# ══════════════════════════════════════════════════════════════ os freios ══

def test_nao_se_abre_duas_do_MESMO_assunto(dois):
    """Duas filas sobre o mesmo assunto é como o RH responde uma e a outra
    envelhece. A recusa ENSINA: manda de volta para a que já existe."""
    ana, _b, esq = dois
    mc.abrir(ana, "ferias", "primeiro", esquema=esq)
    with pytest.raises(mc.Recusa) as exc:
        mc.abrir(ana, "ferias", "segundo", esquema=esq)
    assert "férias" in str(exc.value).lower()


def test_o_teto_de_abertas_segura_a_fila(dois, monkeypatch):
    """Não é desconfiança do motorista: é o que impede a fila do RH de virar
    impossível de atender por causa de uma pessoa com um dia ruim."""
    ana, _b, esq = dois
    monkeypatch.setattr(mc, "MAX_ABERTAS", 2)
    mc.abrir(ana, "ferias", "a", esquema=esq)
    mc.abrir(ana, "contracheque", "b", esquema=esq)
    with pytest.raises(mc.Recusa):
        mc.abrir(ana, "jornada", "c", esquema=esq)


def test_resolver_libera_a_vaga(dois, monkeypatch):
    """A outra ponta: um teto que contasse conversa RESOLVIDA travaria o
    motorista para sempre depois de cinco pedidos na vida."""
    ana, _b, esq = dois
    monkeypatch.setattr(mc, "MAX_ABERTAS", 1)
    c = mc.abrir(ana, "ferias", "a", esquema=esq)
    mc.mudar_status(c["id"], "resolvida", autor_nome="rh", esquema=esq)
    mc.abrir(ana, "contracheque", "b", esquema=esq)      # não levanta


def test_texto_vazio_e_texto_gigante_sao_recusados(dois):
    """Truncar o que a pessoa escreveu sem avisar é perder a metade que
    importava. Recusa legível, sempre."""
    ana, _b, esq = dois
    with pytest.raises(mc.Recusa):
        mc.abrir(ana, "ferias", "   ", esquema=esq)
    with pytest.raises(mc.Recusa):
        mc.abrir(ana, "ferias", "x" * (mc.MAX_TEXTO + 1), esquema=esq)


def test_conversa_resolvida_nao_reabre_por_escrita(dois):
    """Reabrir é explícito, e não um efeito de escrever: sem isso, uma conversa
    fechada volta para a fila do RH sem ninguém decidir, e a fila deixa de ter
    fim — que é a falha que o escopo previa."""
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "a", esquema=esq)
    mc.mudar_status(c["id"], "resolvida", autor_nome="rh", esquema=esq)
    with pytest.raises(mc.Recusa):
        mc.responder(ana, c["id"], "mais uma coisa", esquema=esq)


# ═══════════════════════════════════════════════════ o não-lido e o estado ══

def test_a_resposta_do_RH_vira_nao_lida_e_muda_o_estado(dois):
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "quando?", esquema=esq)
    assert mc.minhas(ana, esquema=esq)["nao_lidas"] == 0

    mc.responder_rh(c["id"], "vencem em 12/2026", autor_nome="rh@x", esquema=esq)
    d = mc.minhas(ana, esquema=esq)
    assert d["nao_lidas"] == 1
    assert d["conversas"][0]["status"] == "aguardando_motorista"

    mc.ler(ana, c["id"], esquema=esq)
    assert mc.minhas(ana, esquema=esq)["nao_lidas"] == 0


def test_responder_atribui_o_dono_no_ato(dois):
    """Atribuir só por botão deixa a fila cheia de conversas "em atendimento"
    sem ninguém dentro — e a pergunta "quem está com isso?" sem resposta."""
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "quando?", esquema=esq)
    mc.responder_rh(c["id"], "resposta", autor_nome="fernanda@x", esquema=esq)
    assert mc.ler_rh(c["id"], esq)["conversa"]["atendente"] == "fernanda@x"


def test_o_motorista_escrever_devolve_a_bola_para_o_RH(dois):
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "quando?", esquema=esq)
    mc.responder_rh(c["id"], "r", autor_nome="rh@x", esquema=esq)
    mc.responder(ana, c["id"], "obrigado, e sobre o abono?", esquema=esq)
    assert mc.ler_rh(c["id"], esq)["conversa"]["status"] == "em_atendimento"


# ═══════════════════════════════════════════════════════════ o comunicado ══

def test_ciencia_vira_mensagem_de_sistema_e_e_IDEMPOTENTE(dois):
    """É o que transforma "mandamos o comunicado" em prova de que ele leu — e
    dois toques no botão não podem virar duas ciências, senão a prova vira
    contagem."""
    ana, _b, esq = dois
    c = mc.abrir_rh(ana["motorista_id"], "comunicado", "Convenção",
                    "O reajuste entra na folha de outubro.",
                    autor_nome="rh@x", esquema=esq)
    assert mc.minhas(ana, esquema=esq)["pendencias"] == 1

    assert mc.dar_ciencia(ana, c["id"], esquema=esq)["ja_tinha"] is False
    assert mc.dar_ciencia(ana, c["id"], esquema=esq)["ja_tinha"] is True

    n = pglocal.um("SELECT count(*) AS n FROM mot_mensagens "
                   "WHERE conversa_id = %(id)s AND evento = 'ciencia'",
                   {"id": c["id"]}, esq)
    assert n["n"] == 1
    assert mc.minhas(ana, esquema=esq)["pendencias"] == 0


def test_ciencia_so_existe_onde_o_assunto_pede(dois):
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "texto", esquema=esq)
    with pytest.raises(mc.Recusa):
        mc.dar_ciencia(ana, c["id"], esquema=esq)


# ═════════════════════════════════════════════════════════ a caixa do RH ═══

def test_a_caixa_ordena_pelo_MAIS_PARADO(dois):
    """A diferença entre uma FILA e uma caixa de e-mail. Numa caixa por data,
    quem escreveu há três semanas nunca mais é visto — e é exatamente essa
    pessoa que liga para a torre."""
    ana, bruno, esq = dois
    velha = mc.abrir(ana, "ferias", "sou a mais antiga", esquema=esq)
    nova = mc.abrir(bruno, "ferias", "sou a mais nova", esquema=esq)
    pglocal.executar(
        "UPDATE mot_conversas SET ultima_em = now() - interval '10 days' "
        "WHERE id = %(id)s", {"id": velha["id"]}, esq)

    ids = [c["id"] for c in mc.caixa(esquema=esq)["conversas"]]
    assert ids[0] == velha["id"], "a caixa ordenou pela mais recente"
    assert nova["id"] in ids


def test_a_caixa_NAO_devolve_o_codigo_do_ERP(dois):
    """Ele é o CPF para pessoa física, e a caixa vai para um navegador. A tela
    precisa do nome, não do documento."""
    ana, _b, esq = dois
    cadastrar(esq, "12345678901", "5547999990003", "COM CPF NO CODIGO")
    mc.abrir(ana, "ferias", "texto", esquema=esq)
    payload = repr(mc.caixa(esquema=esq))
    assert "MOT-A" not in payload and "12345678901" not in payload
    assert "motorista_codigo" not in payload


def test_a_caixa_conta_a_fila_PARADA(dois):
    """O número que diz se o canal está funcionando. Sem ele, "temos um canal
    com o motorista" é uma frase; com ele, é uma medição — e é por ele que a
    decisão de manter ou desligar se toma com dado na mesa."""
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "texto", esquema=esq)
    assert mc.caixa(esquema=esq)["resumo"]["paradas_3d"] == 0
    pglocal.executar(
        "UPDATE mot_conversas SET ultima_em = now() - interval '5 days' "
        "WHERE id = %(id)s", {"id": c["id"]}, esq)
    assert mc.caixa(esquema=esq)["resumo"]["paradas_3d"] == 1


def test_o_RH_nao_abre_para_motorista_desligado(dois):
    ana, _b, esq = dois
    mid = cadastrar(esq, "MOT-C", "5547999990009", "SAIU", ativo=False)
    with pytest.raises(mc.Recusa):
        mc.abrir_rh(mid, "comunicado", "t", "x", autor_nome="rh@x", esquema=esq)


def test_estado_desconhecido_e_recusado(dois):
    ana, _b, esq = dois
    c = mc.abrir(ana, "ferias", "texto", esquema=esq)
    with pytest.raises(mc.Recusa):
        mc.mudar_status(c["id"], "arquivada", autor_nome="rh@x", esquema=esq)
    with pytest.raises(mc.Recusa):
        mc.caixa(status="inventado", esquema=esq)


# ══════════════════════════════════════════════════════ o aviso e a trilha ══

def test_o_aviso_do_whatsapp_NAO_leva_o_conteudo_nem_o_assunto():
    """O que o RH escreveu pode ser sobre salário, saúde ou desligamento, e
    WhatsApp é lido em tela de bloqueio — muitas vezes num aparelho
    compartilhado (medido: 5 dos 585 motoristas dividem o número). O canal tem
    o conteúdo; o aviso só diz que ele existe."""
    texto = mc.AVISO.lower()
    assert "app" in texto
    for vazamento in ("ferias", "férias", "contracheque", "salario", "salário",
                      "atestado", "demiss"):
        assert vazamento not in texto


def test_o_aviso_NAO_abre_a_janela_de_horario():
    """`entrada.py` abre a janela de propósito — código de entrada é resposta a
    alguém com o celular na mão às 03:40. Aqui é o contrário: resposta do RH é
    mensagem de empresa, que é o que a janela existe para conter. Aviso de
    férias às 3 da manhã é a denúncia que faz o número da casa ser banido."""
    import inspect

    from api import main
    fonte = inspect.getsource(main._avisar_motorista)
    assert "janela_inicio" not in fonte and "regras=" not in fonte, (
        "o aviso do RH passou a abrir a janela de horário do WhatsApp")


def test_a_entrada_ABRE_a_janela_e_isso_e_deliberado():
    """A outra ponta do guard acima: sem ela, um módulo que nunca abrisse a
    janela passaria nos dois e ninguém notaria que o código de entrada deixou
    de chegar de madrugada."""
    import inspect

    from api.motorista import entrada
    assert "janela_inicio" in inspect.getsource(entrada.pedir)


# ══════════════════════════════════════════════════════════════ as rotas ═══

def test_as_rotas_do_canal_exigem_sessao(esq):
    """Elas entram no guard geral (`test_rotas.py`), e este confirma que estão
    lá — uma rota de conversa que caísse em `SEM_SESSAO` seria a caixa de
    entrada de todo mundo aberta ao mundo."""
    from .test_rotas import rotas_do_app
    caminhos = {c for c, _ in rotas_do_app()}
    for esperada in ("/api/motorista/conversas",
                     "/api/motorista/conversas/{cid}",
                     "/api/motorista/conversas/{cid}/mensagem",
                     "/api/motorista/conversas/{cid}/ciencia"):
        assert esperada in caminhos, esperada


def test_a_caixa_do_RH_e_do_PAINEL_e_nao_do_app(esq):
    """As duas metades do canal vivem em mundos separados: o cookie do
    motorista nem é enviado para fora de `/api/motorista`, e a caixa do RH
    passa pelo middleware normal, com a tela `rhmot`."""
    from api import auth
    assert not auth._rota_publica("/api/rh/motorista/conversas")
    assert auth._telas_da_rota("/api/rh/motorista/conversas") == frozenset({"rhmot"})
    assert "rhmot" in auth.TELAS


def test_sessao_de_motorista_nao_abre_a_caixa_do_RH(esq):
    """O ponto inteiro da identidade separada, aplicado ao canal."""
    from api.main import app
    mid = cadastrar(esq, "MOT-A", "5547999990001", "ANA")
    sid = msessao.abrir("MOT-A", esquema=esq)
    c = TestClient(app)
    c.cookies.set(msessao.COOKIE, msessao.emitir(mid, sid))
    assert c.get("/api/rh/motorista/conversas").status_code in (401, 403)
