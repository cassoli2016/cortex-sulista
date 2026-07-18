-- MONITORAMENTO DE COLETAS // CST00000972400079520240430080455430305

SELECT 
    coleta.grupo 
    ,coleta.empresa 
    ,coleta.unidade 
    ,coleta.diferenciadornumero 
    ,coleta.serie 
    ,coleta.numero
    ,coleta.numerofatura AS fatura_pedido_dt
    ,coleta.filial
    ,CASE WHEN coleta.situacao = 1 THEN 'Aguardando Confirmação'
          WHEN coleta.situacao = 2 THEN 'Inclusa'
          WHEN coleta.situacao = 3 THEN 'Associado ao Veículo'
          WHEN coleta.situacao = 4 THEN 'Passado para o Veículo'
          WHEN coleta.situacao = 5 THEN 'Realizada' 
          WHEN coleta.situacao = 6 THEN 'Finalizada'
          WHEN coleta.situacao = 7 THEN 'Conhecimento Emitido'
          WHEN coleta.situacao = 8 THEN 'Cancelado'
          WHEN coleta.situacao = 9 THEN 'Bloqueado'
          ELSE '' END AS situacao
    ,CASE WHEN ((CAST(EXTRACT(EPOCH FROM coleta.dtcoletar) AS INTEGER) - CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo') AS INTEGER))/60/60) < 0 THEN '0 dia 0 hora' 
          ELSE (SELECT * FROM avacorpi.fnc_converte_interval(coleta.dtcoletar::TIMESTAMP - CURRENT_TIMESTAMP::TIMESTAMP))::JSON->>'diahoras' END AS tempo_coleta
    ,CASE WHEN coleta.situacao = 7 THEN -1
          WHEN (CAST(EXTRACT(EPOCH FROM coleta.dtcoletar) AS INTEGER) - CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo') AS INTEGER))/60/60 <= 0 THEN 0 
          ELSE (CAST(EXTRACT(EPOCH FROM coleta.dtcoletar) AS INTEGER) - CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo') AS INTEGER))/60/60 END AS tempo_decimal
    ,coleta.dtcoletar
    ,coleta.dtprevisaochegadaviagem AS dtentrega
    ,remetente.nomefantasia AS remetente
    ,coleta.origem || '/' || coleta.uforigem AS origem
    ,coleta.destino || '/' || coleta.ufdestino AS destino
    ,recebedor.nomefantasia AS recebedor
    ,CASE WHEN cavalo.tipofrota = 1 THEN 'Própria'
          WHEN cavalo.tipofrota = 2 THEN 'Terceiro'
          WHEN cavalo.tipofrota = 3 THEN 'Agregado'
          ELSE '' END AS tipofrota
    ,COALESCE(cavalo.numerofrota, cavalo.placa) AS frota_cavalo
    ,COALESCE(carreta.numerofrota, carreta.placa) AS frota_carreta
    ,motorista.razaosocial AS motorista
    ,tipoveiculo.descricao AS tipoveiculo
    ,pagador.descricao AS cliente
    ,ultima_situacao.situacao AS situacao_veiculo
    ,cavalo.placa AS cavalo
    ,carreta.placa AS carreta
    ,trajeto.codigo || ' - ' || trajeto.descricao AS desctrajeto
    ,ultima_ocorrencia_coleta.ocorrencia || ' - ' || ultima_ocorrencia_coleta.descricao AS ultima_ocorrencia_coleta
    ,coleta.dtinc
    ,filial.apelido AS filial_apelido
    ,veiculo_posicao.latituderastreadora AS latitudecavalo
    ,veiculo_posicao.longituderastreadora AS longitudecavalo
    ,veiculo_posicao.descricaoposicao AS posicaocavalo
    ,trajeto.codigo AS codtrajeto
    ,coleta.latitudeorigem
    ,coleta.longitudeorigem
    ,coleta.latitudedestino
    ,coleta.longitudedestino
    ,tipofrete.descricao AS operacao
    ,CASE WHEN pagador.descricao = 'WHIRLPOOL' AND infolog.dtocorrencia IS NULL THEN '?'
          WHEN pagador.descricao = 'WHIRLPOOL' AND infolog.dtocorrencia IS NOT NULL AND infolog.observacao IS NOT NULL THEN '? ' || infolog.observacao
          ELSE '' END AS infolog

FROM coleta

LEFT JOIN coleta_ocorrencia infolog
    ON coleta.grupo = infolog.grupo
    AND coleta.empresa = infolog.empresa
    AND coleta.filial = infolog.filial
    AND coleta.unidade = infolog.unidade
    AND coleta.diferenciadornumero = infolog.diferenciadornumero
    AND coleta.numero = infolog.numero
    AND infolog.ocorrencia = 406

LEFT JOIN tipofrete
    ON coleta.tipofrete = tipofrete.codigo
    AND coleta.grupo = tipofrete.grupo
    AND coleta.empresa = tipofrete.empresa

LEFT JOIN LATERAL (
    SELECT
        coleta_ocorrencia.grupo
        ,coleta_ocorrencia.empresa
        ,coleta_ocorrencia.ocorrencia
        ,ocorrencia.descricao
    FROM coleta_ocorrencia
    LEFT JOIN ocorrencia
        ON coleta_ocorrencia.ocorrencia = ocorrencia.codigo
    WHERE
        coleta.grupo = coleta_ocorrencia.grupo
        AND coleta.empresa = coleta_ocorrencia.empresa
        AND coleta.filial = coleta_ocorrencia.filial
        AND coleta.unidade = coleta_ocorrencia.unidade
        AND coleta.diferenciadornumero = coleta_ocorrencia.diferenciadornumero
        AND coleta.numero = coleta_ocorrencia.numero
    ORDER BY
        coleta_ocorrencia.dtocorrencia DESC 
        ,coleta_ocorrencia.dtinc DESC
    LIMIT 1
) AS ultima_ocorrencia_coleta ON TRUE

LEFT JOIN veiculo cavalo
    ON coleta.veiculo = cavalo.placa

LEFT JOIN tipoveiculo
    ON cavalo.tipoveiculo = tipoveiculo.codigo

LEFT JOIN veiculo_posicao 
    ON cavalo.placa = veiculo_posicao.veiculo
    AND veiculo_posicao.ultimaposicao = 1

LEFT JOIN veiculo carreta
    ON coleta.carreta1 = carreta.placa

LEFT JOIN veiculo carreta1
    ON carreta1.placa = coleta.carreta1

LEFT JOIN veiculo carreta2
    ON carreta2.placa = coleta.carreta2

LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_pagador
    ON coleta.cnpjcpfcodigopagadorfrete = agrupamentocliente_pagador.cnpjcpfcodigo

LEFT JOIN agrupamentocliente pagador
    ON agrupamentocliente_pagador.codigo = pagador.codigo

LEFT JOIN cadastro remetente
    ON coleta.remetente = remetente.codigo

LEFT JOIN cadastro recebedor
    ON coleta.recebedor = recebedor.codigo

LEFT JOIN trajeto
    ON coleta.grupo = trajeto.grupo
    AND coleta.empresa = trajeto.empresa
    AND coleta.trajeto = trajeto.codigo

LEFT JOIN filial
    ON coleta.filial = filial.codigo

LEFT JOIN cadastro motorista
    ON motorista.codigo = coleta.motorista

LEFT JOIN LATERAL (
    SELECT
        veiculo_carregamento.grupo
        ,veiculo_carregamento.empresa
        ,veiculo_carregamento.veiculo
        ,CASE WHEN veiculo_carregamento.situacao = 1 THEN 'Aguardando'
              WHEN veiculo_carregamento.situacao = 2 THEN 'Autorizado'
              WHEN veiculo_carregamento.situacao = 3 THEN 'Carregando'
              WHEN veiculo_carregamento.situacao = 4 THEN 'Chegada com Descarregamento'
              WHEN veiculo_carregamento.situacao = 5 THEN 'Carregado'
              WHEN veiculo_carregamento.situacao = 6 THEN 'Descarregado'
              WHEN veiculo_carregamento.situacao = 7 THEN 'Liberado'
              WHEN veiculo_carregamento.situacao = 8 THEN 'Divergência'
              WHEN veiculo_carregamento.situacao = 9 THEN 'Cancelada'
              WHEN veiculo_carregamento.situacao = 10 THEN 'Em Trânsito'
              WHEN veiculo_carregamento.situacao = 11 THEN 'Rodou Vazio (Saída)'
              WHEN veiculo_carregamento.situacao = 12 THEN 'Chegada s/ Descarregamento'
              WHEN veiculo_carregamento.situacao = 13 THEN 'Saída s/ Descarregamento'
              WHEN veiculo_carregamento.situacao = 14 THEN 'Troca de Veículo/Motorista'
              WHEN veiculo_carregamento.situacao = 15 THEN 'Saída com Descarregamento'
              WHEN veiculo_carregamento.situacao = 16 THEN 'Rodou Vazio Chegada' END AS situacao
    FROM veiculo_carregamento
    WHERE
        veiculo_carregamento.veiculo = cavalo.placa 
    ORDER BY
        veiculo_carregamento.dt DESC 
        ,veiculo_carregamento.dtinc DESC
    LIMIT 1
) AS ultima_situacao ON TRUE

WHERE 
    coleta.dtcoletar::DATE BETWEEN '2026-07-17' AND '2026-07-17' 
    AND coleta.dtcancelamento IS NULL 
    AND coleta.dtcoletar IS NOT NULL
ORDER BY 
    coleta.dtcoletar DESC;