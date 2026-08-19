"""Abastecimento do AVA por placa, para cruzar com a telemetria.

Mesma fonte da tela de Combustivel (sulista.ctaplus_abastecimentos), com os
mesmos filtros: ARLA fora e distancia sana (1..3000 km), a guarda que aquela
tela ja usa para nao deixar leitura absurda entrar na media.

Colunas conferidas contra o banco em 19/08/2026.
Sem acento: LATIN-1 no PG 9.3.
"""
from __future__ import annotations

ABASTECIMENTO_MES_SQL = """
SELECT upper(regexp_replace(coalesce(a.veiculo_placa,''),'[^A-Za-z0-9]','','g'))
         AS placa,
       coalesce(sum(a.volume),0)::float8 AS litros_ava,
       coalesce(sum(CASE WHEN a.distancia > 0 AND a.distancia < 3000
                         THEN a.distancia ELSE 0 END),0)::float8 AS km_ava,
       count(*)::int AS abastecimentos
FROM sulista.ctaplus_abastecimentos a
WHERE a.data_inicio_abastecimento >= %(de)s::date
  AND a.data_inicio_abastecimento <  %(ate)s::date
  AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%arla%%'
  AND nullif(trim(a.veiculo_placa),'') IS NOT NULL
GROUP BY 1
"""
