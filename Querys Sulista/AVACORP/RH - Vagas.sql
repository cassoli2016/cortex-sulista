-- Vagas RH

SELECT
 CASE WHEN sulista.rhaberturavagas.resultado = 1 THEN 'Finalizada'
       WHEN sulista.rhaberturavagas.resultado = 2 THEN 'Cancelado'
       WHEN sulista.rhaberturavagas.resultado = 3 THEN 'Em Andamento(Triagem)'
       WHEN sulista.rhaberturavagas.resultado = 4 THEN 'Em Andamento(Entrevistas)'
       WHEN sulista.rhaberturavagas.resultado = 5 THEN 'Congelada'
       WHEN sulista.rhaberturavagas.resultado = 6 THEN 'Abertura da Vaga'
       END as resultado
, sulista.rhaberturavagas.id
, sulista.rhaberturavagas.grupo
, sulista.rhaberturavagas.empresa
,CASE WHEN sulista.rhaberturavagas.filial = 1 THEN 'MTZ'
      WHEN sulista.rhaberturavagas.filial = 2 THEN 'SBC'
      WHEN sulista.rhaberturavagas.filial = 7 THEN 'RESENDE'
      WHEN sulista.rhaberturavagas.filial = 15 THEN 'PSA'
      WHEN sulista.rhaberturavagas.filial = 19 THEN 'JOI'
      WHEN sulista.rhaberturavagas.filial = 20 THEN 'CRZ'
      WHEN sulista.rhaberturavagas.filial = 21 THEN 'PTA'
      WHEN sulista.rhaberturavagas.filial = 24 THEN 'CURITIBA'
      END as filial
,CASE WHEN sulista.rhaberturavagas.areavaga = 1 THEN 'Admnistrativo'
      WHEN sulista.rhaberturavagas.areavaga = 2 THEN 'Operacional'
      WHEN sulista.rhaberturavagas.areavaga = 3 THEN 'Motoristas' --- NOVO
      END as areavaga
, sulista.rhaberturavagas.unidade
, sulista.rhaberturavagas.cargo
, sulista.rhdepartamento.descricao AS departamento
, sulista.rhaberturavagas.dtsolicitacao
, sulista.rhaberturavagas.solicitante
, CASE WHEN sulista.rhaberturavagas.solicitantecargo = '1' THEN 'Gerente'
       WHEN sulista.rhaberturavagas.solicitantecargo = '2' THEN 'Supervisor'
       WHEN sulista.rhaberturavagas.solicitantecargo = '3' THEN 'Coordenador'
       WHEN sulista.rhaberturavagas.solicitantecargo = '4' THEN 'Recursos Humanos'
       END as solicitantecargo
, CASE WHEN sulista.rhaberturavagas.motivo = 1 THEN 'Aumento de Quadro'
       WHEN sulista.rhaberturavagas.motivo = 2 THEN 'Substituição'
       END as motivo
, sulista.rhaberturavagas.motivoaumento
, sulista.rhaberturavagas.nomesubstituido
, CASE WHEN sulista.rhaberturavagas.tipovaga = 1 THEN 'Efetivo'
       WHEN sulista.rhaberturavagas.tipovaga = 2 THEN 'Temporário'
       WHEN sulista.rhaberturavagas.tipovaga = 3 THEN 'Estágio'
       WHEN sulista.rhaberturavagas.tipovaga = 4 THEN 'Aprendiz'
       END as tipo
, CASE WHEN sulista.rhaberturavagas.escolaridade = 1 THEN 'Fundamental'
       WHEN sulista.rhaberturavagas.escolaridade = 2 THEN 'Ensino Médio'
       WHEN sulista.rhaberturavagas.escolaridade = 3 THEN 'Ensino Superior'
       WHEN sulista.rhaberturavagas.escolaridade = 4 THEN 'Pós Graduação'
       WHEN sulista.rhaberturavagas.escolaridade = 5 THEN 'Mestrado'
       WHEN sulista.rhaberturavagas.escolaridade = 6 THEN 'Doutorado'
       END as escolaridade
, CASE WHEN sulista.rhaberturavagas.sexo = 1 THEN 'Masculino'
       WHEN sulista.rhaberturavagas.sexo = 2 THEN 'Feminino'
       WHEN sulista.rhaberturavagas.sexo = 3 THEN 'Ambos'
       END as sexo
