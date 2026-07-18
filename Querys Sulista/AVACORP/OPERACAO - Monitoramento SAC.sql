-- MONITORAMENTO SAC // CST00000979900079520240626134609500305

WITH posicao AS (
SELECT
  -- BLOCO 1
  coleta.grupo
, coleta.empresa
, coleta.filial AS numero_filial_coleta
, coleta.unidade
, coleta.diferenciadornumero
, coleta.serie
, coleta.numero AS numero_coleta
, coleta.numerofatura as nrpedido
, coleta.agendadefinitiva 
, transporte.numero AS nr_transp

-- CONTA EM ORDEM DECRESCENTE E CLASSIFICA OS TRANSPORTES DISTINTOS DA COLETA.
, DENSE_RANK() OVER (
    PARTITION BY 
        coleta.grupo,
        coleta.empresa,
        coleta.filial,
        coleta.unidade,
        coleta.serie,
        coleta.diferenciadornumero,
        coleta.numero
    ORDER BY transporte.numero DESC
) AS rn_max_transpnumero

, usuario.nomecompleto AS usuarioemissor
, trajeto.codigo AS cod_trajeto  -- mapa
, coleta.remetentedefinido
, coleta.destinatariodefinido
, COALESCE(veiculo_transporte.numerofrota, veiculo_coleta.numerofrota) AS frota_cavalo
, COALESCE(veiculo_transporte.placa, veiculo_coleta.placa) AS placa_cavalo
, COALESCE(carreta1_transporte.numerofrota, carreta1_coleta.numerofrota) AS frota_carreta1
, COALESCE(carreta1_transporte.placa, carreta1_coleta.placa) AS placa_carreta1
, veiculo_posicao.descricaoposicao AS posicao
, CASE WHEN veiculo_posicao.situacao = 1 THEN '? Ligada' 
       ELSE '? Desligada' 
       END AS ignicao
, rotograma.extensao AS kmtotal
, (COALESCE(rotograma.kmpercursorealizado,0))::NUMERIC(15,2) AS rotograma_km_percorrido
, CASE WHEN COALESCE(rotograma.kmpercursorealizado,0) > COALESCE(rotograma.extensao,0) THEN 0
       ELSE ((COALESCE(rotograma.extensao,0) - COALESCE(rotograma.kmpercursorealizado,0)))::NUMERIC(15,2)
       END AS rotograma_km_restante
, motorista.razaosocial AS nomemotorista
, agrupamentocliente.descricao AS cliente
, CASE WHEN coleta_cliente.sequencia IS NULL THEN 1
       ELSE coleta_cliente.sequencia 
       END AS sequencia_cliente
  -- BLOCO 2

, CASE WHEN coleta.remetentedefinido = 1 THEN remetente.nomefantasia 
       ELSE remetentedefinido.nomefantasia
       END AS origem
, coleta.origem || '/' || coleta.uforigem AS local_coleta
, CASE WHEN coleta.destinatariodefinido = 1 THEN destinatario.nomefantasia 
       ELSE destinatariodefinido.nomefantasia
       END AS destino
, coleta.destino || '/' || coleta.ufdestino  AS local_destino

  -- BLOCO 3

, CASE WHEN coleta.remetentedefinido = 1 THEN coleta.dtcoletar
       ELSE coleta_cliente.dtagendamentocoleta
       END AS janela_coleta

, CASE WHEN coleta.remetentedefinido = 1 THEN coleta.dtcoletar
       ELSE coleta_cliente.dtagendamentocoleta
       END  AS dtcoleta

  -- BLOCO 4
, conhecimento.filial || ' - ' || conhecimento.numero AS ctes
, avacorpi.tipoconhecimento.descricao AS tipoconhecimento
, conhecimento_notafiscal.numeronotafiscal::text AS nfe
, SUM(conhecimento_notafiscal.quantidade) AS volumes
, shipment.shipment

  -- BLOCO 5
, CASE WHEN coleta.destinatariodefinido = 1 THEN coleta.dtprevisaochegadaviagem
       ELSE coleta_cliente.dtagendamentoentrega
       END AS janela_entrega
, CASE WHEN COALESCE(rotograma.kmpercursorealizado, 0) > COALESCE(rotograma.extensao, 0) THEN '0 hours'::INTERVAL
       WHEN COALESCE(rotograma_percurso.velocidademaxima, 0) = 0 THEN NULL
       ELSE (COALESCE(rotograma.extensao, 0) - COALESCE(rotograma.kmpercursorealizado, 0)) / rotograma_percurso.velocidademaxima * interval '1 hour'
       END AS tempoestimado2  -- Calcula a previão de chegada. Verificar quando houver mais de um destinatário.

  -- BLOCO 6
, tipofrete.descricao AS operacao

  -- BLOCO 7 Rotograma
, rotograma.grupo as gruporotograma
, rotograma.empresa AS empresarotograma
, rotograma.filial AS filialrotograma
, rotograma.unidade as unidadedocumento
, rotograma_documento.numerodocumento AS numrotograma

, coleta.dtemissao as emissao_coleta
, CASE WHEN coleta_cliente.frustrada = 1 THEN '?? FRUSTRADA'
       WHEN coleta_cliente.coletada = 1 THEN '?? COLETADA'
       WHEN coleta.remetentedefinido = 2 AND coleta.destinatariodefinido = 1 THEN '?? COLETA PROGRAMADA'
       WHEN coleta_cliente.remetente IS NOT NULL then '  '
       --ELSE '?? COLETA PROGRAMADA'
       END AS situacao_mr
, coleta_cliente.confirmaentrega as mr_entrega
, coleta_cliente.hra_chegada AS hra_chegada_mr
, coleta_cliente.hra_saida AS hra_saida_mr

, rotograma.dtfinalizado
, coleta.mercadorias

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

------- Fim de buscar a coleta de um cte

LEFT JOIN coleta_cliente
ON coleta_cliente.grupo = coleta.grupo
AND coleta_cliente.empresa = coleta.empresa
AND coleta_cliente.filial = coleta.filial
AND coleta_cliente.unidade = coleta.unidade 
AND coleta_cliente.diferenciadornumero = coleta.diferenciadornumero
AND coleta_cliente.serie = coleta.serie
AND coleta_cliente.numero = coleta.numero






LEFT JOIN cadastro remetentedefinido
    ON remetentedefinido.codigo = coleta_cliente.remetente

LEFT JOIN cadastro destinatariodefinido
    ON destinatariodefinido.codigo = coleta_cliente.destinatario

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

LEFT JOIN manifesto_composicao
ON manifesto_composicao.grupo = conhecimento.grupo
and manifesto_composicao.empresa =conhecimento.empresa
and manifesto_composicao.filialdocumento = conhecimento.filial
and manifesto_composicao.unidadedocumento = conhecimento.unidade
and manifesto_composicao.diferenciadornumerodocumento = conhecimento.diferenciadornumero
and CASE WHEN conhecimento.serie IS not NULL THEN manifesto_composicao.seriedocumento = conhecimento.serie 
    ELSE TRUE END
and manifesto_composicao.numerodocumento = conhecimento.numero
and manifesto_composicao.tipodocumento = conhecimento.tipodocumento

LEFT JOIN manifesto
ON manifesto.grupo = manifesto_composicao.grupo
and manifesto.empresa = manifesto_composicao.empresa 
and manifesto.filial = manifesto_composicao.filial 
and manifesto.unidade = manifesto_composicao.unidade 
and manifesto.diferenciadornumero = manifesto_composicao.diferenciadornumero 
and manifesto.serie = manifesto_composicao.serie 
and manifesto.numero = manifesto_composicao.numero 

LEFT JOIN transporte_manifesto
ON transporte_manifesto.grupo = manifesto_composicao.grupo 
and transporte_manifesto.empresa = manifesto_composicao.empresa 
and transporte_manifesto.filialdocumento = manifesto_composicao.filial
and transporte_manifesto.unidadedocumento = manifesto_composicao.unidade 
and transporte_manifesto.diferenciadornumerodocumento = manifesto_composicao.diferenciadornumero 
and transporte_manifesto.seriedocumento  = manifesto_composicao.serie
and transporte_manifesto.numerodocumento = manifesto_composicao.numero

LEFT JOIN transporte
ON transporte.grupo = transporte_manifesto.grupo 
and transporte.empresa = transporte_manifesto.empresa 
and transporte.diferenciadornumero = transporte_manifesto.diferenciadornumero 
and transporte.numero = transporte_manifesto.numero

LEFT JOIN veiculo veiculo_coleta
ON veiculo_coleta.placa = coleta.veiculo
LEFT JOIN veiculo veiculo_transporte
ON veiculo_transporte.placa = transporte.veiculo



LEFT JOIN cadastro motorista
    ON motorista.codigo = coleta.motorista

LEFT JOIN veiculo
    ON veiculo.placa = coleta.veiculo

LEFT JOIN veiculo carreta1
    ON carreta1.placa = coleta.carreta1
    


LEFT JOIN usuario
ON coleta.usuarioemissor = usuario.codigo

LEFT JOIN conhecimento_notafiscal
ON conhecimento_notafiscal.grupo = conhecimento.grupo
AND conhecimento_notafiscal.empresa = conhecimento.empresa
AND conhecimento_notafiscal.filial = conhecimento.filial
AND conhecimento_notafiscal.unidade = conhecimento.unidade
AND conhecimento_notafiscal.numero = conhecimento.numero
AND conhecimento_notafiscal.diferenciadornumero = conhecimento.diferenciadornumero
AND conhecimento_notafiscal.serie = conhecimento.serie

LEFT JOIN avacorpi.tipoconhecimento 
ON avacorpi.tipoconhecimento.id = conhecimento.tipo

LEFT JOIN trajeto
ON trajeto.grupo = transporte.grupo
AND trajeto.empresa = transporte.empresa
AND trajeto.codigo = transporte.trajeto

  LEFT JOIN tipofrete
    ON coleta.tipofrete = tipofrete.codigo
    AND coleta.grupo = tipofrete.grupo
    AND coleta.empresa = tipofrete.empresa

LEFT JOIN agrupamentocliente_cnpjcpfcodigo
ON agrupamentocliente_cnpjcpfcodigo.grupo = coleta.grupo
AND agrupamentocliente_cnpjcpfcodigo.empresa = coleta.empresa
AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = coleta.cnpjcpfcodigopagadorfrete
AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1

LEFT JOIN agrupamentocliente
ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo

      LEFT JOIN 
          (SELECT   conhecimento_composicao.numero AS cte
                  , conhecimento_composicao.grupo
                  , conhecimento_composicao.empresa
                  , conhecimento_composicao.filial
                  , conhecimento_composicao.unidade
                  , coleta.numerofatura AS shipment
                  , conhecimento_composicao.serie
                  , coleta.dtcoletar
      
                  FROM conhecimento_composicao
                  LEFT JOIN coleta
                  ON coleta.grupo = conhecimento_composicao.grupo
                  AND coleta.empresa = conhecimento_composicao.empresa
                  AND coleta.filial = conhecimento_composicao.filial
                  AND coleta.unidade = conhecimento_composicao.unidade
                  AND coleta.numero = conhecimento_composicao.numerodocumento
                  AND coleta.serie = conhecimento_composicao.seriedocumento
                  AND coleta.diferenciadornumero = conhecimento_composicao.diferenciadornumerodocumento
                  ) shipment
      ON conhecimento.grupo = shipment.grupo
      AND conhecimento.empresa = shipment.empresa
      AND conhecimento.filial = shipment.filial
      AND conhecimento.unidade = shipment.unidade 
      AND conhecimento.numero = shipment.cte
      AND conhecimento.serie = shipment.serie

LEFT JOIN cadastro remetente
    ON remetente.codigo = COALESCE(coleta.remetente, conhecimento.remetente)
    
LEFT JOIN cadastro destinatario
    ON destinatario.codigo = COALESCE(coleta.destinatario, conhecimento.destinatario)

LEFT JOIN cadastro cnpjpagadorfrete
    ON cnpjpagadorfrete.codigo = COALESCE(coleta.cnpjcpfcodigopagadorfrete, conhecimento.cnpjcpfcodigopagadorfrete)

LEFT JOIN cadastro emissor_nf
    ON emissor_nf.codigo = conhecimento_notafiscal.cnpjcpfcodigoemissor

LEFT JOIN rotograma_documento 
ON rotograma_documento.grupo = transporte.grupo
AND rotograma_documento.empresa = transporte.empresa
AND rotograma_documento.veiculo = transporte.veiculo
AND rotograma_documento.numerodocumento = transporte.numero
AND rotograma_documento.tipodocumento = 201

LEFT JOIN rotograma
ON rotograma.grupo = rotograma_documento.grupo 
AND rotograma.empresa = rotograma_documento.empresa 
AND rotograma.veiculo = rotograma_documento.veiculo 
AND rotograma.sequencia = rotograma_documento.sequencia
AND rotograma_documento.tipodocumento = 201

LEFT JOIN veiculo carreta1_coleta
    ON carreta1_coleta.placa = coleta.carreta1
LEFT JOIN veiculo carreta1_transporte
    ON carreta1_transporte.placa = transporte.carreta1

LEFT JOIN veiculo carreta2_coleta
    ON carreta2_coleta.placa = coleta.carreta2
LEFT JOIN veiculo carreta2_transporte
    ON carreta2_transporte.placa = transporte.carreta2


LEFT JOIN LATERAL (SELECT rotograma_percurso.velocidademaxima

    FROM rotograma_percurso
    WHERE rotograma_percurso.grupo = rotograma.grupo
    AND rotograma_percurso.empresa = rotograma.empresa
    AND rotograma_percurso.veiculo = rotograma.veiculo
    AND rotograma_percurso.sequencia = rotograma.sequencia
    limit 1
    ) AS rotograma_percurso 
    ON TRUE

LEFT JOIN veiculo_posicao
    ON  veiculo_posicao.veiculo = transporte.veiculo
    AND veiculo_posicao.ultimaposicao = 1

WHERE
coleta.dtcoletar::DATE BETWEEN '2026-07-17' AND '2026-07-17'
AND coleta.dtcancelamento IS NULL
AND conhecimento.dtcancelamento IS NULL
--AND coleta.numero IN (9597)

GROUP BY

 -- BLOCO 1
  coleta.mercadorias
, rotograma.dtfinalizado 
, coleta.grupo
, coleta.empresa
, coleta.filial
, coleta.unidade
, coleta.diferenciadornumero
, coleta.serie
, coleta.numero
, usuario.nomecompleto
, coleta.remetentedefinido
, coleta.destinatariodefinido
, trajeto.codigo
, veiculo.numerofrota
, veiculo.placa
, carreta1.numerofrota
, carreta1.placa
, carreta1_transporte.numerofrota
, carreta1_coleta.numerofrota
, carreta1_transporte.placa
, carreta1_coleta.placa
, veiculo_posicao.descricaoposicao
, veiculo_posicao.situacao
, veiculo_transporte.numerofrota
, veiculo_transporte.placa
, veiculo_coleta.placa
, veiculo_coleta.numerofrota
, rotograma.extensao
, rotograma.kmpercursorealizado
, rotograma.extensao
, motorista.razaosocial
, agrupamentocliente.descricao
, coleta_cliente.sequencia
, transporte.numero
  -- BLOCO 2
, remetente.nomefantasia
, remetentedefinido.nomefantasia
, coleta.origem
, coleta.uforigem
, destinatario.nomefantasia
, destinatariodefinido.nomefantasia
, coleta.destino
, coleta.ufdestino
, coleta.numerofatura
  -- BLOCO 3
, coleta.dtcoletar
, coleta_cliente.dtagendamentocoleta

  -- BLOCO 4
, conhecimento.filial
, conhecimento.numero
, avacorpi.tipoconhecimento.descricao
, conhecimento_notafiscal.numeronotafiscal::text
, shipment.shipment

  -- BLOCO 5
, coleta.dtprevisaochegadaviagem
, coleta_cliente.dtagendamentoentrega
, rotograma_percurso.velocidademaxima
  -- BLOCO 6
, tipofrete.descricao

  -- BLOCO 7 Rotograma
, rotograma.grupo
, rotograma.empresa
, rotograma.filial
, rotograma.unidade
, rotograma_documento.numerodocumento
, rotograma.dtfinalizado
, coleta_cliente.frustrada
, coleta_cliente.coletada
, coleta_cliente.confirmaentrega
, coleta_cliente.hra_chegada
, coleta_cliente.hra_saida
, coleta_cliente.remetente
, coleta.destino
ORDER BY
  coleta.numero
, transporte.numero DESC

), ocorrencias as (

---- ####################### O C O R R Ê N C I A S  S A C ####################### ----

      WITH ocorrencias_numeradas AS (
      SELECT
        coleta.grupo
      , coleta.empresa
      , coleta.filial AS filial
      , coleta.unidade
      , coleta.diferenciadornumero
      , coleta.serie
      , coleta.numero AS coleta
      , CASE WHEN coleta_cliente.sequencia IS NULL THEN 1
             ELSE coleta_cliente.sequencia END AS sequencia
      , coleta_ocorrencia.sequenciaocorrencia
      , coleta_ocorrencia.ocorrencia
      , ocorrencia.descricao
      , coleta_ocorrencia.dtocorrencia
      , coleta.remetentedefinido
      , coleta.destinatariodefinido
      , ROW_NUMBER() OVER (
                      PARTITION BY 
                        coleta.grupo, 
                        coleta.empresa, 
                        coleta.filial, 
                        coleta.unidade, 
                        coleta.diferenciadornumero, 
                        coleta.serie, 
                        coleta.numero, 
                        coleta_cliente.sequencia, 
                        coleta_ocorrencia.ocorrencia
                     ORDER BY coleta_ocorrencia.sequenciaocorrencia
                            ) AS rn,
        ROW_NUMBER() OVER (
            PARTITION BY 
                coleta.grupo, 
                coleta.empresa, 
                coleta.filial, 
                coleta.unidade, 
                coleta.diferenciadornumero, 
                coleta.serie,   
                coleta.numero, 
                coleta_cliente.sequencia
            ORDER BY coleta_ocorrencia.dtinc DESC
        ) AS rn_max_sequenciaocorrencia
      
      FROM
      coleta
      
      LEFT JOIN coleta_ocorrencia
      ON coleta_ocorrencia.grupo = coleta.grupo
      AND coleta_ocorrencia.empresa = coleta.empresa
      AND coleta_ocorrencia.filial = coleta.filial
      AND coleta_ocorrencia.unidade = coleta.unidade
      AND coleta_ocorrencia.diferenciadornumero = coleta.diferenciadornumero
      AND coleta_ocorrencia.serie = coleta.serie
      AND coleta_ocorrencia.numero = coleta.numero
      
      LEFT JOIN coleta_cliente
      ON coleta_cliente.grupo = coleta.grupo
      AND coleta_cliente.empresa = coleta.empresa
      AND coleta_cliente.filial = coleta.filial
      AND coleta_cliente.unidade = coleta.unidade 
      AND coleta_cliente.diferenciadornumero = coleta.diferenciadornumero
      AND coleta_cliente.serie = coleta.serie
      AND coleta_cliente.numero = coleta.numero

      LEFT JOIN ocorrencia
      ON ocorrencia.codigo = coleta_ocorrencia.ocorrencia
      
      WHERE
      ocorrencia.descricao ILIKE '%sac%'
      
      ), dados_agregados AS (
      
      SELECT
        ocorrencias_numeradas.grupo
      , ocorrencias_numeradas.empresa
      , ocorrencias_numeradas.filial
      , ocorrencias_numeradas.unidade
      , ocorrencias_numeradas.diferenciadornumero
      , ocorrencias_numeradas.serie
      , ocorrencias_numeradas.coleta
      , ocorrencias_numeradas.sequencia
      , ocorrencias_numeradas.remetentedefinido
      , ocorrencias_numeradas.destinatariodefinido
      , MAX(ocorrencias_numeradas.dtocorrencia) AS dt_status_viagem
      , MAX(CASE WHEN ocorrencias_numeradas.rn_max_sequenciaocorrencia = 1 THEN ocorrencias_numeradas.ocorrencia || ' - ' || ocorrencias_numeradas.descricao 
      END) AS status_viagem
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 394 AND rn = 1 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_carregamento_1
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 395 AND rn = 1 THEN ocorrencias_numeradas.dtocorrencia END) AS saida_carregamento_1
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 396 AND rn = 1 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_descarga_1
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 397 AND rn = 1 THEN ocorrencias_numeradas.dtocorrencia END) AS fim_descarga_1
 
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 394 AND rn = 2 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_carregamento_2
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 395 AND rn = 2 THEN ocorrencias_numeradas.dtocorrencia END) AS saida_carregamento_2
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 396 AND rn = 2 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_descarga_2
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 397 AND rn = 2 THEN ocorrencias_numeradas.dtocorrencia END) AS fim_descarga_2
      
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 394 AND rn = 3 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_carregamento_3
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 395 AND rn = 3 THEN ocorrencias_numeradas.dtocorrencia END) AS saida_carregamento_3
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 396 AND rn = 3 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_descarga_3
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 397 AND rn = 3 THEN ocorrencias_numeradas.dtocorrencia END) AS fim_descarga_3
      
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 394 AND rn = 4 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_carregamento_4
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 395 AND rn = 4 THEN ocorrencias_numeradas.dtocorrencia END) AS saida_carregamento_4
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 396 AND rn = 4 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_descarga_4
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 397 AND rn = 4 THEN ocorrencias_numeradas.dtocorrencia END) AS fim_descarga_4
      
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 394 AND rn = 5 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_carregamento_5
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 395 AND rn = 5 THEN ocorrencias_numeradas.dtocorrencia END) AS saida_carregamento_5
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 396 AND rn = 5 THEN ocorrencias_numeradas.dtocorrencia END) AS chegada_descarga_5
      , MAX(CASE WHEN ocorrencias_numeradas.ocorrencia = 397 AND rn = 5 THEN ocorrencias_numeradas.dtocorrencia END) AS fim_descarga_5

, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440)
           AND rn = 1 THEN ocorrencias_numeradas.descricao END) AS atraso_coleta_1
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440)
           AND rn = 2 THEN ocorrencias_numeradas.descricao END) AS atraso_coleta_2
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440)
           AND rn = 3 THEN ocorrencias_numeradas.descricao END) AS atraso_coleta_3
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440)
           AND rn = 4 THEN ocorrencias_numeradas.descricao END) AS atraso_coleta_4
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440)
           AND rn = 5 THEN ocorrencias_numeradas.descricao END) AS atraso_coleta_5

, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (441, 442, 443, 444, 445, 446, 447, 448, 449, 450, 451, 452, 453, 454, 455, 456)
           AND rn = 1 THEN ocorrencias_numeradas.descricao END) AS atraso_entrega_1
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (441, 442, 443, 444, 445, 446, 447, 448, 449, 450, 451, 452, 453, 454, 455, 456)
           AND rn = 2 THEN ocorrencias_numeradas.descricao END) AS atraso_entrega_2
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (441, 442, 443, 444, 445, 446, 447, 448, 449, 450, 451, 452, 453, 454, 455, 456)
           AND rn = 3 THEN ocorrencias_numeradas.descricao END) AS atraso_entrega_3
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (441, 442, 443, 444, 445, 446, 447, 448, 449, 450, 451, 452, 453, 454, 455, 456)
           AND rn = 4 THEN ocorrencias_numeradas.descricao END) AS atraso_entrega_4
