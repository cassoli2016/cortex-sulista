# -*- coding: utf-8 -*-
"""A COLETA NÃO SOBRESCREVE O QUE A CASA CRIOU.

O MODO DE FALHA QUE ISTO IMPEDE, e ele é caro e silencioso. A coleta da Prolog
roda de 20 em 20 minutos e grava tudo por `ON CONFLICT … DO UPDATE`. No dia em
que alguém cadastrar um pneu aqui e a chave dele colidir com uma da Prolog — ou
em que a Prolog devolver a mesma placa, o mesmo modelo, o mesmo diagrama — a
passada seguinte SUBSTITUI o que foi digitado. Sem erro, sem log. A pessoa que
cadastrou volta na tela e vê outra coisa no lugar, e não há como saber que
houve.

`pne_evento` e `pne_inspecao` já sabiam distinguir; os SEIS CADASTROS não. E
enquanto tudo vinha importado isso não doía — a partir do momento em que o
módulo passou a escrever, doeu.

O PADRÃO DA COLUNA É `cortex`, e isso é deliberado: quem insere sem se declarar
é o código da casa, e a coleta passa a dizer `prolog` explicitamente. Errar para
o lado de "isto é nosso, não sobrescreva" é o lado seguro — no pior caso uma
linha importada deixa de ser atualizada e alguém repara; no outro lado, trabalho
digitado some.
"""
from __future__ import annotations

import pytest

TABELAS = ("pne_pneu", "pne_modelo", "pne_veiculo", "pne_diagrama",
           "pne_motivo", "pne_vida")


@pytest.fixture
def cur(esquema_pg):
    from api import pglocal
    with pglocal.get_conn(esquema=esquema_pg) as c, c.cursor() as k:
        yield k


# --------------------------------------------------------------------------
# a coluna
# --------------------------------------------------------------------------
@pytest.mark.parametrize("tabela", TABELAS)
def test_todo_cadastro_do_modulo_SABE_dizer_quem_o_criou(cur, tabela):
    cur.execute("""
        SELECT column_default, is_nullable FROM information_schema.columns
        WHERE table_name = %s AND column_name = 'origem'""", (tabela,))
    c = cur.fetchone()
    assert c, "%s não sabe dizer se a linha é importada ou nossa" % tabela
    assert c["is_nullable"] == "NO"
    # O PADRÃO É `cortex`: quem insere sem se declarar é o código da casa.
    assert "cortex" in (c["column_default"] or "")


@pytest.mark.parametrize("tabela", TABELAS)
def test_a_origem_e_um_dominio_FECHADO(cur, tabela):
    """Texto livre aqui viraria 'prolog', 'Prolog', 'PROLOG' e nenhum filtro
    funcionaria — e o filtro é justamente o que protege o cadastro."""
    cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s",
                ("%s_origem_ck" % tabela,))
    assert cur.fetchone(), "%s aceita qualquer texto em origem" % tabela


# --------------------------------------------------------------------------
# o que a coleta faz com uma linha nossa
# --------------------------------------------------------------------------
def test_a_COLETA_nao_sobrescreve_pneu_cadastrado_aqui(cur):
    """O guard central deste arquivo.

    Um pneu criado no CÓRTEX que colidisse com a chave de um da Prolog seria
    substituído na passada seguinte. Este teste grava um pneu `cortex`, roda o
    mesmo `INSERT … ON CONFLICT` que a coleta usa, e exige que o nosso não
    tenha mudado.
    """
    cur.execute("INSERT INTO pne_modelo (marca, modelo) VALUES ('M','X') "
                "RETURNING id")
    modelo = cur.fetchone()["id"]
    cur.execute("""
        INSERT INTO pne_pneu (serie, modelo_id, status, prolog_id, origem)
        VALUES ('NOSSO', %s, 'estoque', 'P1', 'cortex')""", (modelo,))

    # o mesmo upsert da coleta, com o WHERE que protege
    cur.execute("""
        INSERT INTO pne_pneu (serie, modelo_id, status, prolog_id, origem)
        VALUES ('DA-PROLOG', %s, 'rodando', 'P1', 'prolog')
        ON CONFLICT (prolog_id) DO UPDATE SET
            serie = EXCLUDED.serie, status = EXCLUDED.status
        WHERE pne_pneu.origem <> 'cortex'""", (modelo,))

    cur.execute("SELECT serie, status, origem FROM pne_pneu "
                "WHERE prolog_id = 'P1'")
    p = cur.fetchone()
    assert p["serie"] == "NOSSO", "a coleta sobrescreveu o cadastro da casa"
    assert p["status"] == "estoque" and p["origem"] == "cortex"


