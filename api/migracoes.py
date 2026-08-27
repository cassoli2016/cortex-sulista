"""Migrations do banco local — aplica `sql/cortex/NNNN_*.sql`.

Trinta linhas em vez do Alembic de propósito: o Alembic deste repositório está
apontado para o schema DA ARQUITETURA (`migrations/versions/0001..0006`, que
nunca rodou), com a tabela de versão dele. Enfiar duas cadeias na mesma
ferramenta confunde justamente na hora em que se está com o banco na mão.

Regras:

- ordem pelo NÚMERO do arquivo, sempre;
- cada migration roda na sua transação: a que falha não deixa metade aplicada,
  e o registro em `schema_versao` entra na MESMA transação do DDL — senão um
  erro no meio deixaria o schema alterado e o runner achando que não aplicou;
- o que já está registrado não roda de novo, então chamar duas vezes é seguro
  e é o modo normal de usar depois de um `git pull`;
- funciona em QUALQUER schema, que é como o teste aplica este mesmo schema num
  universo isolado (ver `docs/MIGRACAO_POSTGRES.md`).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import pglocal

ROOT = Path(__file__).resolve().parent.parent
DIR_SQL = ROOT / "sql" / "cortex"
_NUM = re.compile(r"^(\d{4})_")

# Schemas que ESTE PROCESSO já viu na última versão. `init_db()` é chamado a
# cada escrita (é o que garante que a primeira gravação de uma instalação crie
# as tabelas), e sem esta memória cada chamada custava duas idas ao banco só
# para descobrir que não havia nada a aplicar. Medido: a suíte do orçamento
# passou de 2 para mais de 10 minutos ao migrar.
#
# Seguro porque migration nova só chega com DEPLOY, e deploy reinicia a API —
# processo novo, memória vazia. O `--esquema` do runner também não é afetado:
# ele roda em outro processo.
_EM_DIA: set[str] = set()


def _arquivos() -> list[tuple[int, Path]]:
    return sorted(((int(m.group(1)), p) for p in DIR_SQL.glob("*.sql")
                   if (m := _NUM.match(p.name))), key=lambda x: x[0])


def versao_atual(esquema: str | None = None) -> int | None:
    try:
        r = pglocal.um("SELECT max(versao) AS v FROM schema_versao",
                       esquema=esquema)
    except Exception:  # noqa: BLE001 — schema novo não tem a tabela ainda
        return None
    return (r or {}).get("v")


class NumeroJaUsado(RuntimeError):
    """Duas migrations diferentes com o mesmo número. Ver `pendentes()`."""


def pendentes(esquema: str | None = None) -> list[tuple[int, Path]]:
    """O que falta, na ordem. Schema sem `schema_versao` é schema novo: tudo
    está pendente, inclusive a migration que cria a própria tabela.

    COMPARA NÚMERO **E** NOME DO ARQUIVO. Comparar só o número parece bastar —
    e não basta: com duas frentes trabalhando no mesmo repositório, as duas
    criam o `0009` no mesmo dia. Aconteceu em 27/08/2026: a outra sessão
    aplicou `0009_correio_agenda.sql` em produção enquanto eu ia numerar
    `0009_contrapartida.sql`. Sob a regra antiga o runner veria "0009 já
    aplicada" e PULARIA A MINHA EM SILÊNCIO — sem erro, sem log, e as tabelas
    simplesmente não existiriam. O sintoma apareceria semanas depois, noutra
    máquina, como "tabela não existe".

    Agora número repetido com arquivo diferente é ERRO ALTO. Número registrado
    cujo arquivo não está no disco é normal e não é erro: é a migration de
    outra frente que ainda não foi commitada.
    """
    try:
        registradas = {r["versao"]: r["arquivo"] for r in pglocal.query(
            "SELECT versao, arquivo FROM schema_versao", esquema=esquema)}
    except Exception:  # noqa: BLE001
        registradas = {}
    falta: list[tuple[int, Path]] = []
    for versao, arquivo in _arquivos():
        registrada = registradas.get(versao)
        if registrada is None:
            falta.append((versao, arquivo))
        elif registrada != arquivo.name:
            raise NumeroJaUsado(
                f"a migration {versao:04d} já foi aplicada neste banco como "
                f"{registrada!r}, e o repositório traz {arquivo.name!r} com o "
                "mesmo número. Renumere a sua para o próximo número livre — "
                "aplicar como está deixaria uma das duas de fora, calada.")
    return falta


def aplicar(esquema: str | None = None, falar=None) -> list[int]:
    """Aplica o que falta. Devolve as versões aplicadas NESTA chamada."""
    alvo = esquema or pglocal.ESQUEMA_PADRAO
    if alvo in _EM_DIA:
        return []
    pglocal.criar_esquema(alvo)
    feitas: list[int] = []
    for versao, arquivo in pendentes(alvo):
        with pglocal.get_conn(alvo) as conn:
            with conn.cursor() as cur:
                cur.execute(arquivo.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_versao(versao, arquivo) VALUES(%s, %s)",
                    (versao, arquivo.name))
        feitas.append(versao)
        if falar:
            falar(f"aplicada {versao:04d} — {arquivo.name}")
    _EM_DIA.add(alvo)
    return feitas
