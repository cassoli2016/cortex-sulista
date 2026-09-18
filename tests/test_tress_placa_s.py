# -*- coding: utf-8 -*-
"""O 'S' no fim da placa da 3S — o de agora (coleta) e o de antes (migration).

Quem opera, 18/09/2026: "algumas placas na 3S foi colocado um S no final da
placa; veja se isso interfere em algo na integração com o Córtex". Interfere
em tudo: a chave da casa é a PLACA, e `JOK3001S` não casa com `JOK3001` em
lugar nenhum — a carreta comunicava todo dia e o painel dizia "nunca
comunicou".

O que estes guards protegem é o CONDICIONAL. Cortar a última letra sempre
seria adivinhação: placa brasileira tem sete caracteres, então o corte só vale
quando os sete que sobram formam uma placa válida.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from api import pglocal
from api.tress import armazenamento, coleta
from tests.test_tress import _falso_http, _resp, creds  # noqa: F401

MIGRATION = Path(__file__).resolve().parents[1] / "sql/cortex/0100_tress_placa_s.sql"


# --------------------------------------------------------------- a coleta

def test_o_S_do_fim_CAI_quando_o_que_sobra_e_placa_de_verdade():
    """`JOK3001S` é `JOK3001` com sufixo do cadastro deles; `AA12345S` não é
    placa nenhuma sem o S, então o S fica."""
    assert coleta._placa("JOK3001S") == "JOK3001"      # três letras + 4
    assert coleta._placa("BBX3E09S") == "BBX3E09"      # Mercosul (letra no 5º)
    assert coleta._placa("AAW 5394") == "AAW5394"      # o espaço, como sempre
    # o que NÃO pode cair: sem o S o que sobra não é placa
    assert coleta._placa("AA12345S") == "AA12345S"
    assert coleta._placa("JOK3001") == "JOK3001"       # placa sem S não muda
    assert coleta._placa("") == ""


UM_S = _resp("ListaVeiculos", """<Veiculo>
  <tbVeiculo><Frota>S3074</Frota><Placa>JOK3001S</Placa>
    <Modelo>SEMI-REB.</Modelo><Tipo>Carreta</Tipo>
    <idEquipamento>20250917122792</idEquipamento><NumSerie>8626320883</NumSerie>
    <Chassis>94BF154377V014422</Chassis><idVeiculo>20250521102444</idVeiculo></tbVeiculo>
  <tbVeiculo><Frota>S3074</Frota><Placa>JOK3001</Placa>
    <Modelo>SEMI-REB.</Modelo><Tipo>Carreta</Tipo>
    <idEquipamento>20190926115141</idEquipamento><NumSerie>4632039854</NumSerie>
    <Chassis>94BF154377V014422</Chassis><idVeiculo>20190523124239</idVeiculo></tbVeiculo>
  <tbVeiculo><Frota>S9999</Frota><Placa>AA12345S</Placa>
    <Modelo>SEMI-REB.</Modelo><Tipo>Carreta</Tipo>
    <idEquipamento>20250101000001</idEquipamento><NumSerie>8626320999</NumSerie>
    <Chassis>93EF999</Chassis><idVeiculo>20250101000001</idVeiculo></tbVeiculo>
</Veiculo>""")

POS_S = _resp("ListaUltimaPosicaoVeiculos", """<Posicao>
  <tbUltimaPosicao><Placa>JOK3001S</Placa>
    <Data>2026-09-17T11:45:55-03:00</Data><Velocidade>0</Velocidade>
    <Satelite>9</Satelite><Ignicao>Desligado</Ignicao><UF>SP</UF>
    <Cidade>Jundiaí</Cidade><Bairro>Centro</Bairro><Endereco>Rua X</Endereco>
    <Latitude>-23.18</Latitude><Longitude>-46.88</Longitude>
  </tbUltimaPosicao>
  <tbUltimaPosicao><Placa>JOK3001</Placa>
    <Data>2024-06-05T03:42:15-03:00</Data><Velocidade>0</Velocidade>
    <Satelite>7</Satelite><Ignicao>Desligado</Ignicao><UF>PR</UF>
    <Cidade>Curitiba</Cidade><Bairro>Centro</Bairro><Endereco>Rua Y</Endereco>
    <Latitude>-25.4</Latitude><Longitude>-49.2</Longitude>
  </tbUltimaPosicao>
