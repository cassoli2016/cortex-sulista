# -*- coding: utf-8 -*-
"""Fatura do Sem Parar: o pedágio do TAG, que era o quarto número e o maior.

O QUE ESTA FATURA ACRESCENTA
============================
A tela de Validação de Pedágio nasceu com três números do ERP que não batem, e
com razão para não baterem (ver `validacao.py`). Faltava um quarto, e ele é o
maior de todos — medido na janela de 12 meses set/25 a ago/26:

    CT-e valortaxapedagio (cobrado do cliente) .. R$ 5.027.291
    coleta.valorpedagio   (a operação) ......... R$ 5.636.164
    valepedagio.valorcartao (adiantado) ........ R$ 1.913.238
    SEM PARAR, tag (contaapagar) ............... R$ 6.050.476

O dinheiro SEMPRE esteve no ERP: um título por mês em `contaapagar` para o CNPJ
04.088.208/0001-65, e o `numerotitulo` é o número da nota fiscal impressa na
fatura. O que não existia era a DECOMPOSIÇÃO — placa, praça, travessia. Sem ela
não dá para dizer de que veículo é o gasto, nem conferir tarifa nenhuma.

E O SEM PARAR NÃO É VALE-PEDÁGIO NESTE ERP
==========================================
Ele está cadastrado como administradora (códigos 172 e 175 de
`administradorapef`) e tem ZERO vales em 12 meses. Quem administra vale aqui é
TARGET, GPS PAMCARY e EFRETE. Procurar o gasto do tag em `valepedagio` não acha
nada — a mesma armadilha da RasterJOR, que morava em `sulista.rasterjor_*` e
não onde o nome do fornecedor aparecia.

O TAG PAGA SOBRETUDO PELO AGREGADO
==================================
A casa registrava "a frota própria passa por tag". É verdade e é incompleto: na
fatura de ago/2026, por `veiculo.utilizacaoveiculo`,

    agregado ..... 116 placas ... R$ 373.190  (78,5%)
    locação ......  32 placas ... R$  71.093  (15,0%)
    frota própria .  30 placas ... R$  30.836  ( 6,5%)

A LOCAÇÃO PRECISA APARECER SOZINHA. A primeira versão desta tela quebrava por
`tipofrota`, que só tem três valores e dobra o alugado dentro de "própria" —
ela dizia R$ 101.929 de frota própria onde são R$ 30.836, inflando o próprio em
3,3x e chamando caminhão alugado de nosso.

Se esse pedágio é ou não recobrado do agregado é pergunta de quem opera, e a
tela FAZ a pergunta em vez de respondê-la: `acertoviagemagregado_desconto` está
vazia (0 linhas) e a despesa do acerto traz R$ 9,4 mi em 12 meses lançados pela
própria Sulista, sem detalhe que separe pedágio de combustível.

A CATEGORIA 61 É 7 EIXOS — E ERRAR ISSO ERRA A TARIFA PARA MENOS
================================================================
As categorias vêm de 1 a 6, e também 61, 62 e 63. Não são códigos opacos: a
tarifa POR EIXO só fica constante lendo 61 como 7 eixos, 62 como 8 e 63 como 9
— confirmado em 191 das 207 praças que aparecem com mais de uma categoria (as
16 restantes são free flow, que cobra por veículo, e praça que reajustou no meio
do período). Em Garuva o passo é exato: 5 eixos R$ 28,50 · 6 eixos R$ 34,20 ·
categoria 61 R$ 39,90, todos a R$ 5,70 o eixo.

Categoria que este módulo não conhece NÃO vira eixo inventado: `eixos` sai nulo
e a tarifa por eixo daquela linha fica de fora das médias. Mesma regra da coluna
"Tipo (cód.)" da Manutenção.

A FATURA CONFERE A SI MESMA, E POR ISSO A IMPORTAÇÃO RECUSA
===========================================================
O documento traz um "Resumo da sua Fatura" por TAG e depois o detalhe por
PLACA. Os dois lados têm de fechar, e é o que `conferir()` exige antes de
qualquer gravação. Na fatura 26171585220 fecha ao centavo:

    Passagens (tag) .... R$ 475.118,92   detalhe R$ 475.118,92
    Vale-pedágio ....... R$   1.027,44 C detalhe R$   1.027,44 C
    Plano contratado ... R$   4.614,60
    Estacionamento ..... R$     246,40
    Créditos ........... R$   3.063,61 C
    TOTAL .............. R$ 475.888,87

A QUANTIDADE FECHA POR OUTRO CAMINHO, e vale saber qual: a coluna "Qtd" de
Passagens do resumo NÃO é o número de linhas de tag — ela soma tag + vale +
crédito de passagem (16.980 + 6.251 + 118 = 23.349). Descobri porque a conta não
fechava por 118, e os 118 eram exatamente os créditos dos tipos PASSAGEM e
CREDITO BENEFICIO VP.

Importar pela metade uma fatura de R$ 475 mil produziria um número plausível e
errado, que é a pior família de defeito desta casa. Por isso divergência é
RECUSA, com o que não bateu escrito, nunca um aviso ao lado do número torto.

DUAS PLACAS TÊM MAIS DE UMA TAG
===============================
BBG6G93 aparece com duas e NWP5C88 com três. O resumo é por TAG e o detalhe é
por PLACA, então a conferência soma o resumo POR PLACA — sem isso essas duas
acusam divergência que não existe.

POR QUE O TEXTO É FATIADO POR POSIÇÃO DE COLUNA
===============================================
A primeira versão lia as linhas por expressão regular e errou nas duas pontas
do documento, as duas vezes em silêncio:

  * na seção de VALE são quatro colunas antes da categoria (concessionária,
    embarcador, praça) e a concessionária vem VAZIA na linha de crédito. O
    padrão não-guloso parava nela e colava o embarcador DENTRO da praça, em
    metade das 6.251 linhas — com o valor certo, então nada acusava;
  * em free flow o nome da praça é longo e ENCOSTA na coluna da categoria
    ("...SUL,5"), e aí a linha não casava com padrão nenhum e sumia.

O cabeçalho é repetido em TODA página e diz onde cada coluna começa. Ler os
deslocamentos dele e fatiar por posição resolve os dois casos de uma vez e não
depende de quantas colunas a seção tem. É o mesmo princípio do corte por
marcador: o limite é DERIVADO do documento, nunca escolhido a olho.

E os deslocamentos são lidos POR PÁGINA porque eles mudam de página para
página — a 9 tem "Cat       Viagem" e a 10 tem "Cat        Viagem".

O NÚMERO DA VIAGEM QUEBRA EM DUAS LINHAS
========================================
No vale-pedágio o id da viagem tem 9 dígitos e não cabe na coluna: a fatura
imprime 8 na linha da travessia e o último SOZINHO na linha seguinte. Quem não
juntar grava `10622130` onde a viagem é `106221306` — um id truncado, que é
pior que um id ausente porque parece válido.

O QUE SÓ APARECEU AO RODAR CONTRA SEIS FATURAS QUE O PARSER NUNCA TINHA VISTO
============================================================================
Este leitor ficou verde lendo UMA fatura, a de ago/2026, com teste e tudo.
Depois vieram as de fev a jul, e elas acharam três defeitos — dois deles
mudos:

  * **A seção que eu não conhecia herdava a anterior.** A de jul/2026 tem
    "Detalhamento de Outras Arrecadações", título que não casava com nada:
    `secao` continuava valendo "credito" e um DÉBITO de R$ 95,18 entrava
    somando dentro dos créditos. Hoje todo título de seção é reconhecido
    (`RE_ABRE_SECAO`), o desconhecido ZERA o estado e vira achado. É a família
    do tipo novo do fornecedor caindo num balde silencioso.
  * **O cabeçalho de créditos sempre teve SETE colunas** e eu declarava seis:
    faltava "Número Viagem", então o span de "Tag" ia até "Tipo do Lançamento"
    e engolia os dois juntos. Saía uma tag de vinte dígitos nas quatro faturas,
    e ninguém olha para essa coluna — que é o que torna o defeito duradouro.
  * **Uma linha sem hora derrubava a fatura inteira.** "ENCARGOS DE COBRANÇA"
    não tem hora, placa nem tag, e `time.fromisoformat("")` estourava: 402
    páginas perdidas por causa de uma linha de R$ 95,18.

A lição, que já é conhecida nesta casa em outra roupa: fixture é escrita por
quem já sabe o que espera. O segundo documento REAL é o que acha o que o
primeiro escondia — e aqui foram três, sendo que dois não davam erro nenhum.

E A CONFERÊNCIA QUE SOBREVIVE À FATURA CRESCER é a soma das seções contra o
TOTAL. Ela não precisa saber quais seções existem: soma todas as que o
documento imprimir. Fecha nas sete faturas, inclusive na de julho, que tem duas
seções que as outras não têm. Se amanhã aparecer uma oitava seção e este leitor
não a estiver lendo, a diferença aparece ali em vez de sumir.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging
import re
import unicodedata

log = logging.getLogger(__name__)

# Quem emite. Nomeado porque é por ele que a fatura é reconhecida e porque é a
# chave que liga o gasto ao título mensal em `contaapagar`.
CNPJ_SEM_PARAR = "04088208000165"
ADMINISTRADORA = "SEM PARAR"

# Ver o bloco da docstring: a tarifa por eixo só fica constante com esta leitura.
EIXOS_POR_CATEGORIA = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
                       "61": 7, "62": 8, "63": 9}

# Um centavo de folga: os totais impressos são somas de valores de dois
# decimais, então divergência de verdade nunca é fração de centavo.
TOLERANCIA = 0.01

# Nomes de coluna procurados no cabeçalho de cada página. São PREFIXOS do rótulo
# impresso (evitam depender de acento e de "(R$)"), buscados em ordem — por isso
# "Qtd", que se repete, funciona.
COLUNAS = {
    "tag": ["Data", "Hora", "Concession", "Pra", "Cat", "Valor"],
    "vale": ["Data", "Hora", "Concession", "Embarcador", "Pra", "Cat", "Viagem", "Valor"],
    # "Número Viagem" existe e eu não a declarava: sem ela o span de "Tag"
    # ia até "Tipo do Lançamento" e engolia o número da viagem junto com a
    # tag. Saía uma tag de 20 dígitos, plausível e errada, nas quatro faturas.
    "credito": ["Data", "Hora", "Placa", "Tag", "Número Viagem",
                "Tipo do Lan", "Valor"],
    # "Pref." e "Plano Contratado" são DUAS colunas, e a primeira vem vazia em
    # toda linha desta fatura. Tratá-las como uma só desloca todo o resto.
    "resumo": ["Placa", "Tag", "Pref.", "Plano Contratado", "Passagens", "Qtd",
               "Estacionamento", "Qtd", "Estabelecimento", "Qtd",
               "Vale Ped", "Qtd", "TOTAL"],
}

# Colunas numéricas, alinhadas à DIREITA: nelas o valor pode ser mais largo que
# o rótulo e começar antes dele. Ver `fatiar`.
DIREITA = {
    "tag": frozenset({5}),                    # Valor
    "vale": frozenset({6, 7}),                # Viagem, Valor
    "credito": frozenset({6}),                # Valor
    "resumo": frozenset({3, 4, 5, 6, 7, 8, 9, 10, 11, 12}),
}

SECOES = {
    "Detalhamento das Passagens por Ped": "tag",
    "Detalhamento das Passagens Vale Ped": "vale",
    "Detalhamento de Cr": "credito",
    "Detalhamento das Estadias": "estadia",
    "Detalhamento de Plano Cont": "plano",
    # Só na fatura de jul/2026, e só porque ela atrasou: R$ 11.668,97 de
    # encargo e R$ 95,18 de "outras arrecadações". Não são lidas linha a
    # linha — o total impresso basta para a fatura fechar —, mas PRECISAM
    # existir aqui, pelo motivo do parágrafo abaixo.
    "Detalhamento de Encargos": "encargo",
    "Detalhamento de Outras Arrecada": "outras",
    "Resumo da sua Fatura": "resumo",
    "Descritivo de Valores": "descritivo",
}

# SEÇÃO QUE EU NÃO CONHEÇO NÃO PODE HERDAR A ANTERIOR. Enquanto "Outras
# Arrecadações" não estava no mapa, o título dela não casava com nada, `secao`
# continuava valendo "credito" e as linhas dela entravam como crédito — um
# débito de R$ 95,18 somando dentro dos créditos, sem erro nenhum. É a família
# do tipo novo do fornecedor caindo num balde silencioso.
#
# Toda linha que ABRE seção é reconhecida por este padrão, mesmo a que ainda
# não existe; a desconhecida zera o estado e vira ACHADO na conferência.
RE_ABRE_SECAO = re.compile(r"^\s*(Detalhamento|Descritivo|Resumo)\b.*$")

RE_DESCRITIVO = re.compile(r"^\s*Descritivo:\s*([A-Z0-9]{7})\s*-\s*Plano:\s*(.*)$")
RE_TOTAL = re.compile(r"^\s*TOTAL\b\s*(?:DE\s+)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ ]*?)\s*([\d.,]+)\s*([DC])?\s*$")
RE_DATA = re.compile(r"^\s*\d{2}/\d{2}/\d{2}\b")
RE_PLACA = re.compile(r"^[A-Z]{3}\d[A-Z0-9]\d{2}$")
RE_VALOR_DC = re.compile(r"^([\d.,]+)\s*([DC])?$")

# "BR116, KM057+000, SUL, CAMPINA GDE SUL" -> rodovia, km, sentido, cidade.
# Depois do "+" vêm METROS: KM001+350 é o km 1,350.
RE_PRACA = re.compile(
    r"^([A-Z]{2}\s?\d{3})\s*,\s*KM\s?(\d+)(?:\s*\+\s*(\d+))?\s*,?\s*"
    r"(NORTE|SUL|LESTE|OESTE)?\s*,?\s*(.*)$")


class FaturaInvalida(Exception):
    """O arquivo não é uma fatura Sem Parar legível, ou não fecha consigo mesma."""


def _sem_acento(txt: str) -> str:
    n = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in n if not unicodedata.combining(c))


def _num(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


def _com_sinal(valor: float, dc: str | None) -> float:
    """Crédito é negativo. A fatura marca D/C em coluna própria, nunca com sinal."""
    return -valor if dc == "C" else valor


def _data(txt: str) -> dt.date:
    """dd/mm/aa da fatura. Século fixo em 2000 — não há fatura de 1998 aqui."""
    d, m, a = txt.split("/")
    return dt.date(2000 + int(a), int(m), int(d))


def _valor_dc(txt: str) -> tuple[float, str | None]:
    m = RE_VALOR_DC.match((txt or "").strip())
    if not m:
        raise FaturaInvalida(f"valor ilegível na fatura: {txt!r}")
    return _num(m.group(1)), m.group(2)


def _inteiro(txt: str) -> int:
    t = (txt or "").strip()
    return int(t) if t.isdigit() else 0


# ── fatiar por coluna, e não por expressão regular ──────────────────────────

def colunas(cabecalho: str, nomes: list[str]) -> list[int] | None:
    """Onde cada coluna começa, lido do cabeçalho REAL da página."""
    pos, de = [], 0
    for nome in nomes:
        i = cabecalho.find(nome, de)
        if i < 0:
            return None
        pos.append(i)
        de = i + len(nome)
    return pos


def fatiar(linha: str, pos: list[int], direita: frozenset[int] = frozenset()) -> list[str]:
    """Recorta a linha nos deslocamentos das colunas.

    A última vai até o fim; as demais até o começo da seguinte. É isto que faz
    o nome de praça que ENCOSTA na categoria ("...SUL,5") sair certo: o corte
    vem do cabeçalho, não de onde o texto parece acabar.

    HÁ DOIS TRANSBORDOS, E ELES PEDEM TRATAMENTOS OPOSTOS. Texto alinhado à
    ESQUERDA transborda para a DIREITA e invade a coluna seguinte: é o caso da
    praça de free flow, e ali o corte duro do cabeçalho é exatamente o certo.
    Número alinhado à DIREITA transborda para a ESQUERDA, porque o valor é mais
    largo que o rótulo: "TOTAL" tem 5 caracteres e "766,80 D" tem 8, então ele
    começa 3 posições ANTES do cabeçalho e o corte duro o partia em "306   76"
    e "6,80 D" — a quantidade virava 30.674 e o total virava R$ 6,80.

    Por isso as colunas numéricas são declaradas em `direita`: nelas o começo
    recua até o início do token. Aplicar o recuo em toda coluna desfaria o
    primeiro caso; não aplicar em nenhuma quebra o segundo.
    """
    ini = list(pos)
    for i in sorted(direita):
        limite = ini[i - 1] + 1 if i else 0
        while ini[i] > limite and ini[i] - 1 < len(linha) and not linha[ini[i] - 1].isspace():
            ini[i] -= 1
    fim = ini[1:] + [len(linha) + 1]
    return [linha[a:b].strip() for a, b in zip(ini, fim)]


def partes_da_praca(txt: str) -> dict:
    """Rodovia, km, sentido e cidade a partir do texto da praça.

    Free flow e praça nomeada só pela cidade ("ITATIAIA NORTE") não seguem o
    padrão: voltam com os campos vazios e o texto cru preservado. Inventar
    rodovia para elas seria afirmar o que a fatura não diz — e é por rodovia +
    km que se casa com o cadastro do ERP, então um palpite aqui vira tarifa
    comparada contra a praça errada.
    """
    vazio = {"rodovia": None, "km": None, "sentido": None, "cidade": None, "uf": None}
    limpo = _sem_acento(txt or "").upper().strip()
    limpo = re.sub(r"^(FREE FLOW|F\. FLOW)\s*,?\s*", "", limpo).strip(" ,")
    m = RE_PRACA.match(limpo)
    if not m:
        return vazio
    km = float(m.group(2)) + (float(m.group(3)) / 1000.0 if m.group(3) else 0.0)
    cidade = (m.group(5) or "").strip(" ,-")
    # "GARUVA - SC" traz a UF colada na cidade. Separar não é cosmético: a UF é
    # coluna própria no cadastro do ERP, e um campo chamado `cidade` que às
    # vezes carrega o estado e às vezes não vira filtro com duas linhas para o
    # mesmo lugar.
    uf = None
    m2 = re.match(r"^(.*?)\s*-\s*([A-Z]{2})$", cidade)
    if m2:
        cidade, uf = m2.group(1).strip(), m2.group(2)
    return {"rodovia": m.group(1).replace(" ", ""), "km": km,
            "sentido": m.group(4) or None, "cidade": cidade or None, "uf": uf}


# ── leitura ─────────────────────────────────────────────────────────────────

_CAMPOS_CAB = [
    ("numero_fatura", r"N[ºo°]?\s*da Fatura:\s*(\S+)"),
    ("numero_nf", r"N[ºo°]?\s*da Nota Fiscal:\s*(\S+)"),
    ("codigo_cliente", r"C[óo]digo do Cliente:\s*(\S+)"),
]
_DATAS_CAB = [
    ("dt_emissao", r"Data de Emiss[ãa]o:\s*(\d{2}/\d{2}/\d{2})"),
    ("dt_fechamento", r"Data de Fechamento:\s*(\d{2}/\d{2}/\d{2})"),
    ("dt_vencimento", r"Data de Vencimento:\s*(\d{2}/\d{2}/\d{2})"),
]


def _cabecalho(primeira: str) -> dict:
    out: dict = {"administradora": ADMINISTRADORA, "cnpj_emissor": CNPJ_SEM_PARAR}
    for campo, padrao in _CAMPOS_CAB:
        m = re.search(padrao, primeira)
        out[campo] = m.group(1).strip() if m else None
    for campo, padrao in _DATAS_CAB:
        m = re.search(padrao, primeira)
        out[campo] = _data(m.group(1)) if m else None
    if not out.get("numero_fatura"):
        raise FaturaInvalida("não achei o número da fatura na primeira página — "
                             "este PDF é do Sem Parar Empresas?")
    # A competência é a do FECHAMENTO, não a de hoje: reimportar em outubro a
    # fatura de agosto não pode reetiquetá-la.
    ref = out.get("dt_fechamento") or out.get("dt_emissao")
    out["competencia"] = ref.strftime("%Y-%m") if ref else None
    return out


DESCONHECIDA = "?"


def _secao_de(linha: str) -> str | None:
    """A seção que esta linha abre, `DESCONHECIDA` para título novo, ou None.

    O sentinela é o que impede a seção nova de ser lida como a anterior.
    """
    t = linha.strip()
    for prefixo, chave in SECOES.items():
        if t.startswith(prefixo):
            return chave
    return DESCONHECIDA if RE_ABRE_SECAO.match(linha) else None


def _resumo(campos: list[str]) -> dict | None:
    if len(campos) < 13 or not RE_PLACA.match(campos[0]):
        return None
    plano, dcp = _valor_dc(campos[3])
    pas, dcs = _valor_dc(campos[4])
    est, dce = _valor_dc(campos[6])
    eab, dcb = _valor_dc(campos[8])
    vale, dcv = _valor_dc(campos[10])
    tot, dct = _valor_dc(campos[12])
    return {"placa": campos[0], "tag": campos[1] or None,
            "plano": _com_sinal(plano, dcp),
            "passagens": _com_sinal(pas, dcs), "qtd_passagens": _inteiro(campos[5]),
            "estacionamento": _com_sinal(est, dce), "qtd_estacionamento": _inteiro(campos[7]),
            "estabelecimento": _com_sinal(eab, dcb), "qtd_estabelecimento": _inteiro(campos[9]),
            "vale": _com_sinal(vale, dcv), "qtd_vale": _inteiro(campos[11]),
            "total": _com_sinal(tot, dct)}


def _travessia(campos: list[str], tipo: str, placa: str, npag: int) -> dict:
    if tipo == "tag":
        data, hora, conc, praca, cat, valor = campos[:6]
        emb = viagem = ""
    else:
        data, hora, conc, emb, praca, cat, viagem, valor = campos[:8]
    val, dc = _valor_dc(valor)
    cat = (cat or "").strip()
    praca = (praca or "").strip()
    if not cat:
        # Em free flow o nome da praça é longo e o PDF gruda a categoria NELE,
        # deixando a coluna Cat vazia: "...AEROPORTO KM219+165, SUL,5". O corte
        # por cabeçalho não separa isso porque os dois caracteres estão no mesmo
        # bloco de texto, à esquerda do começo da coluna. Toda travessia tem
        # categoria, então dígito no fim da praça COM a coluna vazia é a
        # categoria — e sem isso essas linhas ficariam sem eixo, que é o que
        # divide o valor para achar a tarifa. São 5 em 16.980.
        m = re.search(r"(\d{1,2})$", praca)
        if m:
            cat, praca = m.group(1), praca[:m.start()].rstrip()
    if cat and cat not in EIXOS_POR_CATEGORIA:
        log.info("categoria de pedágio desconhecida: %r (página %d)", cat, npag)
    return {"pagina": npag, "tipo": tipo, "placa": placa,
            "ts": dt.datetime.combine(_data(data), dt.time.fromisoformat(hora)),
            "concessionaria": (conc or "").strip() or None,
            "embarcador": (emb or "").strip() or None,
            "praca": praca or None,
            "categoria": cat or None, "eixos": EIXOS_POR_CATEGORIA.get(cat),
            "viagem": (viagem or "").strip() or None,
            "valor": val, "dc": dc or "D",
            **partes_da_praca(praca or "")}


def _credito(campos: list[str], npag: int) -> dict:
    """Uma linha da seção de créditos — e ela tem DUAS formas.

    A comum é por veículo: data, hora, placa, tag, tipo do lançamento, valor.

    A outra é lançamento da FATURA INTEIRA, e só apareceu na de jul/2026:
    "ENCARGOS DE COBRANÇA", R$ 95,18 D, **sem hora, sem placa e sem tag**, com
    a descrição começando na coluna da placa e transbordando pelas seguintes.
    A primeira versão estourava nela com `Invalid isoformat string: ''` e
    derrubava a fatura inteira — 382 páginas perdidas por uma linha de 95 reais.

    Duas decisões, e as duas são sobre não inventar dado:
      * a hora fica NULA em vez de virar meia-noite (ver o cabeçalho da
        migration 0030);
      * quando a coluna da placa não contém uma placa, ela NÃO é placa: as
        colunas do meio são remontadas como descrição, porque o texto
        atravessou fronteira de coluna.
    """
    val, dc = _valor_dc(campos[6])
    hora = (campos[1] or "").strip()
    placa = (campos[2] or "").strip()
    if placa and RE_PLACA.match(placa):
        tag = (campos[3] or "").strip() or None
        viagem = (campos[4] or "").strip() or None
        descricao = campos[5] or ""
    else:
        # Lançamento da FATURA, não do veículo: o texto começa na coluna da
        # placa e atravessa as seguintes. Juntar as colunas devolve o texto —
        # os espaços entre elas são preenchimento, e o `split()` os come.
        placa = tag = viagem = None
        descricao = " ".join(campos[2:6])
    return {"pagina": npag, "data": _data(campos[0]),
            "hora": dt.time.fromisoformat(hora) if hora else None,
            "placa": placa or None, "tag": tag, "viagem": viagem,
            "descricao": " ".join(descricao.split()) or None,
            "valor": val, "dc": dc or "C"}


def ler(nome: str, bruto: bytes) -> dict:
    """PDF em memória -> cabeçalho, resumo por tag, travessias e créditos.

    Não grava nada e não fala com banco nenhum. Quem decide se a fatura entra é
    `conferir()`.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependência declarada
        raise FaturaInvalida("pypdf não está instalado nesta máquina.") from exc

    try:
        leitor = PdfReader(io.BytesIO(bruto))
        paginas = [(p.extract_text(extraction_mode="layout") or "") for p in leitor.pages]
    except Exception as exc:  # noqa: BLE001
        raise FaturaInvalida(
            f"não foi possível ler o PDF ({type(exc).__name__}).") from exc

    lido = interpretar(paginas)
    lido["cabecalho"].update({"arquivo_nome": nome, "paginas": len(paginas),
                              "arquivo_sha256": hashlib.sha256(bruto).hexdigest()})
    return lido


