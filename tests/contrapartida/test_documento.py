# tests/contrapartida/test_documento.py
"""Montagem do CT-e de contrapartida — esqueleto.

Nenhum destes testes vai a rede nem ao banco: o dado do ERP entra por um
dicionario fabricado, com os MESMOS valores medidos no CT-e real usado como
piloto (Parizotto, chave ...3585231063585236). O que se testa aqui e o que o
modulo promete: nao assina, nao transmite, nao inventa codigo de municipio e
nao monta documento nenhum sem alguem ter respondido o enquadramento fiscal.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import os
from decimal import Decimal

import pytest

from api.contrapartida import documento as doc

# Espelha o CT-e piloto. Os acentos sao os da tabela oficial (`cidade_ibge`),
# nao os do cadastro do ERP — a diferenca e justamente o assunto de `ibge()`.
DADOS = {
    "chave_original": "35260876104397000204570010003585231063585236",
    "emit_cnpj": "46929365000104", "emit_nome": "RODRIGO ANTONIO PARIZOTTO",
    "emit_fantasia": "RODRIGO ANTONIO PARIZOTTO - PJ",
    "emit_ie": "121511158112", "emit_rntrc": "55520266",
    "emit_logradouro": "RUA BETÂNIA", "emit_numero": 618,
    "emit_complemento": "CASA", "emit_bairro": "PARQUE ORATORIO",
    "emit_cidade": "SANTO ANDRE", "emit_uf": "SP", "emit_cep": 9280200,
    "emit_cep8": "09280200", "emit_cmun": 3547809, "emit_xmun": "SANTO ANDRÉ",
    "emit_ddd": "11", "emit_fone": "83891398", "emit_optante_simples": 1,
    "toma_cnpj": "76104397000204", "toma_apelido": "FIL  S.B. DO CAMPO",
    "toma_ie": "635518020110", "toma_logradouro": "ESTRADA DOS ALVARENGAS",
    "toma_numero": 6025, "toma_complemento": None, "toma_bairro": "ASSUNCAO",
    "toma_cidade": "SAO BERNARDO DO CAMPO", "toma_uf": "SP",
    "toma_cep": 9550850, "toma_cep8": "09550850",
    "ufcoleta": "SP", "cidadecoleta": "SAO BERNARDO DO CAMPO",
    "ini_cmun": 3548708, "ini_xmun": "SÃO BERNARDO DO CAMPO",
    "ufentrega": "SP", "cidadeentrega": "TAUBATE",
    "fim_cmun": 3554102, "fim_xmun": "TAUBATÉ",
    "valortotalprestacao": Decimal("1494.02"),
    "valorfretecompra": Decimal("1066.32"),
    "valortotalmercadoria": Decimal("8610.00"),
    "pesobruto": Decimal("2860.500"), "kmfrete": Decimal("167.81"),
    "embarque": 176247, "documentos_no_embarque": 1, "exige_rateio": False,
    # Remetente e destinatario da CARGA, copiados do CT-e da Sulista. Sem eles
    # a SEFAZ recusa com cStat 469 — descoberto na transmissao, nao no schema.
    "rem_cnpj": "13260523000380",
    "rem_nome": "FAURECIA AUTOMOTIVE INTERIORS BRAZIL LTDA.",
    "rem_ie": "635310175117", "rem_logradouro": "AVENIDA SENADOR VERGUEIRO",
    "rem_numero": 1850, "rem_complemento": None, "rem_bairro": "RUDGE RAMOS",
    "rem_cidade": "SAO BERNARDO DO CAMPO", "rem_uf": "SP",
    "rem_cep": 9750000, "rem_cep8": "09750000",
    "rem_cmun": 3548708, "rem_xmun": "SÃO BERNARDO DO CAMPO",
    "dest_cnpj": "56413990000144",
    "dest_nome": "FABINJECT INDUSTRIA PLASTICA LTDA",
    "dest_ie": "688089115115", "dest_logradouro": "RUA JOSE BENEDITO",
    "dest_numero": 120, "dest_complemento": None, "dest_bairro": "CENTRO",
    "dest_cidade": "TAUBATE", "dest_uf": "SP",
    "dest_cep": 12070000, "dest_cep8": "12070000",
    "dest_cmun": 3554102, "dest_xmun": "TAUBATÉ",
    # As duas NF-e transportadas. cStat 693 sem elas.
    "notas": [
        {"chave": "35260813260523000380550010000386111348217198",
         "modelo": "55", "numero": 38611},
        {"chave": "35260813260523000380550010000386091149290547",
         "modelo": "55", "numero": 38609},
    ],
    "notas_sem_chave": [],
    # IBS/CBS: obrigatorio desde 26/08/2026 (cStat 310 sem ele). CST,
    # classificacao e aliquotas vem do ERP. O IBS-UF aqui esta com 0,1 porque
    # o cadastro real ainda esta zerado e a SEFAZ recusa zero (316) - o valor
    # do ERP entra quando o imposto for configurado.
    "ibs_cst": "000", "ibs_classtrib": "000001",
    "ibs_p_uf": Decimal("0.1"), "ibs_p_mun": None, "cbs_p": Decimal("0.9"),
}

# Enquadramento de TESTE. Nao e definicao fiscal — serve so para exercitar a
# montagem. Trocar por decisao da contabilidade quando ela vier.
ENQ = doc.Enquadramento(cfop_interno="5351", cfop_interestadual="6351",
                        criterio_rateio="cobrado",
                        tp_serv="1", grupo_icms="ICMSSN",
                        cst_icms="90", p_icms=None, base_valor="fretecompra",
                        toma="4", referenciar_original=True)


# --- as guardas ------------------------------------------------------------

def test_nao_assina_e_nao_transmite():
    """Guarda de arvore sintatica, igual a de `servico.py`: montar o XML e
    uma coisa, assinar como terceiro e outra, e a segunda nao mora aqui."""
    with open(doc.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    nomes = {n.attr for n in ast.walk(arvore) if isinstance(n, ast.Attribute)}
    nomes |= {n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)}
    assert not (nomes & {"assinar", "transmitir", "sign", "Certificado",
                         "TransmissaoSOAP", "envia_documento", "post"})


def test_producao_nao_tem_atalho():
    """Mesma regra de `sefaz.py`: ambiente e decisao de quem chama."""
    assert inspect.signature(doc.montar).parameters["ambiente"].default == "2"
    assert not hasattr(doc, "PRODUCAO")


def test_enquadramento_nao_tem_UM_valor_padrao():
    """O ponto do dataclass: nao existe caminho de codigo que monte um CT-e
    sem as seis respostas. Um default aqui seria um chute virando documento."""
    for campo in dataclasses.fields(doc.Enquadramento):
        assert campo.default is dataclasses.MISSING, campo.name
        assert campo.default_factory is dataclasses.MISSING, campo.name


def test_tp_serv_do_SCHEMA_e_nao_o_codigo_do_ERP():
    """O ERP guarda `tiposervico` em base 1 (1=normal, 2=subcontratacao) e o
    schema em base 0. Passar o codigo do ERP direto emitiria subcontratacao
    rotulada como normal — e o '5' do ERP nem existe no schema."""
    with pytest.raises(ValueError, match="base 1"):
        dataclasses.replace(ENQ, tp_serv="5")


def test_grupo_de_icms_com_aliquota_obrigatoria():
    with pytest.raises(ValueError, match="alíquota"):
        dataclasses.replace(ENQ, grupo_icms="ICMS00", cst_icms="00",
                            p_icms=None)


def test_base_de_valor_so_aceita_as_duas_conhecidas():
    with pytest.raises(ValueError, match="base_valor"):
        dataclasses.replace(ENQ, base_valor="media")


# --- o dado do ERP ---------------------------------------------------------

def test_cep_do_erp_e_inteiro_e_perde_o_zero():
    """`9280200` e Santo Andre com o zero comido pelo tipo numerico. Em SP
    isso vale para o estado inteiro; 7 digitos e rejeicao de schema."""
    assert doc.cep(9280200) == "09280200"
    assert doc.cep("09280200") == "09280200"
    assert doc.cep(9550850) == "09550850"


def test_cep_ausente_nao_vira_zeros():
    for vazio in (None, "", 0):
        with pytest.raises(ValueError, match="CEP ausente"):
            doc.cep(vazio)


def test_ibge_casa_sem_acento_e_devolve_a_grafia_OFICIAL(monkeypatch):
    """O cadastro grava SANTO ANDRE e a tabela oficial SANTO ANDRÉ. Quem vai
    no XML e a oficial: `cMun` e `xMun` tem de descrever o mesmo municipio."""
    chamada = {}

    def falso(sql, params):
        chamada.update(params)
        return [{"codigoibge": 3547809, "municipio": "SANTO ANDRÉ"}]

    monkeypatch.setattr(doc.db, "query", falso)
    codigo, nome = doc.ibge("sp", " SANTO  ANDRE ")
    assert (codigo, nome) == (3547809, "SANTO ANDRÉ")
    assert chamada == {"uf": "SP", "cidade": "SANTO ANDRE"}


def test_municipio_sem_ibge_LEVANTA_em_vez_de_chutar(monkeypatch):
    """Codigo de municipio identifica a prestacao. Chutar seria emitir um
    documento que fecha no schema e mente sobre onde o frete aconteceu."""
    monkeypatch.setattr(doc.db, "query", lambda *a, **k: [])
    with pytest.raises(ValueError, match="ITAQUAQUECETUBA/SP"):
        doc.ibge("SP", "ITAQUAQUECETUBA")


# --- o valor ---------------------------------------------------------------

def test_as_duas_bases_dao_numeros_DIFERENTES():
    """R$ 1.494,02 e o que a Sulista cobrou do cliente; R$ 1.066,32 e o que
    ela paga ao agregado. Sao 71,4% um do outro — nao da para confundir."""
    assert doc.valor(DADOS, ENQ) == Decimal("1066.32")
    assert doc.valor(DADOS, dataclasses.replace(
        ENQ, base_valor="prestacao")) == Decimal("1494.02")


def test_rateio_por_valor_cobrado_reproduz_a_viagem_real():
    """Viagem 169646: R$ 3.398,36 pagos, TRES CT-e cobrados a 1.156,00,
    4.661,35 e 2.675,53. Pelo criterio decidido (valor cobrado), as fatias
    sao 462,56 / 1.865,20 / 1.070,59 — conferidas contra a base."""
    viagem = {"valorfretecompra": Decimal("3398.36"),
              "documentos_no_embarque": 3, "exige_rateio": True,
              "prestacao_do_embarque": 8492.88, "embarque": 169646}
    esperado = {"1156.00": "462.56", "4661.35": "1865.20",
                "2675.53": "1070.59"}
    for cobrado, fatia in esperado.items():
        d = dict(DADOS, **viagem, valortotalprestacao=Decimal(cobrado))
        assert doc.valor(d, ENQ) == Decimal(fatia), cobrado


def test_documento_sozinho_na_viagem_leva_o_valor_INTEIRO():
    """52% dos CT-e sao o unico documento da viagem: fator 1, sem divisao."""
    assert doc.fator_rateio(DADOS, ENQ) == 1
    assert doc.valor(DADOS, ENQ) == Decimal("1066.32")


def test_a_base_prestacao_nao_rateia_nunca():
    """Se a base for o valor cobrado do cliente, cada CT-e ja tem o seu — o
    rateio deixa de existir mesmo com varios documentos na viagem."""
    d = dict(DADOS, documentos_no_embarque=3, exige_rateio=True,
             prestacao_do_embarque=8492.88)
    enq = dataclasses.replace(ENQ, base_valor="prestacao")
    assert doc.valor(d, enq) == Decimal("1494.02")


def test_prestacao_zero_na_viagem_PARA_em_vez_de_dividir_por_zero():
    d = dict(DADOS, documentos_no_embarque=2, exige_rateio=True,
             prestacao_do_embarque=0)
    with pytest.raises(ValueError, match="prestação total zero"):
        doc.valor(d, ENQ)


def test_documento_com_prestacao_zero_nao_recebe_fatia_zero():
    """Pelo criterio, ele receberia R$ 0,00 — e documento fiscal de valor
    zero nao e prestacao. Para e avisa."""
    d = dict(DADOS, documentos_no_embarque=2, exige_rateio=True,
             prestacao_do_embarque=1000.0,
             valortotalprestacao=Decimal("0"))
    with pytest.raises(ValueError, match="prestação zero"):
        doc.valor(d, ENQ)


def test_o_criterio_e_explicito_e_os_outros_nao_entram_por_engano():
    """Os quatro criterios fecham a soma; o que muda e quanto imposto cada
    documento carrega. Trocar tem de ser decisao, nao conveniencia."""
    assert doc.CRITERIOS_RATEIO == ("cobrado",)
    for outro in ("peso", "mercadoria", "iguais"):
        with pytest.raises(ValueError, match="criterio_rateio"):
            dataclasses.replace(ENQ, criterio_rateio=outro)


def test_sem_frete_de_compra_a_base_nao_cai_para_zero():
    d = dict(DADOS, valorfretecompra=None)
    with pytest.raises(ValueError, match="frete de compra"):
        doc.valor(d, ENQ)


# --- o XML -----------------------------------------------------------------

def _xsd():
    """Caminho do XSD, ou "" se o grupo `fiscal` nao estiver instalado.

    O `skipif` e avaliado na COLETA, entao um `import nfelib` cru aqui derruba
    a suite INTEIRA (erro de coleta, nao skip) em qualquer ambiente sem o
    grupo — e producao e exatamente isso: o AutoDeploy roda `uv sync` sem
    grupo nenhum, de proposito.
    """
    try:
        import nfelib
    except ImportError:
        return ""
    return os.path.join(os.path.dirname(nfelib.__file__), "cte", "schemas",
                        "v4_0", "cte_v4.00.xsd")


# Montar o XML exige o grupo `fiscal`, que producao NAO instala. Sem este
# marcador a suite fica vermelha no servidor por dependencia ausente de
# proposito — e alarme falso recorrente e alarme que ninguem le.
precisa_fiscal = pytest.mark.skipif(
    not _xsd(), reason="grupo `fiscal` ausente (uv sync --group fiscal)")


@pytest.mark.skipif(not os.path.exists(_xsd()), reason="XSD do CT-e ausente")
def test_o_xml_valida_no_XSD_oficial_menos_a_assinatura():
    """O unico erro aceito e a Signature faltando — e ela falta de proposito.
    Qualquer outro erro aqui e campo obrigatorio que o esqueleto esqueceu."""
    from lxml import etree

    xml = doc.serializar(doc.montar(DADOS, ENQ, numero=1))
    schema = etree.XMLSchema(etree.parse(_xsd()))
    schema.validate(etree.fromstring(xml.encode("utf-8")))
    erros = [e.message for e in schema.error_log]
    assert len(erros) == 1, erros
    assert "Signature" in erros[0]


@precisa_fiscal
def test_homologacao_carimba_REMETENTE_e_DESTINATARIO_e_nao_o_tomador():
    """Custou tres rejeicoes descobrir de quem e o nome.

    646 fala do REMETENTE e 649 do DESTINATARIO; o tomador conserva o nome
    real. A aposta inicial (carimbar o tomador) dava exatamente a mesma
    rejeicao de nao carimbar ninguem, o que faz a tentativa parecer sem
    efeito.
    """
    xml = doc.serializar(doc.montar(DADOS, ENQ, numero=1, ambiente="2"))
    assert xml.count(doc.XNOME_HOMOLOGACAO) == 2, "remetente E destinatario"
    assert DADOS["rem_nome"] not in xml and DADOS["dest_nome"] not in xml
    assert "FIL S.B. DO CAMPO" in xml, "o tomador mantem o nome real"


def test_a_grafia_do_nome_de_homologacao_e_CTE_sem_hifen():
    """A SEFAZ compara caractere a caractere, e no CT-e a grafia e `CTE`, nao
    o `CT-E` que a NF-e usa. Com o hifen leva 646 — a MESMA rejeicao de nao
    ter carimbado nada."""
    assert doc.XNOME_HOMOLOGACAO.startswith("CTE EMITIDO")
    assert "CT-E" not in doc.XNOME_HOMOLOGACAO


@precisa_fiscal
def test_producao_nao_carimba_nome_nenhum():
    """O carimbo e do ambiente de teste: em producao os nomes sao os reais."""
    xml = doc.serializar(doc.montar(DADOS, ENQ, numero=1, ambiente="1"))
    assert doc.XNOME_HOMOLOGACAO not in xml
    assert DADOS["rem_nome"] in xml and DADOS["dest_nome"] in xml


@precisa_fiscal
def test_as_notas_transportadas_entram_todas():
    """O CT-e piloto carrega DUAS notas — nunca foi campo unico."""
    xml = doc.serializar(doc.montar(DADOS, ENQ, numero=1))
    for n in DADOS["notas"]:
        assert n["chave"] in xml
    assert xml.count("<infNFe>") == 2


@precisa_fiscal
def test_sem_nota_com_chave_para_ANTES_de_transmitir():
    """cStat 693. O XSD deixa o grupo OPCIONAL, entao a validacao local passa
    e so a SEFAZ reclama — vale parar antes e dizer o porque."""
    d = dict(DADOS, notas=[], notas_sem_chave=[{"chave": None}])
    with pytest.raises(ValueError, match="Documentos Transportados"):
        doc.montar(d, ENQ, numero=1)


@precisa_fiscal
def test_a_referencia_ao_CT_e_da_sulista_e_o_que_faz_ser_contrapartida():
    """Sem `docAnt` o documento e uma prestacao solta: nada o liga ao CT-e
    que a Sulista ja emitiu, que e a razao de existir do modulo."""
    com = doc.serializar(doc.montar(DADOS, ENQ, numero=1))
    assert DADOS["chave_original"] in com and "<docAnt>" in com
    sem = doc.serializar(doc.montar(
        DADOS, dataclasses.replace(ENQ, referenciar_original=False), numero=1))
    assert DADOS["chave_original"] not in sem


@precisa_fiscal
def test_rntrc_ausente_para_ANTES_de_montar():
    """Sem RNTRC o modal rodoviario e rejeitado documento a documento — com
    3 mil CT-e por mes, esse erro some no meio do lote."""
    d = dict(DADOS, emit_rntrc=None)
    with pytest.raises(ValueError, match="RNTRC"):
        doc.montar(d, ENQ, numero=1)


@precisa_fiscal
def test_simples_nacional_nao_destaca_icms():
    xml = doc.serializar(doc.montar(DADOS, ENQ, numero=1))
    assert "<ICMSSN>" in xml and "<CRT>1</CRT>" in xml
    assert "<vICMS>" not in xml


# --- a transmissao (sem rede) ----------------------------------------------

def test_o_qrcode_e_montado_ANTES_de_transmitir():
    """cStat 850 sem ele. E a ordem importa: o QR e campo do documento, entao
    tem de existir antes da assinatura — depois dela o hash nao fecha."""
    from api.contrapartida import emissao
    src = open(emissao.__file__.replace(".pyc", ".py"),
               encoding="utf-8").read()
    assert src.index("monta_qrcode") < src.index("envia_documento(edoc)")


def test_producao_esta_fechada_na_transmissao():
    """Enquanto o enquadramento fiscal for chute, producao nao abre — e a
    recusa e explicita, com a razao no erro."""
    import inspect

    from api.contrapartida import emissao
    assert inspect.signature(
        emissao.transmitir).parameters["ambiente"].default == "2"
    fonte = inspect.getsource(emissao._guardas)
    assert "PermissionError" in fonte and "HOMOLOGA" in fonte.upper()


def test_numeracao_e_por_ambiente():
    """Homologacao e producao tem numeracao independente: misturar faria o
    primeiro CT-e de producao nascer com o numero gasto num teste."""
    import inspect

    from api.contrapartida import emissao
    fonte = inspect.getsource(emissao.proximo_numero)
    assert "ambiente=?" in fonte


# --- o que a SEFAZ recusa por REGRA, medido em homologacao ------------------

def test_prestacao_normal_nao_aceita_tomador_OUTROS():
    """Rejeicao 746. A consequencia e de negocio, nao de schema: em prestacao
    normal o tomador tem de ser parte da carga, entao o documento sairia
    contra o CLIENTE e nao contra a Sulista."""
    with pytest.raises(ValueError, match="746"):
        dataclasses.replace(ENQ, tp_serv="0", toma="4",
                            referenciar_original=False)


def test_prestacao_normal_nao_aceita_vinculo_com_o_CT_e_anterior():
    """Rejeicao 747. Sem o vinculo, NADA no documento o liga ao CT-e da
    Sulista — que e a razao de existir do modulo."""
    with pytest.raises(ValueError, match="747"):
        dataclasses.replace(ENQ, tp_serv="0", toma="0",
                            referenciar_original=True)


def test_prestacao_normal_com_tomador_da_carga_e_valida():
    """As duas combinacoes que a SEFAZ AUTORIZOU (cStat 100) continuam
    montaveis: o que a guarda barra e so o que o orgao recusa."""
    for toma in ("0", "3"):
        dataclasses.replace(ENQ, tp_serv="0", toma=toma,
                            referenciar_original=False)


def test_subcontratacao_com_tomador_outros_e_vinculo_continua_valida():
    """E a combinacao que autorizou de verdade, protocolo 135260006358665."""
    dataclasses.replace(ENQ, tp_serv="1", toma="4", referenciar_original=True)


def test_a_serie_padrao_e_reservada_e_nao_a_1():
    """Serie 900, aprovada pela area. Serie baixa colidiria com o que o
    agregado ja emita por conta propria — e numero repetido e rejeitado
    documento a documento, no meio de um lote de milhares."""
    import inspect

    from api.contrapartida import emissao
    assert emissao.SERIE_PADRAO == 900
    assert inspect.signature(
        emissao.transmitir).parameters["serie"].default == emissao.SERIE_PADRAO


def test_o_cfop_segue_o_TRECHO_e_nao_e_fixo():
    """Emitente em SP. Comecando em SP: 5351 no mesmo estado, 6351 cruzando
    divisa. Um CFOP fixo erraria a maioria dos documentos."""
    assert ENQ.cfop_de(DADOS) == "5351", "SP -> SP, emitente SP"
    assert ENQ.cfop_de(dict(DADOS, ufentrega="MG")) == "6351"
    assert ENQ.cfop_de(dict(DADOS, ufcoleta="sp", ufentrega=" SP ")) == "5351"


def test_viagem_que_COMECA_fora_da_UF_do_emitente_usa_a_familia_932():
    """Rejeicao 524 — "CFOP invalido, informar 5932 ou 6932". A pergunta vem
    ANTES do trecho, e o caso e a MAIORIA (3.694 de 6.366 no trimestre): o
    agregado mora num estado e roda em todos. No documento da Sulista isso nao
    aparece, porque a filial emitente e sempre a da origem."""
    assert ENQ.cfop_de(dict(DADOS, ufcoleta="MG", ufentrega="SP")) == "6932"
    assert ENQ.cfop_de(dict(DADOS, ufcoleta="MG", ufentrega="MG")) == "5932"
    # emitente MG saindo de MG volta para a familia normal
    assert ENQ.cfop_de(dict(DADOS, emit_uf="MG", ufcoleta="MG",
                            ufentrega="SP")) == "6351"


def test_a_familia_932_nao_e_escolha_de_ninguem():
    """Nao entra no Enquadramento: a SEFAZ nomeia os dois codigos na propria
    recusa. Deixar isso como campo sugeriria que ha o que decidir."""
    assert doc.CFOP_INICIO_EM_OUTRA_UF == {True: "5932", False: "6932"}
    assert not any("932" in getattr(ENQ, c.name)
                   for c in dataclasses.fields(doc.Enquadramento)
                   if isinstance(getattr(ENQ, c.name), str))


def test_cfop_trocado_entre_interno_e_interestadual_e_recusado():
    """A SEFAZ ACEITA o documento com o CFOP do trecho errado — quem reclama e
    a fiscalizacao, meses depois. Por isso a guarda e nossa."""
    with pytest.raises(ValueError, match="interno começa com 5"):
        dataclasses.replace(ENQ, cfop_interno="6351", cfop_interestadual="5351")


def test_cfop_precisa_ter_quatro_digitos():
    with pytest.raises(ValueError, match="4 dígitos"):
        dataclasses.replace(ENQ, cfop_interno="535")


# --- tributacao vinda do ERP (grupo_icms AUTO) ------------------------------

AUTO = dataclasses.replace(ENQ, grupo_icms="AUTO", cst_icms="", p_icms=None)


def test_optante_do_simples_nao_destaca_icms_venha_o_que_vier_do_ERP():
    """A CST do CT-e da Sulista descreve a prestacao DELA, que nao e optante.
    Copiar para um agregado optante poria destaque de imposto num documento
    que nao pode ter. O regime do EMITENTE vem primeiro."""
    d = dict(DADOS, emit_optante_simples=1, cst_erp="000", aliq_erp=12)
    assert AUTO.icms_de(d) == ("ICMSSN", "90", None)


def test_nao_optante_aproveita_a_CST_e_a_ALIQUOTA_que_o_ERP_calculou():
    d = dict(DADOS, emit_optante_simples=2, cst_erp="000", aliq_erp=12)
    grupo, cst, aliq = AUTO.icms_de(d)
    assert (grupo, cst) == ("ICMS00", "00") and aliq == Decimal("12")


def test_isenta_no_erp_vira_grupo_de_isencao_sem_base_nem_aliquota():
    d = dict(DADOS, emit_optante_simples=2, cst_erp="040", aliq_erp=0)
    assert AUTO.icms_de(d) == ("ICMS45", "40", None)
    xml = doc.serializar(doc.montar(d, AUTO, numero=1))
    # Escopo IMPORTA: o grupo do IBS/CBS tem base propria e legitima. Procurar
    # "<vBC>" no XML inteiro acusaria a base do IBS como se fosse a do ICMS.
    bloco_icms = xml[xml.index("<ICMS>"):xml.index("</ICMS>")]
    assert "<ICMS45>" in bloco_icms and "<vBC>" not in bloco_icms, (
        "isenta nao tem base de calculo: mandar vBC zerado declara base zero "
        "numa operacao que nao tem base")


def test_outros_no_erp_vira_ICMS90():
    d = dict(DADOS, emit_optante_simples=2, cst_erp="090", aliq_erp=0)
    grupo, cst, _ = AUTO.icms_de(d)
    assert (grupo, cst) == ("ICMS90", "90")


def test_situacao_tributaria_desconhecida_PARA_em_vez_de_adivinhar():
    """Traduzir codigo fiscal por semelhanca e inventar tributacao."""
    d = dict(DADOS, emit_optante_simples=2, cst_erp="051", aliq_erp=12)
    with pytest.raises(ValueError, match="de-para"):
        AUTO.icms_de(d)


def test_tributada_com_aliquota_zero_no_erp_e_recusada():
    """CST 000 e aliquota 0 declara imposto zero numa operacao tributada."""
    d = dict(DADOS, emit_optante_simples=2, cst_erp="000", aliq_erp=0)
    with pytest.raises(ValueError, match="alíquota zero"):
        AUTO.icms_de(d)


def test_AUTO_recusa_cst_fixa_junto():
    """Um valor fixo ali nao seria usado e daria a impressao de estar valendo."""
    with pytest.raises(ValueError, match="AUTO"):
        dataclasses.replace(ENQ, grupo_icms="AUTO", cst_icms="00",
                            p_icms=Decimal("12"))


def test_grupo_fixo_continua_ignorando_o_erp():
    """Quem fixar o grupo nao quer que o documento decida sozinho."""
    d = dict(DADOS, emit_optante_simples=2, cst_erp="000", aliq_erp=17)
    assert ENQ.icms_de(d) == ("ICMSSN", "90", None)


# --- IBS/CBS (Reforma Tributaria) -------------------------------------------

IBS = {}   # DADOS ja carrega a tributacao de IBS/CBS


def test_o_grupo_de_ibs_cbs_sai_com_o_que_o_ERP_calcula():
    """cStat 310 sem ele. CST, classificacao e aliquotas vem do ERP — nada
    inventado, mesma regra do ICMS."""
    xml = doc.serializar(doc.montar(dict(DADOS, **IBS), AUTO, numero=1))
    assert "<IBSCBS>" in xml
    assert "<CST>000</CST>" in xml and "<cClassTrib>000001</cClassTrib>" in xml
    assert "<pCBS>0.9000</pCBS>" in xml
    assert "<vTotDFe>" in xml, "rejeicao 360 veio junto com o IBS/CBS"


def test_a_base_do_ibs_cbs_e_o_valor_DESTE_documento():
    """Nao se tenta reproduzir a base do CT-e da Sulista: la o total carrega
    taxas, pedagio e seguro. Este documento tem UM componente."""
    d = dict(DADOS, **IBS)
    xml = doc.serializar(doc.montar(d, AUTO, numero=1))
    assert f"<vBC>{doc.valor(d, AUTO)}</vBC>" in xml


def test_ibs_zerado_no_erp_PARA_e_explica_que_e_configuracao():
    """cStat 316. Ha UMA definicao de IBS cadastrada, com 0,0000, e o imposto
    marcado como nao configurado — escolher um numero aqui seria inventar
    aliquota."""
    d = dict(DADOS, **IBS, )
    d["ibs_p_uf"] = Decimal("0")
    with pytest.raises(ValueError, match="316"):
        doc.montar(d, AUTO, numero=1)


def test_sem_tributacao_de_ibs_cbs_no_erp_tambem_para():
    d = dict(DADOS, **IBS)
    d["ibs_cst"] = None
    with pytest.raises(ValueError, match="310"):
        doc.montar(d, AUTO, numero=1)
