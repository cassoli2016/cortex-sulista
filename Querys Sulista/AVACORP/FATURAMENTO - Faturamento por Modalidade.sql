-- FATURAMENTO POR TIPO DE FROTA // alterar data conforme necessario

WITH faturamento AS (

SELECT
     utilizacaoveiculo.descricao AS modalidade
    ,conhecimento.valortotalprestacao AS valor
    ,veiculo.utilizacaoveiculo as utilizacaoveiculo

FROM conhecimento

JOIN avacorpi.tipoconhecimento
ON avacorpi.tipoconhecimento.id = conhecimento.tipo

JOIN cadastro pagadorfrete 
ON pagadorfrete.codigo = conhecimento.cnpjcpfcodigopagadorfrete

LEFT JOIN veiculo
ON conhecimento.veiculo = veiculo.placa

LEFT JOIN utilizacaoveiculo
on utilizacaoveiculo.codigo = veiculo.utilizacaoveiculo

LEFT JOIN tiponegocio
ON conhecimento.grupo = tiponegocio.grupo
AND conhecimento.empresa = tiponegocio.empresa
AND conhecimento.tiponegocio = tiponegocio.id

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
AND conhecimento.numero<1000000
AND conhecimento.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
AND conhecimento.dtemissao::DATE >= '01/06/2023'
AND conhecimento.dtcancelamento IS NULL
AND conhecimento.situacaocte = 3
-- CT-e Normal e Substituido
AND conhecimento.tipo IN (1,4)
AND conhecimento.unidade = 1

AND utilizacaoveiculo.descricao IN ('AGREGADOS', 'FROTA', 'LOCACAO', 'TERCEIROS')



UNION ALL

--###################################-- K  M  M --###################################--


SELECT

      sulista.faturamentokmm.utilizacaoveiculodescricao AS modalidade
    , SUM(sulista.faturamentokmm.valor_cte) AS valor
    , sulista.faturamentokmm.utilizacaoveiculo AS utilizacaoveiculo
           

FROM 
sulista.faturamentokmm

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
ON sulista.faturamentokmm.placa = veiculo.placa

LEFT JOIN utilizacaoveiculo
on utilizacaoveiculo.codigo = veiculo.utilizacaoveiculo

WHERE 

sulista.faturamentokmm.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
AND sulista.faturamentokmm.tipodocumento = 'CT-e'


GROUP BY

  sulista.faturamentokmm.utilizacaoveiculodescricao
, sulista.faturamentokmm.utilizacaoveiculo

)

SELECT 

  retorno.modalidade
, retorno.valor as valor
, (retorno.valor * 100)/SUM(retorno.valor) OVER() AS percentual
, retorno.utilizacaoveiculo

FROM  

(
SELECT
    faturamento.modalidade
  , faturamento.utilizacaoveiculo
  , SUM(faturamento.valor) as valor

  FROM
  faturamento


  GROUP BY
    faturamento.modalidade, faturamento.utilizacaoveiculo
  ORDER BY
    SUM(faturamento.valor) DESC
) retorno