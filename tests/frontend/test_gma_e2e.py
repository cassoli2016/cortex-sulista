# -*- coding: utf-8 -*-
"""A tela da Gestão de Motoristas, com payload CHEIO e no navegador de verdade.

POR QUE ESTE ARQUIVO EXISTE, se `scripts/medir_paineis.py` já mede a tela: a
régua roda com a API devolvendo `{}` e mede o ESQUELETO — tabela vazia, aviso
mudo. A aba "O dia" da Frequência passou com 381px e media 1.060 com o dia
real. Aqui o dublê sai do TETO DO CADASTRO (os motoristas próprios da folha,
todos com desvio e medida), que é o maior que a tela pode ficar.

O que mais se prova aqui, e só aqui:

- a tela abre na régua NOVA e o modelo que paga hoje continua alcançável;
- o gráfico das categorias é redesenhado AO ABRIR a aba — ECharts mede o
  contêiner uma vez, e medida feita sob `hidden` vale zero para sempre;
- ausência não vira R$ 0,00: a linha sem valor base diz o motivo;
- o CPF não chega ao navegador.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# O TETO DO CADASTRO, não o maior ciclo já visto: a folha tem ~83 motoristas
# próprios, e é esse o número que a tela precisa aguentar. Todos com desvio e
# medida sugerida — o pior caso de conteúdo por linha.
N = 83
FILIAIS = ["SBC", "JOI", "MTZ", "CRZ", "PSA"]


def _linha(i):
    return {
        "motorista": str(1000 + i), "nome": f"MOTORISTA DE NOME COMPRIDO {i:02d}",
        "tipo": "MANOBRA" if i % 4 == 0 else "RODOVIARIO",
        "filial": None if i == 7 else FILIAIS[i % len(FILIAIS)],
        "admissao": "2019-03", "gobrax": 70.0 + (i % 30),
        "km": 5000.0 + i, "conduta": 60.0 + (i % 40),
        "desvios": [{"cod": "D07", "nome": "Excesso de velocidade", "grav": "MODERADA",
                     "pts": 7, "data": "2026-09-01"}],
        "meritos": 1, "gr": 40.0 + (i % 50), "gr_viagens": 3 if i % 9 == 0 else 12,
        "gr_risco": 30.0 + i, "gr_insuficiente": i % 9 == 0,
        "gr_contadores": {"velocidade": 9, "area_de_risco": 2, "desvio_rota": 1,
                          "painel": 1, "antena": 1},
        "gr_informativos": {"desengate": 5, "panico": 1, "rodou_fora_horario": 0},
        "nota": 55.0 + (i % 45), "pilares": ["gobrax", "conduta", "gr"],
        "ausentes": [], "status": ["EXCELENTE", "BOM", "ATENCAO", "ALERTA"][i % 4],
        "reputacao": 70.0 + (i % 40), "categoria": ["ELITE", "DIAMANTE", "OURO", "PRATA", "BRONZE"][i % 5],
        "rep_conduta": 80.0 + (i % 30), "ciclos_limpos": i % 7,
        "desvios_6": i % 5, "meritos_6": i % 3,
        "medida": {"nivel": "N4", "medida": "Suspensão (RH)",
                   "porque": "4 desvios em 6 ciclos", "reincidencia_3": 2,
                   "reincidencia_6": 4, "sugerida": True},
    }


CICLO = {
    "ciclo": "2026-09", "rotulo": "16/08 a 15/09 de 2026", "mes_gobrax": "2026-08",
    "linhas": [_linha(i) for i in range(N)],
    "kpis": {"motoristas": N, "com_nota": N, "sem_nota": 0, "nota_mediana": 88.0,
             "por_status": {"EXCELENTE": 21, "BOM": 21, "ATENCAO": 21, "ALERTA": 20},
             "por_categoria": {"ELITE": 17, "DIAMANTE": 17, "OURO": 17, "PRATA": 16,
                               "BRONZE": 16},
             "com_desvio": N, "com_medida": N, "com_pilar_faltando": 40},
    "parametros": {},
    "fontes": {"gobrax": {"motivo": "", "coletado_em": "2026-09-16T03:10:00",
                          "parcial": False, "com_nota": 41},
               "conduta": {"motivo": ""}, "gr": {"motivo": "", "com_viagem": 75}},
    "pendencias": {"codigos_sem_depara": [{"codigo": 79, "descricao": "AVARIA EM CARGA", "vezes": 12},
                                          {"codigo": 80, "descricao": "ATRASO NA ENTREGA", "vezes": 4},
                                          {"codigo": 81, "descricao": "RECUSA DE CARGA", "vezes": 1}],
                   "ocorrencias_sem_codigo": 5, "gobrax_ambiguos": ["JOSE SANTOS"],
                   "gobrax_fora_do_cadastro": 45, "sem_filial": 1, "tipo_sugerido": N},
}

CATALOGO = {
    "ciclo": "2026-09", "rotulo": "16/08 a 15/09 de 2026",
    "ciclos": ["2026-09", "2026-08", "2026-07", "2026-06", "2026-05", "2026-04",
               "2026-03", "2026-02", "2026-01", "2025-12", "2025-11", "2025-10", "2025-09"],
    "grupos": ["RODOVIARIO", "MANOBRA"],
    "parametros": [{"chave": "peso_gobrax", "padrao": 40, "rotulo": "Peso da Gobrax (%)", "explica": "x"},
                   {"chave": "peso_conduta", "padrao": 40, "rotulo": "Peso do comportamento (%)", "explica": "x"},
                   {"chave": "peso_gr", "padrao": 20, "rotulo": "Peso do GR (%)", "explica": "x"},
                   {"chave": "gr_referencia", "padrao": 58, "rotulo": "GR: risco de referência", "explica": "x"},
                   {"chave": "gr_queda", "padrao": 40, "rotulo": "GR: queda máxima", "explica": "x"},
                   {"chave": "gr_piso", "padrao": 20, "rotulo": "GR: piso da nota", "explica": "x"},
                   {"chave": "gr_minimo_viagens", "padrao": 5, "rotulo": "GR: mínimo de viagens", "explica": "x"},
                   {"chave": "bonus_ciclo_limpo", "padrao": 2, "rotulo": "Bônus por ciclo limpo", "explica": "x"},
                   {"chave": "status_excelente", "padrao": 92, "rotulo": "Status: excelente a partir de", "explica": ""},
                   {"chave": "status_bom", "padrao": 85, "rotulo": "Status: bom a partir de", "explica": ""},
                   {"chave": "status_atencao", "padrao": 75, "rotulo": "Status: atenção a partir de", "explica": ""},
                   {"chave": "status_alerta", "padrao": 65, "rotulo": "Status: alerta a partir de", "explica": ""},
                   {"chave": "cat_elite", "padrao": 105, "rotulo": "Categoria: Elite a partir de", "explica": ""},
                   {"chave": "cat_diamante", "padrao": 95, "rotulo": "Categoria: Diamante a partir de", "explica": ""},
                   {"chave": "cat_ouro", "padrao": 85, "rotulo": "Categoria: Ouro a partir de", "explica": ""},
                   {"chave": "cat_prata", "padrao": 70, "rotulo": "Categoria: Prata a partir de", "explica": ""}],
    "parametros_do_ciclo": {g: {"grupo": g, "ciclo": "2026-09", "versao": 3,
                                "vigente_de": "2026-09",
                                "valores": {"peso_gobrax": 40, "peso_conduta": 40,
                                            "peso_gr": 20, "gr_referencia": 58,
                                            "gr_queda": 40, "gr_piso": 20,
                                            "gr_minimo_viagens": 5}}
                            for g in ("RODOVIARIO", "MANOBRA")},
    "desvios": [{"cod": f"D{i:02d}", "nome": f"Desvio de conduta número {i}",
                 "grav": "GRAVE", "pts": 12, "jan": 6} for i in range(1, 15)],
    "meritos": [{"cod": f"M{i:02d}", "nome": f"Mérito número {i}", "pts": 10}
                for i in range(1, 11)],
    "contadores_gr": [], "so_informativos": [
        {"contador": "desengate", "rotulo": "desengate", "porque": "alarme de equipamento"}],
    "depara": {str(c): "D07" for c in range(1, 48)},
    "cadastro": {"total": N, "ativos": N, "manobra": 20, "decididos": 3,
                 "sem_filial": 1, "ultima": "2026-09-18T08:00:00"},
}

PAGAMENTO = {
    "ciclo": "2026-09", "rotulo": "16/08 a 15/09 de 2026", "fonte": "cálculo",
    "fechado": False, "fechamento": None, "eventos": [],
    "linhas": [{**{k: x[k] for k in ("motorista", "nome", "tipo", "filial", "nota",
                                     "status", "categoria")},
                "meses_casa": 80 if i % 4 else None,
                "base": None if i == 7 else 1000.0,
                "base_origem": "sem_filial" if i == 7 else ("ajuste" if i == 3 else "tabela"),
                "base_rotulo": "motorista sem filial no cadastro" if i == 7 else
                               ("ajuste do ciclo" if i == 3 else "tabela por filial"),
                "ajuste_motivo": "acordo de transição" if i == 3 else "",
                "pct": None if i == 7 else 90.0,
                "valor": None if i == 7 else 900.0,
                "motivo": "motorista sem filial no cadastro" if i == 7 else ""}
               for i, x in enumerate(CICLO["linhas"])],
    "tabela": {"base": {"RODOVIARIO": {f: {"valor": 1000.0, "usa_escada": False, "nota": ""}
                                       for f in FILIAIS},
                        "MANOBRA": {f: {"valor": 500.0, "usa_escada": f in ("SBC", "JOI"),
                                        "nota": "pago em outra verba" if f == "CRZ" else ""}
                                    for f in FILIAIS}},
               "escada": {"MANOBRA": [{"ate_meses": 6, "valor": 100.0},
                                      {"ate_meses": 12, "valor": 200.0},
                                      {"ate_meses": 9999, "valor": 300.0}]},
               "versao": 3, "vigente_de": "2026-09", "motivo": ""},
    "kpis": {"motoristas": N, "a_pagar": 73800.0, "teto": 82000.0, "pagos": N - 1,
             "sem_valor": 1, "sem_nota": 0, "sem_tabela": 1, "ajustados": 1},
    "fontes": CICLO["fontes"], "pendencias": CICLO["pendencias"],
}

MOTORISTAS = {
    "estado": CATALOGO["cadastro"],
    "linhas": [{"nome": x["nome"], "cadastro_codigo": x["motorista"],
                "chapa": "C" + x["motorista"], "tipo": x["tipo"],
                "tipo_origem": "sugerido", "filial": x["filial"],
                "filial_origem": "folha", "admissao": "2019-03",
                "funcao": "MOTORISTA CARRETEIRO", "ativo": 1,
                "gobrax_driver_id": None, "sincronizado_em": "2026-09-18T08:00:00",
                "atualizado_em": None, "atualizado_por": None}
               for x in CICLO["linhas"]],
}

ALTURA = """() => {
  const c = document.getElementById('content');
  const b = c.querySelector('#banner');
  const fora = (b && b.offsetParent !== null)
    ? Math.round(b.getBoundingClientRect().height) + 14 : 0;
  return Math.round(c.scrollHeight) - fora;
}"""
LARGURA = ("() => Math.max(0, document.documentElement.scrollWidth"
           " - document.documentElement.clientWidth)")


def _abrir(pg, base_url, pagamento=None):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/premiacao/gma/catalogo" in u:
            corpo = CATALOGO
        elif "/api/premiacao/gma/ciclo" in u:
            corpo = CICLO
        elif "/api/premiacao/gma/pagamento" in u:
            corpo = pagamento if pagamento is not None else PAGAMENTO
        elif "/api/premiacao/gma/valores" in u:
            corpo = PAGAMENTO["tabela"]
        elif "/api/premiacao/gma/motoristas" in u:
            corpo = MOTORISTAS
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base_url + "/static/index.html#prem")
    pg.wait_for_timeout(900)
    return erros


# ───────────────────────────────────────────────────────── a tela abre
def test_a_tela_abre_na_regua_NOVA_e_o_modelo_que_paga_continua_alcancavel(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    assert pg.is_visible("#aba-rank"), "a tela abre no ranking do ciclo"
    assert not pg.is_visible("#aba-prem"), "o modelo antigo é uma aba, não a tela"
    pg.click("#tabprem-prem")
    assert pg.is_visible("#aba-prem")
    assert pg.is_visible("#fPremMes"), "o seletor de mês do modelo antigo continua lá"


def test_a_linha_traz_os_tres_pilares_e_a_medida_sugerida(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.eval_on_selector_all("#gma-rank tr", "els => els.length") == N
    linha = pg.inner_text("#gma-rank tr:first-child")
    assert "MOTORISTA DE NOME COMPRIDO" in linha
    assert "N4" in linha and "Suspensão" in linha
    assert "4 desvios em 6 ciclos" in linha


def test_o_KPI_diz_quantas_notas_sairam_com_pilar_faltando(pagina):
    """Metade da base não tem leitura da Gobrax. Isso não é nota de rodapé: é o
    tamanho do buraco de onde o número saiu."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    banda = pg.inner_text("#kpis-gma")
    assert "40" in banda and "pilar faltando" in banda.lower()


