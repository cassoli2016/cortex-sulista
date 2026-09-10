# -*- coding: utf-8 -*-
"""Ponto Certificado — o que o cliente entende do corpo REAL do fornecedor.

O DUBLÊ É COPIADO DA API DE VERDADE (09/09/2026, versão 3.0.2.0), com CPF, PIS,
matrícula e id de trabalhador trocados. Nada aqui foi montado a partir das
constantes do módulo: dublê derivado do que se testa não testa nada — sabotar a
constante sabotaria junto a entrada, e o teste seguiria verde.

As quatro marcações são as quatro formas que aparecem nas 875 de sete dias:
dentro de cerca com GPS; fora de cerca com GPS de verdade; fora de cerca por
AUSÊNCIA de GPS (a mais comum, 53%); e uma com atividade declarada (só 35%
declaram).

`FlagForaCerca` é `false` nas quatro — como é nas 875. É esse campo que o
módulo se recusa a usar.
"""
from __future__ import annotations

import pytest

from api.pontocertificado import cliente as pc

# ── corpo real do fornecedor, anonimizado ───────────────────────────────────
_DENTRO = {"Atividade": "", "CPF": "00000000000", "CodigoUnidade": "",
           "DataInsercao": "/Date(1788878781000-0300)/",
           "DataMarcacao": "/Date(1788878766000-0300)/",
           "DescricaoLocal": "TRANSPORTADORA SULISTA TUPY", "FlagForaCerca": False,
           "Formulario": None, "GPSLatitude": "-26.29263026174158",
           "GPSLongitude": "-48.81066178902984", "IdLocal": 8741, "LstRespostas": [],
           "MatriculaFuncionario": "MAT000", "NSR": 277707, "NomeLocal": "TUPY",
           "NumSerieRelogio": "00003.19001.113481", "PIS": "11111111110",
           "RespostaFormulario": None, "TipoRegistro": 1, "TrabalhadorId": 900000,
           "id": 191967000}

_FORA_COM_GPS = {"Atividade": "", "CPF": "00000000001", "CodigoUnidade": "",
                 "DataInsercao": "/Date(1788879658000-0300)/",
                 "DataMarcacao": "/Date(1788879639000-0300)/",
                 "DescricaoLocal": "FORA DE CERCA", "FlagForaCerca": False,
                 "Formulario": None, "GPSLatitude": "-23.73968",
                 "GPSLongitude": "-46.59923666666667", "IdLocal": 0, "LstRespostas": [],
                 "MatriculaFuncionario": "MAT001", "NSR": 277709, "NomeLocal": "",
                 "NumSerieRelogio": "00003.19001.059812", "PIS": "11111111111",
                 "RespostaFormulario": None, "TipoRegistro": 1, "TrabalhadorId": 900001,
                 "id": 191969922}

_SEM_GPS = {"Atividade": "", "CPF": "00000000002", "CodigoUnidade": "",
            "DataInsercao": "/Date(1788878539000-0300)/",
            "DataMarcacao": "/Date(1788878537000-0300)/",
            "DescricaoLocal": "FORA DE CERCA", "FlagForaCerca": False,
            "Formulario": None, "GPSLatitude": "0", "GPSLongitude": "0",
            "IdLocal": 0, "LstRespostas": [], "MatriculaFuncionario": "MAT002",
            "NSR": 277706, "NomeLocal": "", "NumSerieRelogio": "00000.31900.997904",
            "PIS": "11111111112", "RespostaFormulario": None, "TipoRegistro": 1,
            "TrabalhadorId": 900002, "id": 191966584}

_COM_ATIVIDADE = {"Atividade": "INICIO INTERVALO ", "CPF": "00000000003",
                  "CodigoUnidade": "", "DataInsercao": "/Date(1788879653000-0300)/",
                  "DataMarcacao": "/Date(1788879617000-0300)/",
                  "DescricaoLocal": "FORA DE CERCA", "FlagForaCerca": False,
                  "Formulario": None, "GPSLatitude": "0", "GPSLongitude": "0",
                  "IdLocal": 0, "LstRespostas": [], "MatriculaFuncionario": "MAT003",
                  "NSR": 277708, "NomeLocal": "",
                  "NumSerieRelogio": "00003.19001.053202", "PIS": "11111111113",
                  "RespostaFormulario": None, "TipoRegistro": 1,
                  "TrabalhadorId": 900003, "id": 191969786}

# cercas reais: uma CÍRCULO e uma do POLÍGONO (raio "0", várias linhas por IdCerca)
_CERCA_CIRCULO = {"DescricaoCerca": "FILIAL SBC ", "IdCerca": 8758, "IdLocal": 702112,
                  "Latitude": "-23.723233921852056",
                  "Local": "FILIAL SBC - TRANSPORTADORA SULISTA",
                  "Longitude": "-46.60542011260986", "NomeCerca": "FILIAL SBC",
                  "Raio": "25", "StatusCerca": "True", "StatusLocal": "True", "Tipo": "1"}
