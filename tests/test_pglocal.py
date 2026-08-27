"""Camada do banco de escrita (PostgreSQL local) e o runner de migrations.

O que se protege aqui, na ordem em que dói:

1. **A senha não vaza.** O diagnóstico vai para uma tela e o erro vai para o
   log: nem um nem outro pode carregar o conteúdo do `.env`.
2. **Schema de produção não é apagável por engano.** `apagar_esquema()` existe
   para teste; um argumento errado apagaria tudo.
3. **A migration é ordenada e idempotente.** Rodar duas vezes é o modo normal
   de usar depois de um `git pull`.

Os testes que precisam de banco vivo se pulam sozinhos dizendo por quê — ver
`tests/conftest.py` e `docs/MIGRACAO_POSTGRES.md`, seção 5.
"""
from __future__ import annotations

import pytest

from api import migracoes, pglocal

SENHA = "senha-de-teste-que-nao-pode-vazar"


@pytest.fixture
def com_senha(monkeypatch):
    monkeypatch.setenv("CORTEX_PG_PASSWORD", SENHA)
    monkeypatch.setenv("CORTEX_PG_HOST", "127.0.0.1")
    monkeypatch.setenv("CORTEX_PG_PORT", "5432")
    monkeypatch.setenv("CORTEX_PG_DB", "cortex")


# ----------------------------------------------------------------- segredo

def test_onde_diz_o_destino_sem_usuario_nem_senha(com_senha):
    """A tela de Saúde precisa dizer contra o que está falando — e só isso."""
    onde = pglocal.onde()
    assert onde == "127.0.0.1:5432/cortex"
    assert SENHA not in onde


def test_diagnostico_nunca_carrega_a_senha(com_senha, monkeypatch):
    """Vai para a tela e para o log; o texto do psycopg pode trazer o conninfo
    inteiro, por isso o diagnóstico devolve só o TIPO do erro."""
    def explode(*a, **kw):
        raise RuntimeError(f"falhou com password={SENHA}")

    monkeypatch.setattr(pglocal.psycopg, "connect", explode)
    d = pglocal.diagnostico()
    assert d["conectado"] is False
    assert d["erro"] == "RuntimeError"
    assert SENHA not in repr(d)


def test_sem_senha_o_recurso_esta_desligado_e_nao_e_erro(monkeypatch):
    """Instalação que ainda não migrou nada é instalação inteira, não quebrada."""
    monkeypatch.delenv("CORTEX_PG_PASSWORD", raising=False)
    assert pglocal.configurado() is False
    d = pglocal.diagnostico()
    assert d == {"configurado": False, "conectado": False, "onde": pglocal.onde(),
                 "erro": None, "ms": None, "versao_schema": None}


def test_usar_sem_configurar_diz_o_que_fazer(monkeypatch):
    monkeypatch.delenv("CORTEX_PG_PASSWORD", raising=False)
    with pytest.raises(pglocal.NaoConfigurado) as e:
        with pglocal.get_conn():
            pass
    assert "CORTEX_PG_PASSWORD" in str(e.value)


# ------------------------------------------------------------- destruição

def test_apagar_esquema_recusa_o_de_producao(com_senha):
    """`apagar_esquema()` é ferramenta de teste. Sem esta guarda, um argumento
    errado apagaria o banco inteiro com CASCADE e sem perguntar."""
    with pytest.raises(ValueError):
        pglocal.apagar_esquema(pglocal.ESQUEMA_PADRAO)


# -------------------------------------------------------------- migrations

def test_migrations_sao_numeradas_e_unicas():
    arquivos = migracoes._arquivos()
    assert arquivos, "não há migration nenhuma em sql/cortex/"
    versoes = [v for v, _ in arquivos]
    assert versoes == sorted(versoes), "a ordem tem de sair pelo número"
    assert len(set(versoes)) == len(versoes), "duas migrations com o mesmo número"


def test_a_primeira_migration_cria_a_tabela_de_versao():
    """`schema_versao` é a única tabela que o runner conhece por nome: se ela
    não vier na 0001, nada mais é registrável."""
    _, primeira = migracoes._arquivos()[0]
    assert "schema_versao" in primeira.read_text(encoding="utf-8")


