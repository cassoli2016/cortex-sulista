# -*- coding: utf-8 -*-
"""A integração com a 3S: cliente, coleta e a fusão com o ERP.

Os guards são das coisas que fariam a integração mentir em silêncio: coleta
vazia virando espelho completo, posição andando para trás, credencial
aparecendo em log, e — a mais cara — o salto de número no dia em que a régua
mudou sendo apresentado como frota que melhorou.
"""
from __future__ import annotations

import datetime as dt

import pytest

from api.tress import armazenamento, cliente, coleta

HOJE = dt.date(2026, 9, 3)


def _resp(operacao: str, miolo: str) -> str:
    """Uma resposta SOAP como a 3S manda: XML escapado DENTRO do resultado."""
    from xml.sax.saxutils import escape
    return ('<?xml version="1.0"?><soap:Envelope '
            'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
            '<%sResponse><%sResult>%s</%sResult></%sResponse>'
            '</soap:Body></soap:Envelope>'
            % (operacao, operacao, escape(miolo), operacao, operacao))


VEICULOS = _resp("ListaVeiculos", """<Veiculo>
  <tbVeiculo><Frota>S2000</Frota><Placa>AAW 5394</Placa>
    <Modelo>SEMI-REB.</Modelo><Tipo>Carreta</Tipo>
    <idEquipamento>2025012315</idEquipamento><NumSerie>8626320</NumSerie>
    <Chassis>93EF133</Chassis><idVeiculo>2025022712</idVeiculo></tbVeiculo>
  <tbVeiculo><Frota>S2001</Frota><Placa>BBB1234</Placa>
    <Modelo>SEMI-REB.</Modelo><Tipo>Carreta</Tipo>
    <idEquipamento>2025012316</idEquipamento><NumSerie>8626321</NumSerie>
    <Chassis>93EF134</Chassis><idVeiculo>2025022713</idVeiculo></tbVeiculo>
</Veiculo>""")

POSICOES = _resp("ListaUltimaPosicaoVeiculos", """<Posicao>
  <tbUltimaPosicao><Placa>AAW 5394</Placa><Frota>S2000</Frota>
    <Data>2026-09-03T13:22:20-03:00</Data><Velocidade>72</Velocidade>
    <Satelite>11</Satelite><Ignicao>Ligado</Ignicao><UF>SP</UF>
    <Cidade>Caçapava</Cidade><Bairro>Centro</Bairro>
    <Endereco>Rodovia BR-376</Endereco>
    <Latitude>-23.1212440</Latitude><Longitude>-45.7242440</Longitude>
  </tbUltimaPosicao>
  <tbUltimaPosicao><Placa>BBB1234</Placa><Frota>S2001</Frota>
    <Data>2024-06-05T03:42:15-03:00</Data><Velocidade>0</Velocidade>
    <Satelite>9</Satelite><Ignicao>Desligado</Ignicao><UF>PR</UF>
    <Cidade>Curitiba</Cidade><Bairro>Centro</Bairro><Endereco>Rua X</Endereco>
    <Latitude>-25.4</Latitude><Longitude>-49.2</Longitude>
  </tbUltimaPosicao>
</Posicao>""")


@pytest.fixture
def creds(monkeypatch):
    valores = {"TRESS_LOGIN": "integracao.sulista", "TRESS_SENHA": "s3nh4&x",
               "TRESS_API_BASE_URL": "https://exemplo.invalido/ws.asmx"}
    monkeypatch.setattr(cliente, "_cred_ler", lambda n: valores.get(n, ""))
    return valores


def _falso_http(monkeypatch, respostas: dict, registro: list | None = None):
    """Troca o urlopen do cliente por um dublê que responde por operação."""
    class _R:
        def __init__(self, corpo):
            self._c = corpo.encode("utf-8")

        def read(self):
            return self._c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None, context=None):
        corpo = req.data.decode("utf-8")
        if registro is not None:
            registro.append(corpo)
        for op, resp in respostas.items():
            if "<%s " % op in corpo or "<%s>" % op in corpo:
                return _R(resp)
        raise AssertionError("operação inesperada: " + corpo[:200])

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _urlopen)


# ------------------------------------------------------------------ cliente

def test_a_senha_vai_ESCAPADA_no_xml(creds, monkeypatch):
    """A senha entra como texto dentro de uma tag. Um `&` cru quebra o
    documento inteiro, o servidor devolve 400 e a pessoa procura o erro na
    credencial — que está certa."""
    enviados = []
    _falso_http(monkeypatch, {"ValidaLogin": _resp("ValidaLogin", "0")}, enviados)
    cliente.chamar("ValidaLogin")
    assert "<Senha>s3nh4&amp;x</Senha>" in enviados[0]
    assert "<Senha>s3nh4&x</Senha>" not in enviados[0]


