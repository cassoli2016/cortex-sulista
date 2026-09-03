# -*- coding: utf-8 -*-
"""A aba "Excluídos" da DRE Gerencial.

Esta funcionalidade cria um jeito de MUDAR O RESULTADO PUBLICADO. Os guards
aqui são todos da mesma família: garantir que isso nunca seja silencioso, e
que a exclusão que alguém marcou realmente valha.
"""
from __future__ import annotations

import datetime as dt

import pytest

from api import dre_exclusoes as ex

LANC = {"grupo": 1, "empresa": 1, "reduzido": 411101, "sequencia": 10760535,
        "dtlancamento": "2026-07-28", "valor_debito": 12851.94,
        "valor_credito": None, "conta": "Diesel Frota",
        "agrupador": "CV - COMBUSTÍVEL", "historico": "Vlr Ref Oleo Diesel"}


# ------------------------------------------------------------------ o motivo

def test_sem_motivo_nao_exclui(esquema_pg):
    """Daqui a seis meses a pergunta não vai ser "o que saiu", vai ser "por
    quê" — e é a resposta disso que se perde primeiro."""
    for ruim in ("", "   ", "ok", "sim"):
        with pytest.raises(ex.MotivoObrigatorio):
            ex.marcar(LANC, ruim, "quem@sulista.com.br", esquema=esquema_pg)
    assert ex.listar(esquema=esquema_pg) == []


def test_sem_autor_nao_exclui(esquema_pg):
    with pytest.raises(ValueError):
        ex.marcar(LANC, "reclassificado no mês seguinte", "",
                  esquema=esquema_pg)


def test_o_motivo_e_o_autor_ficam_gravados(esquema_pg):
    r = ex.marcar(LANC, "  reclassificado   no mês seguinte  ",
                  "cristian@sulista.com.br", esquema=esquema_pg)
    assert r["motivo"] == "reclassificado no mês seguinte"   # espaços normalizados
    assert r["quem"] == "cristian@sulista.com.br"
    assert r["quando"] is not None


# ------------------------------------------------------------------- a chave

def test_a_chave_e_a_de_CINCO_colunas(esquema_pg):
    """Medido em 1.230.480 lançamentos de 12 meses: `sequencia` sozinha colide
    (1.210.855 distintas) e `(sequencia, data)` também. Excluir pela chave
    curta tiraria do resultado um lançamento que ninguém pediu."""
    assert ex.CHAVE == ("grupo", "empresa", "reduzido", "sequencia",
                        "dtlancamento")
    ex.marcar(LANC, "motivo suficiente", "a@b.c", esquema=esquema_pg)
    # mesma sequencia e data, EMPRESA diferente: é outro lançamento
    outro = {**LANC, "empresa": 2}
    ex.marcar(outro, "motivo suficiente", "a@b.c", esquema=esquema_pg)
    assert len(ex.listar(esquema=esquema_pg)) == 2


def test_lancamento_sem_chave_completa_e_recusado(esquema_pg):
    with pytest.raises(ValueError):
        ex.marcar({"grupo": 1, "empresa": 1}, "motivo suficiente", "a@b.c",
                  esquema=esquema_pg)


def test_marcar_duas_vezes_ATUALIZA_e_nao_duplica(esquema_pg):
    ex.marcar(LANC, "primeiro motivo", "a@b.c", esquema=esquema_pg)
    r = ex.marcar(LANC, "motivo corrigido", "b@b.c", esquema=esquema_pg)
    assert r["motivo"] == "motivo corrigido" and r["quem"] == "b@b.c"
    assert len(ex.listar(esquema=esquema_pg)) == 1


def test_desmarcar_devolve_o_lancamento(esquema_pg):
    ex.marcar(LANC, "motivo suficiente", "a@b.c", esquema=esquema_pg)
    assert ex.desmarcar(LANC, esquema=esquema_pg) is True
    assert ex.listar(esquema=esquema_pg) == []
    assert ex.desmarcar(LANC, esquema=esquema_pg) is False


