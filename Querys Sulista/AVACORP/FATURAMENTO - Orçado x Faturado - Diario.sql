-- Meta x Faturado diario // ajustar data conforme necessecidade

WITH faturamento AS (
    -- ################################### -- CONHECIMENTOS (CT-e) -- ################################### --
    SELECT
        conhecimento.dtemissao::DATE AS data_referencia
        -- LISTAGEM DE CONHECIMENTOS NORMAIS
        ,SUM(CASE WHEN conhecimento.complementar = 2 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_normal
        -- LISTAGEM DE CONHECIMENTOS COMPLEMENTARES
        ,SUM(CASE WHEN conhecimento.complementar = 1 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_complementar
        ,0 AS valor_nfse
        ,0 AS valor_meta
    FROM conhecimento
    LEFT JOIN veiculo
        ON conhecimento.veiculo = veiculo.placa
    LEFT JOIN tiponegocio
        ON conhecimento.grupo = tiponegocio.grupo
        AND conhecimento.empresa = tiponegocio.empresa
        AND conhecimento.tiponegocio = tiponegocio.id
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo
        ON agrupamentocliente_cnpjcpfcodigo.grupo = conhecimento.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = conhecimento.empresa
        AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = conhecimento.cnpjcpfcodigopagadorfrete
    WHERE conhecimento.grupo = 1
        AND conhecimento.empresa = 1 
        AND conhecimento.numero < 1000000 
        AND conhecimento.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
        AND conhecimento.dtemissao::DATE >= '01/06/2023'
        AND conhecimento.dtcancelamento IS NULL
        AND conhecimento.situacaocte = 3
        -- CT-e Normal e Substituido
        AND conhecimento.tipo IN (1, 4)
        AND conhecimento.unidade = 1
    GROUP BY 
        conhecimento.dtemissao::DATE

    UNION ALL

    -- ################################### -- K M M -- ################################### --
    SELECT
        sulista.faturamentokmm.dtemissao::DATE AS data_referencia
        ,COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'CT-e' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_cte_normal
        ,0 AS valor_cte_complementar
        ,COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'NFS' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_nfse
        ,0 AS valor_meta
    FROM sulista.faturamentokmm
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo
        ON agrupamentocliente_cnpjcpfcodigo.grupo = sulista.faturamentokmm.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = sulista.faturamentokmm.empresa
        AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = sulista.faturamentokmm.pagadorfrete_cnpj
        AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
    LEFT JOIN agrupamentocliente
        ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
        AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
        AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
    LEFT JOIN veiculo
        ON veiculo.placa = sulista.faturamentokmm.placa
    WHERE sulista.faturamentokmm.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
    GROUP BY
        sulista.faturamentokmm.dtemissao::DATE
        ,sulista.faturamentokmm.tipodocumento

    UNION ALL

    -- ################################### -- N F S - E -- ################################### --
    SELECT  
        notafiscalservico.dtemissao::DATE AS data_referencia
        ,0 AS valor_cte_complementar
        ,0 AS valor_cte_normal
        ,SUM(notafiscalservico.valortotalbruto) AS valor_nfse
        ,0 AS valor_meta
    FROM notafiscalservico
    JOIN cadastro pagadorfrete 
        ON pagadorfrete.codigo = notafiscalservico.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo
        ON agrupamentocliente_cnpjcpfcodigo.grupo = notafiscalservico.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = notafiscalservico.empresa
        AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = notafiscalservico.cnpjcpfcodigo
        AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
    WHERE notafiscalservico.grupo = 1
        AND notafiscalservico.empresa = 1
        AND notafiscalservico.numero < 1000000 
        AND notafiscalservico.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
        AND notafiscalservico.dtemissao::DATE >= '01/06/2023'
        AND notafiscalservico.dtcancelamento IS NULL
        AND (notafiscalservico.emissaoeletronica = 2 
             OR (notafiscalservico.emissaoeletronica = 1 AND notafiscalservico.situacaonfse = 3))
    GROUP BY 
        notafiscalservico.dtemissao::DATE

    UNION ALL

    -- ################################### -- M E T A S -- ################################### --
    SELECT
        sulista.metafaturamento_agrupamentoclientedia.dt::DATE AS data_referencia
        ,0 AS valor_cte_complementar
        ,0 AS valor_cte_normal
        ,0 AS valor_nfse
        ,SUM(sulista.metafaturamento_agrupamentoclientedia.valor) AS valor_meta
    FROM sulista.metafaturamento_agrupamentoclientedia
    WHERE sulista.metafaturamento_agrupamentoclientedia.dt BETWEEN '2026-07-01' AND '2026-07-17'
        AND sulista.metafaturamento_agrupamentoclientedia.tipo = 1
    GROUP BY
        sulista.metafaturamento_agrupamentoclientedia.dt::DATE
)
-- ################################### -- R E S U L T A D O -- ################################### --
SELECT
    TO_CHAR(faturamento.data_referencia, 'DD/MM/YYYY') AS data_emissao,
    SUM(faturamento.valor_meta) AS valor_meta,
    COALESCE(SUM(faturamento.valor_cte_normal) + SUM(faturamento.valor_cte_complementar) + SUM(faturamento.valor_nfse), 0) AS total_realizado
FROM faturamento
GROUP BY 
    faturamento.data_referencia
ORDER BY
    faturamento.data_referencia ASC;