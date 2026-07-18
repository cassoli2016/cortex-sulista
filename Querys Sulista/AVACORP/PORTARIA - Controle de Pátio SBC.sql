--  PATIO SBC

SELECT
    controlepatio.id,
     CASE 
        WHEN controlepatio.dtsaida IS NULL THEN 'Pendente de Saída'
        WHEN controlepatio.dtsaida IS NOT NULL THEN 'Deixou o Pátio'
    END as status,
    controlepatio.grupo,
    controlepatio.empresa,
    controlepatio.filial,
    controlepatio.unidade,
    controlepatio.dtentrada,
    controlepatio.dtsaida,
    CASE 
        WHEN controlepatio.tipo = 1 THEN 'Frota Sulista'
        WHEN controlepatio.tipo = 2 THEN 'Agregado'
        WHEN controlepatio.tipo = 3 THEN 'Terceiro'
        WHEN controlepatio.tipo = 4 THEN 'Colaborador'
        WHEN controlepatio.tipo = 5 THEN 'Visitante'
        WHEN controlepatio.tipo = 6 THEN 'Entregador'
        WHEN controlepatio.tipo = 7 THEN 'Prestador de Serviços'
        WHEN controlepatio.tipo = 8 THEN 'Motorista de App'
    END as tipo,
    controlepatio.placa,
    controlepatio.placacarros,
    controlepatio.carretaplaca,
    CASE WHEN controlepatio.condutor IS NULL THEN controlepatio.nomefuncionario ELSE controlepatio.condutor END AS condutor,
    controlepatio.odometrochegada,
    controlepatio.condutorsaida,
    controlepatio.placacarretasaida,
    controlepatio.odometrosaida,
    controlepatio.docvisitante,
    controlepatio.cliente,
    controlepatio.fornecedor,
    CASE 
        WHEN controlepatio.dtsaida IS NOT NULL THEN 
            TO_CHAR(
                controlepatio.dtsaida - controlepatio.dtentrada, 
                'DD.HH24hMI'
            )
        ELSE NULL
    END as tempo_permanencia,
    controlepatio.observacao,
    controlepatio.usuarioinclusao,
    controlepatio.dtinclusao,
    controlepatio.usuarioalteracao,
    controlepatio.dtalteracao
    
 
FROM sulista.controlepatio
ORDER BY controlepatio.id DESC;