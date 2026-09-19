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

# O PANORAMA NO TETO: os seis ciclos da janela da reputação, os três
# pilares e a lista de pendências inteira. A cobertura é a REAL medida em
# 19/09/2026 (50 de 82 na condução, 1 de 82 no GR) — dublê de cobertura tem a
# ordem de grandeza do real, senão a régua de altura mede uma tela que não
# existe e o semáforo do gráfico nunca chega ao vermelho.
PANORAMA = {
    "ciclo": "2026-10", "rotulo": "16/09 a 15/10 de 2026",
    "fechado": False, "em_curso": True,
    "recorte": "frota própria (cadastro da folha)",
    # 104 AGREGADOS no mesmo ciclo, contra 82 próprios — medido em 19/09/2026.
    # O dublê usa o número real porque a tela existe para dizer que o maior dos
    # dois está FORA desta régua.
    "agregados": {"com_viagem": 104, "motivo": "",
                  "onde": "fora da premiação mensal, que sai da folha — "
                          "agregado concorre na campanha trimestral"},
    "medicao": {
        "motoristas": N, "com_nota": N, "sem_nota": 0,
        "completos": 1, "com_pilar_faltando": N - 1,
        "pilares": [
            {"chave": "gobrax", "rotulo": "Condução", "peso": 40.0,
             "com_nota": 50, "de": N, "media": 86.1, "motivo": ""},
            {"chave": "conduta", "rotulo": "Comportamento", "peso": 40.0,
             "com_nota": N, "de": N, "media": 100.0, "motivo": ""},
            {"chave": "gr", "rotulo": "Gerenciamento de risco", "peso": 20.0,
             "com_nota": 1, "de": N, "media": 99.0, "motivo": ""},
        ],
    },
    "nota": {"mediana": 98.5, "completos": 1, "de": N},
    # OS DOIS GRUPOS, com a cobertura REAL de 19/09/2026. O agregado é o MAIOR
    # (104 × 82) e o de menor cobertura de condução (1 × 50) — se o dublê
    # invertesse isso, o guard aprovaria uma tela que esconde o buraco.
    "grupos": {
        "FROTA": {
            "rotulo": "Frota própria", "motoristas": N, "motivo": "",
            "nota": 98.5, "nota_motivo": "",
            "pilares": [
                {"chave": "gobrax", "rotulo": "Condução", "peso": 40.0,
                 "com_nota": 50, "de": N, "media": 86.1, "motivo": ""},
                {"chave": "conduta", "rotulo": "Comportamento", "peso": 40.0,
                 "com_nota": N, "de": N, "media": 100.0, "motivo": ""},
                {"chave": "gr", "rotulo": "Gerenciamento de risco", "peso": 20.0,
                 "com_nota": 1, "de": N, "media": 99.0, "motivo": ""},
            ]},
        "AGREGADO": {
            "rotulo": "Agregados", "motoristas": 104, "motivo": "",
            "nota": None,
            "nota_motivo": "a nota do agregado é a do regulamento da campanha "
                           "(50/30/20), não a da folha",
            "pilares": [
                {"chave": "gobrax", "rotulo": "Condução", "peso": None,
                 "com_nota": 1, "de": 104, "media": 32.0, "motivo": ""},
                {"chave": "conduta", "rotulo": "Comportamento", "peso": None,
                 "com_nota": 104, "de": 104, "media": 99.9, "motivo": ""},
                {"chave": "gr", "rotulo": "Gerenciamento de risco", "peso": None,
                 "com_nota": 12, "de": 104, "media": 91.8, "motivo": ""},
            ]},
    },
    "categorias": {"ELITE": 12, "DIAMANTE": 36, "OURO": 28, "PRATA": 4,
                   "BRONZE": 2},
    "status": {"EXCELENTE": 66, "BOM": 13, "ATENCAO": 2, "ALERTA": 1},
    "serie": {"fechados": 2, "motivo": "", "linhas": [
        {"ciclo": "2026-05", "rotulo": "16/04 a 15/05 de 2026",
         "em_curso": False, "fechado": True, "mediana": 91.2, "motoristas": 80},
        {"ciclo": "2026-06", "rotulo": "16/05 a 15/06 de 2026",
         "em_curso": False, "fechado": True, "mediana": 93.8, "motoristas": 81},
        {"ciclo": "2026-07", "rotulo": "16/06 a 15/07 de 2026",
         "em_curso": False, "fechado": False, "mediana": None, "motoristas": None},
        {"ciclo": "2026-08", "rotulo": "16/07 a 15/08 de 2026",
         "em_curso": False, "fechado": False, "mediana": None, "motoristas": None},
        {"ciclo": "2026-09", "rotulo": "16/08 a 15/09 de 2026",
         "em_curso": False, "fechado": False, "mediana": None, "motoristas": None},
        {"ciclo": "2026-10", "rotulo": "16/09 a 15/10 de 2026",
         "em_curso": True, "fechado": False, "mediana": 98.5, "motoristas": N},
    ]},
    "pagar": {"pode": False, "filiais_com_valor": 0, "grupos": {},
              "versao": 1, "vigente_de": "2026-01",
              "motivo": "nenhuma filial com valor base cadastrado — a régua "
                        "calcula tudo e não paga nada"},
    "campanha": {"existe": False,
                 "motivo": "nenhuma campanha cadastrada — a aba Campanha cria"},
    "pendencias": [
        {"chave": "depara", "quantos": 3,
         "rotulo": "códigos de ocorrência sem de-para",
         "acao": "aba Ocorrências: dizer o que cada código significa na régua"},
        {"chave": "sem_codigo", "quantos": 5,
         "rotulo": "ocorrências sem código no ERP",
         "acao": "não entram em nenhum pilar — corrigir no lançamento do ERP"},
        {"chave": "sem_filial", "quantos": 2, "rotulo": "motoristas sem filial",
         "acao": "aba Motoristas: sem filial não há valor base, logo não há prêmio"},
        {"chave": "tipo_sugerido", "quantos": N,
         "rotulo": "com o tipo apenas SUGERIDO",
         "acao": "aba Motoristas: confirmar rodoviário ou manobrista"},
        {"chave": "gobrax_fora", "quantos": 45,
         "rotulo": "nomes da Gobrax fora do cadastro",
         "acao": "aba Motoristas: sincronizar a folha ou ajustar o de-para"},
        {"chave": "valores", "quantos": None,
         "rotulo": "o ciclo não tem como pagar",
         "acao": "nenhuma filial com valor base cadastrado"},
        {"chave": "campanha", "quantos": None, "rotulo": "campanha trimestral",
         "acao": "nenhuma campanha cadastrada — a aba Campanha cria"},
    ],
    "fontes": {"gobrax": {"motivo": "", "coletado_em": "2026-09-19T06:21:16",
                          "parcial": True, "com_nota": 50},
               "conduta": {"motivo": ""},
               "gr": {"motivo": "", "com_viagem": 152}},
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


def _abrir(pg, base_url, pagamento=None, me=None, panorama=None):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN if me is None else me
        elif "/api/premiacao/gma/panorama" in u:
            corpo = panorama if panorama is not None else PANORAMA
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
def test_a_tela_abre_na_regua_NOVA_e_o_modelo_ANTIGO_saiu(pagina):
    """Em 18/09/2026 as duas abas do modelo em pagamento saíram da tela, por
    decisão de quem opera: a régua é uma só. As ROTAS do modelo antigo
    continuam de pé — é por elas que a nota da Gobrax é coletada, e ela é um
    dos três pilares da régua nova."""
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    assert pg.is_visible("#aba-pan"), "a tela abre no panorama"
    assert not pg.is_visible("#aba-rank"), "o ranking passou a ser a segunda aba"
    for foi_embora in ("#aba-prem", "#aba-cfg", "#tabprem-prem", "#tabprem-cfg",
                       "#fPremMes", "#prem-conteudo", "#chartPrem"):
        assert pg.query_selector(foi_embora) is None, foi_embora


def test_a_coleta_da_GOBRAX_tem_botao_na_tela_nova(pagina):
    """O gatilho da coleta era abrir a tela antiga. Sem ele, o pilar de
    condução congelaria em silêncio — quem responde por isso agora é a tarefa
    agendada, e este botão é o "agora" de quem não pode esperar a madrugada."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.is_visible("#btnGmaGobrax")


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


# ─────────────────────────────────────────────────── o PANORAMA
def test_o_panorama_poe_a_COBERTURA_antes_da_nota(pagina):
    """A tese da aba, e a razão de ela existir nesta ordem.

    Medido em 19/09/2026 no ciclo real: mediana 98,5 com 81 das 82 notas
    saindo com um pilar faltando. A nota está alta PORQUE falta medição — a
    renormalização redistribui o peso do pilar ausente entre os que sobraram e
    empurra a nota para cima. Uma banda que abrisse com "98,5" seria verdadeira
    e leria ao contrário do que o dado diz."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    rotulos = [e.inner_text().strip().replace(" ⓘ", "")
               for e in pg.query_selector_all("#kpis-gma-pan .label")]
    assert "cobertura" in rotulos[0].lower(), rotulos
    i_cob = next(i for i, r in enumerate(rotulos) if "cobertura" in r.lower())
    i_not = next(i for i, r in enumerate(rotulos) if "nota mediana" in r.lower())
    assert i_cob < i_not, rotulos
    # e a cobertura aparece COM o número, não como adjetivo
    banda = pg.inner_text("#kpis-gma-pan")
    assert "1 de %d" % N in banda, banda
    assert "%d com nota renormalizada" % (N - 1) in banda, banda


