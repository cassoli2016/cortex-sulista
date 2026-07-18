-- Qtde docs e total em aberto TOTAIS

WITH FaturasVencidas AS (
    SELECT DISTINCT
        CASE
            WHEN fatura_composicao.tipodocumentoorigem = 6 THEN 'CT-e'
            WHEN fatura_composicao.tipodocumentoorigem = 10 THEN 'NFS-e'
            ELSE
                tipodocumento.identificacaolivrofiscal
            END AS tipodocumento,
        fatura_composicao.sequencia,
        fatura_composicao.numerosequenciadocumentoorigem AS documento_numero,
        fatura_composicao.filialdocumentoorigem AS documento_filial,
        fatura_composicao.unidadedocumentoorigem AS documento_unidade,
        fatura_composicao.seriedocumentoorigem AS documento_serie,
        fatura.cliente AS cnpjcpfcodigocliente,
        cadastro.razaosocial AS cliente_razaosocial,
        agrupamentocliente.descricao AS grupo_cliente,
        agrupamentocliente.codigo AS codigo_cliente,
        fatura.numero AS fatura_numero,
        fatura.filial AS fatura_filial,
        fatura.unidade AS fatura_unidade,
        CASE
            WHEN COALESCE(fatura.dtprevisaopagamento, fatura.dtvencimento) < CURRENT_DATE AND fatura.dtpagamento IS NULL
            THEN 'Vencido'
            ELSE 'À Vencer'
            END AS fatura_situacao,
        CASE
            WHEN CURRENT_DATE - COALESCE(fatura.dtprevisaopagamento, fatura.dtvencimento) > 90 THEN 'ACIMA DE 90 DIAS'
        END AS tempo_vencido,
        fatura.dtemissao,
        fatura.dtvencimento,
        fatura.dtprevisaopagamento,
        fatura_composicao.valortitulo,
        fatura_composicao.valorpendentecnpjcliente AS valorpendente
    FROM fatura
    JOIN fatura_composicao ON fatura_composicao.grupo = fatura.grupo
        AND fatura_composicao.empresa = fatura.empresa
        AND fatura_composicao.filial = fatura.filial
        AND fatura_composicao.unidade = fatura.unidade
        AND fatura_composicao.sequencia = fatura.sequencia
    LEFT JOIN tipodocumento ON tipodocumento.codigo = fatura_composicao.tipodocumentoorigem
    JOIN cadastro ON cadastro.codigo = fatura.cliente
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
        AND fatura.dtvencimento BETWEEN '2023-08-23' AND '2026-07-16'
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
), DocumentosUnicos AS (
    SELECT DISTINCT
        tipodocumento || '-' || documento_numero || '-' || documento_filial || '-' || documento_unidade || '-' || documento_serie AS doc_chave,
        valorpendente
    FROM FaturasVencidas
    WHERE fatura_situacao = 'Vencido'
)
SELECT
    COUNT(doc_chave) AS qtde_doc,
    TO_CHAR(SUM(valorpendente), 'FM999G999G999D99') AS total_em_aberto
FROM DocumentosUnicos;