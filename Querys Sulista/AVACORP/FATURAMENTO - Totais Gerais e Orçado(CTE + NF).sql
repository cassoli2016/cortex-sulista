-- Total Faturado x orçado - Por nota e CTE // Ajustar a data conforme necessidade

WITH faturamento AS (
SELECT 
     SUM(conhecimento.valortotalprestacao) AS valor_cte
    , 0 AS valor_nfse
    , 0 AS valor_orcado 
FROM conhecimento
LEFT JOIN veiculo
ON conhecimento.veiculo = veiculo.placa
JOIN avacorpi.tipoconhecimento
ON avacorpi.tipoconhecimento.id = conhecimento.tipo
JOIN cadastro pagadorfrete 
ON pagadorfrete.codigo = conhecimento.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente_cnpjcpfcodigo
ON agrupamentocliente_cnpjcpfcodigo.grupo = conhecimento.grupo
AND agrupamentocliente_cnpjcpfcodigo.empresa = conhecimento.empresa
AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = conhecimento.cnpjcpfcodigopagadorfrete
AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
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
 
 
--###################################-- N F   S E R V I Ç O --###################################--
UNION ALL
 
SELECT  -- N F   S E R V I Ç O
0 as valor_cte
    , SUM(notafiscalservico.valortotalbruto) AS valor_nfse
    , 0 AS valor_orcado 
FROM notafiscalservico
JOIN cadastro pagadorfrete 
ON pagadorfrete.codigo = notafiscalservico.cnpjcpfcodigo
LEFT JOIN agrupamentocliente_cnpjcpfcodigo
ON agrupamentocliente_cnpjcpfcodigo.grupo = notafiscalservico.grupo
AND agrupamentocliente_cnpjcpfcodigo.empresa = notafiscalservico.empresa
AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = notafiscalservico.cnpjcpfcodigo
AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
LEFT JOIN agrupamentocliente
ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
 
WHERE notafiscalservico.grupo = 1
AND notafiscalservico.empresa = 1
AND notafiscalservico.numero<1000000
AND notafiscalservico.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'
AND notafiscalservico.dtemissao::DATE >= '01/06/2023'
AND notafiscalservico.dtcancelamento IS NULL
AND (notafiscalservico.emissaoeletronica = 2 OR (notafiscalservico.emissaoeletronica = 1 AND notafiscalservico.situacaonfse = 3))
 
AND coalesce (NULL,'') = ''
 
--###################################-- M E T A S --###################################--
UNION ALL
SELECT
    0 AS valor_cte
  , 0 AS valor_nfse
  , SUM(sulista.metafaturamento_agrupamentoclientedia.valor) AS valor_orçado
 
FROM
sulista.metafaturamento_agrupamentoclientedia
 
LEFT JOIN agrupamentocliente
ON agrupamentocliente.codigo = sulista.metafaturamento_agrupamentoclientedia.agrupamentocliente
AND agrupamentocliente.grupo = sulista.metafaturamento_agrupamentoclientedia.grupo
AND agrupamentocliente.empresa = sulista.metafaturamento_agrupamentoclientedia.empresa
 
WHERE
 
sulista.metafaturamento_agrupamentoclientedia.dt BETWEEN '2026-07-01' AND '2026-07-17'
AND sulista.metafaturamento_agrupamentoclientedia.tipo =  1

 
GROUP BY
 
    EXTRACT(YEAR FROM sulista.metafaturamento_agrupamentoclientedia.dt)  || ' - ' ||
      LPAD(EXTRACT(MONTH FROM sulista.metafaturamento_agrupamentoclientedia.dt)::text, 2, '0')
    , LPAD(EXTRACT(DAY FROM sulista.metafaturamento_agrupamentoclientedia.dt)::text, 2, '0') 



UNION ALL
--###################################-- K  M  M --###################################--


SELECT

     SUM(sulista.faturamentokmm.valor_cte) AS valor_cte
    , 0 AS valor_nfse
    , 0 AS valor_orcado 

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
ON veiculo.placa = sulista.faturamentokmm.placa

WHERE 

sulista.faturamentokmm.dtemissao::DATE BETWEEN '2026-07-01' AND '2026-07-17'



)
--###################################-- R E T O R N O --###################################--
 
SELECT
      TRIM(TO_CHAR(SUM(faturamento.valor_cte),'999G999G999D')) AS valor_realizado_cte
    , TRIM(TO_CHAR(SUM(faturamento.valor_nfse),'999G999G999D')) AS valor_realizado_nfse
    , TRIM(TO_CHAR(SUM(faturamento.valor_nfse) + SUM(faturamento.valor_cte),'999G999G999D')) AS valor_realizado
    , TRIM(TO_CHAR(SUM(faturamento.valor_orcado), '999G999G999D')) AS valor_orcado
    , ROUND(COALESCE(NULLIF(SUM(faturamento.valor_cte) + SUM(faturamento.valor_nfse), 0) 
      /
      NULLIF(SUM(faturamento.valor_orcado), 0), 0) * 100, 0) AS perc_atingido
    , TRIM(TO_CHAR(
    (SUM(faturamento.valor_nfse) + SUM(faturamento.valor_cte)) - SUM(faturamento.valor_orcado),
    '999G999G999D')) AS diferenca_orcadorealizado


FROM faturamento