, MAX(CASE WHEN ocorrencias_numeradas.ocorrencia IN (441, 442, 443, 444, 445, 446, 447, 448, 449, 450, 451, 452, 453, 454, 455, 456)
           AND rn = 5 THEN ocorrencias_numeradas.descricao END) AS atraso_entrega_5

      FROM
      
      ocorrencias_numeradas
      
      GROUP BY
        ocorrencias_numeradas.grupo
      , ocorrencias_numeradas.empresa
      , ocorrencias_numeradas.filial
      , ocorrencias_numeradas.unidade
      , ocorrencias_numeradas.diferenciadornumero
      , ocorrencias_numeradas.serie
      , ocorrencias_numeradas.coleta
      , ocorrencias_numeradas.sequencia
      , ocorrencias_numeradas.remetentedefinido
      , ocorrencias_numeradas.destinatariodefinido
      )
      
      SELECT
      
        dados_agregados.grupo
      , dados_agregados.empresa
      , dados_agregados.filial
      , dados_agregados.unidade
      , dados_agregados.diferenciadornumero
      , dados_agregados.serie
      , dados_agregados.coleta
      , dados_agregados.sequencia
      , dados_agregados.remetentedefinido
      , dados_agregados.destinatariodefinido
      , dados_agregados.status_viagem
      , dados_agregados.dt_status_viagem

      , dados_agregados.chegada_carregamento_1
      , dados_agregados.saida_carregamento_1
      , dados_agregados.chegada_descarga_1
      , dados_agregados.fim_descarga_1
      , dados_agregados.chegada_carregamento_2
      , dados_agregados.saida_carregamento_2
      , dados_agregados.chegada_descarga_2
      , dados_agregados.fim_descarga_2
      , dados_agregados.chegada_carregamento_3
      , dados_agregados.saida_carregamento_3
      , dados_agregados.chegada_descarga_3
      , dados_agregados.fim_descarga_3
      , dados_agregados.chegada_carregamento_4
      , dados_agregados.saida_carregamento_4
      , dados_agregados.chegada_descarga_4
      , dados_agregados.fim_descarga_4
      , dados_agregados.chegada_carregamento_5
      , dados_agregados.saida_carregamento_5
      , dados_agregados.chegada_descarga_5
      , dados_agregados.fim_descarga_5

      , dados_agregados.atraso_coleta_1
      , dados_agregados.atraso_coleta_2
      , dados_agregados.atraso_coleta_3
      , dados_agregados.atraso_coleta_4
      , dados_agregados.atraso_coleta_5
      , dados_agregados.atraso_entrega_1
      , dados_agregados.atraso_entrega_2
      , dados_agregados.atraso_entrega_3
      , dados_agregados.atraso_entrega_4
      , dados_agregados.atraso_entrega_5

      FROM dados_agregados
      ORDER BY sequencia

), coletaagrupada AS (

---- ####################### C O L E T A S  A G R U P A D A S ####################### ----

                WITH agrupamento AS (
                
                SELECT 
                
                  manutencao.gerardocumentoautomatico_coleta.grupo
                , manutencao.gerardocumentoautomatico_coleta.empresa
                , manutencao.gerardocumentoautomatico_coleta.filial
                , manutencao.gerardocumentoautomatico_coleta.unidade
                , manutencao.gerardocumentoautomatico_coleta.diferenciadornumero
                , manutencao.gerardocumentoautomatico_coleta.serie
                , manutencao.gerardocumentoautomatico_coleta.numero
                , manutencao.gerardocumentoautomatico_coleta.sequencia
                
                FROM 
                manutencao.gerardocumentoautomatico_coleta

                ), contagem AS(
                
                SELECT 
                
                  manutencao.gerardocumentoautomatico_coleta.sequencia
                , CASE WHEN COUNT(manutencao.gerardocumentoautomatico_coleta.sequencia) >1 THEN 'AGRUPADA' ELSE 'SIMPLES' END AS tipo
                , STRING_AGG(DISTINCT manutencao.gerardocumentoautomatico_coleta.numero::text, ', ') AS coleta

                FROM 
                manutencao.gerardocumentoautomatico_coleta
                
                
                LEFT JOIN coleta 
                ON coleta.grupo = manutencao.gerardocumentoautomatico_coleta.grupo
                AND coleta.empresa = manutencao.gerardocumentoautomatico_coleta.empresa
                AND coleta.filial = manutencao.gerardocumentoautomatico_coleta.filial
                AND coleta.unidade = manutencao.gerardocumentoautomatico_coleta.unidade 
                AND coleta.diferenciadornumero = manutencao.gerardocumentoautomatico_coleta.diferenciadornumero
                AND coleta.serie = manutencao.gerardocumentoautomatico_coleta.serie
                AND coleta.numero = manutencao.gerardocumentoautomatico_coleta.numero
                
                LEFT JOIN coleta_composicao 
                ON coleta_composicao.grupo = coleta.grupo
                AND coleta_composicao.empresa = coleta.empresa
                AND coleta_composicao.filial = coleta.filial
                AND coleta_composicao.unidade = coleta.unidade 
                AND coleta_composicao.diferenciadornumero = coleta.diferenciadornumero
                AND coleta_composicao.serie = coleta.serie
                AND coleta_composicao.numero = coleta.numero
                
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
                
                LEFT JOIN conhecimento_notafiscal
                ON conhecimento_notafiscal.grupo = conhecimento.grupo
                AND conhecimento_notafiscal.empresa = conhecimento.empresa
                AND conhecimento_notafiscal.filial = conhecimento.filial
                AND conhecimento_notafiscal.unidade = conhecimento.unidade
                AND conhecimento_notafiscal.numero = conhecimento.numero
                AND conhecimento_notafiscal.diferenciadornumero = conhecimento.diferenciadornumero
                AND conhecimento_notafiscal.serie = conhecimento.serie
                
                GROUP BY
                  manutencao.gerardocumentoautomatico_coleta.sequencia
                )
                
                SELECT
                
                  agrupamento.grupo
                , agrupamento.empresa
                , agrupamento.filial
                , agrupamento.unidade
                , agrupamento.diferenciadornumero
                , agrupamento.serie
                , agrupamento.numero
                , agrupamento.sequencia
                , contagem.sequencia
                , contagem.tipo
                , contagem.coleta
                
                FROM  
                agrupamento
                
                LEFT JOIN contagem
                ON contagem.sequencia = agrupamento.sequencia
)

