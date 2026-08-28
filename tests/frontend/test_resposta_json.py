# tests/frontend/test_resposta_json.py
"""A tela nao pode supor que toda resposta e JSON.

`r.json()` direto transforma qualquer resposta HTML - pagina de login com a
sessao expirada, erro de gateway, 502 do tunel - em "Unexpected token '<'",
que nao ajuda quem esta usando nem quem vai depurar. Foi exatamente o que
apareceu ao trocar um certificado vencido.
"""
from __future__ import annotations

import pathlib
import re

HTML = (pathlib.Path(__file__).resolve().parents[2]
        / "api" / "static" / "index.html").read_text(encoding="utf-8")


def test_a_tela_de_contrapartida_nao_chama_json_direto():
    """Os POSTs da tela passam por `respostaJSON`, que le como texto antes."""
    i = HTML.index("let CP_ALVO=null;")
    j = HTML.index("async function loadPoli(")
    trecho = HTML[i:j]
    assert "await r.json()" not in trecho, (
        "algum POST da contrapartida voltou a supor JSON")
    assert trecho.count("respostaJSON(r)") >= 4


def test_o_erro_carrega_status_e_tipo_de_conteudo():
    """Sem status e content-type, a mensagem nao permite distinguir sessao
    expirada de erro de gateway - que pedem acoes diferentes."""
    i = HTML.index("async function respostaJSON(r)")
    corpo = HTML[i:i + 1600]
    assert "r.status" in corpo and "content-type" in corpo


def test_pagina_de_login_e_reconhecida_a_parte():
    """A pagina de login costuma vir com 200 e por isso escapa do tratamento
    de 401 que ja existe no wrapper de fetch: sem deteccao propria, o usuario
    veria "erro" onde o certo e "entre de novo"."""
    i = HTML.index("async function respostaJSON(r)")
    corpo = HTML[i:i + 1600]
    assert re.search(r"login|sign in", corpo, re.I)
    assert "Recarregue a página" in corpo


def test_acao_repetida_sai_da_tabela_e_vira_frase():
    """"Coluna que repete o mesmo valor em todas as linhas sai da tabela" ja
    era regra escrita do projeto, e o validador a quebrou: "O que fazer"
    trazia o mesmo texto nas 29 linhas de certificado e nas 8 de inscricao,
    ocupando 40% da largura para dizer uma coisa so.

    Colapsa pela acao DOMINANTE e nao so quando todas sao iguais: no recorte
    de cadastro sao 8 linhas iguais e 1 diferente, e exigir unanimidade
    devolvia as oito repeticoes.

    ESTA GUARDA JA TRAVOU UM MEIO-TERMO RUIM. A primeira correcao mantinha a
    coluna quando havia excecao, preenchendo as demais com "a mesma acima" —
    que ocupa a largura e nao diz nada, o pior dos dois mundos. Agora a coluna
    SOME sempre que ha acao dominante, e a excecao leva a propria instrucao
    embaixo do diagnostico, onde ela se le junto com o defeito que a motivou.
    """
    i = HTML.index("function cpValidRender()")
    corpo = HTML[i:HTML.index("function cpAutoCarrega()", i)]
    assert "dominante" in corpo and "cpValidAcao" in corpo
    # havendo acao dominante, a coluna nao e desenhada
    assert "(colapsa ? '' : '<th>O que fazer</th>')" in corpo
    # e a excecao aparece NA LINHA, e nao numa coluna que existe por causa dela
    assert "divergentes" in corpo
    # A FORMA RENDERIZADA, e nao a frase: o comentario que explica por que o
    # preenchimento repetido saiu cita "a mesma acima", e uma guarda textual
    # nao distingue codigo de prosa — ela acusaria a propria documentacao.
    assert "a mesma acima</span>" not in corpo, (
        "voltou o preenchimento repetido da coluna colapsada")


def test_botao_de_cadastro_so_na_categoria_de_certificado():
    """Nas linhas de cadastro a correcao e no ERP ou no SINTEGRA: abrir ali o
    cadastro de certificado nao resolve nada e contradiz a instrucao da
    propria linha."""
    i = HTML.index("function cpValidRender()")
    corpo = HTML[i:HTML.index("function cpAutoCarrega()", i)]
    assert "const pode = a.categoria==='certificado';" in corpo
