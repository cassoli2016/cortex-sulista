# scripts/emitir_homologacao.py
"""Monta, assina e transmite UM CT-e de contrapartida em HOMOLOGACAO.

Homologacao e um ambiente de teste da SEFAZ: o documento autorizado la NAO tem
valor fiscal, nao escritura nada e nao gera obrigacao. Producao esta fechada no
modulo `api/contrapartida/emissao.py` enquanto o enquadramento fiscal nao for
definido pela contabilidade - e nao e este script que vai abrir.

O ENQUADRAMENTO ABAIXO E TECNICO, NAO FISCAL
============================================
As seis definicoes ainda estao pendentes. Os valores aqui servem para exercitar
a assinatura e a transmissao, e foram escolhidos pela evidencia do proprio ERP
(a Sulista usa CFOP 6351 + subcontratacao quando ELA e a subcontratada) e pelo
cadastro do agregado (optante do Simples). Trocar quando a resposta vier.

Uso:  uv run --no-sync python scripts/emitir_homologacao.py <CHAVE> [--numero N]
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from api.contrapartida import documento, emissao  # noqa: E402

# CT-e piloto: Parizotto, placa EQU3D30, SP->SP, embarque com UM documento so
# (sem rateio). Escolhido por ser o caso mais simples que existe na base.
CHAVE_PILOTO = "35260876104397000204570010003585231063585236"

# Estado das definicoes em 26/08/2026. DECIDIDO = resposta da area; PENDENTE =
# valor escolhido so para exercitar a transmissao, trocar quando responderem.
# DECIDIDO pela area em 26/08/2026: nao ha dispensa (o agregado emite) e o
# enquadramento e SUBCONTRATACAO. Restam a base do valor e a CST do ICMS.
ENQUADRAMENTO = documento.Enquadramento(
    # 5351 no mesmo estado, 6351 cruzando divisa. Sao dois porque 88% das
    # viagens de agregado sao interestaduais - um CFOP fixo erraria a maioria.
    cfop_interno="5351",
    cfop_interestadual="6351",
    # DECIDIDO: rateio proporcional ao valor cobrado do cliente.
    criterio_rateio="cobrado",
    tp_serv="1",              # DECIDIDO: subcontratacao (base 0 do SCHEMA)
    # DECIDIDO: "use o que ja existe" - a tributacao sai do ERP, documento a
    # documento (regime do emitente manda; nao sendo optante, vale a CST e a
    # aliquota que o ERP ja calculou para aquela rota).
    grupo_icms="AUTO",
    cst_icms="",
    p_icms=None,
    # DECIDIDO e CONFIRMADO em 26/08/2026: o valor pago ao agregado, que e a
    # coluna do frete de compra - a mesma que alimenta o PEF da viagem. O
    # "contrato de transporte" citado pela area E este valor; os campos de PEF
    # da replica nao servem (ver docs/contrapartida-perguntas-contabilidade.md).
    # Como o pagamento e por VIAGEM e o documento e por CT-e, os 48% que
    # dividem viagem passam pelo rateio acima.
    base_valor="fretecompra",
    toma="4",                 # a Sulista como tomadora ("outros")
    referenciar_original=True,  # o vinculo com o nosso CT-e
)
ENQUADRAMENTO_TECNICO = ENQUADRAMENTO   # nome antigo, ainda usado no texto


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chave", nargs="?", default=CHAVE_PILOTO)
    ap.add_argument("--numero", type=int, default=None)
    # Identidade do SISTEMA, nao e-mail pessoal: quem roda o script na
    # bancada varia, e a trilha tem de dizer que foi o CORTEX. Emissao pela
    # tela continua exigindo o usuario logado.
    ap.add_argument("--quem", default=emissao.IDENTIDADE_SISTEMA)
    a = ap.parse_args()

    print("AMBIENTE: HOMOLOGACAO - o documento nao tem valor fiscal.")
    print("Enquadramento TECNICO (a contabilidade ainda nao respondeu):")
    for campo, valor in vars(ENQUADRAMENTO_TECNICO).items():
        print(f"   {campo:22} {valor!r}")

    d = documento.dados(a.chave)
    print(f"\nEmitente: {d['emit_nome']} ({d['emit_cnpj']}) - {d['emit_uf']}")
    print(f"Tomador:  {d['toma_apelido']} ({d['toma_cnpj']})")
    print(f"Remetente:    {d['rem_nome']} ({d['rem_cnpj']})")
    print(f"Destinatario: {d['dest_nome']} ({d['dest_cnpj']})")
    print(f"Notas:    {len(d['notas'])} NF-e")
    print(f"Trecho:   {d['ini_xmun']}/{d['ufcoleta']} -> "
          f"{d['fim_xmun']}/{d['ufentrega']}")
    print(f"Valor:    R$ {documento.valor(d, ENQUADRAMENTO_TECNICO)}")
    print(f"Refere:   {d['chave_original']}\n")

    try:
        r = emissao.transmitir(a.chave, ENQUADRAMENTO_TECNICO, quem=a.quem,
                               numero=a.numero)
    except Exception as exc:  # noqa: BLE001
        print(f"FALHOU: {type(exc).__name__}: {str(exc)[:500]}")
        return 1

    print(f"CT-e {r['serie']}/{r['numero']}  chave {r['chave']}")
    print(f"  lote      {r['cStat_lote']} {r['xMotivo_lote']}")
    print(f"  documento {r['cStat']} {r['xMotivo']}")
    print(f"  protocolo {r['protocolo']}")
    print("  AUTORIZADO" if r["autorizado"] else "  nao autorizado")
    return 0 if r["autorizado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
