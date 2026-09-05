# -*- coding: utf-8 -*-
"""O schema do módulo próprio de pneus: o que ele PROÍBE.

Estes guards não conferem que as tabelas existem — conferem as regras que o
schema carrega, porque é delas que o módulo depende quando a Prolog for
desligada e não houver mais uma segunda fonte para conferir contra.

O EVENTO É A VERDADE. `pne_evento` é append-only e conta a história; o estado
em `pne_pneu` é projeção, para a tela não reprojetar 8.572 históricos a cada
abertura. Mesmo padrão do `audit_log` (imutável) com `aud_sessoes` (linha
viva). Se os dois discordarem, quem manda é o evento.
"""
from __future__ import annotations

import pytest

from api import pglocal


def _exec(esquema: str, sql: str, params=None):
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + esquema)
        cur.execute(sql, params or ())
        try:
            return cur.fetchall()
        except Exception:
            return None


def test_as_tabelas_do_modulo_existem(esquema_pg):
    linhas = _exec(esquema_pg, """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_name LIKE 'pne_%%'
        ORDER BY 1""", (esquema_pg,))
    nomes = {r["table_name"] for r in linhas}
    # A LISTA E EXATA de proposito: tabela nova no modulo acende aqui, e a
    # conversa acontece na revisao. `pne_motivo` entrou em 05/09/2026 com as
    # tabelas de dominio da Prolog (motivos de descarte) — sem ela,
    # `pne_evento.motivo` fica sendo um codigo que so a Prolog sabe ler, e o
    # objetivo declarado e que um dia ela nao esteja mais la.
    assert nomes == {"pne_diagrama", "pne_evento", "pne_inspecao",
                     "pne_modelo", "pne_motivo", "pne_pneu", "pne_sync",
                     "pne_veiculo", "pne_vida"}


def test_o_status_do_pneu_e_fechado(esquema_pg):
    """Status livre vira dez grafias da mesma coisa e nenhum filtro funciona."""
    _exec(esquema_pg, "INSERT INTO pne_pneu (serie, status) VALUES ('A1','rodando')")
    with pytest.raises(Exception):
        _exec(esquema_pg,
              "INSERT INTO pne_pneu (serie, status) VALUES ('A2','RODANDO')")


def test_o_tipo_de_evento_e_fechado(esquema_pg):
    """Movimentação com tipo livre não se agrega: 'instalou', 'instalacao' e
    'INSTALAÇÃO' viram três movimentos diferentes no mesmo relatório."""
    _exec(esquema_pg, "INSERT INTO pne_pneu (id, serie) VALUES (1,'A1')")
    _exec(esquema_pg, """
        INSERT INTO pne_evento (pneu_id, tipo, ocorrido_em, origem)
        VALUES (1,'instalacao', now(), 'cortex')""")
    with pytest.raises(Exception):
        _exec(esquema_pg, """
            INSERT INTO pne_evento (pneu_id, tipo, ocorrido_em, origem)
            VALUES (1,'trocou', now(), 'cortex')""")


def test_a_origem_do_evento_e_declarada(esquema_pg):
    """Sem esta coluna não dá para saber, daqui a dois anos, qual pedaço da
    história veio importado da Prolog e qual foi lançado no CÓRTEX."""
    _exec(esquema_pg, "INSERT INTO pne_pneu (id, serie) VALUES (1,'A1')")
    with pytest.raises(Exception):
        _exec(esquema_pg, """
            INSERT INTO pne_evento (pneu_id, tipo, ocorrido_em, origem)
            VALUES (1,'instalacao', now(), 'planilha')""")


def test_a_sincronizacao_nao_duplica_o_mesmo_evento_da_prolog(esquema_pg):
    """A coleta é retomável e roda de novo em cima do que já trouxe. Sem a
    unicidade, cada passada somaria a história outra vez — e o km da vida, que
    sai da diferença entre eventos, dobraria em silêncio."""
    _exec(esquema_pg, "INSERT INTO pne_pneu (id, serie) VALUES (1,'A1')")
    _exec(esquema_pg, """
        INSERT INTO pne_evento (pneu_id, tipo, ocorrido_em, origem, prolog_id)
        VALUES (1,'instalacao', now(), 'prolog', 'REL-1')""")
    with pytest.raises(Exception):
        _exec(esquema_pg, """
            INSERT INTO pne_evento (pneu_id, tipo, ocorrido_em, origem, prolog_id)
            VALUES (1,'remocao', now(), 'prolog', 'REL-1')""")


def test_o_mesmo_pneu_nao_entra_duas_vezes_pela_prolog(esquema_pg):
    _exec(esquema_pg, "INSERT INTO pne_pneu (serie, prolog_id) VALUES ('A1','T-9')")
    with pytest.raises(Exception):
        _exec(esquema_pg,
              "INSERT INTO pne_pneu (serie, prolog_id) VALUES ('A2','T-9')")


def test_a_vida_e_unica_por_pneu(esquema_pg):
    """'Recapagem 2' só existe uma vez por carcaça. Duas linhas com o mesmo
    número dobrariam o custo da vida e derrubariam o CPK pela metade."""
    _exec(esquema_pg, "INSERT INTO pne_pneu (id, serie) VALUES (1,'A1')")
    _exec(esquema_pg, "INSERT INTO pne_vida (pneu_id, numero) VALUES (1, 2)")
    with pytest.raises(Exception):
        _exec(esquema_pg, "INSERT INTO pne_vida (pneu_id, numero) VALUES (1, 2)")


def test_o_evento_guarda_o_km_do_veiculo_e_aceita_vazio(esquema_pg):
    """O km da vida sai da diferença entre instalação e remoção. Quando
    ninguém anotou o odômetro, o campo fica NULO — e nulo tem de continuar
    nulo, nunca virar zero, senão a conta vira 'rodou nada' em vez de 'não
    sabemos quanto rodou'."""
    _exec(esquema_pg, "INSERT INTO pne_pneu (id, serie) VALUES (1,'A1')")
    _exec(esquema_pg, """
        INSERT INTO pne_evento (pneu_id, tipo, ocorrido_em, km_veiculo)
        VALUES (1,'instalacao', now(), NULL)""")
    r = _exec(esquema_pg,
              "SELECT km_veiculo FROM pne_evento WHERE pneu_id = 1")
    assert r[0]["km_veiculo"] is None
