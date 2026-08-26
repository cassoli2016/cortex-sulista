"""Diz por que a integracao da Monkey nao esta funcionando — sem imprimir segredo.

Uso:  uv run python scripts/verificar_monkey.py
"""
import sys
from pathlib import Path

# rodado como script solto: a raiz do projeto precisa estar no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.monkey import cliente as cli

print("=" * 66)
print("INTEGRACAO MONKEY EXCHANGE (antecipacao Tupy)")
print("=" * 66)
modo = cli.modo_auth()
ids = cli.seller_ids()
host_fixo = bool(cli._cred("MONKEY_BASE_URL"))
print(f"  autenticacao configurada : {modo or 'NENHUMA'}")
if modo == "oauth":
    print(f"  grant_type               : {cli.grant_type()}")
    print(f"  refresh_token            : "
          f"{'configurado' if cli._cred('MONKEY_REFRESH_TOKEN') else 'nao'}")
print(f"  sellerIds ({len(ids)})            : {', '.join(ids) or 'FALTANDO'}")
print(f"  ambiente                 : {cli.ambiente()}"
      f"  ({cli.base_url()}{'  <- MONKEY_BASE_URL' if host_fixo else ''})")
print(f"  pronta para chamar        : {'SIM' if cli.configurado() else 'NAO'}")
print()

if not cli.configurado():
    print("  O que falta:")
    if not modo:
        print("   - MONKEY_TOKEN, ou MONKEY_CLIENT_ID + MONKEY_CLIENT_SECRET")
    if not ids:
        print("   - MONKEY_SELLER_IDS (um por CNPJ, separados por virgula)")
    print()
    print("  Configure na tela de Gestao > Credenciais. Nada disso vai para o")
    print("  git: o cofre fica em data/credenciais.json, com permissao 0600.")
    raise SystemExit(1)

print("  Chamando a API...")
try:
    c = cli.Cliente()
    por_seller = c.recebiveis_por_seller(tamanho=50, maximo_paginas=2)
except cli.MonkeyNaoConfigurado as exc:
    print(f"  CONFIGURACAO: {exc}")
    raise SystemExit(1)
except cli.MonkeyIndisponivel as exc:
    print(f"  FALHOU: {exc}")
    raise SystemExit(2)

linhas = [r for lote in por_seller.values() for r in lote]
# seller que volta VAZIO aparece: com 5 CNPJs, um sem resposta somado aos
# outros quatro nao deixaria rastro nenhum
for s_id, lote in por_seller.items():
    marca = "" if lote else "   <- nada (confira o sellerId neste ambiente)"
    print(f"      seller {s_id}: {len(lote)} recebivel(is){marca}")

from api.monkey import normaliza as nz
d = nz.lote(linhas)
r = d["resumo"]
print(f"  OK: {r['linhas']} recebivel(is) nas 2 primeiras paginas")
print(f"      antecipaveis: {r['antecipaveis']} · R$ {r['valor_antecipavel']:,.2f}")
print(f"      por status: {r['por_status']}")
print(f"      sacados: {r['sacados'][:5]}")
