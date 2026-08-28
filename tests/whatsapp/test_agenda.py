"""Rotinas agendadas de WhatsApp.

A guarda que mais importa aqui não é de horário: é **dado ruim não vira
mensagem**. Uma automação que manda "Faturamento de hoje: R$ 0,00" às 8h da
manhã para a diretoria, porque o ERP não respondeu, assusta na primeira vez e
na segunda vira um remetente que ninguém lê.

As outras três vêm de `api/agendamento.py`, compartilhado com o e-mail, e por
isso já testadas lá: padrão desligado, passagem marcada mesmo sem envio, e
janela de atraso.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from api.whatsapp import agenda, modelos as md, registro
from tests.whatsapp.conftest import gravar_config, http_falso


@pytest.fixture(autouse=True)
def base(esquema_pg, monkeypatch):
    for mod in (agenda, md, registro):
        monkeypatch.setattr(mod, "ESQUEMA", esquema_pg)
    return esquema_pg


def _modelo(**troca):
    d = {"nome": "Aviso", "contexto": "livre", "corpo": "Bom dia."}
    d.update(troca)
    return md.gravar(d, usuario="ana")


def _rotina(chave, **troca):
    d = {"modelo": chave, "destinatarios": "(47) 99999-8888",
         "frequencia": "diario", "hora": "08:00", "ativo": True}
    d.update(troca)
    return agenda.gravar(d, "ana@sulista")


# ------------------------------------------------------------------ validação

def test_nasce_desligada_por_padrao():
    """Cadastrar não é autorizar a disparar todo dia."""
    m = _modelo()
    d = agenda.gravar({"modelo": m["chave"], "destinatarios": "47999998888"},
                      "ana@sulista")
    assert d["ativo"] == 0


def test_telefone_e_guardado_normalizado():
    """O mesmo número digitado de dois jeitos viraria dois destinatários e
    gastaria duas fatias do limite."""
    m = _modelo()
    d = _rotina(m["chave"], destinatarios="(47) 99999-8888, 5547999998888")
    assert d["destinatarios"] == "5547999998888"


def test_modelo_inexistente_e_recusado_NA_GRAVACAO():
    """Erro que só aparece numa rotina desassistida às 8h é erro que ninguém
    vê — e que fica quebrado até alguém notar a ausência da mensagem."""
    with pytest.raises(ValueError, match="não existe"):
        _rotina("modelo-que-nao-existe")


def test_telefone_invalido_e_recusado_na_gravacao():
    m = _modelo()
    with pytest.raises(ValueError, match="inválido"):
        _rotina(m["chave"], destinatarios="(20) 99999-8888")


def test_dia_do_mes_29_a_31_e_recusado():
    """Um mensal marcado no dia 31 não sairia em fevereiro nenhum, e ninguém
    saberia por quê."""
    m = _modelo()
    with pytest.raises(ValueError, match="não existem em todos os meses"):
        _rotina(m["chave"], frequencia="mensal", dia_mes=31)


# -------------------------------------------------------------------- horário

def test_diario_so_em_dias_uteis_pula_o_fim_de_semana():
    """Resumo de faturamento no domingo sai com "sem meta no dia" e vira ruído
    que ensina a ignorar o remetente."""
    ag = {"ativo": 1, "frequencia": "diario", "hora": "08:00", "dias_uteis": 1}
    sabado = datetime(2026, 8, 29, 9, 0)
    segunda = datetime(2026, 8, 31, 9, 0)
    pode, porque = agenda.deve_rodar(ag, sabado)
    assert pode is False and "fim de semana" in porque
    assert agenda.deve_rodar(ag, segunda)[0] is True


def test_sem_dias_uteis_sai_no_sabado_tambem():
    ag = {"ativo": 1, "frequencia": "diario", "hora": "08:00", "dias_uteis": 0}
    assert agenda.deve_rodar(ag, datetime(2026, 8, 29, 9, 0))[0] is True


def test_nao_reenvia_na_mesma_janela():
    """A marca da passagem é o que impede o disparo a cada 15 minutos, quando
    o agendador do Windows passa de novo."""
    ag = {"ativo": 1, "frequencia": "diario", "hora": "08:00", "dias_uteis": 0,
          "ultima_execucao": "2026-08-28 08:02:00"}
    pode, porque = agenda.deve_rodar(ag, datetime(2026, 8, 28, 8, 20))
    assert pode is False and "já enviado" in porque


def test_fora_da_janela_de_atraso_nao_sai():
    """Resumo da manhã chegando à noite ensina a ignorar o remetente."""
    ag = {"ativo": 1, "frequencia": "diario", "hora": "08:00", "dias_uteis": 0}
    pode, porque = agenda.deve_rodar(ag, datetime(2026, 8, 28, 21, 0))
    assert pode is False and "fora da janela" in porque


def test_a_descricao_diz_dias_uteis():
    assert agenda.descrever({"frequencia": "diario", "hora": "08:00",
                             "dias_uteis": 1}) == "todo dia útil às 08:00"


# ------------------------------------------------- dado ruim não vira mensagem

def test_numeros_incompletos_NAO_viram_mensagem(monkeypatch):
    """A guarda principal. Melhor não mandar do que mandar R$ 0,00 para a
    diretoria às 8h da manhã."""
    from api.whatsapp import valores
    m = md.gravar({"nome": "Faturamento", "contexto": "faturamento",
                   "corpo": "Faturamos {{faturado_dia}} em {{data}}."},
                  usuario="ana")
    monkeypatch.setattr(valores, "obter",
                        lambda nome: {"data": "28/08/2026", "faturado_dia": ""})
    vals, erro = agenda.montar_texto(m["chave"])
    assert vals == {} and "faturado_dia" in erro and "nada foi enviado" in erro


def test_provedor_que_estoura_nao_derruba_a_rotina(monkeypatch):
    from api.whatsapp import valores

    def _explode(nome):
        raise RuntimeError("AVA fora do ar")

    m = md.gravar({"nome": "Faturamento", "contexto": "faturamento",
                   "corpo": "Faturamos {{faturado_dia}}."}, usuario="ana")
    monkeypatch.setattr(valores, "obter", _explode)
    vals, erro = agenda.montar_texto(m["chave"])
    assert vals == {} and "não foi possível ler os números" in erro


def test_a_falha_e_REGISTRADA_para_nao_tentar_a_cada_15_min(monkeypatch):
    """Sem marcar a passagem, a rotina se acharia sempre na primeira execução
    e encheria o log com o mesmo erro a cada disparo do agendador."""
    from api.whatsapp import valores
    m = md.gravar({"nome": "Faturamento", "contexto": "faturamento",
                   "corpo": "Faturamos {{faturado_dia}}."}, usuario="ana")
    r = _rotina(m["chave"])
    monkeypatch.setattr(valores, "obter", lambda nome: {"faturado_dia": ""})

    linha = agenda.executar({**r, "id": r["id"]})
    assert "faturado_dia" in linha
    gravada = [x for x in agenda.listar() if x["id"] == r["id"]][0]
    assert gravada["ultima_execucao"]
    assert "não enviado" in gravada["ultimo_resultado"]


def test_modelo_desligado_nao_dispara_a_rotina():
    m = _modelo(ativo=0)
    vals, erro = agenda.montar_texto(m["chave"])
    assert "desligado" in erro


def test_modelo_excluido_deixa_a_rotina_RECUSANDO_e_nao_some():
    """Sem chave estrangeira de propósito: a rotina passa a falhar de forma
    visível, em vez de sumir junto com o modelo."""
    m = _modelo()
    r = _rotina(m["chave"])
    md.excluir(m["id"])
    assert [x for x in agenda.listar() if x["id"] == r["id"]]      # continua lá
    vals, erro = agenda.montar_texto(m["chave"])
    assert "não existe mais" in erro


# ----------------------------------------------------------------- ponta a ponta

def test_rotina_envia_pelo_MESMO_caminho_do_envio_manual():
    """Não existe atalho "porque é automático": a rotina obedece ao interruptor
    geral, à janela, aos limites e à checagem de conexão."""
    gravar_config()
    m = _modelo()
    r = _rotina(m["chave"])
    linha = agenda.executar({**r, "id": r["id"]}, http=http_falso())
    assert linha.startswith("OK"), linha
    trilha = registro.listar(1)[0]
    assert trilha["modelo"] == m["chave"]
    assert trilha["origem"] == "agenda"


def test_com_o_envio_DESLIGADO_a_rotina_nao_manda():
    gravar_config(ativo=False)
    m = _modelo()
    r = _rotina(m["chave"])
    linha = agenda.executar({**r, "id": r["id"]}, http=http_falso())
    assert linha.startswith("FALHA") and "DESLIGADO" in linha


def test_ensaio_nao_envia_e_nao_marca_passagem():
    gravar_config()
    m = _modelo()
    r = _rotina(m["chave"])
    linha = agenda.executar({**r, "id": r["id"]}, ensaio=True, http=http_falso())
    assert linha.strip().startswith(".") and "enviaria" in linha
    assert registro.listar(5) == []
    gravada = [x for x in agenda.listar() if x["id"] == r["id"]][0]
    assert gravada["ultima_execucao"] is None


def test_o_estado_diz_o_motivo_de_cada_rotina_nao_estar_pronta():
    """"Por que não saiu hoje?" é a pergunta que sempre aparece."""
    m = _modelo()
    _rotina(m["chave"], ativo=False)
    item = agenda.estado()["rotinas"][0]
    assert item["pronto"] is False
    assert item["motivo"] == "agendamento desligado"
    assert item["modelo_nome"] == "Aviso"
