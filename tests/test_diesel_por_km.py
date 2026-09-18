# -*- coding: utf-8 -*-
"""O R$/km do diesel e o km/l do caminhão próprio.

Quem opera, 18/09/2026: "valide o km/l — uma tela diz 1,81 e a outra 2,74".
Não eram duas réguas do mesmo número: `diesel_km` é CUSTO POR KM (R$ 1,99/km),
a tela de Combustível publica o km/l de TODA a frota (2,74) e o caminhão
próprio faz 3,10. O ritual mostrava o custo com o rótulo "Consumo — km por
litro" e direção MAIOR-MELHOR — o diesel encarecendo pintava verde.

O SQL roda num banco de DUBLÊ com os tipos do ERP, porque o que se protege aqui
é quem ENTRA na conta: um Polo a 12 km/l e um ARLA a R$ 3 o litro mudam os dois
números sem levantar erro nenhum. Guard de texto aprovaria a volta deles.

Placas e modelos são de mentira — o repositório é público.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from api import db, pglocal, queries

DDL = """
CREATE TABLE veiculo (
  placa varchar, utilizacaoveiculo varchar, tipoveiculo varchar,
  numerofrota varchar, tipofrota integer);
CREATE TABLE ctaplus_abastecimentos (
  veiculo_placa varchar, data_inicio_abastecimento timestamp,
  volume numeric, custo numeric, distancia numeric,
  combustivel_descricao varchar);
CREATE TABLE programacaoembarque (
  veiculo varchar, dtcancelamento date, semaforo integer, numero integer,
  tipo integer, dtemissao date, filial integer, kmfretecompra numeric);
