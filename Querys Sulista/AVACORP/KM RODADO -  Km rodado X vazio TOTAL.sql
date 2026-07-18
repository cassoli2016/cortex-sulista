-- Km rodado x vazio - TOTAL

WITH kmrodado AS (
    SELECT 
        programacaoembarque.numero || ' - ' || programacaoembarque.diferenciadornumero AS prog
        , 1 AS valida
        , COALESCE(clientepagador.descricao, clientedestinovazio.descricao, clientedestinotrajeto.descricao, 
                   clienteorigemvazio.descricao, clienteorigemtrajeto.descricao) AS cliente 
        , CASE WHEN programacaoembarque.tipo = 2 THEN programacaoembarque.kmfretecompra END AS km_carregado 
        , CASE WHEN programacaoembarque.tipo = 3 THEN programacaoembarque.kmfretecompra END AS km_vazio
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

    WHERE programacaoembarque.dtcancelamento IS NULL 
        AND programacaoembarque.semaforo = 1
        AND programacaoembarque.numero < 1000000
        AND programacaoembarque.dtemissao::date BETWEEN '2026-04-01' AND '2026-07-17'
),

retorno_agrupado AS (
    SELECT 
        COALESCE(SUM(kmrodado.km_carregado), 0) AS total_km_carregado,
        COALESCE(SUM(kmrodado.km_vazio), 0) AS total_km_vazio,
        COALESCE(SUM(kmrodado.km_carregado), 0) + COALESCE(SUM(kmrodado.km_vazio), 0) AS km_total_geral
    FROM kmrodado
    LEFT JOIN agrupamentocliente
        ON agrupamentocliente.descricao = kmrodado.cliente
    WHERE kmrodado.valida = 1
)

-- ################################### -- R E S U L T A D O -- ################################### --
SELECT 
    'Carregado' AS status_viagem,
    total_km_carregado AS km_rodado,
    ROUND((total_km_carregado / NULLIF(km_total_geral, 0)) * 100, 2) AS percentual
FROM retorno_agrupado

UNION ALL

SELECT 
    'Vazio' AS status_viagem,
    total_km_vazio AS km_rodado,
    ROUND((total_km_vazio / NULLIF(km_total_geral, 0)) * 100, 2) AS percentual
FROM retorno_agrupado;