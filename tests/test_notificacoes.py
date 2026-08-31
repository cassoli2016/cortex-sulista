"""Notificações — o boas-vindas do primeiro acesso, e por que ele não é uma fila.

O DESENHO QUE ESTES TESTES GUARDAM
==================================
A notificação é DERIVADA a cada leitura; o que se grava é só o que a pessoa
dispensou. Uma fila precisaria de alguém para enfileirar, e no dia em que essa
rotina não rodasse o usuário novo entraria sem receber nada — sem erro, sem
alarme, sem ninguém saber. É o mesmo formato do marcador de manutenção parado
em 77.534 km e do "cliente ativo" que o CRM lê do faturamento em vez de gravar.

E o "já vi isso" é fato sobre a PESSOA, não sobre o navegador: no
`localStorage` o boas-vindas reapareceria no celular, no outro computador e
depois de limpar o cache.
"""
from __future__ import annotations

import pytest

from api import notificacoes as N, pglocal


@pytest.fixture
def usuario(esquema_pg):
    """Um usuário de verdade: `not_lidas` tem FK para `usuarios`."""
    N.ESQUEMA = esquema_pg
    pglocal.executar(
        "INSERT INTO perfis(nome, admin, criado_em) "
        "VALUES ('Teste', 0, '2026-08-31')", esquema=esquema_pg)
    pid = pglocal.um("SELECT id FROM perfis WHERE nome = 'Teste'",
                     esquema=esquema_pg)["id"]
    pglocal.executar(
        "INSERT INTO usuarios(nome, email, senha_hash, perfil_id, criado_em) "
        "VALUES ('MARCOS ANTONIO CASSOLI DA SILVA', 't@s.local', 'x', %s, "
        "'2026-08-31')", (pid,), esquema=esquema_pg)
    uid = pglocal.um("SELECT id FROM usuarios WHERE email = 't@s.local'",
                     esquema=esquema_pg)["id"]
    try:
        yield uid
    finally:
        N.ESQUEMA = None


def _sessao(uid):
    return {"id": uid, "nome": "MARCOS ANTONIO CASSOLI DA SILVA"}


# ── o primeiro acesso ───────────────────────────────────────────────────────


def test_quem_nunca_dispensou_recebe_o_boas_vindas(usuario):
    r = N.listar(_sessao(usuario))
    assert r["nao_lidas"] == 1
    assert [x["chave"] for x in r["itens"]] == ["boas_vindas"]


def test_o_cumprimento_usa_o_PRIMEIRO_NOME(usuario):
    """"Bem-vindo ao CÓRTEX, MARCOS ANTONIO CASSOLI DA SILVA" é cabeçalho de
    cadastro, não cumprimento."""
    t = N.listar(_sessao(usuario))["itens"][0]["titulo"]
    assert t == "Bem-vindo ao CÓRTEX, Marcos"


def test_sem_nome_o_titulo_nao_fica_com_virgula_solta(usuario):
    """"Bem-vindo ao CÓRTEX, " com a vírgula pendurada é o defeito clássico de
    concatenação — e cadastro sem nome existe."""
    t = N.listar({"id": usuario, "nome": ""})["itens"][0]["titulo"]
    assert t == "Bem-vindo ao CÓRTEX"


def test_depois_de_dispensar_nao_volta(usuario):
    assert N.marcar_lida(usuario, "boas_vindas") is True
    r = N.listar(_sessao(usuario))
    assert r["itens"] == [] and r["nao_lidas"] == 0


def test_dispensar_duas_vezes_nao_cria_duas_linhas(usuario):
    """Dois cliques no botão, ou um clique com a rede lenta e o repique do
    usuário. O `ON CONFLICT DO NOTHING` sobre o UNIQUE resolve, e a rota não
    precisa saber disso."""
    N.marcar_lida(usuario, "boas_vindas")
    N.marcar_lida(usuario, "boas_vindas")
    n = pglocal.um("SELECT count(*)::int AS n FROM not_lidas WHERE usuario_id = %s",
                   (usuario,), esquema=N.ESQUEMA)["n"]
    assert n == 1


# ── o que a tabela recusa ───────────────────────────────────────────────────


def test_chave_desconhecida_e_RECUSADA_e_nao_gravada(usuario):
    """Sem a lista de chaves conhecidas, um POST com `chave="qualquer"` gravaria
    lixo permanente — e é justamente esta tabela que decide o que aparece."""
    assert N.marcar_lida(usuario, "inventada") is False
    n = pglocal.um("SELECT count(*)::int AS n FROM not_lidas", esquema=N.ESQUEMA)["n"]
    assert n == 0


def test_a_marca_nao_sobrevive_a_pessoa(usuario):
    """`ON DELETE CASCADE`: sem ele, excluir usuário passa a falhar por chave
    estrangeira — e isso só aparece no dia da exclusão, que é tarde. Mesma
    lição da tabela de fotos."""
    N.marcar_lida(usuario, "boas_vindas")
    pglocal.executar("DELETE FROM usuarios WHERE id = %s", (usuario,),
                     esquema=N.ESQUEMA)
    n = pglocal.um("SELECT count(*)::int AS n FROM not_lidas", esquema=N.ESQUEMA)["n"]
    assert n == 0


def test_sessao_sem_id_devolve_vazio_em_vez_de_estourar(usuario):
    """A barra de topo chama isto em toda carga; um `KeyError` aqui derrubaria
    o menu inteiro por causa de um badge."""
    assert N.listar({"nome": "X"}) == {"itens": [], "nao_lidas": 0}


# ── o desenho, e não a implementação ────────────────────────────────────────


def test_a_notificacao_NAO_e_gravada_em_lugar_nenhum(usuario):
    """O que existe na tabela é a DISPENSA, nunca a notificação pendente. Se
    alguém trocar isto por uma fila, o usuário novo passa a depender de uma
    rotina que pode não rodar — e o sintoma é silêncio."""
    N.listar(_sessao(usuario))
    n = pglocal.um("SELECT count(*)::int AS n FROM not_lidas", esquema=N.ESQUEMA)["n"]
    assert n == 0, "listar() não pode escrever nada"


def test_o_boas_vindas_aponta_para_uma_tela_QUE_EXISTE(usuario):
    """Ação que leva a lugar nenhum é pior que ação nenhuma: o clique some com
    a notificação e não abre nada."""
    from api import auth
    acao = N.listar(_sessao(usuario))["itens"][0]["acao"]
    assert acao["view"] in auth.TELAS or acao["view"] in ("doc",), acao
