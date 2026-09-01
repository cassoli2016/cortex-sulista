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
print(f"  autenticacao configurada : {modo or 'NENHUMA'}")
print(f"  sellerIds                : {len(cli.seller_ids()) or 'FALTANDO'}"
      f" (um por CNPJ, separados por virgula)")
print(f"  ambiente                 : {cli.ambiente()}  ({cli.base_url()})")
print(f"  pronta para chamar        : {'SIM' if cli.configurado() else 'NAO'}")
print()

if not cli.configurado():
    print("  O que falta:")
    if not modo:
        print("   - MONKEY_TOKEN, ou os QUATRO do OAuth2: MONKEY_CLIENT_ID +")
        print("     MONKEY_CLIENT_SECRET + MONKEY_USERNAME + MONKEY_PASSWORD")
        print("     (o primeiro token e grant_type=password - resposta oficial")
        print("     da Monkey em 01/09/2026; a renovacao usa refresh_token)")
    if not cli.seller_id():
        print("   - MONKEY_SELLER_ID (o {id} de /v2/sellers/{id}/receivables,")
        print("     um por CNPJ, separados por virgula)")
    print()
    print("  Configure na tela de Gestao > Credenciais. Nada disso vai para o")
    print("  git: o cofre fica em data/credenciais.json, com permissao 0600.")
    raise SystemExit(1)

print("  Chamando a API (2 primeiras paginas de CADA seller)...")
linhas = []
try:
    c = cli.Cliente()
    for sid in cli.seller_ids():
        c.seller = sid
        lote_seller = c.recebiveis(tamanho=50, maximo_paginas=2)
        print(f"    seller ...{sid[-4:]}: {len(lote_seller)} recebivel(is)")
        linhas.extend(lote_seller)
except cli.MonkeyIndisponivel as exc:
    print(f"  FALHOU: {exc}")
    raise SystemExit(2)

from api.monkey import normaliza as nz
d = nz.lote(linhas)
r = d["resumo"]
print(f"  OK: {r['linhas']} recebivel(is) somando os sellers")
print(f"      antecipaveis: {r['antecipaveis']} · R$ {r['valor_antecipavel']:,.2f}")
print(f"      por status: {r['por_status']}")
print(f"      sacados: {r['sacados'][:5]}")
