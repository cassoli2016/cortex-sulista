"""Diz se o botão de report vai funcionar — sem imprimir o token.

    uv run python scripts/verificar_report.py

Sem isto, "o botão não aparece" é diagnóstico cego: pode ser chave ausente no
.env, repositório errado, token sem permissão de Issues ou sem permissão de
Contents (que só falha na hora de subir o anexo, com o report já digitado).
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402,F401  (o import é o que carrega o .env)
from api.reports import github as gh  # noqa: E402


def _diz(ok: bool, texto: str) -> None:
    print(("  OK   " if ok else "  FALTA") + "  " + texto)


def main() -> int:
    print("\nCÓRTEX — verificação do botão de report\n")
    repo = gh.repo_configurado()
    _diz(bool(repo), f"REPORT_REPO = {repo or '(vazio) — defina no .env'}")
    _diz(gh.configurado(), "GITHUB_TOKEN presente no .env")
    if not gh.configurado():
        print("\nO botão não vai aparecer no painel (recurso desligado, sem erro).\n"
              "Gere um PAT fine-grained em "
              "https://github.com/settings/personal-access-tokens/new\n"
              "com Contents: write + Issues: write SÓ no repositório de reports.\n")
        return 1

    cli = gh.do_ambiente()
    cab = cli._cabecalhos()
    with httpx.Client(timeout=15) as http:
        try:
            r = http.get(f"{gh.API}/repos/{repo}", headers=cab)
        except httpx.HTTPError as exc:
            print(f"\nNão foi possível falar com o GitHub: {exc}\n")
            return 1
        if r.status_code == 401:
            _diz(False, "o token foi recusado (401) — expirou ou está incompleto")
            return 1
        if r.status_code == 404:
            _diz(False, f"o token não enxerga {repo} (404) — repositório errado "
                        "ou fora do escopo do PAT")
            return 1
        if r.status_code >= 400:
            _diz(False, f"GitHub respondeu {r.status_code}")
            return 1

        info = r.json()
        _diz(True, f"repositório acessível · privado: {info.get('private')}")
        if not info.get("private"):
            print("\n  ATENÇÃO: o repositório de destino é PÚBLICO. Print do painel\n"
                  "  carrega faturamento, cliente e PII. Corrija antes de usar.\n")
            return 1
        _diz(bool(info.get("has_issues")), "issues habilitadas no repositório")

        perm = (info.get("permissions") or {})
        _diz(bool(perm.get("push")), "token pode escrever (anexo e issue)")
        if not perm.get("push"):
            print("\n  O PAT precisa de Contents: write E Issues: write. Só leitura\n"
                  "  deixa o report falhar na hora de enviar.\n")
            return 1

    print("\nTudo pronto: o botão aparece no painel e o envio deve funcionar.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
