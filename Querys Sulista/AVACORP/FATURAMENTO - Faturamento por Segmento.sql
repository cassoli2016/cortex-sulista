-- Faturamento por Segmento // Ajustar a data conforme necessidade

WITH segmento AS (
    SELECT
        CASE WHEN tipocarga.descricao = 'METAL MECANICO' THEN 'Metal Mec.'
             WHEN tipocarga.descricao = 'AUTOMOTIVO PESADO' THEN 'Auto Pesado'
             WHEN tipocarga.descricao = 'AUTOMOTIVO LEVE' THEN 'Auto Leve'
             WHEN tipocarga.descricao = 'COSMETICO' THEN 'Cosmetico'
             WHEN tipocarga.descricao = 'LINHA BRANCA' THEN 'Linha Branca'
             WHEN tipocarga.descricao = 'SPOT' THEN 'Outros'
             WHEN tipocarga.descricao = 'PLASTICOS' THEN 'Plásticos'
             WHEN tipocarga.descricao = 'EMBALAGEM' THEN 'Embalagem'
             WHEN tipocarga.descricao = 'AEROSSOL' THEN 'Aerossol'
             WHEN tipocarga.descricao = 'MINERACAO' THEN 'Mineração'
             WHEN tipocarga.descricao = 'SUBCONTRATADO' THEN 'Outros'
             WHEN tipocarga.descricao = 'CONSTRUCAO' THEN 'Construção'
             WHEN tipocarga.descricao = 'MOVEIS' THEN 'Móveis'
             WHEN tipocarga.descricao = 'TELECOM/ELETRICO' THEN 'Telecom/Elétrico'
             WHEN tipocarga.descricao = 'MADEREIRO' THEN 'Outros'
             WHEN tipocarga.descricao = 'RACAO ANIMAL' THEN 'Ração Animal'
             WHEN tipocarga.descricao = 'TELECOM/ ELETRICO' THEN 'Telecom/Elétrico'
             WHEN tipocarga.descricao = 'LOTACAO' THEN 'Outros' 
             ELSE 'N/A' END as segmento,
        SUM(conhecimento.valortotalprestacao) AS valor
    FROM conhecimento
    JOIN avacorpi.tipoconhecimento
        ON avacorpi.tipoconhecimento.id = conhecimento.tipo
    LEFT JOIN veiculo
        ON conhecimento.veiculo = veiculo.placa
    LEFT JOIN tipocarga 
        ON conhecimento.tipocarga = tipocarga.codigo
    LEFT JOIN tipofrete
        ON conhecimento.grupo = tipofrete.grupo
        AND conhecimento.empresa = tipofrete.empresa
        AND conhecimento.tipofrete = tipofrete.codigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo
        ON agrupamentocliente_cnpjcpfcodigo.grupo = conhecimento.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = conhecimento.empresa
        AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = conhecimento.cnpjcpfcodigopagadorfrete
    LEFT JOIN agrupamentocliente
        ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
        AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
        AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
    WHERE conhecimento.grupo = 1
        AND conhecimento.empresa = 1
        AND conhecimento.dtemissao::DATE BETWEEN '2026-01-01' AND '2026-12-31'
        AND veiculo.utilizacaoveiculo IN ('TRA', 'LOC', 'AGR', 'TER', 'PREV')
        AND conhecimento.dtcancelamento IS NULL
        AND conhecimento.situacaocte = 3
        AND conhecimento.filial <> 0
        -- CT-e Normal e Substituido
        AND conhecimento.tipo IN (1,4)
        AND agrupamentocliente.descricao <> 'a'
        AND conhecimento.unidade = 1
    GROUP BY
        tipocarga.descricao
)

SELECT
    segmento.segmento AS segmento,
    SUM(segmento.valor) AS valor,
    ROUND((SUM(segmento.valor) * 100) / SUM(SUM(segmento.valor)) OVER (), 2) AS percentual
FROM segmento
GROUP BY
    segmento.segmento
ORDER BY
    valor DESC;