</Posicao>""")


def test_a_carreta_cadastrada_DUAS_VEZES_vira_UMA_com_o_cadastro_mais_novo(
        creds, monkeypatch, esquema_pg):  # noqa: F811
    """Cinco das 19 estão na conta da 3S com as DUAS formas, porque trocaram
    de rastreador e ninguém apagou o cadastro velho (mesmo chassi, séries
    diferentes). Normalizadas, as duas viram a mesma chave: sem desempate, a
    gravação da segunda apaga a da primeira e quem manda é a ORDEM em que o
    fornecedor listou. O desempate é o `idVeiculo`, que na 3S é um carimbo de
    tempo (`20260814145635`) — medido, não arbitrado."""
    _falso_http(monkeypatch, {"ListaVeiculos": UM_S, "ListaUltimaPosicaoVeiculos": POS_S})
    r = coleta.coletar(esquema=esquema_pg)
    assert r["duplicadas"] == 1, "a duplicata tem de ser CONTADA, não engolida"
    veic = _estado(esquema_pg)["veiculo"]
    assert set(veic) == {"JOK3001", "AA12345S"}
    assert veic["JOK3001"]["num_serie"] == "8626320883", "venceu o cadastro velho"
    # e a posição que fica é a MAIS RECENTE das duas, não a última lida
    pos = armazenamento.posicoes_por_placa(esquema=esquema_pg)
    assert pos["JOK3001"] == dt.datetime(2026, 9, 17, 11, 45, 55)


# ------------------------------------------------------- o que já está gravado

def _plantar(esquema: str) -> None:
    """As TRÊS histórias que o espelho tinha em 18/09/2026, com placas de
    dublê: a linha corrigida na 3S, os dois rastreadores no mesmo chassi, e a
    que só existe com 'S'. Mais duas de controle, que a migration não pode
    tocar."""
    def ex(sql, p):
        pglocal.executar(sql, p, esquema=esquema)

    VEIC = ("INSERT INTO tress_veiculo(placa, frota, modelo, tipo,"
            " id_equipamento, id_veiculo, num_serie, chassi, visto_em, sumiu_em)"
            " VALUES(%s,%s,'SEMI-REB.','Carreta',%s,%s,%s,%s,%s,%s)")
    POS = ("INSERT INTO tress_posicao(placa, id_posicao, dt, latitude, longitude,"
           " velocidade, ignicao, satelites, uf, cidade, bairro, endereco,"
           " coletado_em) VALUES(%s,'1',%s,-23.1,-46.8,0,'Desligado',9,'SP',"
           "'Jundiaí','Centro','Rua X',%s)")
    DIA = "INSERT INTO tress_visto_dia(placa, dia) VALUES(%s,%s)"
    agora = dt.datetime(2026, 9, 18, 9, 31)
    antes = dt.datetime(2026, 9, 17, 13, 1)

    # 1) a MESMA linha, com a placa corrigida na 3S entre duas coletas
    ex(VEIC, ("AAA1A01S", "S1", "eq1", "20250227120620", "ser1", "chassi1", antes, antes))
    ex(VEIC, ("AAA1A01", "S1", "eq1", "20250227120620", "ser1", "chassi1", agora, None))
    ex(POS, ("AAA1A01S", dt.datetime(2026, 9, 17, 13, 30), agora))
    ex(POS, ("AAA1A01", dt.datetime(2026, 9, 18, 9, 26), agora))
    ex(DIA, ("AAA1A01S", dt.date(2026, 9, 17)))
    ex(DIA, ("AAA1A01", dt.date(2026, 9, 18)))

    # 2) DOIS rastreadores no mesmo chassi: o novo está com 'S' e é o que fala
    ex(VEIC, ("BBB2B02S", "S2", "eq-novo", "20250521102444", "ser-nova", "chassi2", agora, None))
    ex(VEIC, ("BBB2B02", "S2", "eq-velho", "20190523124239", "ser-velha", "chassi2", agora, None))
    ex(POS, ("BBB2B02S", dt.datetime(2026, 9, 18, 2, 10), agora))
    ex(POS, ("BBB2B02", dt.datetime(2024, 6, 5, 3, 42), agora))
    for d in (16, 17, 18):
        ex(DIA, ("BBB2B02S", dt.date(2026, 9, d)))
    ex(DIA, ("BBB2B02", dt.date(2026, 9, 18)))          # dia repetido nas duas

    # 3) só existe com 'S'
    ex(VEIC, ("CCC3C03S", "S3", "eq3", "20250226105215", "ser3", "chassi3", agora, None))
    ex(POS, ("CCC3C03S", dt.datetime(2026, 9, 18, 9, 28), agora))
    for d in (15, 16, 17, 18):
        ex(DIA, ("CCC3C03S", dt.date(2026, 9, d)))

    # 4) controle: placa normal e um 'S' que NÃO é sufixo (sem ele não é placa)
    ex(VEIC, ("DDD4D04", "S4", "eq4", "20250226105218", "ser4", "chassi4", agora, None))
    ex(POS, ("DDD4D04", dt.datetime(2026, 9, 18, 8, 45), agora))
    ex(DIA, ("DDD4D04", dt.date(2026, 9, 18)))
    ex(VEIC, ("AA12345S", "S5", "eq5", "20250226105219", "ser5", "chassi5", agora, None))
    ex(DIA, ("AA12345S", dt.date(2026, 9, 18)))


def _rodar_migration(esquema: str, texto: str | None = None) -> None:
    pglocal.executar(texto if texto is not None else MIGRATION.read_text(encoding="utf-8"),
                     esquema=esquema)


@pytest.fixture
def espelho(esquema_pg):
    """O esquema já vem com a migration aplicada (sobre tabela VAZIA, onde ela
    não tem o que juntar). Aqui ela roda DE NOVO, agora com dado dentro — que
    é a única forma de provar a junção. Rodar duas vezes também é o que a casa
    faz em produção quando alguém repete o `migrar_schema.py`."""
    _plantar(esquema_pg)
    return esquema_pg


def _estado(esquema: str) -> dict:
    v = {r["placa"]: dict(r) for r in
         pglocal.query("SELECT * FROM tress_veiculo", esquema=esquema)}
    p = {r["placa"]: dict(r) for r in
         pglocal.query("SELECT * FROM tress_posicao", esquema=esquema)}
    d: dict[str, list] = {}
    for r in pglocal.query("SELECT placa, dia FROM tress_visto_dia ORDER BY placa, dia",
                           esquema=esquema):
        d.setdefault(r["placa"], []).append(r["dia"])
    return {"veiculo": v, "posicao": p, "dia": d}


def test_a_migration_NAO_deixa_placa_com_S_em_nenhuma_das_tres_tabelas(espelho):
    """O 'S' pendurado em `tress_visto_dia` é o pior dos três: a posição a
    coleta repõe em meia hora, o cadastro também — o DIA é histórico e, se
    ficar pendurado numa placa que não existe, some para sempre."""
    _rodar_migration(espelho)
    e = _estado(espelho)
    # `AA12345S` é a testemunha: sem o 'S' ela não é placa, então ela FICA —
    # um guard em que tudo some não distingue junção de faxina.
    assert [p for p in e["veiculo"] if len(p) == 8 and p.endswith("S")] == ["AA12345S"]
    assert [p for p in e["dia"] if len(p) == 8 and p.endswith("S")] == ["AA12345S"]
    assert [p for p in e["posicao"] if len(p) == 8 and p.endswith("S")] == []


def test_o_DIA_muda_de_dono_sem_duplicar_e_sem_perder_nenhum(espelho):
    _rodar_migration(espelho)
    d = _estado(espelho)["dia"]
    # os três dias do rastreador novo + o dia que as duas formas tinham: 3, não 4
    assert d["BBB2B02"] == [dt.date(2026, 9, 16), dt.date(2026, 9, 17), dt.date(2026, 9, 18)]
    assert d["AAA1A01"] == [dt.date(2026, 9, 17), dt.date(2026, 9, 18)]
    assert d["CCC3C03"] == [dt.date(2026, 9, d_) for d_ in (15, 16, 17, 18)]
    assert d["DDD4D04"] == [dt.date(2026, 9, 18)]
    assert d["AA12345S"] == [dt.date(2026, 9, 18)], "essa não é sufixo: não se mexe"


def test_a_posicao_que_FICA_e_a_mais_recente_das_duas(espelho):
    """Sem isto, a junção faz uma carreta que comunicou hoje voltar para 2024
    — e o painel a chama de muda no dia seguinte. É a mesma regra do
    `gravar_posicoes`: a posição só ANDA PARA A FRENTE."""
    _rodar_migration(espelho)
    p = _estado(espelho)["posicao"]
    assert p["BBB2B02"]["dt"] == dt.datetime(2026, 9, 18, 2, 10)   # a do 'S'
    assert p["AAA1A01"]["dt"] == dt.datetime(2026, 9, 18, 9, 26)   # a da base
    assert p["CCC3C03"]["dt"] == dt.datetime(2026, 9, 18, 9, 28)   # veio pela cascata
    assert p["DDD4D04"]["dt"] == dt.datetime(2026, 9, 18, 8, 45)


def test_o_cadastro_que_manda_e_o_MAIS_NOVO_e_vivo_vence_sumido(espelho):
    _rodar_migration(espelho)
    v = _estado(espelho)["veiculo"]
    assert set(v) == {"AAA1A01", "BBB2B02", "CCC3C03", "DDD4D04", "AA12345S"}
    assert v["BBB2B02"]["num_serie"] == "ser-nova", "o cadastro velho venceu"
    assert v["AAA1A01"]["sumiu_em"] is None, "a forma viva tem de prevalecer"
    assert v["CCC3C03"]["num_serie"] == "ser3"


def test_rodar_DE_NOVO_nao_muda_mais_nada(espelho):
    """O `migrar_schema.py` é feito para se repetir sem medo, e backfill que
    só funciona uma vez é armadilha para quem restaurar um backup."""
    _rodar_migration(espelho)
    antes = _estado(espelho)
    _rodar_migration(espelho)
    assert _estado(espelho) == antes


def test_a_placa_corrigida_ARRASTA_a_posicao_em_vez_de_apaga_la(espelho):
    """A FK ganhou `ON UPDATE CASCADE` nesta migration. Sem ela, renomear a
    placa exige apagar a posição antes — e apagar posição para arrumar texto é
    ficar sem resposta para "está comunicando?" durante o conserto."""
    _rodar_migration(espelho)
    pglocal.executar("UPDATE tress_veiculo SET placa='ZZZ9Z99' WHERE placa='CCC3C03'",
                     esquema=espelho)
    p = _estado(espelho)["posicao"]
    assert "ZZZ9Z99" in p and "CCC3C03" not in p
    assert p["ZZZ9Z99"]["dt"] == dt.datetime(2026, 9, 18, 9, 28)
