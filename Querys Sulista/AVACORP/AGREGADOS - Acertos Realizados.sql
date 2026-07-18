-- Relatorio de acertos de agregados

SELECT 
    acertoviagemagregado.numero
    ,acertoviagemagregado.dtemissao
    ,acertoviagemagregado.dtfechamento
    ,COALESCE(acertoviagemagregado.valortotalfaturamento,0) AS valortotalfaturamento
    ,COALESCE(impostos.IRRF,0) AS IRRF
    ,COALESCE(acertoviagemagregado.valorseguro,0) AS valorseguro
    ,COALESCE(acertoviagemagregado.valorcomissao,0) AS valorcomissao
    ,COALESCE(impostos.SESTSENAT,0) AS SESTSENAT
    ,COALESCE(impostos.INSS,0) AS INSS
    ,COALESCE(acertoviagemagregado.valortotaladiantamento, 0) as valortotaladiantamento
    ,COALESCE(acertoviagemagregado.valortotaldescontos, 0) as outrosdescontos
    ,COALESCE(acertoviagemagregado.valortotaldespesas,0) AS valortotaldespesas
    ,COALESCE(acertoviagemagregado.valordesempenho,0) AS valordesempenho
    ,COALESCE(acertoviagemagregado.valortotalacrescimos,0) AS valoracrescimos
    , fornecedor.razaosocial AS nomefornecedor
    ,(COALESCE(acertoviagemagregado.veiculo,''))::VARCHAR AS veiculo
    
FROM acertoviagemagregado

LEFT JOIN grupo ON grupo.codigo = acertoviagemagregado.grupo

LEFT JOIN empresa ON empresa.grupo = acertoviagemagregado.grupo
    AND empresa.codigo = acertoviagemagregado.empresa

LEFT JOIN filial ON filial.grupo = acertoviagemagregado.grupo
    AND filial.empresa= acertoviagemagregado.empresa
    AND filial.codigo= acertoviagemagregado.filial

LEFT JOIN unidade ON unidade.grupo = acertoviagemagregado.grupo
    AND unidade.empresa = acertoviagemagregado.empresa
    AND unidade.filial = acertoviagemagregado.filial
    AND unidade.codigo = acertoviagemagregado.unidade

LEFT JOIN veiculo ON veiculo.placa = acertoviagemagregado.veiculo

LEFT JOIN cadastro fornecedor ON fornecedor.codigo = COALESCE(acertoviagemagregado.cnpjcpfcodigo,veiculo.proprietario)

