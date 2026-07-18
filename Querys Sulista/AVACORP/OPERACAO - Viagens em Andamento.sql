WITH ocorrencias AS (

SELECT

  coleta_ocorrencia.grupo
, coleta_ocorrencia.empresa
, coleta_ocorrencia.filial
, coleta_ocorrencia.unidade
, coleta_ocorrencia.diferenciadornumero
, coleta_ocorrencia.serie
, coleta_ocorrencia.numero
, coleta_ocorrencia.ocorrencia
, ocorrencia.descricao
, coleta_ocorrencia.dtocorrencia

, ROW_NUMBER() OVER (
    PARTITION BY 
        coleta_ocorrencia.grupo,
        coleta_ocorrencia.empresa,
        coleta_ocorrencia.filial,
        coleta_ocorrencia.unidade,
        coleta_ocorrencia.serie,
        coleta_ocorrencia.diferenciadornumero,
        coleta_ocorrencia.numero
    ORDER BY coleta_ocorrencia.dtocorrencia DESC
) AS rn_ocorrencia

FROM
-- 0800-642-2002 unimed
coleta_ocorrencia

LEFT JOIN ocorrencia
ON ocorrencia.codigo = coleta_ocorrencia.ocorrencia

WHERE
coleta_ocorrencia.ocorrencia IN (

394, -- CHEGADA PARA CARREGAMENTO (SAC)
395, -- SAIDA DO CARREGAMENTO (SAC)
396, -- CHEGADA PARA DESCARGA (SAC)
397, -- FIM DE DESCARGA (SAC)
398, -- AGUARDANDO CARREGAMENTO (SAC)
399, -- AGUARDANDO DESCARGA (SAC)
400, -- EM VIAGEM (SAC)
401, -- VIAGEM FINALIZADA (SAC)
425, -- FALHA NO MONITORAMENTO - COLETA (SAC) -- nova 
426, -- PARADA PARA ABASTECIMENTO - COLETA (SAC)
427, -- PARADA OBRIGATÓRIA - COLETA (SAC)
428, -- INÍCIO VIAGEM TARDIA - COLETA (SAC)
429, -- PERNOITE - COLETA (SAC)
430, -- PROBLEMAS MECANICOS - COLETA (SAC)
431, -- TRANSIT TIME - COLETA (SAC)
432, -- TRANSITO – ACIDENTE / RODOVIAS BLOQUEADAS - COLETA (SAC)
433, -- TRANSITO - OBRAS NA PISTA - COLETA (SAC)
434, -- TROCA DE MOTORISTA / VEICULO - COLETA (SAC)
435, -- DESCARGA ANTERIOR - COLETA (SAC)
436, -- PROBLEMAS OPERACIONAIS - COLETA (SAC)
437, -- SEM JANELA COLETA (SAC)
438, -- SINISTRO - COLETA (SAC)
439, -- ERRO DE PROGRAMAÇÃO - COLETA (SAC) -- nova
440, -- FREE TIME EXCEDIDO - COLETA (SAC)
441, -- FALHA NO MONITORAMENTO - ENTREGA (SAC)
442, -- PARADA PARA ABASTECIMENTO - ENTREGA (SAC)
443, -- PARADA OBRIGATORIA - ENTREGA (SAC)
444, -- INICIO VIAGEM TARDIA - ENTREGA (SAC)
445, -- PERNOITE - ENTREGA (SAC)
446, -- PROBLEMAS MECANICOS - ENTREGA (SAC)
447, -- TRANSIT TIME - ENTREGA (SAC)
448, -- TRANSITO – ACIDENTE / RODOVIAS BLOQUEADAS - ENTREGA (SAC)
449, -- TRANSITO - OBRAS NA PISTA - ENTREGA (SAC)
450, -- TROCA DE MOTORISTA / VEICULO - ENTREGA (SAC)
451, -- DESCARGA ANTERIOR - ENTREGA (SAC)
452, -- PROBLEMAS OPERACIONAIS - ENTREGA (SAC)
453, -- SEM JANELA ENTREGA (SAC)
454, -- SINISTRO - ENTREGA (SAC)
455, --ERRO DE PROGRAMAÇÃO - ENTREGA (SAC) -- nova
456  -- FREE TIME EXCEDIDO - ENTREGA (SAC)
)

), rastreamento AS (

SELECT 
 coleta.grupo
, coleta.empresa
, coleta.filial
, coleta.unidade
, coleta.diferenciadornumero
, coleta.serie
, coleta.numero AS num_coleta -- OK

, COALESCE(agrupamentocliente.descricao, 'SEM CLIENTE') AS grupo_cliente -- OK
, COALESCE(remetente.nomefantasia, 'CONSOLIDADA') AS remetente -- OK

, COALESCE(destinatario.nomefantasia, 'CONSOLIDADA') AS destinatario -- OK
--, tipofrete.descricao AS operacao


, CASE WHEN tipofrete.descricao ILIKE '%spot%' OR tipofrete.descricao ILIKE '%extra%' THEN tipofrete.descricao::TEXT || ' ' || '??'
       ELSE tipofrete.descricao
       END AS operacao

, TO_CHAR(coleta.dtprevisaochegadaviagem, 'DD/MM HH24:MI') AS janela_entrega -- OK
, STRING_AGG(conhecimento_notafiscal.numeronotafiscal::text, '/ ') AS nfe -- OK


, CASE WHEN sulista.whatsappcliente.filial IS NULL AND sulista.whatsappcliente.nrcoleta IS NULL THEN 1
       ELSE 2
       END AS validaenvio
, sulista.whatsappcliente.usuarioinclusao AS user_monitoramento
,CASE 
  WHEN COALESCE(rotograma.kmpercursorealizado,0) > COALESCE(rotograma.extensao,0) THEN
      0
  ELSE
      ((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)))::NUMERIC(15,2)
