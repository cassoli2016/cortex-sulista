# -*- coding: utf-8 -*-
"""Apontamentos do motorista e a última posição do celular (14/09/2026).

TRÊS GRUPOS DE GUARD, cada um por uma decisão de quem opera:

**A cerca decide, e a coordenada não fica.** O veredito sai do perímetro da
planta que o ERP já tem (`cadastro_poligono` tipo 1, vértice em LATITUDE,
LONGITUDE) ou, na falta dele, da coordenada do cadastro com raio declarado. A
tabela de apontamentos não tem coluna de latitude nem de longitude — e o guard
lê o `information_schema`, porque guard que lê texto-fonte protege contra
apagar, não contra acrescentar a coluna.

**A localização é obrigatória para apontar**, e o acesso mestre não aponta:
dali sairia a posição de quem administra gravada como a do motorista.

**A posição é só a ÚLTIMA, e some.** Uma linha por motorista (a chave é o
motorista), apagada no fim da viagem, na retirada da autorização e passadas
24 h. É o que separa "onde ele está" de "por onde ele andou".
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from api import pglocal
from api.motorista import apontamento as ap

from .conftest import cadastrar

#: Uma planta no FORMATO DO ERP: `((lat,lon),...)`, latitude primeiro — a ordem
#: inversa da de GIS. Quadrado de ~1 km em volta de (-26,30; -48,80).
PLANTA = "((-26.3045,-48.805),(-26.3045,-48.795),(-26.2955,-48.795),(-26.2955,-48.805))"
VIAGEM = {"numero": "178010", "placa": "NYP-3J22", "vazio": False, "cliente": "X"}

DENTRO = {"lat": -26.3000, "lon": -48.8000, "precisao": 12}
#: 0,01 grau de longitude a 26,3°S ≈ 998 m — a leste da borda leste (-48,795).
FORA = {"lat": -26.3000, "lon": -48.7850, "precisao": 15}


@pytest.fixture
def mot(esq, monkeypatch):
    mid = cadastrar(esq, "MOT-A", "5547999990001", "ANA MOTORISTA")
    sess = {"motorista_codigo": "MOT-A", "motorista_id": mid, "nome": "ANA MOTORISTA",
            "mestre": False, "sessao_id": 1}
    estado = {"viagem": dict(VIAGEM), "erp_falha": False, "pedidos": [],
              "alvo": {"poligono": ap.poligono(PLANTA), "coordenada": None}}
    monkeypatch.setattr(ap, "_viagem", lambda s: estado["viagem"])

    def alvo(codigo, numero, lado):
        if estado["erp_falha"]:
            raise RuntimeError("ERP fora do ar")
        estado["pedidos"].append((codigo, numero, lado))
        return estado["alvo"]

    monkeypatch.setattr(ap, "_alvo_do_erp", alvo)
    return sess, esq, estado


def _n(esq, tabela):
    return pglocal.um(f"SELECT count(*) AS n FROM {tabela}", None, esq)["n"]


# ═══════════════════════════════════════════════════════════════ geometria ══

def test_o_poligono_e_lido_na_ordem_do_ERP():
    pts = ap.poligono(PLANTA)
    assert len(pts) == 4 and pts[0] == (-26.3045, -48.805)


def test_dentro_da_planta_e_DENTRO_com_distancia_zero():
    v = ap.veredito(DENTRO["lat"], DENTRO["lon"], {"poligono": ap.poligono(PLANTA)})
    assert v == {"cerca": "dentro", "referencia": "poligono", "distancia_m": 0}


def test_fora_da_planta_mede_ate_a_BORDA_e_nao_ao_centro():
    """Até o centro seriam ~1,5 km; até a aresta leste, ~1 km. É a aresta que
    diz quanto falta para ele estar no cliente."""
    v = ap.veredito(FORA["lat"], FORA["lon"], {"poligono": ap.poligono(PLANTA)})
    assert v["cerca"] == "fora" and v["referencia"] == "poligono"
    assert 980 <= v["distancia_m"] <= 1015, v


def test_sem_cerca_a_reserva_e_a_COORDENADA_com_raio_declarado():
    alvo = {"poligono": [], "coordenada": (-26.30, -48.80)}
    perto = ap.veredito(-26.3027, -48.80, alvo)           # ~300 m
    longe = ap.veredito(-26.3072, -48.80, alvo)           # ~800 m
    assert perto["cerca"] == "dentro" and perto["referencia"] == "coordenada"
    assert longe["cerca"] == "fora" and 780 <= longe["distancia_m"] <= 820
    assert ap.RAIO_COORDENADA_M == 500


def test_sem_nada_e_SEM_CERCA_e_erp_fora_e_NAO_CONFERIDA():
    """Nenhum dos dois é "fora": fora afirmaria que alguém conferiu."""
    assert ap.veredito(-26.3, -48.8, {})["cerca"] == "sem_cerca"
    assert ap.veredito(-26.3, -48.8, None)["cerca"] == "nao_conferida"


def test_coordenada_zerada_do_cadastro_e_AUSENCIA():
    assert ap._coord("0", "0") is None and ap._coord("", None) is None
    assert ap._coord("-26.3", "-48.8") == (-26.3, -48.8)


def test_os_codigos_SAC_sao_os_do_monitoramento_do_ERP():
    """A torre casa cada apontamento com a ocorrência SAC pelo código. Lista
    escrita à mão se confere contra a fonte que ela diz reproduzir."""
    from api.horas_paradas import fonte
    assert [d["sac"] for d in ap.TIPOS.values()] == [394, 395, 396, 397]
    assert "394, 395, 396, 397" in fonte.CARGAS_SQL


# ═══════════════════════════════════════════════════════════ apontamento ════

def test_a_tabela_de_apontamentos_NAO_TEM_coluna_de_coordenada(esq):
    cols = {r["column_name"] for r in pglocal.query(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = %(s)s AND table_name = 'mot_apontamentos'""",
        {"s": esq}, esq)}
    assert cols, "a tabela não existe no schema de teste"
    assert not {c for c in cols if "lat" in c or "lon" in c or "coord" in c}, cols


