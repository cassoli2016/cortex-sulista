# -*- coding: utf-8 -*-
"""O leitor dos documentos da Whirlpool, sobre TEXTO no layout real.

Os textos abaixo copiam LINHA A LINHA a forma que o `pypdf` extrai dos PDFs
reais (conferido em 16/09/2026 sobre os 290 anexos de 90 dias) — espaçamento,
ordem dos blocos, rótulos com acento. Nomes, CNPJs e valores são INVENTADOS:
o repositório é público e frete de cliente não entra nele. Por isso o dublê
é texto e não PDF: o PDF real carregaria o dado real.
"""
from __future__ import annotations

from api.validacao_whirlpool import leitor as L

# Pré-Cálculo, 2 páginas (um fornecedor por página), número AMERICANO
PAG1_US = """FORNECEDOR ALFA LTDA 11.111.111/0001-11              0.00          1,234.50             180.000               2.016
____________________________________
Valor Total:              0.00          1,234.50             180.000               2.016
Valor do Frete R$          1,100.00
Taxa de Coleta/Entrega R$             84.50
Pedágio R$             50.00
Frete Liquido R$          1,234.50
Base Imp Despesa R$          1,402.84
Valor do ICMS R$            168.34
___________________________________
Valor Líquido a Pagar          1,402.84
Coleta: 110 Unidade Planta Cliente S. I.Estadual: 250.000.000
CNPJ: 99.999.999/0039-59 Município: JOINVILLE-SC
Endereço: Rua Um, 100 CEP: 89000-000
________________________________________________________________________________
Contratante: 110 Unidade Planta Cliente S.A. I.Estadual: 250.000.000
CNPJ: 99.999.999/0039-59 Município: JOINVILLE-SC
Endereço: Rua Um, 100 CEP: 89000-000
________________________________________________________________________________
Entrega: 0001002841 FORNECEDOR ALFA LTDA I.Estadual: 10160442-09
CNPJ: 11.111.111/0001-11 CEP: 81350-200 Incoterm: FOB
Endereço: R DOIS 2221 Município: CURITIBA-PR
________________________________________________________________________________
Moeda: R$ Pré-Cálculo Inbound Página: 1 de 2
Data: 15/09/2026
Transporte Planejado: 10830001 Hora: 18:34:44
________________________________________________________________________________
Observação: Cliente:                         - Data: 00/00 - Hora: 00:00 - Obs:
Fornecedor CNPJ N.F. Vl. N.F. Vl. Frete Peso KG Vol.
Transportadora: 0005003326 TRANSPORTADORA SULISTA S/A Identificador: PRAAA1234
CNPJ: 76.104.397/0001-23 Município: Curitiba-PR
Zona de Tarifa: PR01IN2 Preferencial Curitiba comSC08IN SC - Joinville Inbound Tipo Operação: Transporte Direto
Sub. Tributária / Retenção: Não       ICMS: Sim      ISS: Não         % ICMS:     12.00         % ISS:      0.00
Transp. Planejado:  10830001 Condição Exped: Valor Tabela Frete:        1,100.00
Pré-Cálculo: 261300001 Data-Cálculo: 09/14/2026 08:49:04 Tipo Cálculo: Z1 Rodov. Lotação  Tipo Viagem: Viagem Redonda
Rota: IB2372 IB2372 - Jlle Meio de Transporte: 65 CARRETA SIDER
________________________________________________________________________________"""

