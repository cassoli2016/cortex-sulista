# -*- coding: utf-8 -*-
"""A precedência: de várias fontes discordando, um cadastro só.

É a regra difícil do módulo, e por isso vive sozinha, num arquivo que não fala
com rede nem com o ERP — dá para testá-la inteira com dicionários.

O QUE ELA FAZ
=============
Para cada placa e cada campo do catálogo (`campos.py`), percorre a precedência
do campo e fica com o valor da PRIMEIRA fonte que tiver um. Grava o valor em
`eqp_equipamento` e grava, junto, QUEM venceu, em `origem`.

DUAS DECISÕES QUE PARECEM DETALHE E NÃO SÃO
===========================================

**1. Vazio não vence.** Uma fonte que respondeu `""` ou `None` não "respondeu
o campo" — ela não tem o campo. Se vazio vencesse, a APIBrasil devolvendo
`cor: ""` apagaria a cor que a Smartec tem, e o cadastro pioraria a cada
coleta nova, em silêncio. Quem filtra é a própria fonte, ao gravar (ver
`erp.ler`), e a consolidação confere de novo — a defesa é dupla de propósito,
porque o custo do engano é destruir dado bom.

**2. Divergência não é resolvida em silêncio.** Quando duas fontes têm o campo
e discordam, a precedência escolhe — mas a discordância é REGISTRADA
(`divergencias()`), porque ela quase sempre significa cadastro furado, e é o
achado mais valioso desta integração. O ERP tem chassi em 98–100% da frota;
saber que 100% está PREENCHIDO não diz nada sobre estar CORRETO, e só o
confronto com o Detran responde isso. Desempatar e calar esconderia
exatamente o que se foi buscar.

Nada é desempatado sozinho e apagado — é o mesmo princípio do plano de
manutenção com marcador furado e dos números de frota repetidos em
`api/frota_identidade.py`: mostrar com a evidência ao lado.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import armazenamento as arm
from .campos import CAMPOS, POR_NOME

log = logging.getLogger("cortex.equipamentos")

#: Campos que a consolidação escreve em `eqp_equipamento`, na ordem do catálogo.
COLUNAS = tuple(c["nome"] for c in CAMPOS)


def _vazio(valor) -> bool:
    """`0` e `False` NÃO são vazio. Só `None` e texto em branco são.

    Escrever `if not valor` aqui faria tara zero e `licenciado=False`
    desaparecerem do cadastro, e um `False` que some vira `None` — que a tela
    lê como "não consultado". Um veículo NÃO licenciado apareceria como
    "não sei", que é o oposto do que se precisa saber.
    """
    if valor is None:
        return True
    if isinstance(valor, str) and not valor.strip():
        return True
    if isinstance(valor, (list, dict)) and len(valor) == 0:
        return True
    return False


def _converter(valor, tipo: str):
    """Texto digitado e JSON de fornecedor viram o tipo da coluna.

    Num lugar só. A conversão espalhada é como um `ano` chega ao banco como
    `'2022 '` numa fonte e `2022` noutra, e as duas passam a divergir sem
    divergir.

    Valor que não converte volta `None` e é tratado como ausente — nunca é
    gravado cru numa coluna tipada, que seria erro de transação e derrubaria a
    consolidação inteira por causa de uma placa.
    """
    if _vazio(valor):
        return None
    try:
        if tipo == "inteiro":
            if isinstance(valor, bool):
                return None
            return int(str(valor).strip().split(".")[0].split(",")[0])
        if tipo == "decimal":
            if isinstance(valor, Decimal):
                return valor
            texto = str(valor).strip().replace(".", "").replace(",", ".") \
                if _parece_pt_br(valor) else str(valor).strip()
            return Decimal(texto)
        if tipo == "booleano":
            if isinstance(valor, bool):
                return valor
            texto = str(valor).strip().lower()
            if texto in ("1", "true", "sim", "s", "t", "y", "yes"):
                return True
            if texto in ("0", "false", "nao", "não", "n", "f", "no"):
                return False
            return None
        if tipo == "data":
            if isinstance(valor, datetime):
                return valor.date()
            if isinstance(valor, date):
                return valor
            return _data(str(valor).strip())
        if tipo == "json":
            return valor
        texto = str(valor).strip()
        return texto or None
    except (ValueError, TypeError, InvalidOperation):
        return None


def _parece_pt_br(valor) -> bool:
    """`1.234,56` do Brasil contra `1234.56` de API. A vírgula decide.

    Sem isto, `1.234,56` viraria `1.234` — um valor FIPE mil vezes menor, e
    plausível o bastante para ninguém notar.
    """
    return isinstance(valor, str) and "," in valor


def _data(texto: str):
    """Aceita os formatos que aparecem de verdade, e nada além.

    Sem `dateutil` e sem adivinhação: `03/04/2026` é ambíguo entre padrões, e
    aqui a ordem brasileira é a certa porque a fonte é brasileira. Formato
    desconhecido volta `None`, e o campo fica ausente — nunca uma data errada,
    que é pior que data nenhuma num vencimento de licenciamento.
    """
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S",
                    "%d/%m/%Y %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto[:len(formato) + 8], formato).date()
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────────────────── a precedência

def resolver(fontes: dict[str, dict], edicao: dict[str, str] | None = None
             ) -> tuple[dict, dict]:
    """De `{fonte: {campos}}` para `({campo: valor}, {campo: fonte})`.

    Função PURA — é ela que os testes exercitam, sem banco nenhum.
    """
    edicao = edicao or {}
    valores: dict = {}
    origem: dict[str, str] = {}
    for campo in CAMPOS:
        nome, tipo = campo["nome"], campo["tipo"]
        for fonte in campo["precedencia"]:
            bruto = (edicao.get(nome) if fonte == "manual"
                     else (fontes.get(fonte, {}).get("campos") or {}).get(nome))
            if _vazio(bruto):
                continue
            valor = _converter(bruto, tipo)
            if valor is None:
                continue
            valores[nome] = valor
            origem[nome] = fonte
            break
    return valores, origem


def divergencias(fontes: dict[str, dict],
                 edicao: dict[str, str] | None = None) -> list[dict]:
    """Onde duas fontes têm o campo e discordam.

    Só compara fontes que DECLARAM o campo na precedência: a APIBrasil não
    opinar sobre `vinculo` não é divergência, é ausência.

    A comparação é do valor JÁ CONVERTIDO, e isso importa: `'2022 '` do ERP e
    `2022` do Detran são o MESMO ano, e acusá-los produziria uma lista de
    centenas de divergências falsas — que é o mesmo que não ter lista, porque
    ninguém lê uma lista que erra.
    """
    edicao = edicao or {}
    fora: list[dict] = []
    for campo in CAMPOS:
        nome, tipo = campo["nome"], campo["tipo"]
        if tipo == "json":
            continue          # lista de restrição não se compara por igualdade
        vistos: list[tuple[str, object]] = []
        for fonte in campo["precedencia"]:
            bruto = (edicao.get(nome) if fonte == "manual"
                     else (fontes.get(fonte, {}).get("campos") or {}).get(nome))
            valor = _converter(bruto, tipo)
            if valor is not None:
                vistos.append((fonte, valor))
        distintos = {_chave(v) for _, v in vistos}
        if len(distintos) > 1:
            fora.append({
                "campo": nome, "rotulo": campo["rotulo"],
                "vence": vistos[0][0],
                "valores": [{"fonte": f, "valor": _texto(v)} for f, v in vistos],
            })
    return fora


def _chave(valor):
    """Igualdade tolerante ao que não é diferença de verdade.

    Texto compara sem caixa e sem espaço nas pontas: 'VOLVO' e 'Volvo ' são o
    mesmo fabricante, e tratá-los como divergência encheria a lista de ruído
    até ninguém abrir mais.
    """
    if isinstance(valor, str):
        return valor.strip().upper()
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def _texto(valor) -> str:
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return str(valor)


# ────────────────────────────────────────────────────────── a reconstrução

def _sql_upsert() -> str:
    colunas = ", ".join(COLUNAS)
    marcas = ", ".join(["%s"] * len(COLUNAS))
    # `atualizado_em` só se move quando algo MUDA. Carimbar a cada passada
    # faria a coluna dizer "atualizado agora" numa frota que ninguém tocou, e
    # a tela mostraria frescor que não existe — a mesma mentira da tarja de
    # leitura velha que dizia "0 min atrás" para sempre.
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUNAS)
    return (f"INSERT INTO eqp_equipamento (placa, {colunas}, origem,"
            f"                             criado_em, atualizado_em)"
            f" VALUES (%s, {marcas}, %s, now(), now())"
            f" ON CONFLICT (placa) DO UPDATE SET {sets},"
            f"     origem = EXCLUDED.origem,"
            f"     atualizado_em = CASE"
            f"        WHEN eqp_equipamento IS DISTINCT FROM EXCLUDED"
            f"        THEN now() ELSE eqp_equipamento.atualizado_em END")


def reconstruir(placas: list[str] | None = None) -> dict:
    """Refaz `eqp_equipamento` a partir de `eqp_fonte` + `eqp_edicao`.

    Idempotente por construção: rodar duas vezes seguidas dá o mesmo cadastro.
    É isso que permite chamá-la depois de QUALQUER coleta sem pensar — e o que
    torna a tabela consolidada descartável, já que ela é sempre derivável.
    """
    import json as _json

    fontes_todas = arm.todas_as_fontes()
    edicoes = arm.edicoes()
    alvo = set(placas) if placas else set(fontes_todas) | set(edicoes)

    linhas = []
    for placa in sorted(alvo):
        valores, origem = resolver(fontes_todas.get(placa, {}),
                                   edicoes.get(placa))
        linhas.append((placa, *[valores.get(c) for c in COLUNAS],
                       _json.dumps(origem, ensure_ascii=False)))
    if not linhas:
        return {"equipamentos": 0}

    with pglocal_conn() as (conn, cur):
        cur.executemany(_sql_upsert(), linhas)
    return {"equipamentos": len(linhas)}


def pglocal_conn():
    """Conexão do banco da casa, respeitando o schema de teste.

    Existe como função (e não como import direto no corpo) para que
    `armazenamento.ESQUEMA` seja lido NA HORA — apontar o schema uma vez na
    importação faria a fixture de teste chegar tarde demais e a suíte escrever
    em produção.
    """
    from contextlib import contextmanager

    from .. import pglocal

    @contextmanager
    def _abrir():
        with pglocal.get_conn(arm.ESQUEMA) as conn, conn.cursor() as cur:
            yield conn, cur

    return _abrir()
