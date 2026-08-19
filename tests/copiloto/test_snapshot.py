"""O que o Copiloto enxerga — e sobretudo o que ele NÃO pode enxergar.

O snapshot vai inteiro para um modelo de terceiro. Nome de motorista, placa,
CNPJ e nome de transportador não podem sair daqui, e é o _compacto que garante
isso descartando listas. Com as telas novas (ANTT, telemetria), passou a haver
muito nome dentro dessas listas — daí os testes explícitos.
"""
from __future__ import annotations

import json

from api import copiloto


def test_compacto_mantem_escalares():
    d = {"kpis": None, "total": 10, "media": 3.14159, "nome": "x", "flag": True}
    out = copiloto._compacto(d)
    assert out["total"] == 10
    assert out["media"] == 3.14
    assert out["flag"] is True


def test_compacto_descarta_listas():
    """É aqui que a PII morre: transportadores, motoristas e placas vêm em
    listas."""
    d = {"kpis": {"total": 5},
         "transportadores": [{"nome": "FULANO DE TAL", "rntrc": "123",
                              "pago": 1000.0}],
         "linhas": [{"placa": "ABC1D23", "driverName": "SICRANO"}]}
    out = copiloto._compacto(d)
    assert "transportadores" not in out
    assert "linhas" not in out
    assert "FULANO" not in json.dumps(out)
    assert "ABC1D23" not in json.dumps(out)


def test_compacto_mantem_dict_de_escalares():
    d = {"kpis": {"premiados": 24, "premio_total": 9375.63, "aderencia": None}}
    out = copiloto._compacto(d)
    assert out["kpis"]["premiados"] == 24
    assert out["kpis"]["premio_total"] == 9375.63


def test_compacto_nao_deixa_lista_passar_dentro_de_dict():
    """Um dict com lista dentro é o caminho mais fácil para PII escapar."""
    d = {"resumo": {"total": 3, "nomes": ["FULANO", "SICRANO"]}}
    out = copiloto._compacto(d)
    assert "nomes" not in out["resumo"]
    assert "FULANO" not in json.dumps(out)


def test_as_fontes_novas_estao_declaradas():
    """Toda fonte precisa de rótulo: o front mostra ao gestor o que a IA viu."""
    for chave in ("antt_piso", "antt_rntrc", "telemetria_consumo",
                  "premiacao", "dre_fechamento"):
        assert chave in copiloto._FONTES_ROTULO, chave


def test_todo_rotulo_corresponde_a_uma_fonte_coletada():
    """Rótulo sem fonte engana o ⓘ de procedência: diz que a IA viu uma tela
    que ela não viu."""
    fontes = copiloto._fontes_do_snapshot()
    assert set(copiloto._FONTES_ROTULO) == set(fontes)


def test_premiacao_nao_dispara_coleta_na_gobrax(monkeypatch):
    """Forçar a coleta sairia para a API da Gobrax e travaria o chat por ~18 s.
    Verifica o COMPORTAMENTO: procurar a string 'force' no código quebrava por
    causa do próprio comentário que explica a regra."""
    chamadas = []

    def obter_falso(mes=None, force=False, **kw):
        chamadas.append({"mes": mes, "force": force})
        return {"kpis": {"premiados": 1}}

    from api.premiacao import servico as prem
    monkeypatch.setattr(prem, "obter", obter_falso)
    copiloto._fontes_do_snapshot()["premiacao"]()
    assert chamadas and chamadas[0]["force"] is False


def test_consumo_da_telemetria_le_o_cache_e_nao_a_api(monkeypatch):
    """get_consumo lê o SQLite local; nenhuma chamada à Gobrax pode nascer do
    chat."""
    import inspect

    from api.gobrax import consumo
    fonte = inspect.getsource(consumo.get_consumo)
    assert "armazenamento.ler" in fonte
    assert "sincronizar" not in fonte


def test_banco_fora_nao_faz_o_chat_esperar_todos_os_timeouts(monkeypatch):
    """Medido em 19/08/2026: com o ERP inacessível, as 17 fontes em sequência
    levaram 240 s — o chat ficava 4 minutos mudo antes da primeira palavra.
    Depois da primeira falha de conexão, as demais são puladas."""
    import psycopg

    tentativas = []

    def fonte_ruim(nome):
        def _f():
            tentativas.append(nome)
            raise psycopg.OperationalError("connection timeout")
        return _f

    monkeypatch.setattr(copiloto, "_SNAP", {"ts": 0.0, "texto": "", "falhas": []})
    monkeypatch.setattr(copiloto, "_fontes_do_snapshot",
                        lambda: {f"f{i}": fonte_ruim(f"f{i}") for i in range(10)})
    texto = copiloto._snapshot()
    assert len(tentativas) == 1, f"tentou {len(tentativas)} fontes com o banco fora"
    assert "fontes_indisponiveis" in texto


def test_erro_de_uma_consulta_nao_derruba_as_outras_fontes(monkeypatch):
    """Fail-fast vale só para falha de CONEXÃO. Um erro de uma query específica
    não pode fazer o snapshot desistir do resto."""
    tentativas = []

    def ruim():
        tentativas.append("ruim")
        raise ValueError("coluna inexistente")

    def boa():
        tentativas.append("boa")
        return {"kpis": {"x": 1}}

    monkeypatch.setattr(copiloto, "_SNAP", {"ts": 0.0, "texto": "", "falhas": []})
    monkeypatch.setattr(copiloto, "_fontes_do_snapshot",
                        lambda: {"a": ruim, "b": boa, "c": boa})
    copiloto._snapshot()
    assert tentativas == ["ruim", "boa", "boa"]


def test_deteccao_de_falha_de_banco():
    import psycopg
    assert copiloto._e_falha_de_banco(psycopg.OperationalError("x"))
    assert copiloto._e_falha_de_banco(RuntimeError("connection refused"))
    assert not copiloto._e_falha_de_banco(ValueError("coluna inexistente"))
