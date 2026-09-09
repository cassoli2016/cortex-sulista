"""DDA — leitura do extrato, reconciliação da posição e casamento com o ERP.

O FORMATO aqui é LITERAL, copiado do extrato real do portal do banco (consulta
de boletos, 03/09/2026): os dez rótulos do cabeçalho, a mesma grafia, o mesmo
preâmbulo de nove linhas, e os valores no formato "R$ 1.234,56" — com o
cifrão e o ESPAÇO FINO (U+00A0) que derrubam qualquer parser de número ingênuo.

Os DADOS são fictícios de propósito: o repositório é público (CLAUDE.md §8), e
nome de fornecedor, CNPJ e código de barras reais são dado de negócio. O que o
teste precisa reproduzir é a FORMA do arquivo, não a carteira da empresa.

E o dublê NÃO é montado a partir das constantes do módulo: sabotar
`_COLUNAS` tem de deixar o teste vermelho, e um dublê que se monta a partir da
lista de rótulos seria sabotado junto (a armadilha do cartão de janelas do ERP,
registrada em `docs/LICOES.md`).
"""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest

from api.financeiro import dda


# --------------------------------------------------------------- o arquivo

# As dez colunas do extrato real, na ordem em que ele as exporta. LITERAIS.
CABECALHO = ["Pagador/Agregado", "Beneficiário", "CPF/CNPJ", "Venc.", "Nº Doc.",
             "Até Venc.", "A Pagar", "Tipo de Boleto", "Banco", "Observações",
             "Código de barras"]

# O preâmbulo: nove linhas antes da tabela. É por causa dele que o leitor
# PROCURA o cabeçalho em vez de assumir a linha 10.
PREAMBULO = [
    [], ["Dados da conta"], [],
    ["Nome da empresa: TRANSPORTADORA EXEMPLO S A"],
    ["Agência/Conta: 0098 / 0053934-9"],
    ["CPF/CNPJ:  11.222.333/0001-44"],
    [], ["Boletos"], [],
    ["Data/Hora: 03/09/2026 às 17:32:10"],
]