---- ####################### R E S U L T A D O  1 ####################### ----
, resultado AS (
SELECT --DISTINCT
--BLOCO 1 ok
  posicao.grupo
, posicao.empresa
, posicao.numero_filial_coleta as filial
, posicao.unidade
, posicao.diferenciadornumero
, posicao.serie
, posicao.numero_coleta AS coleta
, posicao.agendadefinitiva 
, posicao.usuarioemissor
, posicao.nr_transp
, COALESCE(coletaagrupada.tipo, 'NORMAL') AS tipo
, coletaagrupada.coleta AS coletaagrupada
, CASE WHEN posicao.numero_filial_coleta = 1 THEN 'MTZ'
       WHEN posicao.numero_filial_coleta = 2 THEN 'SBC'
       WHEN posicao.numero_filial_coleta = 7 THEN 'RESENDE'
       WHEN posicao.numero_filial_coleta = 15 THEN 'PSA'
       WHEN posicao.numero_filial_coleta = 19 THEN 'JOI'
       WHEN posicao.numero_filial_coleta = 20 THEN 'CRZ'
       WHEN posicao.numero_filial_coleta = 21 THEN 'PTA'
       WHEN posicao.numero_filial_coleta = 25 THEN 'CAMPO GRANDE'
       END AS filialnome
, posicao.cod_trajeto
, posicao.frota_cavalo
, posicao.placa_cavalo
, posicao.frota_carreta1
, posicao.placa_carreta1
,INITCAP(CASE 
      WHEN UPPER(SPLIT_PART(posicao.posicao, '-', 2)) LIKE '%,%' THEN UPPER(SPLIT_PART(posicao.posicao, '-', 1)) 
      WHEN ARRAY_LENGTH(REGEXP_SPLIT_TO_ARRAY(posicao.posicao, '-'), 1) > 2 THEN (REGEXP_SPLIT_TO_ARRAY(posicao.posicao, '-'))[3]
      ELSE UPPER(SPLIT_PART(posicao.posicao, '-', 2)) END) AS posicao_atual
, posicao.ignicao
, posicao.kmtotal
, posicao.rotograma_km_percorrido AS percorrido
--, posicao.rotograma_km_restante AS restante

, CASE WHEN posicao.dtfinalizado IS NOT NULL THEN 0 -- Se finalizado (progresso 100%), km restante é 0
       ELSE ((COALESCE(posicao.kmtotal,0) - COALESCE(posicao.rotograma_km_percorrido,0)))::NUMERIC(15,2)
  END AS restante
  
, CASE WHEN posicao.dtfinalizado IS NOT NULL THEN 100
       ELSE (posicao.rotograma_km_percorrido / posicao.kmtotal * 100)
       END AS progresso
--, posicao.rotograma_km_percorrido / posicao.kmtotal * 100 AS progresso      -- REGRA ANTIGA DE VALIDAÇÃO DE ROTOGRAMA
, INITCAP(posicao.nomemotorista) AS motorista
, posicao.cliente
, posicao.sequencia_cliente

-- BLOCO 2 ok
, INITCAP(posicao.origem) AS origem
, INITCAP(posicao.local_coleta) AS local_coleta
, INITCAP(posicao.destino) AS destino
, INITCAP(posicao.local_destino) AS local_destino

-- BLOCO 3 ok
, posicao.janela_coleta
, posicao.dtcoleta
, CASE WHEN posicao.destinatariodefinido = 2 THEN ocorrencias.chegada_carregamento_1
       ELSE
       CASE 
            WHEN posicao.sequencia_cliente = 1 THEN ocorrencias.chegada_carregamento_1
            WHEN posicao.sequencia_cliente = 2 THEN ocorrencias.chegada_carregamento_2
            WHEN posicao.sequencia_cliente = 3 THEN ocorrencias.chegada_carregamento_3
            WHEN posicao.sequencia_cliente = 4 THEN ocorrencias.chegada_carregamento_4
            WHEN posicao.sequencia_cliente = 5 THEN ocorrencias.chegada_carregamento_5
            END
       END AS chegada_carregamento

, CASE WHEN posicao.destinatariodefinido = 2 THEN ocorrencias.saida_carregamento_1
       ELSE
       CASE WHEN posicao.sequencia_cliente = 1 THEN ocorrencias.saida_carregamento_1
            WHEN posicao.sequencia_cliente = 2 THEN ocorrencias.saida_carregamento_2
            WHEN posicao.sequencia_cliente = 3 THEN ocorrencias.saida_carregamento_3
            WHEN posicao.sequencia_cliente = 4 THEN ocorrencias.saida_carregamento_4
            WHEN posicao.sequencia_cliente = 5 THEN ocorrencias.saida_carregamento_5
            END 
       END AS saida_carregamento


, CASE WHEN posicao.destinatariodefinido = 2 THEN ocorrencias.atraso_coleta_1
       ELSE
       CASE 
            WHEN posicao.sequencia_cliente = 1 THEN ocorrencias.atraso_coleta_1
            WHEN posicao.sequencia_cliente = 2 THEN ocorrencias.atraso_coleta_2
            WHEN posicao.sequencia_cliente = 3 THEN ocorrencias.atraso_coleta_3
            WHEN posicao.sequencia_cliente = 4 THEN ocorrencias.atraso_coleta_4
            WHEN posicao.sequencia_cliente = 5 THEN ocorrencias.atraso_coleta_5
            END
       END AS atraso_carregamento

-- BLOCO 4 ok
, STRING_AGG(DISTINCT SPLIT_PART(posicao.ctes, ' - ', 2), ' / ') as ctes
, posicao.tipoconhecimento AS tipo_cte
, STRING_AGG(DISTINCT posicao.nfe, ' / ') as nfe
, SUM(posicao.volumes) AS volumes
--, posicao.shipment AS nrpedido

, posicao.mercadorias

-- BLOCO 5

, posicao.janela_entrega
, CASE WHEN ocorrencias.status_viagem = '401 - VIAGEM FINALIZADA (SAC)' THEN '??'
       ELSE TO_CHAR(NOW() + posicao.tempoestimado2::TIME, 'DD/MM HH24:MI') END AS previsao_chegada

, CASE WHEN posicao.remetentedefinido = 2 THEN ocorrencias.chegada_descarga_1
       ELSE
       CASE WHEN posicao.sequencia_cliente = 1 THEN ocorrencias.chegada_descarga_1
              WHEN posicao.sequencia_cliente = 2 THEN ocorrencias.chegada_descarga_2
              WHEN posicao.sequencia_cliente = 3 THEN ocorrencias.chegada_descarga_3
              WHEN posicao.sequencia_cliente = 4 THEN ocorrencias.chegada_descarga_4
              WHEN posicao.sequencia_cliente = 5 THEN ocorrencias.chegada_descarga_5
              END 
       END AS chegada_descarga

, CASE WHEN posicao.remetentedefinido = 2 THEN ocorrencias.fim_descarga_1
       ELSE
       CASE WHEN posicao.sequencia_cliente = 1 THEN ocorrencias.fim_descarga_1
            WHEN posicao.sequencia_cliente = 2 THEN ocorrencias.fim_descarga_2
            WHEN posicao.sequencia_cliente = 3 THEN ocorrencias.fim_descarga_3
            WHEN posicao.sequencia_cliente = 4 THEN ocorrencias.fim_descarga_4
            WHEN posicao.sequencia_cliente = 5 THEN ocorrencias.fim_descarga_5
            END 
       END AS fim_descarga

, CASE WHEN posicao.destinatariodefinido = 2 THEN ocorrencias.atraso_entrega_1
       ELSE
       CASE 
            WHEN posicao.sequencia_cliente = 1 THEN ocorrencias.atraso_entrega_1
            WHEN posicao.sequencia_cliente = 2 THEN ocorrencias.atraso_entrega_2
            WHEN posicao.sequencia_cliente = 3 THEN ocorrencias.atraso_entrega_3
            WHEN posicao.sequencia_cliente = 4 THEN ocorrencias.atraso_entrega_4
            WHEN posicao.sequencia_cliente = 5 THEN ocorrencias.atraso_entrega_5
            END
       END AS atraso_descarga

-- BLOCO 6
, ocorrencias.status_viagem
, ocorrencias.dt_status_viagem
, posicao.operacao

  -- BLOCO 7 Rotograma
, posicao.gruporotograma
, posicao.empresarotograma
, posicao.filialrotograma
, posicao.unidadedocumento
, posicao.numrotograma
, posicao.situacao_mr
, posicao.mr_entrega
, posicao.hra_chegada_mr
, posicao.hra_saida_mr
, posicao.nrpedido

FROM

posicao

LEFT JOIN ocorrencias
ON ocorrencias.grupo = posicao.grupo
AND ocorrencias.empresa = posicao.empresa
AND ocorrencias.filial = posicao.numero_filial_coleta
AND ocorrencias.unidade = posicao.unidade
AND ocorrencias.diferenciadornumero = posicao.diferenciadornumero
AND ocorrencias.serie = posicao.serie
AND ocorrencias.coleta = posicao.numero_coleta
AND ocorrencias.sequencia = posicao.sequencia_cliente

LEFT JOIN coletaagrupada
ON coletaagrupada.grupo = posicao.grupo
AND coletaagrupada.empresa = posicao.empresa
AND coletaagrupada.filial = posicao.numero_filial_coleta
AND coletaagrupada.unidade = posicao.unidade
AND coletaagrupada.diferenciadornumero = posicao.diferenciadornumero
AND coletaagrupada.serie = posicao.serie
AND coletaagrupada.numero = posicao.numero_coleta




WHERE
  posicao.rn_max_transpnumero = 1

GROUP BY

--BLOCO 1 ok
  posicao.mercadorias
, posicao.dtfinalizado
, posicao.nrpedido
, posicao.grupo
, posicao.empresa
, posicao.numero_filial_coleta
, posicao.unidade
, posicao.diferenciadornumero
, posicao.serie
, posicao.numero_coleta
, posicao.usuarioemissor
, posicao.nr_transp
, posicao.remetentedefinido
, posicao.destinatariodefinido
, coletaagrupada.tipo
, coletaagrupada.coleta
, posicao.cod_trajeto
, posicao.frota_cavalo
, posicao.placa_cavalo
, posicao.frota_carreta1
, posicao.placa_carreta1
, posicao.posicao
, posicao.ignicao
, posicao.kmtotal
, posicao.rotograma_km_percorrido
, posicao.rotograma_km_restante
, posicao.nomemotorista
, posicao.cliente
, posicao.sequencia_cliente
, posicao.agendadefinitiva 

-- BLOCO 2 ok
, posicao.origem
, posicao.local_coleta
, posicao.destino
, posicao.local_destino

-- BLOCO 3 ok
, posicao.janela_coleta
, posicao.dtcoleta
, ocorrencias.chegada_carregamento_1
, ocorrencias.chegada_carregamento_2
, ocorrencias.chegada_carregamento_3
, ocorrencias.chegada_carregamento_4
, ocorrencias.chegada_carregamento_5
, ocorrencias.saida_carregamento_1
, ocorrencias.saida_carregamento_2
, ocorrencias.saida_carregamento_3
, ocorrencias.saida_carregamento_4
, ocorrencias.saida_carregamento_5
, ocorrencias.atraso_coleta_1
, ocorrencias.atraso_coleta_2
, ocorrencias.atraso_coleta_3
, ocorrencias.atraso_coleta_4
, ocorrencias.atraso_coleta_5

-- BLOCO 4 ok
, posicao.tipoconhecimento
, posicao.shipment

-- BLOCO 5
, posicao.janela_entrega
, posicao.janela_entrega
, ocorrencias.chegada_descarga_1
, ocorrencias.chegada_descarga_2
, ocorrencias.chegada_descarga_3
, ocorrencias.chegada_descarga_4
, ocorrencias.chegada_descarga_5
, ocorrencias.fim_descarga_1
, ocorrencias.fim_descarga_2
, ocorrencias.fim_descarga_3
, ocorrencias.fim_descarga_4
, ocorrencias.fim_descarga_5

, ocorrencias.atraso_entrega_1
, ocorrencias.atraso_entrega_2
, ocorrencias.atraso_entrega_3
, ocorrencias.atraso_entrega_4
, ocorrencias.atraso_entrega_5

, posicao.tempoestimado2::TIME

-- BLOCO 6
, ocorrencias.status_viagem
, ocorrencias.dt_status_viagem
, posicao.operacao

  -- BLOCO 7 Rotograma
, posicao.gruporotograma
, posicao.empresarotograma
, posicao.filialrotograma
, posicao.unidadedocumento
, posicao.numrotograma
, posicao.emissao_coleta
, posicao.situacao_mr
, posicao.mr_entrega
, posicao.hra_chegada_mr
, posicao.hra_saida_mr


---- ####################### F R E E   T I M E ####################### ----
), freetime AS (
    WITH freetime_origem AS (
        SELECT
            sulista.sac_freetimecliente.grupo
        , sulista.sac_freetimecliente.empresa
        , sulista.sac_freetimecliente.agrupamentocliente
        , agrupamentocliente.descricao AS cliente
        , sulista.sac_freetimecliente.freetimecarga AS freetime_coleta
        , sulista.sac_freetimecliente.valor_coleta AS vlr_hora_coleta
        , sulista.sac_freetimecliente.freetimedescarga AS freetime_descarga
        , sulista.sac_freetimecliente.valor_entrega AS vlr_hora_descarga
        , sulista.sac_freetimecliente.dtinicio
        , sulista.sac_freetimecliente.dtfim
        , sulista.sac_freetimecliente.distingueoperacao
        , sulista.sac_freetimecliente.observacao
        FROM sulista.sac_freetimecliente
        LEFT JOIN agrupamentocliente
        ON agrupamentocliente.grupo = sulista.sac_freetimecliente.grupo
        AND agrupamentocliente.empresa = sulista.sac_freetimecliente.empresa
        AND agrupamentocliente.codigo = sulista.sac_freetimecliente.agrupamentocliente
    ), coletas AS (
        SELECT
            coleta.grupo
        , coleta.empresa
        , coleta.filial
        , coleta.unidade
        , coleta.diferenciadornumero
        , coleta.serie
        , coleta.numero
        , coleta.dtemissao
        , coleta.dtcoletar
        , agrupamentocliente.descricao AS cliente
        , agrupamentocliente.codigo as cod_cliente
        , coleta.mercadorias
        -- Adicionado o CNPJ do destinatário para uso na condição do freetime
        , destinatario_cadastro.codigo AS cnpj_destinatario
        FROM coleta
        LEFT JOIN agrupamentocliente_cnpjcpfcodigo
        ON agrupamentocliente_cnpjcpfcodigo.grupo = coleta.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = coleta.empresa
        AND agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo = coleta.cnpjcpfcodigopagadorfrete
        AND agrupamentocliente_cnpjcpfcodigo.vinculo = 1
        LEFT JOIN agrupamentocliente
        ON agrupamentocliente.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
        AND agrupamentocliente.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
        AND agrupamentocliente.codigo = agrupamentocliente_cnpjcpfcodigo.codigo
        -- Adicione os JOINs para 'conhecimento' aqui
        LEFT JOIN coleta_composicao
        ON coleta_composicao.grupo = coleta.grupo
        AND coleta_composicao.empresa = coleta.empresa
        AND coleta_composicao.filial = coleta.filial
        AND coleta_composicao.unidade = coleta.unidade
        AND coleta_composicao.diferenciadornumero = coleta.diferenciadornumero
        AND coleta_composicao.serie = coleta.serie
        AND coleta_composicao.numero = coleta.numero
        AND coleta_composicao.tipodocumento IN (6,13)

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
        ON conhecimento.grupo = COALESCE(coleta_composicao.grupo, conhecimento_composicao.grupo)
        AND conhecimento.empresa = COALESCE(coleta_composicao.empresa, conhecimento_composicao.empresa)
        AND conhecimento.filial = COALESCE(coleta_composicao.filialdocumento, conhecimento_composicao.filial)
        AND conhecimento.unidade = COALESCE(coleta_composicao.unidadedocumento, conhecimento_composicao.unidade)
        AND conhecimento.diferenciadornumero = COALESCE(coleta_composicao.diferenciadornumerodocumento, conhecimento_composicao.diferenciadornumero)
        AND conhecimento.serie = COALESCE(coleta_composicao.seriedocumento, conhecimento_composicao.serie)
        AND conhecimento.numero = COALESCE(coleta_composicao.numerodocumento, conhecimento_composicao.numero)

        LEFT JOIN cadastro destinatario_cadastro
        ON destinatario_cadastro.codigo = COALESCE(coleta.destinatario, conhecimento.destinatario)

        WHERE agrupamentocliente.codigo IN (6, 8, 9, 11, 12, 16, 43, 44, 46, 24, 31, 23, 19, 20, 40, 45)
    )
    SELECT
        coletas.grupo
    , coletas.empresa
    , coletas.filial
    , coletas.unidade
    , coletas.diferenciadornumero
    , coletas.serie
    , coletas.numero
    , coletas.dtemissao
    , coletas.dtcoletar
    , coletas.cliente
    , coletas.mercadorias
    , coletas.cnpj_destinatario

    -- Lógica para freetime_coleta
    , CASE WHEN coletas.cod_cliente = 9 THEN freetimelear.freetime_coleta
           WHEN coletas.cod_cliente = 8 AND freetimemaxion_especifico.freetime_coleta IS NOT NULL THEN freetimemaxion_especifico.freetime_coleta
           WHEN coletas.cod_cliente = 8 THEN freetimemaxion_padrao.freetime_coleta
           ELSE freetime_generico_outros.freetime_coleta
           END AS freetime_coleta

    -- Lógica para vlr_hora_coleta
    , CASE WHEN coletas.cod_cliente = 9 THEN freetimelear.vlr_hora_coleta
           WHEN coletas.cod_cliente = 8 AND freetimemaxion_especifico.vlr_hora_coleta IS NOT NULL THEN freetimemaxion_especifico.vlr_hora_coleta
           WHEN coletas.cod_cliente = 8 THEN freetimemaxion_padrao.vlr_hora_coleta
           ELSE freetime_generico_outros.vlr_hora_coleta
           END AS vlr_hora_coleta

    -- Lógica para freetime_descarga
    , CASE WHEN coletas.cod_cliente = 9 THEN freetimelear.freetime_descarga
           WHEN coletas.cod_cliente = 8 AND freetimemaxion_especifico.freetime_descarga IS NOT NULL THEN freetimemaxion_especifico.freetime_descarga
           WHEN coletas.cod_cliente = 8 THEN freetimemaxion_padrao.freetime_descarga
           ELSE freetime_generico_outros.freetime_descarga
           END AS freetime_descarga

    -- Lógica para vlr_hora_descarga
    , CASE WHEN coletas.cod_cliente = 9 THEN freetimelear.vlr_hora_descarga
           WHEN coletas.cod_cliente = 8 AND freetimemaxion_especifico.vlr_hora_descarga IS NOT NULL THEN freetimemaxion_especifico.vlr_hora_descarga
           WHEN coletas.cod_cliente = 8 THEN freetimemaxion_padrao.vlr_hora_descarga
           ELSE freetime_generico_outros.vlr_hora_descarga
           END AS vlr_hora_descarga

    FROM coletas

    LEFT JOIN freetime_origem freetimelear
    ON freetimelear.observacao = coletas.mercadorias
    AND freetimelear.agrupamentocliente = coletas.cod_cliente
    AND coletas.cod_cliente = 9
    AND coletas.dtcoletar BETWEEN freetimelear.dtinicio AND COALESCE(freetimelear.dtfim, CURRENT_TIMESTAMP + INTERVAL '15days')

    LEFT JOIN freetime_origem freetimemaxion_especifico
    ON freetimemaxion_especifico.observacao = coletas.mercadorias
    AND freetimemaxion_especifico.agrupamentocliente = coletas.cod_cliente
    AND coletas.cod_cliente = 8
    AND freetimemaxion_especifico.distingueoperacao = 1
    AND coletas.dtcoletar BETWEEN freetimemaxion_especifico.dtinicio AND COALESCE(freetimemaxion_especifico.dtfim, CURRENT_TIMESTAMP + INTERVAL '15days')
    AND NOT (
        LOWER(TRIM(freetimemaxion_especifico.observacao)) = 'rodas'
        AND coletas.cnpj_destinatario <> '06020318000544' -- SUBSTITUA PELO CNPJ REAL DA VOLKSWAGEN RESENDE (APENAS DÍGITOS)
    )

    LEFT JOIN freetime_origem freetimemaxion_padrao
    ON freetimemaxion_padrao.agrupamentocliente = coletas.cod_cliente
    AND coletas.cod_cliente = 8
    AND freetimemaxion_padrao.distingueoperacao = 2
    AND coletas.dtcoletar BETWEEN freetimemaxion_padrao.dtinicio AND COALESCE(freetimemaxion_padrao.dtfim, CURRENT_TIMESTAMP + INTERVAL '15days')

    LEFT JOIN freetime_origem freetime_generico_outros
    ON freetime_generico_outros.agrupamentocliente = coletas.cod_cliente
    AND coletas.cod_cliente IN (6, 8, 9, 11, 12, 16, 43, 44, 46, 24, 31, 23, 19, 20, 40, 45)
    AND freetime_generico_outros.distingueoperacao = 2
    AND coletas.dtcoletar BETWEEN freetime_generico_outros.dtinicio AND COALESCE(freetime_generico_outros.dtfim, CURRENT_TIMESTAMP + INTERVAL '15days')

    ORDER BY
    coletas.filial, coletas.numero
)

