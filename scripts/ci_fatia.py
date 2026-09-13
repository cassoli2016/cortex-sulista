"""Fatia a suíte para o CI rodar em paralelo — e transforma falha em anotação.

POR QUE EXISTE (12/09/2026)
===========================
A suíte inteira não cabe num job. Sem o banco ela já passava dos 20 min do teto
antigo (de 05 a 12/09 foram 100 execuções seguidas cortadas no meio, sem
resultado nenhum), e com o Postgres — que o CI precisa ter, porque migration
entra sozinha no banco de produção quando a API reinicia — passou dos 50.
Aumentar o teto só adia: a suíte cresce toda semana. Em repositório público os
minutos do GitHub Actions são grátis; o que custa é o RELÓGIO de quem espera o
PR, e o relógio se divide em jobs paralelos.

A DIVISÃO É POR ARQUIVO, NÃO POR TESTE
======================================
A fixture de módulo dos e2e sobe um navegador e um servidor uma vez por
ARQUIVO; picar um arquivo entre fatias pagaria esse custo em cada uma. O peso
do arquivo é o número de testes coletados vezes um multiplicador grosseiro —
o teste com banco aplica as 80+ migrations num schema novo, o e2e sobe
navegador. É ESTIMATIVA, não medição: o tempo real de cada fatia aparece no
GitHub (jobs `fatia N`), e é por ele que se recalibra `PESO_*`.

A REGRA QUE NÃO PODE FALHAR CALADA
==================================
Todo arquivo coletado cai em EXATAMENTE UMA fatia. Um arquivo que some da
divisão some do CI inteiro, e o CI fica verde sem rodá-lo. Por isso a coleta
com erro (um import quebrado) PARA o job em vez de seguir com o que conseguiu
coletar, e fatia vazia também para — `pytest` sem argumento rodaria a suíte
INTEIRA naquela fatia, e o tempo voltaria a estourar.

Uso:
    python scripts/ci_fatia.py listar K N          # arquivos da fatia K (0..N-1)
    python scripts/ci_fatia.py anotar resultado.xml  # falhas -> ::error do GitHub
"""
from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

PESO_BANCO = 4   # esquema_pg: schema novo + todas as migrations, por teste
PESO_TELA = 2    # tests/frontend: navegador e servidor por módulo
_USA_BANCO = re.compile(r"esquema_pg|pg_disponivel")


def coletar(raiz: Path = RAIZ) -> Counter:
    """Testes por arquivo, como o pytest os enxerga. Coleta com erro PARA."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=raiz, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    ids = [linha.strip() for linha in r.stdout.splitlines() if "::" in linha]
    if r.returncode != 0 or not ids:
        raise SystemExit(
            f"coleta falhou (saída {r.returncode}): nenhuma fatia roda sem a "
            f"lista INTEIRA, senão o arquivo quebrado some do CI calado.\n"
            f"{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return Counter(i.split("::", 1)[0] for i in ids)


def peso(arquivo: str, testes: int, raiz: Path = RAIZ) -> int:
    try:
        texto = (raiz / arquivo).read_text(encoding="utf-8")
    except OSError:
        texto = ""
    if _USA_BANCO.search(texto):
        return testes * PESO_BANCO
    if arquivo.startswith("tests/frontend/"):
        return testes * PESO_TELA
    return testes


def dividir(pesos: dict[str, int], n: int) -> list[list[str]]:
    """O mais pesado primeiro, sempre na fatia mais leve. Determinístico: as N
    fatias rodam em N máquinas que calculam a divisão cada uma por si, e o
    empate se desfaz pelo NOME — nunca pela ordem de um dicionário."""
    if n < 1:
        raise ValueError("n precisa ser >= 1")
    cargas = [0] * n
    fatias: list[list[str]] = [[] for _ in range(n)]
    for arq in sorted(pesos, key=lambda a: (-pesos[a], a)):
        k = min(range(n), key=lambda i: (cargas[i], i))
        cargas[k] += pesos[arq]
        fatias[k].append(arq)
    return [sorted(f) for f in fatias]


def _esc_msg(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(s: str) -> str:
    return _esc_msg(s).replace(":", "%3A").replace(",", "%2C")


def anotar(xml: Path) -> int:
    """Uma linha `::error` por teste que falhou ou deu erro.

    O log de um job do Actions exige login MESMO com o repositório público; a
    anotação não — ela aparece na página do PR e na API aberta
    (`/check-runs/{id}/annotations`). É o que deixa quem revisa, e quem não tem
    o `gh` instalado, saber O QUE falhou sem abrir o log."""
    n = 0
    for tc in ET.parse(xml).getroot().iter("testcase"):
        for tag in ("failure", "error"):
            e = tc.find(tag)
            if e is None:
                continue
            linhas = (e.get("message") or e.text or tag).strip().splitlines()
            msg = linhas[0][:300] if linhas else tag
            arq = tc.get("file") or (
                tc.get("classname", "").replace(".", "/") + ".py")
            print(f"::error file={_esc_prop(arq)},"
                  f"title={_esc_prop(tc.get('name', ''))}::{_esc_msg(msg)}")
            n += 1
    return n


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "listar":
        k, n = int(argv[2]), int(argv[3])
        if not 0 <= k < n:
            raise SystemExit(f"fatia {k} fora de 0..{n - 1}")
        contagem = coletar()
        fatias = dividir({a: peso(a, c) for a, c in contagem.items()}, n)
        if not fatias[k]:
            raise SystemExit(f"fatia {k} de {n} ficou VAZIA — pytest sem "
                             "argumento rodaria a suíte inteira aqui")
        print("\n".join(fatias[k]))
        return 0
    if len(argv) == 3 and argv[1] == "anotar":
        anotar(Path(argv[2]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
