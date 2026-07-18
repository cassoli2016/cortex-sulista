-- MILRUN AGENDADO PARA HOJE

SELECT

  coleta.grupo
, coleta.empresa
, CASE WHEN coleta.filial = 2 THEN 'SBC'
       WHEN coleta.filial = 22 THEN 'SJP'
       WHEN coleta.filial = 23 THEN 'SBC CD'
       WHEN coleta.filial = 19 THEN 'JOI'
       WHEN coleta.filial = 21 THEN 'POA'
       WHEN coleta.filial = 20 THEN 'CRU'
       WHEN coleta.filial = 1 THEN 'MTZ'
       WHEN coleta.filial = 15 THEN 'PA'
       WHEN coleta.filial = 7 THEN 'RES' 
       END AS filialapelido
, coleta.filial
, coleta.unidade
, coleta.serie
, coleta.diferenciadornumero
, coleta.numero AS num_coleta --
, veiculo.placa --
, veiculo.numerofrota --
, coleta_cliente.dtagendamentocoleta
, coleta_cliente.dtagendamentoentrega
, remetente.nomefantasia AS remetente --
, destinatario.nomefantasia AS destinatario --
, agrupamentocliente.codigo
, agrupamentocliente.descricao AS cliente
, coleta_cliente.sequencia
, '' AS leg_mapa
, coleta_cliente.hra_chegada::TIMESTAMP WITH TIME ZONE
, coleta_cliente.hra_saida::TIMESTAMP WITH TIME ZONE
, coleta_cliente.hra_saida::TIMESTAMP WITH TIME ZONE - coleta_cliente.hra_chegada::TIMESTAMP WITH TIME ZONE AS tempo_coleta

, CASE WHEN coleta_cliente.frustrada = 1 THEN '?? FRUSTRADA'
       WHEN coleta_cliente.coletada = 1 THEN '?? COLETADA'
       WHEN coleta_cliente.embalagem = 1 THEN '?? EMBALAGEM'
       ELSE '?? COLETA PROGRAMADA'
       END AS situacao
, tipofrete.descricao AS operacao
, CASE WHEN COALESCE(coleta_cliente.hra_chegada::TIMESTAMP WITH TIME ZONE, CURRENT_TIMESTAMP) <= coleta_cliente.dtagendamentocoleta THEN '?? NO PRAZO'
       ELSE '?? ATRASADO'
       END AS pontualidade_coleta
, ocorrencia_cliente.descricao
,'' as leg_notasfiscais
, veiculo_posicao.latituderastreadora
, veiculo_posicao.longituderastreadora


FROM coleta

LEFT JOIN veiculo
ON coleta.veiculo = veiculo.placa

LEFT JOIN coleta_cliente
ON coleta.grupo = coleta_cliente.grupo
AND coleta.empresa = coleta_cliente.empresa 
AND coleta.filial = coleta_cliente.filial 
AND coleta.unidade = coleta_cliente.unidade 
AND coleta.diferenciadornumero = coleta_cliente.diferenciadornumero 
AND coleta.serie = coleta_cliente.serie 
AND coleta.numero = coleta_cliente.numero

LEFT JOIN cadastro remetente
ON coleta_cliente.remetente = remetente.codigo

LEFT JOIN cadastro destinatario
ON coleta_cliente.destinatario = destinatario.codigo


LEFT JOIN agrupamentocliente_cnpjcpfcodigo
ON agrupamentocliente_cnpjcpfcodigo.grupo = coleta.grupo
AND agrupamentocliente_cnpjcpfcodigo.empresa = coleta.empresa
AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = coleta.cnpjcpfcodigopagadorfrete
AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1

LEFT JOIN agrupamentocliente
ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo


LEFT JOIN tipofrete
ON coleta.grupo = tipofrete.grupo
AND coleta.empresa = tipofrete.empresa
AND coleta.tipofrete = tipofrete.codigo

LEFT JOIN veiculo_posicao
    ON  veiculo_posicao.veiculo = coleta.veiculo
    AND veiculo_posicao.ultimaposicao = 1
    
LEFT JOIN ocorrencia_motivo ocorrencia_cliente -- OCORRENCIAS CLIENTE (USADO PARA MR)
ON ocorrencia_cliente.grupo = coleta_cliente.grupo
AND ocorrencia_cliente.empresa = coleta_cliente.empresa
AND ocorrencia_cliente.ocorrencia = 469
AND ocorrencia_cliente.codigo = coleta_cliente.motivoatraso

WHERE

    coleta_cliente.dtagendamentocoleta::DATE BETWEEN CURRENT_DATE AND CURRENT_DATE
AND coleta.destinatariodefinido = 1
AND coleta.sequencia > 1
AND coleta.dtcancelamento IS NULL


ORDER BY
  
  coleta.filial
, coleta.numero
, coleta_cliente.dtagendamentocoleta