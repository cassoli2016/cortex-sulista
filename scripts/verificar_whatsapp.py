"""Diz por que o envio de WhatsApp nao esta funcionando - sem imprimir segredo.

Uso:  uv run python scripts/verificar_whatsapp.py

Este script NAO envia mensagem nenhuma: ele so pergunta a Z-API se a instancia
esta pareada. Mandar uma mensagem "de teste" a partir da linha de comando seria
o unico caminho de envio do sistema que escapa do limite diario e da trilha -
e e justamente esse tipo de atalho que faz um numero ser banido.
"""
import sys
from pathlib import Path

# rodado como script solto: a raiz do projeto precisa estar no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.whatsapp import cliente as cli          # noqa: E402
from api.whatsapp import config as cfg           # noqa: E402
from api.whatsapp import registro                # noqa: E402

print("=" * 66)
print("ENVIO DE WHATSAPP (Z-API)")
print("=" * 66)

c = cfg.ler()
print(f"  instancia            : {cli.instancia_mascarada() or 'FALTANDO'}")
print(f"  token da instancia   : {'guardado' if cli.token() else 'FALTANDO'}")
print(f"  token de seguranca   : {'guardado' if cli.client_token() else 'nao configurado'}")
print(f"  envio ligado         : {'SIM' if c['ativo'] else 'NAO'}")
print(f"  limite por dia       : {c['limite_dia']} destinatarios diferentes")
print(f"  janela de envio      : {c['janela_inicio']} as {c['janela_fim']}"
      f"  (agora {'DENTRO' if cfg.dentro_da_janela() else 'FORA'})")
print()

if not cli.configurado():
    print("  O que falta:")
    if not cli.instancia():
        print("   - ZAPI_INSTANCIA (o {id} de /instances/{id}/token/... no painel Z-API)")
    if not cli.token():
        print("   - ZAPI_TOKEN (o token daquela instancia)")
    print()
    print("  Configure em Gestao > WhatsApp. Nada disso vai para o git: o cofre")
    print("  fica em data/credenciais.json, com permissao 0600.")
    raise SystemExit(1)

print("  Perguntando o estado da instancia (nenhuma mensagem e enviada)...")
est = cli.estado(force=True)
if not est["ok"]:
    print(f"  FALHOU: {est['erro']}")
    raise SystemExit(2)

print(f"  conectado            : {'SIM' if est['conectado'] else 'NAO'}")
print(f"  celular na internet  : {'SIM' if est['celular'] else 'NAO'}")
if est["erro"]:
    print(f"  aviso da Z-API       : {est['erro']}")
print()

if not est["conectado"]:
    print("  A instancia NAO esta pareada a um WhatsApp. Enquanto isso durar o")
    print("  CORTEX recusa os envios de proposito: a Z-API aceitaria as")
    print("  mensagens (HTTP 200) e as guardaria numa fila de ate mil,")
    print("  disparando tudo de uma vez quando o aparelho voltasse.")
    print("  Leia o QR Code novamente no painel da Z-API.")
    raise SystemExit(3)

try:
    r = registro.resumo()
    print(f"  destinatarios hoje   : {r['hoje']} de {c['limite_dia']}")
    print(f"  trilha               : {r['total']} envios ({r['ok']} ok, "
          f"{r['falha']} recusados/falhos)")
except Exception as exc:   # noqa: BLE001
    print(f"  trilha indisponivel  : {type(exc).__name__} "
          "(o banco local do CORTEX nao respondeu)")

print()
if not c["ativo"]:
    print("  Tudo conectado, mas o ENVIO ESTA DESLIGADO em Gestao > WhatsApp.")
    print("  Configurar nao e autorizar a disparar - ligue de proposito.")
    raise SystemExit(4)

print("  Pronto para enviar.")
