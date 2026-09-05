# -*- coding: utf-8 -*-
"""O histórico de movimentação vindo da Prolog.

O QUE ESTES GUARDS PROTEGEM. A classificação do movimento é o coração do
módulo: dela saem "quantos pneus morreram cedo", "quanto rodou cada vida" e
"quanto custou cada recapagem". Errar o tipo não dá erro nenhum — dá um
relatório calmo e errado.

O mapa é ENUMERÁVEL, e isso não é sorte: `source` e `destination` da Prolog são
um enum fechado de quatro valores (INVENTORY, ANALYSIS, INSTALLED, DISPOSAL),
lido do spec. Não há caso "outro" para adivinhar — há dezesseis pares, e a
ordem das regras é o que decide os ambíguos.
"""
from __future__ import annotations

import pytest

from api.pneus import historico as h


def _rel(**kw) -> dict:
    base = {"id": 1, "tireId": 99, "source": "INVENTORY",
            "destination": "INSTALLED", "tireServices": []}
    base.update(kw)
    return base


def _proc(de=598, para=598) -> dict:
    return {"id": 1, "submittedAt": "2026-08-31T20:03:54Z",
            "fromBranchOffice": {"id": de}, "toBranchOffice": {"id": para},
            "submittedBy": {"name": "FULANO"}}


# --------------------------------------------------------------------------
# a classificação do movimento
# --------------------------------------------------------------------------
def test_montar_no_veiculo_e_instalacao():
    assert h._tipo(_rel(destination="INSTALLED"), _proc()) == "instalacao"


def test_sair_do_veiculo_e_remocao():
    assert h._tipo(_rel(source="INSTALLED", destination="ANALYSIS"),
                   _proc()) == "remocao"


def test_ir_para_o_descarte_e_sucata():
    assert h._tipo(_rel(source="ANALYSIS", destination="DISPOSAL"),
                   _proc()) == "sucata"


def test_voltar_do_descarte_e_restauracao():
    """A Prolog tem rota própria para desfazer descarte. Sem este caso, o pneu
    ressuscitado entraria como movimento de estoque e a contagem de sucata do
    mês ficaria alta para sempre."""
    assert h._tipo(_rel(source="DISPOSAL", destination="INVENTORY"),
                   _proc()) == "restauracao"


def test_a_RECAPAGEM_vence_o_par_de_estados():
    """O guard mais importante do mapa.

    A recapagem chega como ANALYSIS -> INVENTORY, que é indistinguível de uma
    simples volta ao estoque. O que a distingue é o serviço com
    `introduceNewTireLifeCycle` — e é ele que abre a vida nova. Classificá-la
    como 'inventario' perderia a vida inteira: sem o evento, não há começo de
    vida, e sem começo não há km nem CPK dela.
    """
    rel = _rel(source="ANALYSIS", destination="INVENTORY", tireServices=[{
        "tireServiceName": "RECAPAGEM", "introduceNewTireLifeCycle": True,
        "tireServiceCost": 610.0, "tireLifeCycleAtService": 1}])
    assert h._tipo(rel, _proc()) == "retorno_recapagem"


def test_servico_que_NAO_abre_vida_nao_e_recapagem():
    """Conserto e vulcanização também são serviços, e não abrem vida. Tratar
    todo serviço como recapagem inflaria a contagem de vidas da frota."""
    rel = _rel(source="ANALYSIS", destination="INVENTORY", tireServices=[{
        "tireServiceName": "CONSERTO", "introduceNewTireLifeCycle": False}])
    assert h._tipo(rel, _proc()) == "inventario"


def test_mudanca_de_filial_e_transferencia():
    assert h._tipo(_rel(source="INVENTORY", destination="INVENTORY"),
                   _proc(de=598, para=602)) == "transferencia"


def test_a_recapagem_vence_ate_a_transferencia():
    """Ordem declarada: o que ABRE VIDA é o assunto do movimento, mesmo quando
    o pneu troca de filial na mesma operação."""
    rel = _rel(source="ANALYSIS", destination="INVENTORY", tireServices=[
        {"introduceNewTireLifeCycle": True, "tireLifeCycleAtService": 2}])
    assert h._tipo(rel, _proc(de=598, para=602)) == "retorno_recapagem"


