-- Pipeline Projetos

SELECT

	  pipelineprojetos.id
	, pipelineprojetos.numeroid
	, pipelineprojetos.versao
	, pipelineprojetos.grupo
	, pipelineprojetos.empresa
	, pipelineprojetos.filial
	, pipelineprojetos.unidade
	
	, pipelineprojetos.projeto
	,UPPER(pipelineprojetos.cliente) as Cliente
	    
    , CASE WHEN pipelineprojetos.temperatura = 1 THEN 'Frio'
           WHEN pipelineprojetos.temperatura = 2 THEN 'Morno'
           WHEN pipelineprojetos.temperatura = 3 THEN 'Quente'
      END AS temperatura
	, pipelineprojetos.segmento
	, tipocarga.descricao
	
	, CASE WHEN pipelineprojetos.tipo_negocio = 1 THEN 'Regular'
	       WHEN pipelineprojetos.tipo_negocio = 2 THEN 'SPOT'
	       WHEN pipelineprojetos.tipo_negocio = 3 THEN 'Reajuste'
	       WHEN pipelineprojetos.tipo_negocio = 4 THEN 'Projeto'
	  END AS tipo_negocio
	  
	, CASE WHEN pipelineprojetos.escopo_principal = 1 THEN 'Transporte'
	       WHEN pipelineprojetos.escopo_principal = 2 THEN 'Transferência'
	       WHEN pipelineprojetos.escopo_principal = 3 THEN 'Outbound'
	       WHEN pipelineprojetos.escopo_principal = 4 THEN 'Inbound'
	       WHEN pipelineprojetos.escopo_principal = 5 THEN 'Crossdocking'
	       WHEN pipelineprojetos.escopo_principal = 6 THEN 'Outro'
	  END AS escopo_principal
	  
	, pipelineprojetos.detalhe_operacao	  
	, CASE WHEN pipelineprojetos.negocio = 1 THEN 'Venda'
	       WHEN pipelineprojetos.negocio = 2 THEN 'Interno'
	       WHEN pipelineprojetos.negocio = 3 THEN 'Externo'
	  END AS negocio
	  
	, CASE WHEN pipelineprojetos.status_negocio = 1 THEN 'Em execução'
	       WHEN pipelineprojetos.status_negocio = 2 THEN 'Entregue'
	       WHEN pipelineprojetos.status_negocio = 3 THEN 'Não Iniciado'
	       WHEN pipelineprojetos.status_negocio = 4 THEN 'Declinado'
	  END AS status_negocio
	  
	, CASE WHEN pipelineprojetos.status_negociacao = 1 THEN 'Aceita'
	       WHEN pipelineprojetos.status_negociacao = 2 THEN 'Não Aceita'
	       WHEN pipelineprojetos.status_negociacao = 3 THEN 'Em negociação'
	       WHEN pipelineprojetos.status_negociacao = 4 THEN 'Declinado'
	       WHEN pipelineprojetos.status_negociacao = 5 THEN 'Somente Projeto'
	  END AS status_negociacao
	  
	, pipelineprojetos.data_recebimento
	, pipelineprojetos.data_inicio
	, pipelineprojetos.deadline
	, pipelineprojetos.data_entrega
	, pipelineprojetos.data_aceite_declinio
	, pipelineprojetos.aging_dias
	
	, CASE WHEN pipelineprojetos.solicitante = 1 THEN 'Cliente'
	       WHEN pipelineprojetos.solicitante = 2 THEN 'Projetos'
	       WHEN pipelineprojetos.solicitante = 3 THEN 'Flávio Donato'
	       WHEN pipelineprojetos.solicitante = 4 THEN 'SAC'
	       WHEN pipelineprojetos.solicitante = 5 THEN 'Operação'
	       WHEN pipelineprojetos.solicitante = 6 THEN 'Cassio de Vargas'
	       WHEN pipelineprojetos.solicitante = 7 THEN 'Ricardo Magalhães'
	  END AS solicitante
	  
    , CASE WHEN pipelineprojetos.responsavel_projeto = 1 THEN 'Lucas Jankovski'
           WHEN pipelineprojetos.responsavel_projeto = 2 THEN 'Gabriel Santos'
           WHEN pipelineprojetos.responsavel_projeto = 3 THEN 'João Daniel'
      END AS responsavel_projeto
    , pipelineprojetos.prazocliente
	, pipelineprojetos.rob_mensal
	, pipelineprojetos.rol_mensal
	, pipelineprojetos.csp
	, pipelineprojetos.lucro_bruto
	, pipelineprojetos.lucro_bruto_percentual
	, pipelineprojetos.motivo_declinio
	, pipelineprojetos.motivo_perda
	, pipelineprojetos.data_inclusao
	, us.nomecompleto as usuario_inclusao
	, pipelineprojetos.data_alteracao
	, usuario.nomecompleto as usuario_alteracao
	,'' as placeholder
	
FROM sulista.pipelineprojetos

LEFT JOIN tipocarga
ON pipelineprojetos.segmento = tipocarga.codigo

LEFT JOIN usuario us
ON pipelineprojetos.usuario_inclusao = us.codigo

LEFT JOIN usuario
ON pipelineprojetos.usuario_alteracao = usuario.codigo

ORDER BY pipelineprojetos.numeroid asc
        ,pipelineprojetos.versao