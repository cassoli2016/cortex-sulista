# -*- coding: utf-8 -*-
"""Abre uma caixa de recolha da SEFAZ para cada filial ATIVA da Sulista.

O CNPJ E A UF SAEM DO ERP, e não de uma lista escrita aqui. A tabela `filial`
do AVA tem o cadastro vivo: quando uma filial abre, fecha ou muda de estado, é
lá que muda — e uma lista à mão neste arquivo envelheceria calada, que é a
forma exata de uma filial parar de recolher sem ninguém saber.

FILIAL INATIVA FICA DE FORA. Consultar o CNPJ de uma filial fechada gastaria a
cota de um serviço que freia consulta sem resultado (cStat 656), para uma caixa
que não recebe mais nota.

Uso:
  uv run --no-sync python scripts/abrir_caixas_dfe.py           # mostra e pergunta
  uv run --no-sync python scripts/abrir_caixas_dfe.py --aplicar
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402
from api.sefaz import armazenamento as arm  # noqa: E402

#: A raiz do CNPJ da Sulista. O ERP guarda também filial de terceiro em algumas
#: instalações; recolher a caixa de quem não é a casa seria consultar a SEFAZ
#: por um CNPJ que não temos certificado nem autorização para consultar.
RAIZ_SULISTA = "76104397"

FILIAIS_SQL = """
SELECT codigo, apelido, cnpj, digitocnpj, uf, cidade, ativoinativo
FROM filial
ORDER BY codigo
"""


def _cnpj14(base, digito) -> str:
    """O ERP guarda o CNPJ SEM o dígito e o dígito à parte, e nem sempre com
    zero à esquerda. Montar isso na mão é onde nasce um CNPJ de 13 dígitos que
    a SEFAZ rejeita com uma mensagem que não fala de dígito nenhum."""
    d = re.sub(r"[^0-9]", "", str(base or ""))
    dv = re.sub(r"[^0-9]", "", str(digito or ""))
    inteiro = (d + dv) if len(d) == 12 else d
    return inteiro.rjust(14, "0")[-14:]


def main(argv: list[str]) -> int:
    aplicar = "--aplicar" in argv
    linhas = db.query(FILIAIS_SQL)

    print("%-5s %-22s %-16s %-3s %-16s %s"
          % ("cod", "apelido", "cnpj", "uf", "cidade", "situacao"))
    alvos = []
    for f in linhas:
        cnpj = _cnpj14(f["cnpj"], f["digitocnpj"])
        ativa = str(f.get("ativoinativo")) == "1"
        da_casa = cnpj.startswith(RAIZ_SULISTA)
        situacao = ("recolhe" if (ativa and da_casa)
                    else "INATIVA no ERP" if not ativa
                    else "outra raiz de CNPJ")
        print("%-5s %-22s %-16s %-3s %-16s %s"
              % (f["codigo"], (f["apelido"] or "")[:22], cnpj, f["uf"] or "",
                 (f["cidade"] or "")[:16], situacao))
        if ativa and da_casa:
            alvos.append((cnpj, (f["apelido"] or "").strip(), f["uf"] or ""))

    print()
    if not alvos:
        print("Nenhuma filial ativa da raiz %s — nada a abrir." % RAIZ_SULISTA)
        return 0
    if not aplicar:
        print("%d caixa(s) a abrir. Rode de novo com --aplicar." % len(alvos))
        return 0

    for cnpj, apelido, uf in alvos:
        antes = arm.caixa(cnpj)
        arm.abrir_caixa(cnpj, apelido, uf)
        # REABRIR NÃO ZERA O NSU (regra do próprio `abrir_caixa`), e dizer isso
        # aqui evita a pergunta "rodar de novo apaga o que já recolhi?".
        print("  %s %-22s %s" % (cnpj, apelido[:22],
                                 "ja existia (NSU preservado: %s)" % antes["ultimo_nsu"]
                                 if antes else "aberta"))
    print()
    print("%d caixa(s) na recolha. Agora rode scripts/coletar_dfe.py." % len(alvos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