_CERCA_POLIGONO = {"DescricaoCerca": "SULISTA CRZ / MAXION", "IdCerca": 8756,
                   "IdLocal": 702102, "Latitude": "-22.58274709463008",
                   "Local": "SULISTA CRZ / MAXION", "Longitude": "-44.95861401799927",
                   "NomeCerca": "MAXION CRZ", "Raio": "0", "StatusCerca": "True",
                   "StatusLocal": "True", "Tipo": "2"}
_CERCA_DESLIGADA = {"DescricaoCerca": "SBC ADMINSTRATIVO ", "IdCerca": 8736,
                    "IdLocal": 702067, "Latitude": "-23.550540569309398",
                    "Local": "RUA YAE MASSUMOTO,193, COOPERATIVA",
                    "Longitude": "-46.63314578525006", "NomeCerca": "SBC ADMINSTRATIVO ",
                    "Raio": "40", "StatusCerca": "False", "StatusLocal": "False",
                    "Tipo": "1"}


# ── a situação da batida ────────────────────────────────────────────────────
def test_ausencia_de_GPS_nao_e_estar_fora():
    """53% das batidas não trazem coordenada, e o fornecedor rotula todas de
    "FORA DE CERCA". Tratar isso como infração foi o que encheu o alarme
    antigo: 63% de reprovação, quase toda ela ausência de dado."""
    assert pc.situacao(_SEM_GPS) == pc.SEM_COORDENADA
    assert pc.situacao(_SEM_GPS) != pc.FORA


def test_fora_de_cerca_COM_coordenada_e_fora_de_verdade():
    assert pc.situacao(_FORA_COM_GPS) == pc.FORA


def test_dentro_de_cerca_e_dentro():
    assert pc.situacao(_DENTRO) == pc.DENTRO


def test_o_modulo_NAO_confia_no_FlagForaCerca():
    """O campo é `false` nas 875 marcações medidas — inclusive nas 679 que o
    próprio fornecedor rotula "FORA DE CERCA". Um módulo que lesse o booleano
    publicaria "nenhuma batida fora" para sempre.

    Aqui o dublê tem `FlagForaCerca=False` numa marcação que ESTÁ fora: se
    alguém trocar a leitura para o flag, este teste cai.
    """
    assert _FORA_COM_GPS["FlagForaCerca"] is False
    assert pc.situacao(_FORA_COM_GPS) == pc.FORA


def test_local_vazio_sem_rotulo_tambem_e_fora():
    """Defesa contra o dia em que o fornecedor parar de escrever o rótulo."""
    m = dict(_FORA_COM_GPS, DescricaoLocal="", NomeLocal="")
    assert pc.situacao(m) == pc.FORA


# ── a data do .NET ──────────────────────────────────────────────────────────
def test_data_dotnet_le_o_epoch_e_respeita_o_fuso():
    d = pc.data_dotnet("/Date(1788878766000-0300)/")
    assert d is not None
    assert d.utcoffset().total_seconds() == -3 * 3600
    # o epoch é UTC e NÃO leva o offset somado: somá-lo deslocaria a série
    # inteira em três horas, e continuaria parecendo hora de trabalho.
    assert int(d.timestamp() * 1000) == 1788878766000


def test_data_dotnet_devolve_None_no_lixo():
    for bruto in (None, "", "2026-09-09", "/Date()/"):
        assert pc.data_dotnet(bruto) is None


# ── a normalização ──────────────────────────────────────────────────────────
def test_normalizar_traz_a_coordenada_como_numero_e_so_quando_existe():
    d = pc.normalizar(_DENTRO)
    assert d["lat"] == pytest.approx(-26.29263, abs=1e-4)
    assert d["lon"] == pytest.approx(-48.81066, abs=1e-4)
    s = pc.normalizar(_SEM_GPS)
    assert s["lat"] is None and s["lon"] is None, \
        "coordenada '0' é ausência, e 0,0 é um ponto no golfo da Guiné"


def test_normalizar_mede_a_latencia_da_batida():
    """10 s de mediana medidos: é o que separa este caminho do AFD manual."""
    assert pc.normalizar(_DENTRO)["latencia_s"] == 15
    assert pc.normalizar(_FORA_COM_GPS)["latencia_s"] == 19


def test_atividade_vazia_continua_vazia():
    """65% das marcações não declaram atividade. Preencher com 'entrada' por
    conveniência inventaria jornada."""
    assert pc.normalizar(_DENTRO)["atividade"] is None
    assert pc.normalizar(_COM_ATIVIDADE)["atividade"] == "INICIO INTERVALO"


# ── as cercas ───────────────────────────────────────────────────────────────
def test_poligono_nao_e_circulo_de_raio_zero(monkeypatch):
    """`Tipo` 2 vem com `Raio` "0" e várias linhas por `IdCerca` — cada uma é
    um vértice. Tratar como círculo de raio zero reprova toda batida da
    unidade, que é o que aconteceria com MAXION, VOLVO e MAN REZENDE."""
    monkeypatch.setattr(pc, "cercas_brutas",
                        lambda **k: [_CERCA_CIRCULO, _CERCA_POLIGONO])
    c = {x["nome"]: x for x in pc.cercas()}
    assert c["FILIAL SBC"]["forma"] == "circulo" and c["FILIAL SBC"]["raio_m"] == 25
    assert c["MAXION CRZ"]["forma"] == "poligono"


