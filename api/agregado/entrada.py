# -*- coding: utf-8 -*-
"""Entrar no app do agregado: telefone, código no WhatsApp, sessão no aparelho.

POR QUE NÃO É SENHA, e por que WhatsApp: a cobertura foi MEDIDA antes da
decisão (16/09/2026) — os 201 donos de veículo agregado têm telefone no
cadastro do ERP, contra 93 com e-mail. Senha exigiria cadastro, recuperação e
suporte para 201 pessoas que falam com a casa pelo WhatsApp o dia inteiro.

O FORMULÁRIO PÚBLICO RESPONDE IGUAL PARA NÚMERO QUE EXISTE E QUE NÃO EXISTE.
Mesmo texto, mesmo código de status — inclusive quando o envio falha, quando o
número está fora do cadastro e quando o freio já cortou o pedido. Aqui a razão
é ainda mais direta que no app do motorista: resposta diferente transformaria
esta tela numa máquina de descobrir QUEM É DONO DE CAMINHÃO que roda para esta
empresa, e quanto cada um tem de frota.

AS CINCO CONTENÇÕES, e o que cada uma cobre — nenhuma cobre a do lado:

1. **Prazo curto** (10 min).
2. **Tentativas contadas** (5 por código): seis dígitos são um milhão de
   combinações; sem teto, um laço acerta em minutos.
3. **Pedidos por hora, POR TELEFONE** (3): sem isso a rota vira um jeito
   confortável de encher o WhatsApp de alguém.
4. **Pedidos por hora, POR ENDEREÇO** (20): o teto por telefone não segura
   VOLUME. É teto de script, não de pessoa.
5. **O código nunca é gravado**: só o SHA-256. E não vai para o log, em lugar
   nenhum, nem em `debug`.

O NÚMERO DA CASA E A JANELA DE HORÁRIO: vale a mesma decisão do app do
motorista (`api/motorista/entrada.py`) — o código sai pelo número PRINCIPAL,
que é o que o dono já reconhece, e a janela de 08:00–20:00 é aberta só neste
caminho, porque código de entrada é resposta a alguém que está esperando por
ele. O teto diário de destinatários da casa NÃO é mexido: com 201 donos que
entram de vez em quando, o consumo fica muito abaixo das ~58 vagas livres por
dia medidas em `zap_envios`.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets

from ..whatsapp import config as zcfg
from ..whatsapp import envio as wa
from ..whatsapp import numeros
from .. import pglocal

log = logging.getLogger("cortex.agregado.entrada")

#: Quanto tempo o código vale.
VALIDADE_MIN = 10

#: Quantas vezes se pode errar o MESMO código antes de ele morrer.
MAX_TENTATIVAS = 5

#: Quantos códigos um telefone pode PEDIR por hora. Não se anuncia: passar do
#: teto responde igual a tudo o mais, senão o próprio freio vira o oráculo que
#: a resposta uniforme existe para fechar.
MAX_PEDIDOS_HORA = 3

#: O mesmo teto pela outra ponta: quantos pedidos saem de UM ENDEREÇO por hora.
#: 20 e não 3 porque um IP não é uma pessoa — o tráfego chega pelo tunnel do
#: Cloudflare e o dono pode estar no NAT da operadora.
MAX_PEDIDOS_HORA_IP = 20

#: A resposta ÚNICA do pedido. Uma constante e não um literal em três lugares:
#: é literal repetido que diverge, e aqui divergir é o defeito. O prazo é
#: DERIVADO de `VALIDADE_MIN` pelo mesmo motivo.
RESPOSTA_PEDIDO = ("Se este número estiver cadastrado, o código de entrada "
                   "chegou no seu WhatsApp. Ele vale por %d minutos."
                   % VALIDADE_MIN)

#: A recusa ÚNICA da confirmação: "código errado" e "código expirado"
#: separados diriam a quem tenta em laço se vale a pena continuar.
RECUSA_CODIGO = "Código inválido ou expirado. Peça um novo código."

TEXTO = ("Seu codigo de entrada no app do agregado e {codigo}.\n"
         "Ele vale por %d minutos.\n\n"
         "Se nao foi voce que pediu, ignore esta mensagem — ninguem entra "
         "sem este codigo." % VALIDADE_MIN)


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota. Nunca 5xx: o Cloudflare troca o
    corpo de 5xx pela página dele e a mensagem não chega a ninguém."""


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def _instancia() -> str | None:
    return os.environ.get("AGREGADO_ZAP_INSTANCIA", "").strip() or None


