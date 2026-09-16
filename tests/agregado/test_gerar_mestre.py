# -*- coding: utf-8 -*-
"""O código mestre do app do agregado: onde ele se gera, e o registro que
impede o PRÓXIMO app de nascer sem gerador.

O DEFEITO QUE ESTE ARQUIVO GUARDA NÃO TINHA SINTOMA NENHUM.

O app do agregado subiu na v1.97.0 com o mecanismo de acesso mestre inteiro —
piso de 16 caracteres, comparação em tempo constante, teto por endereço, tarja
na tela, prazo de 8 horas e trilha separada —, lendo o cofre na chave
`AGREGADO_CODIGO_MESTRE`. Só que:

* a chave não entrou em `credenciais.CAMPOS`, e a tela de Gestão só sabe editar
  o que está no catálogo (`CONHECIDAS`) — então nem campo para colar à mão
  existia;
* a rota que gera (`/api/gestao/credenciais/gerar-mestre`) importava
  `api.motorista.mestre` e só sabia gravar NAQUELA chave;
* o botão "gerar agora" do formulário comparava o nome da credencial com a
  string `'MOTORISTA_CODIGO_MESTRE'`.

O resultado foi um acesso de conferência que a Saúde do Servidor COBRAVA e que
não tinha onde ser gerado. Nada levantou exceção, nenhum teste ficou vermelho, e
a pergunta que descobriu o buraco foi de quem opera: *"onde eu gero a senha
master?"*.

Por isso os guards daqui não olham para a chave do agregado: olham para o
REGISTRO (`credenciais.MESTRES`) e o conferem CONTRA os módulos dos apps,
importando-os. Lista escrita à mão é o que falha nesta casa, e ela só falha em
silêncio — a varredura de agendadores passou meses nomeando uma thread que não
existia, e o guard do EXISTS aprovava a única violação viva por não varrer o
próprio módulo que a continha.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from api import auth, credenciais, integracoes
from api.gestao import comum

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

    Sem este dublê o teste sobrescreveria os códigos mestre de PRODUÇÃO — a
    mesma classe de acidente do `sabotar-isolamento-escreve-em-producao`, só que
    num segredo em vez de numa tabela. `ler` vem junto de `gravar` de propósito:
    é o par que permite provar que o código gerado ABRE o acesso, em vez de só
    conferir que alguma coisa foi escrita.
    """
    guardado: dict[str, str] = {}
    monkeypatch.setattr(credenciais, "gravar",
                        lambda nome, valor: guardado.update({nome: valor})
                        or {"nome": nome, "configurado": True})
    monkeypatch.setattr(credenciais, "ler",
                        lambda nome: guardado.get(nome, ""))
    return guardado


# ═════════════════════════════════════ o registro, conferido contra o código ══

def test_o_registro_de_mestres_BATE_COM_OS_MODULOS_dos_apps():
    """String escrita à mão que descreve código de outro módulo se confere
    IMPORTANDO o módulo, nunca por leitura.

    Se alguém renomear a `CHAVE` do app ou mexer no piso de tamanho, o registro
    fica apontando para uma chave que não existe mais — e o sintoma seria o
    silêncio de sempre: o botão grava num lugar e o app lê de outro, dizendo
    "código inválido" para um código recém-gerado.
    """
    assert credenciais.MESTRES, "o registro veio vazio — a varredura passaria por vacuidade"
    for app, reg in credenciais.MESTRES.items():
        mod = importlib.import_module(reg["modulo"])
        assert mod.CHAVE == reg["chave"], (
            f"{app}: o registro diz {reg['chave']}, o módulo usa {mod.CHAVE}")
        assert mod.TAMANHO_MINIMO == reg["minimo"], (
            f"{app}: o piso do registro ({reg['minimo']}) difere do que o "
            f"módulo aplica ({mod.TAMANHO_MINIMO}) — a tela aceitaria um código "
            f"que o app recusa depois, em silêncio")


def test_todo_codigo_mestre_do_registro_ESTA_NO_CATALOGO_com_o_piso_dele():
    """A tela de Gestão só sabe editar o que está em `CONHECIDAS`: chave fora
    do catálogo é chave sem campo, que foi exatamente o caso do agregado.

    E o piso tem de ser o do MÓDULO: com o mínimo de 8 da casa, um código curto
    passaria aqui e o app o recusaria depois — "salvei e não funciona".
    """
    for app, reg in credenciais.MESTRES.items():
        chave = reg["chave"]
        assert chave in credenciais.CONHECIDAS, (
            f"{app}: {chave} não está no catálogo — a tela de Gestão não tem "
            f"como mostrar o campo, e o segredo não tem onde ser gerado")
        assert credenciais.MINIMO_POR_CREDENCIAL.get(chave) == reg["minimo"], (
            f"{app}: {chave} sem o piso de {reg['minimo']} caracteres")


def test_todo_codigo_mestre_e_ALCANCAVEL_no_painel_de_integracoes():
    """Sem cartão não há modal, e sem modal o formulário é inalcançável — o
    defeito de 07/09 a 10/09/2026, que deixou o gerador do motorista existindo e
    respondendo sem que ninguém conseguisse clicar nele.

    A varredura sai do REGISTRO e confere o painel inteiro: app novo com código
    mestre reprova aqui até ganhar cartão próprio.
    """
    servicos = credenciais.panorama()
    campos_por_servico = {
        s["chave"]: {c["nome"] for m in s["modos"] for c in m["campos"]}
        for s in servicos}
    proprios = {i["chave"] for i in integracoes.panorama([])["proprios"]}
    for app, reg in credenciais.MESTRES.items():
        dono = [ch for ch, campos in campos_por_servico.items()
                if reg["chave"] in campos]
        assert len(dono) == 1, (
            f"{app}: {reg['chave']} aparece em {len(dono)} cartão(ões) do "
            f"painel — precisa de exatamente um, com gerador próprio")
        assert dono[0] in integracoes.NAO_SAO_FORNECEDOR, (
            f"{app}: o cartão {dono[0]} está na lista de FORNECEDORES, e viraria "
            f"uma integração que nunca responde")
        assert dono[0] in proprios, (
            f"{app}: o cartão {dono[0]} não sai na aba dos segredos da casa — "
            f"sem cartão não há modal, e sem modal não há botão")


