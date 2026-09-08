# -*- coding: utf-8 -*-
"""Procurar um documento: no que já temos primeiro, na SEFAZ só se faltar.

POR QUE A ORDEM IMPORTA, e não é economia de rede
=================================================

A SEFAZ **conta** consulta. Ela freia quem pergunta demais (cStat 656, cerca de
uma hora de castigo por CNPJ), e uma tela de busca é o lugar onde alguém digita
a mesma chave três vezes porque não viu o resultado. Ir ao banco primeiro faz a
terceira digitação custar zero.

E há o motivo que decide sozinho: **o documento que já está aqui é o mesmo, e
está guardado.** Buscar fora o que já se tem não traz nada de novo — traz o
risco de gastar a cota e ficar sem poder buscar o que falta de verdade.

A ORDEM É, ENTÃO:

    1. banco local, por chave       -> devolve na hora, `origem="local"`
    2. SEFAZ, por chave             -> guarda e devolve, `origem="sefaz"`
    3. não é da Sulista             -> diz ISSO, e não "não encontrado"

O TERCEIRO CASO TEM NOME PRÓPRIO de propósito. A distribuição só entrega
documento em que o CNPJ do certificado é PARTE — destinatário, transportador,
emitente ou tomador. "Não encontrei" manda a pessoa conferir se digitou certo;
"a Sulista não participa deste documento" encerra a procura. São respostas
diferentes para situações diferentes, e confundi-las custa o tempo de quem
procura.
"""
from __future__ import annotations

import logging
import re

from . import armazenamento as arm, distribuicao as dist

log = logging.getLogger("cortex.sefaz.busca")


def _limpo(chave: str) -> str:
    return re.sub(r"[^0-9]", "", chave or "")


def local(chave: str) -> dict | None:
    """O documento no banco da casa, por chave. Sem tocar na SEFAZ.

    OLHA AS DUAS PORTAS: a caixa da SEFAZ e o XML que chegou por e-mail. É aqui
    que a segunda porta paga o que ela custou — a nota que a SEFAZ nunca vai
    entregar (porque a Sulista não é parte nela) responde nesta busca, e a
    pessoa que digitou a chave não precisa saber por onde ela entrou.

    A chave se repete: a mesma nota chega ao destinatário e ao transportador,
    cada um na sua caixa, e ainda pode chegar por e-mail. **Vence o COMPLETO** —
    entre duas linhas da mesma nota, a que tem o XML autorizado é a que serve.
    Empate resolve pela mais recente.
    """
    ch = _limpo(chave)
    if len(ch) != dist.CHAVE_DIGITOS:
        return None
    with arm.pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cnpj, nsu, tipo, chave, emitente, emitente_nome, "
            "       destinatario, valor, emitido_em, situacao, completo, "
            "       recebido_em, origem, sha256 "
            "FROM (" + arm.fonte() + ") d WHERE chave = %s "
            "ORDER BY completo DESC, recebido_em DESC LIMIT 1", (ch,))
        r = cur.fetchone()
    if not r:
        return None
    d = dict(r)
    from datetime import datetime
    for c in ("emitido_em", "recebido_em"):
        if isinstance(d.get(c), datetime):
            d[c] = d[c].isoformat()
    return d


def por_chave(chave: str, *, cnpj: str = "", uf: str = "",
              buscar_fora: bool = True, cliente=None) -> dict:
    """Local primeiro; SEFAZ só se faltar. Nunca levanta por "não achou".

    `cnpj`/`uf` dizem POR QUAL CAIXA perguntar lá fora. Sem eles, a primeira
    caixa ativa com certificado — que na prática é a matriz, e é a que tem a
    chance de participar do documento.
    """
    ch = _limpo(chave)
    if len(ch) != dist.CHAVE_DIGITOS:
        return {"ok": False, "origem": None,
                "mensagem": "A chave de acesso tem %d dígitos; vieram %d."
                            % (dist.CHAVE_DIGITOS, len(ch))}

    achado = local(ch)
    if achado:
        return {"ok": True, "origem": "local", "documento": achado,
                "mensagem": "já estava guardado aqui"}
    if not buscar_fora:
        return {"ok": False, "origem": "local",
                "mensagem": "não está na recolha (e a busca externa não foi pedida)"}

    caixa = arm.caixa(cnpj) if cnpj else _primeira_com_certificado()
    if not caixa:
        return {"ok": False, "origem": None,
                "mensagem": "Nenhuma filial com certificado A1 no cofre — sem "
                            "certificado não há como perguntar à SEFAZ."}
    try:
        r = dist.buscar_avulso(caixa["cnpj"], uf or caixa.get("uf") or "PR",
                               chave=ch, cliente=cliente)
    except dist.NaoParticipa as exc:
        # NÃO É "não encontrado": é "não é seu". Ver o docstring do módulo.
        return {"ok": False, "origem": "sefaz", "nao_participa": True,
                "mensagem": str(exc)}
    except dist.SemCertificado as exc:
        return {"ok": False, "origem": None, "mensagem": str(exc)}
    except Exception as exc:  # noqa: BLE001
        # O TIPO, nunca o texto: a conninfo e o caminho do certificado passam
        # por aqui em algumas falhas.
        log.warning("busca por chave falhou: %s", type(exc).__name__)
        return {"ok": False, "origem": "sefaz",
                "mensagem": "A SEFAZ não respondeu (%s)." % type(exc).__name__}

    if not r.get("achou"):
        return {"ok": False, "origem": "sefaz",
                "mensagem": "A SEFAZ não devolveu documento para esta chave (%s %s)."
                            % (r.get("cstat") or "?", r.get("motivo") or "")}
    return {"ok": True, "origem": "sefaz", "documento": local(ch) or {},
            "estado": r.get("estado"),
            "mensagem": "buscado na SEFAZ e guardado aqui"}


def _primeira_com_certificado() -> dict | None:
    """A caixa que tem chance de responder.

    Perguntar por uma filial sem certificado gastaria a viagem para receber um
    erro que a casa já sabia dar sozinha.
    """
    from . import painel
    tem = {c["cnpj"] for c in painel.certificados()
           if c.get("tem_certificado") and not c.get("erro")}
    for c in arm.caixas(so_ativas=True):
        if c["cnpj"] in tem:
            return c
    return None
