# scripts/spike_sefaz.py
"""PROVA DE CONCEITO: falar com a SEFAZ em HOMOLOGACAO. Nao emite nada.

O que este teste responde
-------------------------
Sabemos que o certificado assina (scripts/testar_assinatura.py). O que ainda
nao sabemos e se a pilha inteira fecha: mTLS com o certificado do AGREGADO,
resolucao do endpoint da UF certa, SOAP, e resposta da SEFAZ.

`status_servico` e o "ola mundo" dessa integracao: usa exatamente o mesmo
caminho de rede e autenticacao de uma emissao, e nao produz documento nenhum -
nem em homologacao. Se ele responde, a unica coisa que falta provar e a
montagem do XML.

AMBIENTE = 2 (homologacao) fixo neste script, de proposito. Producao aqui seria
um erro de uma tecla com consequencia fiscal.

Uso:  uv run python scripts/spike_sefaz.py <CNPJ> [UF]
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from api.contrapartida import cadastro  # noqa: E402

AMBIENTE_HOMOLOGACAO = "2"


def _corrigir_endpoint(m) -> None:
    """DEFEITO 1 da biblioteca: `get_service_url` so resolve os grupos SVRS e
    SVSP. Estado com SEFAZ propria (PR, MG, MS, MT) cai no `else`, recebe a
    STRING da sigla no lugar do dicionario de configuracao e quebra na linha
    seguinte. O PR - onde esta o primeiro agregado cadastrado - e um deles.

    A configuracao do estado EXISTE no modulo; a funcao so nunca chega nela.
    """
    _orig = m.get_service_url

    def resolvido(sigla, service, ambiente):
        cfg = getattr(m, sigla, None)
        if (isinstance(cfg, dict) and sigla not in m.SVSP_STATES
                and sigla not in m.SVRS_STATES):
            amb = (m.AMBIENTE_PRODUCAO if ambiente == 1
                   else m.AMBIENTE_HOMOLOGACAO)
            return "https://" + cfg[amb]["servidor"] + "/" + cfg[amb][service]
        return _orig(sigla, service, ambiente)

    m.get_service_url = resolvido


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: spike_sefaz.py <CNPJ> [UF]")
        return 2
    cnpj = "".join(c for c in sys.argv[1] if c.isdigit())
    uf = (sys.argv[2] if len(sys.argv) > 2 else "").upper()

    if not uf:
        # a UF do EMITENTE sai do cadastro: usar a da Sulista mandaria o
        # pedido para a SEFAZ errada, que responde "nao e meu contribuinte"
        from api import db
        linha = db.query("SELECT uf FROM cadastro WHERE codigo = %(c)s",
                         {"c": cnpj})
        uf = ((linha[0]["uf"] if linha else "") or "").strip().upper()
        if not uf:
            print("UF do emitente nao esta no cadastro - informe na linha de comando.")
            return 2
    reg = (cadastro.mapa().get(cnpj) or {}).get("certificado")
    senha = cadastro.ler_senha(cnpj)
    if not (reg and senha):
        print(f"Sem certificado ou senha no cofre para {cnpj}.")
        return 1
    arq = cadastro.DIR_CERT / (reg.get("arquivo") or "")
    if not arq.exists():
        print(f"Arquivo nao encontrado: {arq.name}")
        return 1

    import erpbrasil.edoc.cte as mod
    from erpbrasil.assinatura.certificado import Certificado
    from erpbrasil.edoc.cte import SIGLA_ESTADO, CTe
    from erpbrasil.transmissao import TransmissaoSOAP

    _corrigir_endpoint(mod)

    # a biblioteca quer o codigo IBGE, nao a sigla - e a UF tem de ser a do
    # EMITENTE (cada SEFAZ so atende os seus), nao a da Sulista
    if uf not in SIGLA_ESTADO:
        print(f"UF desconhecida: {uf}")
        return 2
    cod_uf = SIGLA_ESTADO[uf]

    print("=" * 74)
    print(f"SEFAZ {uf} — HOMOLOGACAO — certificado de {reg.get('titular')}")
    print("=" * 74)

    cert = Certificado(str(arq), senha)
    transmissao = TransmissaoSOAP(cert)
    cte = CTe(transmissao, cod_uf, ambiente=AMBIENTE_HOMOLOGACAO)

    try:
        r = cte.status_servico()
    except Exception as exc:  # noqa: BLE001
        print(f"  FALHOU: {type(exc).__name__}: {str(exc)[:300]}")
        print()
        if "has no attribute 'export'" in str(exc):
            print()
            print("  DEFEITO 2 da biblioteca: erpbrasil.edoc serializa com a")
            print("  API do generateDS (.export()), mas as classes de CT-e vem")
            print("  do nfelib, que hoje usa xsdata. As duas versoes instaladas")
            print("  nao conversam - o caminho de CT-e nao esta exercitado.")
        else:
            print("  Causas comuns, em ordem de frequencia:")
            print("   - a UF nao e a do emitente (cada SEFAZ so atende os seus);")
            print("   - o certificado nao esta habilitado em homologacao;")
            print("   - o servico da SEFAZ esta fora (acontece, e e rotina).")
        return 1

    print(f"  resposta recebida: {type(r).__name__}")
    for campo in ("cStat", "xMotivo", "tpAmb", "cUF", "dhRecbto", "verAplic"):
        v = getattr(r, campo, None)
        if v is None and hasattr(r, "resposta"):
            v = getattr(r.resposta, campo, None)
        if v is not None:
            print(f"    {campo:10} {v}")
    print()
    print("Se veio cStat 107, o servico esta em operacao e a pilha inteira")
    print("fecha: certificado, mTLS, endpoint da UF, SOAP e resposta. O que")
    print("resta provar e so a montagem do XML do CT-e.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
