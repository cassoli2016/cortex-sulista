-- Rodado por Cliente - Detalhamento

WITH kmrodado AS (
    SELECT 
        programacaoembarque.numero || ' - ' || programacaoembarque.diferenciadornumero AS prog
        , 1 AS valida
        , COALESCE(clientepagador.descricao, clientedestinovazio.descricao, clientedestinotrajeto.descricao, 
                   clienteorigemvazio.descricao, clienteorigemtrajeto.descricao) AS cliente 

        , programacaoembarque.kmfretecompra AS km_total_rodado
        , CASE WHEN programacaoembarque.tipo = 2 THEN programacaoembarque.kmfretecompra END AS km_carregado 
        , CASE WHEN programacaoembarque.tipo = 3 THEN programacaoembarque.kmfretecompra END AS km_vazio

        , CASE WHEN programacaoembarque.tipo = 2 AND (cavalo.utilizacaoveiculo = 'LOC' OR cavalo.utilizacaoveiculo = 'TRA') THEN programacaoembarque.kmfretecompra END AS km_carregado_frota
        , CASE WHEN programacaoembarque.tipo = 2 AND (cavalo.utilizacaoveiculo = 'AGR') THEN programacaoembarque.kmfretecompra END AS km_carregado_agregado
        , CASE WHEN programacaoembarque.tipo = 2 AND (cavalo.utilizacaoveiculo = 'TER') THEN programacaoembarque.kmfretecompra END AS km_carregado_terceiro

        , CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'LOC' OR cavalo.utilizacaoveiculo = 'TRA') THEN programacaoembarque.kmfretecompra END AS km_vazio_frota
        , CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'AGR') THEN programacaoembarque.kmfretecompra END AS km_vazio_agregado 
        , CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'TER') THEN programacaoembarque.kmfretecompra END AS km_vazio_terceiro

        , CASE WHEN trajeto.extensao <= 300 THEN 1
               WHEN trajeto.extensao > 300 THEN 2
          END AS filtro_300

    FROM programacaoembarque
    LEFT JOIN trajeto
        ON programacaoembarque.grupo = trajeto.grupo
        AND programacaoembarque.empresa = trajeto.empresa
        AND programacaoembarque.trajeto = trajeto.codigo
    LEFT JOIN coleta
        ON programacaoembarque.grupo = coleta.grupo
        AND programacaoembarque.empresa = coleta.empresa
        AND programacaoembarque.filialdocumentoorigem = coleta.filial
        AND programacaoembarque.unidadedocumentoorigem = coleta.unidade
        AND programacaoembarque.diferenciadornumerodocumentoorigem = coleta.diferenciadornumero
        AND programacaoembarque.numerodocumentoorigem = coleta.numero
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_clientepagador
        ON coleta.cnpjcpfcodigopagadorfrete = agrupamentocliente_cnpjcpfcodigo_clientepagador.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente clientepagador
        ON agrupamentocliente_cnpjcpfcodigo_clientepagador.codigo = clientepagador.codigo
    LEFT JOIN veiculo cavalo
        ON programacaoembarque.veiculo = cavalo.placa
    LEFT JOIN utilizacaoveiculo
        ON cavalo.utilizacaoveiculo = utilizacaoveiculo.codigo

    -- CLIENTE ORIGEM VAZIO
    LEFT JOIN cadastro origemvazio
        ON programacaoembarque.cadastroorigem = origemvazio.codigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_origemvazio
        ON origemvazio.codigo = agrupamentocliente_cnpjcpfcodigo_origemvazio.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente clienteorigemvazio
        ON agrupamentocliente_cnpjcpfcodigo_origemvazio.codigo = clienteorigemvazio.codigo

    -- CLIENTE DESTINO VAZIO
    LEFT JOIN cadastro destinovazio
        ON programacaoembarque.cadastrodestino = destinovazio.codigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_destinovazio
        ON destinovazio.codigo = agrupamentocliente_cnpjcpfcodigo_destinovazio.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente clientedestinovazio
        ON agrupamentocliente_cnpjcpfcodigo_destinovazio.codigo = clientedestinovazio.codigo

    -- ORIGEM TRAJETO
    LEFT JOIN cadastro origemtrajeto
        ON trajeto.cnpjcpfcodigoorigem = origemtrajeto.codigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_origemtrajeto
        ON origemtrajeto.codigo = agrupamentocliente_cnpjcpfcodigo_origemtrajeto.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente clienteorigemtrajeto
        ON agrupamentocliente_cnpjcpfcodigo_origemtrajeto.codigo = clienteorigemtrajeto.codigo

    -- DESTINO TRAJETO
    LEFT JOIN cadastro destinotrajeto
        ON trajeto.cnpjcpfcodigodestino = destinotrajeto.codigo
    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_destinotrajeto
        ON destinotrajeto.codigo = agrupamentocliente_cnpjcpfcodigo_destinotrajeto.cnpjcpfcodigo
    LEFT JOIN agrupamentocliente clientedestinotrajeto
        ON agrupamentocliente_cnpjcpfcodigo_destinotrajeto.codigo = clientedestinotrajeto.codigo

    WHERE programacaoembarque.dtcancelamento IS NULL 
        AND programacaoembarque.semaforo = 1
        AND programacaoembarque.numero < 1000000
        AND programacaoembarque.dtemissao::date BETWEEN '2023-04-01' AND CURRENT_DATE
)

