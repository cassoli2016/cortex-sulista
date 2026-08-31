# -*- coding: utf-8 -*-
"""A fatura da administradora de tag: leitura e conferência.

A FATURA DE VERDADE NÃO ENTRA NO REPOSITÓRIO, e não é preguiça: são 28 MB com
placa, praça, horário e valor de 192 veículos da operação, e o repositório do
código é PÚBLICO. É a mesma regra que manda o print do botão de report para um
repo separado e privado. Os testes montam páginas sintéticas e exercitam o
parser inteiro por `interpretar()`.

E AS LINHAS SÃO GERADAS A PARTIR DOS DESLOCAMENTOS DO PRÓPRIO CABEÇALHO, não
contadas a dedo. A primeira versão deste arquivo alinhava os espaços na mão e
falhou em três testes por desalinhamento do FIXTURE, não do código — o que é o
pior tipo de teste vermelho, porque manda procurar defeito onde não há. O PDF
real renderiza exatamente assim: cada valor no deslocamento que o cabeçalho
anuncia, com as colunas numéricas alinhadas à direita.

Cada caso aqui nasceu de um defeito encontrado lendo a fatura de ago/2026, e o
mais importante é `test_conferencia_FICA_VERMELHA_...`: sem ele, todos os
outros verdes provariam apenas que a conferência não reclama.
"""
from __future__ import annotations

import pytest

from api.pedagio import semparar as sp

# A quebra de linha NOMEADA. Não é preciosismo: montar este arquivo por script
# gerador já perdeu o escape da barra invertida duas vezes, e nas duas o
# sintoma foi um literal de string sem fechar — erro de sintaxe num arquivo de
# teste, que não diz nada sobre o que se estava testando.
LF = chr(10)


# ── construtor de linha em coluna fixa ──────────────────────────────────────

def _linha(cabecalho: str, nomes: list[str], valores: list[str],
           direita: frozenset[int] = frozenset()) -> str:
    """Escreve os valores nos deslocamentos que o cabeçalho anuncia.

    Coluna à direita termina onde o RÓTULO termina — é o que reproduz o
    transbordo para a esquerda do "TOTAL", cujo valor é mais largo que a
    palavra e por isso começa antes dela.
    """
    pos = sp.colunas(cabecalho, nomes)
    assert pos, "o cabeçalho do fixture não tem todas as colunas"
    buf = [" "] * (max(pos) + 40)
    for i, valor in enumerate(valores):
        v = str(valor)
        if not v:
            continue
        ini = pos[i] + len(nomes[i]) - len(v) if i in direita else pos[i]
        ini = max(ini, 0)
        if ini + len(v) > len(buf):
            buf += [" "] * (ini + len(v) - len(buf))
        buf[ini:ini + len(v)] = list(v)
    return "".join(buf).rstrip()


CAB_RESUMO = ("Placa         Tag             Pref.       Plano Contratado       "
              "Passagens      Qtd    Estacionamento       Qtd     Estabelecimento"
              "      Qtd     Vale Pedágio         Qtd      TOTAL")
CAB_TAG = ("Data           Hora            Concessionária                        "
           "                     Praça                                           "
           "       Cat                Valor(R$)")
CAB_VALE = ("Data        Hora       Concessionária                  Embarcador   "
            "         Praça                                                      "
            "        Cat        Viagem             Valor(R$)")
CAB_CRED = ("Data           Hora            Placa                Tag             "
            "      Número Viagem             Tipo do Lançamento                  "
            "                                      Valor(R$)")


def _cred(data, hora, placa, tag, viagem, tipo, valor):
    return _linha(CAB_CRED, sp.COLUNAS["credito"],
                  [data, hora, placa, tag, viagem, tipo, valor],
                  sp.DIREITA["credito"])


def _resumo(placa, tag, plano, passagens, qtd_pass, vale, qtd_vale, total):
    return _linha(CAB_RESUMO, sp.COLUNAS["resumo"],
                  [placa, tag, "", plano, passagens, qtd_pass, "0,00", "0",
                   "0,00", "0", vale, qtd_vale, total], sp.DIREITA["resumo"])


def _tag(data, hora, conc, praca, cat, valor):
    return _linha(CAB_TAG, sp.COLUNAS["tag"],
                  [data, hora, conc, praca, cat, valor], sp.DIREITA["tag"])