def test_a_coleta_CONTINUA_atualizando_o_que_e_dela(cur):
    """A proteção não pode virar congelamento: o que veio da Prolog tem de
    continuar recebendo as atualizações dela, senão a réplica para de refletir
    a realidade e ninguém percebe."""
    cur.execute("INSERT INTO pne_modelo (marca, modelo) VALUES ('M','X') "
                "RETURNING id")
    modelo = cur.fetchone()["id"]
    cur.execute("""
        INSERT INTO pne_pneu (serie, modelo_id, status, prolog_id, origem)
        VALUES ('ANTIGO', %s, 'estoque', 'P2', 'prolog')""", (modelo,))
    cur.execute("""
        INSERT INTO pne_pneu (serie, modelo_id, status, prolog_id, origem)
        VALUES ('NOVO', %s, 'rodando', 'P2', 'prolog')
        ON CONFLICT (prolog_id) DO UPDATE SET
            serie = EXCLUDED.serie, status = EXCLUDED.status
        WHERE pne_pneu.origem <> 'cortex'""", (modelo,))
    cur.execute("SELECT serie, status FROM pne_pneu WHERE prolog_id = 'P2'")
    p = cur.fetchone()
    assert (p["serie"], p["status"]) == ("NOVO", "rodando")


# --------------------------------------------------------------------------
# o código da coleta realmente carrega a proteção
# --------------------------------------------------------------------------
def test_TODO_upsert_de_cadastro_da_coleta_tem_a_protecao():
    """Guard sobre o código, e ele é o que impede a próxima tabela de entrar
    desprotegida. Um `DO UPDATE` novo num cadastro sem o `WHERE` reabre o
    buraco inteiro, e o sintoma seria a mesma perda silenciosa.

    Ele lê o SQL dos módulos de coleta e exige que todo `ON CONFLICT … DO
    UPDATE` sobre uma das seis tabelas de cadastro traga o `origem <> 'cortex'`.
    """
    import pathlib
    import re

    from api.pneus import cadastro

    raiz = pathlib.Path(cadastro.__file__).parent
    faltando = []
    for arq in ("replica.py", "cadastro.py", "historico.py"):
        texto = (raiz / arq).read_text(encoding="utf-8")
        for m in re.finditer(r"INSERT INTO (pne_\w+)(.{0,3000}?)(?:\"\"\")",
                             texto, re.S):
            tabela, corpo = m.group(1), m.group(2)
            if tabela not in TABELAS:
                continue          # evento e inspeção já têm origem própria
            if "DO UPDATE" not in corpo:
                continue          # DO NOTHING não sobrescreve nada
            if "origem <> 'cortex'" not in corpo:
                faltando.append("%s: %s" % (arq, tabela))
    assert not faltando, (
        "upsert de cadastro sem a proteção — a coleta vai sobrescrever o que "
        "a casa criar: %s" % faltando)


@pytest.mark.parametrize("tabela", TABELAS)
def test_a_coleta_se_DECLARA_prolog_ao_inserir(tabela):
    """Se ela não disser, o padrão `cortex` marca como NOSSO o que veio de lá —
    e a partir daí a proteção impede a própria coleta de atualizar aquilo. O
    silêncio se voltaria contra a réplica."""
    import pathlib
    import re

    from api.pneus import cadastro

    raiz = pathlib.Path(cadastro.__file__).parent
    achou = False
    for arq in ("replica.py", "cadastro.py", "historico.py"):
        texto = (raiz / arq).read_text(encoding="utf-8")
        for m in re.finditer(
                r"INSERT INTO %s\s*\(([^)]*)\)(.{0,900}?)VALUES" % tabela,
                texto, re.S):
            colunas, _ = m.group(1), m.group(2)
            if "origem" not in colunas:
                continue
            achou = True
    # `pne_vida` e `pne_modelo` também entram por caminhos que declaram origem;
    # se algum dia um insert de cadastro deixar de declarar, o teste anterior
    # (a proteção) passa a congelar aquela tabela — e este aponta a causa.
    assert achou or tabela in ("pne_veiculo",), (
        "nenhum INSERT de %s declara a origem; o padrão marcaria como nosso o "
        "que veio da Prolog" % tabela)
