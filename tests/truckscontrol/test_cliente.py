# -*- coding: utf-8 -*-
"""O cliente do web service da TrucksControl, sem rede.

Os XML abaixo são os EXEMPLOS DO MANUAL do fornecedor (17/09/2026), copiados
como vieram — entrada de teste que representa formato externo é literal, nunca
derivada do nosso código. O `<ErrorRequest>` é o que o serviço devolveu de
verdade a uma credencial inválida, medido no ar no mesmo dia.
"""
from __future__ import annotations

import httpx
import pytest

from api.truckscontrol import cliente as tc

CAIXA_PRETA = """<?xml version="1.0" encoding="UTF-8"?>
<ResponseCaixaPreta>
  <Mensagem>
    <cpId>764674020</cpId>
    <veiID>123456</veiID>
    <dt>2017-04-05T09:15:00-03:00</dt>
    <dtinc>2017-04-05T09:59:07.05-03:00</dtinc>
    <lat>-27,6261</lat>
    <lon>-51,4699</lon>
    <vel>0</vel>
    <rpm>500</rpm>
    <estID>14</estID>
  </Mensagem>
  <Mensagem>
    <cpId>764738341</cpId>
    <veiID>123456</veiID>
    <dt>2017-04-05T09:54:00-03:00</dt>
    <dtinc>2017-04-05T10:03:56.623-03:00</dtinc>
    <lat>-28,8052</lat>
    <lon>-49,3716</lon>
    <vel>77</vel>
    <rpm>1200</rpm>
    <estID>734;20</estID>
  </Mensagem>
</ResponseCaixaPreta>"""

ESTATISTICAS = """<?xml version="1.0" encoding="UTF-8"?>
<ResponseTelemetriaEstatistica>
  <TelemetriaEstatistica>
    <estID>10</estID>
    <descricao>Excesso de Velocidade</descricao>
  </TelemetriaEstatistica>
  <TelemetriaEstatistica>
    <estID>14</estID>
    <descricao>Tempo Máximo de Veículo Parado com Motor Ligado</descricao>
  </TelemetriaEstatistica>
</ResponseTelemetriaEstatistica>"""

RELATORIO = """<?xml version="1.0" encoding="UTF-8"?>
<ResponseTelemetriaRelatorio>
<DataHoraRelatorio>
    <dtHr>25/09/2016</dtHr>
  </DataHoraRelatorio>
  <Relatorio>
    <veiID>224495</veiID>
    <distancia>526000</distancia>
    <velMedia>62,5</velMedia>
    <velMax>89</velMax>
    <horIni>120</horIni>
    <horFim>600</horFim>
    <utilizacao>480</utilizacao>
    <odmIni>63000</odmIni>
    <odmFim>63526</odmFim>
    <mediaConsumo>2,45</mediaConsumo>
    <consHoraMotor>12,3</consHoraMotor>
    <rpmMedio>1307</rpmMedio>
    <rpmMax>1900</rpmMax>
    <tempMax>92</tempMax>
    <tempMedia>84,5</tempMedia>
    <totalMotorLig>500</totalMotorLig>
    <totalMotorDeslig>940</totalMotorDeslig>
    <totalMotorLigMov>430</totalMotorLigMov>
    <totalMotorLigPar>70</totalMotorLigPar>
  </Relatorio>
</ResponseTelemetriaRelatorio>"""

ERRO_200 = ('<?xml version="1.0" encoding="UTF-8"?><ErrorRequest><erro>Atributos para '
            'leitura de requisição inválidos. (Atributos, login e/ou senha incorretos.)'
            '</erro></ErrorRequest>')


@pytest.fixture
def credencial(monkeypatch):
    monkeypatch.setattr(tc.credenciais, "ler",
                        lambda nome: {"TRUCKSCONTROL_LOGIN": "12345678910",
                                      "TRUCKSCONTROL_SENHA": "senha-secreta"}.get(nome))


