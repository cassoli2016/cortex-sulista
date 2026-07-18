-- Inadimplentes acima de 1 dia

WITH FaturasVencidas AS (
    SELECT DISTINCT
        CASE
            WHEN fatura_composicao.tipodocumentoorigem = 6 THEN 'CT-e'
            WHEN fatura_composicao.tipodocumentoorigem = 10 THEN 'NFS-e'
            ELSE
                tipodocumento.identificacaolivrofiscal
            END AS tipodocumento,
        agrupamentocliente.descricao AS grupo_cliente,
        agrupamentocliente.codigo as codigo_cliente,
        CASE
            WHEN COALESCE(fatura.dtprevisaopagamento, fatura.dtvencimento) < CURRENT_DATE AND fatura.dtpagamento IS NULL
            THEN 'Vencido'
            ELSE 'À Vencer'
            END AS fatura_situacao,
        fatura_composicao.valorpendentecnpjcliente AS valorpendente,
        (CURRENT_DATE - COALESCE(fatura.dtprevisaopagamento, fatura.dtvencimento)) AS dias_vencido
    FROM fatura
    
    JOIN fatura_composicao USING (grupo, empresa, filial, unidade, sequencia)
    LEFT JOIN tipodocumento ON tipodocumento.codigo = fatura_composicao.tipodocumentoorigem
    JOIN cadastro cliente ON cliente.codigo = fatura.cliente
    LEFT JOIN conhecimento ON conhecimento.grupo = fatura_composicao.grupodocumentoorigem
        AND conhecimento.empresa = fatura_composicao.empresadocumentoorigem
        AND conhecimento.filial = fatura_composicao.filialdocumentoorigem
        AND conhecimento.unidade = fatura_composicao.unidadedocumentoorigem
        AND conhecimento.diferenciadornumero = fatura_composicao.diferenciadornumerodocumentoorigem
        AND conhecimento.serie = fatura_composicao.seriedocumentoorigem
        AND conhecimento.numero = fatura_composicao.numerosequenciadocumentoorigem
        AND fatura_composicao.tipodocumentoorigem = 6
    LEFT JOIN notafiscalservico_calculofrete ON notafiscalservico_calculofrete.grupo = fatura_composicao.grupodocumentoorigem
        AND notafiscalservico_calculofrete.empresa = fatura_composicao.empresadocumentoorigem
        AND notafiscalservico_calculofrete.filial = fatura_composicao.filialdocumentoorigem
        AND notafiscalservico_calculofrete.unidade = fatura_composicao.unidadedocumentoorigem
        AND notafiscalservico_calculofrete.diferenciadornumero = fatura_composicao.diferenciadornumerodocumentoorigem
        AND notafiscalservico_calculofrete.serie = fatura_composicao.seriedocumentoorigem
        AND notafiscalservico_calculofrete.numero = fatura_composicao.numerosequenciadocumentoorigem
        AND fatura_composicao.tipodocumentoorigem = 10
    LEFT JOIN recibo ON recibo.grupo = fatura_composicao.grupodocumentoorigem
        AND recibo.empresa = fatura_composicao.empresadocumentoorigem
        AND recibo.filial = fatura_composicao.filialdocumentoorigem
        AND recibo.unidade = fatura_composicao.unidadedocumentoorigem
        AND recibo.diferenciadornumero = fatura_composicao.diferenciadornumerodocumentoorigem
        AND recibo.serie = fatura_composicao.seriedocumentoorigem
        AND recibo.numero = fatura_composicao.numerosequenciadocumentoorigem
        AND fatura_composicao.tipodocumentoorigem = 8
    LEFT JOIN tiponegocio ON tiponegocio.id = CASE
            WHEN fatura_composicao.tipodocumentoorigem = 6 THEN conhecimento.tiponegocio
            WHEN fatura_composicao.tipodocumentoorigem = 10 THEN notafiscalservico_calculofrete.tiponegocio
            WHEN fatura_composicao.tipodocumentoorigem = 8 THEN recibo.tiponegocio
        END
    LEFT JOIN tipocarga ON tipocarga.grupo = fatura.grupo
        AND tipocarga.empresa = fatura.empresa
        AND tipocarga.codigo = CASE
            WHEN fatura_composicao.tipodocumentoorigem = 6 THEN conhecimento.tipocarga
            WHEN fatura_composicao.tipodocumentoorigem = 10 THEN notafiscalservico_calculofrete.tipocarga
        END
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo ON agrupamentocliente_cnpjcpfcodigo.grupo = fatura.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = fatura.empresa
        AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = fatura.cliente
    LEFT JOIN agrupamentocliente ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
        AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
        AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
    WHERE fatura.grupo = 1
        AND (COALESCE(NULL, 0) = 0 OR fatura.empresa = NULL)
        AND (COALESCE(NULL, 0) = 0 OR fatura.filial = NULL)
        AND (COALESCE(NULL, 0) = 0 OR fatura.unidade = NULL)
        AND fatura_composicao.valorpendentecnpjcliente > 0
        AND fatura.dtcancelamento IS NULL
        AND CASE
            WHEN 'Faturado' = 'Todos' THEN TRUE
            WHEN 'Faturado' = 'Faturado' THEN fatura.composicao = 1
            WHEN 'Faturado' = 'Pendente de Faturamento' THEN fatura.composicao = 2
        END
        AND CASE
            WHEN COALESCE('', '') = '' THEN TRUE
            ELSE
                (CASE
                    WHEN NULL = 'Agrupamento do Cliente' THEN COALESCE(agrupamentocliente.descricao, 'SEM AGRUPAMENTO')
                    WHEN NULL = 'Tipo de Negócio' THEN COALESCE(tiponegocio.descricao, 'SEM TIPO DE NEGÓCIO')
                END) = ''
        END
        AND CASE
            WHEN COALESCE(NULL, '') = '' THEN TRUE
            ELSE COALESCE(tipocarga.descricao, 'SEM TIPO DE CARGA') = NULL
        END
        AND CASE
            WHEN COALESCE('', '') = '' THEN TRUE
            ELSE fatura.cliente = ''
        END
        AND CASE
            WHEN fatura_composicao.tipodocumentoorigem = 6 THEN conhecimento.situacaocte = 3
            ELSE TRUE
        END
        AND fatura_composicao.tipodocumentoorigem = ANY (string_to_array('6,8,10,11', ',')::INT[])
        AND CASE
            WHEN COALESCE(NULL, '') = '' THEN TRUE
            ELSE tiponegocio.descricao = ANY (STRING_TO_ARRAY(NULL, ','))
        END
)
SELECT
    grupo_cliente,
    codigo_cliente,
    COUNT(*) AS qtd_documentos,
    CASE
        WHEN dias_vencido <= 15 THEN 'Até 15 Dias'
        WHEN dias_vencido > 15 AND dias_vencido <= 30 THEN 'Até 30 Dias'
        WHEN dias_vencido > 30 AND dias_vencido <= 90 THEN 'Até 90 Dias'
        ELSE 'Acima de 90 Dias'
    END AS faixa_vencimento,
    SUM(valorpendente) AS "valor_vencido", -- valor vencido - 1 dia
    ROUND((SUM(valorpendente) * 100.0 / SUM(SUM(valorpendente)) OVER ()), 2)::TEXT || '%' AS percentual_vencido,
    '' as leg_consultar
    
FROM
    FaturasVencidas
WHERE
    fatura_situacao = 'Vencido'
    AND dias_vencido >= 1
GROUP BY
    faixa_vencimento,
    grupo_cliente,
    codigo_cliente
    
ORDER BY
   valor_vencido desc 