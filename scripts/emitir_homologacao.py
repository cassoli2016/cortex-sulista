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

ENQUADRAMENTO_TECNICO = documento.Enquadramento(
    cfop="5351",              # prestacao a outro transportador, dentro do estado
    tp_serv="1",              # subcontratacao (base 0 do SCHEMA, nao do ERP)
    grupo_icms="ICMSSN",      # emitente optante do Simples
    cst_icms="90",
    p_icms=None,
    base_valor="fretecompra",  # o que a Sulista PAGA ao agregado
    toma="4",                 # tomador "outros" - a Sulista, com CNPJ
    referenciar_original=True,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chave", nargs="?", default=CHAVE_PILOTO)
    ap.add_argument("--numero", type=int, default=None)
    ap.add_argument("--quem", default="cassoli2013@gmail.com")
    a = ap.parse_args()

    print("AMBIENTE: HOMOLOGACAO - o documento nao tem valor fiscal.")
    print("Enquadramento TECNICO (a contabilidade ainda nao respondeu):")
    for campo, valor in vars(ENQUADRAMENTO_TECNICO).items():
        print(f"   {campo:22} {valor!r}")

    d = documento.dados(a.chave)
    print(f"\nEmitente: {d['emit_nome']} ({d['emit_cnpj']}) - {d['emit_uf']}")
    print(f"Tomador:  {d['toma_apelido']} ({d['toma_cnpj']})")
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
    print(f"  AUTORIZADO" if r["autorizado"] else "  nao autorizado")
    return 0 if r["autorizado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