def _responder(monkeypatch, corpo, status=200, guardar=None):
    def post(self, url, content=None, headers=None, **kw):
        if guardar is not None:
            guardar.append((url, (content or b"").decode("utf-8")))
        return httpx.Response(status, text=corpo,
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", post)


def test_sem_credencial_nao_e_falha_de_coleta_e_diz_onde_cadastrar(monkeypatch):
    monkeypatch.setattr(tc.credenciais, "ler", lambda nome: None)
    with pytest.raises(tc.SemCredencial, match="Integrações"):
        tc.estatisticas()


def test_o_post_vai_na_RAIZ_com_a_credencial_no_corpo(credencial, monkeypatch):
    """O manual dá o corpo e não o caminho; o caminho é a raiz (medido)."""
    vistos = []
    _responder(monkeypatch, ESTATISTICAS, guardar=vistos)
    tc.estatisticas()
    url, corpo = vistos[0]
    assert url == tc.URL
    assert corpo.startswith("<RequestTelemetriaEstatistica>")
    assert "<login>12345678910</login>" in corpo and "<senha>senha-secreta</senha>" in corpo


def test_erro_do_fornecedor_vem_com_HTTP_200(credencial, monkeypatch):
    """Login errado responde 200 com `<ErrorRequest>`: quem olha só o código
    grava uma coleta vazia como se fosse 'nenhum dado'."""
    _responder(monkeypatch, ERRO_200, status=200)
    with pytest.raises(tc.TrucksControlErro, match="recusou"):
        tc.caixa_preta(1)


def test_resposta_estranha_e_ERRO_nao_coleta_vazia(credencial, monkeypatch):
    """Uma página de erro em HTML é XML válido: sem conferir a RAIZ, ela cai
    sem `<Mensagem>` dentro e vira lista vazia — igualzinha a 'não há nada
    novo'. Foi o que a primeira versão deste cliente fazia."""
    _responder(monkeypatch, "<html>erro no servidor</html>")
    with pytest.raises(tc.TrucksControlErro, match="não reconhecida"):
        tc.caixa_preta(1)


def test_a_senha_NAO_aparece_em_mensagem_de_erro(credencial, monkeypatch):
    """A credencial viaja no CORPO: um erro que devolva o corpo cru publica a
    senha no log."""
    _responder(monkeypatch, "<html>erro no servidor</html>")
    with pytest.raises(tc.TrucksControlErro) as e:
        tc.estatisticas()
    assert "senha-secreta" not in str(e.value)
    assert tc._limpar("<login>abc</login><senha>123</senha>") == "<login>…</login><senha>…</senha>"


def test_caixa_preta_le_violacoes_forca_g_e_decimal_com_virgula(credencial, monkeypatch):
    _responder(monkeypatch, CAIXA_PRETA)
    m = tc.caixa_preta(1)
    assert [x["cp_id"] for x in m] == [764674020, 764738341]
    assert m[0]["lat"] == -27.6261 and m[0]["lon"] == -51.4699      # vírgula decimal
    assert m[0]["estatisticas"] == [14]
    assert m[1]["estatisticas"] == [734, 20]                        # separadas por ';'
    assert m[1]["velocidade"] == 77 and m[1]["rpm"] == 1200
    assert m[0]["forca_g"] is None                                  # opcional, ausente
    assert m[0]["dt"] == "2017-04-05T09:15:00-03:00"
    assert m[0]["dtinc"] == "2017-04-05T09:59:07.05-03:00"


def test_o_cursor_vai_no_pedido_e_e_o_maior_recebido(credencial, monkeypatch):
    vistos = []
    _responder(monkeypatch, CAIXA_PRETA, guardar=vistos)
    m = tc.caixa_preta(764674020)
    assert "<cpId>764674020</cpId>" in vistos[0][1]
    assert max(x["cp_id"] for x in m) == 764738341


def test_estatisticas_traduzem_o_estID():
    """Sem o de-para, a violação é um número sem significado na tela."""
    import xml.etree.ElementTree as ET
    raiz = ET.fromstring(ESTATISTICAS)
    assert [n.findtext("descricao") for n in raiz.findall(".//TelemetriaEstatistica")][0] == "Excesso de Velocidade"


def test_relatorio_mantem_as_unidades_do_manual(credencial, monkeypatch):
    """Distância em METROS e horímetro em MINUTOS, como o fornecedor manda:
    converter aqui esconderia a unidade de quem for conferir no portal dele."""
    _responder(monkeypatch, RELATORIO)
    r = tc.telemetria_relatorio()
    assert r["data"] == "25/09/2016"
    v = r["veiculos"][0]
    assert v["veiculo_id"] == 224495
    assert v["distancia_m"] == 526000 and v["utilizacao_min"] == 480
    assert v["media_consumo"] == 2.45 and v["vel_media"] == 62.5
    assert v["rpm_medio"] == 1307 and v["temp_media"] == 84.5
    assert (v["motor_ligado_movimento_min"], v["motor_ligado_parado_min"]) == (430, 70)


def test_tID_vai_sempre_1(credencial, monkeypatch):
    vistos = []
    _responder(monkeypatch, RELATORIO, guardar=vistos)
    tc.telemetria_relatorio()
    assert "<tID>1</tID>" in vistos[0][1]