def test_a_banda_separa_FROTA_de_AGREGADO(pagina):
    """Frota e agregado não se misturam em lugar nenhum do programa — na
    campanha eles nem competem entre si. Medido em 19/09/2026: 82 próprios e
    104 agregados no mesmo ciclo, e a régua mensal só enxerga os 82. Uma tela
    que mostrasse "82" sem dizer o recorte esconderia o MAIOR dos dois
    grupos."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    banda = pg.inner_text("#kpis-gma-pan")
    assert "Frota própria" in banda, banda
    assert "Agregados" in banda, banda
    assert "104" in banda, "o tamanho do grupo agregado não está na tela"
    # e NUNCA a soma dos dois
    assert "186" not in banda, "somou frota com agregado"


def test_a_conducao_do_AGREGADO_e_o_buraco_e_aparece_como_tal(pagina):
    """1 de 104 com telemetria, contra 50 de 82 na frota. A condução pesa
    metade do regulamento da campanha, e sem ela o agregado nem concorre —
    então o cartão é vermelho, não um número discreto no meio do texto."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    cartao = next(c for c in pg.query_selector_all("#kpis-gma-pan .kpi")
                  if "agregados" in c.inner_text().lower()
                  and "Condução" in c.inner_text())
    assert "1 de 104" in cartao.inner_text(), cartao.inner_text()
    assert "bad" in (cartao.get_attribute("class") or ""), (
        "cobertura de 1 em 104 não pode sair sem semáforo")


