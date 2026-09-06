# -*- coding: utf-8 -*-
"""Minha viagem — a viagem em curso do motorista que está logado.

É a tela que dá ao motorista AGREGADO um motivo próprio para abrir o app, e
por isso ela é a primeira: dois terços dos motoristas ativos e dois terços das
viagens são de agregado (medido em 05/09/2026), e hoje eles ligam para a torre
para saber o que está aqui.

A CONSULTA É OUTRA, NÃO É A DA TORRE COM UM FILTRO A MAIS. `queries.TORRE_
TRANSITO_SQL` lê a mesma viagem e devolve `valorfrete` e `km`; esta não
devolve, e não porque alguém se lembre de remover na hora de montar o payload
— porque a coluna não está na consulta. Filtro se esquece num `SELECT *` que
alguém acrescenta; coluna ausente não vaza.

O ESCOPO É A PRIMEIRA COISA DA CLÁUSULA, e ele vem da SESSÃO. Não há parâmetro
de motorista nesta função, e é de propósito: um argumento que a rota pudesse
preencher com o que veio do navegador seria a diferença entre um app e um
buscador da operação alheia.

`cast(... AS text)` NO JOIN DE MOTORISTA: `programacaoembarque.motorista` é
`character varying` HOJE. Em 02/09/2026 a `agrupadorgerencial` foi recriada com
uma coluna trocando de `integer` para `varchar` e cinco telas morreram no
`operator does not exist`. Tabela de terceiro não tem contrato de tipo — o
cast custa o índice desta coluna e paga por não voltar a acontecer aqui; a
janela de data é o que segura o custo (medido no fim deste arquivo).

CACHE COM ÚLTIMA LEITURA BOA (6 h). O ERP é réplica de produção de terceiro e
já teve manhã ruim; um motorista na doca que abre o app e vê tela vazia liga
para a torre — que é o telefonema que este app existe para tirar. Número de
20 minutos atrás, DITO na tela, serve para trabalhar. O que não se faz é
servir o velho calado: `leitura_velha` vai no payload e a tela mostra a tarja.
"""
from __future__ import annotations

import logging

from .. import db
from ..queries import cached

log = logging.getLogger("cortex.motorista.viagem")

#: Até onde atrás se procura uma viagem "em curso". Viagem aberta há mais de um
#: mês não é viagem em curso, é fechamento que ninguém fez — mostrá-la ao
#: motorista como "sua viagem de hoje" seria uma informação errada com cara de
#: certa. Passado o prazo, o app diz que não há viagem, que é a verdade.
DIAS_EM_CURSO = 30

VIAGEM_SQL = """
SELECT p.numero,
       coalesce(nullif(trim(p.veiculo),''),'')                       AS placa,
       coalesce(nullif(trim(p.carreta1),''),'')                      AS carreta1,
       coalesce(nullif(trim(p.carreta2),''),'')                      AS carreta2,
       coalesce(nullif(trim(ag.descricao),''),
                nullif(trim(cp.nomefantasia),''),
                nullif(trim(cp.razaosocial),''), '')                 AS cliente,
       coalesce(nullif(trim(p.cidadeorigem),''),'')                  AS cidade_origem,
       coalesce(nullif(trim(p.uforigem),''),'')                      AS uf_origem,
       coalesce(nullif(trim(p.cidadedestino),''),'')                 AS cidade_destino,
       coalesce(nullif(trim(p.ufdestino),''),'')                     AS uf_destino,
       to_char(p.dtsaida,'YYYY-MM-DD HH24:MI')                       AS saida,
       to_char(coalesce(co.dtprevisaochegadaviagem,
                        p.dtprevisaochegadaviagem),
               'YYYY-MM-DD HH24:MI')                                 AS previsao_chegada,
       (p.tipo = 3)                                                  AS vazio
FROM programacaoembarque p
LEFT JOIN coleta co ON co.grupo = p.grupo AND co.empresa = p.empresa
  AND co.filial = p.filialdocumentoorigem
  AND co.unidade = p.unidadedocumentoorigem
  AND co.diferenciadornumero = p.diferenciadornumerodocumentoorigem
  AND co.numero = p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av
       ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE trim(cast(p.motorista AS text)) = %(mot)s
  AND p.dtcancelamento IS NULL
  AND p.semaforo = 1
  AND p.dtsaida IS NOT NULL
  AND p.dtchegada IS NULL
  AND p.dtsaida >= current_date - %(dias)s
ORDER BY p.dtsaida DESC
LIMIT 1
"""


def _cidade(cidade: str, uf: str) -> str:
    cidade, uf = (cidade or "").strip(), (uf or "").strip()
    if cidade and uf:
        return f"{cidade}/{uf}"
    return cidade or uf or ""


@cached(ttl=60, velha_ate=6 * 3600)
def _consultar(motorista_codigo: str) -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(VIAGEM_SQL, {"mot": str(motorista_codigo),
                                 "dias": DIAS_EM_CURSO})
        linha = cur.fetchone()
    if not linha:
        return {"viagem": None}
    # Serialização no LIMITE do módulo: o `numero` do ERP pode vir Decimal, e
    # Decimal estoura no `render()` do JSONResponse — DEPOIS do try/except da
    # rota, virando 500 em text/plain sem pista nenhuma.
    carretas = [c for c in (linha["carreta1"], linha["carreta2"]) if c]
    return {"viagem": {
        "numero": str(linha["numero"] or ""),
        "placa": linha["placa"],
        "carretas": carretas,
        "cliente": linha["cliente"],
        "origem": _cidade(linha["cidade_origem"], linha["uf_origem"]),
        "destino": _cidade(linha["cidade_destino"], linha["uf_destino"]),
        "saida": linha["saida"],
        "previsao_chegada": linha["previsao_chegada"],
        "vazio": bool(linha["vazio"]),
    }}


def minha(sessao: dict) -> dict:
    """A viagem de QUEM ESTÁ LOGADO. O código sai da sessão, nunca do pedido."""
    return _consultar(str(sessao["motorista_codigo"]))
