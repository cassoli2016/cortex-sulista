"""Diz qual e o proximo numero de versao LIVRE, olhando tambem o origin/main.

POR QUE ISTO EXISTE
===================
Duas sessoes trabalhando em paralelo escolhem o proximo numero cada uma a
partir do que ve na SUA arvore, e acabam nas duas no mesmo. Aconteceu tres
vezes em 27/08/2026 - e a primeira so foi descoberta dias depois, quando um
merge revelou dois blocos diferentes disputando o rotulo 0.70.0.

O `docs/versoes.yaml` local nao basta para decidir: a outra sessao pode ja ter
publicado 0.102.0 sem que este clone tenha ouvido falar. Por isso o script
consulta o origin ANTES de responder.

USO
===
    uv run python scripts/proxima_versao.py            # sugere o proximo MENOR
    uv run python scripts/proxima_versao.py --correcao # sobe so a CORRECAO
    uv run python scripts/proxima_versao.py --maior    # sobe o MAIOR

Ele nao escreve nada: imprime o numero e o que ja esta ocupado, e a decisao de
MAIOR/MENOR/CORRECAO continua sendo de quem entende a mudanca (a regra esta no
CLAUDE.md). Sem rede, avisa que respondeu so com o que tem local.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
YAML = RAIZ / "docs" / "versoes.yaml"
_RE = re.compile(r'^- versao:\s*"([0-9]+)\.([0-9]+)\.([0-9]+)"', re.MULTILINE)


def _versoes(texto: str) -> set[tuple[int, int, int]]:
    return {(int(a), int(b), int(c)) for a, b, c in _RE.findall(texto)}


def _do_origin() -> tuple[set[tuple[int, int, int]], str | None]:
    """As versoes que o origin/main ja publicou. Devolve (conjunto, aviso)."""
    try:
        subprocess.run(["git", "-C", str(RAIZ), "fetch", "--quiet", "origin", "main"],
                       check=True, capture_output=True, timeout=30)
        saida = subprocess.run(
            ["git", "-C", str(RAIZ), "show", "origin/main:docs/versoes.yaml"],
            check=True, capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        # Sem rede a resposta ainda serve para o trabalho local - mas quem le
        # precisa saber que ela pode colidir com o que a outra sessao publicou.
        return set(), f"nao consegui falar com o origin ({type(exc).__name__})"
    return _versoes(saida.stdout), None


def main() -> int:
    local = _versoes(YAML.read_text(encoding="utf-8"))
    remoto, aviso = _do_origin()
    todas = local | remoto
    if not todas:
        print("nenhuma versao encontrada em docs/versoes.yaml")
        return 1

    maior = max(todas)
    if "--maior" in sys.argv:
        prox = (maior[0] + 1, 0, 0)
    elif "--correcao" in sys.argv:
        prox = (maior[0], maior[1], maior[2] + 1)
    else:
        prox = (maior[0], maior[1] + 1, 0)

    # o proximo tem de estar LIVRE dos dois lados, nao so ser o maior + 1
    while prox in todas:
        prox = (prox[0], prox[1], prox[2] + 1)

    v = ".".join(str(x) for x in prox)
    print(f"PROXIMA VERSAO LIVRE: {v}")
    print(f"  maior ja usada .......... {'.'.join(str(x) for x in maior)}")
    print(f"  no versoes.yaml local ... {len(local)} versoes")
    print(f"  no origin/main .......... {len(remoto)} versoes")

    so_remoto = sorted(remoto - local)
    if so_remoto:
        print("  ATENCAO: o origin tem versoes que esta arvore nao tem - "
              + ", ".join(".".join(str(x) for x in s) for s in so_remoto[-5:]))
        print("           traga a main antes de versionar (git merge origin/main)")
    if aviso:
        print(f"  AVISO: {aviso}; a resposta usou SO o arquivo local e pode colidir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