def _vale(data, hora, conc, emb, praca, cat, viagem, valor):
    return _linha(CAB_VALE, sp.COLUNAS["vale"],
                  [data, hora, conc, emb, praca, cat, viagem, valor],
                  sp.DIREITA["vale"])


CAPA = "\n".join([
    "Nome: Transportadora Exemplo S/A",
    "Nº da Fatura: 12345678901",
    "Nº da Nota Fiscal: 999888777",
    "Código do Cliente: 1234567",
    "Data de Emissão: 03/08/26",
    "Data de Fechamento: 03/08/26",
    "Data de Vencimento: 10/08/26",
    "                          Resumo da sua Fatura",
    CAB_RESUMO,
    # 7 passagens de tag; o TOTAL (8 caracteres) é mais largo que a palavra
    # "TOTAL" e por isso transborda para a esquerda, como na fatura real.
    _resumo("AAA1B23", "0700000001", "29,90 D", "228,30 D", "7", "0,00", "0", "258,20 D"),
    # 6 de tag + 2 de vale = 8 na coluna Qtd de Passagens
    _resumo("BBB4C56", "0700000002", "0,00", "117,00 D", "8", "10,00 C", "2", "107,00 D"),
    "TOTAL 370,20 D",
])

# Seção de créditos + uma seção que este leitor NÃO conhece. As duas existem no
# fixture porque as duas quase custaram uma fatura: a de julho de 2026 trouxe
# "Outras Arrecadações", cujo título não casava com nada, e as linhas dela
# entraram como CRÉDITO — um débito somando dentro dos créditos, calado.
CREDITOS = LF.join([
    "Detalhamento de Plano Contratado",
    "TOTAL PLANO CONTRATADO 29,90 D",
    "Detalhamento de Créditos",
    CAB_CRED,
    _cred("17/07/26", "17:21:54", "AAA1B23", "0700000001", "103160243",
          "CONTESTAÇÃO PASSAGEM VP", "12,00 C"),
    # SEM HORA, SEM PLACA, SEM TAG: lançamento da FATURA, não do veículo. Na de
    # jul/2026 ele aparece em seção própria, mas nada garante que continue lá —
    # e a versão anterior estourava com `Invalid isoformat string: ''`,
    # derrubando as 402 páginas por causa de uma linha.
    _cred("12/06/26", "", "AJUSTE DE COBRANÇA", "", "", "", "3,00 C"),
    "TOTAL DE CRÉDITOS 15,00 C",
    # E uma seção INTEIRA que não é lida linha a linha: só o total dela entra na
    # conta. É assim que a de julho traz R$ 11.668,97 de encargo.
    "Detalhamento de Outras Arrecadações",
    CAB_CRED,
    _cred("12/06/26", "", "ENCARGOS DE COBRANÇA", "", "", "1", "20,00 D"),
    "TOTAL OUTRAS ARRECADAÇÕES 20,00 D",
])

LINHA_FALTANTE = _tag("18/07/26", "07:00:00", "CONCES EXEMPLO",
                      "BR101, KM001+350, NORTE, GARUVA - SC", "5", "28,50 D")