SELECT DISTINCT
 resultado.ignicao
, resultado.motorista
, resultado.frota_cavalo
, resultado.placa_cavalo
, resultado.frota_carreta1
, resultado.placa_carreta1
, resultado.kmtotal
, resultado.percorrido
, resultado.restante
, resultado.progresso
, resultado.posicao_atual
, resultado.previsao_chegada
, resultado.cliente
, resultado.coleta
, UPPER(resultado.nrpedido) as nrpedido
, resultado.mercadorias
, resultado.origem
, resultado.local_coleta
, resultado.destino
, resultado.local_destino
, resultado.janela_coleta

, CASE 
    WHEN resultado.mr_entrega = 1 THEN resultado.chegada_carregamento 
    ELSE COALESCE(resultado.hra_chegada_mr::TIMESTAMP, resultado.chegada_carregamento) 
  END AS chegada_carregamento

, CASE 
    WHEN resultado.mr_entrega = 1 THEN resultado.saida_carregamento 
    ELSE COALESCE(resultado.hra_saida_mr::TIMESTAMP, resultado.saida_carregamento) 
  END AS saida_carregamento

, CASE 
    WHEN resultado.mr_entrega = 1 THEN resultado.saida_carregamento::TIMESTAMP - resultado.chegada_carregamento::TIMESTAMP
    ELSE (COALESCE(resultado.hra_saida_mr::TIMESTAMP, resultado.saida_carregamento) - COALESCE(resultado.hra_chegada_mr::TIMESTAMP, resultado.chegada_carregamento)) 
  END AS tempo_coleta 
 
