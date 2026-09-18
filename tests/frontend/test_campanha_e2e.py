# -*- coding: utf-8 -*-
"""A guia Campanha no navegador, com a base inteira.

O que este arquivo guarda:

- a aba diz a RÉGUA DO REGULAMENTO (50/30/20, Elite 90) — ela é outra e a
  confusão com a operacional é o defeito mais caro possível aqui;
- quem está sem telemetria aparece com o MOTIVO e SEM posição: ele não é
  "último", ele não disputa;
- o número que a campanha precisa dizer todo mês (quantos estão no sorteio e
  quantos ficaram de fora por falta de leitura) está na banda, não no rodapé;
- trocar de grupo troca de ranking — frota e agregado não se misturam;
- o botão de sortear só existe no ciclo de encerramento E com o mês fechado.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

CAMPANHA = {"id": 1, "nome": "Programa de Desempenho — 4º trimestre/2026",
            "de_ciclo": "2026-10", "ate_ciclo": "2026-12",
            "sorteio_em": "2026-12-20", "premio": "Moto elétrica",
            "onde": "Matriz — Piraquara/PR",
            "peso_gobrax": 50.0, "peso_conduta": 30.0, "peso_gr": 20.0,
            "cat_elite": 90.0, "cat_ouro": 85.0, "cat_prata": 75.0,
            "exige_gobrax": True, "situacao": "aberta",
            "criado_em": "2026-09-18T20:00:00", "criado_por": "gestor"}


def _linha(i, grupo, elegivel=True, sem_gobrax=False):
    nota = None if sem_gobrax and i % 7 == 0 else 95.0 - (i % 30)
    return {
        "chave": f"k{grupo[:1]}{i:03d}", "nome": f"MOTORISTA {grupo} {i:03d}",
        "grupo": grupo,
        "gobrax": None if sem_gobrax else 90.0 - (i % 20),
        "conduta": 100.0, "gr": 88.0 - (i % 15), "nota": nota,
        "pilares": ["conduta", "gr"] if sem_gobrax else ["gobrax", "conduta", "gr"],
        "ausentes": ["gobrax"] if sem_gobrax else [],
        "categoria": "PENDENTE" if sem_gobrax else
                     ("ELITE" if nota and nota >= 90 else "OURO"),
        "viagens": 12 if grupo == "AGREGADO" else None,
        "venc_cnh": "2030-01-01", "ativo": True, "desvios": i % 3,
        "elegivel": elegivel and not sem_gobrax,
        "faltas": [] if (elegivel and not sem_gobrax) else ["sem_gobrax"],
        "faltas_de_medicao": [] if not sem_gobrax else ["sem_gobrax"],
        "motivo": "" if (elegivel and not sem_gobrax) else
                  "sem leitura da telemetria no ciclo — a nota de condução vale "
                  "metade do regulamento, e sem ela não dá para concorrer",
        "posicao": None,
    }


def _grupo(grupo, n, sem_gobrax):
    linhas = [_linha(i, grupo, sem_gobrax=(i < sem_gobrax)) for i in range(n)]
    linhas.sort(key=lambda x: (not x["elegivel"], x["nota"] is None,
                               -(x["nota"] or 0), x["nome"]))
    pos = 0
    for x in linhas:
        if x["elegivel"]:
            pos += 1
        x["posicao"] = pos if x["elegivel"] else None
    cats = {}
    for x in linhas:
        cats[x["categoria"]] = cats.get(x["categoria"], 0) + 1
    return {"linhas": linhas, "motivo": "", "kpis": {
        "participantes": n, "com_nota": sum(1 for x in linhas if x["nota"]),
        "sem_gobrax": sem_gobrax, "elegiveis": sum(1 for x in linhas if x["elegivel"]),
        "por_categoria": cats, "nota_mediana": 88.0}}


# O TETO DA BASE, não o mês bonito: 81 próprios e 127 agregados, que é o que a
# operação produziu em agosto/2026.
CICLO = {
    "campanha": CAMPANHA, "ciclo": "2026-11", "rotulo": "16/10 a 15/11 de 2026",
    "encerramento": False, "foto": False,
    "ciclos": ["2026-10", "2026-11", "2026-12"],
    "grupos": {"FROTA": _grupo("FROTA", 81, 25),
               "AGREGADO": _grupo("AGREGADO", 127, 84)},
    "fontes": {"gobrax": {"motivo": "", "mes": "2026-10", "com_nota": 101},
               "conduta": {"motivo": ""}, "gr": {"motivo": ""}},
    "sorteios": [],
}

ALTURA = """() => {
  const c = document.getElementById('content');
  const b = c.querySelector('#banner');
  const fora = (b && b.offsetParent !== null)
    ? Math.round(b.getBoundingClientRect().height) + 14 : 0;
  return Math.round(c.scrollHeight) - fora;
}"""


def _abrir(pg, base_url, ciclo=None, campanhas=None):
    corpo_ciclo = ciclo if ciclo is not None else CICLO

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/campanha" in u and "/ciclo" in u:
            corpo = corpo_ciclo
        elif "/api/campanha" in u:
            corpo = campanhas if campanhas is not None else {
                "campanhas": [CAMPANHA], "vigente": CAMPANHA,
                "padrao": {"peso_gobrax": 50, "peso_conduta": 30,
                           "peso_gr": 20, "cat_elite": 90}}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base_url + "/static/index.html#prem")
    pg.wait_for_timeout(700)
    pg.click("#tabprem-camp")
    pg.wait_for_timeout(600)
    return erros


def test_a_aba_diz_a_REGUA_DO_REGULAMENTO_e_nao_a_operacional(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    txt = pg.inner_text("#camp-estado")
    assert "condução 50%" in txt and "comportamento 30%" in txt and "risco 20%" in txt
    assert "Moto elétrica" in txt and "20/12/2026" in txt


def test_a_banda_diz_quantos_DISPUTAM_e_quantos_ficaram_de_fora(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    banda = pg.inner_text("#kpis-camp")
    assert "81" in banda                      # participantes da frota
    assert "56" in banda                      # no sorteio
    assert "25" in banda                      # sem telemetria
    assert "sem telemetria" in banda.lower()


def test_quem_esta_sem_telemetria_NAO_tem_posicao_e_diz_o_motivo(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    fora = pg.eval_on_selector_all(
        "#camp-lista tr",
        "els => els.filter(t => t.innerText.includes('telemetria'))"
        "        .map(t => t.children[0].innerText.trim())")
    assert fora, "ninguém apareceu como fora do sorteio"
    assert all(x == "" for x in fora), "quem não disputa não recebe posição"
    primeiro = pg.inner_text("#camp-lista tr:first-child")
    assert "1º" in primeiro and "concorre" in primeiro


def test_trocar_de_grupo_troca_de_RANKING(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert "MOTORISTA FROTA" in pg.inner_text("#camp-lista")
    pg.select_option("#fCampGrupo", "AGREGADO")
    pg.wait_for_timeout(300)
    lista = pg.inner_text("#camp-lista")
    assert "MOTORISTA AGREGADO" in lista and "MOTORISTA FROTA" not in lista
    banda = pg.inner_text("#kpis-camp")
    assert "127" in banda and "84" in banda


def test_o_botao_de_SORTEAR_so_existe_no_encerramento_COM_o_mes_fechado(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert not pg.is_visible("#btnCampSortear"), "ciclo do meio não sorteia"

    fechado = {**CICLO, "ciclo": "2026-12", "encerramento": True, "foto": True}
    _abrir(pg, base_url, ciclo=fechado)
    assert pg.is_visible("#btnCampSortear")
    assert "ciclo de encerramento" in pg.inner_text("#camp-estado")


def test_o_sorteio_ja_feito_aparece_com_a_SEMENTE(pagina):
    """Com a semente e a lista, qualquer pessoa refaz o sorteio e confere."""
    pg, base_url = pagina
    com = {**CICLO, "sorteios": [{"grupo": "FROTA", "ciclo": "2026-12",
                                  "elegiveis": 56, "semente": "20261220183000",
                                  "ganhador_nome": "FULANO DE TAL",
                                  "suplente_nome": "BELTRANO",
                                  "ata": "evento na matriz",
                                  "realizado_em": "2026-12-20T18:30:00",
                                  "realizado_por": "gestor@sulista.com.br"}]}
    _abrir(pg, base_url, ciclo=com)
    rodape = pg.inner_text("#camp-rodape")
    assert "FULANO DE TAL" in rodape and "BELTRANO" in rodape
    assert "20261220183000" in rodape and "56" in rodape


def test_sem_campanha_a_aba_EXPLICA_e_oferece_o_botao(pagina):
    """Aba que abre vazia ensina a pessoa a não voltar nela."""
    pg, base_url = pagina
    _abrir(pg, base_url, campanhas={"campanhas": [], "vigente": None,
                                    "padrao": {"peso_gobrax": 50,
                                               "peso_conduta": 30,
                                               "peso_gr": 20, "cat_elite": 90}})
    txt = pg.inner_text("#camp-estado")
    assert "Nenhuma campanha cadastrada" in txt and "trimestral" in txt
    assert pg.is_visible("#aba-camp button:has-text('Criar campanha')")


def test_a_aba_cabe_em_UMA_tela_com_a_base_inteira(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    for grupo in ("FROTA", "AGREGADO"):
        pg.select_option("#fCampGrupo", grupo)
        pg.wait_for_timeout(300)
        alt = pg.evaluate(ALTURA)
        assert alt <= 900, f"a aba mede {alt}px com o grupo {grupo} inteiro"