def test_a_nota_do_agregado_NAO_sai_pela_regua_da_folha(pagina):
    """A régua mensal pesa 40/40/20 e sai da folha; a do agregado é a do
    regulamento da campanha, 50/30/20. Publicar uma nota composta do agregado
    pela régua da folha seria inventar uma régua que ninguém aprovou — e ela
    apareceria ao lado da nota da frota como se fossem comparáveis."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    dados = pg.evaluate("() => DATAGMAPAN.grupos")
    assert dados["AGREGADO"]["nota"] is None
    assert "campanha" in (dados["AGREGADO"]["nota_motivo"] or "")
    assert dados["FROTA"]["nota"] == 98.5
    # o eixo do gráfico só carrega o peso de QUEM TEM peso nesta régua
    assert dados["AGREGADO"]["pilares"][0]["peso"] is None


def test_o_panorama_NAO_publica_dinheiro(pagina):
    """A folha mora na aba Prêmio, que é BLOQUEÁVEL por usuário — ela existe
    para se dar a tela a quem acompanha conduta sem dar o dinheiro junto. O
    panorama é a primeira aba, que todo mundo com a tela abre: publicar o total
    aqui contornaria o bloqueio sem ninguém perceber."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    txt = pg.inner_text("#aba-pan")
    assert "R$" not in txt, txt[:400]
    # O ESTADO DO PAGAMENTO APARECE, e como PENDÊNCIA: "não dá para pagar, e
    # por quê" é outra pergunta que "quanto se paga", e só a primeira cabe
    # numa aba que todo mundo com a tela abre.
    assert "nenhuma filial com valor base" in txt, txt[:400]
    # e o payload que alimenta a aba também não carrega valor nenhum
    pagar = pg.evaluate("() => DATAGMAPAN.pagar")
    assert "total" not in pagar and "valor" not in pagar, pagar
    assert pagar["pode"] is False


