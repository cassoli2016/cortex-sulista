-- Comunicação de Veic x Rastreadora

SELECT 
    CASE WHEN veiculo.ativoinativo = 1 THEN 'ATIVO' ELSE 'INATIVO' END AS situacao,
    veiculo.placa,
    COALESCE(veiculo.numerofrota, veiculo.placa) AS numerofrota,
    CASE 
        WHEN veiculo.tipofrota = 1 THEN 'PROPRIO'
        WHEN veiculo.tipofrota = 2 THEN 'TERCEIRO'
        WHEN veiculo.tipofrota = 3 THEN 'AGREGADO' 
    END AS tipofrota,
    tipoveiculo.descricao AS tipoveiculo,
    atividadeveiculo.descricao AS atividadeveiculo,
    rastreador.razaosocial AS rastreador_razaosocial,
    veiculo.tecnologiarastreadora, 
    tipocomunicacaorastreador.descricao AS tipocomunicacaorastreador_descricao,
    
    veiculo_posicao.dt AS dtultimaposicao,
    CASE 
        WHEN veiculo_posicao.situacao = 0 THEN 'DESLIGADO'
        WHEN veiculo_posicao.situacao = 1 THEN 'LIGADO'
        WHEN veiculo_posicao.situacao = 2 THEN 'DESCONHECIDO' 
    END AS ignicao,
    UPPER(veiculo_posicao.descricaoposicao) AS descricaoposicao,
    veiculo_posicao.latituderastreadora,
    veiculo_posicao.longituderastreadora,
    
    CASE 
        WHEN veiculo_posicao.dt IS NULL THEN 'Sem comunicação histórica'
        WHEN veiculo_posicao.dt >= CURRENT_DATE THEN 'Comunicando hoje'
        WHEN veiculo_posicao.dt < CURRENT_DATE AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '2 days' THEN 'Sem comunicação nos últimos 2 dias'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '2 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '5 days' THEN 'Sem comunicação nos últimos 5 dias'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '5 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '15 days' THEN 'Sem comunicação nos últimos 15 dias'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '15 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '20 days' THEN 'Sem comunicação nos últimos 20 dias'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '20 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '30 days' THEN 'Sem comunicação nos últimos 30 dias'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '30 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '60 days' THEN 'Sem comunicação nos últimos 60 dias'
        ELSE 'Sem comunicação a mais de 60 dias'
    END AS faixa_comunicacao
    
   ,CASE 
        WHEN veiculo_posicao.dt IS NULL THEN '99'
        WHEN veiculo_posicao.dt >= CURRENT_DATE THEN '1'
        WHEN veiculo_posicao.dt < CURRENT_DATE AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '2 days' THEN '2'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '2 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '5 days' THEN '3'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '5 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '15 days' THEN '4'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '15 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '20 days' THEN '5'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '20 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '30 days' THEN '6'
        WHEN veiculo_posicao.dt < CURRENT_DATE - INTERVAL '30 days' AND veiculo_posicao.dt >= CURRENT_DATE - INTERVAL '60 days' THEN '7'
        ELSE '8'
    END AS faixa_codigo
    ,CASE WHEN rastreador.razaosocial is null then 0 ELSE 1 end as rastreadora_codigo
FROM veiculo

-- Junção com a última posição conhecida
LEFT JOIN veiculo_posicao
    ON veiculo.placa = veiculo_posicao.veiculo
    AND veiculo_posicao.ultimaposicao = 1

-- Junções da empresa de rastreio e tecnologia (Query 2)
LEFT JOIN cadastro rastreador
    ON veiculo.cnpjcpfcodigorastreador = rastreador.codigo

LEFT JOIN tipocomunicacaorastreador
    ON veiculo.idtipocomunicacaorastreador = tipocomunicacaorastreador.id

-- Junções auxiliares mantidas da Query 1
LEFT JOIN tipoveiculo
    ON veiculo.tipoveiculo = tipoveiculo.codigo

LEFT JOIN atividadeveiculo
    ON veiculo.atividadeveiculo = atividadeveiculo.codigo

WHERE veiculo.ativoinativo = 1 -- Foco inicial em frota ativa conforme e-mail
-- Exemplo de filtros solicitados que podem ser aplicados dinamicamente:
-- AND atividadeveiculo.descricao <> 'ENCOSTADA' 

ORDER BY faixa_codigo, rastreadora_codigo desc, veiculo.placa