SELECT 
  retorno.frota,
  CASE 
    WHEN v.possuimotor = 1 THEN 
      COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
      COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
               NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0)
    ELSE 0 
  END AS km_prox_rev,  
  CASE 
    WHEN v.possuimotor = 1 
     AND (COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
          COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
                   NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0)) < 0 THEN 
     '?? VENCIDA?| ' || ABS(
          COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
          COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
                   NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0)
     ) || ' KM/H'

    WHEN v.possuimotor = 1 
     AND NULLIF(REGEXP_REPLACE(retorno.marcadortroca::TEXT, '\D', '', 'g'), '') IS NOT NULL
     AND (COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
          COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
                   NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0))::FLOAT / 
          NULLIF(REGEXP_REPLACE(retorno.marcadortroca::TEXT, '\D', '', 'g'), '')::INTEGER < 0.1 THEN 
     '?? PRÓXIMA?| ' || ABS(
          COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
          COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
                   NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0)
     ) || ' KM'
    ELSE 'NO PRAZO' 
  END AS status_km_revisao
  
FROM avacorpi.fnc_manutencaopreventiva_gridview 
( 
     2, 1, 1, 1, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3, NULL, 1, 1
) AS retorno

LEFT JOIN veiculo v ON retorno.veiculo = v.placa
LEFT JOIN (
    SELECT 
         veiculo_nome
        ,odometro
        ,ROW_NUMBER() OVER (PARTITION BY veiculo_nome ORDER BY data_inicio_abastecimento DESC) as rn
    FROM sulista.ctaplus_abastecimentos
) cta ON retorno.veiculo = cta.veiculo_nome AND cta.rn = 1

WHERE retorno.ds_grupoproduto = 'MANUTENCAO PREVENTIVA' 
    AND v.possuimotor = 1 
    AND v.ativoinativo = 1 
    AND v.atividadeveiculo NOT IN ('ENC', 'ADM')
    AND retorno.frota <> 'GERADOR'
    AND (
        (v.possuimotor = 1 
         AND (COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
              COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
                       NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0)) < 0)
        OR 
        (v.possuimotor = 1 
         AND NULLIF(REGEXP_REPLACE(retorno.marcadortroca::TEXT, '\D', '', 'g'), '') IS NOT NULL
         AND (COALESCE(NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::TEXT, '\D', '', 'g'), '')::INTEGER, 0) - 
              COALESCE(NULLIF(REGEXP_REPLACE(cta.odometro::TEXT, '\D', '', 'g'), '')::INTEGER, 
                       NULLIF(REGEXP_REPLACE(retorno.marcadoratual::TEXT, '\D', '', 'g'), '')::INTEGER, 0))::FLOAT / 
              NULLIF(REGEXP_REPLACE(retorno.marcadortroca::TEXT, '\D', '', 'g'), '')::INTEGER < 0.1)
    )  
ORDER BY km_prox_rev  