PAG2_US = """FORNECEDOR BETA S.A. 22.222.222/0009-41              0.00            100.00              10.600               0.371
____________________________________
Valor Total:              0.00            100.00              10.600               0.371
Valor do Frete R$             90.00
Taxa de Coleta/Entrega R$              6.00
Pedágio R$              4.00
Frete Liquido R$            100.00
Base Imp Despesa R$            113.64
Valor do ICMS R$             13.64
___________________________________
Valor Líquido a Pagar            113.64
Coleta: 110 Unidade Planta Cliente S. I.Estadual: 250.000.000
CNPJ: 99.999.999/0039-59 Município: JOINVILLE-SC
Endereço: Rua Um, 100 CEP: 89000-000
________________________________________________________________________________
Contratante: 110 Unidade Planta Cliente S.A. I.Estadual: 250.000.000
CNPJ: 99.999.999/0039-59 Município: JOINVILLE-SC
Endereço: Rua Um, 100 CEP: 89000-000
________________________________________________________________________________
Entrega: 0001023009 FORNECEDOR BETA S.A. I.Estadual: 9083461141
CNPJ: 22.222.222/0009-41 CEP: 81170-300 Incoterm: FOB
Endereço: AV TRES 11655 Município: CURITIBA-PR
________________________________________________________________________________
Moeda: R$ Pré-Cálculo Inbound Página: 2 de 2
Data: 15/09/2026
Transporte Planejado: 10830001 Hora: 18:34:44
________________________________________________________________________________
Observação: Cliente:                         - Data: 00/00 - Hora: 00:00 - Obs:
Valor Total da Nota Fiscal                0.00
Peso Total da Nota Fiscal             190.600
Valor Total do Frete Liquído            1,334.50
Valor Total do Liquído a Pagar            1,516.48
Valor Vale Pedágio                 0.00
Fornecedor CNPJ N.F. Vl. N.F. Vl. Frete Peso KG Vol.
Transportadora: 0005003326 TRANSPORTADORA SULISTA S/A Identificador: PRAAA1234
CNPJ: 76.104.397/0001-23 Município: Curitiba-PR
Sub. Tributária / Retenção: Não       ICMS: Sim      ISS: Não         % ICMS:     12.00         % ISS:      0.00
Pré-Cálculo: 261300001 Data-Cálculo: 09/14/2026 08:49:04 Tipo Cálculo: Z1 Rodov. Lotação  Tipo Viagem: Viagem Redonda
Rota: IB2372 IB2372 - Jlle Meio de Transporte: 65 CARRETA SIDER
________________________________________________________________________________"""

# o mesmo formato com número BRASILEIRO e o fornecedor no papel de COLETA
PAG_BR = """FORNECEDOR GAMA LTDA. 33.333.333/0001-98              0,00            155,93              51,000               0,510
____________________________________
Valor Total:              0,00            155,93              51,000               0,510
Valor do Frete R$            132,72
Taxa de Coleta/Entrega R$              9,87
Pedágio R$             13,34
Frete Liquido R$            155,93
Base Imp Despesa R$            177,19
Valor do ICMS R$             21,26
___________________________________
Valor Líquido a Pagar            177,19
Coleta: 0001000359 FORNECEDOR GAMA LTDA. I.Estadual: 250581744
CNPJ: 33.333.333/0001-98 Município: JOINVILLE-SC
Endereço: Rua Quatro 1 CEP: 89000-001
________________________________________________________________________________
Contratante: 120 Unidade Outra Planta S.A. I.Estadual: 587.000.000.116
CNPJ: 99.999.999/0003-48 Município: RIO CLARO-SP
Endereço: Av Cinco 777 CEP: 13506-095
________________________________________________________________________________
Entrega: 120 Unidade Outra Planta S.A. I.Estadual: 587.000.000.116
CNPJ: 99.999.999/0003-48 Município: RIO CLARO-SP
Endereço: Av Cinco 777 CEP: 13506-095
________________________________________________________________________________
Moeda: R$ Pré-Cálculo Inbound Página: 1 de 1
Data: 15/09/2026
Transporte Planejado: 10830002 Hora: 17:01:07
________________________________________________________________________________
Valor Total do Frete Liquído            155,93
Valor Total do Liquído a Pagar            177,19
Fornecedor CNPJ N.F. Vl. N.F. Vl. Frete Peso KG Vol.
Transportadora: 0005003371 TRANSPORTADORA SULISTA S/A Identificador: PRAAA1234
CNPJ: 76.104.397/0002-04 Município: São Bernardo do Campo-SP
Sub. Tributária / Retenção: Não       ICMS: Sim      ISS: Não         % ICMS:     12,00         % ISS:      0,00
Pré-Cálculo: 261300002 Data-Cálculo: 09/15/2026 16:54:56 Tipo Cálculo: Z1 Rodov. Lotação  Tipo Viagem: Viagem Simples
Rota: IB2329 IB2329 Meio de Transporte: 65 CARRETA SIDER
________________________________________________________________________________"""

# Pré-Cálculo mandado ANTES do cálculo: sem linhas de componente
PAG_ZERADO = """FORNECEDOR BETA S.A. 22.222.222/0009-41              0.00              0.00           5,262.974              10.449
____________________________________
Valor Total:              0.00              0.00           5,262.974              10.449
___________________________________
Valor Líquido a Pagar              0.00
Contratante: 110 Unidade Planta Cliente S.A. I.Estadual: 250.000.000
CNPJ: 99.999.999/0039-59 Município: JOINVILLE-SC
Moeda: R$ Pré-Cálculo Inbound Página: 1 de 1
Transporte Planejado: 10830003 Hora: 10:00:00"""

