-- AUTORIZACAO DE SAIDA MATRIZ // CST00000981900079520240717170434050305

SELECT
  sulista.autorizacaosaida.id
, sulista.autorizacaosaida.motorista
, sulista.autorizacaosaida.frota
, sulista.autorizacaosaida.carreta
, CASE WHEN sulista.autorizacaosaida.tipoviagem = 1 THEN 'Viagem'
       WHEN sulista.autorizacaosaida.tipoviagem = 2 THEN 'Manutenção'
       WHEN sulista.autorizacaosaida.tipoviagem = 3 THEN 'Admnistrativo'
       END AS tipoviagem
, sulista.autorizacaosaida.destino

, CASE WHEN sulista.autorizacaosaida.frotaleve = 1 THEN 'Frota Leve'
       WHEN sulista.autorizacaosaida.frotapesada = 1 THEN 'Frota Pesada'
   END AS tipofrota
   
, sulista.autorizacaosaida.dataretorno
,CASE 
    WHEN sulista.autorizacaosaida.frotaleve = 1 
    AND sulista.autorizacaosaida.dataretorno > (CURRENT_DATE + INTERVAL '12 hours')
    THEN 'Pendente'
    ELSE NULL 
END AS pendente
, sulista.autorizacaosaida.usuarioemissao
, sulista.autorizacaosaida.dataemissao
, sulista.autorizacaosaida.usuarioalteracao
, sulista.autorizacaosaida.dataalteracao
, sulista.autorizacaosaida.datasaida
, sulista.autorizacaosaida.odometrosaida
, sulista.autorizacaosaida.usuariosaida
, sulista.autorizacaosaida.observacaosaida

FROM sulista.autorizacaosaida

WHERE enviarportaria = true

ORDER BY id desc