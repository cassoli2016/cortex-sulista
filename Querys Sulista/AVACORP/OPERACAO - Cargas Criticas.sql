-- CARGAS CRITICAS

WITH critica AS (
    SELECT DISTINCT
        coleta.numero AS coleta,
        CASE WHEN filial.apelido = 'FIL - S.B. DO CAMPO' THEN 'SBC'
             WHEN filial.apelido = 'FIL - S.J. PINHAIS' THEN 'SJP'
             WHEN filial.apelido = 'FIL - SBC CD' THEN 'SBC CD'
             WHEN filial.apelido = 'FIL - JOINVILLE' THEN 'JOI'
             WHEN filial.apelido = 'FIL - PORTO ALEGRE' THEN 'POA'
             WHEN filial.apelido = 'FIL - CRUZEIRO' THEN 'CRU'
             WHEN filial.apelido = 'FIL - MTZ' THEN 'MTZ'
             WHEN filial.apelido = 'FIL - POUSO ALEGRE' THEN 'PA'
             WHEN filial.apelido = 'FIL - RESENDE' THEN 'RES' END AS filial,
        agrupamentocliente.descricao AS cliente,
        coleta_ocorrencia.dtinc,
        veiculo.numerofrota,
        CASE WHEN coleta_ocorrencia.observacao IS NULL THEN UPPER(coleta_ocorrencia.observacaocliente) 
             ELSE UPPER(coleta_ocorrencia.observacao) END AS observacao,
        COALESCE(remetente.nomefantasia, remetente_trajeto.nomefantasia) AS remetente,
        COALESCE(destinatario.nomefantasia, destinatario_trajeto.nomefantasia) AS destinatario,
        usuario.loginusuario,
        coleta.trajeto,
        transporte.numero AS numero_transporte,
        transporte.situacao AS situacao_transporte,
        transporte.dtcancelamento

    FROM coleta_ocorrencia

    LEFT JOIN coleta 
        ON coleta_ocorrencia.grupo = coleta.grupo
        AND coleta_ocorrencia.empresa = coleta.empresa
        AND coleta_ocorrencia.filial = coleta.filial
        AND coleta_ocorrencia.unidade = coleta.unidade 
        AND coleta_ocorrencia.diferenciadornumero = coleta.diferenciadornumero 
        AND coleta_ocorrencia.serie = coleta.serie 
        AND coleta_ocorrencia.numero = coleta.numero 

    LEFT JOIN coleta_composicao 
        ON coleta_composicao.grupo = coleta.grupo
        AND coleta_composicao.empresa = coleta.empresa
        AND coleta_composicao.filial = coleta.filial
        AND coleta_composicao.unidade = coleta.unidade 
        AND coleta_composicao.diferenciadornumero = coleta.diferenciadornumero
        AND coleta_composicao.serie = coleta.serie
        AND coleta_composicao.numero = coleta.numero
        AND coleta_composicao.tipodocumento IN (6,13)

    LEFT JOIN filial
        ON coleta.grupo = filial.grupo
        AND coleta.empresa = filial.empresa
        AND coleta.filial = filial.codigo

    LEFT JOIN agrupamentocliente_cnpjcpfcodigo
        ON coleta.grupo = agrupamentocliente_cnpjcpfcodigo.grupo
        AND coleta.empresa = agrupamentocliente_cnpjcpfcodigo.empresa
        AND coleta.cnpjcpfcodigopagadorfrete = agrupamentocliente_cnpjcpfcodigo.cnpjcpfcodigo

    LEFT JOIN agrupamentocliente
        ON agrupamentocliente_cnpjcpfcodigo.grupo = agrupamentocliente.grupo
        AND agrupamentocliente_cnpjcpfcodigo.empresa = agrupamentocliente.empresa
        AND agrupamentocliente_cnpjcpfcodigo.codigo = agrupamentocliente.codigo

    LEFT JOIN conhecimento_composicao
        ON conhecimento_composicao.tipodocumento = 27
        AND conhecimento_composicao.grupo = coleta.grupo
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

    LEFT JOIN manifesto_composicao
        ON manifesto_composicao.grupo = conhecimento.grupo
        AND manifesto_composicao.empresa = conhecimento.empresa
        AND manifesto_composicao.filialdocumento = conhecimento.filial
        AND manifesto_composicao.unidadedocumento = conhecimento.unidade
        AND manifesto_composicao.diferenciadornumerodocumento = conhecimento.diferenciadornumero
        AND CASE WHEN conhecimento.serie IS NOT NULL THEN manifesto_composicao.seriedocumento = conhecimento.serie 
                 ELSE TRUE END
        AND manifesto_composicao.numerodocumento = conhecimento.numero
        AND manifesto_composicao.tipodocumento = conhecimento.tipodocumento

    LEFT JOIN manifesto
        ON manifesto.grupo = manifesto_composicao.grupo
        AND manifesto.empresa = manifesto_composicao.empresa 
        AND manifesto.filial = manifesto_composicao.filial 
        AND manifesto.unidade = manifesto_composicao.unidade 
        AND manifesto.diferenciadornumero = manifesto_composicao.diferenciadornumero 
        AND manifesto.serie = manifesto_composicao.serie 
        AND manifesto.numero = manifesto_composicao.numero 

    LEFT JOIN transporte_manifesto
        ON transporte_manifesto.grupo = manifesto_composicao.grupo 
        AND transporte_manifesto.empresa = manifesto_composicao.empresa 
        AND transporte_manifesto.filialdocumento = manifesto_composicao.filial
        AND transporte_manifesto.unidadedocumento = manifesto_composicao.unidade 
        AND transporte_manifesto.diferenciadornumerodocumento = manifesto_composicao.diferenciadornumero 
        AND transporte_manifesto.seriedocumento = manifesto_composicao.serie
        AND transporte_manifesto.numerodocumento = manifesto_composicao.numero

    LEFT JOIN transporte
        ON transporte.grupo = transporte_manifesto.grupo 
        AND transporte.empresa = transporte_manifesto.empresa 
        AND transporte.diferenciadornumero = transporte_manifesto.diferenciadornumero 
        AND transporte.numero = transporte_manifesto.numero

    LEFT JOIN trajeto
        ON trajeto.grupo = transporte.grupo
        AND trajeto.empresa = transporte.empresa
        AND trajeto.codigo = transporte.trajeto

    LEFT JOIN cadastro remetente_trajeto
        ON trajeto.cnpjcpfcodigoorigem = remetente_trajeto.codigo

    LEFT JOIN cadastro destinatario_trajeto
        ON trajeto.cnpjcpfcodigodestino = destinatario_trajeto.codigo

    LEFT JOIN cadastro remetente
        ON coleta.remetente = remetente.codigo

    LEFT JOIN cadastro destinatario
        ON coleta.destinatario = destinatario.codigo

    LEFT JOIN veiculo
        ON coleta.veiculo = veiculo.placa

    LEFT JOIN usuario
        ON coleta_ocorrencia.usuariodigitacao = usuario.codigo

    WHERE coleta_ocorrencia.ocorrencia = 261 
    AND coleta_ocorrencia.dtinc >= now() - interval '72 hours'
    AND veiculo.placa IS NOT NULL
    AND transporte.situacao <> 3
)
SELECT 
    coleta,
    filial,
    cliente,
    dtinc,
    numerofrota,
    observacao,
    remetente,
    destinatario,
    loginusuario,
    trajeto,
    numero_transporte,
    situacao_transporte,
    dtcancelamento
FROM critica
ORDER BY dtinc DESC;