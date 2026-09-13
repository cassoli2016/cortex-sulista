"""O registro das abas bloqueáveis (`api/acessos.ABAS`) conferido contra o DISCO.

Aba só entra no registro se tirá-la for BLOQUEIO: o servidor recusa a rota
dela, e nada mais depende dessa rota. Uma entrada errada aqui não tem sintoma —
ou a aba some e o dado continua chegando por outra porta, ou tirar a aba
derruba outra tela. Por isso cada unidade é conferida contra a página e contra
o app, e não contra a lista que alguém escreveu à mão:

1. a aba existe na página (botão na barra e painel);
2. cada rota existe no app, e o `ROTA_TELAS` a entrega à tela da unidade;
3. TODA menção à rota na página está dentro das funções declaradas da
   unidade — rota que outra tela também lê não é bloqueável por aba;
4. nenhuma outra página servida (app do motorista, rastreio) cita a rota;
5. todo `leitor` pergunta `abaOculta()` antes de buscar;
6. as unidades não se sobrepõem, e o registro não está vazio.
"""
from __future__ import annotations

import bisect
import re
from pathlib import Path

import pytest

from api import acessos, auth

RAIZ = Path(__file__).resolve().parents[1]
STATIC = RAIZ / "api" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
OUTRAS = {p.name: p.read_text(encoding="utf-8") for p in STATIC.glob("*.html")
          if p.name != "index.html"}

_DECL = [(m.start(), m.group(1)) for m in re.finditer(
    r"^(?:async function|function|const|let|var|class)\s+(\w+)", HTML, re.M)]
_POS = [p for p, _ in _DECL]

UNIDADES = sorted(acessos.ABAS)


def _funcao_em(pos: int) -> str | None:
    i = bisect.bisect_right(_POS, pos) - 1
    return _DECL[i][1] if i >= 0 else None


def _corpo(nome: str) -> str:
    m = re.search(r"^(?:async )?function " + re.escape(nome) + r"\s*\(", HTML, re.M)
    assert m, f"função {nome} não existe na página"
    i = bisect.bisect_right(_POS, m.start())
    fim = _POS[i] if i < len(_POS) else len(HTML)
    return HTML[m.start():fim]


def _mencoes(rota: str, exata: bool) -> list[int]:
    fim = r"(?=[?'\"`$])" if exata else r"(?=[/?'\"`$])"
    return [m.start() for m in re.finditer(re.escape(rota) + fim, HTML)]


def _rotas_do_app() -> list[str]:
    """Todas as rotas do app, INCLUSIVE as dos routers incluídos.

    No FastAPI 0.139 `include_router` não copia as rotas para `app.routes`:
    guarda um `_IncludedRouter` com o router original dentro. Ler só
    `app.routes` enxerga as rotas do `main.py` e perde auth, gestão, CRM,
    Suporte, Equipamentos e WMS inteiros — e aí "a rota não existe" seria
    mentira (visto em 13/09/2026, nas unidades do Suporte e do WMS).
    """
    from api.main import app
    saida: list[str] = []

    def andar(rotas, prefixo: str = "") -> None:
        for r in rotas:
            if type(r).__name__ == "_IncludedRouter":
                andar(r.original_router.routes,
                      prefixo + (getattr(r.include_context, "prefix", "") or ""))
            elif getattr(r, "path", ""):
                saida.append(prefixo + r.path)

    andar(app.routes)
    assert any(p.startswith("/api/suporte/") for p in saida), "a leitura perdeu os routers incluídos"
    return saida


def test_o_registro_nao_esta_vazio():
    """Varredura que não acha nada passa por vacuidade."""
    assert len(acessos.ABAS) >= 25


@pytest.mark.parametrize("chave", UNIDADES)
def test_a_unidade_e_de_uma_tela_do_registro(chave):
    u = acessos.ABAS[chave]
    assert u["tela"] in auth.TELAS
    assert chave.split(".")[0] == u["tela"], "a chave começa pela tela"
    assert u["leitores"], "sem leitor, ninguém busca — a unidade não protege dado nenhum"