def test_registrar_grava_o_VEREDITO_e_consulta_o_lado_certo(mot):
    sess, esq, estado = mot
    ap.autorizar(sess, True, esquema=esq)
    r = ap.registrar(sess, {"tipo": "chegou_coleta", **FORA}, esquema=esq)
    assert r["cerca"] == "fora" and 980 <= r["distancia_m"] <= 1015
    assert estado["pedidos"][-1] == ("MOT-A", "178010", "coleta")
    ap.registrar(sess, {"tipo": "chegou_entrega", **DENTRO}, esquema=esq)
    assert estado["pedidos"][-1][2] == "entrega"
    assert _n(esq, "mot_apontamentos") == 2


def test_sem_AUTORIZACAO_nao_registra(mot):
    sess, esq, _ = mot
    with pytest.raises(ap.Recusa, match="Autorize"):
        ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)
    assert _n(esq, "mot_apontamentos") == 0


def test_sem_COORDENADA_nao_registra(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    with pytest.raises(ap.Recusa, match="localização"):
        ap.registrar(sess, {"tipo": "chegou_coleta"}, esquema=esq)


@pytest.mark.parametrize("dados, trecho", [
    ({"lat": 0, "lon": 0, "precisao": 5}, "não é válida"),
    ({"lat": -26.3, "lon": -48.8, "precisao": 3000}, "imprecisa"),
])
def test_coordenada_sem_valor_e_RECUSADA(mot, dados, trecho):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    with pytest.raises(ap.Recusa, match=trecho):
        ap.registrar(sess, {"tipo": "chegou_coleta", **dados}, esquema=esq)


def test_o_mesmo_apontamento_NAO_se_registra_duas_vezes(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)
    with pytest.raises(ap.Recusa, match="já foi registrado"):
        ap.registrar(sess, {"tipo": "chegou_coleta", **FORA}, esquema=esq)
    assert _n(esq, "mot_apontamentos") == 1


def test_o_acesso_MESTRE_nao_aponta_nem_envia_posicao(mot):
    """Registrar dali gravaria a posição de quem administra como a do motorista."""
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    mestre = {**sess, "mestre": True}
    for acao in (lambda: ap.registrar(mestre, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq),
                 lambda: ap.posicao(mestre, DENTRO, esquema=esq),
                 lambda: ap.autorizar(mestre, False, esquema=esq)):
        with pytest.raises(ap.Recusa, match="conferência"):
            acao()
    assert _n(esq, "mot_apontamentos") == 0 and _n(esq, "mot_posicoes") == 0


def test_sem_viagem_ou_viagem_VAZIA_nao_registra(mot):
    sess, esq, estado = mot
    ap.autorizar(sess, True, esquema=esq)
    estado["viagem"] = None
    with pytest.raises(ap.Recusa, match="viagem em curso"):
        ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)
    estado["viagem"] = {**VIAGEM, "vazio": True}
    with pytest.raises(ap.Recusa, match="vazia"):
        ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)


def test_ERP_fora_do_ar_grava_NAO_CONFERIDA(mot):
    """O apontamento vale mesmo sem a cerca — mas não pode dizer "fora"."""
    sess, esq, estado = mot
    ap.autorizar(sess, True, esquema=esq)
    estado["erp_falha"] = True
    r = ap.registrar(sess, {"tipo": "saiu_coleta", **FORA}, esquema=esq)
    assert r["cerca"] == "nao_conferida" and r["distancia_m"] is None