def _planilha(linhas, preambulo=None, cabecalho=None):
    """Monta um .xlsx no formato do portal. Devolve os bytes."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Boletos"
    for l in (PREAMBULO if preambulo is None else preambulo):
        ws.append(l or [None])
    ws.append(cabecalho or CABECALHO)
    for l in linhas:
        ws.append(l)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _boleto(barras, benef="OFICINA EXEMPLO LTDA", doc="55.444.333/0001-22",
            venc="04/09/2026", ndoc="1555", ate="R$ 350,00",
            apagar=None, tipo="DM Duplicata Mercantil", banco="237",
            obs="Este boleto sofreu alteração/instrução por parte do beneficiário."):
    return ["TRANSPORTADORA EXEMPLO S A", benef, doc, venc, ndoc,
            ate, apagar or ate, tipo, banco, obs, barras]


def _barras(n):
    """44 dígitos únicos e sintéticos."""
    return ("237921559" + f"{n:035d}")[:44]


# ---------------------------------------------------------------- leitura

def test_le_o_formato_do_portal():
    dados = _planilha([_boleto(_barras(1)), _boleto(_barras(2), ate="R$ 1.234,56")])
    r = dda.ler(dados, "DDA_Consulta_Boletos.xlsx")
    assert len(r["boletos"]) == 2
    b = r["boletos"][0]
    assert b["vencimento"] == date(2026, 9, 4)
    assert b["valor"] == 350.0
    assert b["beneficiario_doc"] == "55444333000122"     # só dígitos, como o ERP
    assert b["banco"] == "237"
    # o separador de milhar e o espaço fino não podem virar 123456
    assert r["boletos"][1]["valor"] == 1234.56
    assert r["total"] == 1584.56


def test_le_o_carimbo_do_extrato_e_nao_a_hora_do_upload():
    """A idade do retrato é a do extrato: planilha de duas semanas atrás
    importada hoje é dado de duas semanas atrás."""
    r = dda.ler(_planilha([_boleto(_barras(1))]), "dda.xlsx")
    assert r["extraido_em"].date() == date(2026, 9, 3)
    assert r["extraido_em"].hour == 17
    assert r["pagador_cnpj"] == "11222333000144"


def test_acha_o_cabecalho_com_linha_a_mais_no_topo():
    """O portal vai acrescentar uma linha de preâmbulo algum dia. Assumir a
    linha 10 quebraria em silêncio, deslocando todas as colunas."""
    extra = [["Relatório gerado pelo Internet Banking"], []] + PREAMBULO
    r = dda.ler(_planilha([_boleto(_barras(1))], preambulo=extra), "dda.xlsx")
    assert len(r["boletos"]) == 1
    assert r["boletos"][0]["valor"] == 350.0


def test_valor_a_pagar_e_o_nominal_sao_guardados_separados():
    """Divergem em 170 das 1.061 linhas do extrato real (juros de quem já
    venceu, desconto de quem antecipa). Usar um no lugar do outro erra o
    casamento com o ERP E o caixa."""
    r = dda.ler(_planilha([_boleto(_barras(1), ate="R$ 1.000,00",
                                   apagar="R$ 1.087,45")]), "dda.xlsx")
    assert r["boletos"][0]["valor"] == 1000.0
    assert r["boletos"][0]["a_pagar"] == 1087.45


def test_linha_sem_chave_e_ignorada_e_CONTADA():
    """Linha descartada em silêncio é dinheiro que some do total."""
    r = dda.ler(_planilha([_boleto(_barras(1)),
                           _boleto("", ate="R$ 9.999,00"),
                           _boleto(_barras(3), venc="")]), "dda.xlsx")
    assert len(r["boletos"]) == 1
    assert r["ignoradas"] == 2
    assert r["total"] == 350.0


def test_boleto_repetido_no_arquivo_nao_dobra_o_valor():
    """O portal já exportou linha repetida quando a consulta cruza contas."""
    r = dda.ler(_planilha([_boleto(_barras(7)), _boleto(_barras(7))]), "dda.xlsx")
    assert len(r["boletos"]) == 1
    assert r["repetidas"] == 1
    assert r["total"] == 350.0


def test_linha_digitavel_vira_o_mesmo_codigo_de_barras():
    """O portal exporta ora um ora outro. Sem a conversão, o MESMO boleto
    entraria com duas identidades — e a carga seguinte marcaria uma delas como
    sumida, anunciando pagamento que não houve."""
    barras = "23792155900000350000926096202000000600683860"
    ld = (barras[0:4] + barras[19:24] + str(0) + barras[24:34] + str(0)
          + barras[34:44] + str(0) + barras[4] + barras[5:9] + barras[9:19])
    assert len(ld) == 47
    assert dda._barras_de_linha_digitavel(ld) == barras
    # guia de arrecadação (48 dígitos, começa com 8) tem outro arranjo: devolve
    # None em vez de um palpite
    assert dda._barras_de_linha_digitavel("8" * 48) is None


def test_arquivo_que_nao_e_o_extrato_diz_o_que_fazer():
    dados = _planilha([["a", "b"]], preambulo=[[]],
                      cabecalho=["Coluna A", "Coluna B"])
    with pytest.raises(dda.ArquivoInvalido) as e:
        dda.ler(dados, "outra.xlsx")
    assert "portal do banco" in str(e.value)


# ------------------------------------------------------------- casamento

def _titulo(doc, venc, valor, credor="OFICINA EXEMPLO LTDA"):
    return {"doc": doc, "venc": venc, "valor": valor, "pendente": valor,
            "pago": None, "credor": credor}


def _b(doc, venc, valor, barras="x"):
    return {"barras": barras, "beneficiario": "F", "beneficiario_doc": doc,
            "vencimento": venc, "valor": valor, "a_pagar": valor,
            "documento": None, "tipo": None, "banco": None, "observacao": None}


def test_casamento_exato_e_o_que_sobra_e_a_fila_de_lancamento():
    boletos = [_b("111", date(2026, 10, 5), 100.0, "b1"),
               _b("222", date(2026, 10, 6), 200.0, "b2")]
    titulos = [_titulo("111", date(2026, 10, 5), 100.0)]
    r = dda.casar(boletos, titulos)
    assert r["resumo"]["casados"] == 1
    assert r["resumo"]["faltantes"] == 1
    assert r["resumo"]["faltantes_valor"] == 200.0
    assert r["faltantes"][0]["beneficiario_doc"] == "222"


def test_cada_titulo_do_erp_e_consumido_uma_vez_so():
    """Um fornecedor com cinco boletos de R$ 350 no mesmo dia tem cinco
    títulos. Casar o mesmo cinco vezes esconderia quatro que faltam lançar."""
    boletos = [_b("111", date(2026, 10, 5), 350.0, f"b{i}") for i in range(5)]
    titulos = [_titulo("111", date(2026, 10, 5), 350.0),
               _titulo("111", date(2026, 10, 5), 350.0)]
    r = dda.casar(boletos, titulos)
    assert r["resumo"]["casados"] == 2
    assert r["resumo"]["faltantes"] == 3


def test_valor_diferente_e_casado_mas_reportado_a_parte():
    boletos = [_b("111", date(2026, 10, 5), 1_000.0, "b1")]
    titulos = [_titulo("111", date(2026, 10, 5), 940.0)]
    r = dda.casar(boletos, titulos)
    assert r["resumo"]["casados"] == 0
    assert r["resumo"]["divergentes"] == 1
    assert r["divergentes"][0]["diferenca"] == 60.0


def test_vencimento_prorrogado_no_banco_nao_vira_titulo_faltante():
    """898 das 1.061 linhas do extrato real trazem 'sofreu alteração/instrução
    por parte do beneficiário'."""
    boletos = [_b("111", date(2026, 10, 5), 500.0, "b1")]
    titulos = [_titulo("111", date(2026, 10, 9), 500.0)]
    r = dda.casar(boletos, titulos)
    assert r["resumo"]["prorrogados"] == 1
    assert r["resumo"]["faltantes"] == 0
    assert r["prorrogados"][0]["dias"] == 4
    # fora da janela, é outro título
    longe = dda.casar(boletos, [_titulo("111", date(2026, 11, 5), 500.0)])
    assert longe["resumo"]["faltantes"] == 1


