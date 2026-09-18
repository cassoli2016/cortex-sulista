# -*- coding: utf-8 -*-
"""Tag de HTML escrita DENTRO do texto sai literal na mensagem.

ACONTECEU EM 18/09/2026, num comunicado para quatro gerentes com cópia para a
direção: o último parágrafo foi escrito como

    p.paragrafo("O painel fica em <b>Gestão › Ritual Semanal</b> "
                '(<a href="%s">%s</a>)' % (url, url))

e chegou assim, com as tags à mostra, porque `painel.paragrafo()` ESCAPA o
conteúdo — e escapar é o certo, é a defesa contra o texto de terceiro que vira
marcação. Quem quer link usa `painel.botao()`; quem quer negrito reescreve a
frase. O defeito não tem sintoma nenhum do lado de quem envia: o Python roda,
o e-mail sai, o SMTP aceita, e só quem ABRE a mensagem vê.

São dois guards, e a divisão importa: um prova o COMPORTAMENTO do molde (que
ele escapa), e o outro VARRE o disco atrás de quem passa tag pelo texto — é o
segundo que teria pego o comunicado antes de ele sair.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from api.correio import painel as p

RAIZ = Path(__file__).resolve().parents[2]

#: As funções do molde que ESCAPAM o que recebem. Quem chamar uma delas com
#: tag dentro está escrevendo marcação que o leitor vai ver como texto.
ESCAPAM = {"paragrafo", "secao", "chip", "tabela"}


def test_o_molde_ESCAPA_o_texto_e_isso_e_o_certo():
    """Sem isto, um nome de cliente com `<` quebraria a mensagem — ou pior,
    entraria como marcação. O guard fixa o comportamento para que a correção
    da tag literal não vire "parar de escapar"."""
    html = p.paragrafo('um <b>negrito</b> e um <a href="#">link</a>')
    assert "<b>" not in html and "<a href" not in html
    assert "&lt;b&gt;" in html


def test_o_BOTAO_e_o_caminho_do_link():
    """A alternativa existe, e é ela que deveria ter sido usada."""
    html = p.botao("Abrir o painel", "https://exemplo.invalido/x")
    assert '<a href="https://exemplo.invalido/x"' in html


def _chamadas_com_tag() -> list[str]:
    """Varre o disco atrás de tag dentro de texto que vai ser escapado.

    Lê por `ast`, e não por regex sobre a linha: a chamada quase sempre ocupa
    várias linhas e o texto vem de literais concatenados, que só a árvore junta
    corretamente. Só literais são avaliados — `%s` e variáveis ficam de fora,
    porque o que se procura é a TAG escrita à mão.
    """
    achados, vistas = [], 0
    alvos = sorted((RAIZ / "api").rglob("*.py"))
    for arq in alvos:
        try:
            arvore = ast.parse(arq.read_text(encoding="utf-8"))
        except SyntaxError:                      # pragma: no cover
            continue
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            alvo = no.func
            nome = (alvo.attr if isinstance(alvo, ast.Attribute)
                    else getattr(alvo, "id", ""))
            if nome not in ESCAPAM:
                continue
            vistas += 1
            for arg in [*no.args, *(k.value for k in no.keywords)]:
                texto = ""
                for pedaco in ast.walk(arg):
                    if isinstance(pedaco, ast.Constant) and isinstance(pedaco.value, str):
                        texto += pedaco.value
                if "<" in texto and ">" in texto:
                    achados.append("%s:%d %s(%r)" % (
                        arq.relative_to(RAIZ), no.lineno, nome, texto[:70]))
    # VARREDURA QUE NÃO ACHA NADA PASSA POR VACUIDADE: se um dia o molde for
    # renomeado, o guard ficaria verde sem olhar coisa alguma.
    assert vistas >= 20, ("a varredura encontrou só %d chamadas ao molde — "
                          "ela parou de enxergar o que deveria vigiar" % vistas)
    return achados


def test_ninguem_escreve_TAG_dentro_do_texto_do_email():
    achados = _chamadas_com_tag()
    assert not achados, (
        "estas chamadas escrevem HTML dentro de um texto que vai ser ESCAPADO "
        "— a tag chega literal na mensagem. Link é `painel.botao()`: %s"
        % achados)


def test_a_varredura_PEGA_uma_tag_plantada(tmp_path):
    """A sabotagem do guard mora dentro dele: sem esta prova, "nenhum achado"
    poderia significar "a varredura não funciona"."""
    falso = tmp_path / "api" / "correio"
    falso.mkdir(parents=True)
    (falso / "ruim.py").write_text(
        'from api.correio import painel as p\n'
        'x = p.paragrafo("veja o <b>painel</b> aqui")\n', encoding="utf-8")
    (falso / "ok.py").write_text(
        'from api.correio import painel as p\n'
        'y = p.paragrafo("veja o painel aqui")\n', encoding="utf-8")
    achados = []
    for arq in sorted((tmp_path / "api").rglob("*.py")):
        arvore = ast.parse(arq.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call):
                nome = (no.func.attr if isinstance(no.func, ast.Attribute)
                        else getattr(no.func, "id", ""))
                if nome in ESCAPAM:
                    for arg in no.args:
                        if isinstance(arg, ast.Constant) and "<" in str(arg.value):
                            achados.append(arq.name)
    assert achados == ["ruim.py"], achados


@pytest.mark.parametrize("funcao", sorted(ESCAPAM))
def test_a_lista_de_funcoes_que_escapam_aponta_para_funcao_REAL(funcao):
    """Lista de nomes escrita à mão precisa ser conferida contra a fonte: um
    nome trocado deixaria a varredura ignorando justamente o que ela vigia."""
    assert callable(getattr(p, funcao)), funcao
