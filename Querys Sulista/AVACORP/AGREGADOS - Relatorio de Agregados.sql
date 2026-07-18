WITH frete_compra_valores_calculados AS (
    SELECT
        programacaoembarque_fretecompra_valorfrete.numero,
        programacaoembarque_fretecompra_valorfrete.sequencia,
        programacaoembarque_fretecompra_valorfrete.sequenciatabela,
        programacaoembarque_fretecompra_valorfrete.sequenciavalor,
        tipocalculofretefreteiro.descricao AS tipocalculofretefreteiro_descricao,
        CASE programacaoembarque_fretecompra_valorfrete.calculadopor
            WHEN 1 THEN 'Kg' WHEN 2 THEN 'Tonelada' WHEN 3 THEN 'Volume'
            WHEN 4 THEN 'Sobre mercadoria' WHEN 5 THEN 'Valor fixo' WHEN 6 THEN 'M3'
            WHEN 7 THEN 'Eixo' WHEN 8 THEN 'Fração kg' WHEN 9 THEN 'Sobre frete'
            WHEN 11 THEN 'Km' WHEN 12 THEN 'Notas fiscais' WHEN 13 THEN 'Coletas'
            WHEN 14 THEN 'Entregas' WHEN 15 THEN 'Coletas e entregas' WHEN 16 THEN 'Faixa'
            WHEN 17 THEN 'Formula' WHEN 18 THEN 'Dias' ELSE ''
        END AS calcularpor_descricao,
        programacaoembarque_fretecompra_valorfrete.basecalculo,
        programacaoembarque_fretecompra_valorfrete.valorcalculado,
        programacaoembarque_fretecompra_valorfrete.valorperccalculo,
        programacaoembarque_fretecompra_valorfrete.valorliquido
    FROM programacaoembarque_fretecompra_valorfrete
    INNER JOIN tipocalculofretefreteiro
        ON tipocalculofretefreteiro.grupo = programacaoembarque_fretecompra_valorfrete.grupo
        AND tipocalculofretefreteiro.empresa = programacaoembarque_fretecompra_valorfrete.empresa
        AND tipocalculofretefreteiro.codigo = programacaoembarque_fretecompra_valorfrete.tipocalculofretefreteiro
), 

pagador_embarque AS (
    SELECT DISTINCT
        programacaoembarque_composicao.grupo,
        programacaoembarque_composicao.empresa,
        programacaoembarque_composicao.diferenciadornumero,
        programacaoembarque_composicao.numero AS num_prog,
        pagador.nomefantasia
    FROM programacaoembarque_composicao
    LEFT JOIN conhecimento
        ON conhecimento.grupo = programacaoembarque_composicao.grupo
        AND conhecimento.empresa = programacaoembarque_composicao.empresa
        AND conhecimento.filial = programacaoembarque_composicao.filialdocumento
        AND conhecimento.unidade = programacaoembarque_composicao.unidadedocumento
        AND conhecimento.serie = programacaoembarque_composicao.seriedocumento
        AND conhecimento.diferenciadornumero = programacaoembarque_composicao.diferenciadornumerodocumento
        AND conhecimento.numero = programacaoembarque_composicao.numerodocumento
    LEFT JOIN cadastro pagador ON pagador.codigo = conhecimento.cnpjcpfcodigopagadorfrete
),

financeiro_adiantamento AS (
    SELECT 
        pep.grupo,
        pep.empresa,
        pep.diferenciadornumerotransporte,
        pep.numerotransporte,
        MAX(cp.dtpagamento) AS dtpagamento,
        SUM(pep.valor) AS valor_adiantamento,
        pep.sequenciaparcela as sequencia_financeiro
    FROM pagamentoeletronicofrete_parcela pep
    INNER JOIN contaapagar_composicao cpc
        ON cpc.idparcela = pep.idparcela
    INNER JOIN contaapagar cp
        ON cp.grupo = cpc.grupo
        AND cp.empresa = cpc.empresa
        AND cp.filial = cpc.filial
        AND cp.unidade = cpc.unidade
        AND cp.sequencia = cpc.sequencia
    WHERE pep.dtcancelamento IS NULL
      AND pep.numerotransporte IS NOT NULL 
      AND cp.dtpagamento IS NOT NULL
    GROUP BY 
        pep.grupo,
        pep.empresa,
        pep.diferenciadornumerotransporte,
        pep.numerotransporte, 
        pep.sequenciaparcela
)