, resultado.janela_entrega
, CASE WHEN resultado.agendadefinitiva = 1 THEN 'Sim'
       WHEN resultado.agendadefinitiva = 2 THEN 'Não'
  END as agendadefinitiva


, CASE WHEN resultado.mr_entrega = 1 THEN '?' ELSE NULL END AS mr_entregastatus-- 1 = entrega, NULL = normal
, CASE 
    WHEN resultado.mr_entrega = 1 THEN COALESCE(resultado.hra_chegada_mr::TIMESTAMP, resultado.chegada_descarga)
    ELSE resultado.chegada_descarga 
  END AS chegada_descarga

, CASE 
    WHEN resultado.mr_entrega = 1 THEN COALESCE(resultado.hra_saida_mr::TIMESTAMP, resultado.fim_descarga)
    ELSE resultado.fim_descarga 
  END AS fim_descarga

, CASE 
    WHEN resultado.mr_entrega = 1 THEN 
      (COALESCE(resultado.hra_saida_mr::TIMESTAMP, resultado.fim_descarga) - COALESCE(resultado.hra_chegada_mr::TIMESTAMP, resultado.chegada_descarga))
    ELSE 
      (resultado.fim_descarga - resultado.chegada_descarga)
  END AS tempo_descarga

, resultado.ctes
, resultado.nfe
, resultado.volumes
, CASE WHEN resultado.status_viagem IS NULL AND resultado.placa_cavalo IS NOT NULL THEN 'COLETA PROGRAMADA (SAC)'
       ELSE resultado.status_viagem END AS status_viagem