def interpretar(paginas: list[str]) -> dict:
    """O miolo da leitura, sobre o TEXTO já extraído de cada página.

    Separado de `ler()` de propósito: assim o teste alimenta páginas sintéticas
    e exercita o parser inteiro sem precisar de um PDF de verdade. E um PDF de
    verdade aqui seria uma fatura da empresa — placas, praças e valores — num
    repositório PÚBLICO, que é o que a regra do botão de report já proíbe.
    """
    if not paginas:
        raise FaturaInvalida("o PDF não tem página nenhuma.")

    cab = _cabecalho(paginas[0])
    placa: str | None = None
    secao: str | None = None
    pos: list[int] | None = None
    travessias: list[dict] = []
    creditos: list[dict] = []
    resumo: list[dict] = []
    impressos: dict[str, float] = {}
    desconhecidas: set[str] = set()

    for npag, texto in enumerate(paginas, start=1):
        for linha in texto.splitlines():
            if not linha.strip():
                continue
            m = RE_DESCRITIVO.match(linha)
            if m:
                placa, secao, pos = m.group(1), None, None
                continue
            achou_secao = _secao_de(linha)
            if achou_secao:
                if achou_secao == DESCONHECIDA:
                    desconhecidas.add(" ".join(linha.split()))
                secao, pos = achou_secao, None
                continue
            m = RE_TOTAL.match(linha)
            if m:
                rot = " ".join(m.group(1).split()).upper() or "FATURA"
                impressos[rot] = impressos.get(rot, 0.0) + _com_sinal(_num(m.group(2)),
                                                                     m.group(3))
                continue
            if secao not in COLUNAS:
                continue
            if pos is None:
                pos = colunas(linha, COLUNAS[secao])
                continue
            campos = fatiar(linha, pos, DIREITA[secao])
            if secao == "resumo":
                lido = _resumo(campos)
                if lido:
                    resumo.append(lido)
                continue
            if not RE_DATA.match(campos[0] + " "):
                # Linha de continuação: o id da viagem tem 9 dígitos e o último
                # cai sozinho na linha seguinte. Só ele, e só colando na última
                # travessia lida — qualquer outra coluna preenchida aqui seria
                # linha desconhecida, e aí é melhor ignorar do que adivinhar.
                if (secao == "vale" and travessias and len(campos) >= 7
                        and campos[6].isdigit()
                        and not any(campos[i] for i in (0, 1, 2, 3, 4, 5))):
                    travessias[-1]["viagem"] = (travessias[-1]["viagem"] or "") + campos[6]
                continue
            if secao == "credito":
                # Os créditos vêm ANTES do primeiro "Descritivo:" e trazem a
                # placa em COLUNA PRÓPRIA. Exigir a placa de contexto aqui
                # rejeitaria a fatura inteira na página 6.
                creditos.append(_credito(campos, npag))
                continue
            if placa is None:
                raise FaturaInvalida(
                    f"travessia na página {npag} sem placa: o \"Descritivo:\" da "
                    "seção não foi lido, e gravar sem placa perderia de quem é o gasto.")
            travessias.append(_travessia(campos, secao, placa, npag))

    if not resumo or not travessias:
        raise FaturaInvalida(
            "o arquivo não parece uma fatura do Sem Parar: não achei o "
            '"Resumo da sua Fatura" nem o detalhamento das passagens.')

    return {"cabecalho": cab, "resumo": resumo, "travessias": travessias,
            "creditos": creditos, "totais_impressos": impressos,
            "secoes_desconhecidas": sorted(desconhecidas)}