def test_as_pendencias_de_cadastro_aparecem_na_tela(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    txt = pg.inner_text("#gma-rank-pend")
    assert "3 códigos do ERP sem decisão" in txt
    assert "45 nomes da Gobrax fora do cadastro" in txt
    assert "1 sem filial" in txt


# ───────────────────────────────────────────── a régua de altura, CHEIA
def test_cada_aba_cabe_em_UMA_tela_com_a_base_inteira(pagina):
    """Com dublê vazio a tela mede o esqueleto; aqui ela mede o teto do
    cadastro. Cada aba vale por si — a régua da casa mede a MAIS ALTA."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    for aba in ("rank", "prm", "val", "gr", "oco", "base", "cat", "reg"):
        pg.click(f"#tabprem-{aba}")
        pg.wait_for_timeout(350)
        alt = pg.evaluate(ALTURA)
        assert alt <= 900, f"a aba {aba} mede {alt}px com a base inteira"
        assert pg.evaluate(LARGURA) == 0, f"a aba {aba} empurra a página para o lado"


def test_a_tabela_do_ranking_ROLA_DENTRO_do_card(pagina):
    """83 linhas não cabem na tela. A rolagem é DA TABELA — sem isso a página
    inteira rola e o painel deixa de ser painel."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    rola = pg.eval_on_selector(
        "#gma-rank", "el => { const w = el.closest('.tabroll');"
        " return !!w && w.scrollHeight > w.clientHeight + 4; }")
    assert rola, "a tabela do ranking tem de rolar dentro do card"