, resultado.situacao_mr
, resultado.atraso_carregamento AS motivoatrasocoleta
, CASE WHEN resultado.chegada_carregamento IS NULL THEN NULL ELSE
       CASE WHEN resultado.dtcoleta >= resultado.chegada_carregamento THEN '?? Dentro da Janela' ELSE '?? Fora da Janela' END 
       END AS pontualidade_janela_coleta
, freetime.freetime_coleta
, freetime.vlr_hora_coleta

,CASE WHEN (EXTRACT(EPOCH FROM (resultado.saida_carregamento - resultado.janela_coleta)) / 3600.0 - EXTRACT(EPOCH FROM freetime.freetime_coleta) / 3600.0) <= 0 THEN 0
       ELSE (EXTRACT(EPOCH FROM (resultado.saida_carregamento - resultado.janela_coleta)) / 3600.0 - EXTRACT(EPOCH FROM freetime.freetime_coleta) / 3600.0) * freetime.vlr_hora_coleta
       END AS hora_parada_coleta_valor      
, (
    ROUND(
        (CASE WHEN (EXTRACT(EPOCH FROM (COALESCE(resultado.hra_saida_mr::TIMESTAMP, resultado.saida_carregamento) - resultado.janela_coleta)) - EXTRACT(EPOCH FROM freetime.freetime_coleta)) <= 0
             THEN 0.0
             ELSE (EXTRACT(EPOCH FROM (COALESCE(resultado.hra_saida_mr::TIMESTAMP, resultado.saida_carregamento) - resultado.janela_coleta)) - EXTRACT(EPOCH FROM freetime.freetime_coleta)) / 3600.0
             END)::NUMERIC, 2
    ) || ' horas'
  ) AS tempo_excedido_coleta
  
       
