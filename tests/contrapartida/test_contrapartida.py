# tests/contrapartida/test_contrapartida.py
"""CT-e de contrapartida: o que NAO pode ser somado e o que NAO pode ser feito.

O risco desta tela nao e errar um total - e juntar duas populacoes fiscais
diferentes. O TAC (pessoa fisica) nao emite CT-e por forca da Lei 11.442:
somar os 6.020 CT-e dele aos 12.482 do PJ produziria um passivo 48% maior, com
documento que nao pode existir, e mandaria a operacao atras dele.
"""
from __future__ import annotations

import ast

from api.contrapartida import servico
from api.contrapartida.sql import (FROTA_AGR_SQL, PASSIVO_SQL,
                                   POR_AGREGADO_SQL, POR_MES_SQL)

TODAS = (POR_MES_SQL, POR_AGREGADO_SQL, FROTA_AGR_SQL, PASSIVO_SQL)


def test_sql_respeita_pg93_e_latin1():
    for sql in TODAS:
        assert "FILTER (WHERE" not in sql.upper()
        assert "percentile_cont" not in sql.lower()
        sql.encode("latin-1")


def test_classifica_por_TAMANHO_do_documento():
    """14 digitos = CNPJ (emite), 11 = CPF (nao emite). E o unico criterio
    disponivel: nao ha flag de "e TAC" no cadastro."""
    for sql in (POR_MES_SQL, POR_AGREGADO_SQL, FROTA_AGR_SQL, PASSIVO_SQL):
        assert "= 14 THEN 'pj'" in sql and "= 11 THEN 'tac'" in sql


def test_documento_fora_do_padrao_nao_vira_PJ_por_default():
    """Cair no 'pj' por omissao poria na fila de emissao alguem que talvez nao
    emita. O terceiro caso e explicito e sai num aviso proprio."""
    for sql in TODAS:
        assert "ELSE 'indefinido' END" in sql


def test_cancelado_fora_do_passivo():
    """Passivo que conta documento cancelado e passivo inventado."""
    for sql in TODAS:
        if "conhecimento" in sql:
            assert "coalesce(k.semaforo, 1) = 1" in sql
            assert "k.dtcancelamento IS NULL" in sql


def test_agregado_sem_cadastro_NAO_some_da_fila():
    """LEFT e nao INNER: sumir da fila por falta de cadastro esconderia
    exatamente o caso que precisa de acao."""
    assert "LEFT JOIN cadastro cd" in POR_AGREGADO_SQL


def test_traz_o_que_a_EMISSAO_exige():
    """RNTRC, IE e municipio ausentes viram rejeicao documento a documento -
    com 3 mil CT-e/mes, e o erro que para a operacao."""
    for campo in ("numerorntrc", "inscricaoestadual", "razaosocial", "cidade"):
        assert campo in POR_AGREGADO_SQL


# --- o servico --------------------------------------------------------------

def test_a_tela_e_SO_LEITURA():
    """Guarda de codigo (arvore sintatica, nao texto): emissao em nome de
    terceiro depende de procuracao, certificado e enquadramento fiscal, e
    nenhuma das tres e decisao de software."""
    with open(servico.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    nomes = {n.attr for n in ast.walk(arvore) if isinstance(n, ast.Attribute)}
    nomes |= {n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)}
    assert not (nomes & {"assinar", "transmitir", "emitir", "certificado",
                         "pfx", "sign", "post"})


def test_emitidas_e_zero_declarado_e_nao_calculado():
    """Zero por confirmacao da operacao, nao por consulta que devolveu vazio.
    A diferenca importa: consulta vazia pode ser bug."""
    with open(servico.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        src = f.read()
    assert '"emitidas": 0' in src


def test_pt_br_formata_SO_o_numero():
    """Aplicar replace(",", ".") na frase inteira comeu as virgulas do texto -
    a armadilha da substituicao em massa, em miniatura."""
    assert servico._br(108713961.0, 0) == "108.713.961"
    assert servico._br(1234.5) == "1.234,50"
    assert servico._br(0, 0) == "0"


def test_janela_endireita_e_inclui_o_dia_final():
    de, ate = servico._janela("2026-08-26", "2026-03-01")
    assert de == "2026-03-01" and ate == "2026-08-27"


# --- os avisos --------------------------------------------------------------

def _pj(n): return [{"documento": str(i), "nome": "X", "ie": "1",
                     "rntrc": "2", "cidade": "C"} for i in range(n)]


def test_avisa_SEMPRE_que_nada_foi_emitido():
    av = servico._avisos(_pj(3), [], [], [], [])
    assert any("Nenhuma contrapartida emitida" in a for a in av)


def test_aviso_do_TAC_explica_que_e_do_DOCUMENTO_e_nao_do_certificado():
    """O usuario disse ter certificado de todos. Para o TAC isso nao resolve:
    ele nao e sujeito passivo do CT-e."""
    av = servico._avisos(_pj(53), [{"documento": "1"}] * 30, [], [], [])
    texto = " ".join(av)
    assert "CIOT" in texto and "certificado" in texto


def test_passivo_historico_NAO_vira_fila_de_trabalho():
    """CT-e nao se emite retroativo: a SEFAZ recusa data fora da janela."""
    av = servico._avisos(_pj(1), [], [], [], [
        {"ano": "2025", "classe": "pj", "ctes": 34188, "valor": 108713961.0}])
    alvo = [a for a in av if "Passivo" in a][0]
    assert "108.713.961" in alvo and "retroativo" in alvo
    assert "34.188" in alvo


def test_pendencia_cadastral_nomeia_o_campo_que_falta():
    av = servico._avisos(_pj(1), [], [],
                         [{"documento": "9", "nome": "ACME", "falta": ["RNTRC"]}], [])
    assert any("ACME" in a and "RNTRC" in a for a in av)


# --- RBAC -------------------------------------------------------------------

def test_rota_registrada_e_restrita():
    from api.auth import ROTA_TELAS, TELAS
    assert "ctecp" in TELAS
    assert any(r[0] == "/api/fiscal/contrapartida" and "ctecp" in r[1]
               for r in ROTA_TELAS)
