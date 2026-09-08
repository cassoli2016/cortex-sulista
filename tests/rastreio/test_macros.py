# -*- coding: utf-8 -*-
"""As macros do rastreador na página pública.

O QUE ESTES GUARDS PROTEGEM não é o recurso: é o que vai junto com ele. No
MESMO campo do ERP em que chega "CHEGADA NO CLIENTE" chegam comandos da central
de risco com o que só pode ser código de liberação —
`DESBLOQUEAR VEICULO||3389|3398`, `DESLIGAR SIRENE||1432|1144`,
`ENTREGA DO VEICULO||3650|0323|174488`. Numa página aberta à internet isso não
é um rótulo feio: é incidente de segurança.

AS ENTRADAS AQUI SÃO LITERAIS COPIADOS DO REAL, nunca derivadas de
`macros.PUBLICAS`. Dublê montado a partir da constante testada não testa a
constante: sabotar a lista sabotaria junto o que o teste fabrica, e ele seguiria
verde. Estes textos foram lidos de `ocorrenciarastreamento` em 06/09/2026.
"""
from __future__ import annotations

from api.rastreio import macros

# --------------------------------------------------------------------------
# literais do ERP, copiados do banco vivo
# --------------------------------------------------------------------------
PERIGOSAS = [
    "DESBLOQUEAR VEICULO||3389|3398",
    "DESBLOQUEAR VEICULO||98662|0102",
    "DESBLOQUEAR VEICULO||100684|",
    "DESLIGAR SIRENE||1432|1144",
    "DESLIGAR SIRENE||2986|0910",
    "ENTREGA DO VEICULO||3650|0323|174488",
    "ENTREGA DO VEICULO||||[SATELITE]",
    "INICIO JORNADA||04.09.26.03.38",
    "FIM DE JORNADA||",
]

COM_SUFIXO = [
    ("PARADA TRANSITO||", "Parado no trânsito"),
    ("PARADA TRANSITO||WC", "Parado no trânsito"),
    ("PARADA TRANSITO||PARADO 101", "Parado no trânsito"),
    ("PARADA TRANSITO||[SATELITE]", "Parado no trânsito"),
    ("PARADA PARA REFEICAO||0422|0522", "Parada para refeição"),
    ("PARADA PARA REFEICAO||08.49|9.30", "Parada para refeição"),
    ("PARADA PARA ABASTECIMENTO||773604", "Parada para abastecer"),
    ("PARADA PARA DESCANSO||0730|0900", "Parada para descanso"),
    ("PARADA PARA PERNOITE|||", "Parada para pernoite"),
    ("CHEGADA NO CLIENTE", "Chegou no cliente"),
    ("FIM DE CARGA E/OU DESCARGA", "Carga/descarga concluída"),
    ("FIM DE VIAGEM", "Viagem encerrada"),
]


# --------------------------------------------------------------------------
# a contenção
# --------------------------------------------------------------------------
def test_comando_da_central_de_risco_NAO_SAI():
    """O guard que importa. Um código de liberação numa página pública não é
    vazamento de dado: é a chave do cadeado."""
    for bruto in PERIGOSAS:
        assert macros.rotulo(bruto) is None, bruto


def test_o_que_sai_e_o_NOSSO_texto_nunca_o_do_ERP():
    """A contenção robusta não é a lista: é esta linha. Se amanhã o hub mandar
    `CHEGADA NO CLIENTE|<código>`, o corte casa a chave e o que sai continua
    sendo "Chegou no cliente" — o código não tem por onde vazar."""
    saiu = macros.rotulo("CHEGADA NO CLIENTE|SENHA-4815|162342")
    assert saiu == "Chegou no cliente"
    for pedaco in ("SENHA", "4815", "162342", "|"):
        assert pedaco not in saiu


def test_o_sufixo_do_hub_nao_cria_chave_nova():
    """O hub manda o mesmo evento com sufixos que variam. Sem o corte no
    primeiro `|`, cada variação seria uma chave nova: a lista branca barraria
    evento legítimo enquanto crescesse sem fim."""
    for bruto, esperado in COM_SUFIXO:
        assert macros.rotulo(bruto) == esperado, bruto


