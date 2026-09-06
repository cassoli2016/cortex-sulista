# -*- coding: utf-8 -*-
"""Apaga os schemas de TESTE que sobraram no banco do CÓRTEX, um a um.

POR QUE ISTO EXISTE
===================
A suíte cria um schema exclusivo por teste de banco (`teste_<hex>` pela fixture
`esquema_pg`, `teste_aud_<hex>` pela fixture de auditoria) e o apaga num
`finally`. O `finally` funciona — o que não sobrevive é a rodada MORTA NO MEIO:
`Ctrl+C`, `Stop-Process`, a máquina reiniciando, o AutoDeploy desinstalando o
playwright debaixo da suíte. Aí o schema fica, com as 108 tabelas dentro.

Medido em 05/09/2026: **22 schemas órfãos, 6.182 objetos, 78,4 MB** — contra
391,5 MB do `cortex` de verdade. Não é só peso morto: uma consulta a
`information_schema` que esqueça `AND table_schema = current_schema()` acha a
tabela num desses restos e responde "a migration já rodou". O guard fica VERDE
exatamente no estado que ele existe para pegar.

O QUE PROTEGE ESTE SCRIPT DE APAGAR A COISA ERRADA
==================================================
1. **Padrão fechado, não prefixo.** Só casa `teste_` seguido de hexadecimal do
   tamanho exato que as fixtures geram. `teste_producao`, `testes`, `teste_x`
   não casam com nada aqui. O nome do schema de produção nunca poderia casar.
2. **Lista negra explícita** por cima do padrão, e `pglocal.apagar_esquema()`
   ainda recusa o schema de produção por conta própria — duas travas
   independentes para o mesmo erro.
3. **Aprovação POR SCHEMA, com lote para os antigos.** Os que têm mais de duas
   horas saem numa pergunta só; os recentes — que podem ser de uma suíte viva —
   continuam um a um. Vinte e três perguntas seguidas num prompt de exclusão é
   como se apaga o schema errado: a mão aprende a digitar "s" antes de o olho
   ler o nome. `--tudo` existe, mas exige `--confirmo` junto.
4. **Schema EM USO é pulado.** Se outro processo segura lock em alguma tabela
   dele, há suíte rodando agora — apagar quebraria o teste de outra pessoa.

USO
===
    uv run python scripts/limpar_schemas_teste.py            # pergunta um a um
    uv run python scripts/limpar_schemas_teste.py --listar   # só mostra
    uv run python scripts/limpar_schemas_teste.py --tudo --confirmo
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg import sql as _sql  # noqa: E402

from api import pglocal  # noqa: E402

#: O NOME TEM DE CASAR INTEIRO. As fixtures geram
#: `teste_{uuid4().hex[:12]}` e `teste_aud_{uuid4().hex[:10]}` — hexadecimal,
#: comprimento fixo. Um prefixo solto (`teste_%`) apagaria um schema que
#: alguém tivesse criado à mão para trabalhar; este padrão não alcança nada
#: além do que a suíte fabrica.
PADRAO = re.compile(r"^teste_(?:aud_[0-9a-f]{10}|[0-9a-f]{12})$")

#: Cinto por cima do suspensório. Se um dia o padrão for afrouxado numa
#: manutenção distraída, estes nomes continuam fora.
NUNCA = {"cortex", "public", "information_schema", "pg_catalog", "pg_toast"}

#: `starts_with` E NAO `LIKE`, e nao e estilo: o `%` do `LIKE` e placeholder do
#: psycopg, e a consulta morre em "only '%s', '%b', '%t' are allowed as
#: placeholders". Escapar para `%%` funcionaria e seria a proxima pessoa
#: tropecando na mesma pedra — `starts_with` nao tem `%` nenhum.
#: Abaixo desta idade o schema pode ser de uma rodada VIVA, e cada um se
#: aprova sozinho. Acima dela vai no lote.
#:
#: O CRITÉRIO DE IDADE É MAIS SEGURO QUE O DE LOCK SOZINHO: uma suíte que
#: acabou de morrer solta o lock no mesmo instante, e o schema fica órfão sem
#: nunca ter aparecido como "em uso". Duas horas cobre com folga a suíte
#: completa da casa, que leva pouco mais de trinta minutos.
RECENTE_H = 2

#: A IDADE VEM DE `schema_versao.aplicado_em`, e é a única fonte honesta que
#: existe: o PostgreSQL **não guarda** data de criação de schema. A fixture cria
#: o schema e aplica as migrations em seguida, então o primeiro `aplicado_em`
#: é a hora de nascimento dele, com precisão de segundo.
#:
#: Ordenar por `oid` daria a ordem certa e nenhuma data — e "apague os 20 mais
#: antigos" é uma frase muito pior de aprovar que "apague os 20 com mais de
#: duas horas".
IDADE_SQL = "SELECT min(aplicado_em) AS nasceu FROM {}.schema_versao"

LISTAR_SQL = """
SELECT n.nspname                                        AS esquema,
       n.oid                                            AS oid,
       count(c.oid) FILTER (WHERE c.relkind = 'r')::int AS tabelas,
       coalesce(sum(pg_total_relation_size(c.oid)), 0)::bigint AS bytes,
       coalesce(sum(s.n_live_tup), 0)::bigint           AS linhas
