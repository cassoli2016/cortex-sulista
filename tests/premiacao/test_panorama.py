# -*- coding: utf-8 -*-
"""O panorama do programa — a camada 1 da tela `prem`.

O que este arquivo segura, e por que cada um importa:

- **a cobertura sai junto da nota, sempre.** No ciclo real de 19/09/2026 a
  mediana era 98,5 com 81 das 82 notas calculadas sem um pilar. A nota está
  alta PORQUE falta medição: a renormalização redistribui o peso do pilar
  ausente, e a ausência empurra a nota para cima. É o espelho da regra da casa
  sobre o zero por ausência;
- **frota e agregado ficam separados, e nunca somados.** São 82 próprios e 104
  agregados no mesmo ciclo — o grupo de fora da régua mensal é o MAIOR dos
  dois;
- **a nota composta do agregado não sai por esta régua.** A mensal pesa
  40/40/20 e sai da folha; a do agregado é a do regulamento da campanha,
  50/30/20. Publicar uma pela outra inventaria uma régua que ninguém aprovou;
- **nenhum valor em reais.** A folha mora na aba bloqueável; o panorama é a
  primeira aba, que todo mundo com a tela abre;
- **pilar sem medição é n/d com motivo**, nunca zero;
- **a série de ciclos é GERADA**, e sem ciclo fechado ela DIZ isso em vez de
  desenhar um ponto só.
"""
from __future__ import annotations

import pytest

from api.premiacao import panorama

CICLO = "2026-10"


def _linha(gobrax, conduta, gr, nota, categoria="OURO", status="EXCELENTE"):
    ausentes = [c for c, v in (("gobrax", gobrax), ("conduta", conduta),
                               ("gr", gr)) if v is None]
    return {"gobrax": gobrax, "conduta": conduta, "gr": gr, "nota": nota,
            "categoria": categoria, "status": status, "ausentes": ausentes,
            "pilares": [c for c in ("gobrax", "conduta", "gr")
                        if c not in ausentes],
            "desvios": [], "medida": None}


#: O ciclo montado, no formato que `ranking.montar` devolve. Espelha o REAL:
#: um único motorista com os três pilares, o resto renormalizado.
MONTADO = {
    "ciclo": CICLO, "rotulo": "16/09 a 15/10 de 2026",
    "linhas": [_linha(86.0, 100.0, 99.0, 95.0)]
              + [_linha(86.0, 100.0, None, 98.5) for _ in range(49)]
              + [_linha(None, 100.0, None, 100.0) for _ in range(32)],
    "kpis": {"motoristas": 82, "com_nota": 82, "sem_nota": 0,
             "nota_mediana": 98.5, "com_pilar_faltando": 81,
             "por_status": {"EXCELENTE": 66, "BOM": 13, "ATENCAO": 2,
                            "ALERTA": 1},
             "por_categoria": {"DIAMANTE": 36, "OURO": 28, "ELITE": 12,
                               "PRATA": 4, "BRONZE": 2},
             "com_desvio": 0, "com_medida": 0},
    "parametros": {"RODOVIARIO": {"peso_gobrax": 40.0, "peso_conduta": 40.0,
                                  "peso_gr": 20.0}},
    "fontes": {"gobrax": {"motivo": "", "coletado_em": "2026-09-19T06:21:16",
                          "parcial": True, "com_nota": 50},
               "conduta": {"motivo": ""},
               "gr": {"motivo": "", "com_viagem": 152}},
    "pendencias": {"codigos_sem_depara": [{"codigo": 79, "descricao": "X",
                                           "vezes": 2}],
                   "ocorrencias_sem_codigo": 5, "gobrax_ambiguos": [],
                   "gobrax_fora_do_cadastro": 0, "sem_filial": 2,
                   "tipo_sugerido": 82},
}

AGREGADO = {"rotulo": "Agregados", "motoristas": 104, "motivo": "",
            "nota": None, "nota_motivo": "a nota do agregado é a do "
                                         "regulamento da campanha",
            "pilares": [
                {"chave": "gobrax", "rotulo": "Condução", "peso": None,
                 "com_nota": 1, "de": 104, "media": 32.0, "motivo": ""},
                {"chave": "conduta", "rotulo": "Comportamento", "peso": None,
                 "com_nota": 104, "de": 104, "media": 99.9, "motivo": ""},
                {"chave": "gr", "rotulo": "Gerenciamento de risco",
                 "peso": None, "com_nota": 12, "de": 104, "media": 91.8,
                 "motivo": ""}]}