SELECT
    programacaoembarque.dtemissao AS dt_programacao,
    programacaoembarque.numero AS progr_embarque,
    CASE pagamentoeletronicofrete.filial
        WHEN 2 THEN '2 - S.B. DO CAMPO' WHEN 23 THEN '23 - SBC CD' WHEN 20 THEN '20 - CRUZEIRO'
        WHEN 7 THEN '7 - RESENDE' WHEN 15 THEN '15 - POUSO ALEGRE' WHEN 19 THEN '19 - JOINVILLE'
        WHEN 24 THEN '24 - CURITIBA' WHEN 22 THEN '22 - S.J. PINHAIS' WHEN 21 THEN '21 - PORTO ALEGRE'
        WHEN 1 THEN '1 - MTZ'
    END AS filial_ciot,
    pagamentoeletronicofrete.numerociot,
    CASE WHEN pagador_embarque.nomefantasia IS NULL THEN 'DESLOCAMENTO VAZIO'
         ELSE pagador_embarque.nomefantasia END AS cliente,
    programacaoembarque.veiculo,
    veiculo.numerofrota,
    programacaoembarque.carreta1,
    programacaoembarque.carreta2,
    tipoveiculo.descricao AS tipo_veiculo,
    utilizacaoveiculo.descricao AS utilizacao,
    proprietario.razaosocial,
    motorista.nomefantasia AS motorista,
    programacaoembarque_fretecompra.uforigem,
    programacaoembarque_fretecompra.cidadeorigem,
    programacaoembarque_fretecompra.ufdestino,
    programacaoembarque_fretecompra.cidadedestino,
    programacaoembarque_fretecompra.marcacaorodar AS km_rodado,
    frete_compra_valores_calculados.sequencia,
    UPPER(frete_compra_valores_calculados.calcularpor_descricao) AS calcularpor_descricao,
    CASE WHEN frete_compra_valores_calculados.valorperccalculo = 0 THEN 'Manual'
         ELSE 'Automático' END AS tipoinclusao,
    CASE WHEN frete_compra_valores_calculados.valorperccalculo = 0 THEN programacaoembarque_valorfretecompramanual.valor
         ELSE frete_compra_valores_calculados.valorperccalculo END AS valorperccalculo,
    frete_compra_valores_calculados.valorcalculado,   
    financeiro_adiantamento.valor_adiantamento,
    financeiro_adiantamento.dtpagamento, 
    financeiro_adiantamento.sequencia_financeiro,
    
    frete_compra_valores_calculados.sequenciatabela as sequencia_frete_tabela,
    CASE WHEN frete_compra_valores_calculados.sequenciatabela IS NOT NULL THEN(
    CASE WHEN (SELECT departamento FROM usuario WHERE codigo = 117) = 'INT. DE DADOS' THEN '??'
    ELSE NULL END) ELSE NULL END AS departamento,
    '' AS place_holder
    

FROM programacaoembarque_fretecompra


LEFT JOIN programacaoembarque
    ON programacaoembarque.grupo = programacaoembarque_fretecompra.grupo
    AND programacaoembarque.empresa = programacaoembarque_fretecompra.empresa
    AND programacaoembarque.diferenciadornumero = programacaoembarque_fretecompra.diferenciadornumero
    AND programacaoembarque.numero = programacaoembarque_fretecompra.numero
