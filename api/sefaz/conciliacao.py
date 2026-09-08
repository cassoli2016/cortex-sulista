# -*- coding: utf-8 -*-
"""O documento recolhido contra a operação do ERP — pela CHAVE.

**ESTE É O ÚNICO ARQUIVO DO MÓDULO QUE LÊ O ERP, E ELE É OPCIONAL.**

A recolha é do CÓRTEX e funciona sem o AVA — é módulo do TMS Córtex, e vai ser
usado independente do ERP. Tudo que fala com a SEFAZ, lê o XML, guarda, imprime
e mostra na tela vive sem nada daqui. Este arquivo é a PONTE, e ponte que cai
não leva a estrada junto: a rota chama a conciliação dentro de um `try`, e
quando ela falha o cartão vira "—" em vez de zero, e a tela continua.

Apagar este arquivo inteiro tem de deixar a recolha de pé. `tests/sefaz/
test_independencia.py` cobra as duas coisas: que ninguém do núcleo importe
`api.db`, e que a tela sobreviva ao ERP fora do ar.

É AQUI QUE A RECOLHA DEIXA DE SER ARQUIVO E VIRA INFORMAÇÃO — quando há ERP.

Guardar XML cumpre uma obrigação e não decide nada. O que decide é a pergunta
que só aparece quando os dois lados estão na mesma tela:

    - a nota que o cliente diz ter mandado está no nosso CT-e?
    - o CT-e que emitimos está autorizado na SEFAZ, ou ficou preso?
    - chegou uma nota contra a Sulista que a operação não conhece?

A CHAVE É A JUNÇÃO, e ela existe dos dois lados:

    public.conhecimento.chaveacessocte      225.434 linhas, 99,99% com chave
    public.coleta_notafiscal.chaveacessonfe 602.479 linhas, 99,23% com chave

CONTRA O ERP, SEMPRE PELA CHAVE E NUNCA POR NÚMERO+SÉRIE. Número de nota se
repete entre emitentes; a chave é única no país e carrega CNPJ, modelo, série,
número e um dígito verificador. Casar por número é a receita conhecida de
juntar a nota de um fornecedor com a de outro — e o total continua plausível.

O QUE ESTE MÓDULO NÃO FAZ: escrever no ERP. Ele é somente leitura dos dois
lados, e o que produz é uma comparação. Divergência aqui é assunto de quem
opera, não de rotina automática — "a nota não está no CT-e" pode ser erro de
digitação, carga que mudou de viagem, ou nota que o cliente cancelou.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("cortex.sefaz.conciliacao")

#: O AVA é PostgreSQL 9.3: sem `FILTER (WHERE …)`, agregado condicional é
#: `CASE WHEN`. E `= ANY(%s)` em vez de `IN (…)` montado por string — chave é
#: dado de terceiro e não entra em SQL por concatenação.
_CTE_SQL = """
SELECT chaveacessocte AS chave, numero, dtemissao::date AS emissao
FROM conhecimento
WHERE chaveacessocte = ANY(%s)
"""

_NF_SQL = """
SELECT chaveacessonfe AS chave, numero, dtemissao::date AS emissao
FROM coleta_notafiscal
WHERE chaveacessonfe = ANY(%s)
"""


def _limpa(chaves) -> list[str]:
    saida = []
    for c in chaves or ():
        d = re.sub(r"[^0-9]", "", str(c or ""))
        if len(d) == 44:
            saida.append(d)
    return saida


def no_erp(chaves) -> dict[str, dict]:
    """`{chave: {onde, numero, emissao, …}}` para as chaves que o ERP conhece.

    UMA consulta para cada lado, e não uma por documento: 200 linhas na tela
    virariam 400 idas ao ERP — que é réplica de produção de terceiro e tem dia
    ruim.
    """
    chs = _limpa(chaves)
    if not chs:
        return {}
    from api import db

    achado: dict[str, dict] = {}
    for sql, onde in ((_CTE_SQL, "cte"), (_NF_SQL, "nf")):
        try:
            for r in db.query(sql, (chs,)):
                d = dict(r)
                ch = d.pop("chave")
                # Serialização converte no LIMITE do módulo: `date` estoura no
                # `render()` do JSONResponse, depois do try/except da rota.
                if d.get("emissao") is not None:
                    d["emissao"] = str(d["emissao"])
                d["onde"] = onde
                achado.setdefault(ch, d)
        except Exception as exc:  # noqa: BLE001
            # O ERP com dia ruim NÃO pode derrubar a tela da recolha: ela vale
            # sozinha. A conciliação some, e a tela diz que sumiu.
            log.warning("conciliacao: %s falhou (%s)", onde, type(exc).__name__)
    return achado


def marcar(documentos: list[dict]) -> dict:
    """Anota cada documento com o que o ERP sabe dele. Devolve o resumo.

    `no_erp` é o campo que decide: um documento recolhido que o ERP não conhece
    é uma das duas coisas, e as duas pedem alguém:

      - NF-e de entrada que ninguém lançou (compra sem nota no sistema);
      - CT-e nosso que a operação não registrou.

    E o contrário também vale, mas ele NÃO se mede aqui: CT-e do ERP que a
    SEFAZ não devolveu é assunto da recolha estar em dia, não da conciliação.
    """
    chaves = [d.get("chave") for d in documentos if d.get("chave")]
    mapa = no_erp(chaves)
    casados = 0
    for d in documentos:
        alvo = mapa.get(d.get("chave") or "")
        d["erp"] = alvo
        if alvo:
            casados += 1
    # SÓ NOTA E CT-e ENTRAM NA CONTA. Evento não tem contrapartida no ERP — ele
    # é um fato sobre outro documento —, e contá-lo como "não casado" encheria
    # o número de ruído justamente onde ele deveria acusar.
    comparaveis = [d for d in documentos if d.get("tipo") in ("nfe", "cte")]
    sem = [d for d in comparaveis if not d.get("erp")]
    return {"comparaveis": len(comparaveis), "casados": casados,
            "sem_par": len(sem)}
