# -*- coding: utf-8 -*-
"""Le a caixa `xml@sulista.com.br` e guarda o que for documento fiscal.

    uv run python scripts/coletar_xml_email.py            # a janela padrao (30 dias)
    uv run python scripts/coletar_xml_email.py --dias 90  # varredura maior
    uv run python scripts/coletar_xml_email.py --estado   # so diz como esta

E O QUE A TAREFA AGENDADA RODA, de 30 em 30 minutos.

POR QUE 30 MINUTOS, E POR QUE ISSO NAO TEM O PROBLEMA DA OUTRA PORTA
====================================================================

A recolha da SEFAZ e limitada pelo FREIO do fornecedor: ela pune consulta sem
resultado (cStat 656, uma hora de castigo), e por isso a tarefa dela roda de 20
em 20 minutos com freio no script.

Aqui nao ha nada disso. O Microsoft Graph nao pune leitura, e uma listagem que
nao acha mensagem nova custa uma requisicao e alguns milissegundos. O que
decide a cadencia e o outro lado: alguem mandou o XML e precisa dele na
operacao AGORA. Meia hora e o intervalo em que a pessoa ainda nao teve tempo de
ligar perguntando se chegou.

E A COLETA E IDEMPOTENTE NOS DOIS NIVEIS -- mensagem ja processada e pulada
pelo id, arquivo repetido cai no `sha256`. Rodar duas vezes seguidas nao
duplica nada; rodar depois de uma queda continua de onde parou sem pedir nada
a ninguem.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from api.sefaz import caixa_email  # noqa: E402


def _num(argv: list[str], flag: str, padrao: int) -> int:
    if flag not in argv:
        return padrao
    i = argv.index(flag)
    if i + 1 >= len(argv):
        return padrao
    try:
        return int(argv[i + 1])
    except ValueError:
        return padrao


def main(argv: list[str]) -> int:
    if "--estado" in argv:
        e = caixa_email.estado()
        print("caixa        :", e["caixa"] or "(nao configurada)")
        print("configurada  :", "sim" if e["configurada"] else
              "NAO - falta: %s" % ", ".join(e["falta"]))
        print("ultima coleta:", e["ultima_coleta"] or "nunca")
        print("ultimo ok    :", e["ultimo_sucesso"] or "nunca")
        print("ultimo erro  :", e["ultimo_erro"] or "-")
        print("mensagens    :", e["mensagens"], "(%d sem documento)" % e["vazias"])
        a = e["arquivos"]
        print("arquivos     : %d guardados (%d por e-mail, %d enviados na tela)"
              % (a["total"], a["email"], a["upload"]))
        return 0

    dias = _num(argv, "--dias", caixa_email.DIAS_PADRAO)
    try:
        placar = caixa_email.coletar(dias=dias)
    except caixa_email.NaoConfigurada as exc:
        # NAO E FALHA, E INSTALACAO INCOMPLETA -- e a diferenca importa para a
        # tarefa agendada: sair com erro aqui faria o Windows registrar falha a
        # cada meia hora numa instalacao que so nao foi terminada.
        print("nao configurada:", exc)
        print()
        print("Configure em Administracao > Integracoes > Caixa de XML.")
        return 0
    except caixa_email.Indisponivel as exc:
        print("indisponivel:", exc)
        return 1

    print("caixa       :", placar["caixa"])
    print("mensagens   : %d na janela de %d dias (%d novas)"
          % (placar["mensagens"], dias, placar["novas"]))
    print("documentos  : %d novo(s), %d repetido(s)"
          % (placar["documentos"], placar["repetidos"]))
    print("ignorados   :", placar["ignorados"])
    if placar["falhas"]:
        print("falhas      :", placar["falhas"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