ORDEM = """Coletas (Inbound) - Matéria Prima Transporte: 10830004
Data Hora Início  Centro  Código / CC / Fornecedor Endereço- Origem Peso Kg Volume Ass. e Carimbo
09/11/2026 10:00           110 1017955 Fornecedor Delta S.A. (Fábrica Ut Rua Seis-Santo André-SP           3,000.000      7.640
020301341 TUBO COBRE 19,05X0,5                        20 FEIXE DE TUBOS AMARRADO               3,000.000 KG
 ______________ ___________
Total:           3,000.000        7.640
Entregas (Inbound) - Matéria Prima Transporte: 10830004
Data Hora Início/Fim  Centro  Código / CC / Fornecedor Endereço- Origem Peso Kg Ass. e Carimbo
09/14/2026 00:01    0:00    1183 Jlle Receb Fab.II Básico  Rua Um, 100--SC           3,000.000______________
Total:           3,000.000
Ordem de Coleta: 10830004 09/14/2026  19:05:46
Página 1 de    1
Transportadora: 5003371 - TRANSPORTADORA SULISTA S/A Placa do Veículo: PRAAA1234
            Itinerário: IB2112 - IB2112 - JLLE   Tipo de Veículo: 65 - CARRETA SIDER
               Viagem: SIMPLES / Cliente:                         -  Cond. Expedição:  -  """

EXPRESSO = """Requisição de serviço de transporte expresso
Matéria Prima e Componentes
Status: Aprovado
Dados do solicitante"""


def test_reconhece_os_dois_formatos_e_recusa_o_resto():
    assert L.ler_paginas([PAG1_US, PAG2_US])["formato"] == "precalculo"
    assert L.ler_paginas([ORDEM])["formato"] == "ordem_coleta"
    r = L.ler_paginas([EXPRESSO])
    assert r["formato"] == "desconhecido" and "expresso" in r["motivo"]
    assert L.ler(b"\x89PNG", "png")["formato"] == "desconhecido"


def test_precalculo_uma_pagina_por_fornecedor_com_todos_os_componentes():
    d = L.ler_paginas([PAG1_US, PAG2_US])
    assert d["sotaque"] == "us"
    assert [f["cnpj"] for f in d["fornecedores"]] == ["11111111000111", "22222222000941"]
    f = d["fornecedores"][0]
    assert (f["frete"], f["taxa_coleta"], f["pedagio"], f["frete_liquido"],
            f["base_icms"], f["icms"], f["total_pagar"]) == (
        1100.0, 84.5, 50.0, 1234.5, 1402.84, 168.34, 1402.84)
    assert (f["peso"], f["volume"]) == (180.0, 2.016)
    assert f["contratante"]["cnpj"] == "99999999003959"
    assert f["entrega"]["cnpj"] == "11111111000111"
    assert d["transporte"] == "10830001"
    assert d["icms_pct"] == 12.0
    assert d["transportadora_cnpj"] == "76104397000123"
    assert d["total_pagar"] == 1516.48 and d["total_peso"] == 190.6
    assert d["tipo_viagem"] == "Viagem Redonda"
    assert d["sem_valor"] is False


def test_numero_brasileiro_nao_vira_milhar():
    """`51,000` é 51 kg num documento brasileiro. Lido com a regra americana
    viraria 51 toneladas — e o peso "divergiria" de todo CT-e."""
    d = L.ler_paginas([PAG_BR])
    assert d["sotaque"] == "br"
    f = d["fornecedores"][0]
    assert f["peso"] == 51.0 and f["volume"] == 0.51
    assert f["total_pagar"] == 177.19 and f["frete"] == 132.72
    assert d["icms_pct"] == 12.0
    # o fornecedor aqui é a COLETA, não a entrega
    assert f["coleta"]["cnpj"] == "33333333000198"


def test_precalculo_zerado_e_arquivo_sem_valor():
    d = L.ler_paginas([PAG_ZERADO])
    assert d["sem_valor"] is True
    assert d["fornecedores"][0]["frete"] is None


def test_ordem_de_coleta_peso_volume_e_paradas():
    d = L.ler_paginas([ORDEM])
    assert d["transporte"] == "10830004"
    assert (d["peso_coleta"], d["volume_coleta"], d["peso_entrega"]) == (3000.0, 7.64, 3000.0)
    assert d["itinerario"] == "IB2112 - IB2112 - JLLE"
    assert d["veiculo"] == "65 - CARRETA SIDER"
    papeis = [(p["papel"], p["peso"]) for p in d["paradas"]]
    assert papeis == [("coleta", 3000.0), ("entrega", 3000.0)], papeis


def test_pdf_ilegivel_nao_derruba():
    r = L.ler(b"%PDF-1.4 lixo", "pdf")
    assert r["formato"] == "desconhecido" and "ilegível" in r["motivo"]
