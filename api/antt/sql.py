"""Viagens de agregado/terceiro com o que o piso exige, direto do cadastro.

Fonte canonica do frete de compra e programacaoembarque -- a mesma da tela
Agregados (api/queries.py::_agr_base). Nao trocar por acertoviagemagregado: o
acerto e o fechamento financeiro do periodo, e o piso incide sobre o frete
contratado de cada viagem.

EIXOS SAO DA COMPOSICAO, NAO DA TRACAO. A ANTT cobra pelo conjunto: cavalo
trucado (3 eixos) puxando carreta de 3 eixos e uma composicao de 6. O AVA
guarda as placas do conjunto em programacaoembarque.carreta1/2/3 e a contagem
de eixos de cada tipo em tipoveiculo.quantidadeeixos. Medido em 90 dias de
viagens reais: 3.982 viagens tem tracao de 3 eixos e composicao de 6, e 3.291
tem tracao de 2 e composicao de 5 -- usar a tracao subestimaria o piso pela
metade e deixaria passar viagem paga abaixo do minimo legal.

Colunas conferidas contra o banco em 18/08/2026: veiculo.tipoveiculo (varchar,
codigo), veiculo.carroceriaveiculo, veiculo.tipocargaveiculo (varchar, codigo),
veiculo.bitrem (integer 1=sim 2=nao), tipoveiculo.quantidadeeixos,
programacaoembarque.carreta1/2/3 e .veiculoaltodesempenhociot (1=sim, 2=nao).

Sem acento neste arquivo: o SQL trafega em LATIN-1 no PG 9.3.
"""
from __future__ import annotations

PISO_VIAGENS_SQL = """
SELECT p.numero,
       to_char(p.dtemissao,'YYYY-MM-DD') AS dtemissao,
       p.cnpjcpfcodigoveiculo AS codigo,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''),
                '(sem cadastro)') AS transportador,
       p.veiculo AS placa,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?')
         AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?')
         AS destino,
       coalesce(p.kmfretecompra,0)::float8 AS km,
       coalesce(p.valorfretecompra,0)::float8 AS pago,
       (p.tipo = 3) AS vazio,
       (p.veiculoaltodesempenhociot = 1) AS alto_desempenho,
       -- eixos da COMPOSICAO: tracao + ate tres implementos
       (coalesce(tv.quantidadeeixos,0) + coalesce(t1.quantidadeeixos,0)
        + coalesce(t2.quantidadeeixos,0) + coalesce(t3.quantidadeeixos,0))::int
         AS eixos,
       coalesce(tv.quantidadeeixos,0)::int AS eixos_tracao,
       tv.descricao AS veic_tipo,
       v.carroceriaveiculo AS veic_carroceria,
       v.tipocargaveiculo AS veic_tipocarga,
       tc.descricao AS veic_tipocarga_desc,
       (v.bitrem = 1) AS veic_bitrem
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
LEFT JOIN cadastro c ON c.codigo = p.cnpjcpfcodigoveiculo
LEFT JOIN tipoveiculo tv ON tv.codigo = v.tipoveiculo
LEFT JOIN tipocargaveiculo tc ON tc.codigo = v.tipocargaveiculo
LEFT JOIN veiculo c1 ON c1.placa = nullif(trim(p.carreta1),'')
LEFT JOIN tipoveiculo t1 ON t1.codigo = c1.tipoveiculo
LEFT JOIN veiculo c2 ON c2.placa = nullif(trim(p.carreta2),'')
LEFT JOIN tipoveiculo t2 ON t2.codigo = c2.tipoveiculo
LEFT JOIN veiculo c3 ON c3.placa = nullif(trim(p.carreta3),'')
LEFT JOIN tipoveiculo t3 ON t3.codigo = c3.tipoveiculo
WHERE p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
  AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.numero < 1000000
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
  AND (%(transportador)s::text IS NULL
       OR c.nomefantasia ILIKE '%%'||%(transportador)s||'%%'
       OR c.razaosocial ILIKE '%%'||%(transportador)s||'%%')
ORDER BY p.dtemissao DESC, p.numero DESC
"""
