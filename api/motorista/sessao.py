# -*- coding: utf-8 -*-
"""A sessão do motorista: cookie próprio, tabela própria, porteiro próprio.

POR QUE NÃO É A SESSÃO DA CASA, em uma frase: uma sessão de motorista que o
`auth.sessao_atual` soubesse ler seria uma sessão capaz de chegar ao painel, e
o único obstáculo entre ela e o CÓRTEX inteiro seria um perfil vazio. Aqui ela
é ilegível para o middleware do painel por construção — cookie com outro nome,
um `tipo` no token que esta função exige e a de lá nem olha, e um `sub` que é o
id opaco do vínculo, não o id de usuário do painel.

O `sub` NÃO É O CÓDIGO DO ERP, e isso foi corrigido em 06/09/2026: para pessoa
física aquele código é o CPF, e ele estava indo dentro do cookie, no
`audit_log` e — o caso que de fato viola a regra da casa — no payload da lista
de "quem está entrando". Agora só o id opaco sai daqui; o código fica na coluna
que precisa dele para casar com o AVA. Ver `sql/cortex/0058_motorista_id_opaco.sql`.

TRÊS COISAS QUE O TOKEN NÃO RESOLVE, e por isso `mot_sessoes` existe:

1. **Desligamento.** O JWT diz "é meu e não venceu"; não diz "esta pessoa ainda
   trabalha aqui". `mot_vinculos.ativo` diz, e é conferido a cada requisição.
2. **Aparelho perdido.** Encerrar UMA sessão derruba UM aparelho; sem a linha,
   a única saída seria trocar o segredo da casa e derrubar todo mundo.
3. **"Quem está usando".** Sessão é linha VIVA, com "visto por último" — a
   mesma escolha de `aud_sessoes`, e pela mesma razão: ninguém sai pelo botão.

O TTL É LONGO DE PROPÓSITO (30 dias, deslizante). Sessão curta aqui não é
segurança, é o motorista pedindo código toda semana e desistindo do app — e o
que protege de verdade é o desligamento, que é imediato e independe do prazo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Request, Response

from .. import pglocal

log = logging.getLogger("cortex.motorista.sessao")


def _esq(esquema: str | None = None) -> str | None:
    """O schema em vigor, lido NA CHAMADA e nunca na importação.

    `from . import ESQUEMA` no topo COPIA o valor: o teste que redireciona
    `motorista.ESQUEMA` para um schema descartável não alcançaria esta cópia, e
    o módulo escreveria em PRODUÇÃO com a suíte toda verde. Foi assim que os
    testes da Monkey puseram recebíveis de dublê dentro de `cortex.mky_*` em
    01/09/2026, e o sintoma apareceu numa tela, não na suíte.
    """
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


#: Nome PRÓPRIO. Nunca `cortex_sess`: dois cookies com o mesmo nome e caminhos
#: diferentes é o tipo de coisa que funciona até o dia em que o navegador
#: manda o errado, e aí o motorista recebe 401 do painel sem entender nada.
COOKIE = "cortex_mot"

#: O cookie NÃO passeia pelo site. Com `path` no prefixo da API do app, ele
#: nem é enviado ao painel — o que torna impossível, e não só improvável, que
#: uma sessão de motorista apareça numa requisição de tela da casa.
COOKIE_PATH = "/api/motorista"

#: 30 dias, renovado a cada uso (ver `_renovar_em`).
TTL_DIAS = 30

#: Marca dentro do token. Não é segurança (o token já é assinado): é o que
#: garante que um token do painel, assinado com o MESMO segredo, não seja
#: aceito aqui por engano — e vice-versa, porque lá `sub` é um inteiro.
TIPO = "motorista"

#: Só se regrava `vista_em` quando a anterior está mais velha que isto. Sem o
#: freio, cada requisição do app viraria um UPDATE — e "visto por último" com
#: precisão de segundo não responde nenhuma pergunta que alguém faça.
VISTA_FRESCA_MIN = 5


class SemSessao(Exception):
    """Não há sessão de motorista válida nesta requisição."""


def _segredo() -> str:
    # Importado aqui, e não no topo, para este módulo não puxar `auth` (e com
    # ele o banco de usuários) só por causa de uma constante.
    from .. import auth
    return auth.SECRET


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def emitir(motorista_id: int, sessao_id: int) -> str:
    """O `sub` é o ID OPACO, nunca o `motorista_codigo`.

    Para pessoa física o código do ERP é o CPF, e o token vive no cookie do
    aparelho — um documento que não precisa estar ali não fica ali. Ver
    `sql/cortex/0058_motorista_id_opaco.sql`.
    """
    agora = _agora()
    return jwt.encode({"sub": str(int(motorista_id)), "sid": int(sessao_id),
                       "tipo": TIPO, "iat": agora,
                       "exp": agora + timedelta(days=TTL_DIAS)},
                      _segredo(), algorithm="HS256")


def _https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def gravar_cookie(resp: Response, token: str, request: Request) -> None:
    resp.set_cookie(key=COOKIE, value=token, httponly=True, samesite="lax",
                    path=COOKIE_PATH, secure=_https(request),
                    max_age=TTL_DIAS * 24 * 3600)


def apagar_cookie(resp: Response, request: Request) -> None:
    resp.delete_cookie(key=COOKIE, path=COOKIE_PATH, httponly=True,
                       samesite="lax", secure=_https(request))


def abrir(motorista_codigo: str, *, aparelho: str = "", ip: str = "",
          agente: str = "", esquema: str | None = None) -> int:
    """Cria a linha da sessão e devolve o id dela."""
    linha = pglocal.um(
        """INSERT INTO mot_sessoes(motorista_codigo, aparelho, ip, agente)
           VALUES (%(cod)s, %(ap)s, %(ip)s, %(ag)s) RETURNING id""",
        {"cod": str(motorista_codigo), "ap": (aparelho or "")[:64],
         "ip": (ip or "")[:64], "ag": (agente or "")[:200]},
        _esq(esquema))
    return int(linha["id"])


def encerrar(sessao_id: int, esquema: str | None = None) -> None:
    pglocal.executar(
        "UPDATE mot_sessoes SET encerrada_em = now() "
        "WHERE id = %(id)s AND encerrada_em IS NULL",
        {"id": int(sessao_id)}, _esq(esquema))


def atual(token: str | None, esquema: str | None = None) -> dict | None:
    """Valida o token e carrega o motorista. `None` = sem sessão válida.

    A ORDEM DAS CONFERÊNCIAS É A SEGURANÇA, e cada uma cobre um caso que as
    outras não cobrem: assinatura (token forjado), `tipo` (token do painel),
    sessão viva (aparelho encerrado), vínculo ativo (motorista desligado).
    Faltando a última, um desligado seguiria entrando por 30 dias.
    """
    if not token:
        return None
    try:
        claims = jwt.decode(token, _segredo(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    if claims.get("tipo") != TIPO:
        return None
    sid = claims.get("sid")
    if not sid:
        return None
    esq = _esq(esquema)
    try:
        linha = pglocal.um(
            """SELECT s.id AS sessao_id, s.motorista_codigo, s.vista_em,
                      v.id AS motorista_id, v.nome, v.telefone, v.ativo
                 FROM mot_sessoes s
                 JOIN mot_vinculos v ON v.motorista_codigo = s.motorista_codigo
                WHERE s.id = %(sid)s AND s.encerrada_em IS NULL""",
            {"sid": int(sid)}, esq)
    except Exception as exc:  # noqa: BLE001
        # BANCO FORA (ou migration ainda não aplicada) NÃO VIRA SESSÃO VÁLIDA,
        # e também não vira 500: sem esta rede, todo request do app estouraria
        # em `text/plain` que o Cloudflare troca pela página dele, e o motorista
        # veria um erro que não diz nada. Recusar é a direção segura de errar —
        # quem diz o motivo de verdade é o cartão da Saúde do Servidor.
        log.warning("sessão do motorista indisponível: %s", type(exc).__name__)
        return None
    if not linha or not linha["ativo"]:
        return None
    # O `sub` do token TEM de bater com a linha. Não bater significa token de
    # uma sessão que trocou de dono — não acontece por acidente, e por isso a
    # resposta é recusar em vez de confiar no id.
    if str(linha["motorista_id"]) != str(claims.get("sub")):
        log.warning("token de motorista com sub divergente da sessão %s", sid)
        return None

    if _envelheceu(linha["vista_em"]):
        pglocal.executar(
            "UPDATE mot_sessoes SET vista_em = now() WHERE id = %(id)s",
            {"id": int(sid)}, esq)
    # DUAS CHAVES, COM PAPÉIS DIFERENTES, e a distinção é o ponto desta
    # correção: `motorista_codigo` só serve para consultar o AVA e NÃO SAI do
    # servidor; `motorista_id` é o que pode ser dito para fora (trilha, token,
    # payload). Quem escrever rota nova aqui usa o `id`.
    return {"motorista_codigo": str(linha["motorista_codigo"]),
            "motorista_id": int(linha["motorista_id"]),
            "nome": linha["nome"] or "", "telefone": linha["telefone"] or "",
            "sessao_id": int(sid)}


def _envelheceu(vista_em) -> bool:
    if not vista_em:
        return True
    if vista_em.tzinfo is None:
        vista_em = vista_em.replace(tzinfo=timezone.utc)
    return (_agora() - vista_em) > timedelta(minutes=VISTA_FRESCA_MIN)


def exigir(request: Request, esquema: str | None = None) -> dict:
    """A porta de TODA rota deste módulo, exceto as duas de entrada.

    LEVANTA em vez de devolver `None` pela mesma razão que
    `portal_cliente.escopo()`: uma função que devolvesse "sem sessão" seria
    lida um dia num `if` que trata isso como "sem filtro", e a rota passaria a
    responder a qualquer um. Não há caminho aqui que devolva vazio.
    """
    sess = atual(request.cookies.get(COOKIE), esquema)
    if not sess:
        raise SemSessao("sem sessão de motorista")
    return sess
