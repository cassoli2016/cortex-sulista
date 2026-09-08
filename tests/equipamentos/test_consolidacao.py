# -*- coding: utf-8 -*-
"""A precedência — a regra difícil do cadastro, testada sem banco nenhum.

`resolver()` e `divergencias()` são funções puras de propósito: é isso que
permite exercitar aqui cada decisão que custa caro se estiver errada, com
dicionários, sem ERP no ar e sem gastar consulta paga.
"""
from __future__ import annotations

from decimal import Decimal

from api.equipamentos import consolidacao as cons
from api.equipamentos.campos import CAMPOS, POR_NOME


def _fontes(**kw):
    """`_fontes(erp={"marca": "X"})` → o formato que a consolidação recebe."""
    return {f: {"campos": c} for f, c in kw.items()}


# ─────────────────────────────────────────────────────── quem ganha de quem

def test_o_detran_vence_o_erp_no_chassi():
    """O ERP tem chassi em quase 100% da frota — mas quem digitou foi gente.

    Preenchido e correto são perguntas diferentes, e só o Detran responde a
    segunda. Se o ERP vencesse aqui, a integração inteira não mudaria um
    número e o dinheiro da consulta seria gasto para nada.
    """
    v, o = cons.resolver(_fontes(erp={"chassi": "ERRADO123"},
                                 **{"smartec": {"chassi": "CERTO999"}}))
    assert v["chassi"] == "CERTO999"
    assert o["chassi"] == "smartec"


def test_o_erp_vence_o_detran_no_vinculo():
    """Próprio, agregado ou terceiro é contrato — o Detran não sabe disso."""
    v, o = cons.resolver(_fontes(erp={"vinculo": "agregado"},
                                 **{"smartec": {"vinculo": "proprio"}}))
    assert v["vinculo"] == "agregado"
    assert o["vinculo"] == "erp"


def test_a_mao_vence_tudo():
    """Sem isto o cadastro seria um espelho: a próxima coleta desfaria a
    correção, e quem corrigiu aprenderia numa semana que corrigir não adianta.
    """
    v, o = cons.resolver(
        _fontes(erp={"marca": "MBENZ"}, **{"smartec": {"marca": "VOLVO"}}),
        {"marca": "MERCEDES-BENZ"})
    assert v["marca"] == "MERCEDES-BENZ"
    assert o["marca"] == "manual"


# ───────────────────────────────────────────── vazio não vence (o mais caro)

def test_fonte_com_campo_vazio_nao_apaga_a_fonte_seguinte():
    """A regra que impede o cadastro de PIORAR a cada coleta.

    Se vazio vencesse, a Smartec devolvendo `cor: ""` apagaria a cor que a
    Smartec tem — em silêncio, e a cada coleta nova.
    """
    v, o = cons.resolver(_fontes(smartec={"cor": ""}, erp={"cor": "BRANCA"}))
    assert v["cor"] == "BRANCA"
    assert o["cor"] == "erp"


def test_zero_e_false_NAO_sao_vazio():
    """`0` e `False` são respostas, não ausências.

    Um `licenciado=False` tratado como vazio viraria `None`, e a tela leria
    "não consultado" — o oposto do que se precisa saber sobre um veículo NÃO
    licenciado.
    """
    v, _ = cons.resolver(_fontes(smartec={"tem_restricao": False}))
    assert v["tem_restricao"] is False

    v2, _ = cons.resolver(_fontes(erp={"tara_kg": 0}))
    assert v2["tara_kg"] == 0


# ────────────────────────────────────────────────────────────── conversões

def test_o_decimal_brasileiro_nao_vira_numero_mil_vezes_menor():
    """`1.234,56` lido como `1.234` seria plausível — e é o erro mais caro.

    Valor FIPE mil vezes menor não parece absurdo numa tabela de veículos
    antigos, e ninguém notaria.
    """
    v, _ = cons.resolver(_fontes(erp={"fipe_valor": "1.234,56"}))
    assert v["fipe_valor"] == Decimal("1234.56")


def test_valor_que_nao_converte_e_ausencia_e_nao_derruba_a_placa():
    """Texto onde se espera número não pode virar erro de transação.

    Uma placa com um campo estragado derrubaria a consolidação das 1.446.
    """
    v, o = cons.resolver(_fontes(**{"smartec": {"ano_fabricacao": "sem informação"}},
                                 erp={"ano_fabricacao": 2019}))
    assert v["ano_fabricacao"] == 2019
    assert o["ano_fabricacao"] == "erp"


def test_data_em_formato_desconhecido_e_ausencia_e_nunca_data_errada():
    """Data errada num vencimento de licenciamento é pior que data nenhuma."""
    v, _ = cons.resolver(_fontes(smartec={"cronotacografo_vencimento": "31 de março"}))
    assert "cronotacografo_vencimento" not in v


# ─────────────────────────────────────────────────────────── divergências

def test_a_divergencia_e_registrada_mesmo_com_a_precedencia_decidindo():
    """Desempatar e calar esconderia exatamente o que se foi buscar."""
    d = cons.divergencias(_fontes(erp={"chassi": "AAA"},
                                  **{"smartec": {"chassi": "BBB"}}))
    campos = {x["campo"] for x in d}
    assert "chassi" in campos
    achado = [x for x in d if x["campo"] == "chassi"][0]
    assert achado["vence"] == "smartec"
    assert {v["fonte"] for v in achado["valores"]} == {"erp", "smartec"}


