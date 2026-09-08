# -*- coding: utf-8 -*-
"""O que a recolha da SEFAZ mostra na tela — e o cartão dela nas Integrações.

FUNÇÃO PURA SOBRE O QUE JÁ ESTÁ GRAVADO. Não fala com a SEFAZ e não dispara
coleta: a pergunta é sobre o que JÁ chegou. Fonte de painel que bate no
fornecedor a cada pintura vira carga — e aqui viraria o freio de consumo
indevido, que custa uma hora de recolha parada.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from . import armazenamento as arm

log = logging.getLogger("cortex.sefaz.painel")

#: Depois disto sem recolher, a caixa está PARADA. A tarefa roda de 2 em 2 h
#: das 07h às 19h; 8 horas dá folga para uma execução falhar e a seguinte
#: cobrir, sem acender alarme por um tropeço.
PARADA_APOS_H = 8

#: O certificado A1 vale um ano. Avisar com 30 dias dá tempo de renovar; avisar
#: no dia do vencimento não serve para nada — e vencido a recolha para SEM ERRO
#: em lugar nenhum, que é o que torna este aviso necessário.
AVISO_VENCIMENTO_D = 30


def _idade_h(quando) -> float | None:
    if not isinstance(quando, datetime):
        return None
    agora = datetime.now(timezone.utc)
    return (agora - quando).total_seconds() / 3600.0


def certificados() -> list[dict]:
    """O estado do certificado de cada caixa — SEM abrir o arquivo com a senha.

    Lê a validade do cofre de metadados que o `cadastrar_certificado.py`
    gravou? Não: lê do PRÓPRIO arquivo, que é a fonte. Abrir custa
    milissegundos e não há como o arquivo e a afirmação divergirem — o defeito
    clássico de guardar validade em tabela é ela continuar dizendo "vale até"
    depois de alguém trocar o `.pfx`.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent.parent
    dir_cert = raiz / "data" / "certificados"
    saida = []
    for cx in arm.caixas(so_ativas=True):
        cnpj = cx["cnpj"]
        arq = dir_cert / ("%s.pfx" % cnpj)
        linha = {"cnpj": cnpj, "apelido": cx.get("apelido"),
                 "tem_certificado": arq.exists(), "valida_ate": None,
                 "dias": None, "vencido": None, "erro": None}
        if not arq.exists():
            saida.append(linha)
            continue
        try:
            from api.contrapartida import cadastro, certificado as cert
            senha = cadastro.ler_senha(cnpj)
            if not senha:
                linha["erro"] = "senha nao cadastrada"
                saida.append(linha)
                continue
            meta = cert.ler(arq.read_bytes(), senha)
            linha.update({"valida_ate": str(meta.get("valida_ate") or ""),
                          "dias": meta.get("dias"),
                          "vencido": bool(meta.get("vencido")),
                          "titular": meta.get("titular")})
        except Exception as exc:  # noqa: BLE001
            # O TIPO, nunca o texto: o caminho do arquivo e a senha passam por
            # aqui em algumas falhas.
            linha["erro"] = type(exc).__name__
        saida.append(linha)
    return saida


def panorama() -> dict:
    """O que a tela desenha: as caixas, o resumo e o estado dos certificados."""
    caixas = arm.caixas(so_ativas=True)
    certs = {c["cnpj"]: c for c in certificados()}

    linhas = []
    for cx in caixas:
        c = certs.get(cx["cnpj"], {})
        idade = _idade_h(cx.get("ultima_consulta"))
        # QUANTO FALTA é a distância entre o nosso ponteiro e o maior NSU que
        # EXISTE na SEFAZ. Sem ele a tela só saberia dizer "recolhi 400" — e
        # 400 de quantos é a única forma de a pessoa saber se acabou.
        falta = None
        if cx.get("max_nsu"):
            try:
                falta = max(0, int(cx["max_nsu"]) - int(cx["ultimo_nsu"]))
            except (TypeError, ValueError):
                falta = None
        linhas.append({
            "cnpj": cx["cnpj"], "apelido": cx.get("apelido"), "uf": cx.get("uf"),
            "ultimo_nsu": cx["ultimo_nsu"], "max_nsu": cx.get("max_nsu"),
            "falta": falta,
            "ultima_consulta": (cx["ultima_consulta"].isoformat()
                                if isinstance(cx.get("ultima_consulta"), datetime)
                                else None),
            "idade_h": round(idade, 1) if idade is not None else None,
            "cstat": cx.get("ultimo_cstat"), "motivo": cx.get("ultimo_motivo"),
            "parada": idade is not None and idade > PARADA_APOS_H,
            "certificado": c,
            "documentos": arm.resumo(cx["cnpj"]),
        })
    return {"caixas": linhas, "total": arm.resumo()}