END AS rotograma_km_restante

, rotograma.percpercursorealizado::TEXT AS percpercursorealizado


, TO_CHAR(CAST((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54 || ' HOURS' AS INTERVAL),
    CASE WHEN EXTRACT(HOUR FROM CAST((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54 || ' HOURS' AS INTERVAL)) > 0
    THEN TO_CHAR(CAST((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54 || ' HOURS' AS INTERVAL), 'HH24:MI') || 'H'
    ELSE '00:' || TO_CHAR(CAST((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54 || ' HOURS' AS INTERVAL), 'MI') || 'M'
    END) AS temporestante_numerico -- OK


, TO_CHAR(CURRENT_TIMESTAMP + (((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54) || ' HOURS')::INTERVAL, 'DD/MM HH24:MI') AS previsao_chegada -- OK
, CASE WHEN CURRENT_TIMESTAMP + (((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54) || ' HOURS')::INTERVAL <= coleta.dtprevisaochegadaviagem 
       THEN '?? No Prazo'
       WHEN CURRENT_TIMESTAMP + (((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54) || ' HOURS')::INTERVAL <= coleta.dtprevisaochegadaviagem + INTERVAL '1 hour' 
       THEN '?? Possível Atraso'
       ELSE '?? Atrasado' 
       END AS status_calculado_new -- OK

, CASE WHEN CURRENT_TIMESTAMP + (((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54) || ' HOURS')::INTERVAL <= coleta.dtprevisaochegadaviagem 
       THEN 3
       WHEN CURRENT_TIMESTAMP + (((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)) / 54) || ' HOURS')::INTERVAL <= coleta.dtprevisaochegadaviagem + INTERVAL '1 hour' 
       THEN 2
       ELSE 1 
       END AS ordem_status -- OK

, veiculo.placa AS placa_cavalo -- OK
, COALESCE(veiculo.numerofrota, veiculo.placa) AS veiculo_numerofrota -- OK
, carreta1.placa AS carreta1

, CASE 
    WHEN sulista.status_transito.situacao_transito = 'Livre' THEN '?? Livre'
    WHEN sulista.status_transito.situacao_transito = 'Moderado' THEN '?? Moderado'
    WHEN sulista.status_transito.situacao_transito = 'Pesado' THEN '?? Pesado'
    WHEN sulista.status_transito.situacao_transito = 'Muito congestionado' THEN '? Muito congestionado'
    WHEN sulista.status_transito.situacao_transito = 'Congestionamento severo' THEN '?? Congestionamento severo'
    ELSE 'Aguardando Atualização'
    END AS status_transito


, CASE
    WHEN coleta.remetentedefinido = 2 AND coleta.destinatariodefinido = 1 THEN -- MILKRUN
        COALESCE(
            REPLACE(STRING_AGG(DISTINCT ocorrencia_motivo.descricao::text, ' / '), '(SAC)', ''),
            REPLACE(ocorrencias.descricao, '(SAC)', '')
        )
    ELSE REPLACE(ocorrencias.descricao, '(SAC)', '') -- CARGA DIRETA
END AS motivoatraso  -- utilizar este para visualmente retirar o (SAC) da ocorrencia

FROM coleta

LEFT JOIN coleta_composicao 
ON coleta_composicao.grupo = coleta.grupo
AND coleta_composicao.empresa = coleta.empresa
AND coleta_composicao.filial = coleta.filial
AND coleta_composicao.unidade = coleta.unidade 
AND coleta_composicao.diferenciadornumero = coleta.diferenciadornumero
AND coleta_composicao.serie = coleta.serie
AND coleta_composicao.numero = coleta.numero
AND coleta_composicao.tipodocumento in (6,13)

LEFT JOIN conhecimento_composicao
 ON conhecimento_composicao.tipodocumento = 27
AND conhecimento_composicao.grupo= coleta.grupo
AND conhecimento_composicao.empresa = coleta.empresa
AND conhecimento_composicao.filialdocumento = coleta.filial
AND conhecimento_composicao.unidadedocumento = coleta.unidade
AND conhecimento_composicao.diferenciadornumerodocumento = coleta.diferenciadornumero
AND conhecimento_composicao.seriedocumento = coleta.serie
AND conhecimento_composicao.numerodocumento = coleta.numero

LEFT JOIN conhecimento
ON conhecimento.grupo = COALESCE(coleta_composicao.grupo,conhecimento_composicao.grupo)
AND conhecimento.empresa = COALESCE(coleta_composicao.empresa,conhecimento_composicao.empresa)
AND conhecimento.filial = COALESCE(coleta_composicao.filialdocumento,conhecimento_composicao.filial)
AND conhecimento.unidade = COALESCE(coleta_composicao.unidadedocumento,conhecimento_composicao.unidade)
AND conhecimento.diferenciadornumero = COALESCE(coleta_composicao.diferenciadornumerodocumento,conhecimento_composicao.diferenciadornumero)
AND conhecimento.serie = COALESCE(coleta_composicao.seriedocumento,conhecimento_composicao.serie)
AND conhecimento.numero = COALESCE(coleta_composicao.numerodocumento,conhecimento_composicao.numero)

left join manifesto_composicao
on manifesto_composicao.grupo = conhecimento.grupo
and manifesto_composicao.empresa =conhecimento.empresa
and manifesto_composicao.filialdocumento = conhecimento.filial
and manifesto_composicao.unidadedocumento = conhecimento.unidade
and manifesto_composicao.diferenciadornumerodocumento = conhecimento.diferenciadornumero
and case when conhecimento.serie is not null then manifesto_composicao.seriedocumento = conhecimento.serie 
    else TRUE end
and manifesto_composicao.numerodocumento = conhecimento.numero
and manifesto_composicao.tipodocumento = conhecimento.tipodocumento

left join manifesto
on manifesto.grupo = manifesto_composicao.grupo
and manifesto.empresa = manifesto_composicao.empresa 
and manifesto.filial = manifesto_composicao.filial 
and manifesto.unidade = manifesto_composicao.unidade 
and manifesto.diferenciadornumero = manifesto_composicao.diferenciadornumero 
and manifesto.serie = manifesto_composicao.serie 
and manifesto.numero = manifesto_composicao.numero 

left join transporte_manifesto
on transporte_manifesto.grupo = manifesto_composicao.grupo 
and transporte_manifesto.empresa = manifesto_composicao.empresa 
and transporte_manifesto.filialdocumento = manifesto_composicao.filial
and transporte_manifesto.unidadedocumento = manifesto_composicao.unidade 
and transporte_manifesto.diferenciadornumerodocumento = manifesto_composicao.diferenciadornumero 
and transporte_manifesto.seriedocumento  = manifesto_composicao.serie
and transporte_manifesto.numerodocumento = manifesto_composicao.numero

left join transporte
on transporte.grupo = transporte_manifesto.grupo 
and transporte.empresa = transporte_manifesto.empresa 
and transporte.diferenciadornumero = transporte_manifesto.diferenciadornumero 
and transporte.numero = transporte_manifesto.numero

LEFT JOIN trajeto
ON trajeto.grupo = transporte.grupo
AND trajeto.empresa = transporte.empresa
AND trajeto.codigo = transporte.trajeto

JOIN cadastro motorista
ON motorista.codigo = coleta.motorista

LEFT JOIN veiculo
ON veiculo.placa = transporte.veiculo

LEFT JOIN veiculo carreta1
ON carreta1.placa = transporte.carreta1

LEFT JOIN conhecimento_notafiscal
ON conhecimento_notafiscal.grupo = conhecimento.grupo
AND conhecimento_notafiscal.empresa = conhecimento.empresa
AND conhecimento_notafiscal.filial = conhecimento.filial
AND conhecimento_notafiscal.unidade = conhecimento.unidade
AND conhecimento_notafiscal.numero = conhecimento.numero
AND conhecimento_notafiscal.diferenciadornumero = conhecimento.diferenciadornumero
AND conhecimento_notafiscal.serie = conhecimento.serie

LEFT JOIN agrupamentocliente_cnpjcpfcodigo
ON agrupamentocliente_cnpjcpfcodigo.grupo = coleta.grupo
AND agrupamentocliente_cnpjcpfcodigo.empresa = coleta.empresa
AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = coleta.cnpjcpfcodigopagadorfrete
AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1

LEFT JOIN agrupamentocliente
ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo

LEFT JOIN cadastro remetente
ON remetente.codigo = coleta.remetente
    
LEFT JOIN cadastro destinatario
ON destinatario.codigo = coleta.destinatario

LEFT JOIN rotograma_documento 
ON rotograma_documento.grupo = transporte.grupo
AND rotograma_documento.empresa = transporte.empresa
AND rotograma_documento.veiculo = transporte.veiculo
AND rotograma_documento.numerodocumento = transporte.numero

LEFT JOIN rotograma
ON rotograma.grupo = rotograma_documento.grupo 
AND rotograma.empresa = rotograma_documento.empresa 
AND rotograma.veiculo = rotograma_documento.veiculo 
AND rotograma.sequencia = rotograma_documento.sequencia
AND rotograma_documento.tipodocumento = 201

LEFT JOIN sulista.whatsappcliente
ON sulista.whatsappcliente.grupo = coleta.grupo
AND sulista.whatsappcliente.empresa = coleta.empresa
AND sulista.whatsappcliente.filial = coleta.filial
AND sulista.whatsappcliente.unidade = coleta.unidade
AND sulista.whatsappcliente.nrcoleta = coleta.numero

LEFT JOIN sulista.bot_filaenviowhatsapp
ON sulista.bot_filaenviowhatsapp.chave = coleta.filial || '' ||  coleta.numero
AND sulista.bot_filaenviowhatsapp.idtemplate = 'rastreamento_coletas_grupo_cliente'

  LEFT JOIN tipofrete
    ON coleta.tipofrete = tipofrete.codigo
    AND coleta.grupo = tipofrete.grupo
    AND coleta.empresa = tipofrete.empresa

LEFT JOIN sulista.status_transito
ON sulista.status_transito.placa = coleta.veiculo

LEFT JOIN coleta_ocorrencia 
ON coleta.filial = coleta_ocorrencia.filial
AND coleta.numero = coleta_ocorrencia.numero
AND coleta_ocorrencia.ocorrencia = 469

LEFT JOIN ocorrencia_motivo
ON ocorrencia_motivo.grupo = coleta_ocorrencia.grupo
AND ocorrencia_motivo.empresa = coleta_ocorrencia.empresa
AND ocorrencia_motivo.ocorrencia = coleta_ocorrencia.ocorrencia
AND ocorrencia_motivo.codigo = coleta_ocorrencia.motivo

LEFT JOIN ocorrencias
ON ocorrencias.grupo = coleta.grupo
AND ocorrencias.empresa = coleta.empresa
AND ocorrencias.filial = coleta.filial
AND ocorrencias.unidade = coleta.unidade
AND ocorrencias.diferenciadornumero = coleta.diferenciadornumero
AND ocorrencias.serie = coleta.serie
AND ocorrencias.numero = coleta.numero
AND ocorrencias.rn_ocorrencia = 1

WHERE 

coleta.situacao = 7 -- Não finalizada
AND transporte.situacao = 2 -- Com data de saida mas sem data de chegada
AND transporte.dtcancelamento IS NULL
AND coleta.dtcancelamento IS NULL
AND coleta.veiculo = transporte.veiculo

GROUP BY

  coleta.grupo
, coleta.empresa
, coleta.filial
, coleta.unidade
, coleta.diferenciadornumero
, coleta.serie
, coleta.numero
, trajeto.codigo
, agrupamentocliente.descricao
, remetente.nomefantasia
, destinatario.nomefantasia
, coleta.dtprevisaochegadaviagem
, sulista.bot_filaenviowhatsapp.chave
, rotograma.kmpercursorealizado
, rotograma.extensao
, rotograma.percpercursorealizado
, veiculo.placa
, veiculo.numerofrota
, carreta1.placa
, sulista.whatsappcliente.filial
, sulista.whatsappcliente.nrcoleta
, sulista.whatsappcliente.usuarioinclusao
, tipofrete.descricao
, sulista.status_transito.situacao_transito
, ocorrencias.descricao

)

SELECT

  rastreamento.*

FROM
rastreamento

ORDER BY
  rastreamento.ordem_status ASC
, rastreamento.percpercursorealizado::FLOAT ASC