DETALHE = "\n".join([
    "Descritivo: AAA1B23 - Plano: EMPRESARIAL",
    "Detalhamento das Passagens por Pedágios",
    CAB_TAG,
    # cinco travessias na MESMA praça, em duas categorias: 6 eixos a R$ 34,20 e
    # categoria 61 a R$ 39,90 — a mesma tarifa por eixo, que é a prova no dado
    # de que 61 são SETE eixos. Cinco é o piso para a moda valer.
    _tag("15/07/26", "04:22:10", "CONCES EXEMPLO",
         "BR101, KM001+350, SUL, GARUVA - SC", "6", "34,20 D"),
    _tag("15/07/26", "14:22:10", "CONCES EXEMPLO",
         "BR101, KM001+350, SUL, GARUVA - SC", "6", "34,20 D"),
    _tag("16/07/26", "04:22:10", "CONCES EXEMPLO",
         "BR101, KM001+350, SUL, GARUVA - SC", "6", "34,20 D"),
    _tag("16/07/26", "05:13:01", "CONCES EXEMPLO",
         "BR101, KM001+350, SUL, GARUVA - SC", "61", "39,90 D"),
    _tag("17/07/26", "05:13:01", "CONCES EXEMPLO",
         "BR101, KM001+350, SUL, GARUVA - SC", "61", "39,90 D"),
    # uma travessia SOZINHA numa praça: não estabelece tarifa nenhuma
    _tag("17/07/26", "05:50:00", "OUTRA CONCES",
         "BR277, KM100+000, LESTE, PALMEIRA - PR", "4", "20,00 D"),
    # FREE FLOW: praça longa com a categoria GRUDADA no fim e a coluna Cat vazia
    _tag("17/07/26", "06:13:01", "RIOSP",
         "FREE FLOW, BR116, AEROPORTO KM219+165, SUL,5", "", "25,90 D"),
    "TOTAL PEDÁGIO 228,30 D",
    "Descritivo: BBB4C56 - Plano: EMPRESARIAL",
    "Detalhamento das Passagens por Pedágios",
    CAB_TAG,
    # quatro a R$ 28,50 e duas a R$ 1,50: a MÉDIA daria R$ 3,80 por eixo, um
    # valor que nunca foi cobrado de ninguém; a moda devolve R$ 5,70.
    LINHA_FALTANTE,
    _tag("19/07/26", "08:00:00", "CONCES EXEMPLO",
         "BR101, KM001+350, NORTE, GARUVA - SC", "5", "28,50 D"),
    _tag("19/07/26", "18:00:00", "CONCES EXEMPLO",
         "BR101, KM001+350, NORTE, GARUVA - SC", "5", "28,50 D"),
    _tag("20/07/26", "08:00:00", "CONCES EXEMPLO",
         "BR101, KM001+350, NORTE, GARUVA - SC", "5", "28,50 D"),
    _tag("20/07/26", "09:00:00", "CONCES EXEMPLO",
         "BR101, KM001+350, NORTE, GARUVA - SC", "5", "1,50 D"),
    _tag("21/07/26", "10:00:00", "CONCES EXEMPLO",
         "BR101, KM001+350, NORTE, GARUVA - SC", "5", "1,50 D"),
    "TOTAL PEDÁGIO 117,00 D",
    "Detalhamento das Passagens Vale Pedágio",
    CAB_VALE,
    # o par débito/crédito: o embarcador cobriu R$ 30 do que a praça cobrou R$ 20
    _vale("22/07/26", "11:00:00", "", "CLIENTE EXEMPLO",
          "BR101, KM001+350, SUL, GARUVA - SC", "5", "10622130", "30,00 C"),
    _vale("22/07/26", "11:00:00", "CONCES EXEMPLO", "CLIENTE EXEMPLO",
          "BR101, KM001+350, SUL, GARUVA - SC", "5", "10622130", "20,00 D"),
    # o último dígito da viagem cai SOZINHO na linha seguinte
    _linha(CAB_VALE, sp.COLUNAS["vale"], ["", "", "", "", "", "", "6", ""],
           sp.DIREITA["vale"]),
    "TOTAL VALE PEDÁGIO 10,00 C",
])


def paginas(detalhe: str = DETALHE, creditos: str = None) -> list[str]:
    return [CAPA, CREDITOS if creditos is None else creditos, detalhe]


def test_le_o_cabecalho_e_a_competencia_do_FECHAMENTO():
    cab = sp.interpretar(paginas())["cabecalho"]
    assert cab["numero_fatura"] == "12345678901"
    assert cab["numero_nf"] == "999888777"
    # A competência é a do fechamento, não a de hoje: reimportar em outubro a
    # fatura de agosto não pode reetiquetá-la.
    assert cab["competencia"] == "2026-08"
    assert str(cab["dt_vencimento"]) == "2026-08-10"


def test_a_fatura_sintetica_fecha_consigo_mesma():
    conf = sp.conferir(sp.interpretar(paginas()))
    assert conf["ok"], conf["achados"]
    valores = {x["rotulo"]: x for x in conf["linhas"]}
    assert valores["Passagens (tag)"]["declarado"] == 345.30
    assert valores["Passagens (tag)"]["detalhe"] == 345.30
    assert valores["Vale-pedágio"]["declarado"] == -10.00
    assert valores["Vale-pedágio"]["detalhe"] == -10.00