# ───────────────────────────────────────────────────────── o pagamento
def test_ausencia_de_valor_NAO_vira_zero_em_reais(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabprem-prm")
    pg.wait_for_timeout(400)
    # A CÉLULA DO VALOR, não a linha inteira: o motivo também aparece na coluna
    # "De onde vem", e conferir a linha deixaria passar um R$ 0,00 na coluna do
    # prêmio com o motivo ao lado — que é exatamente o defeito.
    celula = pg.eval_on_selector_all(
        "#gma-prm tr",
        "els => { const tr = els.find(t => t.innerText.includes('MOTORISTA DE NOME COMPRIDO 07'));"
        " return tr ? tr.children[6].innerText.trim() : null; }")
    assert celula == "motorista sem filial no cadastro", celula
    assert "R$" not in (celula or ""), "ausência virou valor em reais"
    linhas = pg.inner_text("#gma-prm")
    assert "ajuste do ciclo" in linhas and "acordo de transição" in linhas
    banda = pg.inner_text("#kpis-gmaprm")
    assert "73.800,00" in banda and "82.000,00" in banda


def test_os_valores_base_tem_ABA_PROPRIA_e_a_escada_aparece(pagina):
    """Com a base inteira, pagamento e tabela de valores no mesmo painel
    mediam 1.523px. O que não cabe vai para sub-aba, nunca para o fim da
    rolagem — e as duas continuam sendo a mesma unidade de acesso."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabprem-val")
    pg.wait_for_timeout(400)
    assert pg.is_visible("#gma-val") and not pg.is_visible("#gma-prm")
    pg.select_option("#fGmaGrupoVal", "MANOBRA")
    pg.wait_for_timeout(200)
    # a observação da filial é campo editável: o texto está no `value`
    assert pg.input_value("#gmaobs-CRZ") == "pago em outra verba"
    assert pg.is_checked("#gmaesc-SBC") and not pg.is_checked("#gmaesc-CRZ")
    assert "PRIMEIRO degrau" in pg.inner_text("#gma-escada")


def test_ciclo_FECHADO_diz_que_mostra_a_fotografia_e_esconde_o_ajuste(pagina):
    pg, base_url = pagina
    fechado = {**PAGAMENTO, "fechado": True, "fonte": "fotografia do fechamento",
               "fechamento": {"ciclo": "2026-09", "situacao": "fechado",
                              "total": 73800.0, "motoristas": N, "sem_nota": 0,
                              "nota": "", "fechado_em": "2026-09-16T09:12:00",
                              "fechado_por": "gestor@sulista.com.br",
                              "fechado": True}}
    _abrir(pg, base_url, pagamento=fechado)
    pg.click("#tabprem-prm")
    pg.wait_for_timeout(400)
    assert "fotografia" in pg.inner_text("#gma-prm-estado").lower()
    assert not pg.is_visible("#btnGmaFechar")
    assert pg.is_visible("#btnGmaReabrir")
    assert pg.eval_on_selector_all(
        "#gma-prm button", "els => els.length") == 0, \
        "ciclo fechado não oferece ajuste: mês pago não se recalcula"


# ─────────────────────────────────────────────────── o gráfico e as abas
def test_o_grafico_das_categorias_e_redesenhado_AO_ABRIR_a_aba(pagina):
    """O ECharts mede o contêiner UMA vez. Medida feita sob `hidden` vale zero
    para sempre — e o sintoma é mudo: eixos certos, rótulos suprimidos."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.get_attribute("#aba-cat", "data-ao-abrir") == "gmaCatRender"
    pg.click("#tabprem-cat")
    pg.wait_for_timeout(500)
    # o ECharts da casa desenha em SVG (`renderer:'svg'`), não em canvas
    largura = pg.eval_on_selector(
        "#chartGmaCat", "el => { const c = el.querySelector('svg');"
        " return c ? c.getBoundingClientRect().width : 0; }")
    assert largura > 400, f"o gráfico mediu {largura}px — mediu escondido"


def test_o_contador_da_aba_de_ocorrencias_conta_o_que_FALTA_DECIDIR(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.inner_text("#ct-gma-oco").strip() == "3"


def test_o_CPF_nao_chega_ao_navegador(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabprem-base")
    pg.wait_for_timeout(400)
    corpo = pg.inner_text("#view-prem")
    import re
    assert not re.search(r"\b\d{11}\b", corpo), "algo com cara de CPF na tela"
