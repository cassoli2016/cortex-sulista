# -*- coding: utf-8 -*-
"""O ERP como FONTE do cadastro — e o único arquivo que morre com o Avacorp.

POR QUE ISOLADO NUM ARQUIVO SÓ
==============================
Porque a decisão é sair do Avacorp. Se a leitura do AVA estivesse espalhada
pelo módulo, "sair do ERP" seria uma varredura arqueológica; concentrada aqui,
é apagar um arquivo e ver o que reclama — e o que reclama está nomeado em
`campos.pendencias_da_independencia()`.

Nada mais em `api/equipamentos/` importa `api.db`. Há guard cobrando isso
(`tests/equipamentos/test_erp_isolado.py`): é a única defesa contra a leitura
do ERP voltar a vazar para o resto do módulo, porque essa volta não tem
sintoma nenhum — funciona perfeitamente, até o dia do desligamento.

O QUE FOI MEDIDO ANTES DE ESCREVER ISTO (07/09/2026)
====================================================
- **`marcaveiculo` é CÓDIGO, não nome**: 'FAC', 'MBENZ', 'FOR'. Os 100% de
  preenchimento são 100% de uma abreviação. `public.marcaveiculo` (40 linhas)
  traduz, e o join casa 100% da frota ativa — por isso ele entra. Sem ele o
  cadastro mostraria 'MBENZ' e alguém escreveria "Mercedes" no lugar, que é
  rótulo inventado.
- **`modeloveiculo` NÃO tem tabela de domínio** ('SR', '2422', '1218'). Fica
  CRU, e o cadastro diz que é o código do ERP. Código sem domínio não vira
  rótulo inventado — o nome do modelo vem do Detran ou não vem.
- **`corcabine` está vazio em 100% da frota**; quem tem a cor é
  `idcorveiculocabine` (1.272 de 1.977, 64%), que casa com `public.corveiculo`.
  Ler o campo texto e concluir "o ERP não tem cor" seria falso — a cor está
  ali, noutra coluna.
- **`tipoveiculo.tracao` e `.reboca` são flags 1=sim / 2=não**, e é delas que
  sai a categoria. A prova está no cadastro: 'CARRETA 2 EIXOS REBOCADORA
  (BTREM)' tem `tracao=2, reboca=1` — não é tracionada e reboca a segunda —,
  enquanto 'CARRETA 2 EIXOS REBOCADA (BTREM)' tem `2, 2`. Sem esse par a
  leitura seria chute; com ele é evidência escrita no próprio ERP.
- `tara`, `capacidadecarga` vêm em QUILO (9000.000) e `capacidadetanque` em
  litro. Guardados na unidade de origem.

O QUE ESTA FONTE NÃO PODE RESPONDER
===================================
Situação no Detran, CRLV, restrição e FIPE com mês de referência. Não é
lacuna de preenchimento: o ERP não tem esses campos. Ver `api/apibrasil/`.
"""
from __future__ import annotations

import logging

from .. import db

log = logging.getLogger("cortex.equipamentos")

FONTE = "erp"

