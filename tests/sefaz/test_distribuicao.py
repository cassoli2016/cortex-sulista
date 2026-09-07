# -*- coding: utf-8 -*-
"""A recolha da SEFAZ: o laco de NSU, e as tres coisas que ele nao pode errar.

DUBLE COPIA O CORPO REAL. Os XML abaixo sao a forma que o servico devolve de
verdade -- `resNFe` com os campos que ele manda (inclusive os que a casa nao
le), `procNFe` com a estrutura de `NFe`+`protNFe`, e o `docZip` em gzip+base64.
Duble com corpo inventado testa o duble.

E os XML sao LITERAIS, escritos aqui: entrada de teste que representa formato
EXTERNO nao se deriva do codigo que vai le-la. Montar o `resNFe` a partir do
proprio `leitura.ESQUEMAS` faria sabotar a constante sabotar junto o que o
teste fabrica, e ele seguiria verde.
"""
from __future__ import annotations

import base64
import gzip
from datetime import datetime, timedelta, timezone

import pytest

from api.sefaz import armazenamento as arm, distribuicao as dist, leitura

CNPJ = "76104397000123"

# ---------------------------------------------------------------- os corpos

RES_NFE = (
    '<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
    '<chNFe>41260912345678000199550010000012341000012349</chNFe>'
    '<CNPJ>12345678000199</CNPJ>'
    '<xNome>METALURGICA EXEMPLO LTDA</xNome>'
    '<IE>1234567890</IE>'
    '<dhEmi>2026-09-05T14:32:00-03:00</dhEmi>'
    '<tpNF>1</tpNF>'
    '<vNF>4821.55</vNF>'
    '<digVal>abc123</digVal>'
    '<dhRecbto>2026-09-05T14:35:12-03:00</dhRecbto>'
    '<nProt>141260000123456</nProt>'
    '<cSitNFe>1</cSitNFe>'
    '</resNFe>')

PROC_NFE = (
    '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
    '<NFe><infNFe Id="NFe41260912345678000199550010000012341000012349" versao="4.00">'
    '<ide><cUF>41</cUF><natOp>VENDA</natOp><mod>55</mod><serie>1</serie>'
    '<nNF>1234</nNF><dhEmi>2026-09-05T14:32:00-03:00</dhEmi></ide>'
    '<emit><CNPJ>12345678000199</CNPJ><xNome>METALURGICA EXEMPLO LTDA</xNome></emit>'
    '<dest><CNPJ>76104397000123</CNPJ><xNome>SULISTA</xNome></dest>'
    '<total><ICMSTot><vNF>4821.55</vNF></ICMSTot></total>'
    '</infNFe></NFe>'
    '<protNFe versao="4.00"><infProt><chNFe>41260912345678000199550010000012341000012349</chNFe>'
    '<nProt>141260000123456</nProt><cStat>100</cStat>'
    '<xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe>'
    '</nfeProc>')

RES_EVENTO = (
    '<resEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">'
    '<cOrgao>41</cOrgao><CNPJ>12345678000199</CNPJ>'
    '<chNFe>41260912345678000199550010000012341000012349</chNFe>'
    '<dhEvento>2026-09-06T09:10:00-03:00</dhEvento>'
    '<tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento>'
    '<xEvento>Cancelamento</xEvento><nProt>141260000999999</nProt>'
    '</resEvento>')


