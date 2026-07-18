SELECT 
    retorno.placa,
    retorno.numerofrota,
    retorno.rebocador,
    retorno.rebocado,
    retorno.refrigeracao,
    retorno.proprietario,
    retorno.razaosocial_proprietario,
    retorno.descricao_tipo,
    retorno.bitrem,
    retorno.descricao_marca,
    retorno.descricao_modelo,
    retorno.descricao_utilizacao,
    retorno.descricao_atividade,
    retorno.descricao_caracteristica,
    retorno.razaosocial_veiculomotorista,
    retorno.descricao_carroceria,
    retorno.descricao_tipocargaveiculo,
    retorno.capacidadecarga,
    retorno.anofabricacao,
    retorno.codigorenavam,
    retorno.nome_empresa,
    retorno.apelido_filial,
    retorno.descricao_unidade,
    retorno.tipofrota,
    retorno.grupo,
    retorno.empresa,
    retorno.semaforo,
    retorno.ativoinativo,
    retorno.considerarveiculopropriooutraempresagrupo,
    retorno.perm_alterar,
    retorno.nomeformularioveiculo,
    retorno.autorformularioveiculo,
    retorno.parametros_impressao,
    retorno.placatemporaria,
    usuarioinc.nomecompleto AS usuarioinc,
    veiculo.dtinc,
    usuarioalt.nomecompleto AS usuarioalt,
    veiculo.dtalt,
    CASE WHEN veiculo.status_veiculo = 1 THEN '?? LIBERADO'
         WHEN veiculo.status_veiculo = 2 THEN '?? FINANCIADO'
         WHEN veiculo.status_veiculo = 3 THEN '?? BLOQUEADO'
    END AS status_veiculo,
    cabine.descricao AS cor_cabine,
    carroceria.descricao AS cor_carroceria
    
FROM 
    avacorpi.fnc_veiculo_gridview (
        1,
        1,
        NULL,
        NULL,
        'Todos',
        NULL,
        'Todos',
        NULL,
        NULL,
        NULL,
        NULL
    ) AS retorno

LEFT JOIN 
    veiculo 
    ON veiculo.placa = retorno.placa

LEFT JOIN 
    usuario AS usuarioinc
    ON usuarioinc.codigo = veiculo.usuarioinc

LEFT JOIN 
    usuario AS usuarioalt
    ON usuarioalt.codigo = veiculo.usuarioalt

LEFT JOIN corveiculo cabine
ON cabine.id = veiculo.idcorveiculocabine

LEFT JOIN corveiculo carroceria
ON carroceria.id = veiculo.idcorveiculocarroceria