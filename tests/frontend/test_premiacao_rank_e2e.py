"""Ranking de motoristas da Premiação (#prem) contra o index.html real.

O payload sai do CÁLCULO de verdade sobre o snapshot real de julho/2026 — assim
o teste cobre a ponta a ponta (regra → render → ordenação) e não uma fixture
inventada que concorda com o código por construção.

POR QUE ordenar é o comportamento que importa aqui: o prêmio é km × valor ×
(nota/100). Em julho o km varia 5,5× entre motoristas e a nota só 1,4× — o
ranking por prêmio é dominado pelo km e NÃO ordena conduta. Ordenar por Nota é
a única forma de ler conduta nesta tela.
"""
from __future__ import annotations

import json
from pathlib import Path

from api.premiacao import calculo
from tests.frontend.conftest import USUARIO

RAIZ = Path(__file__).resolve().parents[2]
SNAP = RAIZ / "data" / "premiacao" / "premiacao-2026-07.json"
PARAMS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}


def _payload():
    drivers = json.loads(SNAP.read_text(encoding="utf-8"))["drivers"]
    calc = calculo.calcular(drivers, PARAMS)
    return {**calc, "mes": "2026-07", "coletado_em": "2026-08-01T10:00:00",
            "configurado": True, "parcial": False}


def _abrir(pg, base):
    corpo = _payload()

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            c = USUARIO
        elif "/api/frota/premiacao/serie" in u:
            c = {"meses": []}
        elif "/api/frota/premiacao" in u:
            c = corpo
        elif "/api/versao" in u:
            c = {"versao": "0.9.0", "rotulo": "CX-19/08/2026-v0.9.0", "data": "2026-08-19"}
        else:
            c = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(c))

    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#prem")
    pg.wait_for_selector("#prem-rank tr.forn-row", timeout=20000)
    return corpo


def _coluna(pg, idx):
    """Valores de uma coluna das linhas visíveis, na ordem em que estão na tela."""
    return pg.eval_on_selector_all(
        "#prem-rank tr.forn-row",
        f"ls=>ls.map(l=>l.children[{idx}].innerText.trim())")


def test_abre_ordenado_por_premio_maior_primeiro(pagina):
    pg, base = pagina
    corpo = _abrir(pg, base)
    premios = [float(v.replace("R$", "").replace(".", "").replace(",", ".").strip())
               for v in _coluna(pg, 3)]
    assert premios == sorted(premios, reverse=True)
    assert len(premios) == len(corpo["linhas"])


def test_clicar_em_nota_reordena_por_conduta(pagina):
    """Ordenar por nota tem de mudar a leitura da tela, não só o cabeçalho.

    O topo pode coincidir: notas empatam (vários 99) e o desempate cai na ordem
    de entrada, que é a de prêmio. O que prova a ordenação é a lista INTEIRA
    mudar, e quem tem nota alta com prêmio baixo subir de verdade.
    """
    pg, base = pagina
    _abrir(pg, base)
    por_premio = _coluna(pg, 0)
    pg.click("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.wait_for_timeout(120)
    notas = [float(v) for v in _coluna(pg, 1) if v not in ("—", "")]
    assert notas == sorted(notas, reverse=True), "clicar em Nota não ordenou por nota"

    por_nota = _coluna(pg, 0)
    assert sorted(por_nota) == sorted(por_premio), "reordenar não pode perder linha"
    iguais = sum(1 for a, b in zip(por_premio, por_nota) if a == b)
    assert iguais < len(por_premio) // 2, (
        f"as duas ordens são quase iguais ({iguais}/{len(por_premio)} na mesma "
        "posição) — a coluna não estaria dando leitura nova")


def test_nota_alta_com_premio_baixo_sobe_ao_ordenar_por_nota(pagina):
    """O caso que justifica a coluna: em jul/2026 um motorista com nota 98
    (quase o teto) tem prêmio de R$ 77 por ter rodado pouco, e some no fim do
    ranking por prêmio. É o motorista que a premiação por CONDUTA destacaria."""
    pg, base = pagina
    corpo = _abrir(pg, base)
    # entre os ELEGÍVEIS: quem recebeu prêmio apesar de rodar pouco, com nota alta.
    # Inelegível tem prêmio 0 e venceria o critério sem dizer nada sobre conduta.
    elig = [l for l in corpo["linhas"] if l.get("elegivel")]
    alvo = max(elig, key=lambda l: (l.get("nota") or 0) - (l.get("premio") or 0) / 8)
    nome = alvo["driverName"]

    # a célula do nome pode trazer o badge do motivo junto — casar por prefixo
    def pos(nome):
        col = _coluna(pg, 0)
        for i, txt in enumerate(col):
            if txt.startswith(nome):
                return i
        raise AssertionError(f"{nome!r} não está na tabela")

    pos_premio = pos(nome)
    pg.click("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.wait_for_timeout(120)
    pos_nota = pos(nome)
    assert pos_nota < pos_premio, (
        f"{nome} (nota {alvo.get('nota')}, prêmio {alvo.get('premio')}) estava em "
        f"{pos_premio} por prêmio e foi para {pos_nota} por nota — deveria subir")


def test_segundo_clique_inverte_a_ordem(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.wait_for_timeout(120)
    pg.click("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.wait_for_timeout(120)
    notas = [float(v) for v in _coluna(pg, 1) if v not in ("—", "")]
    assert notas == sorted(notas), "segundo clique deveria inverter para menor primeiro"


def test_ordena_pelo_teclado(pagina):
    """O <th> é role=button: quem navega por teclado precisa conseguir ordenar."""
    pg, base = pagina
    _abrir(pg, base)
    pg.focus("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(120)
    notas = [float(v) for v in _coluna(pg, 1) if v not in ("—", "")]
    assert notas == sorted(notas, reverse=True)


def test_hint_diz_por_qual_coluna_esta_ordenado(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert "prêmio" in pg.inner_text("#prem-rank-hint").lower()
    pg.click("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.wait_for_timeout(120)
    assert "nota" in pg.inner_text("#prem-rank-hint").lower()


def test_nao_elegivel_continua_visivel_depois_de_reordenar(pagina):
    """Quem ficou de fora do prêmio não pode sumir da lista ao trocar a ordem —
    o gestor precisa ver quem não recebeu e por quê."""
    pg, base = pagina
    corpo = _abrir(pg, base)
    fora = sum(1 for l in corpo["linhas"] if not l.get("elegivel"))
    assert fora > 0, "fixture sem inelegíveis não exercita este caso"
    pg.click("#prem-rank >> xpath=../thead/tr/th[2]")
    pg.wait_for_timeout(120)
    assert len(_coluna(pg, 0)) == len(corpo["linhas"])
