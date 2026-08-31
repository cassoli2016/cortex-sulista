"""Modelos de mensagem de WhatsApp — o texto escrito uma vez e reusado.

O que este arquivo protege, em ordem de quanto custa errar:

1. **Mensagem com buraco não sai.** `{{cliente}}` sem valor recusa o envio em
   vez de virar "Prezado , ...". A rede é dupla: `enviar_modelo` renderiza
   estrito, e `enviar` recusa qualquer texto que ainda tenha `{{...}}` — mesmo
   vindo de uma área que não usou modelo nenhum.
2. **Variável fora do contexto é recusada NA GRAVAÇÃO.** É o único momento em
   que alguém está olhando. Depois, quem descobre é o cliente.
3. **A substituição não é `str.format`.** Texto escrito por usuário passando
   por `format` alcança atributo de objeto; aqui `{0}` e `{x.y}` são texto
   comum, e continuam texto comum.
"""
from __future__ import annotations

import pytest

from api.whatsapp import modelos as md


# ------------------------------------------------------------- renderização

def test_renderiza_o_que_tem_e_recusa_o_que_falta():
    corpo = "Olá {{cliente}}, o título {{documento}} vence em {{vencimento}}."
    texto = md.renderizar(corpo, {"cliente": "TUPY", "documento": "123",
                                  "vencimento": "15/08/2026"})
    assert texto == "Olá TUPY, o título 123 vence em 15/08/2026."

    with pytest.raises(md.VariavelFaltando, match="vencimento"):
        md.renderizar(corpo, {"cliente": "TUPY", "documento": "123"})


def test_valor_em_branco_conta_como_faltando():
    """Espaço em branco no formulário é o mesmo que não preencher — e é o caso
    real: a pessoa apaga o exemplo e esquece de digitar."""
    with pytest.raises(md.VariavelFaltando):
        md.renderizar("Olá {{cliente}}", {"cliente": "   "})


def test_variavel_repetida_e_pedida_uma_vez_so():
    corpo = "{{cliente}}, obrigado. Até logo, {{cliente}}!"
    assert md.variaveis_usadas(corpo) == ["cliente"]
    assert md.renderizar(corpo, {"cliente": "TUPY"}) == "TUPY, obrigado. Até logo, TUPY!"


def test_chave_de_format_nao_e_interpretada():
    """`str.format` sobre texto de usuário é acesso a atributo de objeto:
    `{0.__class__}` alcança o interpretador. A substituição é por regex, e
    chave de format continua sendo texto."""
    corpo = "Total {0} e {conta.saldo} e {}"
    assert md.renderizar(corpo, {}) == corpo


def test_chave_malformada_e_recusada_em_vez_de_sair_literal():
    for ruim in ("Olá {{ Cliente }}", "Olá {{2via}}", "Olá {{}}"):
        with pytest.raises(md.ModeloInvalido, match="não é uma variável válida"):
            md.validar({"nome": "x", "contexto": "cobranca", "corpo": ruim})


def test_previa_mostra_o_buraco_em_vez_de_sumir_com_ele():
    """A prévia do editor NÃO é estrita: quem está escrevendo precisa ver o
    texto inteiro, com o campo por preencher marcado."""
    assert md.previa("Olá {{cliente}}, {{documento}}", "cobranca") == \
        "Olá TUPY FUNDIÇÕES, 123456"
    assert md.renderizar("Olá {{cliente}}", {}, estrito=False) == "Olá [cliente]"


def test_texto_gigante_depois_de_preenchido_e_recusado():
    """O corpo cabe no limite e a mensagem preenchida não — é o caso que só
    aparece com o valor real na mão."""
    with pytest.raises(md.VariavelFaltando, match="4096"):
        md.renderizar("{{cliente}}", {"cliente": "x" * 5000})


# ------------------------------------------------------------------ contexto

def test_variavel_fora_do_contexto_e_recusada_com_a_lista_do_que_existe():
    with pytest.raises(md.ModeloInvalido) as exc:
        md.validar({"nome": "Aviso", "contexto": "viagem",
                    "corpo": "Olá {{cliente}}, o título {{documento}} venceu."})
    assert "{{documento}}" in str(exc.value)
    assert "Viagem" in str(exc.value)          # diz o contexto pelo rótulo
    assert "previsao" in str(exc.value)        # e o que está disponível


def test_contexto_livre_nao_aceita_variavel_nenhuma():
    with pytest.raises(md.ModeloInvalido, match="nenhuma"):
        md.validar({"nome": "x", "contexto": "livre", "corpo": "Olá {{cliente}}"})


def test_contexto_inexistente_e_recusado():
    """O nome escolhido aqui não pode ser um candidato a virar contexto de
    verdade — este teste já quebrou no dia em que "faturamento" foi criado."""
    with pytest.raises(md.ModeloInvalido, match="não existe"):
        md.validar({"nome": "x", "contexto": "contexto-que-nunca-existira",
                    "corpo": "oi"})