def test_erro_chega_como_TEXTO_com_http_200(creds, monkeypatch):
    """Esta API não usa código de erro: devolve "Erro: ..." no lugar do
    resultado, com HTTP 200. Quem decide é o conteúdo, nunca o status."""
    _falso_http(monkeypatch, {"ValidaLogin": _resp(
        "ValidaLogin", "Erro: Usuário ou senha inválidos")})
    with pytest.raises(cliente.TressIndisponivel) as exc:
        cliente.chamar("ValidaLogin")
    assert "inválidos" in str(exc.value)


def test_a_credencial_NAO_aparece_na_excecao(creds, monkeypatch):
    """A senha vai no CORPO, então o corpo devolvido num erro a carrega."""
    _falso_http(monkeypatch, {"ValidaLogin": _resp(
        "ValidaLogin", "Erro: falhou com <Senha>s3nh4&x</Senha> de "
                       "integracao.sulista")})
    with pytest.raises(cliente.TressIndisponivel) as exc:
        cliente.chamar("ValidaLogin")
    texto = str(exc.value)
    assert "s3nh4&x" not in texto and "integracao.sulista" not in texto


def test_sem_credencial_e_instalacao_incompleta(monkeypatch):
    monkeypatch.setattr(cliente, "_cred_ler", lambda n: "")
    assert not cliente.configurado()
    with pytest.raises(cliente.TressNaoConfigurado):
        cliente.chamar("ValidaLogin")
    assert cliente.testar()["estado"] == "info"


# ------------------------------------------------------------------- coleta

def test_a_coleta_le_veiculos_e_posicoes(creds, monkeypatch, esquema_pg):
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    r = coleta.coletar(esquema=esquema_pg)
    assert (r["veiculos"], r["posicoes"]) == (2, 2)
    pos = armazenamento.posicoes_por_placa(esquema=esquema_pg)
    # a PLACA é a chave, e a 3S manda com espaço
    assert set(pos) == {"AAW5394", "BBB1234"}
    assert pos["AAW5394"] == dt.datetime(2026, 9, 3, 13, 22, 20)


def test_a_coleta_e_idempotente(creds, monkeypatch, esquema_pg):
    """O agendador repete quando a máquina acorda."""
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    coleta.coletar(esquema=esquema_pg)
    assert armazenamento.estado(esquema=esquema_pg)["veiculos"] == 2


def test_coleta_VAZIA_nunca_vira_espelho_completo(creds, monkeypatch, esquema_pg):
    """"A lista voltou sem ninguém" não é "a frota acabou": é falha do
    fornecedor com cara de sucesso. Fechar 227 veículos por causa dela
    apagaria o painel."""
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    _falso_http(monkeypatch, {"ListaVeiculos": _resp("ListaVeiculos", "<Veiculo></Veiculo>")})
    with pytest.raises(cliente.TressIndisponivel):
        coleta.coletar(esquema=esquema_pg)
    e = armazenamento.estado(esquema=esquema_pg)
    assert e["veiculos"] == 2 and e["sumidos"] == 0


def test_a_posicao_so_ANDA_PARA_A_FRENTE(creds, monkeypatch, esquema_pg):
    """Equipamento que reenvia buffer atrasado faria a comunicação "voltar no
    tempo", e uma carreta que falou hoje apareceria como muda."""
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    antiga = POSICOES.replace("2026-09-03T13:22:20-03:00",
                              "2020-01-01T00:00:00-03:00")
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": antiga})
    coleta.coletar(esquema=esquema_pg)
    pos = armazenamento.posicoes_por_placa(esquema=esquema_pg)
    assert pos["AAW5394"] == dt.datetime(2026, 9, 3, 13, 22, 20)