# ATENCAO: ESTE MODULO NAO USA `semaforo = 1`, E ISSO E DELIBERADO.
#
# O resto da casa filtra frota ativa por `semaforo = 1` (veja
# `api/frota_identidade.py`). MEDIDO em 07/09/2026, esse filtro esta ERRADO
# para este uso: dos 1.977 veiculos com `semaforo = 1`, **534 tem
# `ativoinativo = 2` E `dtinativo` preenchida** -- ou seja, foram baixados,
# com data, e continuam entrando na conta. As baixas sao reais e antigas:
# 163 em 2026, 154 em 2025, 118 em 2024, 99 em 2023.
#
# A frota ATIVA de verdade e 1.446, nao 1.977:
#
#     vinculo     ativo   com semaforo=1   cadastro total
#     proprio       308            588              599
#     agregado      122            303              305
#     terceiro    1.016          1.086            1.092
#
# Aqui a diferenca custa DINHEIRO: cada placa e uma consulta paga por produto,
# e 531 placas mortas x 4 produtos sao ~2.100 consultas gastas para descobrir
# a situacao de licenciamento de veiculo que a Sulista nao opera mais.
#
# `dtinativo IS NULL` entra junto com `ativoinativo = 1` porque as duas marcas
# tambem discordam entre si em 2 registros -- e num cadastro de terceiro,
# preenchido de fora, concordancia de duas marcas e mais barata que escolher
# a certa. E DUAS MARCAS DE ATIVO QUE DISCORDAM JA MORDERAM ESTA CASA: e a
# mesma familia da conciliacao nativa do ERP, cuja `situacao` parou em 2023
# enquanto o vinculo com o razao seguia vivo.
#
# Sem acento e sem travessao no SQL: o AVA e LATIN1 e o psycopg codifica a
# QUERY nessa codificacao antes de enviar -- um travessao aqui estoura com
# UnicodeEncodeError apontando para a posicao do caractere, nao para o SQL.
#
# Os joins de dominio sao LEFT de proposito: hoje casam 100%, mas cadastro de
# terceiro entra pelo ERP sem passar por ninguem daqui, e um INNER faria o
# equipamento SUMIR do cadastro em vez de aparecer com o codigo cru. Sumir e
# a falha sem sintoma; aparecer estranho tem sintoma.
_SQL = """
SELECT trim(v.placa)                                  AS placa,
       nullif(trim(v.codigorenavam), '')              AS renavam,
       nullif(trim(v.numerochassi), '')               AS chassi,
       nullif(trim(v.numeromotor), '')                AS numero_motor,
       nullif(trim(v.placaanterior), '')              AS placa_anterior,
       nullif(trim(v.tipoveiculo), '')                AS tipo_codigo,
       nullif(trim(t.descricao), '')                  AS tipo,
       t.tracao                                       AS flag_tracao,
       t.reboca                                       AS flag_reboca,
       t.quantidadeeixos                              AS eixos,
       nullif(trim(v.carroceriaveiculo), '')          AS carroceria_codigo,
       nullif(trim(cr.descricao), '')                 AS carroceria,
       nullif(trim(v.marcaveiculo), '')               AS marca_codigo,
       nullif(trim(m.descricao), '')                  AS marca,
       nullif(trim(v.modeloveiculo), '')              AS modelo,
       nullif(v.anofabricacao, 0)                     AS ano_fabricacao,
       nullif(v.anomodelo, 0)                         AS ano_modelo,
       nullif(trim(co.descricao), '')                 AS cor,
       nullif(v.tara, 0)                              AS tara_kg,
       nullif(v.capacidadecarga, 0)                   AS capacidade_carga_kg,
       nullif(v.capacidadem3, 0)                      AS capacidade_m3,
       nullif(v.capacidadetanque, 0)                  AS capacidade_tanque_l,
       nullif(trim(v.ufemplacamento), '')             AS uf,
       nullif(trim(v.cidadeemplacamento), '')         AS municipio,
       v.tipofrota                                    AS tipofrota,
       nullif(trim(v.proprietario), '')               AS proprietario_doc,
       nullif(v.valorfipe, 0)                         AS fipe_valor,
       v.filial                                       AS filial,
       nullif(trim(v.numerofrota), '')                AS numero_frota,
       v.combustivelgasolina, v.combustivelalcool, v.combustivelgas,
       v.combustiveldiesel, v.combustivelquerosene, v.combustiveleletricidade
  FROM veiculo v
  LEFT JOIN tipoveiculo       t  ON t.codigo  = v.tipoveiculo
  LEFT JOIN carroceriaveiculo cr ON cr.codigo = v.carroceriaveiculo
  LEFT JOIN marcaveiculo      m  ON m.codigo  = v.marcaveiculo
  LEFT JOIN corveiculo        co ON co.id     = v.idcorveiculocabine
 WHERE v.ativoinativo = 1 AND v.dtinativo IS NULL
   AND nullif(trim(v.placa), '') IS NOT NULL
 ORDER BY 1
"""

# `tipofrota` do ERP. O rotulo bonito mora aqui, no Python, e nao no SQL --
# mesma razao do travessao: o AVA e LATIN1.
_VINCULO = {1: "proprio", 2: "terceiro", 3: "agregado"}

# 1 = sim, 2 = nao. Ver o cabecalho: a prova esta no par BTREM.
_SIM = 1

# As seis colunas booleanas de combustivel do ERP, na ordem em que a etiqueta
# deve sair quando o veiculo for flex.
_COMBUSTIVEIS = (
    ("combustiveldiesel", "Diesel"),
    ("combustivelgasolina", "Gasolina"),
    ("combustivelalcool", "Etanol"),
    ("combustivelgas", "GNV"),
    ("combustiveleletricidade", "Elétrico"),
    ("combustivelquerosene", "Querosene"),
)