def test_o_campo_VEM_MARCADO_para_a_tela_saber_que_tem_gerador():
    """A marca é o que substituiu o `=== 'MOTORISTA_CODIGO_MESTRE'` do
    formulário. Ela diz DE QUE APP o campo é — nunca o valor —, e é por isso que
    pode viajar para a tela.
    """
    for app, reg in credenciais.MESTRES.items():
        st = credenciais.status(reg["chave"])
        assert st.get("mestre") == app, (
            f"{reg['chave']} sem a marca de código mestre: o botão de gerar não "
            f"apareceria no formulário")
        assert "valor" not in st, "o valor de um segredo nunca vai para a tela"
    # e um campo comum NÃO ganha a marca — senão o botão apareceria no lugar
    # errado, oferecendo trocar o token de um fornecedor por um sorteio nosso
    assert "mestre" not in credenciais.status("GOBRAX_TOKEN")


# ═══════════════════════════════════════════════════════════════════ a rota ══

def test_gera_NA_CHAVE_DO_APP_PEDIDO_e_nao_encosta_na_do_outro(cliente, cofre_falso):
    """A rotação é POR APP. Gerar o código do agregado não pode derrubar o
    acesso de quem está conferindo o app de um motorista neste minuto."""
    antes = cliente.post("/api/gestao/credenciais/gerar-mestre?app=motorista")
    assert antes.status_code == 200, antes.text
    do_motorista = antes.json()["codigo"]

    r = cliente.post("/api/gestao/credenciais/gerar-mestre?app=agregado")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["app"] == "agregado"
    assert cofre_falso["AGREGADO_CODIGO_MESTRE"] == d["codigo"]
    assert cofre_falso["MOTORISTA_CODIGO_MESTRE"] == do_motorista, (
        "gerar o código de um app trocou o do outro")
    assert d["codigo"] != do_motorista


def test_o_padrao_continua_sendo_o_MOTORISTA(cliente, cofre_falso):
    """Compatibilidade com quem chamava antes desta versão — inclusive uma aba
    aberta com o `index.html` antigo em cache. Exigir o parâmetro transformaria
    a entrega num erro para quem não recarregou a página."""
    r = cliente.post("/api/gestao/credenciais/gerar-mestre")
    assert r.status_code == 200, r.text
    assert r.json()["app"] == "motorista"
    assert "MOTORISTA_CODIGO_MESTRE" in cofre_falso
    assert "AGREGADO_CODIGO_MESTRE" not in cofre_falso


def test_app_DESCONHECIDO_e_recusa_legivel_e_nao_grava_nada(cliente, cofre_falso):
    """A lista fechada mora no registro: `app` que vem do cliente nunca vira
    nome de chave. Recusa é 4xx — 5xx o Cloudflare troca pela página dele, e a
    mensagem não chega."""
    r = cliente.post("/api/gestao/credenciais/gerar-mestre?app=../cortex")
    assert r.status_code == 409, r.text
    assert "codigo" not in r.json()
    assert not cofre_falso, "recusa que mesmo assim escreveu no cofre"


def test_o_codigo_gerado_ABRE_O_ACESSO_de_verdade(cliente, cofre_falso, esq):
    """O teste que fecha o ciclo, e o único que teria pego o defeito inteiro:
    não basta gravar uma string — o módulo do app tem de aceitá-la depois.

    Era aqui que o buraco aparecia: `configurado()` respondia False para sempre,
    porque ninguém tinha como pôr valor naquela chave.
    """
    from api.agregado import mestre as am

    assert not am.configurado(), "o cofre do teste devia nascer vazio"
    codigo = cliente.post(
        "/api/gestao/credenciais/gerar-mestre?app=agregado").json()["codigo"]
    assert am.configurado(), (
        "o código foi gerado e o app continua dizendo que não há acesso mestre")
    am.conferir(codigo, ip="10.0.0.1", esquema=esq)          # silêncio = vale
    with pytest.raises(am.Recusa):
        am.conferir(codigo + "x", ip="10.0.0.2", esquema=esq)


def test_o_SEGREDO_nao_entra_na_trilha_mas_o_APP_entra(cliente, cofre_falso):
    """`audit_log` é append-only e imutável: um valor que entrasse ali não sairia
    mais. O que se registra é quem gerou, para qual app, e quando — e o app
    precisa estar lá, senão duas rotações ficam indistinguíveis depois."""
    codigo = cliente.post(
        "/api/gestao/credenciais/gerar-mestre?app=agregado").json()["codigo"]
    with auth._conn() as c:
        linhas = c.execute(
            "SELECT usuario, acao, alvo, detalhe FROM audit_log "
            "WHERE acao = 'codigo_mestre_gerado'").fetchall()
    assert linhas, "gerar o código mestre não entrou na trilha"
    trilha = repr([dict(l) for l in linhas])
    assert codigo not in trilha, "O SEGREDO FOI PARAR NA TRILHA IMUTÁVEL"
    assert "AGREGADO_CODIGO_MESTRE" in trilha
    assert "app do agregado" in trilha
