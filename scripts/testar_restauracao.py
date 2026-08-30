"""Prova que o backup do CÓRTEX RESTAURA — não que o arquivo existe.

POR QUE ISTO EXISTE
===================
`pg_restore -l` lista o conteúdo do dump e só prova que o arquivo está
íntegro. Backup que nunca foi restaurado é uma suposição, e é sempre no pior
dia que se descobre que a suposição era falsa. Esta é a razão de "restauração
de backup testada de verdade" ser um dos três critérios declarados do `1.0.0`
no CLAUDE.md — e o gatilho para apagar os `.db` da migração de 27/08/2026,
que só existem como desfazer enquanto esta prova não passar.

O QUE ELE FAZ, EM ORDEM
=======================
1. Cria um banco NOVO E VAZIO (nunca toca no de produção — ver a trava abaixo).
2. Restaura o dump mais recente nele.
3. **Estrutura**: as tabelas do restaurado são as mesmas da produção?
4. **Schema em dia**: o migrador não encontra migration pendente no restaurado?
   É o que prova que o schema restaurado é o que o CÓDIGO espera, e não só um
   schema qualquer que carregou sem erro.
5. **Volume**: linha por linha, tabela por tabela, contra a produção. Tabela
   MENOR na produção que no backup é o alarme (dado sumiu depois do dump);
   maior é o esperado (a produção andou desde as 03:20).
6. **Funcional**: a API sobe apontada para o restaurado e os módulos do CÓRTEX
   leem dele pelos caminhos REAIS de leitura, não por SQL escrito aqui.
7. Apaga o banco de teste.

A TRAVA QUE IMPORTA
===================
Toda operação destrutiva confere o nome do alvo contra `CORTEX_PG_DB` e
recusa se forem iguais. Restaurar por cima da produção é exatamente o
acidente que um script de teste de restauração pode causar, e ele seria pior
que nunca ter testado.

Uso:
    uv run --no-sync python scripts/testar_restauracao.py
    uv run --no-sync python scripts/testar_restauracao.py --dump <arquivo>
    uv run --no-sync python scripts/testar_restauracao.py --manter
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PG_BIN = Path(r"C:\Program Files\PostgreSQL\17\bin")
ALVO_PADRAO = "cortex_restauracao_teste"
DIR_DUMP = ROOT / "data" / "backup"


# ── ambiente ────────────────────────────────────────────────────────────────
def ler_env() -> dict:
    """As credenciais saem do `.env`, como no backup — nunca da linha de
    comando, que é visível para qualquer usuário da máquina."""
    arq = ROOT / ".env"
    if not arq.exists():
        raise SystemExit("ERRO: .env não encontrado.")
    cfg = {}
    for linha in arq.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.strip().startswith("#"):
            k, _, v = linha.partition("=")
            cfg[k.strip()] = v.strip()
    if not cfg.get("CORTEX_PG_PASSWORD"):
        raise SystemExit("banco local não configurado (sem CORTEX_PG_PASSWORD).")
    return cfg


def _conn(cfg: dict, banco: str):
    import psycopg
    return psycopg.connect(
        host=cfg.get("CORTEX_PG_HOST", "127.0.0.1"),
        port=cfg.get("CORTEX_PG_PORT", "5432"),
        dbname=banco, user=cfg.get("CORTEX_PG_USER", "cortex"),
        password=cfg["CORTEX_PG_PASSWORD"], connect_timeout=10)


def _pg(cfg: dict, exe: str, *args: str, banco: str | None = None) -> subprocess.CompletedProcess:
    caminho = PG_BIN / f"{exe}.exe"
    if not caminho.exists():
        raise SystemExit(f"ERRO: {exe} não encontrado em {PG_BIN}")
    base = ["-h", cfg.get("CORTEX_PG_HOST", "127.0.0.1"),
            "-p", str(cfg.get("CORTEX_PG_PORT", "5432")),
            "-U", cfg.get("CORTEX_PG_USER", "cortex")]
    if banco:
        base += ["-d", banco]
    amb = {**os.environ, "PGPASSWORD": cfg["CORTEX_PG_PASSWORD"]}
    return subprocess.run([str(caminho), *base, *args], env=amb,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


# ── a trava ─────────────────────────────────────────────────────────────────
def travar(cfg: dict, alvo: str) -> None:
    """Recusa qualquer alvo que possa ser a produção.

    Não é paranoia: este script APAGA e RECRIA o banco que recebe. Um erro de
    digitação no `--alvo` seria o acidente mais caro que ele pode causar.
    """
    prod = cfg.get("CORTEX_PG_DB", "cortex")
    if alvo.strip().lower() == prod.strip().lower():
        raise SystemExit(
            f"RECUSADO: o alvo '{alvo}' é o banco de PRODUÇÃO. Este script "
            "apaga e recria o banco que recebe — escolha outro nome.")
    if not alvo.startswith("cortex_") or len(alvo) < 10:
        raise SystemExit(
            f"RECUSADO: o alvo '{alvo}' não parece um banco de teste. "
            "Use um nome começando com 'cortex_'.")


# ── as etapas ───────────────────────────────────────────────────────────────
def recriar(cfg: dict, alvo: str) -> None:
    travar(cfg, alvo)
    _pg(cfg, "dropdb", "--if-exists", alvo, banco=None)
    r = _pg(cfg, "createdb", alvo, banco=None)
    if r.returncode:
        raise SystemExit(f"ERRO ao criar {alvo}: {r.stderr.strip()}")


def apagar(cfg: dict, alvo: str) -> None:
    travar(cfg, alvo)
    _pg(cfg, "dropdb", "--if-exists", alvo, banco=None)


def restaurar(cfg: dict, alvo: str, dump: Path) -> list[str]:
    travar(cfg, alvo)
    r = _pg(cfg, "pg_restore", "--no-owner", "--no-privileges",
            str(dump), banco=alvo)
    # pg_restore devolve != 0 por AVISO tambem (owner ausente, extensao ja
    # existente). O que interessa e o que ele chama de `error:`.
    erros = [l for l in (r.stderr or "").splitlines()
             if "error:" in l.lower()]
    return erros


def tabelas(cfg: dict, banco: str, esquema: str = "cortex") -> dict[str, int]:
    """Nome -> contagem de linhas, para todas as tabelas do schema."""
    with _conn(cfg, banco) as con, con.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY 1",
            (esquema,))
        nomes = [r[0] for r in cur.fetchall()]
        fora = {}
        for n in nomes:
            cur.execute(f'SELECT count(*) FROM "{esquema}"."{n}"')
            fora[n] = cur.fetchone()[0]
    return fora


def migrations_pendentes(cfg: dict, alvo: str) -> list[str]:
    """O migrador, apontado para o restaurado, não pode achar nada pendente.

    É a prova de que o schema que voltou é o que o CÓDIGO ATUAL espera — um
    dump antigo restaura sem erro nenhum e ainda assim deixa o sistema sem
    uma tabela que o código de hoje usa.
    """
    amb = {**os.environ, "CORTEX_PG_DB": alvo,
           "CORTEX_PG_PASSWORD": cfg["CORTEX_PG_PASSWORD"],
           "CORTEX_PG_HOST": cfg.get("CORTEX_PG_HOST", "127.0.0.1"),
           "CORTEX_PG_PORT": str(cfg.get("CORTEX_PG_PORT", "5432")),
           "CORTEX_PG_USER": cfg.get("CORTEX_PG_USER", "cortex")}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "migrar_schema.py"),
                        "--conferir"], env=amb, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    saida = (r.stdout or "") + (r.stderr or "")
    linhas = [l.strip() for l in saida.splitlines() if l.strip()]
    return linhas


def leituras_reais(cfg: dict, alvo: str) -> list[tuple[str, str]]:
    """Os módulos do CÓRTEX lendo o banco restaurado pelos caminhos REAIS.

    Consulta escrita aqui provaria que o Postgres funciona, não que o CÓRTEX
    funciona. Estas são as mesmas funções que as telas chamam.
    """
    os.environ["CORTEX_PG_DB"] = alvo
    for k, v in cfg.items():
        if k.startswith("CORTEX_PG_") and k != "CORTEX_PG_DB":
            os.environ[k] = v

    fora: list[tuple[str, str]] = []

    def tenta(rotulo, fn):
        try:
            r = fn()
            n = len(r) if hasattr(r, "__len__") else r
            fora.append((rotulo, f"OK · {n}"))
        except Exception as exc:  # noqa: BLE001
            fora.append((rotulo, f"FALHOU · {type(exc).__name__}: {exc}"))

    from api.extrato import armazenamento as ext
    from api.gestao import acoes, atas
    from api.orcamento import armazenamento as orc
    from api.premiacao import config as prem

    tenta("Extrato · contas", lambda: ext.listar_contas())
    tenta("Extrato · importações", lambda: ext.listar_importacoes())
    tenta("Orçamento · versões", lambda: orc.listar_versoes(None))
    tenta("Gestão · ações", lambda: acoes.listar())
    tenta("Gestão · atas", lambda: atas.listar())
    tenta("Premiação · versões", lambda: prem.versoes(None))
    return fora


def api_sobe(cfg: dict, alvo: str) -> str:
    """A API DE VERDADE, no uvicorn, apontada para o banco restaurado.

    `/api/health` não toca banco — por isso ela não é a prova, é o pré-
    requisito: se a aplicação nem sobe com essa configuração, o resto não
    importa. A prova de dado é `leituras_reais`.
    """
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()

    amb = {**os.environ, "CORTEX_PG_DB": alvo,
           "CORTEX_PG_PASSWORD": cfg["CORTEX_PG_PASSWORD"]}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app",
         "--host", "127.0.0.1", "--port", str(porta), "--log-level", "warning"],
        env=amb, cwd=str(ROOT), stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        import urllib.error
        import urllib.request
        limite = time.time() + 90
        while time.time() < limite:
            if proc.poll() is not None:
                return f"FALHOU · a API morreu no boot (código {proc.returncode})"
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{porta}/api/health", timeout=2) as r:
                    if r.status == 200:
                        return f"OK · subiu na porta {porta} e respondeu /api/health"
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        return "FALHOU · não respondeu em 90 s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── relatório ───────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Testa a restauração do backup.")
    ap.add_argument("--dump", help="dump a restaurar (padrão: o mais recente)")
    ap.add_argument("--alvo", default=ALVO_PADRAO)
    ap.add_argument("--manter", action="store_true",
                    help="não apaga o banco de teste no fim")
    args = ap.parse_args()

    cfg = ler_env()
    prod = cfg.get("CORTEX_PG_DB", "cortex")
    travar(cfg, args.alvo)

    if args.dump:
        dump = Path(args.dump)
    else:
        cands = sorted(DIR_DUMP.glob("cortex-*.dump"),
                       key=lambda p: p.stat().st_mtime)
        if not cands:
            raise SystemExit(f"nenhum dump em {DIR_DUMP}")
        dump = cands[-1]
    if not dump.exists():
        raise SystemExit(f"dump não encontrado: {dump}")

    idade_h = (time.time() - dump.stat().st_mtime) / 3600
    print(f"dump      : {dump.name} · {dump.stat().st_size/1024:,.0f} KB "
          f"· {idade_h:.1f} h atrás")
    print(f"produção  : {prod}")
    print(f"alvo      : {args.alvo}  (será apagado e recriado)")
    print()

    falhas: list[str] = []

    print("1. criando banco vazio…")
    recriar(cfg, args.alvo)

    print("2. restaurando…")
    erros = restaurar(cfg, args.alvo, dump)
    if erros:
        falhas.append(f"pg_restore reportou {len(erros)} erro(s)")
        for e in erros[:5]:
            print(f"   ! {e}")
    else:
        print("   sem erros")

    print("3. estrutura…")
    try:
        tab_r = tabelas(cfg, args.alvo)
        tab_p = tabelas(cfg, prod)
    except Exception as exc:  # noqa: BLE001
        print(f"   FALHOU: {type(exc).__name__}: {exc}")
        if not args.manter:
            apagar(cfg, args.alvo)
        return 1
    faltando = sorted(set(tab_p) - set(tab_r))
    sobrando = sorted(set(tab_r) - set(tab_p))
    print(f"   {len(tab_r)} tabelas no restaurado · {len(tab_p)} na produção")
    if faltando:
        falhas.append(f"tabelas ausentes no restaurado: {', '.join(faltando)}")
        print(f"   ! ausentes: {', '.join(faltando)}")
    if sobrando:
        # não é falha: a produção pode ter recebido migration depois do dump
        print(f"   · só no restaurado (dump mais antigo que o schema? ): "
              f"{', '.join(sobrando)}")

    print("4. schema em dia (o migrador olhando o restaurado)…")
    # CASAR SUBSTRING EM PROSA É FRÁGIL, e esta linha já deu falso positivo:
    # procurava "pendente" e casava com "nada pendente (versão 22)". O migrador
    # imprime uma linha POR migration faltando, cada uma começando com
    # "pendente NNNN — arquivo.sql" — é o começo da linha que decide, não a
    # presença da palavra. Alarme que acende sem haver problema, no script que
    # existe justamente para dizer se há problema.
    for l in migrations_pendentes(cfg, args.alvo):
        print(f"   {l}")
        if l.startswith("pendente "):
            falhas.append(f"migration pendente no restaurado: {l}")

    print("5. volume por tabela…")
    vazias, menores = [], []
    for nome in sorted(tab_r):
        r, p = tab_r[nome], tab_p.get(nome, 0)
        if p > 0 and r == 0:
            vazias.append(f"{nome} (produção {p})")
        elif r > p:
            menores.append(f"{nome} (backup {r} > produção {p})")
    total_r = sum(tab_r.values())
    total_p = sum(tab_p.values())
    print(f"   {total_r:,} linhas no restaurado · {total_p:,} na produção")
    if vazias:
        falhas.append("tabela com dado na produção e VAZIA no backup: "
                      + "; ".join(vazias))
        for v in vazias:
            print(f"   ! vazia no backup: {v}")
    for m in menores:
        # produção MENOR que o backup: alguém apagou depois do dump
        print(f"   · atenção: {m}")

    print("6. a API sobe apontada para o restaurado…")
    r = api_sobe(cfg, args.alvo)
    print(f"   {r}")
    if r.startswith("FALHOU"):
        falhas.append(f"a API não subiu: {r}")

    print("7. os módulos leem o restaurado pelos caminhos reais…")
    for rotulo, res in leituras_reais(cfg, args.alvo):
        print(f"   {rotulo:26} {res}")
        if res.startswith("FALHOU"):
            falhas.append(f"leitura falhou: {rotulo} — {res}")

    if args.manter:
        print(f"\nbanco {args.alvo} MANTIDO para inspeção.")
    else:
        print("\n8. apagando o banco de teste…")
        apagar(cfg, args.alvo)

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} problema(s)")
        for f in falhas:
            print(f"  - {f}")
        return 1
    print("RESULTADO: o backup RESTAURA e o sistema sobe em cima dele.")
    print(f"  dump {dump.name} · {len(tab_r)} tabelas · {total_r:,} linhas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
