"""Diz por que a integracao da Prolog nao esta funcionando — sem expor segredo.

    uv run python scripts/verificar_prolog.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.pneus import cliente as cli

print("=" * 68)
print("INTEGRACAO PROLOG (pneus)")
print("=" * 68)
print(f"  autenticacao configurada : {cli.modo_auth() or 'NENHUMA'}")
print(f"  filiais                  : {cli.filiais_configuradas() or 'FALTANDO'}")
print(f"  base                     : {cli.base_url()}")
print(f"  pronta para consultar    : {'SIM' if cli.pronto() else 'NAO'}")
print()

if not cli.modo_auth():
    print("  Falta a credencial. Configure UMA destas em Gestao > Credenciais:")
    print("   - PROLOG_TOKEN")
    print("   - PROLOG_USUARIO + PROLOG_SENHA")
    print("   - PROLOG_CLIENT_ID + PROLOG_CLIENT_SECRET (+ PROLOG_TOKEN_URL)")
    raise SystemExit(1)

if not cli.filiais_configuradas():
    print("  Ha credencial, mas falta PROLOG_FILIAIS.")
    print("  `branchOfficesId` e obrigatorio em /api/v3/tires. Listando as")
    print("  filiais disponiveis para voce escolher os ids:")
    try:
        for f in cli.Cliente().filiais():
            print(f"     id={f.get('id')}  {f.get('name') or f.get('description')}")
    except cli.PrologIndisponivel as exc:
        print(f"     nao deu para listar: {exc}")
    raise SystemExit(1)

print("  Consultando pneus...")
try:
    linhas = cli.Cliente().pneus()
except cli.PrologIndisponivel as exc:
    print(f"  FALHOU: {exc}")
    raise SystemExit(2)

from api.pneus import analise as an
k = an.analisar(linhas)["kpis"]
print(f"  OK: {k['total']} pneus · {k['rodando']} rodando")
print(f"      abaixo do limite legal : {k['abaixo_legal']} "
      f"({k['abaixo_legal_direcional']} no direcional)")
print(f"      sulco medido em        : {k['sulco_cobertura']} de {k['rodando']}")
print(f"      CPK informado em       : {k['cpk_cobertura']} de {k['total']}")
print(f"      por situacao           : {k['por_status']}")
