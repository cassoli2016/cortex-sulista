-- Repactuações de clientes

SELECT
      pipelineprojetos_repactuacoes.id
    , pipelineprojetos_repactuacoes.grupo
    , pipelineprojetos_repactuacoes.empresa
    , pipelineprojetos_repactuacoes.filial
    , pipelineprojetos_repactuacoes.unidade 
    , agrupamentocliente.descricao -- Cliente
    , pipelineprojetos_repactuacoes.observacao 
    , pipelineprojetos_repactuacoes.mes_repac
    
    -- GATILHO 1
    , pipelineprojetos_repactuacoes.porcento_aplicacao_diesel_1
    , pipelineprojetos_repactuacoes.data_aplicacao_diesel_1
    
    , CASE 
        WHEN pipelineprojetos_repactuacoes.porcento_aplicacao_diesel_1 IS NULL AND pipelineprojetos_repactuacoes.sem_gatilho_diesel_1 = 0 THEN NULL
        WHEN pipelineprojetos_repactuacoes.sem_gatilho_diesel_1 = 0 THEN '??' -- 0 = GATILHO ATIVO
        WHEN pipelineprojetos_repactuacoes.sem_gatilho_diesel_1 = 1 THEN '??' -- 1 = SEM GATILHO
      END as sem_gatilho_diesel_1     
       
    -- GATILHO 2
    , pipelineprojetos_repactuacoes.porcento_aplicacao_diesel_2
    , pipelineprojetos_repactuacoes.data_aplicacao_diesel_2
    , CASE 
        WHEN pipelineprojetos_repactuacoes.porcento_aplicacao_diesel_2 IS NULL  AND pipelineprojetos_repactuacoes.sem_gatilho_diesel_2 = 0 THEN NULL
        WHEN pipelineprojetos_repactuacoes.sem_gatilho_diesel_2 = 0 THEN '??' -- 0 = GATILHO ATIVO
        WHEN pipelineprojetos_repactuacoes.sem_gatilho_diesel_2 = 1 THEN '??' -- 1 = SEM GATILHO
      END as sem_gatilho_diesel_2
      
     -- GATILHO 3
    , pipelineprojetos_repactuacoes.porcento_aplicacao_diesel_3
    , pipelineprojetos_repactuacoes.data_aplicacao_diesel_3
    , CASE 
        WHEN pipelineprojetos_repactuacoes.porcento_aplicacao_diesel_3 IS NULL  AND pipelineprojetos_repactuacoes.sem_gatilho_diesel_3 = 0 THEN NULL
        WHEN pipelineprojetos_repactuacoes.sem_gatilho_diesel_3 = 0 THEN '??' -- 0 = GATILHO ATIVO
        WHEN pipelineprojetos_repactuacoes.sem_gatilho_diesel_3 = 1 THEN '??' -- 1 = SEM GATILHO
      END as sem_gatilho_diesel_3
      
    , pipelineprojetos_repactuacoes.porcento_aplicacao_negocios
    , pipelineprojetos_repactuacoes.data_aplicacao_negocios
    , pipelineprojetos_repactuacoes.total_porcento
    , CASE WHEN pipelineprojetos_repactuacoes.status = 1 THEN 'Aplicada'
           WHEN pipelineprojetos_repactuacoes.status = 2 THEN 'Não Aplicada'
           WHEN pipelineprojetos_repactuacoes.status = 3 THEN 'Realizado BID'
           WHEN pipelineprojetos_repactuacoes.status = 4 THEN 'Rota Cancelada'
           WHEN pipelineprojetos_repactuacoes.status = 5 THEN 'Contrato Rescindido'
      END AS status
    , CASE WHEN pipelineprojetos_repactuacoes.usuarioinclusao IN (114,117) THEN 'SISTEMA'
       ELSE usuario.nomecompleto END as usuarioinclusao
    , pipelineprojetos_repactuacoes.dtinclusao
    
    , CASE WHEN pipelineprojetos_repactuacoes.usuarioinclusao IN (114,117) THEN 'SISTEMA'
       ELSE us.nomecompleto  END as usuarioalteracao
    , pipelineprojetos_repactuacoes.dtalteracao
    
FROM sulista.pipelineprojetos_repactuacoes

LEFT JOIN agrupamentocliente
ON pipelineprojetos_repactuacoes.cliente = agrupamentocliente.codigo

LEFT JOIN usuario
ON pipelineprojetos_repactuacoes.usuarioinclusao = usuario.codigo

LEFT JOIN usuario us
ON pipelineprojetos_repactuacoes.usuarioalteracao = us.codigo

ORDER BY pipelineprojetos_repactuacoes.mes_repac DESC;