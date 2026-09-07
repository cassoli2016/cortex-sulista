# -*- coding: utf-8 -*-
"""Recolhe da SEFAZ os documentos fiscais emitidos contra a Sulista.

POR QUE EXISTE: a nota de entrada chega hoje por e-mail do fornecedor, quando
chega. O serviço nacional de Distribuição de DFe entrega ao destinatário tudo
que foi emitido contra o CNPJ dele — é a única fonte que não depende de alguém
lembrar de mandar o XML, e o XML é a obrigação de cinco anos.

A varredura é POR CNPJ, e a Sulista tem dez ativos (um por filial): o serviço
mantém uma sequência de NSU separada para cada um.

Uso:
  uv run --no-sync python scripts/coletar_dfe.py                 # todas as caixas
  uv run --no-sync python scripts/coletar_dfe.py 76104397000123  # uma só
  uv run --no-sync python scripts/coletar_dfe.py --forcar        # ignora o freio nosso

SAI COM 0 QUANDO NÃO HÁ O QUE FAZER. Sem certificado não é falha, é instalação
incompleta — e uma tarefa agendada marcada como quebrada onde a integração
ainda não foi ligada ensina a ignorar o vermelho do agendador.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.sefaz import armazenamento as arm, distribuicao as dist  # noqa: E402


def main(argv: list[str]) -> int:
    forcar = "--forcar" in argv
    alvos = [a for a in argv[1:] if not a.startswith("--")]

    caixas = arm.caixas(so_ativas=True)
    if alvos:
        caixas = [c for c in caixas if c["cnpj"] in alvos]
    if not caixas:
        print("dfe: nenhuma caixa ativa na recolha. Abra com "
              "`scripts/abrir_caixas_dfe.py`.")
        return 0

    total = {"caixas": 0, "novos": 0, "completados": 0, "pulou": 0, "erros": 0}
    for c in caixas:
        cnpj, uf = c["cnpj"], (c.get("uf") or "PR")
        try:
            r = dist.recolher(cnpj, uf, ambiente=dist.PRODUCAO, forcar=forcar)
        except dist.SemCertificado as exc:
            # Instalação incompleta: DIZ o que falta e segue para a próxima
            # caixa. Uma filial sem certificado não pode parar as outras nove.
            print("  %s: %s" % (cnpj, exc))
            total["pulou"] += 1
            continue
        except Exception as exc:  # noqa: BLE001
            # O TIPO, nunca o texto: a conninfo e o caminho do certificado
            # passam por aqui em algumas falhas.
            print("  %s: FALHOU (%s)" % (cnpj, type(exc).__name__))
            total["erros"] += 1
            continue

        total["caixas"] += 1
        if "pulou" in r:
            print("  %s: %s" % (cnpj, r["pulou"]))
            total["pulou"] += 1
            continue
        total["novos"] += r["novos"]
        total["completados"] += r["completados"]
        print("  %s: %d lote(s) · %d novo(s) · %d completado(s) · %s %s"
              % (cnpj, r["lotes"], r["novos"], r["completados"],
                 r["cstat"], r["motivo"][:40]))

    print()
    print("dfe: %d caixa(s) varrida(s) · %d documento(s) novo(s) · "
          "%d completado(s) · %d pulada(s) · %d erro(s)"
          % (total["caixas"], total["novos"], total["completados"],
             total["pulou"], total["erros"]))
    # ERRO EM UMA CAIXA NÃO DERRUBA A TAREFA. O que derruba é nenhuma ter
    # rodado: aí não é dia ruim de uma filial, é a integração parada.
    return 1 if (total["erros"] and not total["caixas"]) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
