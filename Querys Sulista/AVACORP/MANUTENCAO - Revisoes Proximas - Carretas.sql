-- REVISOES PROXIMAS - TRAÇOES //

SELECT 
    retorno.frota,
    CASE 
        WHEN c.descricao <> 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER < 0 THEN 
            '?? VENCIDO A ' || ABS(((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER) || ' DIAS'
        WHEN c.descricao = 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER < 0 THEN 
            '?? VENCIDO A ' || ABS(((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER) || ' DIAS'
        WHEN c.descricao <> 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER <= 30 THEN 
            '?? PRÓXIMA EM ' || ABS(((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER) || ' DIAS'
        WHEN c.descricao = 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER <= 30 THEN 
            '?? PRÓXIMA EM ' || ABS(((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER) || ' DIAS'
        ELSE 'NO PRAZO' 
    END AS status_tempo_revisao,
    CASE 
        WHEN c.descricao <> 'CARROCERIA BAU' THEN ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER
        WHEN c.descricao = 'CARROCERIA BAU' THEN ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER
        ELSE 0 
    END AS tempo_prox_revisao
FROM avacorpi.fnc_manutencaopreventiva_gridview 
( 
     2 
    ,1 
    ,1 
    ,1 
    ,NULL
    ,NULL
    ,NULL
    ,NULL
    ,NULL
    ,NULL
    ,NULL
    ,3 
    ,NULL 
    ,1
    ,1
) AS retorno

LEFT JOIN veiculo v ON retorno.veiculo = v.placa
LEFT JOIN carroceriaveiculo c ON v.carroceriaveiculo = c.codigo
LEFT JOIN filial f ON v.filiallocado = f.codigo 
WHERE retorno.ds_grupoproduto = 'MANUTENCAO PREVENTIVA' 
    AND retorno.modeloveiculo LIKE '%SEMI REBOQUE%' 
    AND v.modeloveiculo <> 'GERAR' 
    AND v.ativoinativo = 1 
    AND v.atividadeveiculo <> 'ENC' 
    AND (
        (c.descricao <> 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER < 0) OR
        (c.descricao = 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER < 0) OR
        (c.descricao <> 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER <= 30) OR
        (c.descricao = 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER <= 30)
    )
ORDER BY tempo_prox_revisao