"""

JANELA = ("2026-09-01", "2026-09-30")


def _popular(cur):
    cur.execute("""INSERT INTO veiculo VALUES
        ('CAM0001', 'TRA', 'CTRT6', 'T3000', 1),
        ('CAM0002', 'LOC', 'CTR',   'RL3022', 1),
        ('CAR0001', 'TRA', 'A',     'A2010', 1),
        ('AGR0001', 'AGR', 'CTRT6', 'S3015', 2)""")
    # caminhão próprio: 3.000 km com 1.000 L a R$ 6/L → 3,00 km/l e R$ 2,00/km
    cur.execute("""INSERT INTO ctaplus_abastecimentos VALUES
        ('CAM0001', '2026-09-03 08:00', 600, 3600, 1800, 'DIESEL S10'),
        ('CAM0002', '2026-09-05 09:00', 400, 2400, 1200, 'DIESEL S10')""")
    # o AUTOMÓVEL: 12 km/l e R$ 0,50/km. Se entrar, puxa o km/l para cima e o
    # R$/km para baixo — foi o que acontecia.
    cur.execute("""INSERT INTO ctaplus_abastecimentos VALUES
        ('CAR0001', '2026-09-07 10:00', 50, 300, 600, 'GASOLINA')""")
    # o ARLA: litro barato, sem km. Entrava no preço do litro e o derrubava.
    cur.execute("""INSERT INTO ctaplus_abastecimentos VALUES
        ('CAM0001', '2026-09-09 11:00', 100, 300, 0, 'ARLA 32')""")
    # o agregado: diesel que não é nosso
    cur.execute("""INSERT INTO ctaplus_abastecimentos VALUES
        ('AGR0001', '2026-09-11 12:00', 500, 3000, 1000, 'DIESEL S10')""")
    # distância absurda: o registro existe e a leitura não serve
    cur.execute("""INSERT INTO ctaplus_abastecimentos VALUES
        ('CAM0002', '2026-09-13 13:00', 30, 180, 9000, 'DIESEL S10')""")
    # km vazio da frota própria, para o custo do vazio
    cur.execute("""INSERT INTO programacaoembarque VALUES
        ('CAM0001', NULL, 1, 10, 3, '2026-09-04', 1, 1000)""")


@pytest.fixture
def ava(esquema_pg, monkeypatch):
    with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        # o SQL lê `sulista.ctaplus_abastecimentos`; no dublê o schema de teste
        # responde pelos dois nomes
        cur.execute("CREATE SCHEMA IF NOT EXISTS sulista")
        cur.execute("CREATE VIEW sulista.ctaplus_abastecimentos AS"
                    " SELECT * FROM ctaplus_abastecimentos")
        _popular(cur)

    @contextmanager
    def conexao_dubla():
        with pglocal.get_conn(esquema_pg) as c:
            yield c

    monkeypatch.setattr(db, "get_conn", conexao_dubla)
    queries._RESP_CACHE.clear()
    yield esquema_pg
    queries._RESP_CACHE.clear()


def _ler(ava):
    return queries._custo_vazio_proprio(*JANELA)


def test_o_AUTOMOVEL_nao_entra_na_conta_do_caminhao(ava):
    """Nove Polos, Saveiros e um Jeep vivem dentro de TRA/LOC e fazem 12 km/l
    contra 3,1 do caminhão. São 2% do litro e mexiam nos dois números: o km/l
    próprio ia de 3,10 para 3,33 e o R$/km caía quase 10% — e é o R$/km que
    valoriza o km vazio, ou seja, a mistura decidia DINHEIRO."""
    d = _ler(ava)
    # 3.000 km, 1.000 L, R$ 6.000 → exatamente 3,00 km/l e R$ 2,00/km
    assert d["km_l_proprio"] == pytest.approx(3.0), d
    assert d["diesel_km"] == pytest.approx(2.0), d


def test_o_ARLA_nao_entra_no_preco_do_litro(ava):
    """O ARLA custa menos por litro e não anda um metro. No numerador do R$/km
    ele é custo sem km; no preço do litro, ele baixava a média. A conta agora
    lê as MESMAS linhas dos dois lados."""
    with pglocal.get_conn(ava) as c, c.cursor() as cur:
        cur.execute("SELECT count(*)::int n FROM ctaplus_abastecimentos"
                    " WHERE combustivel_descricao ILIKE '%%arla%%'")
        assert cur.fetchone()["n"] == 1, "o dublê precisa ter ARLA dentro"
    d = _ler(ava)
    # com o ARLA no custo seriam R$ 6.300 / 3.000 km = R$ 2,10
    assert d["diesel_km"] == pytest.approx(2.0), d


def test_o_AGREGADO_nao_entra_porque_o_diesel_nao_e_nosso(ava):
    """Agregado rodando vazio é custo de frete-compra dele."""
    d = _ler(ava)
    # com o agregado seriam 4.000 km e 1.500 L → 2,67 km/l
    assert d["km_l_proprio"] == pytest.approx(3.0), d


def test_distancia_absurda_fica_de_FORA_dos_dois_lados(ava):
    """9.000 km num abastecimento de 30 L é leitura torta, não viagem. Se ela
    entrasse no km e não no litro (ou vice-versa), os dois números mentiriam em
    direções opostas."""
    d = _ler(ava)
    assert d["km_l_proprio"] == pytest.approx(3.0), d
    assert d["diesel_km"] == pytest.approx(2.0), d


def test_o_custo_do_vazio_usa_o_RS_POR_KM_do_caminhao(ava):
    """O número que vira dinheiro na tela: 1.000 km vazios × R$ 2,00."""
    d = _ler(ava)
    assert d["km_vazio_proprio"] == pytest.approx(1000.0)
    assert d["custo_vazio_proprio"] == pytest.approx(2000.0), d


def test_a_recusa_por_modalidade_devolve_as_MESMAS_chaves():
    """A tela filtra por modalidade e TER/AGR não têm diesel nosso. Chave que
    só existe num dos caminhos vira KeyError na tela — e a tela é a mesma."""
    d = queries._custo_vazio_proprio(*JANELA, modalidade="AGR")
    assert set(d) == {"diesel_km", "km_l_proprio", "km_vazio_proprio",
                      "custo_vazio_proprio"}
    assert all(v is None for v in d.values())


# ===================================================== o indicador do ritual

def test_o_indicador_de_diesel_e_CUSTO_e_menor_e_melhor():
    """Ele já se chamou "Consumo — km por litro" com direção MAIOR-MELHOR: o
    diesel encarecendo por km pintava VERDE na reunião semanal. Guard do
    rótulo, da unidade e — a que custa caro — da direção."""
    from api.gestao import ritual
    f = ritual.FONTES["diesel_km"]
    assert f.unidade == "R$/km", f.unidade
    assert f.direcao == "menor_melhor", f.direcao
    assert "consumo" not in f.rotulo.lower(), f.rotulo
    assert "km/l" not in f.onde


def test_o_CONSUMO_existe_como_indicador_proprio():
    """A correção do rótulo sozinha tiraria o km/l da reunião. Ele volta como
    indicador PRÓPRIO, do caminhão próprio — não o 2,74 da tela de Combustível,
    que soma agregado e automóvel."""
    from api.gestao import ritual
    f = ritual.FONTES["consumo_proprio"]
    assert (f.unidade, f.direcao, f.gerencia) == ("km/l", "maior_melhor", "operacao")
    assert f.ler_ano is not None, "o consumo também acumula no ano"
    v = ritual.ler_fonte("consumo_proprio")
    assert v is None or isinstance(v, float)


def test_a_migration_corrige_o_cadastro_e_acrescenta_o_consumo(esquema_pg):
    """O cadastro é DADO: corrigir a fonte no código não mexe na linha que a
    reunião lê. E a correção é condicional — ajuste feito à mão pela tela de
    cadastro não pode ser desfeito por migration."""
    linhas = {r["fonte"]: dict(r) for r in pglocal.query(
        "SELECT fonte, nome, unidade, direcao FROM ges_indicadores"
        " WHERE fonte IN ('diesel_km','consumo_proprio')", esquema=esquema_pg)}
    assert linhas["diesel_km"]["unidade"] == "R$/km"
    assert linhas["diesel_km"]["direcao"] == "menor_melhor"
    assert "Consumo" not in linhas["diesel_km"]["nome"]
    assert linhas["consumo_proprio"]["unidade"] == "km/l"
    assert linhas["consumo_proprio"]["direcao"] == "maior_melhor"
