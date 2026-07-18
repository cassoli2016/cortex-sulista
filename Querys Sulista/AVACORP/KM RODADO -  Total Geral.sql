-- Total geral agrupado

WITH kmrodado AS
(
    SELECT 
      programacaoembarque.numero,
      programacaoembarque.diferenciadornumero,
      programacaoembarque.dtemissao,

      COALESCE(
        clientepagador.codigo,
        clientedestinovazio.codigo,
        clientedestinotrajeto.codigo,
        clienteorigemvazio.codigo,
        clienteorigemtrajeto.codigo
      ) AS cliente,

      programacaoembarque.kmfretecompra AS km_total_rodado,

      CASE WHEN programacaoembarque.tipo = 2 THEN programacaoembarque.kmfretecompra END AS km_carregado,
      CASE WHEN programacaoembarque.tipo = 3 THEN programacaoembarque.kmfretecompra END AS km_vazio,

      CASE 
        WHEN programacaoembarque.tipo = 2
        AND (utilizacaoveiculo.descricao ILIKE '%FROTA%' 
          OR utilizacaoveiculo.descricao ILIKE '%PROPRIO%' 
          OR utilizacaoveiculo.descricao ILIKE '%LOCA%')
        THEN programacaoembarque.kmfretecompra
      END AS km_carregado_frota,

      CASE 
        WHEN programacaoembarque.tipo = 2
        AND (utilizacaoveiculo.descricao ILIKE '%AGREGADO%' 
          OR utilizacaoveiculo.descricao ILIKE '%AGR%')
        THEN programacaoembarque.kmfretecompra
      END AS km_carregado_agregado,

      CASE 
        WHEN programacaoembarque.tipo = 2
        AND (utilizacaoveiculo.descricao ILIKE '%TERCEIRO%' 
          OR utilizacaoveiculo.descricao ILIKE '%TERC%')
        THEN programacaoembarque.kmfretecompra
      END AS km_carregado_terceiro,

      CASE 
        WHEN programacaoembarque.tipo = 3
        AND (utilizacaoveiculo.descricao ILIKE '%FROTA%' 
          OR utilizacaoveiculo.descricao ILIKE '%PROPRIO%' 
          OR utilizacaoveiculo.descricao ILIKE '%LOCA%')
        THEN programacaoembarque.kmfretecompra
      END AS km_vazio_frota,

      CASE 
        WHEN programacaoembarque.tipo = 3
        AND (utilizacaoveiculo.descricao ILIKE '%AGREGADO%' 
          OR utilizacaoveiculo.descricao ILIKE '%AGR%')
        THEN programacaoembarque.kmfretecompra
      END AS km_vazio_agregado,

      CASE 
        WHEN programacaoembarque.tipo = 3
        AND (utilizacaoveiculo.descricao ILIKE '%TERCEIRO%' 
          OR utilizacaoveiculo.descricao ILIKE '%TERC%')
        THEN programacaoembarque.kmfretecompra
      END AS km_vazio_terceiro,

      CASE 
        WHEN utilizacaoveiculo.descricao ILIKE '%FROTA%' 
          OR utilizacaoveiculo.descricao ILIKE '%PROPRIO%' 
          OR utilizacaoveiculo.descricao ILIKE '%LOCA%'
        THEN programacaoembarque.kmfretecompra ELSE 0
      END AS km_total_frota,

      CASE 
        WHEN utilizacaoveiculo.descricao ILIKE '%AGREGADO%' 
          OR utilizacaoveiculo.descricao ILIKE '%AGR%'
        THEN programacaoembarque.kmfretecompra ELSE 0
      END AS km_total_agregado,

      CASE 
        WHEN utilizacaoveiculo.descricao ILIKE '%TERCEIRO%' 
          OR utilizacaoveiculo.descricao ILIKE '%TERC%'
        THEN programacaoembarque.kmfretecompra ELSE 0
      END AS km_total_terceiro

    FROM programacaoembarque

    LEFT JOIN programacaoembarque_composicao
      ON programacaoembarque.numero = programacaoembarque_composicao.numero
      AND programacaoembarque.empresa = programacaoembarque_composicao.empresa
      AND programacaoembarque.diferenciadornumero = programacaoembarque_composicao.diferenciadornumero

    LEFT JOIN conhecimento
      ON programacaoembarque_composicao.numerodocumento = conhecimento.numero
      AND programacaoembarque_composicao.filialdocumento = conhecimento.filial
      AND programacaoembarque_composicao.seriedocumento = conhecimento.serie

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

    LEFT JOIN cadastro origemvazio
      ON programacaoembarque.cadastroorigem = origemvazio.codigo

    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_origemvazio
      ON origemvazio.codigo = agrupamentocliente_cnpjcpfcodigo_origemvazio.cnpjcpfcodigo

    LEFT JOIN agrupamentocliente clienteorigemvazio
      ON agrupamentocliente_cnpjcpfcodigo_origemvazio.codigo = clienteorigemvazio.codigo

    LEFT JOIN cadastro destinovazio
      ON programacaoembarque.cadastrodestino = destinovazio.codigo

    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_destinovazio
      ON destinovazio.codigo = agrupamentocliente_cnpjcpfcodigo_destinovazio.cnpjcpfcodigo

    LEFT JOIN agrupamentocliente clientedestinovazio
      ON agrupamentocliente_cnpjcpfcodigo_destinovazio.codigo = clientedestinovazio.codigo

    LEFT JOIN cadastro origemtrajeto
      ON trajeto.cnpjcpfcodigoorigem = origemtrajeto.codigo

    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_origemtrajeto
      ON origemtrajeto.codigo = agrupamentocliente_cnpjcpfcodigo_origemtrajeto.cnpjcpfcodigo

    LEFT JOIN agrupamentocliente clienteorigemtrajeto
      ON agrupamentocliente_cnpjcpfcodigo_origemtrajeto.codigo = clienteorigemtrajeto.codigo

    LEFT JOIN cadastro destinotrajeto
      ON trajeto.cnpjcpfcodigodestino = destinotrajeto.codigo

    LEFT JOIN agrupamentocliente_cnpjcpfcodigo agrupamentocliente_cnpjcpfcodigo_destinotrajeto
      ON destinotrajeto.codigo = agrupamentocliente_cnpjcpfcodigo_destinotrajeto.cnpjcpfcodigo

    LEFT JOIN agrupamentocliente clientedestinotrajeto
      ON agrupamentocliente_cnpjcpfcodigo_destinotrajeto.codigo = clientedestinotrajeto.codigo

    WHERE
      programacaoembarque.dtcancelamento IS NULL
      AND programacaoembarque.semaforo = 1
      AND programacaoembarque.dtemissao::date 
      BETWEEN '2023-04-01' AND current_date

    GROUP BY
      programacaoembarque.numero,
      programacaoembarque.diferenciadornumero,
      programacaoembarque.dtemissao,
      programacaoembarque.kmfretecompra,
      programacaoembarque.tipo,
      COALESCE(
        clientepagador.codigo,
        clientedestinovazio.codigo,
        clientedestinotrajeto.codigo,
        clienteorigemvazio.codigo,
        clienteorigemtrajeto.codigo
      ),
      utilizacaoveiculo.descricao
)