def _zip(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode()


class _Doc:
    """O `docZip` como a biblioteca o entrega: atributos NSU/schema + valor."""

    def __init__(self, nsu, esquema, xml):
        self.NSU = nsu
        self.schema = esquema
        self.value = _zip(xml)


class _Resposta:
    def __init__(self, cstat, motivo, ult, mx, docs):
        self.cStat = cstat
        self.xMotivo = motivo
        self.ultNSU = ult
        self.maxNSU = mx
        self.tpAmb = "1"
        self.verAplic = "1.0"
        self.dhResp = "2026-09-07T10:00:00-03:00"
        self.loteDistDFeInt = type("L", (), {"docZip": docs})()


class _Retorno:
    def __init__(self, resposta):
        self.resposta = resposta


class ClienteFalso:
    """Devolve os lotes na ordem, e REGISTRA o NSU que recebeu.

    O registro e o que permite provar que o ponteiro andou -- sem ele o teste
    afirmaria so o resultado final, e um laco que reconsulta o mesmo NSU
    quarenta vezes daria o mesmo resultado final."""

    def __init__(self, lotes):
        self.lotes = list(lotes)
        self.pedidos = []

    def consultar_distribuicao(self, cnpj_cpf, ultimo_nsu=False, **kw):
        self.pedidos.append(ultimo_nsu)
        return _Retorno(self.lotes.pop(0) if self.lotes
                        else _Resposta("137", "Nenhum documento localizado",
                                       ultimo_nsu, ultimo_nsu, []))


@pytest.fixture
def caixa(esquema_pg, monkeypatch):
    monkeypatch.setattr(arm, "ESQUEMA", esquema_pg)
    arm.abrir_caixa(CNPJ, "FIL MTZ")
    return esquema_pg


# ============================================================= a leitura

def test_o_esquema_decide_o_tipo_e_se_e_completo():
    assert leitura.classificar("resNFe_v1.01") == ("nfe", False)
    assert leitura.classificar("procNFe_v4.00") == ("nfe", True)
    assert leitura.classificar("resEvento_v1.01") == ("evento", False)
    assert leitura.classificar("procEventoNFe_v1.00") == ("evento", True)


def test_o_esquema_casa_por_PREFIXO_e_nao_pela_versao():
    """A SEFAZ versiona no proprio campo. Casar a string inteira quebraria na
    primeira versao nova -- e quebraria em SILENCIO: o documento viraria
    'desconhecido' e sumiria da tela sem erro nenhum."""
    assert leitura.classificar("procNFe_v9.99") == ("nfe", True)


def test_o_que_o_parser_NAO_conhece_continua_guardado():
    """Documento que o parser de hoje nao entende nao pode ser descartado: o
    XML e a obrigacao de cinco anos, e o parser se ensina depois.

    A NF3e (nota de energia eletrica) e o exemplo REAL: ela circula no mesmo
    servico e nao esta em `ESQUEMAS`."""
    d = leitura.ler_documento("procNF3e_v1.00", "<algo>x</algo>")
    assert d["tipo"] == "desconhecido"
    assert d["xml"] == "<algo>x</algo>", "o XML tem de sobreviver"


def test_o_CTe_OS_conta_como_CTe_e_isso_e_de_proposito():
    """`procCTeOS` casa com o prefixo `procCTe` -- e esta certo: CT-e OS e uma
    especie de CT-e, nao um documento de outra familia. O casamento por prefixo
    acerta aqui pelo mesmo motivo que sobrevive a uma versao nova."""
    assert leitura.classificar("procCTeOS_v4.00") == ("cte", True)


def test_le_o_resumo_de_NFe_como_a_SEFAZ_manda():
    d = leitura.ler_documento("resNFe_v1.01", RES_NFE)
    assert d["tipo"] == "nfe" and d["completo"] is False
    assert d["chave"] == "41260912345678000199550010000012341000012349"
    assert d["emitente"] == "12345678000199"
    assert d["emitente_nome"] == "METALURGICA EXEMPLO LTDA"
    assert d["valor"] == 4821.55
    assert d["situacao"] == "1"


def test_le_a_nota_INTEIRA_e_pega_o_emitente_e_nao_o_destinatario():
    """No `procNFe` o CNPJ aparece DUAS vezes: emitente e destinatario. Pegar o
    segundo faria toda nota de entrada parecer emitida pela propria Sulista."""
    d = leitura.ler_documento("procNFe_v4.00", PROC_NFE)
    assert d["completo"] is True
    assert d["emitente"] == "12345678000199", "leu o destinatario no lugar"
    assert d["valor"] == 4821.55


def test_um_documento_torto_NAO_derruba_o_lote():
    """Numa varredura de 4.000, um byte torto no meio nao pode custar a leva."""
    docs = [{"nsu": "1", "esquema": "resNFe_v1.01", "conteudo": _zip(RES_NFE)},
            {"nsu": "2", "esquema": "resNFe_v1.01", "conteudo": "nao-e-base64!!"},
            {"nsu": "3", "esquema": "resEvento_v1.01", "conteudo": _zip(RES_EVENTO)}]
    linhas = leitura.ler_lote(docs)
    assert [l["nsu"] for l in linhas] == ["1", "3"]


# ============================================================ o NSU e texto

@pytest.mark.parametrize("entrada,esperado", [
    ("1", "000000000000001"),
    (12, "000000000000012"),
    ("000000000000100", "000000000000100"),
    ("", "000000000000000"),
    (None, "000000000000000"),
])
def test_o_NSU_e_texto_de_15_digitos(entrada, esperado):
    assert arm.nsu(entrada) == esperado


def test_a_comparacao_de_NSU_so_funciona_com_o_zero_a_esquerda():
    """O motivo de o NSU nunca virar inteiro: `'12' < '100'` e FALSO. Com os
    15 digitos a comparacao de TEXTO acompanha a numerica, e e nela que o
    `greatest` do banco se apoia."""
    assert arm.nsu(12) < arm.nsu(100)
    assert "12" > "100", "se isto mudar, a premissa acima mudou junto"


# ========================================================== o armazenamento

def test_reler_o_mesmo_NSU_nao_duplica(caixa):
    """Reler um trecho e normal. Sem a chave, o total de compras do mes
    dobraria de um jeito PLAUSIVEL."""
    linha = leitura.ler_documento("resNFe_v1.01", RES_NFE)
    linha["nsu"] = "10"
    assert arm.gravar(CNPJ, linha) == "novo"
    assert arm.gravar(CNPJ, linha) == "repetido"
    assert len(arm.documentos(CNPJ)) == 1


def test_o_resumo_vira_documento_completo(caixa):
    """O caminho normal: o `resNFe` chega antes da ciencia, o `procNFe` depois.
    A segunda leitura e um UPGRADE, nao uma duplicata."""
    r = leitura.ler_documento("resNFe_v1.01", RES_NFE)
    r["nsu"] = "10"
    arm.gravar(CNPJ, r)
    assert arm.documentos(CNPJ)[0]["completo"] is False

    p = leitura.ler_documento("procNFe_v4.00", PROC_NFE)
    p["nsu"] = "10"
    assert arm.gravar(CNPJ, p) == "completado"
    d = arm.documentos(CNPJ)[0]
    assert d["completo"] is True
    assert "<nfeProc" in arm.xml_de(CNPJ, "10")


def test_o_resumo_NUNCA_sobrescreve_o_documento_completo(caixa):
    """A regra que protege a obrigacao de cinco anos. Uma releitura anterior a
    manifestacao chegando por cima da posterior APAGARIA o XML da nota -- e
    seria em silencio, com a linha continuando na tela."""
    p = leitura.ler_documento("procNFe_v4.00", PROC_NFE)
    p["nsu"] = "10"
    arm.gravar(CNPJ, p)

    r = leitura.ler_documento("resNFe_v1.01", RES_NFE)
    r["nsu"] = "10"
    assert arm.gravar(CNPJ, r) == "repetido"
    assert arm.documentos(CNPJ)[0]["completo"] is True
    assert "<nfeProc" in arm.xml_de(CNPJ, "10"), "o XML da nota foi PERDIDO"


def test_o_NSU_da_caixa_so_ANDA_PARA_FRENTE(caixa):
    """Uma resposta fora de ordem ou um retry nao pode fazer a varredura andar
    para tras -- seria reler o que ja esta guardado, e ficar em laco."""
    arm.marcar_consulta(CNPJ, ultimo_nsu="500", cstat="138")
    assert arm.caixa(CNPJ)["ultimo_nsu"] == arm.nsu(500)
    arm.marcar_consulta(CNPJ, ultimo_nsu="100", cstat="138")
    assert arm.caixa(CNPJ)["ultimo_nsu"] == arm.nsu(500), "o NSU RECUOU"


def test_reabrir_a_caixa_nao_zera_o_NSU(caixa):
    """Zerar seria reler meses de documento e queimar a cota do servico por um
    clique repetido."""
    arm.marcar_consulta(CNPJ, ultimo_nsu="900", cstat="137")
    arm.abrir_caixa(CNPJ, "FIL MTZ")
    assert arm.caixa(CNPJ)["ultimo_nsu"] == arm.nsu(900)


# ================================================================== o laco

def test_a_varredura_percorre_os_lotes_ate_o_137(caixa):
    cliente = ClienteFalso([
        _Resposta("138", "Documento localizado", "000000000000002",
                  "000000000000004",
                  [_Doc("000000000000001", "resNFe_v1.01", RES_NFE),
                   _Doc("000000000000002", "resEvento_v1.01", RES_EVENTO)]),
        _Resposta("138", "Documento localizado", "000000000000004",
                  "000000000000004",
                  [_Doc("000000000000004", "procNFe_v4.00", PROC_NFE)]),
    ])
    r = dist.recolher(CNPJ, "PR", cliente=cliente)
    assert r["lotes"] == 2 and r["novos"] == 3
    # o PONTEIRO andou: o segundo pedido pediu o que veio DEPOIS do primeiro
    assert cliente.pedidos == ["000000000000000", "000000000000002"]
    assert arm.caixa(CNPJ)["ultimo_nsu"] == "000000000000004"


def test_o_137_e_o_FIM_NORMAL_e_nao_um_erro(caixa):
    """A recolha diaria termina em 137 quase todo dia -- nao ha nota nova
    depois do ultimo NSU. Cartao vermelho ali ensina a ignorar o cartao."""
    cliente = ClienteFalso([_Resposta("137", "Nenhum documento localizado",
                                      "000000000000000", "000000000000000", [])])
    r = dist.recolher(CNPJ, "PR", cliente=cliente)
    assert r["cstat"] == "137" and r["fim_normal"] is True and r["novos"] == 0


def test_o_656_PARA_a_varredura_na_hora(caixa):
    """Consumo indevido e o freio da SEFAZ. Insistir depois dele prolonga o
    bloqueio -- e o bloqueio e por CNPJ."""
    cliente = ClienteFalso([
        _Resposta("138", "Documento localizado", "000000000000001",
                  "000000000000900",
                  [_Doc("000000000000001", "resNFe_v1.01", RES_NFE)]),
        _Resposta("656", "Consumo Indevido", "000000000000001",
                  "000000000000900", []),
    ])
    r = dist.recolher(CNPJ, "PR", cliente=cliente)
    assert r["cstat"] == "656" and r["lotes"] == 2
    assert r["fim_normal"] is False


def test_depois_do_656_a_PROXIMA_varredura_tambem_espera(caixa):
    """ACHADO SABOTANDO, e era defeito de verdade.

    A versao anterior parava o laco no 656 -- e so isso. O freio nosso olhava
    apenas o 137, entao `ultimo_cstat = "656"` nao travava nada: a execucao
    seguinte (a tarefa roda de hora em hora) batia de novo DENTRO do bloqueio
    da SEFAZ, prolongando-o.

    E o `break` do 656 era, sozinho, DECORATIVO: o `!= 138` logo abaixo ja
    parava o laco, entao sabota-lo deixava o teste verde. Guard que nao ficaria
    vermelho nao conferia nada -- foi ele que apontou para ca.
    """
    cliente = ClienteFalso([_Resposta("656", "Consumo Indevido",
                                      "000000000000000", "000000000000900", [])])
    dist.recolher(CNPJ, "PR", cliente=cliente)
    assert arm.caixa(CNPJ)["ultimo_cstat"] == "656"

    r = dist.recolher(CNPJ, "PR", cliente=ClienteFalso([]))
    assert r["lotes"] == 0, "consultou de novo DENTRO do bloqueio da SEFAZ"
    assert r.get("freado") is True
    assert r["esperar_min"] >= 60, (
        "a espera depois do freio DELES tem de ser maior que a nossa: %r"
        % r.get("esperar_min"))


def test_ponteiro_que_nao_anda_NAO_vira_laco_infinito(caixa):
    """Acontece de verdade: 138 com o mesmo ultNSU quando o lote so traz
    documento que nao descomprime. Sem a guarda seriam 40 chamadas identicas e
    um 656 na cara."""
    parado = _Resposta("138", "Documento localizado", "000000000000000",
                       "000000000000900",
                       [_Doc("000000000000001", "resNFe_v1.01", "nao-zipado")])
    cliente = ClienteFalso([parado] * 50)
    r = dist.recolher(CNPJ, "PR", cliente=cliente)
    assert r["lotes"] == 1, "consultou %d vezes com o NSU parado" % r["lotes"]


def test_alcancar_o_maxNSU_encerra_sem_mais_uma_chamada(caixa):
    """`maxNSU` e o maior que EXISTE. Alcancado, mais uma chamada so serviria
    para ouvir 137 -- e e consulta sem resultado, que e o que o 656 pune."""
    cliente = ClienteFalso([
        _Resposta("138", "Documento localizado", "000000000000007",
                  "000000000000007",
                  [_Doc("000000000000007", "resNFe_v1.01", RES_NFE)]),
    ])
    r = dist.recolher(CNPJ, "PR", cliente=cliente)
    assert r["lotes"] == 1 and len(cliente.pedidos) == 1


def test_o_NSU_e_gravado_a_CADA_lote_e_nao_no_fim(caixa):
    """Uma primeira varredura tem dezenas de lotes. Se o NSU so fosse gravado
    no fim, uma queda no meio faria tudo recomecar do zero na proxima -- que e
    exatamente o padrao de consulta que o 656 pune."""
    class Explode(ClienteFalso):
        def consultar_distribuicao(self, cnpj_cpf, ultimo_nsu=False, **kw):
            if len(self.pedidos) == 1:
                raise RuntimeError("a rede caiu no meio da varredura")
            return super().consultar_distribuicao(cnpj_cpf, ultimo_nsu, **kw)

    cliente = Explode([
        _Resposta("138", "Documento localizado", "000000000000003",
                  "000000000000900",
                  [_Doc("000000000000003", "resNFe_v1.01", RES_NFE)]),
    ])
    with pytest.raises(RuntimeError):
        dist.recolher(CNPJ, "PR", cliente=cliente)
    assert arm.caixa(CNPJ)["ultimo_nsu"] == "000000000000003", (
        "a queda no meio perdeu o progresso do primeiro lote")


# ================================================================= o freio

def test_nao_reconsulta_em_seguida_quando_a_ultima_deu_137(caixa):
    """O freio NOSSO vem antes do deles: a SEFAZ pune consulta repetida sem
    resultado, e o castigo dura ~1 h por CNPJ."""
    cliente = ClienteFalso([_Resposta("137", "Nenhum documento localizado",
                                      "000000000000000", "000000000000000", [])])
    dist.recolher(CNPJ, "PR", cliente=cliente)
    r = dist.recolher(CNPJ, "PR", cliente=ClienteFalso([]))
    assert "pulou" in r and r["lotes"] == 0


def test_o_freio_NAO_vale_quando_a_varredura_parou_com_documento(caixa):
    """O freio so vale quando a ultima varredura terminou em 137 -- "nao ha
    nada novo". Se ela parou AINDA COM DOCUMENTO (por teto de lotes, ou porque
    alcancou o maxNSU do lote), continuar e o certo e a SEFAZ nao reclama.

    E foi este teste que arrumou a REGRA, nao o contrario: a primeira versao
    dele supunha "trouxe documento => sem freio", e a varredura que DRENA a
    caixa termina em 137 justamente por ter drenado. Frear depois dela esta
    certo -- consultar de novo em cinco minutos seria consulta sem resultado,
    que e o que o 656 pune."""
    cliente = ClienteFalso([
        _Resposta("138", "Documento localizado", "000000000000002",
                  "000000000000002",   # alcancou o maxNSU: para COM 138
                  [_Doc("000000000000002", "resNFe_v1.01", RES_NFE)]),
    ])
    dist.recolher(CNPJ, "PR", cliente=cliente)
    assert arm.caixa(CNPJ)["ultimo_cstat"] == "138"

    r = dist.recolher(CNPJ, "PR", cliente=ClienteFalso([
        _Resposta("138", "Documento localizado", "000000000000003",
                  "000000000000003",
                  [_Doc("000000000000003", "resEvento_v1.01", RES_EVENTO)])]))
    assert r["lotes"] == 1 and "pulou" not in r


def test_a_varredura_que_DRENOU_a_caixa_e_freada(caixa):
    """O outro lado da mesma regra, e o caso comum: recolheu tudo, ouviu 137, e
    a proxima chamada em seguida seria consulta sem resultado."""
    cliente = ClienteFalso([
        _Resposta("138", "Documento localizado", "000000000000001",
                  "000000000000900",
                  [_Doc("000000000000001", "resNFe_v1.01", RES_NFE)]),
    ])   # o duble cai no 137 quando acabam os lotes, como a SEFAZ
    r1 = dist.recolher(CNPJ, "PR", cliente=cliente)
    assert r1["cstat"] == "137" and r1["novos"] == 1
    r2 = dist.recolher(CNPJ, "PR", cliente=ClienteFalso([]))
    assert "pulou" in r2 and r2["lotes"] == 0


def test_forcar_passa_por_cima_do_freio_nosso(caixa):
    cliente = ClienteFalso([_Resposta("137", "Nenhum documento localizado",
                                      "000000000000000", "000000000000000", [])])
    dist.recolher(CNPJ, "PR", cliente=cliente)
    r = dist.recolher(CNPJ, "PR", cliente=ClienteFalso([]), forcar=True)
    assert r["lotes"] == 1


# ============================================================= o certificado

def test_sem_certificado_a_mensagem_DIZ_O_QUE_FAZER(caixa):
    """Instalacao incompleta nao e falha: e "falta um passo", e o erro tem de
    dizer QUAL."""
    with pytest.raises(dist.SemCertificado) as e:
        dist._certificado("00000000000000")
    assert "cadastrar_certificado" in str(e.value)


# ================================== os defeitos da biblioteca, medidos

def test_o_binding_da_distribuicao_EXISTE_e_nao_sumiu_em_silencio():
    """O defeito mais caro desta integracao, e o mais silencioso.

    `erpbrasil.edoc.nfe` importa os bindings legados dentro de
    `with suppress(ImportError)`. Eles fazem `from six.moves import
    zip_longest`, e sem o `six` o import NAO da erro: ele apaga os nomes
    `distDFeInt`, `retDistDFeInt` e uma duzia de outros, em silencio. A falha
    aparece muito depois, no meio da consulta:

        NameError: name 'distDFeInt' is not defined

    O `six` esta em `[project.dependencies]` por causa disto. Este guard existe
    porque um `uv sync` que o deixe cair NAO quebra nenhum import -- quebra a
    recolha de NF, e so na hora de recolher.
    """
    import erpbrasil.edoc.nfe as n
    faltando = [nome for nome in ("distDFeInt", "retDistDFeInt")
                if not hasattr(n, nome)]
    assert not faltando, (
        "%s sumiu de erpbrasil.edoc.nfe -- quase certamente o `six` nao esta "
        "instalado (o modulo engole o ImportError e apaga o nome). "
        "`uv sync` com o pyproject atual resolve." % faltando)


def test_a_sigla_da_UF_vira_o_CODIGO_IBGE():
    """`NFe(...)` quer o NUMERO. Com a sigla, `int('PR')` estoura la dentro do
    construtor da biblioteca, com uma mensagem que nao fala de UF nenhuma."""
    assert dist.codigo_uf("PR") == 41
    assert dist.codigo_uf("sp") == 35
    with pytest.raises(ValueError):
        dist.codigo_uf("XX")


def test_a_versao_da_distribuicao_NAO_e_a_da_NFe():
    """MEDIDO contra o servico real em 07/09/2026: com a versao "4.00" (que e a
    que `NFe.versao` traz de fabrica, e que `consultar_distribuicao` copia para
    dentro do pedido) a SEFAZ responde

        239 · Rejeicao: Cabecalho - Versao do arquivo XML nao suportada

    -- mensagem que fala de "cabecalho" e manda procurar no SOAP, onde nao
    esta. O schema da distribuicao e 1.01."""
    assert dist.VERSAO_DISTRIBUICAO == "1.01"


def test_uma_REJEICAO_nao_faz_o_ponteiro_pular(caixa):
    """ACHADO EM PRODUCAO, na segunda chamada real (07/09/2026).

    Numa rejeicao 656 a SEFAZ devolve `ultNSU` -- e ele NAO e o que consumimos,
    e onde a sequencia dela esta. O `greatest()` do banco o gravou como se
    fosse progresso, e o ponteiro da matriz saltou de 0 para 1.144.010 sozinho:
    tres meses de historico pulados em silencio, numa integracao cuja razao de
    existir e a guarda de cinco anos.

    Pular historico e decisao de quem opera. O numero nao se perde -- vai para
    `max_nsu`, que e o que ele de fato e.
    """
    cliente = ClienteFalso([_Resposta("656", "Consumo Indevido (Deve ser "
                                      "utilizado o ultNSU nas solicitacoes "
                                      "subsequentes)",
                                      "000000001144010", "000000000000000", [])])
    dist.recolher(CNPJ, "PR", cliente=cliente)
    c = arm.caixa(CNPJ)
    assert c["ultimo_nsu"] == "000000000000000", (
        "o ponteiro PULOU numa rejeicao: %s" % c["ultimo_nsu"])
    assert c["max_nsu"] == "000000001144010", (
        "o fim da sequencia se perdeu -- e dele que sai o 'quanto falta'")


def test_o_137_tambem_nao_faz_o_ponteiro_pular(caixa):
    """Mesma regra, outro codigo: no 137 a SEFAZ ecoa o NSU que pedimos. Hoje
    isso e inofensivo (ecoa o mesmo), mas a regra e "so anda com documento" --
    e uma regra que vale por acidente em um dos casos nao e regra."""
    arm.marcar_consulta(CNPJ, ultimo_nsu="000000000000500", cstat="138")
    cliente = ClienteFalso([_Resposta("137", "Nenhum documento localizado",
                                      "000000000000900", "000000000000900", [])])
    dist.recolher(CNPJ, "PR", cliente=cliente, forcar=True)
    assert arm.caixa(CNPJ)["ultimo_nsu"] == "000000000000500"