def test_conferencia_FICA_VERMELHA_quando_falta_travessia():
    """A prova de que os outros verdes valem alguma coisa.

    Conferência que passa por VACUIDADE é pior que conferência nenhuma: ela
    ocupa o lugar da que faria falta. A sabotagem aqui é uma travessia apagada,
    que é o modo de falhar que a importação existe para pegar — página não
    lida, cabeçalho diferente, corte no meio do PDF.
    """
    faltando = DETALHE.replace(LINHA_FALTANTE + "\n", "")
    assert faltando != DETALHE, "a sabotagem não removeu linha nenhuma"
    conf = sp.conferir(sp.interpretar(paginas(faltando)))
    assert not conf["ok"]
    assert any("Passagens" in a for a in conf["achados"]), conf["achados"]


def test_a_categoria_61_vale_SETE_eixos():
    """Sem isso a tarifa por eixo sai 16% baixa nessas linhas, e para MENOS."""
    trav = sp.interpretar(paginas())["travessias"]
    por_cat = {t["categoria"]: t for t in trav if t["tipo"] == "tag"}
    assert por_cat["6"]["eixos"] == 6
    assert por_cat["61"]["eixos"] == 7
    # e é isso que faz a tarifa por eixo bater entre as duas categorias
    assert round(por_cat["6"]["valor"] / por_cat["6"]["eixos"], 2) == 5.70
    assert round(por_cat["61"]["valor"] / por_cat["61"]["eixos"], 2) == 5.70


def test_praca_que_ENCOSTA_na_categoria_nao_perde_o_eixo():
    """Free flow: "...SUL,5" é praça + categoria grudadas, com a coluna vazia.

    Sem a separação, `eixos` sai nulo e a linha some da tarifa observada — e
    some CALADA, porque o valor continua certo.
    """
    trav = [t for t in sp.interpretar(paginas())["travessias"]
            if t["concessionaria"] == "RIOSP"]
    assert len(trav) == 1
    assert trav[0]["categoria"] == "5" and trav[0]["eixos"] == 5
    assert not (trav[0]["praca"] or "").endswith("5")


def test_o_TOTAL_do_resumo_nao_come_a_quantidade_ao_lado():
    """A coluna alinhada à direita transborda para a ESQUERDA.

    "306   766,80 D" cortado no deslocamento do cabeçalho virava quantidade
    30.674 e total R$ 6,80 — dois números plausíveis e errados.
    """
    resumo = {r["placa"]: r for r in sp.interpretar(paginas())["resumo"]}
    assert resumo["AAA1B23"]["total"] == 258.20
    assert resumo["AAA1B23"]["qtd_passagens"] == 7
    assert resumo["BBB4C56"]["vale"] == -10.00
    assert resumo["BBB4C56"]["qtd_vale"] == 2


def test_o_numero_da_viagem_que_quebra_em_duas_linhas_e_colado():
    """Truncado ele parece válido, e é isso que o torna pior que ausente."""
    vale = [t for t in sp.interpretar(paginas())["travessias"] if t["tipo"] == "vale"]
    assert len(vale) == 2, "a linha de continuação virou uma travessia"
    assert {t["viagem"] for t in vale} == {"10622130", "106221306"}


def test_o_vale_separa_concessionaria_de_embarcador():
    """Na linha de crédito a concessionária vem VAZIA, e o padrão antigo
    empurrava o embarcador para dentro da praça em metade das linhas."""
    vale = {t["dc"]: t for t in sp.interpretar(paginas())["travessias"]
            if t["tipo"] == "vale"}
    assert vale["C"]["embarcador"] == "CLIENTE EXEMPLO"
    assert vale["C"]["concessionaria"] is None
    assert vale["D"]["embarcador"] == "CLIENTE EXEMPLO"
    assert vale["D"]["concessionaria"] == "CONCES EXEMPLO"
    assert vale["C"]["praca"] == vale["D"]["praca"] == "BR101, KM001+350, SUL, GARUVA - SC"


@pytest.mark.parametrize("texto,esperado", [
    ("BR101, KM001+350, SUL, GARUVA - SC", ("BR101", 1.35, "SUL", "GARUVA", "SC")),
    ("SP160, KM24+260, SUL, S.B. DO CAMPO", ("SP160", 24.26, "SUL", "S.B. DO CAMPO", None)),
    ("FREE FLOW, BR116, MARG TIETÊ", (None, None, None, None, None)),
    ("ITATIAIA NORTE", (None, None, None, None, None)),
])
def test_a_praca_so_e_decomposta_quando_a_fatura_diz_rodovia_e_km(texto, esperado):
    """Praça nomeada só pela cidade fica com os campos VAZIOS.

    Inventar rodovia faria a tarifa ser comparada contra a praça errada, que é
    pior que não comparar — sai um desvio com cara de achado.
    """
    p = sp.partes_da_praca(texto)
    assert (p["rodovia"], p["km"], p["sentido"], p["cidade"], p["uf"]) == esperado