SELECT
  TO_CHAR(SUM(km_carregado), '999G999G999G999') AS kmcarregado,
  TO_CHAR(SUM(km_vazio), '999G999G999G999') AS kmvazio,
  TO_CHAR(SUM(km_total_rodado), '999G999G999G999') AS kmtotal,
  TO_CHAR(COALESCE(SUM(km_vazio) / NULLIF(SUM(km_total_rodado), 0), 0) * 100, '990.99%') AS percentualvazio,

  TO_CHAR(SUM(km_carregado_frota), '999G999G999G999') AS kmcarregadofrota,
  TO_CHAR(SUM(km_vazio_frota), '999G999G999G999') AS kmvaziofrota,
  TO_CHAR(SUM(km_total_frota), '999G999G999G999') AS kmtotalfrota,
  TO_CHAR(COALESCE(SUM(km_vazio_frota) / NULLIF(SUM(km_total_frota), 0), 0) * 100, '990.99%') AS percentualvaziofrota,

  TO_CHAR(SUM(km_carregado_agregado), '999G999G999G999') AS kmcarregadoagregado,
  TO_CHAR(SUM(km_vazio_agregado), '999G999G999G999') AS kmvazioagregado,
  TO_CHAR(SUM(km_total_agregado), '999G999G999G999') AS kmtotalagregado,
  TO_CHAR(COALESCE(SUM(km_vazio_agregado) / NULLIF(SUM(km_total_agregado), 0), 0) * 100, '990.99%') AS percentualvazioagregado,

  TO_CHAR(SUM(km_carregado_terceiro), '999G999G999G999') AS kmcarregadoterceiro,
  TO_CHAR(SUM(km_vazio_terceiro), '999G999G999G999') AS kmvazioterceiro,
  TO_CHAR(SUM(km_total_terceiro), '999G999G999G999') AS kmtotalterceiro,
  TO_CHAR(COALESCE(SUM(km_vazio_terceiro) / NULLIF(SUM(km_total_terceiro), 0), 0) * 100, '990.99%') AS percentualvazioterceiro

FROM kmrodado
LEFT JOIN agrupamentocliente ON agrupamentocliente.codigo = kmrodado.cliente

WHERE km_total_rodado > 0
