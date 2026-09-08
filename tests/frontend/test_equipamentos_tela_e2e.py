# -*- coding: utf-8 -*-
"""A tela de Equipamentos contra o index.html real — o CAMINHO DO DADO.

POR QUE ESTE ARQUIVO EXISTE
===========================
A tela foi para produção quebrada, e nenhuma régua da casa pegou. Ela media
altura (776px, cabe), largura (zero rolagem), tema (0 achados) e espaçamento
(0 fora da escala) — e passava em todas, porque **medir layout não exercita o
caminho do dado**.

O defeito: `respostaJSON` devolve `{ok, dados}`, e as seis chamadas da tela
tratavam o retorno como se fosse o payload. `EQP_CAT.vinculos` era `undefined`,
a tela abria com "undefined is not an object" no lugar da tabela, e nada mais
carregava. Um erro de JavaScript, num caminho que teste nenhum percorria.

O que este arquivo garante é modesto e é o que faltava: **a tela abre, chama as
rotas, e desenha o que veio** — sem um único erro de página.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CATALOGO = {
    "grupos": [
        {"grupo": "Identidade",
         "campos": [{"campo": "chassi", "rotulo": "Chassi", "tipo": "texto",
                     "so_erp": False, "ajuda": None,
                     "fontes": ["corrigido à mão", "Smartec (Detran)"]}]},
    ],
    "vinculos": [{"chave": "proprio", "rotulo": "Próprio"},
                 {"chave": "agregado", "rotulo": "Agregado"},
                 {"chave": "terceiro", "rotulo": "Terceiro"}],
    "categorias": [{"chave": "tracao", "rotulo": "Tração"},
                   {"chave": "implemento", "rotulo": "Implemento"}],
}

PANORAMA = {
    "total": 1448,
    "por_vinculo": [
        {"vinculo": "proprio", "rotulo": "Próprio", "total": 308,
         "tracao": 80, "implemento": 228},
        {"vinculo": "agregado", "rotulo": "Agregado", "total": 122,
         "tracao": 122, "implemento": 0},
        {"vinculo": "terceiro", "rotulo": "Terceiro", "total": 1016,
         "tracao": 594, "implemento": 422},
    ],
    "cobertura_detran": [
        {"vinculo": "proprio", "rotulo": "Próprio", "total": 308,
         "com_detran": 301, "falta": 7},
    ],
    "dependencia_do_erp": {
        "campos_do_erp": 24000, "campos_no_total": 27000, "percentual": 88.4,
        "campos_sem_alternativa": [
            {"campo": "vinculo", "rotulo": "Vínculo",
             "ajuda": "contrato, não documento"}],
    },
    "cobertura_smartec": {"total": 1448, "com_smartec": 301, "falta": 1147,
                          "percentual": 20.8},
}

LISTA = {
    "equipamentos": [
        {"placa": "ABQ3174", "numero_frota": "R3000", "vinculo": "proprio",
         "categoria": "tracao", "marca": "MBENZ", "modelo": "1218",
         "ano_fabricacao": 1991, "eixos": 3,
         "chassi": "9BM384009MB905474", "uf": "PR", "situacao": None},
    ],
    "mostrando": 1, "total": 1448, "limite": 500,
}

DIVERGENCIAS = {
    "divergencias": [
        {"placa": "ABQ3174", "campo": "chassi", "rotulo": "Chassi",
         "vence": "smartec",
         "valores": [{"fonte": "smartec", "valor": "AAA"},
                     {"fonte": "erp", "valor": "BBB"}]},
    ],
    "placas_conferidas": 301, "placas_no_cadastro": 1448,
    "conferencia_comecou": True,
}


def _abrir(pagina, lista=None, divergencias=None):
    pg, base_url = pagina
    chamadas = []

    def rota(route):
        u = route.request.url
        chamadas.append(u.split("/api/")[-1].split("?")[0])
        if "/api/auth/me" in u:
            corpo = USUARIO
        elif "/api/equipamentos/catalogo" in u:
            corpo = CATALOGO
        elif "/api/equipamentos/panorama" in u:
            corpo = PANORAMA
        elif "/api/equipamentos/divergencias" in u:
            corpo = divergencias if divergencias is not None else DIVERGENCIAS
        elif "/api/equipamentos" in u:
            corpo = lista if lista is not None else LISTA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#eqp")
    pg.wait_for_selector("#eqpTab tbody tr", timeout=20000)
    return pg, erros, chamadas


def test_a_tela_abre_SEM_erro_de_pagina(pagina):
    """O guard que teria pego o defeito que foi para produção.

    Um erro de JavaScript não derruba nada visível na régua de altura: a
    seção existe, mede 776px e "cabe". Só percorrer o caminho do dado
    acusa.
    """
    _, erros, _ = _abrir(pagina)
    assert not erros, f"a pagina levantou erro de JS: {erros}"


def test_a_tabela_desenha_o_que_veio_da_rota(pagina):
    """`respostaJSON` devolve `{ok, dados}` — se alguém voltar a ler o
    envelope como se fosse o payload, a linha some e este teste acusa."""
    pg, _, _ = _abrir(pagina)
    linha = pg.locator("#eqpTab tbody tr").first.inner_text()
    assert "ABQ3174" in linha
    assert "MBENZ" in linha
    assert "Próprio" in linha, "o rotulo do vinculo nao foi traduzido"
    assert "Tração" in linha, "o rotulo da categoria nao foi traduzido"


def test_situacao_nao_consultada_aparece_DITA_e_nao_em_branco(pagina):
    """Célula vazia se lê como "sem problema"; "não consultado" é a verdade.

    A situação no Detran não tem fonte hoje. Deixá-la em branco faria a tela
    afirmar, em silêncio, algo que ninguém mediu.
    """
    pg, _, _ = _abrir(pagina)
    assert "não consultado" in pg.locator("#eqpTab tbody tr").first.inner_text()


def test_o_KPI_de_conferencia_NAO_diz_zero_por_cento_antes_de_comecar(pagina):
    """Zero que é ausência de medição não é desempenho.

    Com a carga não iniciada, "0%" se lê como um resultado ruim; o correto é
    dizer que não começou.
    """
    sem_carga = {**PANORAMA, "cobertura_detran": [
        {"vinculo": "proprio", "rotulo": "Próprio", "total": 308,
         "com_detran": 0, "falta": 308}]}
    pg, base_url = pagina

    def rota(route):
        u = route.request.url
        corpo = (USUARIO if "/api/auth/me" in u
                 else CATALOGO if "catalogo" in u
                 else sem_carga if "panorama" in u
                 else DIVERGENCIAS if "divergencias" in u
                 else LISTA)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(f"{base_url}/static/index.html#eqp")
    pg.wait_for_selector("#eqpKpis .kpi", timeout=20000)
    texto = pg.locator("#eqpKpis").inner_text()
    assert "não iniciada" in texto
    assert "0%" not in texto


def test_divergencia_vazia_DIZ_se_a_conferencia_comecou(pagina):
    """Lista vazia por falta de medição e por ausência de problema são a
    mesma imagem e o oposto em significado."""
    nada = {"divergencias": [], "placas_conferidas": 0,
            "placas_no_cadastro": 1448, "conferencia_comecou": False}
    pg, _, _ = _abrir(pagina, divergencias=nada)
    hint = pg.locator("#eqpDivHint").inner_text()
    assert "não começou" in hint or "nao comecou" in hint
    assert "NÃO significa" in hint or "NAO significa" in hint


def test_a_tela_chama_as_quatro_rotas(pagina):
    """Rota que a tela não chama é rota que ninguém percebe que quebrou."""
    _, _, chamadas = _abrir(pagina)
    for esperada in ("equipamentos/catalogo", "equipamentos/panorama",
                     "equipamentos/divergencias"):
        assert any(c.startswith(esperada) for c in chamadas), \
            f"a tela nao chamou {esperada}: {chamadas}"
