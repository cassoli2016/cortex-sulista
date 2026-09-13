"""Dois arquivos de migration com o mesmo número não chegam à `main`.

O runner (`api/migracoes.py`) já recusa número repetido — mas recusa NO BANCO,
e o banco que importa é o de produção: a migration entra sozinha quando a API
reinicia depois do deploy (`startup` → `auth.init_db()` → `migracoes.aplicar`).
A recusa ali é `NumeroJaUsado` no log, a migration nova fora do banco, e cada
escrita que passa por `init_db()` falhando até alguém renumerar e empurrar de
novo.

Com mais de uma pessoa abrindo PR, as duas pegam o "próximo número livre" no
mesmo dia — aconteceu com o `0009` em 27/08/2026, entre duas sessões na mesma
máquina, e com desenvolvedor de fora a chance só aumenta. Aqui a colisão
aparece no PR, antes do merge, com o nome dos dois arquivos.

A varredura usa `migracoes._arquivos()` de propósito: o que interessa é o que o
RUNNER enxerga, não uma segunda leitura do diretório que pode divergir dele.
"""
from __future__ import annotations

from collections import defaultdict

from api import migracoes


def test_nenhum_numero_de_migration_se_repete():
    por_numero: dict[int, list[str]] = defaultdict(list)
    for numero, arquivo in migracoes._arquivos():
        por_numero[numero].append(arquivo.name)

    # varredura que não acha nada passaria por vacuidade: a casa tem 80+
    assert len(por_numero) > 50, (
        f"só {len(por_numero)} migrations em {migracoes.DIR_SQL} — o diretório "
        "mudou de lugar ou o padrão do nome mudou?")

    repetidos = {f"{n:04d}": sorted(nomes)
                 for n, nomes in por_numero.items() if len(nomes) > 1}
    assert not repetidos, (
        "número de migration repetido — renumere a MAIS NOVA para o próximo "
        f"número livre em origin/main: {repetidos}")


def test_todo_sql_do_diretorio_de_migrations_tem_numero():
    """Arquivo sem o prefixo `NNNN_` é ignorado pelo runner EM SILÊNCIO: a
    tabela que ele cria simplesmente não existe em produção."""
    vistos = {p.name for _, p in migracoes._arquivos()}
    ignorados = sorted(p.name for p in migracoes.DIR_SQL.glob("*.sql")
                       if p.name not in vistos)
    assert not ignorados, (
        f"estes .sql não seguem o padrão NNNN_nome.sql e o runner nunca vai "
        f"aplicá-los: {ignorados}")
