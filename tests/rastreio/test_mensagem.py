# -*- coding: utf-8 -*-
"""A REDAÇÃO do aviso de WhatsApp.

O QUE ESTES GUARDS PROTEGEM. Esta é a única coisa que a casa escreve e que sai
para o telefone de alguém que não é usuário do sistema — e sai sozinha, de hora
em hora, sem ninguém olhando. Três coisas não podem escapar:

1. **Nada sensível.** Valor, placa, motorista, CNPJ, coordenada. Um WhatsApp
   encaminhado não tem como ser desfeito.
2. **A barra não pode mentir nas pontas.** 99% desenhado como dez blocos cheios
   é lido como "chegou", e quem lê vai para a doca.
3. **O link tem de existir e apontar para o domínio certo.** Ele é o que separa
   "aviso útil" de "aviso que manda a pessoa redigitar tudo de novo".
"""
from __future__ import annotations

import pytest

from api.rastreio import mensagem

TOKEN = "abc123.deadbeef"


def _carga(**kw) -> dict:
    base = {"documento": "CT-e 51283", "origem": "Diadema/SP",
            "destino": "Santos/SP", "estado": "em_viagem",
            "entregue_em": None, "link_token": TOKEN,
            "andamento": {"tem_posicao": True, "progresso_pct": 62,
                          "falta_km": 118, "km_rota": 310, "por_rota": True,
                          "atualizado_ha_min": 7,
                          "transito": {"estado": "lento",
                                       "rotulo": "Trânsito lento",
                                       "atraso_min": 12}}}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# a barra
# --------------------------------------------------------------------------
def test_a_estrada_tem_sempre_a_mesma_largura():
    for pct in (0, 1, 37, 50, 99, 100):
        assert len(mensagem.barra(pct)) == mensagem.CELULAS, pct


def test_o_CAMINHAO_marca_a_posicao():
    """É ele que transforma "58%" em "estou aqui" — que é a pergunta que a
    pessoa realmente faz ao abrir a mensagem."""
    for pct in (0, 25, 50, 75, 99):
        b = mensagem.barra(pct)
        assert b.count(mensagem.CARRO) == 1, pct
        # e ele anda: a quantidade de estrada percorrida cresce com o %
    assert (mensagem.barra(75).count(mensagem.FEITO)
            > mensagem.barra(25).count(mensagem.FEITO))


def test_o_caminhao_NUNCA_chega_ao_fim_antes_dos_100():
    """A regra das pontas, agora mais visível ainda: com o caminhão na última
    célula a pessoa lê CHEGOU e desce para a doca. Só 100% troca a estrada pela
    bandeirada."""
    for pct in (95, 97, 98, 99):
        b = mensagem.barra(pct)
        assert b.endswith(mensagem.FALTA), pct
        assert mensagem.CHEGADA not in b, pct
    fim = mensagem.barra(100)
    assert fim.endswith(mensagem.CHEGADA) and mensagem.CARRO not in fim


def test_zero_por_cento_poe_o_caminhao_na_LARGADA():
    b = mensagem.barra(0)
    assert b.startswith(mensagem.CARRO)
    assert mensagem.FEITO not in b, "pintou estrada que ninguém rodou"


def test_a_estrada_aguenta_valor_fora_da_faixa():
    """Um progresso negativo ou acima de 100 é defeito de outro lugar; aqui ele
    não pode virar uma barra de tamanho errado no celular do cliente."""
    for pct in (-30, 140):
        assert len(mensagem.barra(pct)) == mensagem.CELULAS, pct


# --------------------------------------------------------------------------
# o link
# --------------------------------------------------------------------------
def test_o_link_vai_no_FRAGMENTO_e_nao_na_query():
    """O que vem depois do `#` não sai do aparelho: não chega ao servidor nem
    ao log do proxy. Na query, o token de uma carga de cliente ficaria gravado
    no log de acesso do Cloudflare."""
    lig = mensagem.link(_carga())
    assert "/r#c=" + TOKEN in lig
    assert "?" not in lig and "t=" + TOKEN not in lig


def test_o_dominio_e_o_da_casa_e_e_configuravel(monkeypatch):
    """Configurável não é firula: este domínio já mudou uma vez no meio da
    construção, e um endereço cravado teria ido junto na mensagem de todo
    cliente até alguém reparar."""
    monkeypatch.delenv("RASTREIO_URL_BASE", raising=False)
    assert mensagem.link(_carga()).startswith("https://cortex.sulista.com.br/")
    monkeypatch.setenv("RASTREIO_URL_BASE", "https://outro.exemplo.com/")
    assert mensagem.link(_carga()).startswith("https://outro.exemplo.com/r#")


def test_sem_token_o_link_ainda_leva_para_a_pagina():
    """Melhor a busca que link nenhum: sem isto, uma falha ao emitir o token
    deixaria a mensagem sem saída nenhuma."""
    c = _carga()
    c.pop("link_token")
    assert mensagem.link(c).endswith("/rastreio")


def test_toda_mensagem_leva_o_link(monkeypatch):
    monkeypatch.delenv("RASTREIO_URL_BASE", raising=False)
    casos = [_carga(),
             _carga(estado="descarregando"),
             _carga(andamento={"tem_posicao": False, "fora_da_rota": True}),
             _carga(andamento={"tem_posicao": False, "posicao_velha_min": 240})]
    for c in casos:
        t = mensagem.montar(c)
        assert t and TOKEN in t, c["estado"]