def test_o_grafico_dos_PILARES_desenha_e_diz_a_cobertura(pagina):
    """O gráfico é o que responde "de onde vem a nota". Ele nasce na aba
    aberta de propósito: o ECharts mede o contêiner UMA vez, e medida feita
    sob `hidden` vale zero para sempre."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.wait_for_selector("#chartGmaPilar svg", timeout=20000)
    # O HINT É DE UMA LINHA — ele diz o TAMANHO dos dois grupos. O detalhe por
    # pilar mora no rótulo de cada barra, e repeti-lo aqui levava o `.head` de
    # 53 para 173px, estourando a régua de altura.
    hint = pg.inner_text("#gma-pan-pil-hint")
    assert "frota %d" % N in hint and "agregados 104" in hint, hint

    # A COBERTURA VAI NO RÓTULO DA BARRA, e é isso que impede a média de ser
    # lida sozinha: 32,0 na condução do agregado com UM medido de 104.
    svg = pg.eval_on_selector("#chartGmaPilar svg", "el => el.textContent")
    assert "(50/%d)" % N in svg, svg
    assert "(1/104)" in svg, svg
    # DUAS séries, uma por grupo, com a legenda que as separa
    assert "Frota própria" in svg and "Agregados" in svg, svg


def test_sem_ciclo_fechado_a_serie_DIZ_em_vez_de_desenhar(pagina):
    """Um ponto desenhado como linha sugere uma tendência que ninguém mediu. O
    programa ainda não fechou ciclo nenhum (19/09/2026), e a resposta honesta
    é a frase."""
    pg, base_url = pagina
    vazia = {**PANORAMA, "serie": {
        "fechados": 0,
        "motivo": "nenhum ciclo fechado ainda — a série começa no primeiro "
                  "fechamento",
        "linhas": [{**x, "mediana": None, "fechado": False}
                   for x in PANORAMA["serie"]["linhas"]]}}
    _abrir(pg, base_url, panorama=vazia)
    assert "nenhum ciclo fechado" in pg.inner_text("#gma-pan-serie-hint")
    assert pg.query_selector("#chartGmaSerie svg") is None, (
        "desenhou gráfico de uma série sem ponto nenhum")


def test_o_que_FALTA_vem_com_a_acao_e_conta_na_aba(pagina):
    """Contagem sem ação é um número que ninguém sabe o que fazer com."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    linhas = pg.inner_text("#gma-pan-pend")
    assert "códigos de ocorrência sem de-para" in linhas
    assert "aba Ocorrências" in linhas, "a linha não diz o que fazer"
    assert "nenhuma filial com valor base" in linhas
    assert pg.inner_text("#ct-gma-pan").strip() == str(len(PANORAMA["pendencias"]))


def test_o_panorama_fora_do_ar_NAO_derruba_a_tela(pagina):
    """As outras abas não dependem dele: o ciclo, a régua e o cadastro seguem
    úteis. Aba em branco se lê como "está tudo certo, não há nada aqui"."""
    pg, base_url = pagina
    _abrir(pg, base_url, panorama={"erro": "recusa", "mensagem": "sem panorama"})
    assert "n/d" in pg.inner_text("#kpis-gma-pan")
    pg.click("#tabprem-rank")
    pg.wait_for_timeout(300)
    assert pg.is_visible("#aba-rank")
    assert pg.inner_text("#gma-rank").strip(), "o ranking parou junto"

