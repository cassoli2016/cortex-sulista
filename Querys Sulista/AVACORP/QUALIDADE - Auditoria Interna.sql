-- Auditoria Interna

SELECT

	 controle_auditoria.id
	, controle_auditoria.grupo
	, controle_auditoria.empresa
	, controle_auditoria.filial
	, CASE WHEN controle_auditoria.filial = 1 THEN 'MTZ'
	       WHEN controle_auditoria.filial = 2 THEN 'SBC'
	       WHEN controle_auditoria.filial = 7 THEN 'RESENDE'
	       WHEN controle_auditoria.filial = 15 THEN 'PSA'
	       WHEN controle_auditoria.filial = 19 THEN 'JOI'
           WHEN controle_auditoria.filial = 20 THEN 'CRZ'
           WHEN controle_auditoria.filial = 21 THEN 'PTA'
       END AS filialnome
	, controle_auditoria.unidade
	, controle_auditoria.dt_auditoria
	, controle_auditoria.area_setor
	, controle_auditoria.processo_auditado
	, controle_auditoria.responsavel_area
	, CASE WHEN controle_auditoria.tipo_auditoria = 1 THEN 'Interna'
	       WHEN controle_auditoria.tipo_auditoria = 2 THEN 'Externa'
	  ELSE 'Outro' end as tipo_auditoria
	, CASE
	   WHEN controle_auditoria.auditor IS NULL
        THEN controle_auditoria.auditor_externo
       WHEN controle_auditoria.auditor = 1
        THEN 'Qualidade'
       WHEN controle_auditoria.auditor = 2
        THEN 'Setor interno'
       ELSE 'Não informado'
      END AS auditor_real
	, controle_auditoria.auditor_externo
	, CASE WHEN controle_auditoria.resultado = 1 THEN 'Aprovado'
	else 'Reprovado' end as resultado
	, controle_auditoria.qtde_ncs
	, controle_auditoria.qtde_observacoes
	, controle_auditoria.principal_problema
	, controle_auditoria.acao_definida
	, controle_auditoria.prazo_acao
	, CASE WHEN controle_auditoria.status_acao = '1' THEN 'Não Iniciado'
	       WHEN controle_auditoria.status_acao = '2' THEN 'Em Andamento'
	       WHEN controle_auditoria.status_acao = '3' THEN 'Concluída'
	       WHEN controle_auditoria.status_acao = '4' THEN 'Cancelado'
	  END AS status_acao
	, CASE WHEN controle_auditoria.verificado_qualidade = 1 THEN 'Sim'
	else 'Não' end as verificado_qualidade
	, controle_auditoria.dt_encerramento
	, controle_auditoria.observacoes
	, usuario.nomecompleto as usuarioinclusao
    , controle_auditoria.dtinclusao
    , us.nomecompleto as usuarioalteracao
    , controle_auditoria.dtalteracao
    
FROM sulista.controle_auditoria

LEFT JOIN usuario
on controle_auditoria.usuarioinclusao = usuario.codigo

LEFT JOIN usuario us
on controle_auditoria.usuarioalteracao= us.codigo

ORDER BY controle_auditoria.id DESC