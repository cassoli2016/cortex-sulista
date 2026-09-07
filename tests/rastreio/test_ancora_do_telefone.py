# -*- coding: utf-8 -*-
"""O piso de uma mensagem por hora, medido no BANCO e não lido no arquivo.

POR QUE ESTE ARQUIVO EXISTE. O piso do aviso (`assinatura.INTERVALO_MIN`, 60
minutos) tinha três guards em `tests/rastreio/test_aviso.py` e todos eram sobre
a comparação em Python — passavam `desde_min=61` e `desde_min=22` de fixture e
conferiam quem saía. Nenhum rodava o SQL que PRODUZ o `desde_min`, e era ali
que o piso estava furado: o `::int` do Postgres ARREDONDA, então `59m31s` virava
`60` e a mensagem saía meio minuto antes da hora.

Não é teoria. Em 06/09/2026, na trilha `zap_envios`, o telefone final 9121
recebeu duas mensagens separadas por **59,9 minutos** — abaixo do piso que o
módulo inteiro existe para respeitar. Guard que lê o texto do módulo teria
passado; só executar a consulta pega isto.

O SCHEMA É DESCARTÁVEL (`esquema_pg`), e isso não é formalidade: em 06/09/2026
um guard que mexeu em `search_path` mandou a escrita da suíte para `cortex` e
apagou 219 registros reais. Aqui a consulta é de leitura, mas as LINHAS são
escritas — e escrever inscrição de dublê em produção mandaria WhatsApp para o
telefone do dublê no ciclo seguinte.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.rastreio import assinatura


def _inscrever(esquema: str, telefone: str, *, ha_segundos: int | None,
               criado_ha_segundos: int = 7200, numero: int = 90001) -> int:
    """Uma inscrição ativa. `ha_segundos` é a idade do ÚLTIMO ENVIO; `None`
    é quem nunca recebeu nada — aí a âncora é o pedido."""
    envio = ("now() - make_interval(secs => %d)" % ha_segundos
             if ha_segundos is not None else "NULL")
    return pglocal.um(
        "INSERT INTO rst_inscricao"
        " (grupo, empresa, filial, numero, serie, telefone, criado_em,"
        "  expira_em, ultimo_envio)"
        " VALUES (1, 1, 1, %%s, 1, %%s,"
        "         now() - make_interval(secs => %%s),"
        "         now() + interval '10 days', %s)"
        " RETURNING id" % envio,
        (numero, telefone, criado_ha_segundos), esquema=esquema)["id"]


def _desde(esquema: str) -> dict:
    """`{telefone: desde_min}` pela consulta DE VERDADE do módulo."""
    return {i["telefone"]: i["desde_min"]
            for i in assinatura.ativas(esquema=esquema)}


# --------------------------------------------------------------------------
# o piso
# --------------------------------------------------------------------------
@pytest.mark.parametrize("segundos, esperado", [
    (59 * 60 + 59, 59),   # 59m59s ainda é 59 — o piso de 60 não caiu
    (59 * 60 + 31, 59),   # o caso que o `::int` arredondava para 60
    (59 * 60 + 52, 59),   # 59,9 min: o intervalo REAL medido em 06/09/2026
    (60 * 60, 60),        # a hora cheia, que é quando pode sair
    (60 * 60 + 1, 60),
    (180 * 60, 180),      # a cadência "menos", três horas
])
def test_a_ancora_TRUNCA_os_minutos_e_nao_arredonda(esquema_pg, segundos,
                                                    esperado):
    """`desde_min` é quanto tempo JÁ passou, nunca quanto quase passou.

    Cada parâmetro aqui é um guard próprio: o de 59m31s prova o arredondamento
    e os outros provam que a correção não empurrou o piso para o outro lado —
    truncar o que já passou de 60 min faria a mensagem atrasar um minuto a cada
    ciclo, que é o mesmo defeito de sinal trocado.
    """
    _inscrever(esquema_pg, "5541999990001", ha_segundos=segundos)
    assert _desde(esquema_pg)["5541999990001"] == esperado


def test_a_ancora_e_do_TELEFONE_e_nao_da_carga(esquema_pg):
    """Duas cargas do mesmo número saem numa mensagem só, então o relógio é um
    só. Ancorar por carga faria quem acompanha duas receber duas por hora."""
    _inscrever(esquema_pg, "5541999990002", ha_segundos=3600, numero=90001)
    _inscrever(esquema_pg, "5541999990002", ha_segundos=600, numero=90002)
    # a mais RECENTE manda: falamos com este telefone há 10 minutos
    assert _desde(esquema_pg)["5541999990002"] == 10


def test_quem_NUNCA_recebeu_conta_do_pedido_MAIS_ANTIGO(esquema_pg):
    """Quem espera desde as 12h38 não vai para o fim da fila porque pediu uma
    segunda carga às 14h."""
    _inscrever(esquema_pg, "5541999990003", ha_segundos=None,
               criado_ha_segundos=7200, numero=90001)
    _inscrever(esquema_pg, "5541999990003", ha_segundos=None,
               criado_ha_segundos=600, numero=90002)
    assert _desde(esquema_pg)["5541999990003"] == 120


def test_inscricao_CANCELADA_nao_ancora_o_telefone(esquema_pg):
    """Cancelar libera a vaga e some do relógio. Se a linha morta continuasse
    contando, quem cancelou uma carga e cadastrou outra ficaria com a âncora
    presa na antiga — e a mensagem sairia na hora errada, sem erro nenhum."""
    ident = _inscrever(esquema_pg, "5541999990004", ha_segundos=60,
                       numero=90001)
    _inscrever(esquema_pg, "5541999990004", ha_segundos=3600, numero=90002)
    pglocal.executar("UPDATE rst_inscricao SET ativo = FALSE WHERE id = %s",
                     (ident,), esquema=esquema_pg)
    assert _desde(esquema_pg)["5541999990004"] == 60


# --------------------------------------------------------------------------
# o guard do guard
# --------------------------------------------------------------------------
def test_a_consulta_da_ancora_e_a_MESMA_que_producao_usa():
    """Este arquivo só vale se `ativas()` executar `ATIVAS_SQL`.

    Sem isto, alguém poderia editar a consulta dentro da função e deixar a
    constante — que é o que os testes acima rodam — parada e verde para sempre.
    """
    import inspect
    fonte = inspect.getsource(assinatura.ativas)
    assert "ATIVAS_SQL" in fonte and "SELECT" not in fonte, (
        "a consulta da âncora saiu da constante: os guards de "
        "test_ancora_do_telefone.py passariam a medir SQL que ninguém roda")