def test_todo_contexto_declara_exemplo_para_toda_variavel():
    """A prévia do editor é feita com esses exemplos: variável sem exemplo
    apareceria vazia justamente na hora de conferir o texto."""
    for chave, ctx in md.CONTEXTOS.items():
        assert ctx["rotulo"] and ctx["ajuda"], chave
        for v in ctx["variaveis"]:
            assert v["chave"] == v["chave"].lower(), (chave, v)
            assert md._VAR.fullmatch("{{%s}}" % v["chave"]), (chave, v)
            assert v["rotulo"] and v["exemplo"], (chave, v)


# --------------------------------------------------------------------- chave

def test_chave_sai_do_nome_sem_acento_nem_simbolo():
    assert md.slugificar("Cobrança — 1º aviso") == "cobranca-1o-aviso"
    assert md.slugificar("  Freetime: fim do prazo  ") == "freetime-fim-do-prazo"


def test_nome_sem_letra_nem_numero_nao_vira_chave():
    with pytest.raises(md.ModeloInvalido, match="chave"):
        md.validar({"nome": "———", "contexto": "livre", "corpo": "oi"})


# --------------------------------------------------------------------- store

@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(md, "ESQUEMA", esquema_pg)
    return esquema_pg


def _novo(**troca) -> dict:
    base = {"nome": "Cobrança — 1º aviso", "contexto": "cobranca",
            "descricao": "Primeiro contato, tom amigável",
            "corpo": "Olá {{cliente}}, o título {{documento}} venceu em "
                     "{{vencimento}} ({{valor}})."}
    base.update(troca)
    return base


def test_grava_le_e_enriquece(esq):
    d = md.gravar(_novo(), usuario="ana@sulista")
    assert d["chave"] == "cobranca-1o-aviso"

    lido = md.obter("cobranca-1o-aviso")
    assert lido["nome"] == "Cobrança — 1º aviso"
    assert lido["variaveis"] == ["cliente", "documento", "vencimento", "valor"]
    assert "TUPY FUNDIÇÕES" in lido["previa"]      # prévia com os exemplos
    assert lido["criado_por"] == "ana@sulista"
    assert lido["ativo"] == 1


def test_chave_repetida_e_recusada_com_nome_proprio(esq):
    md.gravar(_novo(), usuario="ana@sulista")
    with pytest.raises(md.ModeloInvalido, match="Já existe"):
        md.gravar(_novo(), usuario="ana@sulista")


def test_editar_o_proprio_modelo_nao_colide_com_ele_mesmo(esq):
    d = md.gravar(_novo(), usuario="ana@sulista")
    d2 = md.gravar(_novo(corpo="Olá {{cliente}}, tudo bem?"),
                   usuario="bruno@sulista", modelo_id=d["id"])
    assert d2["id"] == d["id"]
    assert md.obter(d["chave"])["atualizado_por"] == "bruno@sulista"


def test_renomear_nao_muda_a_chave_quando_ela_e_informada(esq):
    """A chave é o contrato com quem chama o modelo. Renomear é cosmético;
    trocar a chave é mudança de contrato, e só acontece de propósito."""
    d = md.gravar(_novo(), usuario="ana@sulista")
    md.gravar(_novo(nome="Cobrança — aviso amigável", chave=d["chave"]),
              usuario="ana@sulista", modelo_id=d["id"])
    atual = md.obter(d["chave"])
    assert atual is not None and atual["nome"] == "Cobrança — aviso amigável"


def test_listar_filtra_por_contexto_e_por_ligado(esq):
    """Conta o DELTA, não o total.

    O schema nasce com modelos SEMEADOS por migration (hoje o do prazo de
    indicação da Smartec), e um teste que espera número absoluto quebra a cada
    seed novo — sem que a listagem tenha nada de errado. O que ele precisa
    provar é o filtro, e filtro se prova pela diferença.
    """
    antes = len(md.listar())
    antes_ativos = len(md.listar(so_ativos=True))
    antes_livre = len(md.listar(contexto="livre"))

    md.gravar(_novo(), usuario="a")
    md.gravar(_novo(nome="Boas-vindas", contexto="livre",
                    corpo="Olá! Somos a Sulista.", ativo=0), usuario="a")

    assert len(md.listar()) - antes == 2
    # o segundo nasceu desligado, então só um entra no filtro de ativos
    assert len(md.listar(so_ativos=True)) - antes_ativos == 1
    assert len(md.listar(contexto="livre")) - antes_livre == 1


def test_excluir_devolve_o_que_sumiu_para_a_auditoria(esq):
    d = md.gravar(_novo(), usuario="a")
    apagado = md.excluir(d["id"])
    assert apagado["chave"] == d["chave"] and apagado["nome"]
    assert md.obter(d["chave"]) is None
    assert md.excluir(d["id"]) is None
