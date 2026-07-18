"""SQL de custos (Suprimentos) — gerado de Querys Sulista/AVACORP/CUSTOS -
Custos Avacorp.sql; datas parametrizadas (%(de)s/%(ate)s). É a CTE `custos`
(4 blocos: abastecimento ext/int + OC com/sem NF). Use como prefixo + SELECT.
"""

CUSTOS_CTE = r"""
WITH custos AS(
SELECT 
CURRENT_TIMESTAMP AS data_atual
,'ABASTECIMENTO EXT' AS status_nf
,notafiscalsimples.numero AS numero_ordemcompra
,fnc_busca_gefu(notafiscalsimples.grupo, notafiscalsimples.empresa, notafiscalsimples.filial, notafiscalsimples.unidade,'F') AS filial_ordemcompra
,notafiscalsimples.dtemissao AS dtemissao_ordemcompra
,NULL::DATE AS dtprevisaoentrega
,'' AS valida_os
,NULL::INT AS num_os
,NULL AS tipo_os
,NULL::DATE AS dtemissao_os
,NULL AS objetivo_os
,veiculo.placa AS placa
,tipoveiculo.descricao AS tipo_veiculo
,veiculo.numerofrota AS frota
,NULL AS produto
,notafiscalsimples.quantidadetotalcombustivel AS qtde
,notafiscalsimples.valortotal AS valor
,fornecedor.razaosocial AS fornecedor
,fornecedor.latitude AS lati_fornecedor
,fornecedor.longitude AS long_fornecedor
,fornecedor.cidade as cidade_fornecedor
,fornecedor.uf AS uf_fornecedor
,NULL::INT AS num_nf
,NULL::DATE AS dt_entrada_nf
,NULL::DATE AS dt_emissao_nf
,NULL AS tipooperacao
,'411101'::INT AS reduzidodebito
,'Diesel Frota' AS conta_contabil
,'CV - COMBUSTÍVEL' AS agrupador
,NULL AS user_oc
,NULL AS user_aprova
,NULL AS aprovacao
,NULL AS observacao
,veiculo_marcador.diferencamarcador

FROM veiculo_marcador
    
JOIN veiculo
ON veiculo.placa = veiculo_marcador.veiculo

LEFT JOIN tipoveiculo
ON tipoveiculo.codigo = veiculo.tipoveiculo
    
JOIN notafiscalsimples
ON notafiscalsimples.grupo = veiculo_marcador.grupo
AND notafiscalsimples.empresa = veiculo_marcador.empresa
AND notafiscalsimples.filial = veiculo_marcador.filial
AND notafiscalsimples.unidade = veiculo_marcador.unidade
AND notafiscalsimples.diferenciadorsequencia = veiculo_marcador.diferenciadornumero
AND notafiscalsimples.sequencia = veiculo_marcador.numero
AND notafiscalsimples.tipodocumento = veiculo_marcador.tipodocumento

LEFT JOIN cadastro fornecedor
ON notafiscalsimples.fornecedor = fornecedor.codigo

WHERE 
veiculo_marcador.tipomarcador IN (1)
AND veiculo.tipofrota = 1
AND veiculo_marcador.tipodocumento IN (30)
AND veiculo_marcador.agrupador = 2
AND notafiscalsimples.dtemissao::date BETWEEN %(de)s::date AND %(ate)s::date

UNION ALL

SELECT 

CURRENT_TIMESTAMP AS data_atual
,'ABASTECIMENTO INT' AS status_nf
,notafiscalsimples.numero AS numero_ordemcompra
,fnc_busca_gefu(notafiscalsimples.grupo, notafiscalsimples.empresa, notafiscalsimples.filial, notafiscalsimples.unidade,'F') AS filial_ordemcompra
,notafiscalsimples.dtemissao AS dtemissao_ordemcompra
,NULL::DATE AS dtprevisaoentrega
,'' AS valida_os
,NULL::INT AS num_os
,NULL AS tipo_os
,NULL::DATE AS dtemissao_os
,NULL AS objetivo_os
,veiculo.placa AS placa
,tipoveiculo.descricao AS tipo_veiculo
,veiculo.numerofrota AS frota
,NULL AS produto
,notafiscalsimples.quantidadetotalcombustivel AS qtde
,notafiscalsimples.valortotal AS valor
,fornecedor.razaosocial AS fornecedor
,fornecedor.latitude AS lati_fornecedor
,fornecedor.longitude AS long_fornecedor
,fornecedor.cidade as cidade_fornecedor
,fornecedor.uf AS uf_fornecedor
,NULL::INT AS num_nf
,NULL::DATE AS dt_entrada_nf
,NULL::DATE AS dt_emissao_nf
,NULL AS tipooperacao
,'411101'::INT AS reduzidodebito
,'Diesel Frota' AS conta_contabil
,'CV - COMBUSTÍVEL' AS agrupador
,NULL AS user_oc
,NULL AS user_aprova
,NULL AS aprovacao
,NULL AS observacao
,veiculo_marcador.diferencamarcador

FROM veiculo_marcador
    
JOIN veiculo
ON veiculo.placa = veiculo_marcador.veiculo

LEFT JOIN tipoveiculo
ON tipoveiculo.codigo = veiculo.tipoveiculo
    
JOIN notafiscalsimples
ON notafiscalsimples.grupo = veiculo_marcador.grupo
AND notafiscalsimples.empresa = veiculo_marcador.empresa
AND notafiscalsimples.filial = veiculo_marcador.filial
AND notafiscalsimples.unidade = veiculo_marcador.unidade
AND notafiscalsimples.diferenciadorsequencia = veiculo_marcador.diferenciadornumero
AND notafiscalsimples.sequencia = veiculo_marcador.numero
AND notafiscalsimples.tipodocumento = veiculo_marcador.tipodocumento

LEFT JOIN cadastro fornecedor
ON notafiscalsimples.fornecedor = fornecedor.codigo

WHERE 
veiculo_marcador.tipomarcador IN (1)
AND veiculo.tipofrota = 1
AND veiculo_marcador.tipodocumento IN (31)
AND veiculo_marcador.agrupador = 2
AND notafiscalsimples.dtemissao::date BETWEEN %(de)s::date AND %(ate)s::date

UNION ALL

SELECT
CURRENT_TIMESTAMP AS data_atual
,'SEM NF' AS status_nf 
,ordemcompra.numero AS numero_ordemcompra
,fnc_busca_gefu(ordemcompra.grupo, ordemcompra.empresa, ordemcompra.filial, ordemcompra.unidade,'F') AS filial_ordemcompra
,CASE WHEN ordemcompra.dtemissao::DATE  = ordemcompra.dtprevisaoentrega THEN ordemcompra.dtemissao ELSE ordemcompra.dtprevisaoentrega END AS dtemisao_ordemcompra
,ordemcompra.dtprevisaoentrega AS dtprevisaoentrega
,CASE WHEN ordemservico.numero IS NULL THEN 'SEM OS' ELSE 'COM OS' END AS valida_os
,ordemservico.numero AS num_os
,CASE WHEN ordemservico.tipomanutencao = 1 THEN 'PREVENTIVA'
      WHEN ordemservico.tipomanutencao = 2 THEN 'CORRETIVA' 
      WHEN ordemservico.tipomanutencao = 3 THEN 'AMBAS' ELSE '' END AS tipo_os
,ordemservico.dtemissao AS dtemissao_os
,objetivoordemservico.descricao AS objetivo_os
,COALESCE(ordemcompra_item_rateiocentrocusto.veiculo,ordemservico.veiculo) AS placa
,COALESCE(tipo_veic_rateio.descricao, tipoveiculo.descricao) AS tipo_veiculo
,COALESCE(veic_rateio.numerofrota,veiculo.numerofrota) AS frota
,produto.descricao AS produto
,CASE WHEN ordemcompra_item_rateiocentrocusto.grupo IS NOT NULL THEN COALESCE(ordemcompra_item_rateiocentrocusto.quantidade, 0) ELSE ordemcompra_item.quantidade END AS qtde
,CASE WHEN ordemcompra_item_rateiocentrocusto.grupo IS NOT NULL THEN COALESCE(ordemcompra_item_rateiocentrocusto.valor, 0) ELSE ordemcompra_item.valortotal END AS valor

,UPPER(initcap(cadastro.razaosocial)) as fornecedor
,cadastro.latitude AS lati_fornecedor
,cadastro.longitude AS long_fornecedor
,cadastro.cidade as cidade_fornecedor
,cadastro.uf AS uf_fornecedor
,NULL AS num_nf
,NULL AS dt_entrada_nf
,NULL AS dt_emissao_nf
,tipooperacao.descricao AS tipooperacao
,ordemcompra_item.reduzidodebito
,UPPER(planoconta.descricao) AS conta_contabil
,agrupador.descricao AS agrupador
,usuario.loginusuario AS user_oc
,user_aprova.loginusuario AS user_aprova
,CASE WHEN ordemcompra.dtaprovador IS NULL THEN 'PENDENTE DE APROVAÇÃO' ELSE 'APROVADA' END AS aprovacao
,ordemcompra.observacao
,0 AS diferencamarcador
    
FROM ordemcompra_item

LEFT JOIN (SELECT DISTINCT
ordemcompra.numero
,ordemcompra.filial
,notafiscalentrada.numero AS NF

FROM ordemcompra

LEFT JOIN ordemcompra_item 
ON  ordemcompra.grupo = ordemcompra_item.grupo
AND ordemcompra.empresa = ordemcompra_item.empresa
AND ordemcompra.filial = ordemcompra_item.filial
AND ordemcompra.unidade = ordemcompra_item.unidade
AND ordemcompra.diferenciadornumero = ordemcompra_item.diferenciadornumero 
AND ordemcompra.numero = ordemcompra_item.numero

LEFT JOIN notafiscalentrada_item_ordemcomprarecebida
    ON  ordemcompra_item.grupo = notafiscalentrada_item_ordemcomprarecebida.grupo
    AND ordemcompra_item.empresa = notafiscalentrada_item_ordemcomprarecebida.empresa
    AND ordemcompra_item.filial = notafiscalentrada_item_ordemcomprarecebida.filialordemcompra
    AND ordemcompra_item.unidade = notafiscalentrada_item_ordemcomprarecebida.unidadeordemcompra
    AND ordemcompra_item.diferenciadornumero = notafiscalentrada_item_ordemcomprarecebida.diferenciadornumeroordemcompra
    AND ordemcompra_item.numero = notafiscalentrada_item_ordemcomprarecebida.numeroordemcompra
    AND ordemcompra_item.sequencia = notafiscalentrada_item_ordemcomprarecebida.sequenciaitemordemcompra

LEFT JOIN notafiscalentrada_item
    ON  notafiscalentrada_item.grupo = notafiscalentrada_item_ordemcomprarecebida.grupo
    AND notafiscalentrada_item.empresa = notafiscalentrada_item_ordemcomprarecebida.empresa
    AND notafiscalentrada_item.cnpjcpfcodigo = notafiscalentrada_item_ordemcomprarecebida.cnpjcpfcodigo
    AND notafiscalentrada_item.dtemissao = notafiscalentrada_item_ordemcomprarecebida.dtemissao
    AND notafiscalentrada_item.serie = notafiscalentrada_item_ordemcomprarecebida.serie
    AND notafiscalentrada_item.numero = notafiscalentrada_item_ordemcomprarecebida.numero
    AND notafiscalentrada_item.sequencia = notafiscalentrada_item_ordemcomprarecebida.sequencia

LEFT JOIN notafiscalentrada
    ON  notafiscalentrada_item.grupo = notafiscalentrada.grupo
    AND notafiscalentrada_item.empresa = notafiscalentrada.empresa
    AND notafiscalentrada_item.cnpjcpfcodigo = notafiscalentrada.cnpjcpfcodigo
    AND notafiscalentrada_item.dtemissao = notafiscalentrada.dtemissao
    AND notafiscalentrada_item.serie = notafiscalentrada.serie
    AND notafiscalentrada_item.numero = notafiscalentrada.numero

WHERE notafiscalentrada.numero IS NOT NULL) notafiscal ON ordemcompra_item.filial = notafiscal.filial AND ordemcompra_item.numero = notafiscal.numero

LEFT JOIN produto
    ON  produto.grupo = ordemcompra_item.grupo
    AND produto.empresa = ordemcompra_item.empresa
    AND produto.codigo = ordemcompra_item.produto

LEFT JOIN ordemcompra_item_rateiocentrocusto
    ON  ordemcompra_item.grupo = ordemcompra_item_rateiocentrocusto.grupo
    AND ordemcompra_item.empresa = ordemcompra_item_rateiocentrocusto.empresa
    AND ordemcompra_item.filial = ordemcompra_item_rateiocentrocusto.filial
    AND ordemcompra_item.unidade = ordemcompra_item_rateiocentrocusto.unidade
    AND ordemcompra_item.diferenciadornumero = ordemcompra_item_rateiocentrocusto.diferenciadornumero
    AND ordemcompra_item.numero = ordemcompra_item_rateiocentrocusto.numero
  AND ordemcompra_item.sequencia = ordemcompra_item_rateiocentrocusto.sequencia

LEFT JOIN ordemcompra
    ON  ordemcompra.grupo = ordemcompra_item.grupo
    AND ordemcompra.empresa = ordemcompra_item.empresa
    AND ordemcompra.filial = ordemcompra_item.filial
    AND ordemcompra.unidade = ordemcompra_item.unidade
    AND ordemcompra.diferenciadornumero = ordemcompra_item.diferenciadornumero
    AND ordemcompra.numero = ordemcompra_item.numero

JOIN tipooperacao
    ON  tipooperacao.grupo = ordemcompra_item.grupo
    AND tipooperacao.empresa = ordemcompra_item.empresa
    AND tipooperacao.codigo = ordemcompra_item.tipooperacao

LEFT JOIN usuario
ON ordemcompra.usuarioemissor = usuario.codigo

LEFT JOIN usuario user_aprova
ON ordemcompra.usuarioaprovador = user_aprova.codigo

LEFT JOIN cadastro
    ON  cadastro.codigo = ordemcompra.cnpjcpffornecedor

LEFT JOIN planoconta 
ON planoconta.reduzido = ordemcompra_item.reduzidodebito

LEFT JOIN sulista.agrupadorgerencial agrupador
ON agrupador.grupo = planoconta.grupo
AND agrupador.reduzido = planoconta.reduzido

LEFT JOIN ordemservico
ON ordemcompra.grupo = ordemservico.grupo
AND ordemcompra.empresa = ordemservico.empresa
AND ordemcompra.filial = ordemservico.filial
AND ordemcompra.unidade = ordemservico.unidade
AND ordemcompra.numerodocumento = ordemservico.numero

LEFT JOIN objetivoordemservico
  ON objetivoordemservico.grupo = ordemservico.grupo
  AND objetivoordemservico.empresa = ordemservico.empresa
  AND objetivoordemservico.codigo = ordemservico.objetivoordemservico

LEFT JOIN veiculo
ON veiculo.placa = ordemservico.veiculo

LEFT JOIN tipoveiculo
ON tipoveiculo.codigo = veiculo.tipoveiculo

LEFT JOIN veiculo veic_rateio
ON ordemcompra_item_rateiocentrocusto.veiculo = veic_rateio.placa

LEFT JOIN tipoveiculo tipo_veic_rateio
ON tipo_veic_rateio.codigo = veic_rateio.tipoveiculo

WHERE COALESCE(ordemcompra_item.dtsuspensao,ordemcompra.dtsuspensao) IS NULL
AND notafiscal.numero IS NULL
AND ordemcompra.dtemissao::date BETWEEN %(de)s::date AND %(ate)s::date

UNION ALL

SELECT
CURRENT_TIMESTAMP AS data_atual
,'COM NF' AS status_nf
,ordemcompra.numero AS numero_ordemcompra
,fnc_busca_gefu(ordemcompra.grupo, ordemcompra.empresa, ordemcompra.filial, ordemcompra.unidade,'F') AS filial_ordemcompra
,ordemcompra.dtemissao AS dtemissao_ordemcompra
,ordemcompra.dtprevisaoentrega AS dtprevisaoentrega
,CASE WHEN ordemservico.numero IS NULL THEN 'SEM OS' ELSE 'COM OS' END AS valida_os
,ordemservico.numero AS num_os
,CASE WHEN ordemservico.tipomanutencao = 1 THEN 'PREVENTIVA'
      WHEN ordemservico.tipomanutencao = 2 THEN 'CORRETIVA' 
      WHEN ordemservico.tipomanutencao = 3 THEN 'AMBAS' ELSE '' END AS tipo_os
,ordemservico.dtemissao AS dtemissao_os
,objetivoordemservico.descricao AS objetivo_os
,COALESCE(ordemcompra_item_rateiocentrocusto.veiculo,ordemservico.veiculo) AS placa
,COALESCE(tipo_veic_rateio.descricao, tipoveiculo.descricao) AS tipo_veiculo
,COALESCE(veic_rateio.numerofrota,veiculo.numerofrota) AS frota
,produto.descricao AS produto

,CASE WHEN ordemcompra_item_rateiocentrocusto.grupo IS NOT NULL THEN COALESCE(ordemcompra_item_rateiocentrocusto.quantidade, 0) ELSE ordemcompra_item.quantidade END AS qtde
,CASE WHEN ordemcompra_item_rateiocentrocusto.grupo IS NOT NULL THEN COALESCE(ordemcompra_item_rateiocentrocusto.valor, 0) ELSE notafiscalentrada_item.valortotal END AS valor

,UPPER(initcap(cadastro.razaosocial)) as fornecedor
,cadastro.latitude AS lati_fornecedor
,cadastro.longitude AS long_fornecedor
,cadastro.cidade as cidade_fornecedor
,cadastro.uf AS uf_fornecedor
,notafiscalentrada.numero AS num_nf
,notafiscalentrada.dtentrada AS dt_entrada_nf
,notafiscalentrada.dtemissao AS dt_emissao_nf
,tipooperacao.descricao AS tipooperacao
,ordemcompra_item.reduzidodebito
,UPPER(planoconta.descricao) AS conta_contabil
,agrupador.descricao AS agrupador
,usuario.loginusuario AS user_oc
,user_aprova.loginusuario AS user_aprova
,CASE WHEN ordemcompra.dtaprovador IS NULL THEN 'PENDENTE DE APROVAÇÃO' ELSE 'APROVADA' END AS aprovacao
,ordemcompra.observacao
,0 AS diferencamarcador
    
FROM notafiscalentrada_item_ordemcomprarecebida

JOIN notafiscalentrada_item
    ON  notafiscalentrada_item.grupo = notafiscalentrada_item_ordemcomprarecebida.grupo
    AND notafiscalentrada_item.empresa = notafiscalentrada_item_ordemcomprarecebida.empresa
    AND notafiscalentrada_item.cnpjcpfcodigo = notafiscalentrada_item_ordemcomprarecebida.cnpjcpfcodigo
    AND notafiscalentrada_item.dtemissao = notafiscalentrada_item_ordemcomprarecebida.dtemissao
    AND notafiscalentrada_item.serie = notafiscalentrada_item_ordemcomprarecebida.serie
    AND notafiscalentrada_item.numero = notafiscalentrada_item_ordemcomprarecebida.numero
    AND notafiscalentrada_item.sequencia = notafiscalentrada_item_ordemcomprarecebida.sequencia

JOIN notafiscalentrada
    ON  notafiscalentrada_item.grupo = notafiscalentrada.grupo
    AND notafiscalentrada_item.empresa = notafiscalentrada.empresa
    AND notafiscalentrada_item.cnpjcpfcodigo = notafiscalentrada.cnpjcpfcodigo
    AND notafiscalentrada_item.dtemissao = notafiscalentrada.dtemissao
    AND notafiscalentrada_item.serie = notafiscalentrada.serie
    AND notafiscalentrada_item.numero = notafiscalentrada.numero

JOIN produto
    ON  produto.grupo = notafiscalentrada_item.grupo
    AND produto.empresa = notafiscalentrada_item.empresa
    AND produto.codigo = notafiscalentrada_item.produto

JOIN cadastro
    ON  cadastro.codigo = notafiscalentrada.cnpjcpfcodigo

JOIN ordemcompra_item
    ON  ordemcompra_item.grupo = notafiscalentrada_item_ordemcomprarecebida.grupo
    AND ordemcompra_item.empresa = notafiscalentrada_item_ordemcomprarecebida.empresa
    AND ordemcompra_item.filial = notafiscalentrada_item_ordemcomprarecebida.filialordemcompra
    AND ordemcompra_item.unidade = notafiscalentrada_item_ordemcomprarecebida.unidadeordemcompra
    AND ordemcompra_item.diferenciadornumero = notafiscalentrada_item_ordemcomprarecebida.diferenciadornumeroordemcompra
    AND ordemcompra_item.numero = notafiscalentrada_item_ordemcomprarecebida.numeroordemcompra
    AND ordemcompra_item.sequencia = notafiscalentrada_item_ordemcomprarecebida.sequenciaitemordemcompra

LEFT JOIN ordemcompra_item_rateiocentrocusto
    ON  ordemcompra_item.grupo = ordemcompra_item_rateiocentrocusto.grupo
    AND ordemcompra_item.empresa = ordemcompra_item_rateiocentrocusto.empresa
    AND ordemcompra_item.filial = ordemcompra_item_rateiocentrocusto.filial
    AND ordemcompra_item.unidade = ordemcompra_item_rateiocentrocusto.unidade
    AND ordemcompra_item.diferenciadornumero = ordemcompra_item_rateiocentrocusto.diferenciadornumero
    AND ordemcompra_item.numero = ordemcompra_item_rateiocentrocusto.numero
  AND ordemcompra_item.sequencia = ordemcompra_item_rateiocentrocusto.sequencia
    
JOIN ordemcompra
    ON  ordemcompra.grupo = ordemcompra_item.grupo
    AND ordemcompra.empresa = ordemcompra_item.empresa
    AND ordemcompra.filial = ordemcompra_item.filial
    AND ordemcompra.unidade = ordemcompra_item.unidade
    AND ordemcompra.diferenciadornumero = ordemcompra_item.diferenciadornumero
    AND ordemcompra.numero = ordemcompra_item.numero

JOIN tipooperacao
    ON  tipooperacao.grupo = ordemcompra_item.grupo
    AND tipooperacao.empresa = ordemcompra_item.empresa
    AND tipooperacao.codigo = ordemcompra_item.tipooperacao

LEFT JOIN usuario
ON ordemcompra.usuarioemissor = usuario.codigo

LEFT JOIN usuario user_aprova
ON ordemcompra.usuarioaprovador = user_aprova.codigo

JOIN planoconta 
ON planoconta.reduzido = ordemcompra_item.reduzidodebito

LEFT JOIN sulista.agrupadorgerencial agrupador
ON agrupador.grupo = planoconta.grupo
AND agrupador.reduzido = planoconta.reduzido

LEFT JOIN ordemservico
ON ordemcompra.grupo = ordemservico.grupo
AND ordemcompra.empresa = ordemservico.empresa
AND ordemcompra.filial = ordemservico.filial
AND ordemcompra.unidade = ordemservico.unidade
AND ordemcompra.numerodocumento = ordemservico.numero

LEFT JOIN objetivoordemservico
  ON objetivoordemservico.grupo = ordemservico.grupo
  AND objetivoordemservico.empresa = ordemservico.empresa
  AND objetivoordemservico.codigo = ordemservico.objetivoordemservico

LEFT JOIN veiculo
ON veiculo.placa = ordemservico.veiculo

LEFT JOIN tipoveiculo
ON tipoveiculo.codigo = veiculo.tipoveiculo

LEFT JOIN veiculo veic_rateio
ON ordemcompra_item_rateiocentrocusto.veiculo = veic_rateio.placa

LEFT JOIN tipoveiculo tipo_veic_rateio
ON tipo_veic_rateio.codigo = veic_rateio.tipoveiculo

WHERE  
notafiscalentrada_item_ordemcomprarecebida.grupo = 1
AND notafiscalentrada_item_ordemcomprarecebida.empresa = 1
AND notafiscalentrada.dtentrada::date BETWEEN %(de)s::date AND %(ate)s::date)
"""