@pytest.mark.parametrize("chave", UNIDADES)
def test_cada_aba_existe_na_pagina(chave):
    for g, k in acessos.ABAS[chave]["abas"]:
        barra = re.search(r'<div class="subtabs[^"]*"[^>]*data-abas="' + re.escape(g) + r'"[^>]*>(.*?)</div>',
                          HTML, re.S)
        assert barra, f"{chave}: não há barra de abas '{g}'"
        assert re.search(r'<button[^>]*\bdata-aba="' + re.escape(k) + r'"', barra.group(1)), \
            f"{chave}: a barra '{g}' não tem a aba '{k}'"
        assert re.search(r'<[^>]*\bclass="aba\b[^"]*"[^>]*\bdata-abas="' + re.escape(g)
                         + r'"[^>]*\bdata-aba="' + re.escape(k) + r'"', HTML) or \
            re.search(r'<[^>]*\bdata-abas="' + re.escape(g) + r'"[^>]*\bdata-aba="'
                      + re.escape(k) + r'"[^>]*\bclass="aba\b', HTML), \
            f"{chave}: não há painel .aba '{g}.{k}'"


@pytest.mark.parametrize("chave", UNIDADES)
def test_cada_rota_existe_no_app_e_e_da_tela_da_unidade(chave):
    u = acessos.ABAS[chave]
    app = _rotas_do_app()
    for p in u["rotas"]:
        assert any(r == p or r.startswith(p + "/") for r in app), f"{chave}: {p} não existe no app"
    for e in u["exatas"]:
        assert e in app, f"{chave}: {e} não existe no app"
    for r in (*u["rotas"], *u["exatas"]):
        telas = auth._telas_da_rota(r)
        assert telas and u["tela"] in telas, f"{chave}: {r} não é entregue à tela {u['tela']}"


@pytest.mark.parametrize("chave", UNIDADES)
def test_toda_mencao_a_rota_esta_nos_carregadores_da_unidade(chave):
    u = acessos.ABAS[chave]
    donas = set(u["leitores"]) | set(u["acoes"])
    for rota, exata in [(r, False) for r in u["rotas"]] + [(e, True) for e in u["exatas"]]:
        achadas = _mencoes(rota, exata)
        assert achadas, f"{chave}: a página não cita {rota} — rota morta ou grafia errada"
        fora = sorted({_funcao_em(p) for p in achadas} - donas)
        assert not fora, f"{chave}: {rota} também é lida por {fora} — não é bloqueável por aba"


@pytest.mark.parametrize("chave", UNIDADES)
def test_nenhuma_outra_pagina_cita_a_rota(chave):
    u = acessos.ABAS[chave]
    for nome, texto in OUTRAS.items():
        for r in (*u["rotas"], *u["exatas"]):
            assert r not in texto, f"{chave}: {nome} usa {r}"


@pytest.mark.parametrize("chave", UNIDADES)
def test_todo_leitor_pula_quando_a_aba_esta_oculta(chave):
    u = acessos.ABAS[chave]
    pares = {(g, k) for g, k in u["abas"]}
    for nome in u["leitores"]:
        m = re.search(r"abaOculta\('(\w+)','(\w+)'\)", _corpo(nome))
        assert m and (m.group(1), m.group(2)) in pares, \
            f"{chave}: {nome} busca sem perguntar se a aba foi tirada"


def test_as_unidades_nao_se_sobrepoem():
    todas = [(c, r) for c, u in acessos.ABAS.items() for r in (*u["rotas"], *u["exatas"])]
    for c1, r1 in todas:
        for c2, r2 in todas:
            if c1 != c2:
                assert acessos.aba_da_rota(r2) != c1, f"{r2} ({c2}) cai também na unidade {c1}"


def test_cada_rota_registrada_cai_na_propria_unidade():
    for c, u in acessos.ABAS.items():
        for r in (*u["rotas"], *u["exatas"]):
            assert acessos.aba_da_rota(r) == c


def test_rota_exata_nao_engole_a_vizinha():
    """A Projeção é `/api/financeiro/projecao`; `/projecao/detalhe` é o drill
    de OUTRAS abas do Fluxo Consolidado e não pode cair junto."""
    assert acessos.aba_da_rota("/api/financeiro/projecao") == "fluxcon.plano"
    assert acessos.aba_da_rota("/api/financeiro/projecao/detalhe") is None
