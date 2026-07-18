-- FATURAMENTO POR CLIENTE // NESTE É PRECISO ALTERAR A DATA DE ACORDO COM NESSECIDADE

WITH faturamento AS (
SELECT
      COALESCE(agrupamentocliente.codigo::VARCHAR,conhecimento.cnpjcpfcodigopagadorfrete) AS codigo
    , COALESCE(agrupamentocliente.descricao,pagadorfrete.razaosocial) AS descricao
      -- LISTAGEM DE CONHECIMENTOS COMPLEMENTARES
    , SUM(CASE WHEN conhecimento.complementar = 1 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_complementar
      -- LISTAGEM DE CONHECIMENTOS NORMAIS
    , SUM(CASE WHEN conhecimento.complementar = 2 THEN conhecimento.valortotalprestacao ELSE 0 END) AS valor_cte_normal
    , 0 as valor_nfse
    , 0 AS valor_meta
    
FROM conhecimento

JOIN avacorpi.tipoconhecimento
ON avacorpi.tipoconhecimento.id = conhecimento.tipo

LEFT JOIN veiculo
ON conhecimento.veiculo = veiculo.placa

LEFT JOIN tiponegocio
ON conhecimento.grupo = tiponegocio.grupo
AND conhecimento.empresa = tiponegocio.empresa
AND conhecimento.tiponegocio = tiponegocio.id

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




GROUP BY 
    COALESCE(agrupamentocliente.codigo::VARCHAR,conhecimento.cnpjcpfcodigopagadorfrete) 
   ,COALESCE(agrupamentocliente.descricao,pagadorfrete.razaosocial) 
   
--###################################-- N F   S E R V I Ç O --###################################--

UNION ALL

SELECT  -- N F   S E R V I Ç O
      COALESCE(agrupamentocliente.codigo::VARCHAR,notafiscalservico.cnpjcpfcodigo) AS codigo
    , COALESCE(agrupamentocliente.descricao,pagadorfrete.razaosocial) AS descricao
    , 0 AS valor_cte_complementar
    , 0 AS valor_cte_normal
    , SUM(notafiscalservico.valortotalbruto) AS valor_nfse
    , 0 AS valor_meta

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


GROUP BY 
      COALESCE(agrupamentocliente.codigo::VARCHAR,notafiscalservico.cnpjcpfcodigo)
    , COALESCE(agrupamentocliente.descricao,pagadorfrete.razaosocial)


--###################################-- M E T A S --###################################--

UNION ALL

SELECT
      agrupamentocliente.codigo::VARCHAR as codigo
    , agrupamentocliente.descricao as descricao
    , 0 AS valor_cte_complementar
    , 0 AS valor_cte_normal
    , 0 AS valor_nfse
    , SUM(metafaturamento_agrupamentoclientedia.valor) AS valor_meta


FROM sulista.metafaturamento_agrupamentoclientedia

JOIN agrupamentocliente
ON agrupamentocliente.grupo = metafaturamento_agrupamentoclientedia.grupo
AND agrupamentocliente.empresa = metafaturamento_agrupamentoclientedia.empresa
AND agrupamentocliente.codigo = metafaturamento_agrupamentoclientedia.agrupamentocliente

WHERE
sulista.metafaturamento_agrupamentoclientedia.dt BETWEEN '2026-07-01' AND '2026-07-17'
AND sulista.metafaturamento_agrupamentoclientedia.tipo = 1


GROUP BY
  agrupamentocliente.descricao
, agrupamentocliente.codigo


UNION ALL
--###################################-- K  M  M --###################################--


SELECT

      agrupamentocliente.codigo::VARCHAR as codigo
    , agrupamentocliente.descricao as descricao
    , 0 AS valor_cte_complementar
    , COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'CT-e' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_cte_normal
    , COALESCE(CASE WHEN sulista.faturamentokmm.tipodocumento = 'NFS' THEN SUM(sulista.faturamentokmm.valor_cte) END, 0) AS valor_nfse
    , 0 AS valor_meta



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



GROUP BY

      agrupamentocliente.codigo
    , agrupamentocliente.descricao
    , sulista.faturamentokmm.tipodocumento

)
--###################################-- R E T O R N O --###################################--

SELECT
      faturamento.codigo
    , faturamento.descricao
    , SUM(faturamento.valor_cte_normal) AS valor_cte_normal
    , SUM(faturamento.valor_cte_complementar) AS valor_cte_complementar
    , SUM(faturamento.valor_nfse) AS valor_nfse
    , SUM(faturamento.valor_cte_normal) + SUM(faturamento.valor_cte_complementar) + SUM(faturamento.valor_nfse) AS valor_total
    , SUM(faturamento.valor_meta) AS valor_meta
--    , (SUM(faturamento.valor_cte_normal) + SUM(faturamento.valor_cte_complementar)) / SUM(faturamento.valor_meta) AS perc_atingido
    , TO_CHAR(COALESCE(NULLIF(SUM(faturamento.valor_cte_normal) + SUM(faturamento.valor_cte_complementar) + SUM(faturamento.valor_nfse), 0) 
      /
      NULLIF(SUM(faturamento.valor_meta), 0), 0) * 100, '990.99') AS perc_atingido
    
    FROM faturamento
GROUP BY 
      faturamento.codigo
    , faturamento.descricao
ORDER BY
      SUM(faturamento.valor_cte_normal) + SUM(faturamento.valor_cte_complementar) + SUM(faturamento.valor_nfse) DESC