LEFT JOIN LATERAL(
    SELECT retorno.grupo,
                retorno.empresa,
                retorno.filial,
                retorno.unidade,
                retorno.diferenciadornumero,
                retorno.numero, 
                SUM(retorno.IRRF) AS IRRF,
                SUM(retorno.INSS) AS INSS,
                SUM(retorno.SESTSENAT) AS SESTSENAT
      FROM (SELECT acertoviagemagregado_calculo.grupo,
                      acertoviagemagregado_calculo.empresa,
                      acertoviagemagregado_calculo.filial,
                      acertoviagemagregado_calculo.unidade,
                      acertoviagemagregado_calculo.diferenciadornumero,
                      acertoviagemagregado_calculo.numero, 
                      SUM(acertoviagemagregado_calculo.valor) AS IRRF,
                      SUM(0) AS INSS,
                      SUM(0) AS SESTSENAT

             FROM acertoviagemagregado   
             JOIN acertoviagemagregado_calculo  ON acertoviagemagregado_calculo.grupo = acertoviagemagregado.grupo
                                                            AND acertoviagemagregado_calculo.empresa = acertoviagemagregado.empresa
                                                            AND acertoviagemagregado_calculo.filial = acertoviagemagregado.filial
                                                            AND acertoviagemagregado_calculo.unidade = acertoviagemagregado.unidade
                                                            AND acertoviagemagregado_calculo.diferenciadornumero = acertoviagemagregado.diferenciadornumero 
                                                            AND acertoviagemagregado_calculo.numero = acertoviagemagregado.numero
                                                            AND acertoviagemagregado_calculo.tipocalculoacertoviagem = 2
             WHERE acertoviagemagregado.grupo = 1
             AND acertoviagemagregado.empresa = 1
             AND (COALESCE(NULL,0) = 0 OR  acertoviagemagregado.filial = NULL)
             AND (COALESCE(1,0) = 0 OR acertoviagemagregado.unidade = 1)                  
             AND acertoviagemagregado.dtemissao BETWEEN '2026-07-01' AND '2026-07-17'
             AND (CASE WHEN '' <> '' THEN fornecedor.codigo = avacorpi.fnc_desformata_cnpjcpf('')
                                    ELSE TRUE END)
             AND (CASE WHEN UPPER('')<> '' THEN acertoviagemagregado.veiculo = UPPER('')
                                    ELSE TRUE END)                     

             GROUP BY acertoviagemagregado_calculo.grupo,
                         acertoviagemagregado_calculo.empresa,
                         acertoviagemagregado_calculo.filial,
                         acertoviagemagregado_calculo.unidade,
                         acertoviagemagregado_calculo.diferenciadornumero,
                         acertoviagemagregado_calculo.numero
             UNION ALL

             SELECT acertoviagemagregado_calculo.grupo,
                                acertoviagemagregado_calculo.empresa,
                                acertoviagemagregado_calculo.filial,
                                acertoviagemagregado_calculo.unidade,
                                acertoviagemagregado_calculo.diferenciadornumero,
                                acertoviagemagregado_calculo.numero, 
                                SUM(0) AS IRRF,
                                SUM(acertoviagemagregado_calculo.valor) AS INSS,
                                SUM(0) AS SESTSENAT

             FROM acertoviagemagregado   
             JOIN acertoviagemagregado_calculo  ON acertoviagemagregado_calculo.grupo = acertoviagemagregado.grupo
                                                            AND acertoviagemagregado_calculo.empresa = acertoviagemagregado.empresa
                                                            AND acertoviagemagregado_calculo.filial = acertoviagemagregado.filial
                                                            AND acertoviagemagregado_calculo.unidade = acertoviagemagregado.unidade
                                                            AND acertoviagemagregado_calculo.diferenciadornumero = acertoviagemagregado.diferenciadornumero 
                                                            AND acertoviagemagregado_calculo.numero = acertoviagemagregado.numero
                                                            AND acertoviagemagregado_calculo.tipocalculoacertoviagem = 1
             WHERE acertoviagemagregado.grupo = 1
             AND acertoviagemagregado.empresa = 1
             AND (COALESCE(NULL,0) = 0 OR  acertoviagemagregado.filial = NULL)
             AND (COALESCE(1,0) = 0 OR acertoviagemagregado.unidade = 1)                  
             AND acertoviagemagregado.dtemissao BETWEEN '2026-07-01' AND '2026-07-17'
             AND (CASE WHEN '' <> '' THEN fornecedor.codigo = avacorpi.fnc_desformata_cnpjcpf('')
                 ELSE TRUE END)
             AND (CASE WHEN '' <> '' THEN acertoviagemagregado.veiculo = UPPER('')
                 ELSE TRUE END)                     

             GROUP BY acertoviagemagregado_calculo.grupo,
                      acertoviagemagregado_calculo.empresa,
                      acertoviagemagregado_calculo.filial,
                      acertoviagemagregado_calculo.unidade,
                      acertoviagemagregado_calculo.diferenciadornumero,
                      acertoviagemagregado_calculo.numero
             UNION ALL

             SELECT acertoviagemagregado_calculo.grupo,
                      acertoviagemagregado_calculo.empresa,
                      acertoviagemagregado_calculo.filial,
                      acertoviagemagregado_calculo.unidade,
                      acertoviagemagregado_calculo.diferenciadornumero,
                      acertoviagemagregado_calculo.numero, 
                      SUM(0) AS IRRF,
                      SUM(0) AS INSS,
                      SUM(acertoviagemagregado_calculo.valor) AS SESTSENAT

             FROM acertoviagemagregado   
             JOIN acertoviagemagregado_calculo  ON acertoviagemagregado_calculo.grupo = acertoviagemagregado.grupo
                                                            AND acertoviagemagregado_calculo.empresa = acertoviagemagregado.empresa
                                                            AND acertoviagemagregado_calculo.filial = acertoviagemagregado.filial
                                                            AND acertoviagemagregado_calculo.unidade = acertoviagemagregado.unidade
                                                            AND acertoviagemagregado_calculo.diferenciadornumero = acertoviagemagregado.diferenciadornumero 
                                                            AND acertoviagemagregado_calculo.numero = acertoviagemagregado.numero
                                                            AND acertoviagemagregado_calculo.tipocalculoacertoviagem = 3
             WHERE acertoviagemagregado.grupo = 1
             AND acertoviagemagregado.empresa = 1
             AND (COALESCE(NULL,0) = 0 OR  acertoviagemagregado.filial = NULL)
             AND (COALESCE(1,0) = 0 OR acertoviagemagregado.unidade = 1)                  
             AND acertoviagemagregado.dtemissao BETWEEN '2026-07-01' AND '2026-07-17'
             AND (CASE WHEN '' <> '' THEN fornecedor.codigo = avacorpi.fnc_desformata_cnpjcpf('') 
                                      ELSE TRUE END)
             AND (CASE WHEN '' <> '' THEN acertoviagemagregado.veiculo = UPPER('')
                                      ELSE TRUE END)                     

             GROUP BY acertoviagemagregado_calculo.grupo,
                         acertoviagemagregado_calculo.empresa,
                         acertoviagemagregado_calculo.filial,
                         acertoviagemagregado_calculo.unidade,
                         acertoviagemagregado_calculo.diferenciadornumero,
                         acertoviagemagregado_calculo.numero) retorno
                                 
        GROUP BY retorno.grupo,
          retorno.empresa,
          retorno.filial,
          retorno.unidade,
          retorno.diferenciadornumero,
          retorno.numero) impostos
        ON impostos.grupo = acertoviagemagregado.grupo 
        AND impostos.empresa = acertoviagemagregado.empresa 
        AND impostos.filial = acertoviagemagregado.filial 
        AND impostos.unidade = acertoviagemagregado.unidade 
        AND impostos.diferenciadornumero = acertoviagemagregado.diferenciadornumero 
        AND impostos.numero = acertoviagemagregado.numero
          
WHERE acertoviagemagregado.grupo = 1
    AND acertoviagemagregado.empresa = 1
    AND (COALESCE(NULL,0) = 0 OR  acertoviagemagregado.filial = NULL)
    AND (COALESCE(1,0) = 0 OR acertoviagemagregado.unidade = 1)                
    AND acertoviagemagregado.dtemissao BETWEEN '2026-07-01' AND '2026-07-17'
    AND (CASE WHEN '' <> '' THEN fornecedor.codigo = avacorpi.fnc_desformata_cnpjcpf('') 
                             ELSE TRUE END)
    AND (CASE WHEN '' <> '' THEN acertoviagemagregado.veiculo = UPPER('')
                             ELSE TRUE END)