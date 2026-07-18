-- LEADS COMERCIAIS

SELECT

	 gestaocomercial.id
	, CASE WHEN gestaocomercial.responsavel = 1 THEN 'FLÁVIO DONATO'
	       WHEN gestaocomercial.responsavel = 2 THEN 'JOÃO DANIEL'
	       WHEN gestaocomercial.responsavel = 3 THEN 'CASSIO DE VARGAS'
	       WHEN gestaocomercial.responsavel = 4 THEN 'RICARDO MAGALHÃES'
	       WHEN gestaocomercial.responsavel = 5 THEN 'NATÁLIA RIBEIRO'
	   END AS responsavel
	, gestaocomercial.data
	, gestaocomercial.cliente
    , CASE WHEN gestaocomercial.temperatura = 1 THEN 'Frio'
           WHEN gestaocomercial.temperatura = 2 THEN 'Morno'
           WHEN gestaocomercial.temperatura = 3 THEN 'Quente'
      END AS temperatura
	, gestaocomercial.unidade_regiao
	, tipocarga.descricao
	, CASE WHEN gestaocomercial.origem_lead = 1 THEN 'Indicação'
        WHEN gestaocomercial.origem_lead = 2 THEN 'Google / Site'
        WHEN gestaocomercial.origem_lead = 3 THEN 'LinkedIn / Redes Sociais'
        WHEN gestaocomercial.origem_lead = 4 THEN 'Prospecção Ativa'
        WHEN gestaocomercial.origem_lead = 5 THEN 'Eventos / Feiras'
        WHEN gestaocomercial.origem_lead = 6 THEN 'E-mail Marketing'
        WHEN gestaocomercial.origem_lead = 7 THEN 'Parceiros'
        WHEN gestaocomercial.origem_lead = 8 THEN 'Ex-Cliente'
        WHEN gestaocomercial.origem_lead = 9 THEN 'Outros'
      END AS origem_lead_desc
	, gestaocomercial.descricao_servico
	, gestaocomercial.potencial_receita
	, gestaocomercial.rob_previsto
	, gestaocomercial.rob_realizado
	, gestaocomercial.temperatura as temperatura_codigo
	, CASE WHEN gestaocomercial.status_negociacao = 1 THEN 'Qualificado'
           WHEN gestaocomercial.status_negociacao = 2 THEN 'Não Qualificado'	
           WHEN gestaocomercial.status_negociacao = 3 THEN 'Em Prospecção'
	END AS status_negociacao
	, gestaocomercial.status_negociacao as negociacaocodigo
	, gestaocomercial.previsao_fechamento
	, gestaocomercial.previsao_fechamento::date - CURRENT_DATE AS dias_para_fechamento
	,CASE gestaocomercial.motivo_perda
    WHEN '1' THEN 'Sem orçamento'
    WHEN '2' THEN 'Fora do perfil'
    WHEN '3' THEN 'Sem prioridade no momento'
    WHEN '4' THEN 'Concorrente'
    WHEN '5' THEN 'Não avançou internamente'
    WHEN '6' THEN 'Não respondeu'
    WHEN '7' THEN 'Produto/escopo não atende'
    WHEN '8' THEN 'Sem Sinergia operacional'
    WHEN '9' THEN 'Outros'
END AS motivo_perda
	, gestaocomercial.observacoes
	, gestaocomercial.nomecliente
	, gestaocomercial.telefonecliente
	, gestaocomercial.telefonecliente2
	, gestaocomercial.emailcliente
	, gestaocomercial.ativoinativo
	, usuario.nomecompleto as usuarioinclusao
    , gestaocomercial.dtinclusao
    , us.nomecompleto as usuarioalteracao
    , gestaocomercial.dtalteracao
	
FROM sulista.gestaocomercial

LEFT JOIN tipocarga
ON gestaocomercial.cliente_segmento = tipocarga.codigo

LEFT JOIN usuario
ON gestaocomercial.usuarioinclusao = usuario.codigo

LEFT JOIN usuario us
ON gestaocomercial.usuarioalteracao = us.codigo

WHERE 1=1
AND gestaocomercial.ativoinativo = 1
ORDER BY gestaocomercial.id DESC 
, gestaocomercial.ativoinativo