def _normalizar(bruto: str) -> str:
    """Telefone normalizado, ou "" — NUNCA levanta para fora.

    Levantar aqui seria a primeira diferença de resposta entre um número
    malformado e um número que não existe, e é justamente a diferença que este
    arquivo inteiro existe para não ter.
    """
    try:
        n = numeros.normalizar(bruto or "")
        return n if numeros.valido(n) else ""
    except Exception:  # noqa: BLE001 — o contrato é não vazar o motivo
        return ""


def _vinculos(telefone: str, esquema: str | None = None) -> list[dict]:
    """O `id` vem junto porque é ELE que pode ser dito para fora. O
    `proprietario_codigo` (o CPF, para pessoa física) só serve para consultar o
    AVA e nunca entra em payload nenhum."""
    return pglocal.query(
        """SELECT id, proprietario_codigo, nome FROM agr_vinculos
            WHERE telefone = %(f)s AND ativo
            ORDER BY nome, proprietario_codigo""",
        {"f": telefone}, _esq(esquema))


def pedir(telefone_bruto: str, *, ip: str = "", esquema: str | None = None,
          http=None) -> dict:
    """Manda um código, ou não manda. A resposta é a MESMA nos dois casos."""
    esq = _esq(esquema)
    fone = _normalizar(telefone_bruto)
    if not fone:
        return {"ok": True, "mensagem": RESPOSTA_PEDIDO}

    # OS DOIS TETOS NA MESMA IDA AO BANCO.
    recentes = pglocal.um(
        """SELECT sum(CASE WHEN telefone = %(f)s THEN 1 ELSE 0 END) AS por_fone,
                  sum(CASE WHEN ip = %(ip)s AND %(ip)s <> '' THEN 1 ELSE 0 END) AS por_ip
             FROM agr_codigos
            WHERE criado_em > now() - interval '1 hour'""",
        {"f": fone, "ip": (ip or "")[:64]}, esq)
    r = recentes or {}
    if (int(r.get("por_fone") or 0) >= MAX_PEDIDOS_HORA
            or int(r.get("por_ip") or 0) >= MAX_PEDIDOS_HORA_IP):
        # O log distingue os dois (um é pessoa insistindo, o outro é script);
        # a RESPOSTA não distingue nada, que é o ponto.
        log.info("pedido de código freado (fone=%s ip=%s)",
                 r.get("por_fone"), r.get("por_ip"))
        return {"ok": True, "mensagem": RESPOSTA_PEDIDO}

    if not _vinculos(fone, esq):
        # Nada é enviado e nada é gravado: gravar aqui faria a tabela de
        # códigos virar a lista de quem TENTOU.
        return {"ok": True, "mensagem": RESPOSTA_PEDIDO}

    codigo = f"{secrets.randbelow(900000) + 100000}"
    pglocal.executar(
        """INSERT INTO agr_codigos(telefone, codigo_hash, expira_em, ip)
           VALUES (%(f)s, %(h)s, now() + (%(m)s * interval '1 minute'), %(ip)s)""",
        {"f": fone, "h": _hash(codigo), "ip": (ip or "")[:64],
         "m": VALIDADE_MIN}, esq)

    # O ENVIO INTEIRO VAI DENTRO DO `try`, E A RESPOSTA NÃO MUDA POR NADA QUE
    # ACONTEÇA AQUI: uma exceção escapando daqui viraria 500 para o número
    # CADASTRADO e 200 para o desconhecido, e a resposta uniforme deixaria de
    # ser uniforme exatamente no caso que ela protege.
    try:
        geral = zcfg.ler()
        r = wa.enviar(
            fone, TEXTO.format(codigo=codigo),
            usuario="app-agregado", origem="agregado_entrada",
            instancia=_instancia(), http=http, esquema=esq,
            # A janela vai aberta AQUI e só aqui; o teto do dia continua
            # protegendo o número da casa.
            regras={**geral, "janela_inicio": "00:00", "janela_fim": "23:59",
                    "limite_numero": geral["limite_dia"], "limite_modelo": None})
        if not r.get("ok"):
            log.warning("código de entrada não saiu: %s",
                        r.get("erro") or "sem motivo")
    except Exception as exc:  # noqa: BLE001 — o contrato é a resposta uniforme
        log.warning("código de entrada falhou antes do envio: %s",
                    type(exc).__name__)
    return {"ok": True, "mensagem": RESPOSTA_PEDIDO}


