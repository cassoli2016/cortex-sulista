# -*- coding: utf-8 -*-
"""A Smartec como FONTE do cadastro — o Detran que a casa JÁ paga.

POR QUE ELA E NÃO UM FORNECEDOR NOVO
====================================
Esta fonte substituiu uma integração paga que chegou a ser escrita e foi
DESFEITA em 08/09/2026, e a razão vale mais que o código: a consulta de placa
que se ia comprar (R$ 2,50 por veículo, ~R$ 3.600 pela frota) devolve o mesmo
que a Smartec já devolve — e a Smartec já está contratada, configurada e
coletando todo dia.

O que faltava não era fornecedor: era CHAMAR o que já existia.
`api/smartec/coleta.coletar_restricoes()` estava escrita, testada e nunca era
executada, porque não entrou em `coletar_tudo()` (ela consulta um renavam por
vez, e aquela rotina só faz o que devolve a frota inteira numa chamada). O
resultado é que `smt_restricoes` tinha ZERO linhas — roubo, furto, Renajud e
recall, que é o dado de maior valor da lista, simplesmente não eram coletados.

A LIÇÃO, que é a mesma do pedágio e da própria Smartec: **antes de contratar
fonte para um dado, procurar o dado no que a casa já assina.** Aqui o custo do
erro seria de milhares de reais por uma informação já paga.

O QUE A SMARTEC DEVOLVE, MEDIDO (08/09/2026)
============================================
`smt_veiculos` é o registro do DENATRAN, e é mais rico que o do ERP:

    renavam         '1187450682'
    chassi          '9536R8275LR004355'
    marca           'VW/19.360 CTC 4X2'      <- descritor COMPLETO
    tipo            'CAMINHÃO TRATOR'        <- espécie do DENATRAN
    cor             'BRANCA'
    ano_fabricacao  2019   ano_modelo  2020
    uf              'PR'

O CAMPO `marca` NÃO É A MARCA — é o descritor `MARCA/MODELO VERSÃO` inteiro,
do jeito que o DENATRAN o publica. Ele vai para `versao`, e não para `marca`,
por decisão declarada: partir a string no primeiro `/` daria marca='SR' num
semirreboque (SR é o prefixo de espécie, não o fabricante — 'SR/FACCHINI SRF
LOED' é um Facchini). Código sem tabela de domínio não vira rótulo inventado;
a marca decodificada continua vindo do ERP, que TEM tabela de domínio
(`public.marcaveiculo`, 40 linhas, casa 100%).

`smt_licenciamento` traz o MÊS de licenciamento — e só ele: `valor_taxa`,
`guia` e `guia_vencimento` vieram vazios em todas as linhas. Mês de
licenciamento NÃO é data de vencimento do CRLV, e mapeá-lo para
`crlv_vencimento` seria inventar uma data — pior que data nenhuma.

`smt_licencas` traz o vencimento do CRONOTACÓGRAFO, que é obrigação real de
frota e não existe em lugar nenhum do ERP.
"""
from __future__ import annotations

import logging

from .. import pglocal
from . import armazenamento as arm

log = logging.getLogger("cortex.equipamentos")

FONTE = "smartec"