def test_status_da_cerca_chega_como_TEXTO(monkeypatch):
    """"True"/"False" são strings no corpo do fornecedor. `bool("False")` é
    True — a cerca desligada passaria por ligada."""
    monkeypatch.setattr(pc, "cercas_brutas", lambda **k: [_CERCA_DESLIGADA, _CERCA_CIRCULO])
    c = {x["id_local"]: x for x in pc.cercas()}
    assert c[702067]["ativa"] is False, "cerca com StatusCerca='False' está DESLIGADA"
    assert c[702112]["ativa"] is True


# ── o cursor ────────────────────────────────────────────────────────────────
def test_o_cursor_recusa_ZERO_em_vez_de_devolver_vazio():
    """MEDIDO: `ultIdImportado=0` devolve lista VAZIA, não o histórico. Quem
    chamasse com 0 concluiria "nada novo" e gravaria um cursor que nunca anda —
    a coleta ficaria parada para sempre, sem erro nenhum."""
    with pytest.raises(ValueError, match="id real"):
        pc.marcacoes_desde(0)


def test_marcacoes_desde_normaliza_o_que_vem(monkeypatch):
    monkeypatch.setattr(pc, "_chamar",
                        lambda m, c, **k: [_DENTRO, _SEM_GPS, _FORA_COM_GPS])
    d = pc.marcacoes_desde(191476207)
    assert [x["situacao"] for x in d] == [pc.DENTRO, pc.SEM_COORDENADA, pc.FORA]
    assert d[0]["id"] == 191967000


# ── o que nunca pode vazar ──────────────────────────────────────────────────
def test_a_senha_nunca_sobrevive_ao_saneamento():
    """Ela viaja no CORPO de StartSession: qualquer exceção que carregue o
    pedido a leva para o log."""
    pedido = ('{"chaveEmpresa":"4ecc7623-ebd7-404e-84ac-9bdf7e2e04e4",'
              '"usuario":"alguem@sulista.com.br","senha":"SENHA-SECRETA-123"}')
    limpo = pc._limpar(pedido)
    for segredo in ("SENHA-SECRETA-123", "alguem@sulista.com.br",
                    "4ecc7623-ebd7-404e-84ac-9bdf7e2e04e4"):
        assert segredo not in limpo


def test_o_token_nunca_sobrevive_ao_saneamento():
    token = "md/pq+bTOOl84ss6DR/DcS04KwH34J7Zvy" + "A" * 220
    assert token not in pc._limpar(f'{{"tokenAcesso":"{token}"}}')
    assert token not in pc._limpar("erro ao chamar com " + token)


def test_sem_credencial_o_modulo_DIZ_o_que_falta(monkeypatch):
    """Instalação incompleta não é falha — e a mensagem tem de dizer o nome
    dos campos, senão vira 'não configurado' sem saída."""
    monkeypatch.setattr(pc, "_do_cofre", lambda: None)
    monkeypatch.setattr(pc, "_do_globus", lambda: None)
    assert pc.configurado() is False
    falta = pc.o_que_falta()
    assert "PONTOCERT_CHAVE_EMPRESA" in falta and "PONTOCERT_SENHA" in falta


def test_a_credencial_emprestada_se_declara(monkeypatch):
    """Enquanto não há credencial própria, a do Globus vale — mas a origem
    aparece, para que a troca não seja esquecida."""
    monkeypatch.setattr(pc, "_do_cofre", lambda: None)
    monkeypatch.setattr(pc, "_do_globus",
                        lambda: {"chave": "k", "usuario": "u", "senha": "s",
                                 "origem": "globus"})
    assert pc.credencial()["origem"] == "globus"
    assert pc.diagnostico()["origem_credencial"] == "globus"


def test_o_cofre_tem_precedencia_sobre_o_emprestimo(monkeypatch):
    monkeypatch.setattr(pc, "_do_cofre",
                        lambda: {"chave": "k", "usuario": "u", "senha": "s",
                                 "origem": "cofre"})
    monkeypatch.setattr(pc, "_do_globus",
                        lambda: {"chave": "x", "usuario": "y", "senha": "z",
                                 "origem": "globus"})
    assert pc.credencial()["origem"] == "cofre"


def test_diagnostico_nunca_levanta(monkeypatch):
    """Ele alimenta a Saúde do Servidor: se levantar, derruba o cartão de
    todos os outros junto."""
    def explode(*a, **k):
        raise RuntimeError("token vazado aqui: " + "B" * 250)
    monkeypatch.setattr(pc, "_do_cofre",
                        lambda: {"chave": "k", "usuario": "u", "senha": "s",
                                 "origem": "cofre"})
    monkeypatch.setattr(pc, "versao_api", explode)
    d = pc.diagnostico()
    assert d["configurado"] is True
    assert "B" * 250 not in str(d)
