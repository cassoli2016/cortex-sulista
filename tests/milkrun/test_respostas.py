# tests/milkrun/test_respostas.py
"""Respostas calculadas: o modelo nao escolhe onde o numero E a resposta.

Motivo medido (A/B de 26/08): o gemma4 respondeu "MARTINREA, 212,5 min" a
"onde ficou mais parado" quando o certo era METALURGICA RIOSULENSE com 307,4 -
valor que estava no contexto DUAS vezes. O qwen deu a maior PERMANENCIA quando
perguntado do maior ATRASO. Resposta confiante, especifica e errada.
"""
from __future__ import annotations

from api.milkrun import respostas as r

CTX = {
    "periodo": {"de": "2026-08-19", "ate": "2026-08-26"},
    "pontos_com_permanencia_medida": 93,
    "pontos_com_atraso_medido": 40,
    "piores_atrasos": [
        {"coleta": 11710, "placa": "PKI5B52", "local": "S RIKO",
         "atraso_min": 333, "previsto": "p", "chegada": "c"},
        {"coleta": 55362, "placa": "TBB6A15", "local": "TEC BOMBAS",
         "atraso_min": 112, "previsto": "p", "chegada": "c"}],
    "ranking_fornecedores_por_permanencia": [
        {"local": "RIOSULENSE", "permanencia_mediana_min": 285.6,
         "permanencia_media_min": 285.6, "permanencia_max_min": 307.4,
         "paradas_com_medida": 2},
        {"local": "DELGA", "permanencia_mediana_min": 253.1,
         "permanencia_media_min": 253.1, "permanencia_max_min": 299.7,
         "paradas_com_medida": 1}],
    "ranking_placas_por_permanencia": [
        {"placa": "TBA3C91", "permanencia_mediana_min": 264.0,
         "permanencia_media_min": 208.0, "paradas_com_medida": 3}],
    "coletas": [{"coleta": 15900, "placa": "TBA3C91", "pontos": [
        {"local": "RIOSULENSE", "permanencia_min": 307.4,
         "chegada": "c", "saida": "s"}]}],
    "kpis": {"solicitacoes": 59, "pontos": 163, "concluidos": 109,
             "pendentes": 48, "frustrados": 4, "pct_realizado": 87.2,
             "vencidas": 12, "permanencia_mediana": 73.7},
}


def test_maior_atraso_traz_coleta_e_placa_certas():
    t = r.responder("Qual coleta teve o maior atraso e de quanto foi?", CTX)
    assert "11710" in t and "PKI5B52" in t and "5h33" in t


def test_atraso_NAO_cai_no_ranking_de_permanencia():
    """A confusao que o qwen cometeu sozinho: atraso e permanencia sao coisas
    diferentes, e a intencao de atraso tem de casar primeiro."""
    t = r.responder("Quem atrasou mais?", CTX)
    assert "atraso" in t.lower() and "RIOSULENSE" not in t


def test_top_n_respeita_o_numero_pedido():
    assert r.responder("Top 1 fornecedores por tempo parado", CTX).count("\n1.") == 1
    assert "2." in r.responder("Top 2 fornecedores por tempo parado", CTX)


def test_maior_permanencia_e_o_maximo_REAL():
    t = r.responder("Em qual ponto o veículo ficou mais tempo parado?", CTX)
    assert "RIOSULENSE" in t and "5h07" in t
    assert "DELGA" not in t


def test_veiculo_ficou_mais_tempo_NAO_e_ranking_de_placa():
    """Casava com a intencao de ranking por conter "veiculo" e "tempo" perto
    um do outro, e devolvia lista em vez do maximo."""
    t = r.responder("Em qual ponto o veículo ficou mais tempo parado?", CTX)
    assert "Top" not in t


def test_ranking_de_placa_so_quando_pedido():
    t = r.responder("Quais placas ficam mais paradas?", CTX)
    assert "TBA3C91" in t and "placas" in t


def test_mediana_e_media_vao_juntas_e_explicadas():
    t = r.responder("Top 3 fornecedores por tempo parado", CTX)
    assert "mediana" in t and "média" in t and "puxa a média" in t


def test_concordancia_de_parada():
    t = r.responder("Top 2 fornecedores por tempo parado", CTX)
    assert "1 parada ·" in t or t.rstrip().endswith("1 parada") or "1 parada" in t
    assert "1 paradas" not in t


def test_periodo_sem_medida_EXPLICA_em_vez_de_negar():
    """No recorte de HOJE as paradas estao pendentes. "Nao consta" faz o leitor
    achar que a tela nao tem o dado, quando basta abrir o periodo."""
    vazio = dict(CTX, pontos_com_permanencia_medida=0, pontos_com_atraso_medido=0)
    t = r.responder("Qual o maior atraso?", vazio)
    assert "Amplie o período" in t


def test_pergunta_aberta_vai_para_o_modelo():
    """Cobrir demais viraria arvore de decisao, que e pior que um modelo para
    o que e aberto."""
    assert r.responder("Por que a coleta 11710 demorou tanto?", CTX) is None
    assert r.responder("", CTX) is None


def test_detalhe_podado_e_declarado():
    t = r.responder("Onde ficou mais tempo parado?", dict(CTX, detalhe_podado={"x": 1}))
    assert "reduzido" in t


def test_fallback_no_agregado_quando_o_detalhe_foi_podado():
    """O agregado nunca e podado. Dizer "sem paradas medidas" com o numero no
    proprio contexto seria o erro que este modulo existe para nao cometer."""
    sem_detalhe = dict(CTX, coletas=[])
    t = r.responder("Onde ficou mais tempo parado?", sem_detalhe)
    assert "RIOSULENSE" in t and "5h07" in t