, sulista.rhaberturavagas.experiencia 
, CASE WHEN sulista.rhaberturavagas.diassemana = '1' THEN '6X1 (Segunda a sábado)'
       WHEN sulista.rhaberturavagas.diassemana = '2' THEN '6X1 (Domingo a sexta)'
       WHEN sulista.rhaberturavagas.diassemana = '3' THEN '5x2 (Segunda a sexta)'    
       WHEN sulista.rhaberturavagas.diassemana = '4' THEN '12x36'
   END AS diassemana
, CASE WHEN sulista.rhaberturavagas.sabado = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.sabado = 0 THEN 'Não'
       END as sabado
, CASE WHEN sulista.rhaberturavagas.pcd = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.pcd = 2 THEN 'Não'
       WHEN sulista.rhaberturavagas.pcd = 3 THEN 'Não especificado'
       END as pcd
, CASE WHEN sulista.rhaberturavagas.uniforme = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.uniforme = 2 THEN 'Não'
       END as uniforme
, sulista.rhaberturavagas.salario
, CASE WHEN sulista.rhaberturavagas.plr = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.plr = 0 THEN 'Não' 
       END as plr
, CASE WHEN sulista.rhaberturavagas.vt = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.vt = 0 THEN 'Não'  
       END as vt
, CASE WHEN sulista.rhaberturavagas.planosaude = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.planosaude = 0 THEN 'Não' 
       END as planosaude
, CASE WHEN sulista.rhaberturavagas.ticket = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.ticket = 0 THEN 'Não'
       END as ticket
, CASE WHEN sulista.rhaberturavagas.planoodonto = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.planoodonto = 0 THEN 'Não'
       END as planoodonto
, CASE WHEN sulista.rhaberturavagas.segurovida = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.segurovida = 0 THEN 'Não'
       END as segurovida
, CASE WHEN sulista.rhaberturavagas.dayoff = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.dayoff = 0 THEN 'Não'
       END as dayoff
, sulista.rhaberturavagas.perfil
, CASE  WHEN sulista.rhaberturavagas.equipamentos = 1 THEN 'Sim'
       WHEN sulista.rhaberturavagas.equipamentos = 0 THEN 'Não'
       END as equipamentos
, CASE WHEN sulista.rhaberturavagas.computador = 1 THEN 'Desktop'
       WHEN sulista.rhaberturavagas.computador = 2 THEN 'Notebook'
       WHEN sulista.rhaberturavagas.computador = 3 THEN 'Não Necessita'
       END as computador
, CASE WHEN sulista.rhaberturavagas.celular = 1 THEN 'Não'
       WHEN sulista.rhaberturavagas.celular = 2 THEN 'Sim'
       END as celular
, sulista.rhaberturavagas.dtadimissao
, CASE WHEN sulista.rhaberturavagas.recrutamentotipo = 1 THEN 'Interno' 
       WHEN sulista.rhaberturavagas.recrutamentotipo = 2 THEN 'Externo' 
       END as recrutamentotipo
, sulista.rhaberturavagas.resultadonome
, sulista.rhaberturavagas.resultadocpf
, sulista.rhaberturavagas.datafechamento
, CASE WHEN sulista.rhaberturavagas.plataformarecrutamento = 1 THEN 'Indicação'
       WHEN sulista.rhaberturavagas.plataformarecrutamento = 2 THEN 'Facebook'  
       WHEN sulista.rhaberturavagas.plataformarecrutamento = 3 THEN 'LinkedIn'  
       WHEN sulista.rhaberturavagas.plataformarecrutamento = 4 THEN 'Sine/Pat' 
       WHEN sulista.rhaberturavagas.plataformarecrutamento = 5 THEN 'Outros'  
   END AS origemrecrutamento
, sulista.rhaberturavagas.plataformarecrutamentodesc
, sulista.rhaberturavagas.usuarioinclusao
, sulista.rhaberturavagas.dtinclusao
, sulista.rhaberturavagas.usuarioalteracao
, sulista.rhaberturavagas.dtalteracao


FROM

sulista.rhaberturavagas

LEFT JOIN sulista.rhdepartamento
ON sulista.rhdepartamento.grupo = sulista.rhaberturavagas.grupo
AND sulista.rhdepartamento.empresa = sulista.rhaberturavagas.empresa
AND sulista.rhdepartamento.codigo = sulista.rhaberturavagas.departamento

ORDER BY sulista.rhaberturavagas.resultado DESC
        ,sulista.rhaberturavagas.dtinclusao DESC