# ── a fatura conferindo a si mesma ──────────────────────────────────────────

def _soma(linhas: list[dict], **filtro) -> float:
    return round(sum(_com_sinal(x["valor"], x["dc"]) for x in linhas
                     if all(x.get(k) == v for k, v in filtro.items())), 2)


def conferir(lido: dict) -> dict:
    """Confronta o DETALHE contra o RESUMO que a própria fatura imprime.

    Devolve `{"ok": bool, "achados": [...], "linhas": [...]}`. Quem chama recusa
    a importação quando `ok` é falso: uma fatura de meio milhão importada pela
    metade produz número plausível e errado, que é o defeito que esta casa mais
    paga caro.
    """
    resumo, trav, cred = lido["resumo"], lido["travessias"], lido["creditos"]

    # O resumo é por TAG e o detalhe é por PLACA — duas placas têm mais de uma
    # tag, e sem somar por placa elas acusam divergência que não existe.
    por_placa: dict[str, dict] = {}
    for r in resumo:
        a = por_placa.setdefault(r["placa"], {"passagens": 0.0, "vale": 0.0,
                                              "qtd_passagens": 0, "qtd_vale": 0})
        a["passagens"] += r["passagens"]
        a["vale"] += r["vale"]
        a["qtd_passagens"] += r["qtd_passagens"]
        a["qtd_vale"] += r["qtd_vale"]

    linhas = []

    def _cmp(rotulo: str, declarado: float, detalhe: float, unidade: str = "R$"):
        dif = round(detalhe - declarado, 2)
        linhas.append({"rotulo": rotulo, "declarado": round(declarado, 2),
                       "detalhe": round(detalhe, 2), "diferenca": dif,
                       "unidade": unidade, "ok": abs(dif) <= TOLERANCIA})
        return linhas[-1]

    _cmp("Passagens (tag)", sum(a["passagens"] for a in por_placa.values()),
         _soma(trav, tipo="tag"))
    _cmp("Vale-pedágio", sum(a["vale"] for a in por_placa.values()),
         _soma(trav, tipo="vale"))
    _cmp("Créditos", lido["totais_impressos"].get("CRÉDITOS", 0.0), _soma(cred))

    _cmp("Quantidade de vale", sum(a["qtd_vale"] for a in por_placa.values()),
         sum(1 for x in trav if x["tipo"] == "vale"), "linhas")

    # A "Qtd" de Passagens do resumo NÃO é o número de linhas de tag: ela soma
    # tag + vale + parte dos créditos (16.980 + 6.251 + 118 = 23.349). QUAIS
    # créditos entram eu não sei dizer — nesta fatura ficam de fora exatamente
    # as 2 "CONTESTAÇÃO PASSAGEM VP", e uma regra tirada de duas linhas de um
    # único documento é palpite, não régua. Então a conferência afirma só o que
    # a estrutura garante: o detalhe tem de cobrir as travessias declaradas, e
    # a folga não pode passar do número de créditos. Isso ainda pega o que
    # precisa ser pego — página não lida derruba o piso na hora.
    qtd_decl = sum(a["qtd_passagens"] for a in por_placa.values())
    folga = qtd_decl - len(trav)
    linhas.append({
        "rotulo": "Quantidade de passagens", "declarado": qtd_decl,
        "detalhe": len(trav), "diferenca": -folga, "unidade": "linhas",
        "ok": 0 <= folga <= len(cred),
        "nota": f"a fatura conta {qtd_decl} passagens; li {len(trav)} travessias "
                f"e {len(cred)} créditos, e a diferença de {folga} cabe nos créditos"})

    # A CONFERÊNCIA MAIS FORTE DA FATURA, e a que sobrevive a ela crescer: a
    # soma dos totais de SEÇÃO tem de dar o TOTAL da fatura. Vale em todas as
    # quatro lidas até aqui, inclusive na de jul/2026, que trouxe duas seções
    # que as outras não têm (encargos R$ 11.668,97 e outras arrecadações
    # R$ 95,18) e mesmo assim fecha.
    #
    # Ela é forte porque não precisa saber quais seções existem: soma TODAS as
    # que a fatura imprimir. Uma seção nova entra na conta sozinha, e se eu não
    # a estiver lendo, a diferença aparece aqui em vez de sumir.
    impressos = dict(lido["totais_impressos"])
    total = impressos.pop("FATURA", None)
    if total is not None:
        _cmp("Total da fatura", total, round(sum(impressos.values()), 2))

    achados = [f"{x['rotulo']}: a fatura declara "
               f"{x['declarado']:,.2f} e o detalhe soma {x['detalhe']:,.2f} "
               f"({x['diferenca']:+,.2f} {x['unidade']})".replace(",", "·")
               for x in linhas if not x["ok"]]

    # Seção que o parser não conhece é ACHADO, nunca silêncio: foi assim que
    # "Outras Arrecadações" entrou como crédito na fatura de julho.
    for titulo in lido.get("secoes_desconhecidas") or []:
        achados.append(f"seção que este leitor não conhece: {titulo!r} — as "
                       "linhas dela não foram lidas")

    placas_resumo = set(por_placa)
    placas_detalhe = {x["placa"] for x in trav}
    orfas = sorted(placas_detalhe - placas_resumo)
    if orfas:
        achados.append("placas no detalhe que não estão no resumo: "
                       + ", ".join(orfas[:8]))
    return {"ok": not achados, "achados": achados, "linhas": linhas,
            "placas": len(placas_resumo), "tags": len(resumo)}