-- ################################### -- R E S U L T A D O -- ################################### --
SELECT 
    kmrodado.cliente
    -- TOTAL GERAL
    , COALESCE(SUM(kmrodado.km_carregado), 0) AS km_carregado
    , COALESCE(SUM(kmrodado.km_vazio), 0) AS km_vazio
    , COALESCE(SUM(kmrodado.km_carregado), 0) + COALESCE(SUM(kmrodado.km_vazio), 0) AS km_total
    , COALESCE(ROUND((SUM(kmrodado.km_vazio) / NULLIF(SUM(kmrodado.km_carregado) + SUM(kmrodado.km_vazio), 0)) * 100, 2), 0) AS percentual_vazio

    -- DETALHAMENTO FROTA
    , COALESCE(SUM(kmrodado.km_carregado_frota), 0) AS km_carregado_frota
    , COALESCE(SUM(kmrodado.km_vazio_frota), 0) AS km_vazio_frota 
    , COALESCE(SUM(kmrodado.km_carregado_frota), 0) + COALESCE(SUM(kmrodado.km_vazio_frota), 0) AS km_total_frota 
    , COALESCE(ROUND((SUM(kmrodado.km_vazio_frota) / NULLIF(SUM(kmrodado.km_carregado_frota) + SUM(kmrodado.km_vazio_frota), 0)) * 100, 2), 0) AS percentual_vazio_frota

    -- DETALHAMENTO AGREGADO
    , COALESCE(SUM(kmrodado.km_carregado_agregado), 0) AS km_carregado_agregado
    , COALESCE(SUM(kmrodado.km_vazio_agregado), 0) AS km_vazio_agregado
    , COALESCE(SUM(kmrodado.km_carregado_agregado), 0) + COALESCE(SUM(kmrodado.km_vazio_agregado), 0) AS km_total_agregado
    , COALESCE(ROUND((SUM(kmrodado.km_vazio_agregado) / NULLIF(SUM(kmrodado.km_carregado_agregado) + SUM(kmrodado.km_vazio_agregado), 0)) * 100, 2), 0) AS percentual_vazio_agregado 

    -- DETALHAMENTO TERCEIRO
    , COALESCE(SUM(kmrodado.km_carregado_terceiro), 0) AS km_carregado_terceiro
    , COALESCE(SUM(kmrodado.km_vazio_terceiro), 0) AS km_vazio_terceiro
    , COALESCE(SUM(kmrodado.km_carregado_terceiro), 0) + COALESCE(SUM(kmrodado.km_vazio_terceiro), 0) AS km_total_terceiro
    , COALESCE(ROUND((SUM(kmrodado.km_vazio_terceiro) / NULLIF(SUM(kmrodado.km_carregado_terceiro) + SUM(kmrodado.km_vazio_terceiro), 0)) * 100, 2), 0) AS percentual_vazio_terceiro

FROM kmrodado 
LEFT JOIN agrupamentocliente
    ON agrupamentocliente.descricao = kmrodado.cliente
WHERE kmrodado.valida = 1
    AND kmrodado.cliente NOT IN ('REPOSICIONAMENTO')
GROUP BY 
    kmrodado.cliente
HAVING 
    COALESCE(SUM(kmrodado.km_carregado), 0) <> 0 
    AND COALESCE(SUM(kmrodado.km_vazio), 0) <> 0
ORDER BY 
    percentual_vazio ASC;