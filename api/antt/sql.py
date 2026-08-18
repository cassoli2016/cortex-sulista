"""Viagens de agregado/terceiro com os campos de veiculo que o piso exige.

Fonte canonica do frete de compra e programacaoembarque -- a mesma da tela
Agregados (api/queries.py::_agr_base). Nao trocar por acertoviagemagregado: o
acerto e o fechamento financeiro do periodo, e o piso incide sobre o frete
contratado de cada viagem.

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
       tv.descricao AS veic_tipo,
       cr.descricao AS veic_carroceria,
       coalesce(v.bitrem, false) AS veic_bitrem,
       tc.descricao AS veic_tipocarga
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
LEFT JOIN cadastro c ON c.codigo = p.cnpjcpfcodigoveiculo
LEFT JOIN tipoveiculo tv ON tv.codigo = v.tipo
LEFT JOIN carroceria cr ON cr.codigo = v.carroceria
LEFT JOIN tipocargaveiculo tc ON tc.codigo = v.tipocargaveiculo
WHERE p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
  AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.numero < 1000000
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
  AND (%(transportador)s::text IS NULL
       OR c.nomefantasia ILIKE '%%'||%(transportador)s||'%%'
       OR c.razaosocial ILIKE '%%'||%(transportador)s||'%%')
ORDER BY p.dtemissao DESC, p.numero DESC
"""
