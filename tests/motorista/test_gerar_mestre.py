# -*- coding: utf-8 -*-
"""O gerador do código mestre — a única rota da casa que devolve um segredo.

POR QUE O GERADOR MORA NO CÓRTEX (pedido de quem opera, 07/09/2026): a
alternativa era alguém digitar 24 caracteres aleatórios num `.env` da máquina
de produção. Na prática isso dá um de dois finais — ou ninguém configura, e o
acesso de conferência não existe; ou alguém escolhe um valor memorizável, e o
segredo que abre a PII de ~300 pessoas vira um palpite.

A EXCEÇÃO DE DEVOLVER O SEGREDO tem a mesma forma da senha provisória da casa:
o valor é gerado PELO SISTEMA (nunca escolhido), vai para o cofre no mesmo
instante, e a resposta é a única chance de lê-lo. O que este arquivo guarda são
as três coisas que fazem essa exceção ser segura — e cada uma some por um
motivo diferente numa refatoração distraída.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import auth, credenciais
from api.gestao import comum
from api.motorista import mestre as mm

SENHA = "senha-de-teste-123"


@pytest.fixture
def cliente(esquema_pg, monkeypatch):
    """API de pé com um administrador logado, sobre um schema descartável."""
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute(
            "SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES('Chefe','chefe@sulista.com.br',%s,%s,1,0,%s)""",
            (auth._ph.hash(SENHA), perfil["id"], auth._agora()))
    cli = TestClient(app)
    r = cli.post("/api/auth/login",
                 json={"email": "chefe@sulista.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


@pytest.fixture
def cofre_falso(monkeypatch):
    """O COFRE É UM ARQUIVO, e arquivo não tem schema descartável.

    Sem este dublê, o teste sobrescreveria o código mestre de PRODUÇÃO — que é
    exatamente a classe de acidente do `sabotar-isolamento-escreve-em-producao`,
    só que num segredo em vez de numa tabela.
    """
    guardado = {}
    monkeypatch.setattr(credenciais, "gravar",
                        lambda nome, valor: guardado.update({nome: valor})
                        or {"nome": nome, "configurado": True})
    return guardado


# ═══════════════════════════════════════════════════ o código que ele gera ══

def test_o_codigo_e_forte_e_sem_caractere_AMBIGUO():
    """Ele é LIDO DE UMA TELA E DIGITADO NOUTRA, às vezes num celular. O/0/l/I/1
    aqui não é elegância — é o chamado de "não funciona" que ninguém consegue
    diagnosticar, porque quem digitou jura que digitou certo. Mesma regra da
    senha provisória da casa."""
    vistos = {credenciais.gerar_codigo_mestre() for _ in range(50)}
    assert len(vistos) == 50, "o gerador repetiu — não é aleatório de verdade"
    for cod in vistos:
        assert len(cod) >= mm.TAMANHO_MINIMO
        assert not (set(cod) & set("O0lI1")), (
            "caractere ambíguo no código: %r" % cod)
        assert cod.count("-") == 3, "os grupos ajudam a digitar sem errar"


def test_o_minimo_do_cofre_para_ESTE_campo_e_o_do_modulo():
    """Os outros mínimos da casa vão para BAIXO porque o FORNECEDOR decide o
    tamanho da senha dele. Este vai para CIMA, e é o único: é segredo nosso, e
    abre a PII de ~300 pessoas. Sem esta linha, o mínimo de 8 da casa deixaria
    passar um código que o app depois recusaria em silêncio — "salvei e não
    funciona"."""
    assert credenciais.MINIMO_POR_CREDENCIAL[mm.CHAVE] == mm.TAMANHO_MINIMO
    assert mm.CHAVE in credenciais.CONHECIDAS, (
        "fora do catálogo, a tela de Gestão nem sabe editar este campo")


# ══════════════════════════════════════════════════════════════ a rota ═════

def test_sem_sessao_nao_gera_nada():
    from api.main import app
    r = TestClient(app).post("/api/gestao/credenciais/gerar-mestre")
    assert r.status_code == 401
    assert "codigo" not in r.text


def test_gera_grava_no_cofre_e_devolve_UMA_vez(cliente, cofre_falso):
    r = cliente.post("/api/gestao/credenciais/gerar-mestre")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["codigo"] and d["aviso"]
    # o que voltou é EXATAMENTE o que foi para o cofre
    assert cofre_falso[mm.CHAVE] == d["codigo"]
    # e ele abre o acesso de verdade
    assert len(d["codigo"]) >= mm.TAMANHO_MINIMO


def test_gerar_de_novo_SUBSTITUI(cliente, cofre_falso):
    """Isto é a rotação: quem sabia o código velho perde o acesso na hora."""
    primeiro = cliente.post("/api/gestao/credenciais/gerar-mestre").json()["codigo"]
    segundo = cliente.post("/api/gestao/credenciais/gerar-mestre").json()["codigo"]
    assert primeiro != segundo
    assert cofre_falso[mm.CHAVE] == segundo


def test_o_SEGREDO_NAO_entra_na_trilha(cliente, cofre_falso, esquema_pg):
    """`audit_log` é append-only e imutável: um valor que entrasse ali não sairia
    mais. O que se registra é que alguém gerou, e quando — que é a pergunta que
    a auditoria responde."""
    codigo = cliente.post("/api/gestao/credenciais/gerar-mestre").json()["codigo"]
    with auth._conn() as c:
        linhas = c.execute(
            "SELECT usuario, acao, alvo, detalhe FROM audit_log "
            "WHERE acao = 'codigo_mestre_gerado'").fetchall()
    assert linhas, "gerar o código mestre não entrou na trilha"
    trilha = repr([dict(l) for l in linhas])
    assert codigo not in trilha, "O SEGREDO FOI PARAR NO audit_log"
    assert "chefe@sulista.com.br" in trilha, "a trilha não diz QUEM gerou"


def test_falha_ao_gravar_NAO_devolve_o_codigo(cliente, monkeypatch):
    """Devolver o código sem ter gravado seria a pior das saídas: quem lê copia
    um segredo que não abre nada, e o acesso continua com o valor antigo — sem
    ninguém saber."""
    def explode(nome, valor):
        raise OSError("disco cheio")
    monkeypatch.setattr(credenciais, "gravar", explode)
    r = cliente.post("/api/gestao/credenciais/gerar-mestre")
    assert r.status_code == 500
    assert "codigo" not in r.json()
