# -*- coding: utf-8 -*-
"""O medidor e a rosca do painel de TV do cliente, EXECUTADOS.

Estes testes existem porque os primeiros que escrevi não valiam nada: eles
liam o TEXTO-FONTE do `index.html` — "o `path` está lá", "a palavra `zona`
aparece" — e continuavam verdes com a função sabotada, porque o código morto
continua escrito no arquivo. Teste que afirma implementação em vez de
comportamento é o "verde que nunca ficaria vermelho" da casa.

Aqui as funções são CHAMADAS no navegador e o que se afirma é o SVG que sai.
"""
from __future__ import annotations

import re


def _monta(pg, base_url, chamada):
    """Carrega o app e executa uma das funções de desenho da TV."""
    pg.goto(f"{base_url}/static/index.html")
    pg.wait_for_function("() => typeof tvCliGauge === 'function'", timeout=15000)
    return pg.evaluate(f"() => {chamada}")


# ------------------------------------------------------------------ medidor

def test_o_medidor_desenha_DOIS_arcos_quando_ha_faixa(pagina):
    """39% dentro e 31% na zona: o mural tem de mostrar o teto de 70%.

    A faixa do meio é o que este painel existe para não esconder — o contrato
    de freetime distingue por mercadoria e o apontamento não diz qual era.
    Numa parede ninguém lê o rodapé, então a ambiguidade tem de estar no
    desenho.
    """
    pg, base = pagina
    svg = _monta(pg, base, "tvCliGauge(38.6, 'ruim', 31.3)")
    arcos = re.findall(r'stroke="(#[0-9A-Fa-f]{6})"[^>]*stroke-dasharray="([\d.]+)', svg)
    cores = [c for c, _ in arcos]
    assert "#FBBF24" in cores, "o arco da faixa (âmbar) não foi desenhado"
    assert "#F87171" in cores, "o arco do conservador não foi desenhado"
    # o âmbar vai ATÉ 70% e o vermelho para em 39% — o teto é o arco maior
    val = {c: float(v) for c, v in arcos}
    assert val["#FBBF24"] > val["#F87171"]
    assert "até 70%" in svg


def test_sem_faixa_o_medidor_desenha_UM_arco_so(pagina):
    """Contrato único não tem zona cinzenta — inventar uma seria mentir para o
    outro lado."""
    pg, base = pagina
    svg = _monta(pg, base, "tvCliGauge(81.5, 'ok', 0)")
    assert "#FBBF24" not in svg
    assert "até" not in svg
    assert "82%" in svg or "81%" in svg


def test_sem_regua_o_medidor_nao_desenha_arco_nenhum(pagina):
    """Sem freetime cadastrado não há o que classificar, e verde sem régua é
    verde inventado."""
    pg, base = pagina
    saida = _monta(pg, base, "tvCliGauge(null, '', null)")
    assert "<svg" not in saida
    assert "sem régua" in saida


def test_o_arco_do_medidor_nao_passa_do_fim_da_escala(pagina):
    """100% preenche o arco inteiro; acima disso não estica."""
    pg, base = pagina
    svg = _monta(pg, base, "tvCliGauge(100, 'ok', 40)")
    vals = [float(v) for v in re.findall(r'stroke-dasharray="([\d.]+)', svg)]
    assert max(vals) <= 131.9 + 0.1, vals


# -------------------------------------------------------------------- rosca

def test_a_rosca_reparte_o_anel_na_proporcao_das_fatias(pagina):
    """3 / 30 / 33 de 66: as fatias somam a volta inteira, e cada uma vale o
    que representa."""
    pg, base = pagina
    svg = _monta(pg, base, """tvCliRosca([
        {rot:'Na origem', n:3, cor:'#8FA6BC'},
        {rot:'Em viagem', n:30, cor:'#4ADE80'},
        {rot:'No destino', n:33, cor:'#FBBF24'}])""")
    dashes = [float(d) for d in re.findall(r'stroke-dasharray="([\d.]+)', svg)]
    volta = 2 * 3.141592653589793 * 34
    assert len(dashes) == 3
    assert abs(sum(dashes) - volta) < 0.5, (dashes, volta)
    # a maior fatia (33) é a maior do desenho, e a menor (3) a menor
    assert max(dashes) == dashes[2] and min(dashes) == dashes[0]
    assert ">66<" in svg, "o total no meio do anel sumiu"


def test_a_rosca_omite_fatia_ZERO_e_nao_desenha_risco(pagina):
    """Categoria sem carga não vira um traço de largura zero no anel."""
    pg, base = pagina
    svg = _monta(pg, base, """tvCliRosca([
        {rot:'Na origem', n:0, cor:'#8FA6BC'},
        {rot:'Em viagem', n:5, cor:'#4ADE80'}])""")
    assert len(re.findall(r'<circle', svg)) == 1


def test_a_rosca_leva_o_numero_ao_lado_da_cor(pagina):
    """Sem tooltip numa TV, a legenda É a leitura."""
    pg, base = pagina
    svg = _monta(pg, base, """tvCliRosca([
        {rot:'Em viagem', n:30, cor:'#4ADE80'},
        {rot:'No destino', n:33, cor:'#FBBF24'}])""")
    assert "Em viagem" in svg and "<b>30</b>" in svg
    assert "No destino" in svg and "<b>33</b>" in svg


def test_rosca_sem_carga_nenhuma_diz_isso(pagina):
    pg, base = pagina
    saida = _monta(pg, base, "tvCliRosca([{rot:'Em viagem', n:0, cor:'#4ADE80'}])")
    assert "<circle" not in saida
    assert "nenhuma carga" in saida


# -------------------------------------------------------------- número em pt-BR

def test_horas_saem_com_VIRGULA(pagina):
    """"6.5h" saiu no mural do render real: concatenar float na string entrega
    o separador do JavaScript, não o do país."""
    pg, base = pagina
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_function("() => typeof tvH === 'function'", timeout=15000)
    assert pg.evaluate("() => tvH(6.5)") == "6,5h"
    assert pg.evaluate("() => tvH(3)") == "3h"
    assert pg.evaluate("() => tvH(null)") == "n/d"