def test_matriz_registra_o_boleto_e_a_filial_leva_o_titulo():
    """O defeito mais caro que este módulo teve, e o menos visível.

    O fornecedor registra o boleto pela MATRIZ e o ERP lança o título pela
    FILIAL que emitiu a nota. Casando só pelo CNPJ completo, o par não existe e
    o boleto vira "sem título no ERP" — R$ 333 mil de falso alarme no primeiro
    extrato real (09/09/2026), com a Raízen sozinha respondendo por R$ 268 mil
    deles: 33453598/0001-23 no banco contra 33453598/0244-99 no ERP.

    É a mesma regra que a antecipação já usa do outro lado da conta, onde o
    CLIENTE fatura por várias filiais do grupo.
    """
    boletos = [_b("33453598000123", date(2026, 9, 10), 29_750.0, "b1")]
    titulos = [_titulo("33453598024499", date(2026, 9, 10), 29_750.0, "RAIZEN FILIAL")]
    r = dda.casar(boletos, titulos)
    assert r["resumo"]["casados"] == 1, r["resumo"]
    assert r["resumo"]["faltantes"] == 0
    assert r["casados"][0]["nivel"] == "raiz", r["casados"][0]


def test_a_raiz_NAO_afrouxa_o_casamento_por_data():
    """A raiz só vale com o vencimento EXATO. Numa janela de 7 dias ela casaria
    dois postos diferentes do mesmo grupo com o mesmo valor — e um boleto que
    falta lançar sumiria contra o título de outro estabelecimento."""
    boletos = [_b("11111111000199", date(2026, 9, 10), 5_000.0, "b1")]
    # mesmo grupo, OUTRA filial, vencimento 3 dias depois
    titulos = [_titulo("11111111022200", date(2026, 9, 13), 5_000.0)]
    r = dda.casar(boletos, titulos)
    assert r["resumo"]["faltantes"] == 1, r["resumo"]
    assert r["resumo"]["prorrogados"] == 0


def test_o_cnpj_completo_ganha_da_raiz_quando_os_dois_servem():
    """Havendo par exato, é ele que vale — a raiz é o plano B, não um empate."""
    boletos = [_b("22222222000155", date(2026, 9, 10), 800.0, "b1")]
    titulos = [_titulo("22222222033300", date(2026, 9, 10), 800.0, "FILIAL"),
               _titulo("22222222000155", date(2026, 9, 10), 800.0, "MATRIZ")]
    r = dda.casar(boletos, titulos)
    assert r["casados"][0]["nivel"] == "exato", r["casados"][0]
    assert r["casados"][0]["erp_doc"] == "22222222000155"


def test_boleto_sem_cnpj_nao_casa_por_nome():
    """O mesmo fornecedor aparece com quatro grafias no MESMO arquivo. Casar
    por nome deixaria metade de fora e juntaria o que não é o mesmo."""
    r = dda.casar([_b(None, date(2026, 10, 5), 100.0, "b1")],
                  [_titulo("111", date(2026, 10, 5), 100.0)])
    assert r["resumo"]["faltantes"] == 1


def test_faltantes_por_mes_ignora_o_que_ja_tem_titulo():
    """Prorrogado e divergente já têm título no ERP: somá-los contaria a mesma
    obrigação duas vezes no piso do mês."""
    boletos = [_b("111", date(2026, 10, 5), 100.0, "b1"),   # faltante
               _b("222", date(2026, 10, 6), 900.0, "b2"),   # prorrogado
               _b("333", date(2026, 11, 7), 50.0, "b3")]    # faltante
    titulos = [_titulo("222", date(2026, 10, 9), 900.0)]
    conf = dda.casar(boletos, titulos)
    conf["disponivel"] = True
    conf["erp_indisponivel"] = False
    assert dda.faltantes_por_mes(conf) == {"2026-10": 100.0, "2026-11": 50.0}