def test_aplica_e_registra_a_versao(esquema_pg):
    assert migracoes.versao_atual(esquema_pg) == migracoes._arquivos()[-1][0]
    assert migracoes.pendentes(esquema_pg) == []


def test_aplicar_de_novo_nao_faz_nada(esquema_pg):
    """É o comando normal depois de um `git pull`: tem de ser seguro."""
    assert migracoes.aplicar(esquema_pg) == []


def test_schema_novo_tem_tudo_pendente(pg_disponivel):
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    nome = "teste_pendencia_zero"
    pglocal.criar_esquema(nome)
    try:
        assert len(migracoes.pendentes(nome)) == len(migracoes._arquivos())
    finally:
        pglocal.apagar_esquema(nome)


def test_esquemas_de_teste_nao_se_enxergam(esquema_pg):
    """A base de um teste não pode aparecer no outro — é o que o arquivo em
    `tmp_path` dava de graça e o schema precisa dar de propósito."""
    from api.antt import armazenamento as arm
    outro = "teste_vizinho_isolado"
    migracoes.aplicar(outro)
    try:
        arm.gravar_lote([{"rntrc": "111", "nome": "X", "situacao": "ATIVO",
                          "categoria": "ETC", "uf": "SP", "municipio": "SBC",
                          "data_situacao": "01/07/2026"}], "2026-07", esquema_pg)
        assert arm.todas(esquema_pg) != {}
        assert arm.todas(outro) == {}
    finally:
        pglocal.apagar_esquema(outro)


# ------------------------------------------- número de migration repetido
#
# Duas frentes no mesmo repositório criam o mesmo número no mesmo dia — foi o
# que aconteceu em 27/08/2026 com o `0009`. O runner comparava só o NÚMERO e
# teria pulado uma das duas em silêncio.


def test_nao_existem_dois_arquivos_com_o_mesmo_numero():
    """Pega a colisão no commit, não no deploy."""
    numeros = [v for v, _ in migracoes._arquivos()]
    repetidos = {n for n in numeros if numeros.count(n) > 1}
    assert not repetidos, f"migrations com número repetido: {sorted(repetidos)}"


def test_numero_ja_aplicado_com_outro_arquivo_e_erro_alto(esquema_pg):
    """O caso que motivou a correção: o banco tem 0009 aplicada como
    `0009_correio_agenda.sql` e o repositório traz outro `0009_*.sql`. Antes
    isso era um `skip` silencioso — as tabelas nunca eram criadas, sem erro."""
    from api import pglocal
    n = migracoes._arquivos()[-1][0] + 1
    pglocal.executar(
        "INSERT INTO schema_versao(versao, arquivo) VALUES(%s, %s)",
        (n, f"{n:04d}_de_outra_frente.sql"), esquema=esquema_pg)

    class ArquivoFalso:
        name = f"{n:04d}_minha_migration.sql"

    original = migracoes._arquivos
    try:
        migracoes._arquivos = lambda: original() + [(n, ArquivoFalso())]
        with pytest.raises(migracoes.NumeroJaUsado) as e:
            migracoes.pendentes(esquema_pg)
        assert "de_outra_frente" in str(e.value)
        assert "minha_migration" in str(e.value)
    finally:
        migracoes._arquivos = original


def test_numero_registrado_sem_arquivo_no_disco_nao_e_erro(esquema_pg):
    """Migration de outra frente, ainda não commitada, aparece no banco e não
    no repositório. É o estado normal enquanto ela não commita — não pode
    quebrar o deploy de quem não tem nada a ver com isso."""
    from api import pglocal
    n = migracoes._arquivos()[-1][0] + 50
    pglocal.executar(
        "INSERT INTO schema_versao(versao, arquivo) VALUES(%s, %s)",
        (n, f"{n:04d}_nao_commitada.sql"), esquema=esquema_pg)
    assert migracoes.pendentes(esquema_pg) == []