FROM pg_namespace n
LEFT JOIN pg_class c ON c.relnamespace = n.oid
                    AND c.relkind IN ('r', 'i', 't', 'S', 'v')
LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
WHERE starts_with(n.nspname, 'teste_')
GROUP BY n.nspname, n.oid
ORDER BY n.oid
"""

#: Schemas com lock segurado por OUTRO backend. Se a suíte de alguém está
#: rodando agora, o schema dela aparece aqui — e apagá-lo derrubaria o teste
#: no meio, com um erro que não aponta para cá.
EM_USO_SQL = """
SELECT DISTINCT n.nspname AS esquema
FROM pg_locks l
JOIN pg_class c    ON c.oid = l.relation
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE l.pid <> pg_backend_pid()
  AND starts_with(n.nspname, 'teste_')
"""


def mb(b: int) -> str:
    return "%.1f MB" % (b / 1024.0 / 1024.0)


def horas(nasceu) -> float | None:
    if not nasceu:
        return None
    agora = datetime.now(timezone.utc) if nasceu.tzinfo else datetime.now()
    return max(0.0, (agora - nasceu).total_seconds() / 3600.0)


def idade_txt(h: float | None) -> str:
    if h is None:
        return "n/d"
    if h < 1:
        return "%d min" % int(h * 60)
    if h < 48:
        return "%.1f h" % h
    return "%d dias" % int(h / 24)


def _nasceu(esquema: str):
    """Quando o schema nasceu, ou None. Nunca levanta.

    SEM RESPOSTA É TRATADO COMO RECENTE mais adiante — um schema sem
    `schema_versao` não é da fixture normal, e o lado seguro para o que não se
    entende é pedir aprovação individual.
    """
    try:
        with pglocal.get_conn() as conn, conn.cursor() as cur:
            cur.execute(_sql.SQL(IDADE_SQL).format(_sql.Identifier(esquema)))
            return (cur.fetchone() or {}).get("nasceu")
    except Exception:  # noqa: BLE001
        return None


def levantar() -> tuple[list[dict], set[str], list[str]]:
    """(candidatos, em_uso, recusados). Nunca apaga nada."""
    linhas = [dict(r) for r in pglocal.query(LISTAR_SQL, ())]
    em_uso = {r["esquema"] for r in pglocal.query(EM_USO_SQL, ())}
    bons, recusados = [], []
    for r in linhas:
        nome = r["esquema"]
        if nome in NUNCA or not PADRAO.match(nome):
            # NÃO É ERRO, É ACHADO: um `teste_*` que não casa o padrão foi
            # criado por outra coisa, e quem decide o destino dele é gente.
            recusados.append(nome)
            continue
        r["horas"] = horas(_nasceu(nome))
        bons.append(r)
    # DO MAIS VELHO PARA O MAIS NOVO. Idade desconhecida vai para o FIM, junto
    # dos recentes: é onde mora a aprovação individual.
    bons.sort(key=lambda x: (x["horas"] is None, -(x["horas"] or 0)))
    return bons, em_uso, recusados


def main() -> int:
    # O CONSOLE DO WINDOWS NAO E UTF-8 por padrao, e sem isto "órfão" sai
    # "rfo" — num script que pergunta antes de APAGAR, texto ilegivel e um
    # risco, nao um detalhe. Mesmo padrao dos auditores da casa.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    args = set(sys.argv[1:])
    so_listar = "--listar" in args
    tudo = "--tudo" in args

    if tudo and "--confirmo" not in args:
        print("--tudo exige --confirmo junto. É apagar sem perguntar; escreva "
              "as duas.")
        return 2

    # DIZER CONTRA QUE BANCO ISTO VAI RODAR, sempre e antes de tudo. Um script
    # que apaga schema e não mostra o destino é um script que uma vez roda no
    # banco errado.
    print("banco: %s" % pglocal.onde())
    bons, em_uso, recusados = levantar()

    if recusados:
        print("\nfora do padrão, NÃO serão tocados (confira à mão):")
        for n in recusados:
            print("   %s" % n)

    if not bons:
        print("\nnenhum schema de teste órfão. Nada a fazer.")
        return 0

    total = sum(r["bytes"] for r in bons)
    print("\n%d schema(s) de teste, %s no total:" % (len(bons), mb(total)))
    print("   %-24s %8s %10s %9s %9s  %s"
          % ("schema", "tabelas", "tamanho", "linhas", "idade", "situação"))
    for r in bons:
        print("   %-24s %8d %10s %9d %9s  %s"
              % (r["esquema"], r["tabelas"], mb(r["bytes"]), r["linhas"],
                 idade_txt(r["horas"]),
                 "EM USO — será pulado" if r["esquema"] in em_uso else "órfão"))

    if so_listar:
        return 0

    # A ORDEM É DA MAIS ANTIGA PARA A MAIS NOVA (oid crescente). A mais nova é
    # a que tem mais chance de ser de uma rodada ainda viva, e deixá-la por
    # último dá a quem aprova a informação na ordem certa.
    apagados, liberado = 0, 0
    sempre = tudo

    # APROVAÇÃO EM LOTE PARA OS ANTIGOS. Vinte e três perguntas seguidas num
    # prompt de exclusão é como se apaga o schema errado: a mão aprende a
    # digitar "s" antes de o olho ler o nome. Os velhos vão numa pergunta só;
    # os recentes — que podem ser de uma suíte viva — continuam um a um.
    livres = [r for r in bons if r["esquema"] not in em_uso]
    antigos = [r for r in livres
               if r["horas"] is not None and r["horas"] >= RECENTE_H]
    if antigos and not sempre:
        print("\n%d schema(s) com mais de %dh, somando %s:"
              % (len(antigos), RECENTE_H, mb(sum(r["bytes"] for r in antigos))))
        print("   do mais velho (%s) ao mais novo (%s)"
              % (idade_txt(antigos[0]["horas"]),
                 idade_txt(antigos[-1]["horas"])))
        try:
            resp = input("   apagar TODOS estes de uma vez? [s]im / [n]ão "
                         "(pergunto um a um): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\ninterrompido — nada foi apagado.")
            return 0
        if resp in ("s", "sim", "y"):
            for r in antigos:
                try:
                    pglocal.apagar_esquema(r["esquema"])
                except Exception as exc:  # noqa: BLE001
                    print("   %s FALHOU (%s)" % (r["esquema"], type(exc).__name__))
                    continue
                apagados += 1
                liberado += r["bytes"]
            print("   %d apagado(s) no lote." % apagados)
            # Os antigos saem da fila individual; sobram os recentes.
            feitos = {r["esquema"] for r in antigos}
            bons = [r for r in bons if r["esquema"] not in feitos]
            if bons:
                print("\nagora os recentes, um a um — estes podem ser de uma "
                      "suíte rodando agora:")

    for r in bons:
        nome = r["esquema"]
        if nome in em_uso:
            print("\n%s: PULADO — outro processo tem lock aqui (suíte rodando?)"
                  % nome)
            continue
        if not sempre:
            print("\n%s — %d tabela(s), %s, %d linha(s), criado há %s"
                  % (nome, r["tabelas"], mb(r["bytes"]), r["linhas"],
                     idade_txt(r["horas"])))
            try:
                resp = input("   apagar? [s]im / [n]ão / [t]odos / [q]uit: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\ninterrompido — nada mais será apagado.")
                break
            if resp in ("q", "quit"):
                print("   parando aqui.")
                break
            if resp in ("t", "todos"):
                sempre = True
            elif resp not in ("s", "sim", "y"):
                print("   mantido.")
                continue
        try:
            pglocal.apagar_esquema(nome)
        except Exception as exc:  # noqa: BLE001
            # FALHA DE UM NÃO DERRUBA O RESTO, e ela é DITA: um schema que não
            # apaga costuma ser exatamente o que está em uso.
            print("   FALHOU (%s): %s" % (type(exc).__name__, exc))
            continue
        apagados += 1
        liberado += r["bytes"]
        print("   apagado.")

    print("\n%d schema(s) apagado(s), %s liberado(s)." % (apagados, mb(liberado)))
    if apagados:
        print("O espaço volta ao sistema de arquivos no autovacuum; para "
              "devolver agora, rode VACUUM FULL fora do horário de uso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