def test_todo_par_do_enum_tem_classificacao():
    """O enum é fechado: dezesseis pares, nenhum sem resposta. Se a Prolog
    acrescentar um valor, este teste continua verde — mas o par novo cairá em
    'inventario' e o par CRU guardado no evento é o que vai denunciar."""
    estados = ("INVENTORY", "ANALYSIS", "INSTALLED", "DISPOSAL")
    validos = {"instalacao", "remocao", "sucata", "restauracao", "inventario",
               "transferencia", "retorno_recapagem"}
    for a in estados:
        for b in estados:
            assert h._tipo(_rel(source=a, destination=b), _proc()) in validos


# --------------------------------------------------------------------------
# os sulcos
# --------------------------------------------------------------------------
def test_os_quatro_sulcos_saem_na_ORDEM_declarada():
    """A ordem é o que torna o array legível: interno, meio interno, meio
    externo, externo. Sem ela seriam quatro números soltos."""
    rel = _rel(innerTreadDepth=9.0, middleInnerTreadDepth=8.5,
               middleOuterTreadDepth=8.0, outerTreadDepth=7.5)
    assert h._sulcos(rel) == [9.0, 8.5, 8.0, 7.5]


def test_sem_medida_de_sulco_nao_inventa_lista():
    assert h._sulcos(_rel()) is None


def test_sulco_parcial_preserva_o_buraco():
    """Medida faltando é lacuna, não zero: um ponto não medido vira None e
    continua None, senão o desgaste irregular apareceria onde não houve."""
    assert h._sulcos(_rel(innerTreadDepth=9.0, outerTreadDepth=7.0)) == [
        9.0, None, None, 7.0]


# --------------------------------------------------------------------------
# o caminhar da coleta
# --------------------------------------------------------------------------
def test_a_coleta_anda_para_TRAS_um_mes_por_vez():
    assert h._anterior("2026-09") == "2026-08"
    assert h._anterior("2026-01") == "2025-12"


def test_os_limites_do_mes_cobrem_o_mes_inteiro():
    """Fevereiro bissexto é o caso que um `+30 dias` erraria — e errar aqui é
    perder um dia de movimentação por mês, em silêncio."""
    assert h._limites("2026-02") == ("2026-02-01", "2026-02-28")
    assert h._limites("2024-02") == ("2024-02-01", "2024-02-29")
    assert h._limites("2026-12") == ("2026-12-01", "2026-12-31")


def test_sem_credencial_a_coleta_recusa_sem_levantar(monkeypatch):
    """Sem credencial não é falha, é instalação incompleta — e a tarefa
    agendada não pode morrer por isso."""
    monkeypatch.setattr(h.cliente, "pronto", lambda: False)
    r = h.sincronizar()
    assert r["ok"] is False and "não configurada" in r["erro"]


def test_a_cota_estourada_NAO_derruba_a_coleta(monkeypatch):
    """Medido em produção: a segunda rodada seguida bate 429. A execução tem
    de guardar o que já trouxe, registrar o motivo e deixar a próxima
    continuar — 429 é cota, não credencial, e some sozinho."""
    from api.pneus import cliente as cli

    chamadas = {"n": 0}

    class _Falso:
        def get(self, caminho, params=None, timeout=120):
            chamadas["n"] += 1
            if chamadas["n"] > 2:
                raise cli.PrologIndisponivel("cota esgotada (HTTP 429)")
            return {"content": [], "lastPage": False, "empty": False}

    monkeypatch.setattr(h.cliente, "pronto", lambda: True)
    monkeypatch.setattr(h.cliente, "Cliente", lambda *a, **k: _Falso())
    monkeypatch.setattr(h.cliente, "filiais_configuradas", lambda: ["598"])
    gravado = {}
    monkeypatch.setattr(h, "_gravar_estado",
                        lambda c, r, e: gravado.update(cursor=c, erro=e))
    monkeypatch.setattr(h, "_estado", lambda: {"cursor": None, "registros": 0})

    class _Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return None
        rowcount = 0

    class _Conn:
        def cursor(self): return _Ctx(_Cur())
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Ctx:
        def __init__(self, o): self.o = o
        def __enter__(self): return self.o
        def __exit__(self, *a): return False

    monkeypatch.setattr(h.pglocal, "get_conn", lambda *a, **k: _Conn())

    r = h.sincronizar(orcamento=6)
    assert r["ok"] is False
    assert "429" in r["erro"] or "cota" in r["erro"].lower()
    assert gravado["erro"], "o motivo da parada não foi registrado"