@pytest.fixture
def montado(monkeypatch):
    """O ciclo e as fontes externas em dublê.

    `_montado` é a função CACHEADA — trocar `ranking.montar` por baixo dela
    deixaria o cache de uma outra rodada responder no lugar do dublê, e o teste
    passaria a medir o cache.
    """
    monkeypatch.setattr(panorama, "_montado", lambda c: MONTADO)
    monkeypatch.setattr(panorama, "_grupo_agregado", lambda c: dict(AGREGADO))
    monkeypatch.setattr(panorama.fechamento, "situacao", lambda c: None)
    monkeypatch.setattr(panorama.fechamento, "historico", lambda cs: {})
    monkeypatch.setattr(panorama.premio, "tabela",
                        lambda c: {"base": {}, "escada": {}, "versao": 1,
                                   "vigente_de": "2026-01", "motivo": ""})
    monkeypatch.setattr(panorama, "_campanha",
                        lambda c: {"existe": False, "motivo": "nenhuma campanha"})
    return panorama.montar(CICLO)


# ───────────────────────────────────────────── a cobertura e a nota
def test_a_nota_NUNCA_sai_sem_a_cobertura(montado):
    """98,5 com 1 de 82 completos não é a mesma afirmação que 98,5 com 82 de
    82, e o payload não deixa separar as duas."""
    assert montado["nota"]["mediana"] == 98.5
    assert montado["nota"]["completos"] == 1
    assert montado["nota"]["de"] == 82
    assert montado["medicao"]["com_pilar_faltando"] == 81


def test_pilar_sem_medicao_e_ND_com_motivo_e_nunca_zero(monkeypatch):
    """Zero é um número que alguém mediu. Pilar que ninguém mediu vira uma
    barra no chão e se lê como desempenho péssimo — o contrário do que houve."""
    linhas = [_linha(None, 100.0, None, 100.0) for _ in range(3)]
    pil = panorama._pilares(linhas, {"peso_gobrax": 40.0})
    gob = next(x for x in pil if x["chave"] == "gobrax")
    assert gob["media"] is None, "pilar sem medição não pode ter média"
    assert gob["com_nota"] == 0 and gob["de"] == 3
    assert "nenhum motorista medido" in gob["motivo"]
    cond = next(x for x in pil if x["chave"] == "conduta")
    assert cond["media"] == 100.0 and cond["com_nota"] == 3


def test_a_cobertura_de_cada_pilar_sai_junto_da_media(montado):
    pil = {x["chave"]: x for x in montado["medicao"]["pilares"]}
    assert pil["gobrax"]["com_nota"] == 50 and pil["gobrax"]["de"] == 82
    assert pil["gr"]["com_nota"] == 1
    # e o peso vem da régua, não escrito à mão
    assert pil["gobrax"]["peso"] == 40.0


# ───────────────────────────────────────────── os dois grupos
def test_frota_e_agregado_vem_SEPARADOS(montado):
    g = montado["grupos"]
    assert g["FROTA"]["motoristas"] == 82
    assert g["AGREGADO"]["motoristas"] == 104
    # e em lugar nenhum a soma dos dois
    assert 186 not in (g["FROTA"]["motoristas"], g["AGREGADO"]["motoristas"])
    assert montado["medicao"]["motoristas"] == 82, (
        "a medição da régua mensal é da frota própria, e só")