def ler() -> list[dict]:
    """O que a Smartec sabe de cada placa, nos nomes de campo do cadastro.

    Lê do banco da CASA (`smt_*`), não da API: quem fala com a Smartec é
    `api/smartec/coleta.py`, e essa separação é o que permite reconstruir o
    cadastro sem rede nenhuma — e sem gastar chamada de um fornecedor que tem
    limite.

    O `FULL JOIN` é de propósito: um veículo pode estar em `smt_licencas` (tem
    cronotacógrafo) e não em `smt_veiculos` (a consulta de característica
    falhou naquele dia). Com `INNER` ele sumiria do cadastro, e sumir é a
    falha sem sintoma.
    """
    linhas = pglocal.query(
        "SELECT coalesce(v.placa, l.placa, lc.placa, r.placa) AS placa,"
        "       coalesce(v.renavam, l.renavam, lc.renavam, r.renavam) AS renavam,"
        "       v.chassi, v.marca AS descritor, v.tipo AS especie, v.cor,"
        "       v.ano_fabricacao, v.ano_modelo, v.uf,"
        "       l.mes           AS licenciamento_mes,"
        "       lc.cronotacografo,"
        "       r.tem_restricao, r.resumo AS restricao_resumo,"
        "       r.detalhe       AS restricao_detalhe,"
        "       r.comunicacao_venda, r.agente_financeiro"
        "  FROM smt_veiculos v"
        "  FULL JOIN smt_licenciamento l ON l.placa = v.placa"
        "  FULL JOIN smt_licencas     lc ON lc.placa = coalesce(v.placa, l.placa)"
        # RESTRICAO CASA POR RENAVAM, NAO POR PLACA: `gravar_restricoes` grava
        # a placa VAZIA (a API de restricoes so recebe renavam e nao devolve
        # placa). Um join por placa casaria ZERO linhas -- e zero restricao
        # se le como frota sem problema, que e a leitura errada mais cara
        # possivel. O `ltrim(...,'0')` porque a Smartec grava o renavam sem
        # zeros a esquerda e o ERP com.
        "  FULL JOIN smt_restricoes    r"
        "         ON ltrim(r.renavam, '0') = ltrim(coalesce(v.renavam, l.renavam, lc.renavam), '0')",
        esquema=arm.ESQUEMA)

    fora: list[dict] = []
    for r in linhas:
        placa = (r.get("placa") or "").strip().upper()
        if not placa:
            continue
        campos = {
            "renavam": (r.get("renavam") or "").strip() or None,
            "chassi": (r.get("chassi") or "").strip() or None,
            # O descritor DENATRAN inteiro. Ver o cabeçalho: ele NÃO é a marca.
            "versao": (r.get("descritor") or "").strip() or None,
            "especie": (r.get("especie") or "").strip() or None,
            "cor": (r.get("cor") or "").strip() or None,
            "ano_fabricacao": r.get("ano_fabricacao"),
            "ano_modelo": r.get("ano_modelo"),
            "uf": (r.get("uf") or "").strip() or None,
            "licenciamento_mes": r.get("licenciamento_mes"),
            "cronotacografo_vencimento": r.get("cronotacografo"),
            "tem_restricao": _impeditiva(r),
            "alienacao_fiduciaria": _alienacao(r),
            "restricoes": _restricoes(r),
        }
        campos = {k: v for k, v in campos.items() if v is not None and v != ""}
        fora.append({"placa": placa, "campos": campos, "payload": r})
    return fora


#: O que IMPEDE o veículo de rodar, ou exige ação hoje. Alienação fiduciária
#: NÃO está aqui de propósito — ver `_impeditiva`.
IMPEDITIVAS = ("ROUBO", "FURTO", "RENAJUD", "RECALL", "BLOQUEIO",
               "JUDICIAL", "APREEN", "BAIXA", "SINISTRO")


def _valores(no) -> list[str]:
    """Só os VALORES de uma estrutura aninhada, em caixa alta.

    ESTA FUNÇÃO EXISTE POR UM DEFEITO MEDIDO, e o defeito é instrutivo: a
    primeira versão procurava as palavras impeditivas no JSON SERIALIZADO do
    detalhe. Só que o bloco do SENATRAN tem CHAVES chamadas `Roubo`,
    `Renajud`, `Recall` e `Venda` — e elas vêm em toda resposta, com valor
    nulo. O texto casava sempre.

    Resultado na coleta real de 08/09/2026: **292 de 292 veículos
    classificados como restrição impeditiva**, incluindo os que respondiam
    "NADA CONSTA". Um painel em que tudo é vermelho não é um painel de risco:
    é ruído, e ensina a ignorar o vermelho justamente no dia em que um deles
    for verdade.

    Buscar em texto serializado é buscar nos nomes dos campos junto com o
    conteúdo. Aqui se anda pela estrutura e só o VALOR é lido.
    """
    if no is None:
        return []
    if isinstance(no, dict):
        fora = []
        for v in no.values():
            fora.extend(_valores(v))
        return fora
    if isinstance(no, (list, tuple)):
        fora = []
        for v in no:
            fora.extend(_valores(v))
        return fora
    texto = str(no).strip().upper()
    return [texto] if texto and texto not in ("NONE", "NULL") else []


def _texto_das_restricoes(r: dict) -> str:
    """Tudo que as duas fontes VALORARAM, num texto só.

    São DUAS fontes dentro da mesma resposta — o resumo do Detran e o bloco do
    SENATRAN — e elas DISCORDAM: medido em 19 veículos da frota (08/09/2026),
    6 tinham restrição numa e não na outra (3 em cada sentido). Não é uma
    delas estar errada: são registros diferentes, o estadual e o nacional.

    Por isso a leitura é a UNIÃO das duas, e não a escolha de uma. Escolher a
    "melhor" fonte perderia um terço dos casos — e num sentido perigoso,
    porque o que falta numa é justamente o que a outra tem.
    """
    partes = [str(r.get("restricao_resumo") or "").upper()]
    partes.extend(_valores(r.get("restricao_detalhe")))
    return " ".join(partes)


