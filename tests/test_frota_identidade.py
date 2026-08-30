"""Quem é este veículo: número de frota E placa, sempre juntos.

O QUE ESTES TESTES GUARDAM
==========================
O CÓRTEX estava dividido — custos, pneus e manutenção chaveavam por
`numerofrota`; telemetria, premiação e tudo que vem da Gobrax, por `placa`. E
várias consultas faziam `coalesce(numerofrota, placa)`, que é o pior dos dois:
a chave **muda de natureza** conforme o cadastro esteja preenchido, e ninguém
percebe olhando a tela.

A decisão: **a chave é a PLACA, a identidade mostrada são as duas.**

E A MEDIÇÃO QUE MUDOU O DESENHO
===============================
O campo `numerofrota` está preenchido em 1.857 de 1.973 veículos — 94%, que
parecia ótima cobertura. Mas em **947 deles o valor É A PRÓPRIA PLACA**,
copiada no campo (926 em terceiro, quase certamente por importação). A
cobertura útil é **46%**, não 94%.

Se `rotulo()` não tratasse esse caso, metade da frota apareceria como
`AAW7D10 · AAW7D10` — e, pior, PARECERIA ter número de frota quando não tem.
"""
from __future__ import annotations

import pytest

from api import frota_identidade as fi


def _v(placa, frota=None, tipo="Proprio"):
    return {"placa": placa, "frota": frota, "tipo": tipo, "atividade": "ATI"}


# ── o rótulo ────────────────────────────────────────────────────────────────


def test_com_numero_mostra_os_dois():
    """`582 · JOK3003`: a operação fala "o 582" e o sistema fala "JOK3003"."""
    assert fi.rotulo("582", "JOK3003") == "582 · JOK3003"


def test_sem_numero_mostra_SO_a_placa():
    """E NÃO um travessão nem "sem frota": são 116 veículos sem número, e
    poluir toda linha para dizer o que já se vê seria ruído."""
    assert fi.rotulo(None, "JOK3003") == "JOK3003"
    assert fi.rotulo("", "JOK3003") == "JOK3003"


def test_numero_IGUAL_a_placa_mostra_so_a_placa():
    """O caso DOMINANTE: 947 dos 1.857 preenchidos têm a placa copiada no
    campo. `AAW7D10 · AAW7D10` seria absurdo, e faria metade da frota parecer
    ter número quando não tem."""
    assert fi.rotulo("AAW7D10", "AAW7D10") == "AAW7D10"
    # e a comparação ignora caixa: cadastro digitado à mão varia
    assert fi.rotulo("aaw7d10", "AAW7D10") == "AAW7D10"


def test_sem_placa_nao_quebra():
    assert fi.rotulo("582", None) == "582"
    assert fi.rotulo(None, None) == "—"


# ── o De-Para ───────────────────────────────────────────────────────────────


def test_o_mapa_e_por_PLACA_porque_a_placa_e_a_chave():
    m = fi.mapa([_v("JOK3003", "582"), _v("AAA1A11", None, "Terceiro")])
    assert set(m) == {"JOK3003", "AAA1A11"}
    assert m["JOK3003"]["rotulo"] == "582 · JOK3003"
    assert m["AAA1A11"]["rotulo"] == "AAA1A11"


def test_o_tipo_volta_ACENTUADO():
    """O SQL devolve "Proprio" sem acento porque o AVA é LATIN1 e o psycopg
    codifica a QUERY nessa codificação — um travessão ali estoura com
    UnicodeEncodeError. O acento mora no Python."""
    m = fi.mapa([_v("JOK3003", "582", "Proprio")])
    assert m["JOK3003"]["tipo"] == "Próprio"


# ── as pendências ───────────────────────────────────────────────────────────


def test_cobertura_conta_o_numero_UTIL_e_nao_o_campo_preenchido():
    """A diferença entre os dois é 947 veículos: chamar campo preenchido de
    cobertura mentiria por um fator de dois."""
    p = fi.pendencias([
        _v("JOK3003", "582"),                    # número de verdade
        _v("AAW7D10", "AAW7D10", "Terceiro"),    # placa copiada
        _v("BBB2B22", None, "Terceiro"),         # sem número
    ])
    assert p["total"] == 3
    assert p["com_frota"] == 1            # só o primeiro
    assert p["campo_preenchido"] == 2     # dois têm o campo cheio
    assert p["cobertura"] == pytest.approx(33.3, abs=0.1)