LEFT JOIN transporte_programacaoembarque
    ON transporte_programacaoembarque.grupo = programacaoembarque.grupo
    AND transporte_programacaoembarque.empresa = programacaoembarque.empresa
    AND transporte_programacaoembarque.diferenciadornumerodocumento = programacaoembarque.diferenciadornumero
    AND transporte_programacaoembarque.numerodocumento = programacaoembarque.numero
LEFT JOIN transporte
    ON transporte.grupo = transporte_programacaoembarque.grupo
    AND transporte.empresa = transporte_programacaoembarque.empresa
    AND transporte.diferenciadornumero = transporte_programacaoembarque.diferenciadornumero
    AND transporte.numero = transporte_programacaoembarque.numero

LEFT JOIN financeiro_adiantamento
    ON financeiro_adiantamento.grupo = transporte.grupo
    AND financeiro_adiantamento.empresa = transporte.empresa
    AND financeiro_adiantamento.diferenciadornumerotransporte = transporte.diferenciadornumero
    AND financeiro_adiantamento.numerotransporte = transporte.numero

LEFT JOIN pagamentoeletronicofrete_composicao
    ON pagamentoeletronicofrete_composicao.grupodocumento = transporte.grupo
    AND pagamentoeletronicofrete_composicao.empresadocumento = transporte.empresa
    AND pagamentoeletronicofrete_composicao.filialdocumento = transporte.filial
    AND pagamentoeletronicofrete_composicao.unidadedocumento = transporte.unidade
    AND pagamentoeletronicofrete_composicao.diferenciadornumerodocumento = transporte.diferenciadornumero
    AND pagamentoeletronicofrete_composicao.numerodocumento = transporte.numero
LEFT JOIN pagamentoeletronicofrete
    ON pagamentoeletronicofrete.grupo = pagamentoeletronicofrete_composicao.grupo
    AND pagamentoeletronicofrete.empresa = pagamentoeletronicofrete_composicao.empresa
    AND pagamentoeletronicofrete.sequencia = pagamentoeletronicofrete_composicao.sequencia

LEFT JOIN frete_compra_valores_calculados
    ON programacaoembarque.numero = frete_compra_valores_calculados.numero
LEFT JOIN programacaoembarque_valorfretecompramanual
    ON programacaoembarque_valorfretecompramanual.grupo = programacaoembarque_fretecompra.grupo
    AND programacaoembarque_valorfretecompramanual.empresa = programacaoembarque_fretecompra.empresa
    AND programacaoembarque_valorfretecompramanual.diferenciadornumero = programacaoembarque_fretecompra.diferenciadornumero
    AND programacaoembarque_valorfretecompramanual.numero = programacaoembarque_fretecompra.numero
    AND programacaoembarque_valorfretecompramanual.sequencia = frete_compra_valores_calculados.sequencia
LEFT JOIN veiculo ON programacaoembarque.veiculo = veiculo.placa
LEFT JOIN utilizacaoveiculo ON veiculo.utilizacaoveiculo = utilizacaoveiculo.codigo
LEFT JOIN tipoveiculo ON veiculo.tipoveiculo = tipoveiculo.codigo
LEFT JOIN cadastro motorista ON programacaoembarque.motorista = motorista.codigo
LEFT JOIN pagador_embarque
    ON pagador_embarque.grupo = programacaoembarque.grupo
    AND pagador_embarque.empresa = programacaoembarque.empresa
    AND pagador_embarque.diferenciadornumero = programacaoembarque.diferenciadornumero
    AND pagador_embarque.num_prog = programacaoembarque.numero
LEFT JOIN cadastro proprietario ON proprietario.codigo = veiculo.proprietario

WHERE
    programacaoembarque.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
AND utilizacaoveiculo.descricao = 'AGREGADOS'
AND programacaoembarque.dtcancelamento IS NULL
--AND programacaoembarque.numero = 162632

ORDER BY
    programacaoembarque.dtemissao DESC;