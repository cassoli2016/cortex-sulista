"""O cartão de cache local da Saúde, depois da migração para o PostgreSQL.

POR QUE ESTE CARTÃO ENCOLHEU
============================
Até 30/08/2026 ele listava nove bancos SQLite, dos quais **oito** só diziam
"migrada para o PostgreSQL · arquivo mantido como desfazer". Um cartão em que
89% das linhas dizem "isto não está em uso" ensina a pular o cartão — e junto
com ele a única linha que decide alguma coisa (o cache da Gobrax, onde
corrupção é falha silenciosa: o número sai menor e nada acusa).

É a mesma família do alarme que acende sem haver problema, já registrada no
CLAUDE.md: o que não muda nunca deixa de ser lido.

O QUE SOBROU, E POR QUÊ
=======================
- **A tabela** lista só o que está VIVO — hoje `telemetria.db`, que fica fora
  do PostgreSQL de propósito por ser cache reconstruível.
- **A linha de resumo dos arquivos da migração SUMIU da tela em 30/08/2026**,
  quando eles foram arquivados em `data/arquivo/` — a restauração do backup
  passou a ser o caminho de volta, testada de verdade. Ela some sozinha porque
  a varredura é da PASTA: zero arquivos, zero linha.
- **Mas o código não virou resíduo, e é o ponto destes testes.** Ele continua
  sendo o sensor de duas coisas vivas: um `.db` que VOLTE para `data/` (o
  rollback, que reaparece na hora e como conhecido, não como alarme) e um
  `.db` que ninguém declarou (módulo novo escrevendo em SQLite contra a regra).
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from api import servidor as sv

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def dados(tmp_path, monkeypatch):
    """Um diretório `data/` de mentira, para não depender do disco real."""
    monkeypatch.setattr(sv, "_dir_dados", lambda: tmp_path)
    return tmp_path


def _cria(pasta: Path, nome: str, quando=None) -> Path:
    p = pasta / nome
    con = sqlite3.connect(p)
    con.execute("create table t(a int)")
    con.commit()
    con.close()
    if quando is not None:
        ts = quando.timestamp()
        os.utime(p, (ts, ts))
    return p


# ── a tabela: só o que está vivo ────────────────────────────────────────────


def test_a_tabela_lista_apenas_as_bases_vivas(dados):
    """Nenhum arquivo da migração entra como linha — esse era o problema."""
    _cria(dados, "telemetria.db")
    for nome in sv.MIGRADAS:
        _cria(dados, nome, sv.LIMITE_MIGRACAO - timedelta(days=1))
    nomes = {b["arquivo"] for b in sv._bases_locais()}
    assert nomes == {"telemetria.db"}
    assert not (nomes & sv.MIGRADAS)


def test_nenhuma_base_viva_e_tambem_migrada():
    """Um arquivo nos dois lugares apareceria como linha E dentro do resumo,
    contado duas vezes."""
    vivas = {a for _, a in sv.BASES_VIVAS}
    assert not (vivas & sv.MIGRADAS), vivas & sv.MIGRADAS


def test_cache_ausente_e_info_e_nao_erro(dados):
    """A base nasce no primeiro uso do recurso — vermelho ali seria alarme
    sobre função que ninguém ligou."""
    b = sv._bases_locais()[0]
    assert b["status"] == "info" and "não usada ainda" in b["detalhe"]


def test_cache_integro_sai_ok_com_a_data_da_escrita(dados):
    _cria(dados, "telemetria.db")
    b = sv._bases_locais()[0]
    assert b["status"] == "ok" and "íntegra" in b["detalhe"]
    assert b["bytes"] > 0


def test_arquivo_corrompido_e_ERRO(dados):
    """Cache corrompido é falha silenciosa na premiação: o número sai menor e
    nada acusa. É o motivo de este cartão continuar existindo."""
    (dados / "telemetria.db").write_bytes(b"isto nao e um banco sqlite")
    b = sv._bases_locais()[0]
    assert b["status"] == "erro"


# ── o resumo, e os dois sensores dentro dele ────────────────────────────────


def test_sem_arquivo_nenhum_o_resumo_SOME(dados):
    """Quando o último for apagado a migração terminou de verdade — e a linha
    tem de sumir, não dizer "0 arquivos"."""
    assert sv._migradas() is None


def test_arquivo_migrado_DE_VOLTA_em_data_reaparece_no_cartao(dados):
    """O caminho de rollback, e é por isso que a lista MIGRADAS não virou
    resíduo depois do arquivamento de 30/08/2026.

    Devolver um `.db` para `data/` o faz reaparecer na hora — a varredura é da
    PASTA, não de uma lista fixa. E ele volta como conhecido (`info`), não
    como banco não declarado: uma volta deliberada não é alarme.
    """
    antes = sv.LIMITE_MIGRACAO - timedelta(days=1)
    for nome in ("auth.db", "orcamento.db", "push.db"):
        _cria(dados, nome, antes)
    m = sv._migradas()
    assert m["arquivos"] == 3 and m["bytes"] > 0
    assert m["status"] == "info"
    assert "27/08/2026" in m["detalhe"] and "volta" in m["detalhe"]


def test_o_cache_VIVO_nao_entra_no_resumo(dados):
    _cria(dados, "telemetria.db")
    _cria(dados, "auth.db", sv.LIMITE_MIGRACAO - timedelta(days=1))
    assert sv._migradas()["arquivos"] == 1


def test_SENSOR_arquivo_migrado_escrito_de_novo_vira_ALERTA(dados):
    """O que transforma oito linhas mortas numa útil.

    Um `.db` migrado gravado de novo significa que código novo voltou a
    escrever em SQLite contra a regra da casa — e esse dado NÃO está no
    PostgreSQL. Hoje isso passaria despercebido.
    """
    _cria(dados, "auth.db", sv.LIMITE_MIGRACAO - timedelta(days=1))
    _cria(dados, "orcamento.db", sv.LIMITE_MIGRACAO + timedelta(days=2))
    m = sv._migradas()
    assert m["status"] == "alerta"
    assert m["reescritos"] == ["orcamento.db"]
    # a mensagem tem de dizer QUAL arquivo e QUAL a consequencia
    assert "orcamento.db" in m["detalhe"]
    assert "PostgreSQL" in m["detalhe"]


def test_SENSOR_db_que_ninguem_declarou_vira_ALERTA(dados):
    """A varredura é do DIRETÓRIO, não de uma lista, justamente para pegar o
    arquivo que apareceu sem passar por aqui. Uma lista fixa só enxerga o que
    já se sabia."""
    _cria(dados, "auth.db", sv.LIMITE_MIGRACAO - timedelta(days=1))
    _cria(dados, "modulo_novo.db")
    m = sv._migradas()
    assert m["status"] == "alerta"
    assert m["nao_declarados"] == ["modulo_novo.db"]
    assert "pglocal" in m["detalhe"], "a mensagem tem de dizer onde escrever"


def test_o_resumo_nao_quebra_sem_o_diretorio(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_dir_dados", lambda: tmp_path / "nao_existe")
    assert sv._migradas() is None


# ── a regra que o cartão não deveria precisar vigiar sozinho ────────────────

# Único módulo autorizado a abrir SQLite: o cache da Gobrax, que fica fora do
# PostgreSQL de propósito por ser reconstruível. `servidor.py` entra porque é
# quem CONFERE a integridade desse cache, em modo somente-leitura.
SQLITE_AUTORIZADO = {"api/gobrax/armazenamento.py", "api/servidor.py"}


def test_so_o_modulo_autorizado_abre_SQLITE():
    """A regra do CLAUDE.md — "ao criar módulo novo que escreve, use
    api/pglocal.py, nunca abra SQLite" — amarrada num teste.

    O cartão da Saúde pega isso pelo efeito (um `.db` novo no diretório), mas
    depende de alguém olhar a tela. Aqui quebra no CI, que é onde tem de doer.
    """
    achados = []
    for py in (RAIZ / "api").rglob("*.py"):
        rel = py.relative_to(RAIZ).as_posix()
        if re.search(r"\bsqlite3\.connect\b", py.read_text(encoding="utf-8")):
            achados.append(rel)
    extras = sorted(set(achados) - SQLITE_AUTORIZADO)
    assert not extras, (
        "módulo novo abrindo SQLite: " + ", ".join(extras)
        + " — escrita do CÓRTEX vai para o PostgreSQL (api/pglocal.py). "
          "Ver 'Onde o dado é ESCRITO' no CLAUDE.md.")