@pytest.fixture
def agregado_real(monkeypatch):
    """`_grupo_agregado` DE VERDADE, com dublê só nas FONTES.

    A primeira versão deste arquivo monkeypatchava a própria
    `_grupo_agregado` e lia o dicionário escrito à mão logo abaixo — a
    sabotagem "a nota do agregado saindo pela régua da folha" passou VERDE,
    porque o teste não tocava na função sabotada. O limite do dublê é a
    FRONTEIRA (o ERP e os pilares), nunca a função sob teste.
    """
    from api.campanha import base as cbase
    from api.premiacao import parametros, pilares

    pessoas = [{"cpf": "111", "nome": "A", "viagens": 9, "venc_cnh": None},
               {"cpf": "222", "nome": "B", "viagens": 4, "venc_cnh": None},
               {"cpf": "333", "nome": "C", "viagens": 7, "venc_cnh": None}]
    monkeypatch.setattr(cbase, "agregados_do_ciclo", lambda c: pessoas)
    # SÓ UM com telemetria, como no real (1 de 104).
    monkeypatch.setattr(pilares, "gobrax",
                        lambda alvo, cadastro=None, dir_path=None:
                        {"notas": {"111": {"nota": 32.0}}, "motivo": "",
                         "ambiguos": [], "sem_cadastro": []})
    monkeypatch.setattr(pilares, "comportamento_janela",
                        lambda alvo, n, dp: {"por_ciclo": {
                            CICLO: {c["cpf"]: {"desvios": [], "meritos": []}
                                    for c in pessoas}}, "motivo": "",
                            "nao_mapeados": [], "sem_codigo": 0})
    monkeypatch.setattr(pilares, "nota_comportamento", lambda ficha: 100.0)
    monkeypatch.setattr(pilares, "gr_janela",
                        lambda *a, **k: {"por_ciclo": {
                            CICLO: {"111": {"nota": 90.0},
                                    "222": {"nota": 93.6}}}, "motivo": ""})
    monkeypatch.setattr(parametros, "depara", lambda: {})
    monkeypatch.setattr(parametros, "pesos_gr", lambda c: {})
    monkeypatch.setattr(parametros, "ler", lambda c, g: {"valores": {
        "gr_minimo_viagens": 5, "gr_referencia": 58, "gr_queda": 40,
        "gr_piso": 20}})
    return panorama._grupo_agregado(CICLO)


def test_o_agregado_e_MAIOR_e_a_tela_diz_onde_ele_esta(montado):
    """Quem lê "82 motoristas" e conhece a operação conclui que o sistema
    perdeu gente: no mesmo ciclo rodaram 104 agregados."""
    assert montado["recorte"].startswith("frota própria")
    assert montado["grupos"]["AGREGADO"]["motoristas"] > \
        montado["grupos"]["FROTA"]["motoristas"]


# ───────────────────────────────────────────── o dinheiro
def test_o_panorama_NAO_publica_valor_em_reais(montado):
    """A aba do prêmio é bloqueável por usuário — ela existe para se dar a tela
    a quem acompanha conduta sem dar a folha junto. O panorama é a primeira
    aba, que todo mundo com a tela abre."""
    import json
    bruto = json.dumps(montado, ensure_ascii=False)
    for proibido in ('"total"', '"valor"', '"base"', 'R$'):
        assert proibido not in bruto, (proibido, bruto[:300])
    assert montado["pagar"]["pode"] is False
    assert "valor base" in montado["pagar"]["motivo"]


def test_com_valores_cadastrados_o_ciclo_PODE_pagar_e_o_VALOR_nao_atravessa(
        montado, monkeypatch):
    """O módulo LÊ a tabela de valores para saber se há cadastro, e é o ponto
    em que o dinheiro passa mais perto de vazar. O dublê tem valores com cara
    de valor justamente para que o guard prove que eles não saem.

    `"valor" not in payload` não serve de guard: `filiais_com_valor` é uma
    CONTAGEM e contém a palavra. Quem responde é o número.
    """
    import json
    monkeypatch.setattr(
        panorama.premio, "tabela",
        lambda c: {"base": {"RODOVIARIO": {"SBC": 1234.56, "JOI": 987.65}},
                   "escada": {"RODOVIARIO": {"24": 1500.0}}, "versao": 2,
                   "vigente_de": "2026-01", "motivo": ""})
    d = panorama.montar(CICLO)
    assert d["pagar"]["pode"] is True
    assert d["pagar"]["filiais_com_valor"] == 2
    assert d["pagar"]["grupos"] == {"RODOVIARIO": 2}

    bruto = json.dumps(d, ensure_ascii=False)
    for quantia in ("1234.56", "1234,56", "987.65", "987,65", "1500"):
        assert quantia not in bruto, ("vazou um valor da tabela", quantia)
    # e o bloco tem exatamente as chaves que foram decididas — chave nova aqui
    # nasce publicada, e é assim que o dinheiro voltaria sem ninguém ver
    assert set(d["pagar"]) == {"pode", "motivo", "filiais_com_valor", "grupos",
                               "versao", "vigente_de"}


