-- TRAÇÕES EM MANUTENCAO

SELECT 
    TO_CHAR(ordemservico.dtemissao, 'DD/MM HH24:MI') AS dtemissao,
    ordemservico.numero,
    cadastro.nomefantasia AS fornecedor,
    veiculo.numerofrota,
    ordemservico.veiculo,
    tipoveiculo.descricao AS tipo_veiculo,
    TO_CHAR(ordemservico.dtinicial, 'DD/MM HH24:MI') AS dtinicial,
    TO_CHAR(ordemservico.dtfechamento, 'DD/MM HH24:MI') AS dtfechamento,
    CASE 
        WHEN 
            CASE 
                WHEN ordemservico.dtfechamento IS NULL THEN 
                    (CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo') AS FLOAT) - 
                     CAST(EXTRACT(EPOCH FROM ordemservico.dtinicial) AS FLOAT))/60/60 
                ELSE 
                    (EXTRACT(EPOCH FROM ordemservico.dtfechamento) - 
                     EXTRACT(EPOCH FROM ordemservico.dtinicial))/60/60 
            END < 1 
        THEN 
            TO_CHAR(ROUND(
                CAST(
                    CASE 
                        WHEN ordemservico.dtfechamento IS NULL THEN 
                            (CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo') AS FLOAT) - 
                             CAST(EXTRACT(EPOCH FROM ordemservico.dtinicial) AS FLOAT))/60 
                        ELSE 
                            (EXTRACT(EPOCH FROM ordemservico.dtfechamento) - 
                             EXTRACT(EPOCH FROM ordemservico.dtinicial))/60 
                    END 
                AS NUMERIC), 2), 'FM999990.00') || ' M'
        ELSE 
            TO_CHAR(ROUND(
                CAST(
                    CASE 
                        WHEN ordemservico.dtfechamento IS NULL THEN 
                            (CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo') AS FLOAT) - 
                             CAST(EXTRACT(EPOCH FROM ordemservico.dtinicial) AS FLOAT))/60/60 
                        ELSE 
                            (EXTRACT(EPOCH FROM ordemservico.dtfechamento) - 
                             EXTRACT(EPOCH FROM ordemservico.dtinicial))/60/60 
                    END 
                AS NUMERIC), 2), 'FM999990') || ' H'
    END AS tempo_os,
    CASE 
        WHEN ordemservico.tipomanutencao = 1 THEN 'PREVENTIVA' 
        WHEN ordemservico.tipomanutencao = 2 THEN 'CORRETIVA' 
        WHEN ordemservico.tipomanutencao = 3 THEN 'AMBAS' 
    END AS tipo_manutencao,
    CASE 
        WHEN ordemservico.dtfechamento IS NULL THEN 'EM ABERTO' 
        ELSE 'ENCERRADA' 
    END AS status_os

FROM ordemservico
LEFT JOIN veiculo ON ordemservico.veiculo = veiculo.placa
LEFT JOIN tipoveiculo ON veiculo.tipoveiculo = tipoveiculo.codigo
LEFT JOIN cadastro ON ordemservico.fornecedor = cadastro.codigo
WHERE (TO_CHAR(ordemservico.dtinicial, 'MM/YYYY') = TO_CHAR(CURRENT_DATE, 'MM/YYYY') 
       OR ordemservico.dtfechamento IS NULL) 
      AND tipoveiculo.descricao IN ('CAVALO TRUCADO 6X2','CAVALO MECANICO 4X2')
      AND ordemservico.dtfechamento IS NULL

ORDER BY ordemservico.dtinicial ASC