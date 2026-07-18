--TOTAL DE VEIC COM REVISAO NO PRAZO // PROXIMA // VENCIDA // %

WITH status_cte AS (
    SELECT 
        retorno.veiculo,
        retorno.frota,
        f.apelido AS filial,
        t.descricao AS tipo,
        retorno.ds_grupoproduto,
        retorno.ds_subgrupo,
        retorno.ds_utilizacaoveiculo,
        c.descricao AS carroceria,
        retorno.marcaveiculo,
        retorno.modeloveiculo,
        retorno.dtultimatroca,
        retorno.marcadorproximatroca::TIMESTAMP,
        CASE 
            WHEN c.descricao <> 'CARROCERIA BAU' THEN (retorno.dtultimatroca::DATE + 180)
            WHEN c.descricao = 'CARROCERIA BAU' THEN (retorno.dtultimatroca::DATE + 240)
            ELSE CURRENT_DATE 
        END AS marcador_proxima,
        CASE 
            WHEN c.descricao <> 'CARROCERIA BAU' THEN ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER
            WHEN c.descricao = 'CARROCERIA BAU' THEN ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER
            ELSE 0 
        END AS tempo_prox_revisao,
        CASE 
            WHEN c.descricao <> 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER < 0 THEN 'REVISÃO VENCIDA'
            WHEN c.descricao = 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER < 0 THEN 'REVISÃO VENCIDA'
            WHEN c.descricao <> 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 180) - CURRENT_DATE)::INTEGER <= 30 THEN 'REVISÃO PRÓXIMA'
            WHEN c.descricao = 'CARROCERIA BAU' AND ((retorno.dtultimatroca::DATE + 240) - CURRENT_DATE)::INTEGER <= 30 THEN 'REVISÃO PRÓXIMA'
            ELSE 'NO PRAZO' 
        END AS status_revisao
    FROM avacorpi.fnc_manutencaopreventiva_gridview(2, 1, 1, 1, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3, NULL, 1, 1) AS retorno
    LEFT JOIN veiculo v 
        ON retorno.veiculo = v.placa
    LEFT JOIN carroceriaveiculo c 
        ON v.carroceriaveiculo = c.codigo
    LEFT JOIN tipoveiculo t 
        ON retorno.tipoveiculo = t.codigo
    LEFT JOIN filial f 
        ON v.filiallocado = f.codigo 
    WHERE 
        retorno.ds_grupoproduto = 'MANUTENCAO PREVENTIVA' 
        AND retorno.modeloveiculo LIKE '%SEMI REBOQUE%' 
        AND v.modeloveiculo <> 'GERAR' 
        AND v.ativoinativo = 1 
        AND v.atividadeveiculo <> 'ENC'
)
SELECT 
    COUNT(*) AS total_veiculos,
    SUM(CASE WHEN status_revisao = 'NO PRAZO' THEN 1 ELSE 0 END) AS no_prazo,
    SUM(CASE WHEN status_revisao = 'REVISÃO PRÓXIMA' THEN 1 ELSE 0 END) AS revisao_proxima,
    SUM(CASE WHEN status_revisao = 'REVISÃO VENCIDA' THEN 1 ELSE 0 END) AS revisao_vencida,
    ROUND(SUM(CASE WHEN status_revisao = 'REVISÃO VENCIDA' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*)::NUMERIC * 100, 2) AS percent_revisaovencida
FROM status_cte;