def test_arquivo_que_nao_e_fatura_recusa_com_motivo_legivel():
    with pytest.raises(sp.FaturaInvalida) as exc:
        sp.interpretar(["um PDF qualquer, sem nada disso"])
    assert "número da fatura" in str(exc.value)


# ── o que as faturas de mai, jun e jul de 2026 acrescentaram ────────────────
#
# Os quatro casos abaixo não vieram de leitura de código: vieram de rodar o
# parser, já pronto e verde, contra três faturas que ele nunca tinha visto.
# Três deles são defeitos que a fatura de agosto sozinha não revelaria.

def test_a_soma_das_secoes_e_o_total_da_fatura():
    """A conferência mais forte, e a que sobrevive à fatura crescer.

    Ela não precisa saber quais seções existem: soma TODAS as que a fatura
    imprimir. Vale nas quatro faturas reais, inclusive na de jul/2026, que
    trouxe duas seções que as outras não têm.
    """
    conf = sp.conferir(sp.interpretar(paginas()))
    total = next(x for x in conf["linhas"] if x["rotulo"] == "Total da fatura")
    assert total["declarado"] == 370.20
    assert total["detalhe"] == 370.20
    assert total["ok"]


def test_secao_DESCONHECIDA_nao_herda_a_anterior():
    """O defeito que custou a fatura de julho, e que não dava erro nenhum.

    "Outras Arrecadações" não estava no mapa de seções, então o título não
    casava com nada, `secao` continuava valendo "credito" e o débito de
    R$ 95,18 entrava somando DENTRO dos créditos. É a família do tipo novo do
    fornecedor caindo num balde silencioso.

    Aqui a seção é renomeada para uma que este leitor não conhece: as linhas
    dela têm de ficar de fora E o fato tem de virar achado.
    """
    creditos = CREDITOS.replace("Detalhamento de Outras Arrecadações",
                                "Detalhamento de Coisa Que Ainda Nao Existe")
    lido = sp.interpretar(paginas(creditos=creditos))
    assert lido["secoes_desconhecidas"] == ["Detalhamento de Coisa Que Ainda Nao Existe"]
    # o débito NÃO entrou nos créditos
    assert sorted(c["valor"] for c in lido["creditos"]) == [3.00, 12.00]
    conf = sp.conferir(lido)
    assert not conf["ok"]
    assert any("não conhece" in a for a in conf["achados"]), conf["achados"]


def test_lancamento_da_fatura_nao_tem_hora_nem_placa():
    """"ENCARGOS DE COBRANÇA": data, descrição e valor, mais nada.

    A primeira versão estourava com `Invalid isoformat string: ''` e derrubava
    a fatura inteira — 402 páginas perdidas por uma linha de R$ 95,18. E a hora
    fica NULA em vez de virar meia-noite: horário inventado vira gráfico.
    """
    cred = {c["descricao"]: c for c in sp.interpretar(paginas())["creditos"]}
    enc = cred["AJUSTE DE COBRANÇA"]
    assert enc["hora"] is None
    assert enc["placa"] is None and enc["tag"] is None
    assert enc["dc"] == "C" and enc["valor"] == 3.00
    assert str(enc["data"]) == "2026-06-12"


def test_o_credito_separa_a_tag_do_numero_da_viagem():
    """O cabeçalho de créditos tem SETE colunas, e eu declarava seis.

    Sem "Número Viagem" no meio, o span de "Tag" ia até "Tipo do Lançamento" e
    engolia o número da viagem: saía uma tag de vinte dígitos, plausível e
    errada, nas quatro faturas. Ninguém olhava para essa coluna, que é
    exatamente o que torna o defeito duradouro.
    """
    cred = {c["descricao"]: c for c in sp.interpretar(paginas())["creditos"]}
    c = cred["CONTESTAÇÃO PASSAGEM VP"]
    assert c["placa"] == "AAA1B23"
    assert c["tag"] == "0700000001"
    assert c["viagem"] == "103160243"