def test_a_ENTREGA_nao_precisa_de_link():
    """A carga chegou. Mandar a pessoa clicar para ver que chegou é ruído."""
    t = mensagem.montar(_carga(estado="entregue",
                               entregue_em="2026-09-04T15:30:00"))
    assert t and "Entregue" in t and "15:30" in t


# --------------------------------------------------------------------------
# o conteúdo
# --------------------------------------------------------------------------
def test_a_mensagem_diz_progresso_trecho_e_transito():
    t = mensagem.montar(_carga())
    assert "62%" in t
    assert "118 km" in t and "310 km" in t
    assert "Diadema/SP" in t and "Santos/SP" in t
    assert "12 min" in t
    assert "há 7 min" in t


def test_a_RETA_se_declara_e_a_rota_nao():
    """A reta subestima sempre — "faltam 56 km" quando faltam 80 de asfalto é
    uma promessa que a operação não cumpre."""
    c = _carga()
    c["andamento"]["por_rota"] = False
    assert "linha reta" in mensagem.montar(c)
    assert "linha reta" not in mensagem.montar(_carga())


def test_o_semaforo_do_transito_tem_TRES_estados_e_nada_mais():
    """Introduzir um quarto tom aqui quebraria o significado que o resto da
    casa já ensinou a ler."""
    assert set(mensagem.PONTO_TRANSITO) == {"livre", "lento", "parado",
                                            "bloqueado"}
    assert len(set(mensagem.PONTO_TRANSITO.values())) == 3


def test_transito_de_estado_desconhecido_nao_vira_linha_muda():
    c = _carga()
    c["andamento"]["transito"] = {"estado": "sei_la", "rotulo": "?"}
    t = mensagem.montar(c)
    assert "sei_la" not in t and "?" not in t


def test_sem_posicao_e_sem_ressalva_a_mensagem_CALA():
    """A terceira das três respostas: cala porque não há o que dizer."""
    assert mensagem.montar(_carga(andamento={"tem_posicao": False})) is None
    assert mensagem.montar(_carga(andamento={})) is None


def test_veiculo_fora_da_rota_RECUSA_dizendo_o_motivo():
    t = mensagem.montar(_carga(andamento={"tem_posicao": False,
                                          "fora_da_rota": True}))
    assert t and "situar o veículo" in t
    # E NÃO INVENTA PROGRESSO: um 0% aqui seria lido e acreditado.
    assert "%" not in t


def test_posicao_velha_vira_ressalva_e_nao_numero_antigo():
    t = mensagem.montar(_carga(andamento={"tem_posicao": False,
                                          "posicao_velha_min": 240}))
    assert t and "4h" in t
    t2 = mensagem.montar(_carga(andamento={"tem_posicao": False,
                                           "posicao_velha_min": 45}))
    assert t2 and "45 min" in t2


def test_carga_sem_origem_ainda_diz_o_destino():
    c = _carga()
    c.pop("origem")
    assert "Santos/SP" in mensagem.montar(c)


# --------------------------------------------------------------------------
# o que NÃO pode sair
# --------------------------------------------------------------------------
@pytest.mark.parametrize("estado,andamento", [
    ("em_viagem", None),
    ("entregue", None),
    ("descarregando", None),
    ("em_viagem", {"tem_posicao": False, "fora_da_rota": True}),
    ("em_viagem", {"tem_posicao": False, "posicao_velha_min": 300}),
])
def test_NENHUMA_mensagem_leva_dado_sensivel(estado, andamento):
    """O guard que vale mais que todos os outros deste arquivo.

    A carga de teste vem contaminada de propósito com placa, motorista, valor e
    coordenada — se qualquer caminho de redação passar a copiar o dicionário em
    vez de montar por lista explícita, este teste acende.
    """
    c = _carga(estado=estado, entregue_em="2026-09-04T15:30:00")
    if andamento is not None:
        c["andamento"] = andamento
    c["placa"] = "AAA1A11"
    c["motorista"] = "Fulano de Tal"
    c["valor_frete"] = 12345.67
    c["andamento"]["lat"] = -23.6821
    c["andamento"]["placa"] = "AAA1A11"
    # O BLOCO `transporte` EXISTE NO PAYLOAD DE VERDADE desde 05/09/2026: a
    # PÁGINA mostra placa e motorista, a MENSAGEM não. Contaminar com a forma
    # real é o que faz este guard valer — com a forma antiga ele conferia um
    # payload que não existe mais.
    c["transporte"] = {"cliente": "TUPY - JOINVILE/SC", "pagador": None,
                       "pagador_igual_cliente": False,
                       "motorista": "Fulano de Tal", "cavalo": "AAA1A11",
                       "carreta": "BBB2B22"}
    t = mensagem.montar(c) or ""
    for proibido in ("AAA1A11", "BBB2B22", "Fulano", "12345", "R$", "-23.68"):
        assert proibido not in t, proibido


def test_a_saida_e_UMA_PALAVRA_no_rodape():
    """Quem precisa achar um site para cancelar bloqueia o número em vez
    disso — e o bloqueio atinge o número que fala com todos os clientes."""
    assert "SAIR" in mensagem.RODAPE
