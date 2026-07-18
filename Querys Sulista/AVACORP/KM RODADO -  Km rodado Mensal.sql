-- KM rodado Mensal - Lifetime

WITH kmrodado AS (
    SELECT 
        programacaoembarque.numero || ' - ' || programacaoembarque.diferenciadornumero AS prog
        , 1 AS valida
        , programacaoembarque.dtemissao
        , COALESCE(clientepagador.descricao, clientedestinovazio.descricao, clientedestinotrajeto.descricao, 
                   clienteorigemvazio.descricao, clienteorigemtrajeto.descricao) AS cliente 
        , trajeto.codigo || ' - ' || trajeto.descricao AS trajeto
        , programacaoembarque.cidadeorigem || ' > ' || programacaoembarque.cidadedestino AS rota
        , CASE WHEN programacaoembarque.tipo = 3 THEN programacaoembarque.kmfretecompra END AS km_vazio
        , CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'LOC' OR cavalo.utilizacaoveiculo = 'TRA') THEN programacaoembarque.kmfretecompra END AS km_vazio_frota
        , CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'AGR') THEN programacaoembarque.kmfretecompra END AS km_vazio_agregado
        , CASE WHEN programacaoembarque.tipo = 3 AND (cavalo.utilizacaoveiculo = 'AGR') THEN programacaoembarque.valorfretecompra END AS valor_vazio_agregado
        , programacaoembarque.numero AS numeroviagem
        , CASE WHEN trajeto.extensao <= 300 THEN 1
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
    WHERE programacaoembarque.dtcancelamento IS NULL 
        AND programacaoembarque.semaforo = 1
        AND programacaoembarque.numero < 1000000
        AND programacaoembarque.dtemissao::date BETWEEN '2023-06-01' AND current_date
), 
resultado AS (
    SELECT 
        EXTRACT(MONTH FROM kmrodado.dtemissao) AS mes_numero,
        EXTRACT(YEAR FROM kmrodado.dtemissao) AS ano,
        COALESCE(SUM(kmrodado.km_vazio), 0) AS kmvazio,
        SUM(kmrodado.km_vazio_agregado) AS km_vazio_agregado,
        SUM(kmrodado.valor_vazio_agregado) AS valor_vazio_agregado,
        SUM(kmrodado.km_vazio_frota) AS km_vazio_frota,
        SUM(kmrodado.km_vazio_frota) * 3.7 AS valor_vazio_frota
    FROM kmrodado 
    LEFT JOIN agrupamentocliente
        ON agrupamentocliente.descricao = kmrodado.cliente
    WHERE kmrodado.valida = 1
    GROUP BY 
        EXTRACT(YEAR FROM kmrodado.dtemissao),
        EXTRACT(MONTH FROM kmrodado.dtemissao)
    HAVING 
        COALESCE(SUM(kmrodado.km_vazio), 0) > 0
)

SELECT 
    CASE mes_numero
        WHEN 1 THEN 'Janeiro' WHEN 2 THEN 'Fevereiro' WHEN 3 THEN 'Março'
        WHEN 4 THEN 'Abril' WHEN 5 THEN 'Maio' WHEN 6 THEN 'Junho'
        WHEN 7 THEN 'Julho' WHEN 8 THEN 'Agosto' WHEN 9 THEN 'Setembro'
        WHEN 10 THEN 'Outubro' WHEN 11 THEN 'Novembro' WHEN 12 THEN 'Dezembro'
    END || '/' || ano AS mes_ano,
    COALESCE(valor_vazio_agregado, 0) AS valor_vazio_agregado,
    COALESCE(valor_vazio_frota, 0) AS valor_vazio_frota,
    COALESCE(valor_vazio_agregado, 0) + COALESCE(valor_vazio_frota, 0) AS valor_vazio_total
FROM resultado
ORDER BY 
    ano ASC, 
    mes_numero ASC;