def _impeditiva(r: dict) -> bool | None:
    """Há restrição que IMPEÇA o veículo de rodar?

    NÃO é "há alguma restrição". Medido em 19 veículos: 10 têm restrição e
    **todas as 10 são alienação fiduciária** — veículo financiado, que numa
    transportadora é o estado normal de boa parte da frota. Somar as duas
    coisas num booleano só pintaria metade do painel de vermelho
    permanentemente, e vermelho permanente ensina a ignorar o vermelho.

    `None` quando não se consultou — e `None` nunca é pintado de verde.
    """
    if r.get("tem_restricao") is None:
        return None
    texto = _texto_das_restricoes(r)
    return any(m in texto for m in IMPEDITIVAS)


def _alienacao(r: dict) -> str | None:
    """O banco credor, quando o veículo é financiado.

    Informação útil (vender o ativo exige quitar) e que NÃO é alarme. Guardar
    o nome do agente, e não um booleano, porque a pergunta que se faz na
    prática é "com qual banco?".
    """
    if r.get("tem_restricao") is None:
        return None
    if "ALIENACAO" not in _texto_das_restricoes(r) and not r.get("agente_financeiro"):
        return None
    return (r.get("agente_financeiro") or "").strip() or "sim, credor não informado"


def _restricoes(r: dict) -> list | None:
    """A lista de restrições, só com o que a Smartec de fato respondeu.

    `tem_restricao` FALSO com lista vazia é uma resposta ("consultei, não
    há"); `tem_restricao` nulo é outra ("não consultei"). Devolver `[]` nos
    dois casos apagaria a diferença, e o painel pintaria de verde o que nunca
    foi olhado.

    O detalhe vem como jsonb (dict), não texto — por isso ele é percorrido por
    `_valores`, e não concatenado. Ver lá o defeito que isso evita.
    """
    if r.get("tem_restricao") is None:
        return None
    itens: list[dict] = []
    resumo = (r.get("restricao_resumo") or "").strip()
    if resumo and resumo.upper() != "NADA CONSTA":
        itens.append({"fonte": "Detran", "descricao": resumo})
    for valor in _valores(r.get("restricao_detalhe")):
        # "NADA CONSTA" e datas de atualização não são restrição.
        if valor == "NADA CONSTA" or _parece_data(valor):
            continue
        if not any(valor == i["descricao"].upper() for i in itens):
            itens.append({"fonte": "SENATRAN", "descricao": valor})
    for rotulo, chave in (("Comunicação de venda", "comunicacao_venda"),
                          ("Agente financeiro", "agente_financeiro")):
        v = (r.get(chave) or "").strip()
        if v:
            itens.append({"fonte": rotulo, "descricao": v})
    return itens


def _parece_data(texto: str) -> bool:
    """`05/09/2026` no meio da lista de restrições é carimbo, não restrição."""
    t = texto.replace("/", "").replace("-", "").replace(":", "").replace(" ", "")
    return t.isdigit() and len(t) >= 6


def sincronizar() -> dict:
    """Traz a Smartec para `eqp_fonte`. De graça: lê o banco da casa."""
    linhas = ler()
    n = arm.gravar_fontes(FONTE, linhas)
    log.info("equipamentos: %d equipamentos da Smartec", n)
    return {"lidos_da_smartec": n}


def cobertura() -> dict:
    """Quantas placas do cadastro a Smartec alcança — e quantas faltam.

    É o número que decide o próximo passo comercial: a Smartec cobre o que
    está cadastrado NA CONTA dela, não a frota inteira. Ampliar a conta é
    barato perto de comprar consulta avulsa, mas só se sabe quanto falta
    olhando os dois lados.
    """
    r = pglocal.um(
        "SELECT count(*) AS total,"
        "       count(f.placa) AS com_smartec"
        "  FROM eqp_equipamento e"
        "  LEFT JOIN (SELECT DISTINCT placa FROM eqp_fonte"
        "              WHERE fonte = 'smartec') f ON f.placa = e.placa"
        " WHERE e.ativo = true", esquema=arm.ESQUEMA) or {}
    total = int(r.get("total") or 0)
    tem = int(r.get("com_smartec") or 0)
    return {"total": total, "com_smartec": tem, "falta": total - tem,
            "percentual": round(100 * tem / total, 1) if total else None}