def _problemas(linhas: list[dict]) -> list[str]:
    """O que precisa de alguém HOJE, em ordem de gravidade.

    Cada item nomeia a filial: "a recolha parou" sem dizer qual das dez não é
    informação, é aviso para ser ignorado.
    """
    fora: list[str] = []
    venc, sem_cert, paradas, freadas = [], [], [], []
    for l in linhas:
        rot = l.get("apelido") or l["cnpj"]
        c = l.get("certificado") or {}
        if not c.get("tem_certificado"):
            sem_cert.append(rot)
        elif c.get("vencido"):
            venc.append("%s (venceu em %s)" % (rot, c.get("valida_ate")))
        elif isinstance(c.get("dias"), int) and c["dias"] <= AVISO_VENCIMENTO_D:
            venc.append("%s (vence em %d d)" % (rot, c["dias"]))
        if l.get("cstat") == "656":
            freadas.append(rot)
        elif l.get("parada"):
            paradas.append(rot)

    if venc:
        fora.append("certificado vencendo ou vencido: " + ", ".join(venc))
    if sem_cert:
        fora.append("%d filial(is) sem certificado A1 no cofre (%s)"
                    % (len(sem_cert), ", ".join(sem_cert[:3])
                       + ("…" if len(sem_cert) > 3 else "")))
    if paradas:
        fora.append("recolha parada há mais de %dh em: %s"
                    % (PARADA_APOS_H, ", ".join(paradas)))
    if freadas:
        # FREIO NÃO É DEFEITO NOSSO, e por isso vem por último e sem alarme: a
        # SEFAZ pune consulta repetida sem resultado, e a espera é o certo.
        fora.append("freada(s) pela SEFAZ, aguardando o prazo: "
                    + ", ".join(freadas))
    return fora


def cartao_de_integracao() -> dict:
    """A linha da SEFAZ na Central de Integrações.

    A SEFAZ NÃO ESTÁ NO COFRE DE CREDENCIAIS, e por isso ela se descreve aqui:
    o que autentica é um certificado A1 em arquivo, com validade e senha
    próprias — "está configurada?" para ela é "o `.pfx` existe, abre, é do CNPJ
    certo e ainda vale?", que é outra pergunta.
    """
    d = panorama()
    linhas = d["caixas"]
    problemas = _problemas(linhas)
    com_cert = sum(1 for l in linhas
                   if (l.get("certificado") or {}).get("tem_certificado"))
    tot = d["total"]

    if not linhas:
        conf_estado, conf_status = "desligada", "info"
        falta = ["nenhuma caixa aberta (rode scripts/abrir_caixas_dfe.py)"]
    elif com_cert == 0:
        conf_estado, conf_status = "incompleta", "alerta"
        falta = ["certificado A1 de nenhuma filial está no cofre"]
    elif com_cert < len(linhas):
        conf_estado, conf_status = "incompleta", "alerta"
        falta = ["certificado A1 de %d das %d filiais"
                 % (len(linhas) - com_cert, len(linhas))]
    else:
        conf_estado, conf_status = "ativa", "ok"
        falta = []

    partes = ["%d de %d filial(is) com certificado" % (com_cert, len(linhas))]
    if tot.get("total"):
        partes.append("%d documento(s) recolhido(s)" % tot["total"])
        if tot.get("pendentes"):
            # PENDENTE É O NÚMERO QUE DECIDE: documento que está só no resumo é
            # XML que a casa NÃO tem, e tem obrigação de guardar.
            partes.append("%d ainda sem o XML completo (falta a ciência)"
                          % tot["pendentes"])
    else:
        partes.append("nenhum documento recolhido ainda")

    chegada_status = "ok"
    if any("parada" in p or "vencido" in p for p in problemas):
        chegada_status = "alerta"
    if problemas:
        chegada_status = "alerta"
        partes.extend(problemas)

    return {
        "chave": "sefaz",
        "nome": "SEFAZ (recolha de NF)",
        "resumo": ("As notas fiscais emitidas CONTRA a Sulista, e os eventos "
                   "delas, direto do serviço nacional de Distribuição de DFe. "
                   "É a única fonte que não depende de o fornecedor mandar o "
                   "XML por e-mail — e o XML é a obrigação de guarda de cinco "
                   "anos."),
        "alimenta": "Central de Documentos",
        "estado": ("ok" if (conf_status == "ok" and chegada_status == "ok")
                   else "alerta"),
        "configuracao": {"estado": conf_estado, "status": conf_status,
                         "falta": falta, "modo": "certificado A1",
                         "regime": None},
        "chegada": {"regime": "coleta", "status": chegada_status,
                    "detalhe": " · ".join(partes)},
    }