# --------------------------------------------------------------------------
# os campos que a casa NÃO lia — e a lição da Gobrax outra vez
# --------------------------------------------------------------------------
def test_o_hodometro_e_lido_e_tem_FAIXA_FISICA():
    """O guard de um achado real, 05/09/2026.

    `odometerReading` estava no payload desde sempre e a casa não lia: a coluna
    `km_veiculo` ficou 100% vazia nos 2.497 eventos importados, e sem hodômetro
    não há km de vida — o denominador do CPK. É a lição da Gobrax (14
    indicadores devolvidos, 3 lidos) repetida com outro fornecedor.

    E ele vem sujo: medidos numa página de 100 processos, 31 de 478 movimentos
    traziam valores fora da faixa — 1, 134 e 7.359.990. Nenhum é caminhão. Fora
    da faixa vira NULO, porque um hodômetro errado não estraga o CPK: ele o
    estraga EM SILÊNCIO, com número plausível.
    """
    assert h._odometro({"odometerReading": 377000}) == 377000
    for absurdo in (1, 134, 7359990, 0, -5, None, "", "abc"):
        assert h._odometro({"odometerReading": absurdo}) is None, absurdo
    assert h._odometro({}) is None


def test_a_placa_vem_SUJA_e_e_limpa_na_entrada():
    """28 das 478 chegaram com tabulação ou espaço nas bordas. Sem o `strip` o
    cruzamento com o cadastro do ERP falha nessas — e falha calado, virando
    'veículo sem km' em vez de erro."""
    for cru, limpo in (("\tFZS5B14", "FZS5B14"), (" SSY9G19", "SSY9G19"),
                       ("STK5C17\t", "STK5C17"), ("abc1d23", "ABC1D23")):
        assert h._placa({"vehicle": {"licensePlate": cru}}) == limpo
    assert h._placa({"vehicle": {"licensePlate": "   "}}) is None
    assert h._placa({}) is None


def test_o_evento_ja_gravado_RECEBE_os_campos_novos(esquema_pg):
    """O guard do backfill, contra o banco DE VERDADE.

    Com `ON CONFLICT DO NOTHING`, os 2.497 eventos já coletados ficariam sem
    placa, posição e hodômetro PARA SEMPRE — só os futuros teriam km, e o
    buraco não teria sintoma nenhum.

    Este teste grava DUAS vezes o mesmo movimento: primeiro sem os campos
    (como a coleta antiga fazia), depois com eles. Só o `DO UPDATE` faz a
    segunda passada preencher a primeira. E ele roda no Postgres real porque
    a diferença entre DO NOTHING e DO UPDATE só existe lá — um dublê de cursor
    aceitaria as duas e o teste ficaria verde com o defeito de volta.
    """
    from api import pglocal

    proc = {"submittedAt": "2026-08-31T17:44:38Z",
            "submittedBy": {"name": "FULANO"},
            "vehicle": {"licensePlate": "	TBB6B01"},
            "tireRelocations": [{
                "id": "7470789", "tireId": "1650908",
                "source": "INVENTORY", "destination": "INSTALLED",
                "tirePositionDestinationNomenclature": "TDE",
                "tireLifeCycleAtRelocation": 3}]}

    with pglocal.get_conn(esquema=esquema_pg) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO pne_modelo (marca, modelo) VALUES ('X','Y') "
                    "RETURNING id")
        modelo = cur.fetchone()["id"]
        cur.execute("INSERT INTO pne_pneu (serie, modelo_id, filial, status, "
                    "vida_atual, prolog_id) "
                    "VALUES ('30394',%s,'MTZ','rodando',3,'1650908')",
                    (modelo,))

        # PRIMEIRA VOLTA, como a coleta antiga: sem hodômetro no payload.
        novos = h._gravar_processo(cur, dict(proc, odometerReading=None), [], [0])
        assert novos == 1
        cur.execute("SELECT placa, posicao, km_veiculo FROM pne_evento")
        antes = cur.fetchone()
        assert antes["km_veiculo"] is None

        # SEGUNDA VOLTA, com o payload inteiro. É este o backfill.
        atualizados = [0]
        novos = h._gravar_processo(cur, dict(proc, odometerReading=90724), [],
                                   atualizados)
        assert novos == 0, "contou backfill como história nova"
        assert atualizados[0] == 1

        cur.execute("SELECT placa, posicao, km_veiculo FROM pne_evento")
        linhas = cur.fetchall()
        assert len(linhas) == 1, "duplicou o evento em vez de atualizar"
        d = linhas[0]
        assert d["km_veiculo"] == 90724, "o evento já gravado não recebeu o km"
        assert d["placa"] == "TBB6B01" and d["posicao"] == "TDE"