# -------------------------------------------------------------------- o selo

def test_o_total_segue_a_convencao_da_DRE(esquema_pg):
    """`crédito − débito`, como a DRE inteira — para o selo dizer "o resultado
    seria X a mais" sem que alguém precise inverter de cabeça."""
    ex.marcar(LANC, "motivo suficiente", "a@b.c", esquema=esquema_pg)
    t = ex.total(esquema=esquema_pg)
    assert t["n"] == 1
    assert t["efeito"] == pytest.approx(-12851.94)


def test_o_total_respeita_o_periodo(esquema_pg):
    ex.marcar(LANC, "motivo suficiente", "a@b.c", esquema=esquema_pg)
    assert ex.total("2026-07-01", "2026-08-01", esquema=esquema_pg)["n"] == 1
    assert ex.total("2026-08-01", "2026-09-01", esquema=esquema_pg)["n"] == 0


# ------------------------------------------------------------------- o filtro

def test_sem_exclusao_o_filtro_e_VAZIO():
    """Uma cláusula com lista vazia é erro de sintaxe, e a DRE de quem nunca
    excluiu nada é o caso mais comum de todos."""
    assert ex.filtro_sql("l", 0) == ""


def test_o_filtro_usa_parametro_NOMEADO():
    """As consultas da DRE usam `%(de)s`; o psycopg não deixa misturar nomeado
    com posicional na mesma consulta."""
    sql = ex.filtro_sql("l", 3)
    assert sql.count("%(dre_excluidos)s") == 1
    # e NENHUM posicional: um `%s` solto aqui faria o psycopg recusar a
    # consulta inteira, e a DRE cairia no dia em que alguém excluísse algo
    assert "%s" not in sql.replace("%(dre_excluidos)s", "")


def test_o_filtro_NAO_usa_unnest_de_varias_colunas():
    """O AVA é PostgreSQL 9.3 e o `unnest` multi-coluna só existe do 9.4 em
    diante — funcionaria na bancada e falharia em produção."""
    assert "unnest(" not in ex.filtro_sql("l", 2).lower()


def test_a_data_entra_com_FORMATO_FIXO():
    """`dtlancamento::text` depende do DateStyle da sessão. No dia em que ele
    mudasse, o filtro pararia de casar SEM ERRO — a exclusão simplesmente
    deixaria de valer, que é a pior forma de falhar deste código."""
    assert "to_char(l.dtlancamento,'YYYY-MM-DD')" in ex.filtro_sql("l", 1)


def test_a_chave_de_texto_casa_com_o_que_o_sql_monta():
    c = (1, 1, 411101, 10760535, dt.date(2026, 7, 28))
    assert ex.chave_texto(c) == "1|1|411101|10760535|2026-07-28"


def test_os_PARAMS_saem_com_a_chave_inteira():
    """Guard escrito depois de um sabote passar batido: eu testava
    `chave_texto` isolada e nunca `filtro_params`, que é quem a DRE usa de
    verdade. Truncar a chave ali não derrubava teste nenhum — e uma chave
    curta casa com lançamentos que ninguém mandou excluir."""
    chs = [(1, 1, 411101, 10760535, dt.date(2026, 7, 28)),
           (1, 2, 411108, 10759786, dt.date(2026, 7, 22))]
    p = ex.filtro_params(chs)
    assert list(p) == ["dre_excluidos"]
    assert p["dre_excluidos"] == ["1|1|411101|10760535|2026-07-28",
                                  "1|2|411108|10759786|2026-07-22"]
    # cada chave tem as CINCO partes, sempre
    assert all(x.count("|") == 4 for x in p["dre_excluidos"])


