-- ABASTECIMENTOS PENDENTES FORA DO ACERTO DE AGREGADO
WITH abastecimento AS (

SELECT 

  notafiscalsimples.veiculo::text AS placa
, veiculo,numerofrota
, avacorpi.fnc_formata_cnpjcpf(notafiscalsimples.cnpjcpfcodigoveiculo)::text AS cnpj_agregado
, agregado.nomefantasia::text AS nome_agregado
, notafiscalsimples.dtemissao::date AS data
, 'ABASTECIMENTO'::text AS descricao
, 'SUBTRAIR'::text AS tipooperacao
, notafiscalsimples.valorapagar AS valor

FROM notafiscalsimples

LEFT JOIN veiculo
ON veiculo.placa = notafiscalsimples.veiculo

LEFT JOIN cadastro agregado
ON agregado.codigo = notafiscalsimples.cnpjcpfcodigoveiculo

LEFT JOIN cadastro posto
ON posto.codigo = notafiscalsimples.fornecedor

WHERE

  notafiscalsimples.numeroacertoviagem IS NULL
AND veiculo.utilizacaoveiculo = 'AGR'

ORDER BY
notafiscalsimples.dtemissao DESC

), manuais AS (
-- LANÇAMENTOS MANUAIS

SELECT 

  calculo.veiculo::text AS placa
, veiculo.numerofrota
, avacorpi.fnc_formata_cnpjcpf(calculo.cnpjcpfcodigoveiculo)::text AS cnpj_agregado
, agregado.nomefantasia::text AS nome_agregado
, calculo.dtlancamento::date AS data
, tipocalculoacertoviagem.descricao::text AS descricao
, CASE WHEN calculo.tipooperacao = 1 THEN 'SOMAR'::text
       WHEN calculo.tipooperacao = 2 THEN 'SUBTRAIR'::text
       WHEN calculo.tipooperacao = 3 THEN 'RECEITA'::text
       ELSE 'DESPESA'::text
       END AS tipooperacao
, calculo.valor

FROM avacorpi.acertoviagemagregado_calculomanual calculo

LEFT JOIN cadastro fornecedor
ON fornecedor.codigo = calculo.cnpjcpfcodigo

LEFT JOIN cadastro agregado
ON agregado.codigo = calculo.cnpjcpfcodigoveiculo

JOIN tipocalculoacertoviagem
ON tipocalculoacertoviagem.grupo = calculo.grupo
AND tipocalculoacertoviagem.empresa = calculo.empresa
AND tipocalculoacertoviagem.codigo = calculo.tipocalculoacertoviagem

LEFT JOIN acertoviagemagregado_calculo
ON acertoviagemagregado_calculo.sequenciacalculoavai = calculo.sequencia

LEFT JOIN veiculo
ON veiculo.placa = calculo.veiculo

WHERE

 acertoviagemagregado_calculo.numero IS NULL

ORDER BY 
calculo.sequencia DESC

)

SELECT
  abastecimento.nome_agregado
, abastecimento.placa
, abastecimento.numerofrota
, abastecimento.cnpj_agregado
, abastecimento.data
, abastecimento.descricao
, abastecimento.tipooperacao
, abastecimento.valor

FROM abastecimento

UNION ALL

SELECT
  manuais.nome_agregado
, manuais.placa
, manuais.numerofrota
, manuais.cnpj_agregado
, manuais.data
, manuais.descricao
, manuais.tipooperacao
, manuais.valor

FROM manuais

ORDER BY 
nome_agregado asc