def test_quem_sai_da_conta_e_marcado_e_quem_volta_e_LIMPO(creds, monkeypatch,
                                                          esquema_pg):
    """Sem limpar o `sumiu_em`, a carreta que volta ao contrato ficaria fora do
    painel para sempre e ninguém procuraria o motivo aqui."""
    monkeypatch.setattr(coleta, "MINIMO_PARA_FECHAR", 1)
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    so_um = _resp("ListaVeiculos", """<Veiculo><tbVeiculo><Frota>S2000</Frota>
      <Placa>AAW 5394</Placa><Tipo>Carreta</Tipo></tbVeiculo></Veiculo>""")
    _falso_http(monkeypatch, {"ListaVeiculos": so_um,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    assert coleta.coletar(esquema=esquema_pg)["sumiram"] == 1
    assert armazenamento.estado(esquema=esquema_pg)["sumidos"] == 1
    # e volta
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    assert armazenamento.estado(esquema=esquema_pg)["sumidos"] == 0


def test_o_DIA_de_cada_posicao_fica_registrado(creds, monkeypatch, esquema_pg):
    """A última posição responde "está viva?"; só o dia responde "comunicou
    NAQUELE dia?" — que é a pergunta da régua diária."""
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    assert armazenamento.vistos_no_dia(HOJE, esquema=esquema_pg) == {"AAW5394"}
    assert armazenamento.vistos_no_dia(dt.date(2024, 6, 5),
                                       esquema=esquema_pg) == {"BBB1234"}
    assert armazenamento.vistos_no_dia(dt.date(2026, 1, 1),
                                       esquema=esquema_pg) == set()


def test_a_primeira_leitura_e_a_NOSSA_nao_a_do_dado(creds, monkeypatch,
                                                    esquema_pg):
    """A primeira coleta traz posições velhas por natureza — havia carreta com
    última posição de 2024. A fronteira da régua é quando NÓS passamos a ler,
    não o dia mais antigo que apareceu."""
    _falso_http(monkeypatch, {"ListaVeiculos": VEICULOS,
                              "ListaUltimaPosicaoVeiculos": POSICOES})
    coleta.coletar(esquema=esquema_pg)
    assert armazenamento.primeira_leitura(esquema=esquema_pg) == dt.date.today()


# -------------------------------------------------------------------- fusão

def test_a_fusao_vence_a_leitura_mais_recente_e_nunca_piora(monkeypatch):
    """A 3S MELHORA a leitura do ERP, nunca a derruba: se ela estiver fora do
    ar ou trouxer dado mais velho, o painel volta a ser o que era."""
    from api import queries

    monkeypatch.setattr(
        "api.tress.armazenamento.posicoes_por_placa",
        lambda esquema=None: {"AAA1111": dt.datetime(2026, 9, 3, 10, 0),
                              "BBB2222": dt.datetime(2020, 1, 1, 0, 0)})
    linhas = [
        {"placa": "AAA1111", "ultima": None},                       # só 3S
        {"placa": "BBB2222", "ultima": dt.datetime(2026, 9, 2, 8, 0)},  # ERP ganha
        {"placa": "CCC3333", "ultima": dt.datetime(2026, 9, 1, 8, 0)},  # sem 3S
    ]
    fora, placar = queries._fundir_com_3s(linhas)
    por = {r["placa"]: r["ultima"] for r in fora}
    assert por["AAA1111"] == dt.datetime(2026, 9, 3, 10, 0)
    assert por["BBB2222"] == dt.datetime(2026, 9, 2, 8, 0)   # NÃO piorou
    assert por["CCC3333"] == dt.datetime(2026, 9, 1, 8, 0)
    assert placar["so_3s"] == 1 and placar["erp"] == 1


def test_sem_o_espelho_a_fusao_se_declara_indisponivel(monkeypatch):
    """Falha da 3S não pode derrubar o painel — ele volta a ser só o ERP, e
    diz isso na fonte."""
    from api import queries

    def _explode(esquema=None):
        raise RuntimeError("banco fora")

    monkeypatch.setattr("api.tress.armazenamento.posicoes_por_placa", _explode)
    linhas = [{"placa": "AAA1111", "ultima": None}]
    fora, placar = queries._fundir_com_3s(linhas)
    assert placar["indisponivel"] and fora[0]["ultima"] is None


# ------------------------------------------------- a régua que mudou no meio

def test_o_salto_do_primeiro_dia_NAO_e_anunciado_como_melhora():
    """No dia em que a leitura direta entrou, o número saltou de 54 para 128 —
    e isso não foi a frota melhorando, foi o CÓRTEX passando a enxergar.
    Chamar isso de evolução seria a mentira mais fácil deste aviso, ainda por
    cima uma que agrada."""
    from api.whatsapp import valores

    dados = {
        "dia": HOJE, "alvo": "3S", "troca_de_regua": True,
        "hoje": {"frota": 223, "comunicou": 128, "nunca": 39,
                 "mudo_15d": 45, "parou": 11},
        "anterior": {"dia": HOJE - dt.timedelta(days=1), "comunicou": 54,
                     "nunca": 115, "mudo_15d": 45, "frota": 223},
        "diferenca": {"primeira": False, "mudou": True, "entraram": [],
                      "sairam": ["X"]},
        "placas": [{"placa": "A1", "situacao": "nunca", "ultima": None}],
    }
    v = valores.comunicacao_3s(dados)
    assert "+74" not in v["evolucao"] and "+75" not in v["evolucao"]
    assert "direto da 3S" in v["evolucao"]
    # e no dia seguinte a comparação volta ao normal
    dados["troca_de_regua"] = False
    assert "Contra" in valores.comunicacao_3s(dados)["evolucao"]
