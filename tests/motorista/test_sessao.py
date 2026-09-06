# -*- coding: utf-8 -*-
"""A sessão do motorista — o que a derruba, e o que não deveria derrubá-la.

O QUE ESTES TESTES IMPEDEM:

- que um motorista DESLIGADO continue entrando pelos 30 dias do token. O JWT
  responde "é meu e não venceu"; quem responde "esta pessoa ainda pode entrar"
  é `mot_vinculos.ativo`, e é conferido a CADA requisição;
- que encerrar um aparelho não encerre nada;
- que um token com `sid` de uma sessão e `sub` de outro motorista passe;
- que `exigir()` devolva vazio em vez de levantar — a função que devolve
  "sem sessão" é lida um dia num `if` que trata isso como "sem filtro".
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.motorista import sessao as msessao

from .conftest import cadastrar

FONE = "5547999990001"


class ReqFalso:
    """Só o que `exigir` lê. Um `Request` de verdade exige um scope ASGI
    inteiro, e o teste passaria a medir o Starlette em vez do guard."""

    class _Url:
        scheme = "http"

    def __init__(self, cookies=None, https=False):
        self.cookies = cookies or {}
        self.headers = {"x-forwarded-proto": "https" if https else "http"}
        # `_https` lê `request.url.scheme` como PADRÃO do `.get`, e default de
        # `.get` é avaliado sempre — um dublê sem `url` estoura mesmo quando o
        # header está lá. Dublê mais pobre que o real acha defeito que não
        # existe e esconde o que existe.
        self.url = self._Url()


def _sessao_pronta(esq, codigo="MOT-1"):
    cadastrar(esq, codigo, FONE, nome="João")
    sid = msessao.abrir(codigo, aparelho="ap-1", esquema=esq)
    return sid, msessao.emitir(codigo, sid)


def test_token_valido_carrega_o_motorista(esq):
    sid, token = _sessao_pronta(esq)
    s = msessao.atual(token, esq)
    assert s["motorista_codigo"] == "MOT-1" and s["nome"] == "João"
    assert s["sessao_id"] == sid


def test_desligar_o_vinculo_derruba_na_requisicao_seguinte(esq):
    _, token = _sessao_pronta(esq)
    assert msessao.atual(token, esq) is not None

    pglocal.executar("UPDATE mot_vinculos SET ativo = false", None, esq)
    assert msessao.atual(token, esq) is None, (
        "desligado seguiria entrando pelos 30 dias do token")


def test_encerrar_a_sessao_derruba_aquele_aparelho(esq):
    sid, token = _sessao_pronta(esq)
    _, token2 = None, None
    sid2 = msessao.abrir("MOT-1", aparelho="ap-2", esquema=esq)
    token2 = msessao.emitir("MOT-1", sid2)

    msessao.encerrar(sid, esq)
    assert msessao.atual(token, esq) is None
    assert msessao.atual(token2, esq) is not None, (
        "encerrar um aparelho não pode derrubar os outros")


def test_token_com_sub_de_outro_motorista_nao_passa(esq):
    """O `sid` sozinho seria suficiente para carregar a linha. Conferir o
    `sub` contra ela é o que impede um token remontado de virar outra pessoa."""
    sid, _ = _sessao_pronta(esq, "MOT-1")
    cadastrar(esq, "MOT-2", "5547999990002", nome="Maria")

    forjado = msessao.emitir("MOT-2", sid)   # sid de MOT-1, sub de MOT-2
    assert msessao.atual(forjado, esq) is None


def test_token_sem_tipo_nao_passa(esq):
    """Um token do painel é assinado com o MESMO segredo. Sem o `tipo`, ele
    entraria aqui só por ter um `sub` que casasse com um código."""
    import jwt
    from datetime import datetime, timedelta, timezone
    sid, _ = _sessao_pronta(esq)
    agora = datetime.now(timezone.utc)
    sem_tipo = jwt.encode({"sub": "MOT-1", "sid": sid, "iat": agora,
                           "exp": agora + timedelta(days=1)},
                          msessao._segredo(), algorithm="HS256")
    assert msessao.atual(sem_tipo, esq) is None


def test_token_de_lixo_e_ausencia_de_token_nao_estouram(esq):
    for t in (None, "", "isto.nao.e.um.jwt", "a" * 200):
        assert msessao.atual(t, esq) is None


def test_exigir_LEVANTA_em_vez_de_devolver_vazio(esq):
    with pytest.raises(msessao.SemSessao):
        msessao.exigir(ReqFalso(), esq)
    with pytest.raises(msessao.SemSessao):
        msessao.exigir(ReqFalso({msessao.COOKIE: "lixo"}), esq)


def test_exigir_devolve_a_sessao_quando_o_cookie_presta(esq):
    _, token = _sessao_pronta(esq)
    s = msessao.exigir(ReqFalso({msessao.COOKIE: token}), esq)
    assert s["motorista_codigo"] == "MOT-1"


def test_visto_por_ultimo_so_regrava_quando_envelhece(esq):
    """Sem o freio, cada requisição do app viraria um UPDATE — e 'visto por
    último' com precisão de segundo não responde pergunta nenhuma."""
    sid, token = _sessao_pronta(esq)
    antes = pglocal.um("SELECT vista_em FROM mot_sessoes WHERE id=%(i)s",
                       {"i": sid}, esq)["vista_em"]
    msessao.atual(token, esq)
    igual = pglocal.um("SELECT vista_em FROM mot_sessoes WHERE id=%(i)s",
                       {"i": sid}, esq)["vista_em"]
    assert igual == antes

    pglocal.executar(
        "UPDATE mot_sessoes SET vista_em = now() - interval '1 hour' "
        "WHERE id = %(i)s", {"i": sid}, esq)
    msessao.atual(token, esq)
    depois = pglocal.um("SELECT vista_em FROM mot_sessoes WHERE id=%(i)s",
                        {"i": sid}, esq)["vista_em"]
    assert depois > antes


def test_o_cookie_e_httponly_e_nao_sai_do_prefixo(esq):
    """HttpOnly é o que impede um script na página de ler a sessão; o `path`
    é o que impede o navegador de mandá-la para o painel."""
    from fastapi.responses import JSONResponse
    resp = JSONResponse({})
    msessao.gravar_cookie(resp, "tok", ReqFalso(https=True))
    cru = resp.headers["set-cookie"]
    assert "HttpOnly" in cru and "Secure" in cru
    assert "Path=/api/motorista" in cru
    assert cru.startswith(msessao.COOKIE + "=")


def test_banco_fora_RECUSA_em_vez_de_estourar(esq, monkeypatch):
    """Sem esta rede, todo request do app estouraria em `text/plain` — que o
    Cloudflare troca pela página dele — e o motorista veria um erro mudo.
    Recusar é a direção segura de errar; quem diz o motivo é a Saúde."""
    _, token = _sessao_pronta(esq)

    def fora(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(msessao.pglocal, "um", fora)
    assert msessao.atual(token, esq) is None
    with pytest.raises(msessao.SemSessao):
        msessao.exigir(ReqFalso({msessao.COOKIE: token}), esq)
