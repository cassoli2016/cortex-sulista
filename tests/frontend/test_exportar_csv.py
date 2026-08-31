# -*- coding: utf-8 -*-
"""Exportar CSV: as tres coisas que o Excel em portugues quebra.

Primeira exportacao de tabela desta casa, e o helper (`baixarCSV`) nasceu
generico porque a proxima vai querer o mesmo. Os tres detalhes abaixo parecem
formatacao e nao sao -- cada um produz um arquivo que ABRE SEM ERRO e mostra a
coisa errada, que e o modo de falhar mais caro:

  BOM UTF-8         sem ele o Excel pt-BR le em ANSI e "JOSE" com acento vira
                    "JOSÃ‰". O arquivo esta certo e a planilha mostra lixo --
                    e a culpa parece do sistema que exportou.
  SEPARADOR `;`     no Excel pt-BR a virgula e decimal: com `,` a linha
                    inteira cai numa coluna so.
  ASPAS             nome com `;` ou com aspa desloca todas as colunas dali para
                    a frente, e a planilha abre sem reclamar, com os dados na
                    coluna errada.

E o valor sai com VIRGULA decimal e sem separador de milhar, porque ele precisa
ser NUMERO na planilha -- somar a coluna e a primeira coisa que alguem faz com
o arquivo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# Duas linhas com o que quebra: ponto-e-virgula no cargo, aspa no nome, acento
# em tudo. Duble copia o formato do ERP, nao um caso limpo.
CUSTO = {
    "periodo": {"de": "2025-09-01", "ate": "2026-08-31"}, "meses": 12,
    "filtros": {}, "naturezas": [], "eventos": [], "eventos_total": 0,
    "serie": [], "provisao_filial": [],
    "cinza": {"nome": "x", "valor": 0, "n": 0, "com_ferias": 0, "pct": 0},
    "agendadas": {
        "n": 2, "dias": 36, "dias_abono": 10, "com_abono": 1, "agora": 1,
        "custo": 9000.0, "custo_gozo": 7000.0, "custo_abono": 2000.0,
        "dias_medios": 18.0, "unidades": 1, "por_mes": [],
        "pico": {"mes": "2026-09", "n": 2, "dias": 36, "custo": 9000.0},
        "por_unidade": [{"filial": "FILIAL SBC", "pessoas": 2, "dias": 36,
                         "custo": 9000.0}],
        "detalhe": [
            {"nome": 'JOSÉ D"ÁVILA', "chapa": "001912",
             "cargo": "COORDENADOR; FATURAMENTO", "area": "FINANCEIRO",
             "filial": "FILIAL SBC", "ini": "2026-09-01", "fim": "2026-09-20",
             "dias": 20, "dias_abono": 10, "ab_ini": "2026-09-21",
             "ab_fim": "2026-09-30", "agora": True, "custo": 6543.21},
            {"nome": "MARIA CLARA", "chapa": "003807", "cargo": "AUX OPER",
             "area": "CRUZEIRO", "filial": "FILIAL SBC", "ini": "2026-09-05",
             "fim": "2026-09-20", "dias": 16, "dias_abono": 0,
             "ab_ini": None, "ab_fim": None, "agora": False, "custo": 2456.79},
        ],
    },
    "kpis": {"realizado": 0, "dobra_paga": 0, "dobra_lanc": 0, "medio_mes": 0,
             "agendado": 9000.0, "agendado_n": 2, "agendado_dias": 36,
             "provisao": 0, "prov_vencido": 0, "prov_avos": 0, "prov_fgts": 0,
             "exposicao": 0, "exposicao_n": 0, "dias_gozados": 0,
             "fator": 1.08, "fgts_pct": 8.0},
    "fonte": "t", "atualizado_em": "2026-08-31 09:00",
}
FER = {
    "dias": 90, "colaboradores": [], "filtros": {}, "filiais": [],
    "agenda_mensal": [], "janela_futura": {"de": "2026-08-31", "ate": "2027-07-31"},
    "duplicadas": 0,
    "kpis": {"ativos": 2, "com_direito": 0, "sem_agenda": 0, "segundo_6": 0,
             "em_dobra": 0, "dobra_prazo": 0, "dobra_30": 0, "agendados": 2,
             "em_ferias_agora": 1, "ficha_parada": 0, "filiais": 1},
    "por_filial": [], "fila": [], "agenda": [], "fichas_paradas": [],
    "fonte": "t", "atualizado_em": "2026-08-31 09:00",
}


@pytest.fixture()
def tela(pagina):
    pg, base_url = pagina

    def rota(route):
        u = route.request.url
        c = (ADMIN if "/api/auth/me" in u
             else CUSTO if "/ferias/custo" in u
             else FER if "/api/rh/ferias" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(c, ensure_ascii=False))

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#ferias")
    pg.wait_for_selector("#kpis-ferias .kpi", timeout=20000)
    pg.click("#tabferias-agenda")
    pg.wait_for_selector("#fer-agendadas tr", timeout=20000)
    return pg


def _baixar(pg, tmp_path: Path) -> str:
    with pg.expect_download() as info:
        pg.click("#btnFerAgCsv")
    destino = tmp_path / "saida.csv"
    info.value.save_as(str(destino))
    bruto = destino.read_bytes()
    assert bruto[:3] == b"\xef\xbb\xbf", (
        "sem BOM UTF-8 o Excel pt-BR le em ANSI e todo acento vira lixo")
    return bruto.decode("utf-8-sig")


def test_o_acento_chega_INTEIRO(tela, tmp_path):
    txt = _baixar(tela, tmp_path)
    assert "Funcionário" in txt and "Início do gozo" in txt
    assert "Ã" not in txt, "acento remontado errado"


def test_o_separador_e_ponto_e_virgula(tela, tmp_path):
    """Com virgula, o Excel pt-BR joga a linha inteira numa coluna so."""
    linhas = [l for l in _baixar(tela, tmp_path).split("\r\n") if l]
    assert linhas[0].count(";") == 12, linhas[0]


def test_ponto_e_virgula_DENTRO_do_campo_nao_desloca_coluna(tela, tmp_path):
    """`COORDENADOR; FATURAMENTO` sem aspas empurraria todas as colunas dali
    para a frente -- e a planilha abriria sem reclamar, com o custo caindo na
    coluna da data."""
    import csv
    import io
    txt = _baixar(tela, tmp_path)
    linhas = list(csv.reader(io.StringIO(txt), delimiter=";"))
    assert len({len(l) for l in linhas if l} - {0}) == 1, (
        "linhas com numero de colunas diferente: %s"
        % [len(l) for l in linhas if l])
    dados = [l for l in linhas[1:] if l]
    assert dados[0][2] == "COORDENADOR; FATURAMENTO"


def test_aspa_no_nome_sobrevive(tela, tmp_path):
    """Aspa dentro de campo entre aspas precisa ser DOBRADA."""
    import csv
    import io
    linhas = list(csv.reader(io.StringIO(_baixar(tela, tmp_path)), delimiter=";"))
    assert linhas[1][0] == 'JOSÉ D"ÁVILA'


def test_o_valor_e_NUMERO_para_a_planilha(tela, tmp_path):
    """Virgula decimal e SEM ponto de milhar: com o ponto, o Excel pt-BR le
    como texto em algumas configuracoes e a coluna deixa de somar -- e somar a
    coluna e a primeira coisa que alguem faz com o arquivo."""
    import csv
    import io
    linhas = list(csv.reader(io.StringIO(_baixar(tela, tmp_path)), delimiter=";"))
    valores = [l[12] for l in linhas[1:] if l]
    assert valores == ["6543,21", "2456,79"], valores
    assert not any("." in v for v in valores), "ponto de milhar quebra a soma"


def test_exporta_o_que_esta_VISIVEL_e_nao_a_base_inteira(tela, tmp_path):
    """Quem buscou um nome espera levar aquilo. Exportar a base inteira depois
    de filtrar entrega um arquivo que nao e o que estava na tela -- e ninguem
    confere linha por linha o que acabou de baixar."""
    tela.fill("#fFerAgBusca", "maria")
    tela.wait_for_timeout(300)
    linhas = [l for l in _baixar(tela, tmp_path).split("\r\n") if l]
    assert len(linhas) == 2, "cabecalho + a unica linha que casou"
    assert "MARIA CLARA" in linhas[1]


def test_o_nome_do_arquivo_leva_a_DATA(tela):
    """Quem recebe o arquivo por e-mail precisa saber de quando ele e sem abrir."""
    import re
    with tela.expect_download() as info:
        tela.click("#btnFerAgCsv")
    assert re.match(r"ferias-agendadas-\d{4}-\d{2}-\d{2}\.csv$",
                    info.value.suggested_filename), info.value.suggested_filename


def test_sem_linha_visivel_AVISA_em_vez_de_baixar_arquivo_vazio(tela):
    """Um CSV so com cabecalho parece dado que sumiu."""
    tela.fill("#fFerAgBusca", "zzzzzz")
    tela.wait_for_timeout(300)
    tela.click("#btnFerAgCsv")
    tela.wait_for_timeout(400)
    assert tela.is_visible("#banner"), "deveria avisar que nao ha o que exportar"
