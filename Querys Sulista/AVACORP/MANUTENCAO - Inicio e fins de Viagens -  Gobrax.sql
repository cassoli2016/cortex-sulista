--  Inicio e fim de viagens motoristas - gobrax

SELECT
    id_registro,
    CASE WHEN origem = 'CARGA INICIAL' THEN 'TRUCKS CONTROL' ELSE origem END as origem,
    placa_veiculo AS placa,
    CASE WHEN veiculo.utilizacaoveiculo = 'LOC' THEN 'LOCADO'
         WHEN veiculo.utilizacaoveiculo = 'TRA' THEN 'FROTA'
         WHEN veiculo.utilizacaoveiculo = 'AGR' THEN 'AGREGADO'
         WHEN veiculo.utilizacaoveiculo = 'TER' THEN 'TERCEIRO'
    END AS utilizacaoveiculo,
    cpf_motorista,
    nome_motorista AS motorista,
    TO_CHAR(data_inicio, 'DD/MM/YYYY HH24:MI:SS') AS inicio_viagem,
    TO_CHAR(data_fim, 'DD/MM/YYYY HH24:MI:SS') AS fim_viagem,
    
    CASE 
        WHEN data_fim IS NULL THEN 'Em Andamento'
        ELSE 'Finalizada'
    END AS status_operacao,
    CASE 
        WHEN enviado_inicio = TRUE AND (data_fim IS NULL OR enviado_fim = TRUE) THEN '?? Sincronizado'

        WHEN log_api_inicio LIKE '%Motorista não cadastrado%' OR log_api_inicio LIKE '%CPF inválido%' THEN '?? Erro: Motorista/CPF sem Cadastro (Code 2)'
        WHEN log_api_inicio LIKE '%Veículo não identificado%' THEN '?? Erro: Veículo não cadastrado (Code 1)'
        WHEN log_api_inicio LIKE '%Acesso nao permitido%' THEN '?? Erro: Acesso Negado (Code 71)'
        WHEN log_api_fim LIKE '%Status 500%' OR log_api_inicio LIKE '%Status 500%'THEN '? Aguardando Integração'
        WHEN enviado_inicio = FALSE AND log_api_inicio IS NULL THEN '? Aguardando Envio'
        ELSE '?? Verificar Logs'
    END AS status_integracao,
    log_api_inicio AS retorno_api_inicio,
    log_api_fim AS retorno_api_fim,
    TO_CHAR(data_ultima_atualizacao, 'DD/MM/YYYY HH24:MI') AS ultima_sincronizacao,
    TO_CHAR(data_ultima_integracao, 'DD/MM/YYYY HH24:MI') AS ultima_integracao,
    payload_envio as requisicao,
    CASE WHEN  data_fim IS NOT NULL AND data_fim <= data_inicio + INTERVAL '1 hour' THEN '??' ELSE '??' END as validacao,
    CASE WHEN (SELECT departamento FROM usuario WHERE codigo = 117) = 'INT. DE DADOS' THEN '???'
    ELSE NULL END AS departamento,
    '' AS place_holder
FROM 
    sulista.integracao_gobrax
    
LEFT JOIN veiculo
on sulista.integracao_gobrax.placa_veiculo = veiculo.placa

ORDER BY COALESCE(data_fim, data_inicio) DESC;