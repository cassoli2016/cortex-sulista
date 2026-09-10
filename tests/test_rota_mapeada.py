# -*- coding: utf-8 -*-
"""Toda rota `/api/*` tem dono no RBAC — e as exceções se provam.

POR QUE ISTO NÃO EXISTIA, E POR QUE PASSOU DESPERCEBIDO
=======================================================
O middleware é fail-closed: rota `/api/*` não mapeada devolve 403 para
não-admin. Isso é a proteção certa — e é também o motivo de a falha nunca
aparecer em teste. Quem escreve a rota costuma ser admin quando confere, vê
200, e o 403 só nasce para o operador, em produção, no dia seguinte.

Procurei o guard que varre as rotas do app conferindo o mapeamento e ele não
existia em 09/09/2026, com 268 rotas `/api/*` no ar.

AS TRÊS FAMÍLIAS QUE NÃO PASSAM PELO RBAC DE TELA
=================================================
E cada uma por uma razão diferente, não por esquecimento:

  - `/api/gestao/*` é checado como ADMIN no middleware ANTES do mapeamento de
    telas. Mapear ali seria letra morta — é por isso que as rotas do ritual
    semanal ficam FORA desse prefixo: quem preenche o ritual é gerente, e sob
    `/api/gestao` a tela nasceria inútil para o público dela.
  - `/api/motorista/*` atende o app do motorista, cujo interlocutor NÃO é
    usuário do CÓRTEX: ele entra com identidade própria e não tem tela.
  - `/api/rastreio/*` é a única superfície da casa sem login — a página pública
    que o cliente abre pelo link.

A lista é escrita à mão, então ela mesma é conferida contra o código: um
prefixo que deixe de existir, ou que passe a ter tela, faz o teste falhar.
"""
from __future__ import annotations

import pytest

from api import auth

#: Prefixos que respondem por outro caminho de autorização. Cada um tem o
#: motivo escrito acima; nenhum é "não deu tempo de mapear".
FORA_DO_RBAC_DE_TELA = {
    "/api/gestao": "checado como admin no middleware, antes do mapa de telas",
    "/api/motorista": "app do motorista — identidade própria, não é usuário do painel",
    "/api/rastreio": "página pública de rastreio — a única superfície sem login",
    # Sonda de vida. Ela existe para ser consultada SEM sessão — é o que o
    # túnel e o monitor perguntam, e mapear tela para ela seria negá-la a quem
    # precisa: quem chama não está logado por definição.
    "/api/health": "sonda de vida, consultada sem sessão",
}

#: `/api/gestao` aparece TAMBÉM em `ROTA_TELAS`, e isso é sabido: o CLAUDE.md
#: registra que aquelas entradas são LETRA MORTA para não-admin, porque o
#: middleware barra o prefixo antes de chegar ao mapa de telas. Não é engano —
#: é redundância inofensiva que ninguém removeu. O teste da coexistência pula
#: este prefixo em vez de fingir que o estado é outro.
COEXISTENCIA_CONHECIDA = {"/api/gestao"}


#: Rotas que OUTRO TESTE registra no app de verdade e não desfaz.
#:
#: `tests/test_erro_nao_tratado.py` precisa de um endpoint que estoure para
#: provar que a exceção não vaza segredo — e o registra no `app` real, numa
#: fixture de módulo. Ele fica lá para todo teste que rodar depois na mesma
#: sessão.
#:
#: ISTO SÓ APARECEU NA SUÍTE COMPLETA. Rodando este arquivo sozinho, ou com os
#: vizinhos, o guard passava: a dependência de ordem é invisível até a ordem
#: acontecer. É o argumento inteiro a favor de rodar tudo antes de subir.
ROTAS_DE_TESTE = ("/api/_t_",)


def _rotas() -> list[str]:
    from api.main import app
    return sorted({r.path for r in app.routes
                   if getattr(r, "path", "").startswith("/api/")
                   and not r.path.startswith(ROTAS_DE_TESTE)})


def _tem_dono(caminho: str) -> bool:
    if any(caminho == p or caminho.startswith(p + "/")
           for p in FORA_DO_RBAC_DE_TELA):
        return True
    if any(caminho.startswith(pref) for pref, _ in auth.ROTA_TELAS):
        return True
    return any(caminho.startswith(pref)
               for pref in getattr(auth, "_ROTAS_SEM_TELA", ()))


def test_a_varredura_acha_rota_de_verdade():
    """Varredura que não acha nada passa por vacuidade: se o import do app
    mudar de forma, tudo aqui vira verde-para-sempre."""
    rotas = _rotas()
    assert len(rotas) > 100, f"só {len(rotas)} rotas — a varredura não está vendo o app"


def test_toda_rota_da_api_tem_dono_no_RBAC():
    """Rota sem mapeamento é 403 para todo não-admin — e ninguém descobre
    escrevendo o código, porque quem escreve costuma conferir como admin."""
    orfas = [c for c in _rotas() if not _tem_dono(c)]
    assert not orfas, (
        "rota(s) /api/* sem dono no RBAC — o middleware é fail-closed e elas "
        "vão devolver 403 para quem não é admin:\n  " + "\n  ".join(orfas) +
        "\n\nMapeie em `auth.ROTA_TELAS` (tela que a contém) ou em "
        "`auth._ROTAS_SEM_TELA` (todo usuário logado).")


@pytest.mark.parametrize("prefixo,motivo", sorted(FORA_DO_RBAC_DE_TELA.items()))
def test_a_excecao_descreve_rota_que_EXISTE(prefixo, motivo):
    """A lista de exceção descreve o código, então se confere contra ele.

    Prefixo que ninguém mais serve é exceção obsoleta — e exceção obsoleta é
    onde a próxima rota se esconde sem que ninguém repare.
    """
    rotas = _rotas()
    assert any(c.startswith(prefixo) for c in rotas), (
        f"{prefixo} não é servido por rota nenhuma — exceção obsoleta ({motivo})")


@pytest.mark.parametrize("prefixo", sorted(set(FORA_DO_RBAC_DE_TELA) - COEXISTENCIA_CONHECIDA))
def test_a_excecao_nao_engole_rota_que_TEM_tela(prefixo):
    """O outro lado: se um desses prefixos passar a ter mapeamento de tela, a
    exceção deixou de ser exceção e está escondendo o RBAC de verdade."""
    mapeadas = [p for p, _ in auth.ROTA_TELAS
                if p == prefixo or p.startswith(prefixo + "/")]
    assert not mapeadas, (
        f"{prefixo} está em FORA_DO_RBAC_DE_TELA e TAMBÉM em ROTA_TELAS "
        f"({mapeadas}) — uma das duas está errada, e a exceção vence calada.")