# ───────────────────────────────────────────── a série
def test_a_serie_e_GERADA_e_sem_fechamento_DIZ_o_motivo(montado):
    """`GROUP BY` não devolve o ciclo que não tem linha: colhendo do banco, um
    ciclo sem fechamento sumiria e a linha emendaria por cima do buraco."""
    s = montado["serie"]
    assert len(s["linhas"]) == panorama.JANELA, "o intervalo não foi gerado"
    assert s["fechados"] == 0
    assert "nenhum ciclo fechado" in s["motivo"]
    # o ciclo em curso entra marcado, com a nota do cálculo
    atual = s["linhas"][-1]
    assert atual["ciclo"] == CICLO and atual["em_curso"] is True
    assert atual["mediana"] == 98.5
    # e os anteriores, sem fechamento, ficam VAZIOS — nunca zero
    assert all(x["mediana"] is None for x in s["linhas"][:-1])


def test_ciclo_fechado_entra_na_serie_com_a_mediana_da_FOTO(montado, monkeypatch):
    monkeypatch.setattr(panorama.fechamento, "historico",
                        lambda cs: {cs[0]: {"motoristas": 80, "com_nota": 80,
                                            "mediana": 91.2}})
    d = panorama.montar(CICLO)
    assert d["serie"]["fechados"] == 1
    assert d["serie"]["linhas"][0]["mediana"] == 91.2
    assert d["serie"]["motivo"] == ""


# ───────────────────────────────────────────── o que falta
def test_cada_pendencia_diz_O_QUE_FAZER(montado):
    """Contagem sem ação é um número que ninguém sabe o que fazer com."""
    pend = montado["pendencias"]
    assert pend, "o ciclo real tem pendências e elas sumiram"
    for x in pend:
        assert x["acao"], x
        assert x["rotulo"], x
    chaves = {x["chave"] for x in pend}
    assert {"depara", "sem_codigo", "sem_filial", "valores", "campanha"} <= chaves
    # a que impede pagar carrega o motivo do próprio módulo, não um texto solto
    valores = next(x for x in pend if x["chave"] == "valores")
    assert valores["acao"] == montado["pagar"]["motivo"]


def test_ciclo_invalido_e_recusa_legivel():
    with pytest.raises(ValueError, match="Ciclo inválido"):
        panorama.montar("setembro")


def test_a_nota_composta_do_AGREGADO_nao_sai_pela_regua_da_folha(agregado_real):
    """A mensal pesa 40/40/20 e sai da folha; a do agregado é a do regulamento
    da campanha, 50/30/20. Uma nota publicada pela régua errada apareceria ao
    lado da nota da frota como se fossem comparáveis.

    ESTE GUARD NASCEU VACUOSO, e a sabotagem o pegou: ele lia o dicionário que
    a fixture `montado` escreve à mão, com `_grupo_agregado` trocada por um
    lambda. Com a função trocada, fazer a nota sair pela régua da folha não
    mudava nada do que o teste via — verde com o defeito dentro.
    """
    ag = agregado_real
    assert ag["motoristas"] == 3
    assert ag["nota"] is None, "a régua da folha não dá nota ao agregado"
    assert "campanha" in ag["nota_motivo"]
    assert all(p["peso"] is None for p in ag["pilares"]), (
        "o peso da folha não vale para o agregado")


def test_o_AGREGADO_e_medido_pelos_MESMOS_pilares(agregado_real):
    """O que muda entre os dois grupos é a RÉGUA, não a leitura: a Gobrax, as
    ocorrências do ERP e os contadores do GR casam por CPF e não sabem quem é
    CLT e quem é fornecedor. É por isso que a cobertura do agregado é medível
    mesmo sem campanha criada — e é ela que mostra o buraco (1 de 104 no real).
    """
    pil = {x["chave"]: x for x in agregado_real["pilares"]}
    assert pil["gobrax"]["com_nota"] == 1 and pil["gobrax"]["de"] == 3
    assert pil["gobrax"]["media"] == 32.0
    assert pil["conduta"]["com_nota"] == 3
    assert pil["gr"]["com_nota"] == 2
