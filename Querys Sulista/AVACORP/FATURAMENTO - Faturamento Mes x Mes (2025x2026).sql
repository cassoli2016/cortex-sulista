-- MES ATUAL X MES ATUAL NO ANO PASSADO (faturado)  // Ajustar a data conforme necessidade

WITH faturamento23 AS (
    -- ################################### -- A V A C O R P (Anterior) -- ################################### --
    SELECT
        LPAD(EXTRACT(MONTH FROM conhecimento.dtemissao)::text, 2, '0') AS dt_emissao
        ,SUM(CASE WHEN conhecimento.complementar = 2 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_normal
        ,SUM(CASE WHEN conhecimento.complementar = 1 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_complementar
        ,0 as valor_nfse
    FROM conhecimento
    LEFT JOIN veiculo ON conhecimento.veiculo = veiculo.placa
    LEFT JOIN tiponegocio ON conhecimento.grupo = tiponegocio.grupo AND conhecimento.empresa = tiponegocio.empresa AND conhecimento.tiponegocio = tiponegocio.id
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = conhecimento.grupo AND agrupamentocliente_cnpjcpfcodigo.empresa = conhecimento.empresa AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = conhecimento.cnpjcpfcodigopagadorfrete
    WHERE conhecimento.grupo = 1 
    AND conhecimento.empresa = 1 
    AND conhecimento.numero < 1000000 
    AND conhecimento.dtemissao::DATE BETWEEN ('01/07/2026 00:00:00'::DATE - INTERVAL '1 year') AND ('17/07/2026 00:00:00'::DATE - INTERVAL '1 year')
    AND conhecimento.dtemissao::DATE >= '01/06/2023'
    AND conhecimento.dtcancelamento IS NULL
    AND conhecimento.situacaocte = 3
    AND conhecimento.tipo IN (1, 4)
    AND conhecimento.unidade = 1
    GROUP BY LPAD(EXTRACT(MONTH FROM conhecimento.dtemissao)::text, 2, '0')

    UNION ALL
    
    -- ################################### -- K M M (Anterior) -- ################################### --
    SELECT
        LPAD(EXTRACT(MONTH FROM sulista.faturamentokmm.dtemissao)::text, 2, '0') AS dt_emissao
        ,COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'CT-e' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_cte_normal
        ,0 AS valor_cte_complementar
        ,COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'NFS' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_nfse
    FROM sulista.faturamentokmm
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = sulista.faturamentokmm.grupo AND agrupamentocliente_cnpjcpfcodigo.empresa = sulista.faturamentokmm.empresa AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = sulista.faturamentokmm.pagadorfrete_cnpj AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
    LEFT JOIN agrupamentocliente ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
    LEFT JOIN veiculo ON veiculo.placa = sulista.faturamentokmm.placa
    WHERE sulista.faturamentokmm.dtemissao::DATE BETWEEN ('01/07/2026 00:00:00'::DATE - INTERVAL '1 year') AND ('17/07/2026 00:00:00'::DATE - INTERVAL '1 year')
    GROUP BY LPAD(EXTRACT(MONTH FROM sulista.faturamentokmm.dtemissao)::text, 2, '0'), sulista.faturamentokmm.tipodocumento

    UNION ALL
    
    -- ################################### -- N F  S E R V I Ç O (Anterior) -- ################################### --
    SELECT 
        LPAD(EXTRACT(MONTH FROM notafiscalservico.dtemissao)::text, 2, '0') AS dt_emissao
        ,0 AS valor_cte_complementar
        ,0 AS valor_cte_normal
        ,SUM(notafiscalservico.valortotalbruto) AS valor_nfse
    FROM notafiscalservico
    JOIN cadastro pagadorfrete ON pagadorfrete.codigo = notafiscalservico.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = notafiscalservico.grupo AND agrupamentocliente_cnpjcpfcodigo.empresa = notafiscalservico.empresa AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = notafiscalservico.cnpjcpfcodigo AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
    WHERE notafiscalservico.grupo = 1 
    AND notafiscalservico.empresa = 1 
    AND notafiscalservico.numero < 1000000 
    AND notafiscalservico.dtemissao::DATE BETWEEN ('01/07/2026 00:00:00'::DATE - INTERVAL '1 year') AND ('17/07/2026 00:00:00'::DATE - INTERVAL '1 year')
    AND notafiscalservico.dtemissao::DATE >= '01/06/2023'
    AND notafiscalservico.dtcancelamento IS NULL
    AND (notafiscalservico.emissaoeletronica = 2 OR (notafiscalservico.emissaoeletronica = 1 AND notafiscalservico.situacaonfse = 3))
    GROUP BY LPAD(EXTRACT(MONTH FROM notafiscalservico.dtemissao)::text, 2, '0')
),

fat_2023 AS (
    SELECT
        faturamento23.dt_emissao AS dt_emissao_23
        ,SUM(faturamento23.valor_cte_normal) + SUM(faturamento23.valor_cte_complementar) + SUM(faturamento23.valor_nfse) AS total_realizado_23
    FROM faturamento23
    GROUP BY faturamento23.dt_emissao
),

faturamento24 AS (
    -- ################################### -- A V A C O R P (Atual) -- ################################### --
    SELECT
        LPAD(EXTRACT(MONTH FROM conhecimento.dtemissao)::text, 2, '0') AS dt_emissao
        ,SUM(CASE WHEN conhecimento.complementar = 2 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_normal
        ,SUM(CASE WHEN conhecimento.complementar = 1 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_complementar
        ,0 as valor_nfse
    FROM conhecimento
    LEFT JOIN veiculo ON conhecimento.veiculo = veiculo.placa
    LEFT JOIN tiponegocio ON conhecimento.grupo = tiponegocio.grupo AND conhecimento.empresa = tiponegocio.empresa AND conhecimento.tiponegocio = tiponegocio.id
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = conhecimento.grupo AND agrupamentocliente_cnpjcpfcodigo.empresa = conhecimento.empresa AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = conhecimento.cnpjcpfcodigopagadorfrete
    WHERE conhecimento.grupo = 1 
    AND conhecimento.empresa = 1 
    AND conhecimento.numero < 1000000 
    AND conhecimento.dtemissao::DATE BETWEEN '01/07/2026 00:00:00' AND '17/07/2026 00:00:00' 
    AND conhecimento.dtcancelamento IS NULL
    AND conhecimento.situacaocte = 3
    AND conhecimento.tipo IN (1, 4)
    AND conhecimento.unidade = 1
    GROUP BY LPAD(EXTRACT(MONTH FROM conhecimento.dtemissao)::text, 2, '0')

    UNION ALL
    
    -- ################################### -- N F  S E R V I Ç O (Atual) -- ################################### --
    SELECT 
        LPAD(EXTRACT(MONTH FROM notafiscalservico.dtemissao)::text, 2, '0') AS dt_emissao
        ,0 AS valor_cte_complementar
        ,0 AS valor_cte_normal
        ,SUM(notafiscalservico.valortotalbruto) AS valor_nfse
    FROM notafiscalservico
    JOIN cadastro pagadorfrete ON pagadorfrete.codigo = notafiscalservico.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = notafiscalservico.grupo AND agrupamentocliente_cnpjcpfcodigo.empresa = notafiscalservico.empresa AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = notafiscalservico.cnpjcpfcodigo AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
    WHERE notafiscalservico.grupo = 1 
    AND notafiscalservico.empresa = 1 
    AND notafiscalservico.numero < 1000000 
    AND notafiscalservico.dtemissao::DATE BETWEEN '01/07/2026 00:00:00' AND '17/07/2026 00:00:00' 
    AND notafiscalservico.dtcancelamento IS NULL
    AND (notafiscalservico.emissaoeletronica = 2 OR (notafiscalservico.emissaoeletronica = 1 AND notafiscalservico.situacaonfse = 3))
    GROUP BY LPAD(EXTRACT(MONTH FROM notafiscalservico.dtemissao)::text, 2, '0')
),

fat_2024 AS (
    SELECT
        faturamento24.dt_emissao AS dt_emissao_24
        ,SUM(faturamento24.valor_cte_normal) + SUM(faturamento24.valor_cte_complementar) + SUM(faturamento24.valor_nfse) AS total_realizado_24
    FROM faturamento24
    GROUP BY faturamento24.dt_emissao
)

-- ################################### -- R E S U L T A D O -- ################################### --
SELECT
    CASE WHEN fat_2023.dt_emissao_23 = '01' THEN 'Janeiro'
         WHEN fat_2023.dt_emissao_23 = '02' THEN 'Fevereiro'
         WHEN fat_2023.dt_emissao_23 = '03' THEN 'Março'
         WHEN fat_2023.dt_emissao_23 = '04' THEN 'Abril'
         WHEN fat_2023.dt_emissao_23 = '05' THEN 'Maio'
         WHEN fat_2023.dt_emissao_23 = '06' THEN 'Junho'
         WHEN fat_2023.dt_emissao_23 = '07' THEN 'Julho'
         WHEN fat_2023.dt_emissao_23 = '08' THEN 'Agosto'
         WHEN fat_2023.dt_emissao_23 = '09' THEN 'Setembro'
         WHEN fat_2023.dt_emissao_23 = '10' THEN 'Outubro'
         WHEN fat_2023.dt_emissao_23 = '11' THEN 'Novembro'
         WHEN fat_2023.dt_emissao_23 = '12' THEN 'Dezembro'
    END AS mes,
    fat_2023.total_realizado_23 AS realizado_anterior,
    fat_2024.total_realizado_24 AS realizado_atual,
    ROUND(((fat_2024.total_realizado_24 - fat_2023.total_realizado_23) / fat_2023.total_realizado_23) * 100, 2) AS dif_perc
FROM fat_2023
JOIN fat_2024
    ON fat_2024.dt_emissao_24 = fat_2023.dt_emissao_23
ORDER BY 
    fat_2023.dt_emissao_23 ASC;