def test_a_lista_e_BRANCA_e_nao_negra():
    """Lista de proibidos deixa passar o que for criado depois — e macro nova é
    cadastrada pela central de risco, não por nós."""
    for inventada in ("MACRO QUE NINGUEM VIU", "COMANDO NOVO||1234",
                      "ABRIR BAU||9999", ""):
        assert macros.rotulo(inventada) is None, inventada


def test_nenhum_rotulo_publico_carrega_numero_do_hub():
    """Se um valor da lista trouxesse o texto cru, o corte não adiantaria."""
    for chave, texto in macros.PUBLICAS.items():
        assert "|" not in texto, chave
        assert not any(c.isdigit() for c in texto), (chave, texto)


def test_os_MARCOS_sao_um_subconjunto_do_que_pode_sair():
    """Um marco fora da lista branca seria um evento que dispara mensagem e
    não pode ser mostrado — e a mensagem sairia com um rótulo vazio."""
    assert macros.MARCOS <= set(macros.PUBLICAS)


def test_a_JORNADA_do_motorista_nao_e_assunto_do_cliente():
    """A página fala da mercadoria. A rotina de trabalho de uma pessoa não é
    assunto de quem contratou o frete."""
    assert macros.rotulo("INICIO JORNADA||030920260340") is None
    assert macros.rotulo("FIM DE JORNADA||") is None


# --------------------------------------------------------------------------
# a leitura
# --------------------------------------------------------------------------
class _DbFalso:
    def __init__(self, linhas):
        self.linhas = linhas
        self.params = None

    def query(self, sql, params=None):
        self.params = params
        return self.linhas


def _linha(macro, quando="2026-09-06T19:08:07", cidade="CURITIBA", uf="PR"):
    from datetime import datetime
    return {"macro": macro, "quando": datetime.fromisoformat(quando),
            "cidade": cidade, "uf": uf}


def test_recentes_devolve_so_o_que_pode_sair(monkeypatch):
    from api import db
    falso = _DbFalso([
        _linha("FIM DE VIAGEM"),
        _linha("DESBLOQUEAR VEICULO||3389|3398"),
        _linha("CHEGADA NO CLIENTE"),
        _linha("DESLIGAR SIRENE||1432|1144"),
    ])
    monkeypatch.setattr(db, "query", falso.query)
    evs = macros.recentes("ABC1D23")
    assert [e["rotulo"] for e in evs] == ["Viagem encerrada",
                                          "Chegou no cliente"]
    assert all(e["marco"] for e in evs)


def test_o_lugar_sai_como_CIDADE_UF_e_nao_coordenada(monkeypatch):
    """A página arredonda a posição do veículo de propósito; a movimentação
    tem de ficar no MESMO grão. E usa o formatador da casa — o meu trocava
    espaço por barra e escrevia "Campina/Grande/Do/Sul/PR"."""
    from api import db
    monkeypatch.setattr(db, "query", _DbFalso(
        [_linha("CHEGADA NO CLIENTE", cidade="CAMPINA GRANDE DO SUL",
                uf="PR")]).query)
    assert macros.recentes("ABC1D23")[0]["onde"] == "Campina Grande Do Sul/PR"


def test_falha_de_leitura_devolve_VAZIO_e_nao_derruba_a_carga(monkeypatch):
    """A movimentação é um acréscimo. Derrubar o detalhe inteiro porque a
    tabela de macros não respondeu seria trocar uma informação a mais pela
    informação toda."""
    from api import db

    def explode(sql, params=None):
        raise RuntimeError("o ERP caiu")

    monkeypatch.setattr(db, "query", explode)
    assert macros.recentes("ABC1D23") == []