def _combustivel(linha: dict) -> str | None:
    """As seis colunas booleanas viram uma etiqueta.

    Flex é `Diesel + Etanol`, e não uma das duas escolhida por nós: escolher
    apagaria a informação de que o veículo aceita as duas.
    """
    marcados = [rot for col, rot in _COMBUSTIVEIS if linha.get(col) == _SIM]
    return " + ".join(marcados) or None


def _categoria(linha: dict) -> str | None:
    """tração ou implemento, a partir da flag do ERP.

    NÃO existe 'leve' aqui, e é deliberado: separar VAN e automóvel de um
    caminhão 3/4 exigiria ler a DESCRIÇÃO do tipo, que é heurística, e
    heurística escondida vira verdade do sistema. Quando a APIBrasil trouxer
    a `especie` do Detran — que é domínio escrito, não palpite — a categoria
    ganha o terceiro valor com fonte.
    """
    flag = linha.get("flag_tracao")
    if flag is None:
        return None
    return "tracao" if flag == _SIM else "implemento"


def ler() -> list[dict]:
    """A frota ativa do ERP, já nos nomes de campo do cadastro.

    Devolve `{"placa": ..., "campos": {...}, "payload": {...}}` por
    equipamento — o mesmo formato que toda fonte entrega à consolidação, para
    que ela não precise saber de quem veio.
    """
    fora: list[dict] = []
    for linha in db.query(_SQL):
        placa = (linha.get("placa") or "").strip().upper()
        if not placa:
            continue
        campos = {
            "renavam": linha.get("renavam"),
            "chassi": linha.get("chassi"),
            "numero_motor": linha.get("numero_motor"),
            "placa_anterior": linha.get("placa_anterior"),
            "categoria": _categoria(linha),
            "tipo": linha.get("tipo") or linha.get("tipo_codigo"),
            "carroceria": linha.get("carroceria") or linha.get("carroceria_codigo"),
            "marca": linha.get("marca") or linha.get("marca_codigo"),
            # CRU, e assumidamente cru: nao ha dominio de modelo no ERP.
            "modelo": linha.get("modelo"),
            "ano_fabricacao": linha.get("ano_fabricacao"),
            "ano_modelo": linha.get("ano_modelo"),
            "cor": linha.get("cor"),
            "combustivel": _combustivel(linha),
            "tara_kg": linha.get("tara_kg"),
            "capacidade_carga_kg": linha.get("capacidade_carga_kg"),
            "capacidade_m3": linha.get("capacidade_m3"),
            "capacidade_tanque_l": linha.get("capacidade_tanque_l"),
            "eixos": linha.get("eixos"),
            "uf": linha.get("uf"),
            "municipio": linha.get("municipio"),
            "vinculo": _VINCULO.get(linha.get("tipofrota")),
            "proprietario_doc": linha.get("proprietario_doc"),
            "fipe_valor": linha.get("fipe_valor"),
            "ativo": True,   # o SQL ja filtra ativo; ver o cabecalho
            "filial": (str(linha["filial"]) if linha.get("filial") is not None
                       else None),
            "numero_frota": linha.get("numero_frota"),
        }
        # Campo vazio NAO entra: `None` em `campos` faria a fonte "responder"
        # o campo com nada e vencer a fonte seguinte na precedencia. Ausencia
        # e ausencia; e a diferenca entre nao ter e ter vazio e justamente o
        # que a precedencia usa para decidir.
        campos = {k: v for k, v in campos.items() if v is not None and v != ""}
        fora.append({"placa": placa, "campos": campos, "payload": linha})
    return fora


def placas() -> list[dict]:
    """Só placa + vínculo + ativo. É o que a coleta usa para escolher a fila.

    Consulta separada e enxuta de propósito: montar a fila da APIBrasil não
    precisa dos trinta campos, e a fila é lida com frequência.
    """
    linhas = db.query(
        "SELECT trim(placa) AS placa, tipofrota"
        "  FROM veiculo"
        " WHERE ativoinativo = 1 AND dtinativo IS NULL"
        "   AND nullif(trim(placa), '') IS NOT NULL"
        " ORDER BY 1")
    return [{"placa": r["placa"].strip().upper(),
             "vinculo": _VINCULO.get(r["tipofrota"])}
            for r in linhas if (r.get("placa") or "").strip()]