, resultado.atraso_descarga AS motivoatrasodescarga
, CASE WHEN resultado.chegada_descarga IS NULL THEN NULL ELSE
      CASE WHEN resultado.janela_entrega >= resultado.chegada_descarga THEN '?? Dentro da Janela' ELSE '?? Fora da Janela' END
         END AS pontualidade_janela_entrega
, freetime.freetime_descarga
, freetime.vlr_hora_descarga

, CASE WHEN (EXTRACT(EPOCH FROM (resultado.fim_descarga - resultado.janela_entrega)) / 3600.0 - EXTRACT(EPOCH FROM freetime.freetime_descarga) / 3600.0) <= 0 THEN 0
       ELSE (EXTRACT(EPOCH FROM (resultado.fim_descarga - resultado.janela_entrega)) / 3600.0 - EXTRACT(EPOCH FROM freetime.freetime_descarga) / 3600.0) * freetime.vlr_hora_descarga
       END AS hora_parada_descarga_valor

, (
    ROUND(
        (CASE WHEN (EXTRACT(EPOCH FROM (resultado.fim_descarga - resultado.janela_entrega)) - EXTRACT(EPOCH FROM freetime.freetime_descarga)) <= 0
             THEN 0.0
             ELSE (EXTRACT(EPOCH FROM (resultado.fim_descarga - resultado.janela_entrega)) - EXTRACT(EPOCH FROM freetime.freetime_descarga)) / 3600.0
             END)::NUMERIC, 2
    ) || ' horas'
  ) AS tempo_excedido_descarga,
  
  
-- SEMÁFORO UNIFICADO (COLETA + DESCARGA)
(
    CASE 
        -- nada começou ou não tem freetime cadastrado
        WHEN (
            (resultado.chegada_carregamento IS NULL AND resultado.chegada_descarga IS NULL)
            OR (freetime.freetime_coleta IS NULL AND freetime.freetime_descarga IS NULL) OR COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento) IS NOT NULL OR resultado.fim_descarga IS NOT NULL
        ) 
        THEN NULL
        
        -- lógica da COLETA
        WHEN resultado.chegada_carregamento IS NOT NULL 
             AND freetime.freetime_coleta IS NOT NULL
        THEN (
            CASE 
                WHEN (
                    EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now()) 
                           - resultado.janela_coleta::timestamp)
                    )) / 3600.0
                ) <= 0
                    THEN '?? Freetime Coleta - Atrasado'
                WHEN (
                    EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now()) 
                           - resultado.janela_coleta::timestamp)
                    )) / 3600.0
                ) <= 0.5
                    THEN '?? Freetime Coleta - Verificar'
                WHEN (
                    EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now()) 
                           - resultado.janela_coleta::timestamp)
                    )) / 3600.0
                ) <= 1.5
                    THEN '?? Freetime Coleta - Possível Atraso'
                ELSE '?? Freetime Coleta - No Prazo'
            END
        )

        -- lógica da DESCARGA
        WHEN resultado.chegada_descarga IS NOT NULL 
             AND freetime.freetime_descarga IS NOT NULL
        THEN (
            CASE 
                WHEN (
                    EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now()) - resultado.janela_entrega)
                    )) / 3600.0
                ) <= 0
                    THEN '?? Freetime Descarga - Atrasado'
                WHEN (
                    EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now()) - resultado.janela_entrega)
                    )) / 3600.0
                ) <= 0.5
                    THEN '?? Freetime Descarga - Verificar'
                WHEN (
                    EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now()) - resultado.janela_entrega)
                    )) / 3600.0
                ) <= 1.5
                    THEN '?? Freetime Descarga - Possível Atraso'
                ELSE '?? Freetime Descarga - No Prazo'
            END
        )
    END
) AS semaforo_unificado
,(
    CASE
        -- se não tem chegada ou freetime cadastrado ? NULL
        WHEN (
            (resultado.chegada_carregamento IS NULL AND resultado.chegada_descarga IS NULL)
            OR (freetime.freetime_coleta IS NULL AND freetime.freetime_descarga IS NULL) OR COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento) IS NOT NULL OR resultado.fim_descarga IS NOT NULL
        )
        THEN NULL

         -- COLETA
        WHEN resultado.chegada_carregamento IS NOT NULL
             AND freetime.freetime_coleta IS NOT NULL
        THEN
            (CASE 
                WHEN EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           - resultado.janela_coleta::timestamp)
                    )) >= 0
                THEN
                    LPAD(FLOOR(EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           - resultado.janela_coleta::timestamp)
                    )) / 3600)::text, 2, '0')
                    || ':' ||
                    LPAD(FLOOR((EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           - resultado.janela_coleta::timestamp)
                    )) - FLOOR(EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           - resultado.janela_coleta::timestamp)
                    )) / 3600)*3600)/60)::text, 2, '0')
                ELSE
                    '-' ||
                    LPAD(FLOOR(ABS(EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           -resultado.janela_coleta::timestamp)
                    )) / 3600))::text, 2, '0')
                    || ':' ||
                    LPAD(FLOOR(ABS((EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           - resultado.janela_coleta::timestamp)
                    )) - FLOOR(EXTRACT(EPOCH FROM (
                        freetime.freetime_coleta
                        - (COALESCE(resultado.hra_saida_mr::timestamp, resultado.saida_carregamento::timestamp, now())
                           - resultado.janela_coleta::timestamp)
                    )) / 3600)*3600)/60))::text, 2, '0')
            END)

        -- DESCARGA
        WHEN resultado.chegada_descarga IS NOT NULL
             AND freetime.freetime_descarga IS NOT NULL
        THEN
            (CASE 
                WHEN EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) >= 0
                THEN
                    LPAD(FLOOR(EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) / 3600)::text, 2, '0')
                    || ':' ||
                    LPAD(FLOOR((EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) - FLOOR(EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) / 3600)*3600)/60)::text, 2, '0')
                ELSE
                    '-' ||
                    LPAD(FLOOR(ABS(EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) / 3600))::text, 2, '0')
                    || ':' ||
                    LPAD(FLOOR(ABS((EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) - FLOOR(EXTRACT(EPOCH FROM (
                        freetime.freetime_descarga
                        - (COALESCE(resultado.fim_descarga, now())
                           - resultado.janela_entrega)
                    )) / 3600)*3600)/60))::text, 2, '0')
            END)
    END
) AS tempo_restante_unificado
       
, resultado.dt_status_viagem
, '' AS documentos
, resultado.operacao
, resultado.usuarioemissor
, resultado.tipo
, resultado.coletaagrupada
, resultado.nr_transp
, resultado.filialnome
, resultado.sequencia_cliente
, resultado.tipo_cte


FROM

resultado

LEFT JOIN freetime
ON freetime.grupo = resultado.grupo
AND freetime.empresa = resultado.empresa
AND freetime.filial = resultado.filial
AND freetime.unidade = resultado.unidade
AND freetime.diferenciadornumero = resultado.diferenciadornumero
AND freetime.serie = resultado.serie
AND freetime.numero = resultado.coleta

LEFT JOIN sulista.whatsappcliente
ON sulista.sulista.whatsappcliente.grupo = resultado.grupo
AND sulista.sulista.whatsappcliente.empresa = resultado.empresa
AND sulista.sulista.whatsappcliente.filial = resultado.filial
AND sulista.sulista.whatsappcliente.unidade = resultado.unidade
AND sulista.sulista.whatsappcliente.nrcoleta = resultado.coleta