# ───────────────────────────────────────────── a régua de altura, CHEIA
def test_cada_aba_cabe_em_UMA_tela_com_a_base_inteira(pagina):
    """Com dublê vazio a tela mede o esqueleto; aqui ela mede o teto do
    cadastro. Cada aba vale por si — a régua da casa mede a MAIS ALTA."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    for aba in ("pan", "rank", "prm", "val", "gr", "oco", "base", "cat", "reg"):
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
    # O RANKING E' A SEGUNDA ABA desde o Panorama (19/09/2026). Medir sem
    # abrir devolvia `clientHeight` ZERO — e zero nunca é maior que zero, então
    # o guard reprovava uma rolagem que existe. Elemento escondido não se mede.
    pg.click("#tabprem-rank")
    pg.wait_for_timeout(350)
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


# O CORPO DE `/api/auth/me` SAI DO SERVIDOR, e não de um dicionário escrito
# aqui: é o recorte dele que estava errado. Um dublê à mão com `"poderes"`
# dentro provaria que o JavaScript lê a chave, e aprovaria para sempre o
# servidor que não a manda — que era o defeito.
def _me(poderes):
    from api import auth
    return auth._payload_me({
        "id": 1, "nome": "Teste", "email": "teste@sulista.local",
        "perfil": "Administrador", "perfil_id": 1, "admin": True,
        "telas": list(ADMIN.get("telas") or []), "deve_trocar_senha": False,
        "telefone": "", "cargo": "", "setor": "", "ramal": "", "foto_em": None,
        "cliente_cnpj_raiz": None, "pagina_inicial": None, "abas_tiradas": [],
        "simulacao": None, "poderes": list(poderes)})


def test_o_botao_de_CONFERIR_o_app_aparece_para_quem_tem_o_poder(pagina):
    """Este é o guard que faltava em 18/09/2026 — e a ausência dele deixou a
    entrega inteira sem efeito: o poder existia, a rota existia, o botão
    existia no HTML, e ele não era desenhado para NINGUÉM porque o payload da
    sessão não levava `poderes`. Quem conferia continuou digitando o código
    mestre, que é o que a entrega prometia aposentar."""
    pg, base_url = pagina
    _abrir(pg, base_url, me=_me(["poder.conferir_app"]))
    pg.click("#tabprem-base")
    pg.wait_for_timeout(400)
    botoes = pg.query_selector_all("#aba-base button")
    rotulos = [b.inner_text().strip() for b in botoes]
    assert any("Ver o app" in r for r in rotulos), (
        "o botão de conferir não foi desenhado para quem TEM o poder: %s"
        % rotulos[:8])
    # SÃO DUAS PORTAS: o app do motorista não leva até a campanha, e sem a
    # segunda quem quisesse conferir a campanha voltaria ao código mestre.
    assert any("Ver a campanha" in r for r in rotulos), rotulos[:8]


def test_cada_porta_abre_o_SEU_endereco(pagina):
    """Dois botões que abrissem a mesma página seriam pior que um: quem
    clicasse em "Ver a campanha" veria o app do motorista e concluiria que a
    campanha não aparece para aquela pessoa. O destino se confere pela JANELA
    que abre, nunca pelo texto do `onclick`."""
    pg, base_url = pagina
    _abrir(pg, base_url, me=_me(["poder.conferir_app"]))
    # O `confirm()` do botão: sem isto o Playwright DISPENSA o diálogo, a
    # função devolve cedo e nenhuma janela abre — o teste falharia por um
    # motivo que não é o que ele mede.
    pg.on("dialog", lambda d: d.accept())
    pg.click("#tabprem-base")
    pg.wait_for_timeout(400)
    for rotulo, esperado in (("Ver o app", "/motorista"),
                             ("Ver a campanha", "/campanha")):
        alvo = next(b for b in pg.query_selector_all("#aba-base button")
                    if rotulo in b.inner_text())
        with pg.expect_popup() as nova:
            alvo.click()
        aberta = nova.value
        # A BARRA DO FIM É DO SERVIDOR DE BANCADA, não do endereço: ele serve
        # a pasta `api/`, e `api/motorista` é um PACOTE — o `/motorista` vira
        # `301 → /motorista/`. Em produção o FastAPI responde na rota exata.
        from urllib.parse import urlparse
        caminho = urlparse(aberta.url).path.rstrip("/")
        assert caminho == esperado, (rotulo, aberta.url)
        aberta.close()


def test_sem_o_poder_o_botao_NAO_aparece(pagina):
    """A outra metade: poder que não foi dado não desenha botão. Sem esta, um
    `gmaPodeConferir()` que devolvesse `true` sempre passaria no guard de
    cima — e a tela ofereceria a todos uma porta que o servidor recusa."""
    pg, base_url = pagina
    _abrir(pg, base_url, me=_me([]))
    pg.click("#tabprem-base")
    pg.wait_for_timeout(400)
    rotulos = [b.inner_text().strip() for b in pg.query_selector_all("#aba-base button")]
    assert not any("Ver o app" in r for r in rotulos), rotulos[:8]

def test_o_CPF_nao_chega_ao_navegador(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabprem-base")
    pg.wait_for_timeout(400)
    corpo = pg.inner_text("#view-prem")
    import re
    assert not re.search(r"\b\d{11}\b", corpo), "algo com cara de CPF na tela"