def test_placa_copiada_e_categoria_PROPRIA_e_nao_soma_com_sem_numero():
    """Consertos diferentes: "ninguém preencheu" x "preencheram errado"."""
    p = fi.pendencias([_v("A1", "A1", "Terceiro"), _v("B2", None, "Terceiro")])
    assert p["frota_igual_placa_total"] == 1
    assert p["sem_frota_total"] == 1
    assert [x["placa"] for x in p["frota_igual_placa"]] == ["A1"]
    assert [x["placa"] for x in p["sem_frota"]] == ["B2"]


def test_a_quebra_POR_TIPO_desarma_o_numero_grande():
    """"116 sem número" parece descuido nosso; "113 são terceiro" diz que é
    cadastro que a Sulista não controla. É a mesma regra dos 664 de 836."""
    p = fi.pendencias([_v("A1", None, "Terceiro"), _v("B2", None, "Terceiro"),
                       _v("C3", None, "Proprio")])
    assert p["sem_frota_por_tipo"] == {"Terceiro": 2, "Próprio": 1}


def test_numero_repetido_traz_as_placas_como_EVIDENCIA():
    p = fi.pendencias([_v("JOK3003", "582"), _v("JOK3H03", "582")])
    assert len(p["repetidos"]) == 1
    assert p["repetidos"][0]["placas"] == ["JOK3003", "JOK3H03"]


def test_a_placa_copiada_NAO_entra_como_numero_repetido():
    """Duas placas com o campo preenchido com elas mesmas não dividem número
    nenhum — contá-las como repetidas inventaria uma pendência."""
    p = fi.pendencias([_v("A1", "A1"), _v("B2", "B2")])
    assert p["repetidos"] == []


# ── a hipótese sobre o repetido ─────────────────────────────────────────────


def test_reconhece_placa_antiga_x_MERCOSUL():
    """O 5º caractere (índice 4) vira letra: JOK3003 -> JOK3H03. Errar o índice
    faz o detector devolver a hipótese genérica justamente nos casos em que
    ele tinha algo a dizer — 7 dos 10 repetidos da frota são deste tipo."""
    p = fi.pendencias([_v("JOK3003", "582"), _v("JOK3H03", "582")])
    assert "Mercosul" in p["repetidos"][0]["provavel"]


def test_UMA_letra_de_diferenca_fora_do_Mercosul_e_ERRO_DE_DIGITACAO():
    """`BBY2F64` x `BYY2F64` diferem no 2º caractere. Isso é pior que cadastro
    duplicado: significa que UMA DAS PLACAS NÃO EXISTE, e tudo lançado nela
    some."""
    p = fi.pendencias([_v("BBY2F64", "S3154"), _v("BYY2F64", "S3154")])
    prov = p["repetidos"][0]["provavel"]
    assert "digita" in prov and "2º caractere" in prov


def test_placas_sem_padrao_ficam_na_hipotese_GENERICA():
    """Inventar diagnóstico onde não há padrão seria pior que não diagnosticar:
    `SL3017` liga FCN2H22 a SWB1G57, que são veículos diferentes mesmo."""
    p = fi.pendencias([_v("FCN2H22", "SL3017"), _v("SWB1G57", "SL3017")])
    assert p["repetidos"][0]["provavel"] == "dois cadastros dividindo o mesmo número"


# ── o corte das listas ──────────────────────────────────────────────────────


def test_a_lista_e_cortada_MAS_o_total_vai_junto():
    """Top-N sem contador vira total falso. São 947 linhas de placa copiada:
    mandá-las inteiras engordaria a resposta em ~90 KB para desenhar uma
    tabela que rola internamente de qualquer jeito."""
    muitos = [_v(f"P{i:05d}", f"P{i:05d}", "Terceiro")
              for i in range(fi.LIMITE_LISTA + 50)]
    p = fi.pendencias(muitos)
    assert len(p["frota_igual_placa"]) == fi.LIMITE_LISTA
    assert p["frota_igual_placa_total"] == fi.LIMITE_LISTA + 50
