# tests/poligonos/test_poligonos.py
"""Permanencia nos poligonos da planta do cliente.

O que estes testes protegem, em ordem de quanto custaria descobrir tarde:

1. a ORDEM (lat, lon) do teste de contencao - errada, a tela fica vazia e nao
   da erro nenhum;
2. a permanencia ESTIMADA - sem ela, 34% das visitas (uma leitura de GPS so)
   mediriam zero minuto e a tela diria que ninguem para em lugar nenhum;
3. o TETO da estimativa - sem ele uma placa cuja leitura anterior foi ha 40 min
   ganha 20 minutos de portaria que nao existiram;
4. a MEDIANA em vez da media - 12,7% das visitas ao perimetro passam de 24 h
   (caminhao estacionado) e a media fica 2,4x a mediana.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from api.poligonos import servico
from api.poligonos.sql import (BBOX, CNPJ_TUPY_JOINVILLE, EXTENSAO_MAX,
                               GAP_VISITA, POLIGONOS_SQL, VISITAS_SQL)


# --- o SQL ------------------------------------------------------------------

def test_contencao_usa_a_ordem_latitude_longitude():
    """GOTCHA que nao levanta erro, so devolve vazio: os vertices em
    cadastro_poligono estao gravados como (LATITUDE, LONGITUDE), ao contrario
    da convencao GIS (x=lon, y=lat)."""
    assert "point(vp.latituderastreadora,\n" in VISITAS_SQL \
        or "point(vp.latituderastreadora," in VISITAS_SQL
    assert "point(vp.longituderastreadora, vp.latituderastreadora)" not in VISITAS_SQL


def test_desempate_entre_poligonos_e_deterministico():
    """Dois pares de poligonos internos se sobrepoem (Almox Ligas / Ligas II e
    Expedicao Perfis / Almox Granalhas). Sem ORDER BY, o LIMIT 1 escolheria
    qualquer um e o ranking mudaria sozinho entre execucoes."""
    assert "ORDER BY cp.id LIMIT 1" in VISITAS_SQL


def test_sql_respeita_pg93_e_latin1():
    for sql in (VISITAS_SQL, POLIGONOS_SQL):
        assert "FILTER (WHERE" not in sql.upper()
        assert "percentile_cont" not in sql.lower()
        sql.encode("latin-1")


def test_uma_passagem_so_pelo_teste_de_contencao():
    """O caro e o teste geometrico por linha (~67 mil posicoes/mes). Rodar as
    duas sessionizacoes em consultas separadas pagava o custo duas vezes -
    medido, 4,1 s + 3,9 s contra 5,0 s com o `bruto` compartilhado."""
    assert VISITAS_SQL.count("FROM veiculo_posicao") == 1
    assert "UNION ALL" in VISITAS_SQL


def test_o_perimetro_e_os_pontos_sao_tipos_diferentes():
    """tipo 1 = perimetro do sitio (um poligono de 26 vertices), tipo 4 = os
    pontos internos. Misturar os dois faria o tempo em ponto ser contado
    tambem como tempo de planta e a fila daria zero."""
    assert "cp.tipo = 4" in VISITAS_SQL
    assert "cp2.tipo = 1" in VISITAS_SQL


def test_caixa_do_sitio_filtra_antes_do_teste_geometrico():
    assert "BETWEEN %(lat1)s AND %(lat2)s" in VISITAS_SQL
    assert BBOX["lat1"] < BBOX["lat2"] and BBOX["lon1"] < BBOX["lon2"]


def test_cliente_entra_por_cnpj():
    """cadastro_poligono so guarda o codigo, nao o nome do cliente."""
    assert CNPJ_TUPY_JOINVILLE.isdigit() and len(CNPJ_TUPY_JOINVILLE) == 14


# --- as constantes medidas --------------------------------------------------

def test_corte_de_visita_acima_da_cadencia_do_rastreador():
    """MEDIDO em agosto/26 dentro da planta: 77,3% das leituras vem de 3 a 5
    min da anterior e so 0,6% passam de 15 min. Um corte menor que a cadencia
    partiria uma parada normal em varias visitas."""
    assert GAP_VISITA.startswith("15")


def test_teto_da_extensao_e_meia_cadencia():
    assert EXTENSAO_MAX.startswith("3")


# --- as estatisticas --------------------------------------------------------

def test_toda_estatistica_da_tela_e_mediana():
    """A media nao serve para nenhum dos dois escopos: no perimetro por causa
    do caminhao estacionado (uma visita de 145 h), no ponto por causa da cauda
    (p99 de 151 min contra mediana de 9)."""
    fonte = servico.__file__.replace(".pyc", ".py")
    with open(fonte, encoding="utf-8") as f:
        src = f.read()
    assert "statistics.median" in src
    assert "statistics.mean" not in src


def test_mediana_e_p90():
    assert servico._med([1.0, 2.0, 3.0]) == 2.0
    assert servico._med([]) is None
    assert servico._p90([float(i) for i in range(1, 11)]) == 9.0


# --- a janela ---------------------------------------------------------------

def test_janela_padrao_e_o_dia_final_entra_inteiro():
    de, ate = servico._janela(None, "2026-08-26")
    assert de == "2026-07-28"          # 29 dias para tras
    assert ate == "2026-08-27"         # exclusivo: o dia 26 inteiro entra


def test_janela_invertida_e_endireitada():
    de, ate = servico._janela("2026-08-26", "2026-08-01")
    assert de == "2026-08-01" and ate == "2026-08-27"


def test_janela_tem_teto():
    """Sem indice espacial, o teste de contencao roda por posicao; 120 dias ja
    levam ~20 s e um pedido de 2 anos derrubaria a tela."""
    de, ate = servico._janela("2024-01-01", "2026-08-26")
    assert de == "2026-04-28"


# --- o casamento ponto x passagem ------------------------------------------

def _v(placa, h0, h1, pol=None):
    return {"veiculo": placa, "poligono_id": pol,
            "entrada": datetime(2026, 8, 10, h0), "saida": datetime(2026, 8, 10, h1),
            "leituras": 5}


def test_ponto_casa_com_a_passagem_que_o_contem():
    planta = [_v("ABC1D23", 8, 18)]
    pontos = [_v("ABC1D23", 9, 10, 1), _v("ABC1D23", 14, 15, 2)]
    d = servico._casar(planta, pontos)
    assert d.pop("_orfas") == 0
    assert len(next(iter(d.values()))) == 2


def test_ponto_de_outra_placa_nao_casa():
    d = servico._casar([_v("ABC1D23", 8, 18)], [_v("XYZ9W88", 9, 10, 1)])
    assert d["_orfas"] == 1


def test_visita_orfa_e_CONTADA_e_nao_sumida():
    """Leitura de borda pode deixar a visita a ponto fora de qualquer passagem
    pelo perimetro. Ela conta no ranking e sai no aviso - some calada seria
    um numero menor sem explicacao."""
    d = servico._casar([_v("ABC1D23", 8, 9)], [_v("ABC1D23", 14, 15, 1)])
    assert d["_orfas"] == 1


# --- os avisos --------------------------------------------------------------

def test_avisa_quando_a_fila_domina_e_NAO_chama_tudo_de_espera():
    """Parte do tempo fora de ponto pode ser area de servico ainda nao
    mapeada. Tratar tudo como espera acusaria o cliente por uma lacuna de
    cadastro da propria Sulista."""
    av = servico._avisos(74.5, 0, 100, 0, [], [{"id": 1}])
    assert any("FORA de qualquer ponto" in a for a in av)
    assert any("nao mapeada" in a for a in av)


def test_avisa_a_cobertura_das_visitas_estimadas():
    av = servico._avisos(10.0, 912, 2676, 0, [], [{"id": 1}])
    assert any("912 de 2676" in a and "ESTIMADA" in a for a in av)


def test_sem_perimetro_a_tela_diz_o_que_perdeu():
    av = servico._avisos(None, 0, 0, 0, [], [])
    assert any("Perimetro da planta nao cadastrado" in a for a in av)


def test_poligono_sem_movimento_e_informacao():
    av = servico._avisos(10.0, 0, 10, 0, ["Almox CBL"], [{"id": 1}])
    assert any("Almox CBL" in a for a in av)


# --- RBAC -------------------------------------------------------------------

def test_tela_registrada_no_rbac_e_na_rota():
    from api.auth import ROTA_TELAS, TELAS
    assert "poli" in TELAS
    assert any(r[0] == "/api/operacional/poligonos" and "poli" in r[1]
               for r in ROTA_TELAS)
