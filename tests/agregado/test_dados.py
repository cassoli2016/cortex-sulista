# -*- coding: utf-8 -*-
"""As consultas do app do agregado: o que elas NÃO podem trazer.

Este arquivo guarda três promessas escritas no contrato do módulo
(`api/agregado/__init__.py`), e cada uma delas falha em SILÊNCIO se quebrar —
a tela responde, bonita, com o dado errado:

1. o que o CLIENTE pagou à Sulista nunca sai (a margem da casa não é assunto
   do fornecedor);
2. o escopo é o dono, e ele entra no `WHERE` de toda consulta;
3. o documento do dono (CPF, para 80 dos 201) não vai para payload nenhum.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from api.agregado import dados

FONTE = Path(dados.__file__).read_text(encoding="utf-8")


def _sqls() -> dict[str, str]:
    """As constantes SQL do módulo, colhidas do DISCO por `ast`.

    Varredura, e não lista escrita à mão: lista à mão envelhece no dia em que
    alguém acrescenta uma consulta — e é justamente a consulta nova que ninguém
    conferiu. O `assert` contra o vazio existe porque varredura que não acha
    nada passa por vacuidade.
    """
    arvore = ast.parse(FONTE)
    achados = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Name):
            nome = no.targets[0].id
            if nome.endswith("_SQL"):
                achados[nome] = getattr(dados, nome)
    assert len(achados) >= 8, achados.keys()
    return achados


@pytest.mark.parametrize("nome", sorted(_sqls()))
def test_nenhuma_consulta_traz_a_receita_da_casa(nome):
    """`valorfretecompra` é o que a Sulista PAGA ao dono (dele, pode sair);
    `valorfrete` é o que o cliente pagou à Sulista (não pode).

    O GUARD PRECISA SEPARAR OS DOIS, e é por isso que ele não é um `in`: a
    primeira versão desta conferência procurava "p.valorfrete" e acusava
    `p.valorfretecompra` — um falso positivo que, se tivesse sido "consertado"
    afrouxando a regra, deixaria passar o de verdade.
    """
    sql = _sqls()[nome]
    assert not re.search(r"valorfrete(?!compra)", sql), nome
    for proibido in ("valorfretecalculado", "margem", "resultado"):
        assert proibido not in sql.lower(), (nome, proibido)


@pytest.mark.parametrize("nome", sorted(_sqls()))
def test_toda_consulta_e_presa_ao_dono_ou_as_placas_dele(nome):
    """Consulta sem escopo é consulta que responde a qualquer um.

    Ou ela filtra pelo código do dono (`%(cod)s`), ou pelas placas que saíram
    de `veiculos()` (`%(placas)s`) — e as placas também vêm do dono, nunca do
    navegador.
    """
    sql = _sqls()[nome]
    assert ("%(cod)s" in sql) or ("%(placas)s" in sql), nome


def test_o_detalhe_do_acerto_poe_o_dono_no_where_junto_do_numero():
    """Ler e descartar não é recusar: a diferença entre "não mostra" e "não
    lê" é a única que vale quando o dado é o extrato financeiro de outro."""
    for nome in ("ACERTO_RECEITA_SQL", "ACERTO_DESPESA_SQL",
                 "ACERTO_ADIANT_SQL", "ACERTO_DESCONTO_SQL"):
        sql = getattr(dados, nome)
        assert "a.numero = %(numero)s" in sql, nome
        assert "cnpjcpfcodigoveiculo, '')) = %(cod)s" in sql, nome


def test_nenhuma_funcao_publica_recebe_o_dono_como_parametro():
    """O escopo vem da SESSÃO. Uma função que aceita o dono como argumento é
    uma função que um dia é chamada com o dono errado — e o defeito é mudo."""
    arvore = ast.parse(FONTE)
    publicas = [n for n in arvore.body
                if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
    assert {f.name for f in publicas} >= {
        "veiculos", "acertos", "acerto_detalhe", "viagens",
        "abastecimentos", "lancamentos", "ocorrencias", "resumo"}
    for f in publicas:
        args = [a.arg for a in f.args.args]
        assert args and args[0] == "sess", (f.name, args)
        for proibido in ("cod", "proprietario", "dono", "codigo", "placa", "placas"):
            assert proibido not in args, (f.name, proibido)


def test_a_ocorrencia_mostrada_e_motivo_e_nao_o_ciclo_do_sac():
    """São 110 mil ocorrências em 12 meses nas placas de agregado, quase todas
    do ciclo do SAC (chegada, saída, em viagem). Listá-las esconderia o que o
    dono precisa ver — e o corte está escrito numa constante, não espalhado."""
    assert "BETWEEN 425 AND 456" in dados.OCORRENCIAS_MOTIVO
    assert "271" in dados.OCORRENCIAS_MOTIVO
    for codigo in ("394", "395", "396", "397", "400", "401"):
        assert codigo not in dados.OCORRENCIAS_SQL, codigo


def test_a_modalidade_e_agregado_e_esta_escrita_uma_vez_so():
    """`AGR` é agregado; `TER` (terceiro) é outro universo e ficou de fora por
    decisão de quem opera (16/09/2026)."""
    assert dados.UTILIZACAO == "AGR"
    assert f"= '{dados.UTILIZACAO}'" in dados.VEICULOS_SQL
    assert "'TER'" not in FONTE


def test_o_teto_de_linhas_e_dito_e_nao_so_aplicado():
    """Top-N sem contador vira total falso: quem corta diz quanto cortou."""
    assert dados.MAX_LINHAS >= 100
    for chave in ("acertos", "viagens", "abastecimentos", "lancamentos", "ocorrencias"):
        assert f'"{chave}": linhas[:MAX_LINHAS]' in FONTE or \
               f'"{chave}": linhas[:MAX_LINHAS],' in FONTE, chave
    assert FONTE.count('"mostrados"') >= 5 and FONTE.count('"total"') >= 5
