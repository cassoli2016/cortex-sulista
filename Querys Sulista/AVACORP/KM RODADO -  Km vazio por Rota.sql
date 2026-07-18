WITH kmrodado AS
(

SELECT --DISTINCT
  programacaoembarque.numero || ' - ' || programacaoembarque.diferenciadornumero AS prog
, COALESCE(clientepagador.descricao, clientedestinovazio.descricao, clientedestinotrajeto.descricao, 
           clienteorigemvazio.descricao, clienteorigemtrajeto.descricao) AS cliente -- OK
, trajeto.codigo || ' - ' || trajeto.descricao AS trajeto
, programacaoembarque.cidadeorigem || ' > ' || programacaoembarque.cidadedestino AS rota
, programacaoembarque.kmfretecompra AS km_total_rodado
, CASE WHEN programacaoembarque.tipo = 2 THEN programacaoembarque.kmfretecompra 
       END km_carregado 
, CASE WHEN programacaoembarque.tipo = 3 THEN programacaoembarque.kmfretecompra 
       END km_vazio

, CASE WHEN programacaoembarque.tipo = 2 AND (cavalo.utilizacaoveiculo = 'LOC' OR cavalo.utilizacaoveiculo = 'TRA') THEN programacaoembarque.kmfretecompra 
       END km_carregado_frota
, CASE WHEN programacaoembarque.tipo = 2 AND (cavalo.utilizacaoveiculo = 'AGR') THEN programacaoembarque.kmfretecompra 
       END km_carregado_agregado
, CASE WHEN programacaoembarque.tipo = 2 AND (cavalo.utilizacaoveiculo = 'TER') THEN programacaoembarque.kmfretecompra 
       END km_carregado_terceiro

, CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'LOC' OR cavalo.utilizacaoveiculo = 'TRA') THEN programacaoembarque.kmfretecompra 
       END km_vazio_frota
, CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'AGR') THEN programacaoembarque.kmfretecompra 
       END km_vazio_agregado 
, CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'TER') THEN programacaoembarque.kmfretecompra 
       END km_vazio_terceiro

, programacaoembarque.numero AS numeroviagem

,
CASE WHEN trajeto.extensao <= 300 THEN 1
     WHEN trajeto.extensao > 300 THEN 2
     END AS filtro_300



FROM programacaoembarque

LEFT JOIN trajeto
ON trajeto.grupo = programacaoembarque.grupo
AND trajeto.empresa = programacaoembarque.empresa
AND trajeto.codigo = programacaoembarque.trajeto

LEFT JOIN coleta
ON coleta.grupo = programacaoembarque.grupo
AND coleta.empresa = programacaoembarque.empresa
AND coleta.filial = programacaoembarque.filialdocumentoorigem
AND coleta.unidade = programacaoembarque.unidadedocumentoorigem
AND coleta.diferenciadornumero = programacaoembarque.diferenciadornumerodocumentoorigem
AND coleta.numero = programacaoembarque.numerodocumentoorigem

LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_clientepagador
ON agrupamentocliente_cnpjcpfcodigo_clientepagador.cnpjcpfcodigo = coleta.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente clientepagador
ON clientepagador.codigo = agrupamentocliente_cnpjcpfcodigo_clientepagador.codigo

LEFT JOIN veiculo cavalo
ON cavalo.placa = programacaoembarque.veiculo
LEFT JOIN utilizacaoveiculo
ON utilizacaoveiculo.codigo = cavalo.utilizacaoveiculo

-- CLIENTE ORIGEM VAZIO
LEFT JOIN cadastro origemvazio
ON origemvazio.codigo = programacaoembarque.cadastroorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_origemvazio
ON agrupamentocliente_cnpjcpfcodigo_origemvazio.cnpjcpfcodigo = origemvazio.codigo
LEFT JOIN agrupamentocliente clienteorigemvazio
ON clienteorigemvazio.codigo = agrupamentocliente_cnpjcpfcodigo_origemvazio.codigo

-- CLIENTE DESTINO VAZIO
LEFT JOIN cadastro destinovazio
ON destinovazio.codigo = programacaoembarque.cadastrodestino
LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_destinovazio
ON agrupamentocliente_cnpjcpfcodigo_destinovazio.cnpjcpfcodigo = destinovazio.codigo
LEFT JOIN agrupamentocliente clientedestinovazio
ON clientedestinovazio.codigo = agrupamentocliente_cnpjcpfcodigo_destinovazio.codigo

-- ORIGEM TRAJETO
LEFT JOIN cadastro origemtrajeto
ON origemtrajeto.codigo = trajeto.cnpjcpfcodigoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_origemtrajeto
ON agrupamentocliente_cnpjcpfcodigo_origemtrajeto.cnpjcpfcodigo = origemtrajeto.codigo
LEFT JOIN agrupamentocliente clienteorigemtrajeto
ON clienteorigemtrajeto.codigo = agrupamentocliente_cnpjcpfcodigo_origemtrajeto.codigo

-- DESTINO TRAJETO
LEFT JOIN cadastro destinotrajeto
ON destinotrajeto.codigo = trajeto.cnpjcpfcodigodestino
LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_destinotrajeto
ON agrupamentocliente_cnpjcpfcodigo_destinotrajeto.cnpjcpfcodigo = destinotrajeto.codigo
LEFT JOIN agrupamentocliente clientedestinotrajeto
ON clientedestinotrajeto.codigo = agrupamentocliente_cnpjcpfcodigo_destinotrajeto.codigo

WHERE 
programacaoembarque.dtcancelamento IS NULL 
AND programacaoembarque.semaforo = 1
AND programacaoembarque.numero < 1000000
AND programacaoembarque.dtemissao::date BETWEEN '2023-05-01' AND CURRENT_DATE

)

SELECT 
  kmrodado.rota
, COUNT(DISTINCT(kmrodado.numeroviagem)) AS nr_viagens
, COALESCE(SUM(kmrodado.km_carregado), 0) AS kmcarregado
, COALESCE(SUM(kmrodado.km_vazio), 0) AS kmvazio
, COALESCE(SUM(kmrodado.km_carregado), 0) + COALESCE(SUM(kmrodado.km_vazio), 0) AS kmtotal


FROM 
  kmrodado 

LEFT JOIN agrupamentocliente
ON agrupamentocliente.descricao = kmrodado.cliente

  WHERE 
  kmrodado.km_vazio > 0



GROUP BY 
  kmrodado.rota

ORDER BY
  COALESCE(SUM(kmrodado.km_vazio), 0) DESC