def test_a_consulta_LIMITA_a_janela_e_a_placa(monkeypatch):
    """Janela estreita e coluna indexada: a tabela tem 1 milhão de linhas e o
    AVA é 9.3 com `statement_timeout`."""
    from api import db
    falso = _DbFalso([])
    monkeypatch.setattr(db, "query", falso.query)
    macros.recentes("abc1d23", desde="2026-09-05", ate="2026-09-07")
    assert falso.params["placa"] == "ABC1D23", "a placa tem de ir normalizada"
    assert falso.params["dias"] == macros.DIAS
    assert falso.params["desde"] == "2026-09-05"
    assert falso.params["ate"] == "2026-09-07"
    assert "o.dtinc >=" in macros.SQL, "sem janela na coluna indexada"
    assert "o.veiculo = " in macros.SQL


def test_a_janela_do_aviso_vem_da_CONFIGURACAO_e_nao_do_codigo():
    """A página DIZ o horário em que os avisos saem, e ele é editável em
    Gestão › WhatsApp — já foi 08:00 e hoje é 06:00. Cravar o horário no HTML
    o tornaria mentira no dia em que alguém mudasse a configuração."""
    from api.rastreio import detalhe
    from api.whatsapp import config as wcfg
    c = wcfg.ler()
    assert detalhe._janela_do_aviso() == {"inicio": c["janela_inicio"],
                                          "fim": c["janela_fim"]}


def test_o_PAYLOAD_da_carga_leva_a_janela_ate_a_pagina(monkeypatch):
    """O guard que faltava, e a lição: o primeiro testava só a FUNÇÃO isolada.
    Trocar `"aviso_janela": _janela_do_aviso()` por `{}` no payload deixava a
    página muda e o teste verde — a função certa, desligada do lugar onde ela
    importa. Sabotar mostrou; sem sabotar, este arquivo teria passado a
    impressão de cobrir algo que não cobria."""
    from api.rastreio import detalhe
    from api.whatsapp import config as wcfg

    monkeypatch.setattr(detalhe, "_andamento", lambda linha: {})
    monkeypatch.setattr(detalhe, "_notas", lambda chaves: [])
    # O DUBLÊ ACOMPANHA A ASSINATURA REAL: `_movimentacao` ganhou `limite`
    # quando o encerramento por chegada passou a precisar da viagem inteira, e
    # não só das seis últimas que a tela mostra.
    monkeypatch.setattr(detalhe, "_movimentacao",
                        lambda linha, limite=None: [])

    # A linha crua do ERP, com o mínimo que `consulta._limpo` exige.
    linha = {"grupo": 1, "empresa": 1, "filial": 1, "numero": 51283,
             "serie": 1, "dtemissao": None, "dtprevisaoentrega": None,
             "dtentrega": None, "dtagendamentoentrega": None,
             "dtiniciodescarga": None, "placa": None, "carreta": None,
             "cidadecoleta": None, "ufcoleta": None,
             "destinatario_nome": None, "destinatario_cidade": None,
             "destinatario_uf": None, "motorista_nome": None,
             "cliente_nome": None, "pagador_nome": None}
    carga = detalhe._montar(linha, {"g": 1, "e": 1, "f": 1, "n": 51283,
                                    "s": 1})
    c = wcfg.ler()
    assert carga["aviso_janela"] == {"inicio": c["janela_inicio"],
                                     "fim": c["janela_fim"]}


def test_sem_ler_a_configuracao_a_janela_sai_VAZIA(monkeypatch):
    """Prometer um horário que não se conseguiu ler é pior que não prometer
    nada: a página omite a linha em vez de inventar."""
    from api.rastreio import detalhe
    from api.whatsapp import config as wcfg

    def explode():
        raise RuntimeError("arquivo de configuração ilegível")

    monkeypatch.setattr(wcfg, "ler", explode)
    assert detalhe._janela_do_aviso() == {}


def test_a_consulta_NAO_tem_porcentagem_solta():
    """`%` em constante de consulta vira placeholder do psycopg — inclusive
    dentro de comentário. Custou uma hora em 06/09/2026: a consulta foi
    recusada inteira, o `except` devolveu lista vazia como manda o contrato, e
    o resultado foi "nenhuma placa tem movimentação" — plausível e falso."""
    import re
    sobrando = re.findall(r"%(?!\((placa|dias|desde|ate|limite)\)s)", macros.SQL)
    assert not sobrando, sobrando
