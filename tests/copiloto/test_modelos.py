"""Cadeia de modelos do Copiloto.

O catálogo :free do OpenRouter muda com frequência: em 19/08/2026, quatro dos
seis preferidos já não existiam. O código sobrevive a isso (usa o resto do
catálogo), mas a lista precisa de manutenção — e ninguém percebe uma lista de
nomes mortos sem um teste que reclame.
"""
from __future__ import annotations

from api import copiloto


def _catalogo(*ids):
    return {"data": [{"id": i, "context_length": 100000} for i in ids]}


def test_preferido_que_existe_vem_primeiro(monkeypatch):
    monkeypatch.setattr(copiloto, "_CATALOGO", {"ts": 0.0, "lista": []})
    monkeypatch.setattr(copiloto, "PREFERIDOS", ["bom/modelo:free"])
    monkeypatch.setattr(copiloto, "_http",
                        lambda *a, **k: (200, _catalogo("outro/x:free", "bom/modelo:free")))
    assert copiloto.modelos_free()[0] == "bom/modelo:free"


def test_preferido_que_sumiu_e_ignorado_sem_quebrar(monkeypatch):
    """O que garante que o Copiloto não morre quando o OpenRouter aposenta um
    modelo: o nome morto sai da fila e o resto do catálogo assume."""
    monkeypatch.setattr(copiloto, "_CATALOGO", {"ts": 0.0, "lista": []})
    monkeypatch.setattr(copiloto, "PREFERIDOS", ["morto/modelo:free", "vivo/modelo:free"])
    monkeypatch.setattr(copiloto, "_http",
                        lambda *a, **k: (200, _catalogo("vivo/modelo:free", "outro/y:free")))
    lista = copiloto.modelos_free()
    assert "morto/modelo:free" not in lista
    assert lista[0] == "vivo/modelo:free"
    assert "outro/y:free" in lista


def test_catalogo_sem_nenhum_preferido_ainda_devolve_modelos(monkeypatch):
    monkeypatch.setattr(copiloto, "_CATALOGO", {"ts": 0.0, "lista": []})
    monkeypatch.setattr(copiloto, "PREFERIDOS", ["nada/aqui:free"])
    monkeypatch.setattr(copiloto, "_http",
                        lambda *a, **k: (200, _catalogo("a/x:free", "b/y:free")))
    assert len(copiloto.modelos_free()) == 2


def test_so_entram_modelos_gratuitos(monkeypatch):
    """Um modelo pago na fila viraria cobrança silenciosa."""
    monkeypatch.setattr(copiloto, "_CATALOGO", {"ts": 0.0, "lista": []})
    monkeypatch.setattr(copiloto, "PREFERIDOS", [])
    monkeypatch.setattr(copiloto, "_http",
                        lambda *a, **k: (200, _catalogo("gratis/x:free", "pago/y")))
    lista = copiloto.modelos_free()
    assert lista == ["gratis/x:free"]
    assert all(m.endswith(":free") for m in lista)


def test_a_lista_de_preferidos_nao_tem_nome_repetido():
    assert len(copiloto.PREFERIDOS) == len(set(copiloto.PREFERIDOS))


def test_preferidos_ainda_existem_no_catalogo_real():
    """Teste de MANUTENÇÃO, não de código: avisa quando a lista envelhece.

    Requer rede e a chave; sem elas, não julga nada — não é papel deste teste
    quebrar a suíte por falta de internet.
    """
    import pytest
    if not copiloto.api_key():
        pytest.skip("sem OPENROUTER_API_KEY")
    try:
        catalogo = set(copiloto.modelos_free())
    except Exception:  # noqa: BLE001
        pytest.skip("catálogo do OpenRouter indisponível")
    mortos = [m for m in copiloto.PREFERIDOS if m not in catalogo]
    assert not mortos, (
        "modelos preferidos que sumiram do catálogo (atualize PREFERIDOS): "
        + ", ".join(mortos))


def test_desempate_por_porte_do_modelo(monkeypatch):
    """Antes ordenava por context_length: um modelo de 8B com janela enorme
    passava na frente de um de 200B. Porte é proxy melhor para qualidade."""
    monkeypatch.setattr(copiloto, "_CATALOGO", {"ts": 0.0, "lista": []})
    monkeypatch.setattr(copiloto, "PREFERIDOS", [])
    catalogo = {"data": [
        {"id": "pequeno/modelo-8b:free", "context_length": 1000000},
        {"id": "grande/modelo-200b:free", "context_length": 8000},
    ]}
    monkeypatch.setattr(copiloto, "_http", lambda *a, **k: (200, catalogo))
    assert copiloto.modelos_free()[0] == "grande/modelo-200b:free"


def test_modelo_sem_porte_no_id_cai_no_criterio_antigo(monkeypatch):
    monkeypatch.setattr(copiloto, "_CATALOGO", {"ts": 0.0, "lista": []})
    monkeypatch.setattr(copiloto, "PREFERIDOS", [])
    catalogo = {"data": [
        {"id": "sem/porte-a:free", "context_length": 8000},
        {"id": "sem/porte-b:free", "context_length": 900000},
    ]}
    monkeypatch.setattr(copiloto, "_http", lambda *a, **k: (200, catalogo))
    assert copiloto.modelos_free()[0] == "sem/porte-b:free"