def test_erp_fora_do_ar_nao_vira_zero_faltante():
    """Zero afirmaria 'conferi e está tudo lançado', que ninguém conferiu."""
    assert dda.faltantes_por_mes({"disponivel": True, "erp_indisponivel": True,
                                  "faltantes": []}) == {}


# --------------------------------------------------- posição e reconciliação

def test_importar_reconcilia_a_posicao(esquema_pg):
    """O extrato é um RETRATO. Boleto pago some da extração seguinte, e se cada
    carga só inserisse, a base viraria a soma histórica de tudo que já foi
    devido."""
    dda.ESQUEMA = esquema_pg
    try:
        p1 = _planilha([_boleto(_barras(1)), _boleto(_barras(2)), _boleto(_barras(3))])
        r1 = dda.importar(p1, "dda1.xlsx", usuario="teste", esquema=esquema_pg)
        assert r1["boletos"] == 3 and r1["novos"] == 3 and r1["sumiram"] == 0
        assert len(dda.posicao(esquema_pg)) == 3

        # o boleto 2 foi pago e não vem mais; entra um 4 novo
        p2 = _planilha([_boleto(_barras(1)), _boleto(_barras(3)), _boleto(_barras(4))])
        r2 = dda.importar(p2, "dda2.xlsx", usuario="teste", esquema=esquema_pg)
        assert r2["novos"] == 1
        assert r2["sumiram"] == 1
        vivos = {b["barras"] for b in dda.posicao(esquema_pg)}
        assert vivos == {_barras(1), _barras(3), _barras(4)}
    finally:
        dda.ESQUEMA = None


def test_carga_parcial_nao_fecha_o_que_nao_pode_ter_trazido(esquema_pg):
    """Extrato de uma conta só marcaria como sumido o que ele nunca teve chance
    de trazer — 'R$ 4 mi de boletos foram pagos' no dia em que alguém exportou
    meia planilha."""
    dda.ESQUEMA = esquema_pg
    try:
        dda.importar(_planilha([_boleto(_barras(1)), _boleto(_barras(2))]),
                     "cheia.xlsx", esquema=esquema_pg)
        r = dda.importar(_planilha([_boleto(_barras(1))]), "parcial.xlsx",
                         completa=False, esquema=esquema_pg)
        assert r["sumiram"] == 0
        assert len(dda.posicao(esquema_pg)) == 2
    finally:
        dda.ESQUEMA = None


def test_reimportar_o_mesmo_arquivo_nao_rejuvenesce_o_dado(esquema_pg):
    """Clicar duas vezes é acidente comum. Refazer a carga marcaria como
    'visto agora' um retrato velho, sem que nada tenha chegado."""
    dda.ESQUEMA = esquema_pg
    try:
        p = _planilha([_boleto(_barras(1))])
        a = dda.importar(p, "dda.xlsx", esquema=esquema_pg)
        b = dda.importar(p, "dda.xlsx", esquema=esquema_pg)
        assert a["ja_existia"] is False and b["ja_existia"] is True
        assert b["carga_id"] == a["carga_id"]
        assert b["novos"] == 0 and b["sumiram"] == 0
    finally:
        dda.ESQUEMA = None


def test_estado_mede_a_idade_do_extrato_nao_a_do_upload(esquema_pg):
    dda.ESQUEMA = esquema_pg
    try:
        assert dda.estado(esquema_pg)["configurado"] is False
        dda.importar(_planilha([_boleto(_barras(1))]), "dda.xlsx", esquema=esquema_pg)
        e = dda.estado(esquema_pg)
        assert e["configurado"] is True and e["boletos"] == 1
        # o extrato é de 03/09/2026 e o upload é de agora: a idade tem de sair
        # do PRIMEIRO
        esperado = (date.today() - date(2026, 9, 3)).days
        assert e["idade_dias"] == esperado, (e["idade_dias"], esperado)
        assert e["velho"] is (esperado > dda.IDADE_MAX_DIAS)
    finally:
        dda.ESQUEMA = None


def test_sem_tabela_a_posicao_e_vazia_e_nao_explode():
    """Instalação sem a migration aplicada não pode derrubar a projeção — ela
    só perde o piso medido."""
    dda.ESQUEMA = "teste_dda_inexistente_de_proposito"
    try:
        assert dda.posicao() == []
        assert dda.estado()["configurado"] is False
    finally:
        dda.ESQUEMA = None
