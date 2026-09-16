# -*- coding: utf-8 -*-
"""A sessão do agregado: cookie próprio, tabela própria, porteiro próprio.

POR QUE NÃO É A SESSÃO DA CASA, em uma frase: uma sessão de agregado que o
`auth.sessao_atual` soubesse ler seria uma sessão capaz de chegar ao painel, e
o único obstáculo entre ela e o CÓRTEX inteiro seria um perfil vazio. Aqui ela
é ilegível para o middleware do painel por construção — cookie com outro nome,
um `tipo` no token que esta função exige e a de lá nem olha, e um `sub` que é o
id opaco do vínculo.

E POR QUE NÃO É A SESSÃO DO MOTORISTA, que já existe e é parecida: o `tipo` do
token é o que separa os dois apps. Sem ele, um cookie de motorista abriria o
app do agregado (e veria dinheiro que não é dele) assim que alguém copiasse o
valor de um aparelho para o outro. São dois públicos, dois escopos e duas
tabelas de vínculo; o token tem de dizer qual.

O `sub` É O ID OPACO, NUNCA O CÓDIGO DO ERP: para pessoa física aquele código é
o CPF (80 dos 201 donos), e um documento que não precisa estar no cookie não
fica no cookie. A lição é do app do motorista, que precisou corrigir isso
depois (`sql/cortex/0058_motorista_id_opaco.sql`); aqui já nasce certo.

O TTL É LONGO DE PROPÓSITO (30 dias, deslizante). Sessão curta aqui não é
segurança, é o dono pedindo código toda semana e desistindo do app — e o que
protege de verdade é o desligamento, que é imediato e independe do prazo. A
exceção é a SESSÃO MESTRE (`api/agregado/mestre.py`): prazo de horas,
`mestre = true` na linha, e tarja obrigatória na tela.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Request, Response

from .. import pglocal

log = logging.getLogger("cortex.agregado.sessao")


def _esq(esquema: str | None = None) -> str | None:
    """O schema em vigor, lido NA CHAMADA e nunca na importação (ver
    `api/agregado/__init__.py`)."""
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


#: Nome PRÓPRIO, e diferente do `cortex_mot` do motorista: dois cookies com o
#: mesmo nome e caminhos diferentes funcionam até o dia em que o navegador
#: manda o errado.
COOKIE = "cortex_agr"

#: O cookie NÃO passeia pelo site: com `path` no prefixo da API do app, ele nem
#: é enviado ao painel nem ao app do motorista.
COOKIE_PATH = "/api/agregado"

#: 30 dias, renovado a cada uso (ver `_renovar_em`).
TTL_DIAS = 30

#: Marca dentro do token. Não é segurança (o token já é assinado): é o que
#: impede um token do painel — ou do app do motorista, assinado com o MESMO
#: segredo — de ser aceito aqui.
TIPO = "agregado"

#: Só se regrava `vista_em` quando a anterior está mais velha que isto. Sem o
#: freio, cada requisição do app viraria um UPDATE.
VISTA_FRESCA_MIN = 5


class SemSessao(Exception):
    """Não há sessão de agregado válida nesta requisição."""


def _segredo() -> str:
    # Importado aqui, e não no topo, para este módulo não puxar `auth` (e com
    # ele o banco de usuários) só por causa de uma constante.
    from .. import auth
    return auth.SECRET


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def emitir(agregado_id: int, sessao_id: int, *, horas: float | None = None) -> str:
    """O `sub` é o ID OPACO, nunca o `proprietario_codigo`.

    `horas` encurta o prazo, e quem usa isso é o ACESSO MESTRE: o prazo curto
    entra no `exp` do TOKEN e no `max_age` do COOKIE, e não só num dos dois —
    cookie que sobrevive ao token faz a página parecer logada e receber 401 em
    toda leitura.
    """
    agora = _agora()
    prazo = (timedelta(hours=float(horas)) if horas
             else timedelta(days=TTL_DIAS))
    return jwt.encode({"sub": str(int(agregado_id)), "sid": int(sessao_id),
                       "tipo": TIPO, "iat": agora, "exp": agora + prazo},
                      _segredo(), algorithm="HS256")


def _https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def gravar_cookie(resp: Response, token: str, request: Request, *,
                  horas: float | None = None) -> None:
    """`horas` encurta o cookie junto com o token — ver `emitir`."""
    resp.set_cookie(key=COOKIE, value=token, httponly=True, samesite="lax",
                    path=COOKIE_PATH, secure=_https(request),
                    max_age=int(horas * 3600) if horas
                            else TTL_DIAS * 24 * 3600)


def apagar_cookie(resp: Response, request: Request) -> None:
    resp.delete_cookie(key=COOKIE, path=COOKIE_PATH, httponly=True,
                       samesite="lax", secure=_https(request))


def abrir(proprietario_codigo: str, *, aparelho: str = "", ip: str = "",
          agente: str = "", mestre: bool = False,
          esquema: str | None = None) -> int:
    """Cria a linha da sessão e devolve o id dela."""
    linha = pglocal.um(
        """INSERT INTO agr_sessoes(proprietario_codigo, aparelho, ip, agente, mestre)
           VALUES (%(cod)s, %(ap)s, %(ip)s, %(ag)s, %(m)s) RETURNING id""",
        {"cod": str(proprietario_codigo), "ap": (aparelho or "")[:64],
         "ip": (ip or "")[:64], "ag": (agente or "")[:200],
         "m": bool(mestre)},
        _esq(esquema))
    return int(linha["id"])


def encerrar(sessao_id: int, esquema: str | None = None) -> None:
    pglocal.executar(
        "UPDATE agr_sessoes SET encerrada_em = now() "
        "WHERE id = %(id)s AND encerrada_em IS NULL",
        {"id": int(sessao_id)}, _esq(esquema))


def atual(token: str | None, esquema: str | None = None) -> dict | None:
    """Valida o token e carrega o proprietário. `None` = sem sessão válida.

    A ORDEM DAS CONFERÊNCIAS É A SEGURANÇA, e cada uma cobre um caso que as
    outras não cobrem: assinatura (token forjado), `tipo` (token do painel ou
    do app do motorista), sessão viva (aparelho encerrado), vínculo ativo
    (agregado desligado). Faltando a última, um desligado seguiria vendo o
    dinheiro dos veículos por 30 dias.
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
            """SELECT s.id AS sessao_id, s.proprietario_codigo, s.vista_em,
                      s.mestre,
                      v.id AS agregado_id, v.nome, v.telefone, v.ativo
                 FROM agr_sessoes s
                 JOIN agr_vinculos v
                   ON v.proprietario_codigo = s.proprietario_codigo
                WHERE s.id = %(sid)s AND s.encerrada_em IS NULL""",
            {"sid": int(sid)}, esq)
    except Exception as exc:  # noqa: BLE001
        # BANCO FORA (ou migration ainda não aplicada) NÃO VIRA SESSÃO VÁLIDA,
        # e também não vira 500: sem esta rede, todo request do app estouraria
        # em `text/plain` que o Cloudflare troca pela página dele. Recusar é a
        # direção segura de errar.
        log.warning("sessão do agregado indisponível: %s", type(exc).__name__)
        return None
    if not linha or not linha["ativo"]:
        return None
    # O `sub` do token TEM de bater com a linha: não bater significa token de
    # uma sessão que trocou de dono, o que não acontece por acidente.
    if str(linha["agregado_id"]) != str(claims.get("sub")):
        log.warning("token de agregado com sub divergente da sessão %s", sid)
        return None

    if _envelheceu(linha["vista_em"]):
        pglocal.executar(
            "UPDATE agr_sessoes SET vista_em = now() WHERE id = %(id)s",
            {"id": int(sid)}, esq)
    # DUAS CHAVES, COM PAPÉIS DIFERENTES: `proprietario_codigo` só serve para
    # consultar o AVA e NÃO SAI do servidor; `agregado_id` é o que pode ser
    # dito para fora (trilha, token, payload).
    return {"proprietario_codigo": str(linha["proprietario_codigo"]),
            "agregado_id": int(linha["agregado_id"]),
            "nome": linha["nome"] or "", "telefone": linha["telefone"] or "",
            "sessao_id": int(sid),
            # A MARCA VIAJA NA SESSÃO, e é ela que obriga a tarja: sem sair
            # daqui, a página não teria como saber em que conta está.
            "mestre": bool(linha.get("mestre"))}


def _envelheceu(vista_em) -> bool:
    if not vista_em:
        return True
    if vista_em.tzinfo is None:
        vista_em = vista_em.replace(tzinfo=timezone.utc)
    return (_agora() - vista_em) > timedelta(minutes=VISTA_FRESCA_MIN)


def exigir(request: Request, esquema: str | None = None) -> dict:
    """A porta de TODA rota deste módulo, exceto as de entrada.

    LEVANTA em vez de devolver `None` pela mesma razão que
    `portal_cliente.escopo()`: uma função que devolvesse "sem sessão" seria
    lida um dia num `if` que trata isso como "sem filtro", e a rota passaria a
    responder a qualquer um.
    """
    sess = atual(request.cookies.get(COOKIE), esquema)
    if not sess:
        raise SemSessao("sem sessão de agregado")
    return sess