def test_caixa_e_espaco_NAO_sao_divergencia():
    """'VOLVO' e 'Volvo ' são o mesmo fabricante.

    Acusá-los encheria a lista de ruído até ninguém abrir mais — e uma lista
    que erra é o mesmo que lista nenhuma.
    """
    d = cons.divergencias(_fontes(erp={"marca": "VOLVO"},
                                  **{"smartec": {"marca": "Volvo "}}))
    assert not [x for x in d if x["campo"] == "marca"]


def test_ausencia_NAO_e_divergencia():
    """A Smartec não opinar sobre um campo não é discordar dele."""
    d = cons.divergencias(_fontes(erp={"vinculo": "proprio"},
                                  **{"smartec": {"marca": "VOLVO"}}))
    assert not [x for x in d if x["campo"] == "vinculo"]


# ──────────────────────────────────────────────── integridade do catálogo

def test_toda_precedencia_nomeia_fonte_conhecida():
    """Fonte com nome errado não levanta erro: o campo fica vazio para sempre.

    É exatamente o modo de falha que a `categoria` já teve nesta entrega —
    nasceu com precedência sem o `erp`, e as 1.446 linhas saíram com a coluna
    nula sem um único erro no caminho.
    """
    from api.equipamentos.campos import FONTES
    for c in CAMPOS:
        desconhecidas = set(c["precedencia"]) - set(FONTES)
        assert not desconhecidas, (
            f"campo {c['nome']} aponta para fonte inexistente: {desconhecidas}")


def test_todo_campo_do_catalogo_e_coluna_no_banco():
    """O catálogo e a migration não podem divergir.

    A consolidação monta o INSERT a partir do catálogo: um campo que não seja
    coluna derruba a gravação inteira, e uma coluna sem campo nunca é
    preenchida. A lista sai do DISCO, do próprio SQL, e não de uma segunda
    lista escrita à mão que envelheceria calada.
    """
    from pathlib import Path
    import re
    pasta = Path(__file__).resolve().parents[2] / "sql" / "cortex"

    # A tabela nasce na 0070 e as migrations seguintes a ALTERAM. Ler so a
    # 0070 daria um guard que reprova todo campo novo -- e ler so o ALTER
    # daria um que aprova qualquer coisa. A varredura junta as duas coisas,
    # e sai do DISCO: `glob` pega a migration que ainda nem existe.
    sql = (pasta / "0070_equipamentos.sql").read_text(encoding="utf-8")
    corpo = sql.split("CREATE TABLE IF NOT EXISTS eqp_equipamento")[1]
    colunas = set(re.findall(r"^\s{2}(\w+)\s+\w", corpo.split(");")[0], re.M))

    for arq in sorted(pasta.glob("0*.sql")):
        # COMENTARIO FORA ANTES DE VARRER. Esta linha nasceu de um defeito
        # real: um `;` DENTRO de um comentario cortava o bloco ALTER no meio,
        # e os DROP seguintes ficavam invisiveis para o guard -- que entao
        # acusava como orfas colunas que ja tinham sido removidas.
        # Regex sobre SQL le CODIGO, nunca prosa.
        texto = re.sub(r"--.*", "", arq.read_text(encoding="utf-8"))
        for bloco in re.findall(
                r"ALTER TABLE eqp_equipamento(.*?);", texto, re.S):
            colunas |= set(re.findall(
                r"ADD COLUMN IF NOT EXISTS\s+(\w+)", bloco))
            colunas -= set(re.findall(
                r"DROP COLUMN IF EXISTS\s+(\w+)", bloco))

    assert len(colunas) > 20, f"varredura do SQL achou so {len(colunas)} colunas"
    faltando = {c["nome"] for c in CAMPOS} - colunas
    assert not faltando, f"campos sem coluna na migration: {sorted(faltando)}"

    # E O ESPELHO: coluna que nenhum campo do catalogo preenche e coluna
    # eternamente vazia. Ela se preenche ou se remove -- foi por isso que
    # `fipe_codigo` e `fipe_referencia` sairam na 0071.
    estruturais = {"placa", "origem", "criado_em", "atualizado_em"}
    orfas = colunas - {c["nome"] for c in CAMPOS} - estruturais
    assert not orfas, f"colunas que nenhum campo preenche: {sorted(orfas)}"


def test_campo_so_erp_e_o_que_realmente_so_o_erp_preenche():
    """`so_erp` é derivado do catálogo, não de uma segunda lista.

    Se um campo ganhar outra fonte e continuar marcado `so_erp`, a tela
    mostraria como pendência da independência algo que já foi resolvido — e
    pendência falsa ensina a ignorar a lista.
    """
    for c in CAMPOS:
        automaticas = [f for f in c["precedencia"] if f != "manual"]
        if c["so_erp"]:
            assert automaticas == ["erp"], (
                f"{c['nome']} esta marcado so_erp mas tem outras fontes: "
                f"{automaticas}")
        elif automaticas == ["erp"]:
            raise AssertionError(
                f"{c['nome']} so tem o ERP como fonte e NAO esta marcado "
                f"so_erp — ele sumiria da lista de pendencias da independencia")