def test_da_viagem_devolve_os_QUATRO_na_ordem(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.registrar(sess, {"tipo": "saiu_coleta", **DENTRO}, esquema=esq)
    lista = ap.da_viagem(sess, "178010", esquema=esq)
    assert [x["tipo"] for x in lista] == list(ap.TIPOS)
    feitos = {x["tipo"]: x for x in lista if x["feito"]}
    assert set(feitos) == {"saiu_coleta"}
    assert feitos["saiu_coleta"]["cerca"] == "dentro" and feitos["saiu_coleta"]["em"]


# ═══════════════════════════════════════════════════════ a última posição ═══

def test_a_posicao_guarda_UMA_linha_por_motorista(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    for lat in (-26.31, -26.32, -26.33):
        assert ap.posicao(sess, {"lat": lat, "lon": -48.8, "precisao": 30},
                          esquema=esq)["viagem"] is True
    linhas = pglocal.query("SELECT lat FROM mot_posicoes", None, esq)
    assert len(linhas) == 1 and linhas[0]["lat"] == pytest.approx(-26.33)


def test_viagem_TERMINADA_apaga_a_posicao(mot):
    sess, esq, estado = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.posicao(sess, DENTRO, esquema=esq)
    estado["viagem"] = None
    assert ap.posicao(sess, DENTRO, esquema=esq) == {"viagem": False}
    assert _n(esq, "mot_posicoes") == 0


def test_RETIRAR_a_autorizacao_apaga_a_posicao_e_bloqueia(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.posicao(sess, DENTRO, esquema=esq)
    assert ap.autorizar(sess, False, esquema=esq)["aceita"] is False
    assert _n(esq, "mot_posicoes") == 0
    with pytest.raises(ap.Recusa):
        ap.posicao(sess, DENTRO, esquema=esq)


def test_o_apontamento_tambem_atualiza_a_ultima_posicao(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)
    assert _n(esq, "mot_posicoes") == 1


def test_o_mapa_so_ve_placa_EM_VIAGEM_e_posicao_FRESCA(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.posicao(sess, DENTRO, esquema=esq)
    vistas = ap.posicoes_celular({"NYP3J22"}, esquema=esq)
    assert [p["placa"] for p in vistas] == ["NYP3J22"], "a placa se compara normalizada"
    assert vistas[0]["fonte"] == "celular do motorista" and vistas[0]["idade_min"] == 0
    assert ap.posicoes_celular({"OUT1A23"}, esquema=esq) == []

    pglocal.executar("UPDATE mot_posicoes SET em_servidor = now() - interval '3 hours'",
                     None, esq)
    assert ap.posicoes_celular({"NYP3J22"}, esquema=esq) == [], "velha não vai ao mapa"
    assert _n(esq, "mot_posicoes") == 1, "mas ainda não passou das 24 h"

    pglocal.executar("UPDATE mot_posicoes SET em_servidor = now() - interval '25 hours'",
                     None, esq)
    ap.posicoes_celular({"NYP3J22"}, esquema=esq)
    assert _n(esq, "mot_posicoes") == 0, "passadas 24 h a linha SOME"


# ═══════════════════════════════════════════════════════════════ a torre ═════

def test_a_torre_poe_o_ERP_AO_LADO_e_nao_expoe_o_codigo(mot, monkeypatch):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)
    em_app = pglocal.um("SELECT to_char(em_servidor,'YYYY-MM-DD HH24:MI') AS e "
                        "FROM mot_apontamentos", None, esq)["e"]
    erp = (datetime.strptime(em_app, "%Y-%m-%d %H:%M")
           - timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M")
    monkeypatch.setattr(ap, "_sac_do_erp",
                        lambda pares: {("MOT-A", "178010", 394): erp})
    d = ap.para_torre(esquema=esq)
    item = d["itens"][0]
    assert item["erp_em"] == erp and item["erp_dif_min"] == 12
    assert item["motorista"] == "ANA MOTORISTA" and item["rotulo"] == "Cheguei para carregar"
    texto = json.dumps(d)
    assert "MOT-A" not in texto and "motorista_codigo" not in texto, \
        "o código do motorista (CPF, para pessoa física) não sai do servidor"
    assert d["resumo"]["dentro"] == 1 and d["resumo"]["com_erp"] == 1


def test_a_torre_com_ERP_fora_diz_NAO_SEI(mot, monkeypatch):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)

    def falha(pares):
        raise RuntimeError("ERP fora")

    monkeypatch.setattr(ap, "_sac_do_erp", falha)
    d = ap.para_torre(esquema=esq)
    assert d["erp_ok"] is False and d["itens"][0]["erp_em"] is None


def test_a_contagem_e_so_de_ESCALARES(mot):
    sess, esq, _ = mot
    ap.autorizar(sess, True, esquema=esq)
    ap.registrar(sess, {"tipo": "chegou_coleta", **DENTRO}, esquema=esq)
    ap.registrar(sess, {"tipo": "saiu_coleta", **FORA}, esquema=esq)
    c = ap.contagem(esquema=esq)
    assert (c["ap_7d"], c["dentro_7d"], c["fora_7d"], c["autorizados"]) == (2, 1, 1, 1)
    assert c["posicoes_frescas"] == 1