def confirmar(telefone_bruto: str, codigo: str, *, aparelho: str = "",
              agregado: str = "", ip: str = "", agente: str = "",
              esquema: str | None = None) -> dict:
    """Confere o código e abre a sessão.

    Devolve `{"escolher": [...]}` quando o telefone serve a MAIS DE UM vínculo
    — o caso comum aqui é o dono pessoa física que também tem os veículos no
    CNPJ da empresa dele. Nesse caminho o código NÃO é consumido: a pessoa
    acabou de prová-lo, e queimá-lo para perguntar quem ela é obrigaria a pedir
    outro só porque tem duas inscrições.
    """
    from . import sessao as ses

    esq = _esq(esquema)
    fone = _normalizar(telefone_bruto)
    digitado = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if not fone or not digitado:
        raise Recusa(RECUSA_CODIGO)

    linha = pglocal.um(
        """SELECT id, codigo_hash, tentativas FROM agr_codigos
            WHERE telefone = %(f)s AND usado_em IS NULL AND expira_em > now()
            ORDER BY criado_em DESC LIMIT 1""",
        {"f": fone}, esq)
    if not linha:
        raise Recusa(RECUSA_CODIGO)

    # A tentativa é contada ANTES da comparação: contar depois deixaria de fora
    # exatamente as que interessam — as que erram —, e o teto nunca chegaria.
    tentativas = int(linha["tentativas"]) + 1
    pglocal.executar(
        "UPDATE agr_codigos SET tentativas = %(t)s WHERE id = %(id)s",
        {"t": tentativas, "id": linha["id"]}, esq)
    if tentativas > MAX_TENTATIVAS:
        pglocal.executar(
            "UPDATE agr_codigos SET usado_em = now() WHERE id = %(id)s",
            {"id": linha["id"]}, esq)
        raise Recusa(RECUSA_CODIGO)

    if not hmac.compare_digest(str(linha["codigo_hash"]), _hash(digitado)):
        raise Recusa(RECUSA_CODIGO)

    vinculos = _vinculos(fone, esq)
    if not vinculos:
        # O vínculo caiu entre o pedido e a confirmação (desligamento). Recusa
        # legível e diferente: aqui a pessoa PROVOU quem é, então esconder o
        # motivo só a faria tentar de novo para sempre.
        pglocal.executar(
            "UPDATE agr_codigos SET usado_em = now() WHERE id = %(id)s",
            {"id": linha["id"]}, esq)
        raise Recusa("Este número não tem acesso ao app. Fale com a Sulista.")

    # A ESCOLHA VIAJA PELO ID OPACO, NUNCA PELO CÓDIGO: esta lista vai para o
    # navegador, e o código do ERP é o CPF de pessoa física.
    escolhido = str(agregado or "").strip()
    if len(vinculos) > 1 and not escolhido:
        return {"escolher": [{"id": int(v["id"]), "nome": v["nome"] or ""}
                             for v in vinculos]}
    validos = {str(v["id"]): v for v in vinculos}
    if escolhido and escolhido not in validos:
        raise Recusa(RECUSA_CODIGO)
    alvo = validos[escolhido] if escolhido else vinculos[0]

    # Consumir o código invalida TODOS os outros em aberto do mesmo telefone.
    pglocal.executar(
        """UPDATE agr_codigos SET usado_em = now()
            WHERE telefone = %(f)s AND usado_em IS NULL""",
        {"f": fone}, esq)

    # `abrir` grava a FK, que é o código (junção interna, não sai); `emitir`
    # assina o ID, que é o que vive no cookie do aparelho.
    sessao_id = ses.abrir(alvo["proprietario_codigo"], aparelho=aparelho, ip=ip,
                          agente=agente, esquema=esq)
    return {"ok": True, "agregado_id": int(alvo["id"]),
            "nome": alvo["nome"] or "",
            "token": ses.emitir(int(alvo["id"]), sessao_id),
            "sessao_id": sessao_id}
