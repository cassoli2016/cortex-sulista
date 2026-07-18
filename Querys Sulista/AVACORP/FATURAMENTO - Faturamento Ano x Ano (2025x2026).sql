-- ANO ATUAL X ANO PASSADO (faturado)  // Ajustar a data conforme necessidade


WITH faturamento_anterior AS (
    -- ################################### -- A V A C O R P (Período Anterior) -- ################################### --
    SELECT
        EXTRACT(MONTH FROM conhecimento.dtemissao) AS dt_emissao
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
    GROUP BY EXTRACT(MONTH FROM conhecimento.dtemissao)

    UNION ALL

    -- ################################### -- K M M (Período Anterior) -- ################################### --
    SELECT
        EXTRACT(MONTH FROM sulista.faturamentokmm.dtemissao) AS dt_emissao
        ,COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'CT-e' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_cte_normal
        ,0 AS valor_cte_complementar
        ,COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'NFS' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_nfse
    FROM sulista.faturamentokmm
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = sulista.faturamentokmm.grupo AND agrupamentocliente_cnpjcpfcodigo.empresa = sulista.faturamentokmm.empresa AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = sulista.faturamentokmm.pagadorfrete_cnpj AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
    LEFT JOIN agrupamentocliente ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
    LEFT JOIN veiculo ON veiculo.placa = sulista.faturamentokmm.placa
    WHERE sulista.faturamentokmm.dtemissao::DATE BETWEEN ('01/07/2026 00:00:00'::DATE - INTERVAL '1 year') AND ('17/07/2026 00:00:00'::DATE - INTERVAL '1 year')
    GROUP BY EXTRACT(MONTH FROM sulista.faturamentokmm.dtemissao), sulista.faturamentokmm.tipodocumento

    UNION ALL

    -- ################################### -- N F S E R V I Ç O (Período Anterior) -- ################################### --
    SELECT 
        EXTRACT(MONTH FROM notafiscalservico.dtemissao) AS dt_emissao
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
    GROUP BY EXTRACT(MONTH FROM notafiscalservico.dtemissao)
),

faturamento_atual AS (
    -- ################################### -- A V A C O R P (Período Atual) -- ################################### --
    SELECT
        EXTRACT(MONTH FROM conhecimento.dtemissao) AS dt_emissao
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
    GROUP BY EXTRACT(MONTH FROM conhecimento.dtemissao)

    UNION ALL

    -- ################################### -- N F S E R V I Ç O (Período Atual) -- ################################### --
    SELECT 
        EXTRACT(MONTH FROM notafiscalservico.dtemissao) AS dt_emissao
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
    GROUP BY EXTRACT(MONTH FROM notafiscalservico.dtemissao)
),

consolida_anterior AS (
    SELECT
        dt_emissao,
        SUM(valor_cte_normal) + SUM(valor_cte_complementar) + SUM(valor_nfse) AS total_realizado
    FROM faturamento_anterior
    GROUP BY dt_emissao
),

consolida_atual AS (
    SELECT
        dt_emissao,
        SUM(valor_cte_normal) + SUM(valor_cte_complementar) + SUM(valor_nfse) AS total_realizado
    FROM faturamento_atual
    GROUP BY dt_emissao
)

-- ################################### -- R E S U L T A D O -- ################################### --
SELECT
    SUM(ant.total_realizado) AS total_periodo_anterior,
    SUM(atu.total_realizado) AS total_periodo_atual,
    SUM(atu.total_realizado) - SUM(ant.total_realizado) AS diferenca_valor
FROM consolida_anterior ant
JOIN consolida_atual atu 
    ON ant.dt_emissao = atu.dt_emissao;