def test_o_filtro_de_exclusao_entra_nas_TRES_consultas(esquema_pg):
    """Sem a âncora, `_com_exclusoes` LEVANTA em vez de devolver a consulta
    sem filtro: exclusão que não vale é pior que exclusão que falha, porque a
    DRE mostraria o número velho com cara de certo."""
    from api import queries

    chs = [(1, 1, 411101, 10760535, dt.date(2026, 7, 28))]
    for nome in ("DRE_AG_SQL", "DRE_AG_CONTA_SQL", "DRE_AJUSTADAS_SQL"):
        saida = queries._com_exclusoes(getattr(queries, nome), chs)
        assert "%(dre_excluidos)s" in saida, nome
    with pytest.raises(RuntimeError):
        queries._com_exclusoes("SELECT 1", chs)


def test_sem_exclusao_a_consulta_fica_INTACTA():
    from api import queries

    assert queries._com_exclusoes(queries.DRE_AG_SQL, []) is queries.DRE_AG_SQL


# -------------------------------------------------------------------- a busca

def test_a_busca_so_traz_conta_de_RESULTADO():
    """Mostrar aqui um lançamento que a DRE já ignora seria oferecer a exclusão
    de algo que não muda nada — e quem clicasse ficaria procurando o efeito."""
    import inspect

    fonte = inspect.getsource(ex.buscar)
    assert "p.estrutural ~ '^[34]'" in fonte


def test_a_busca_tem_TETO_e_ele_se_declara():
    """Lista cortada em silêncio faz quem procura concluir que o lançamento
    não existe."""
    import inspect

    fonte = inspect.getsource(ex.buscar)
    assert "BUSCA_LIMITE" in fonte and "truncou" in fonte


# --------------------------------------------------------------------- o RBAC

def test_a_permissao_de_excluir_e_SEPARADA_da_de_ler():
    """A DRE é aberta por várias pessoas e nem todas devem poder mexer no
    resultado publicado. Foi decisão de quem opera."""
    from api import auth

    assert "dreexc" in auth.TELAS
    rotas = dict(auth.ROTA_TELAS)
    assert rotas["/api/dre/exclusoes/marcar"] == frozenset({"dreexc"})
    assert rotas["/api/dre/exclusoes/remover"] == frozenset({"dreexc"})
    # LER é de quem abre a DRE: o número da tela depende disto, e esconder o
    # porquê de quem lê seria pior do que não ter a funcionalidade
    assert "dre" in rotas["/api/dre/exclusoes"]


def test_a_rota_especifica_vem_ANTES_da_generica():
    """Invertida a ordem, o prefixo genérico engoliria o específico e qualquer
    um que abre a DRE poderia excluir."""
    from api import auth

    rotas = [r for r, _ in auth.ROTA_TELAS]
    assert (rotas.index("/api/dre/exclusoes/marcar")
            < rotas.index("/api/dre/exclusoes"))


# ---------------------------------------------------------------- a tela diz

def test_a_dre_CARREGA_quanto_foi_excluido():
    """Um número que pode ser mexido sem aparecer não é um número, é uma
    opinião: o payload da DRE leva o selo."""
    from pathlib import Path

    # NAO `inspect.getsource(get_dre)`: a funcao e DECORADA (`@cached`), e o
    # getsource devolve o wrapper. Este teste passou verde um tempo so porque
    # o decorador estava deslocado por engano — verde pelo motivo errado.
    fonte = (Path(__file__).resolve().parents[1] / "api"
             / "queries.py").read_text(encoding="utf-8")
    assert '"excluidos": excluidos' in fonte
    assert "_chs = dre_exclusoes.chaves(" in fonte


def test_a_tela_mostra_o_selo_e_o_motivo():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert 'id="dre-selo"' in html
    assert "function dreSelo(" in html
    # A CHAMADA, não a definição. O primeiro jeito de escrever isto foi
    # `"dreSelo(d)" in html`, que casa com `function dreSelo(d)` — tirar a
    # chamada de dentro do `loadDre` não derrubava o teste, e o selo
    # simplesmente não apareceria.
    assert "renderDre(d); dreSelo(d);" in html, (
        "o selo precisa ser CHAMADO pelo loadDre, e não só existir")
    # o motivo aparece para quem só lê
    assert "x.motivo" in html
