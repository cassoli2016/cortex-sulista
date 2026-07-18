-- Indicadores de Qualidade

SELECT

  sulista.indicadorescorporativos.id
, sulista.indicadorescorporativos.grupo
, sulista.indicadorescorporativos.empresa
, CASE
    WHEN sulista.indicadorescorporativos.filial = 1 THEN 'MTZ'
    WHEN sulista.indicadorescorporativos.filial = 2 THEN 'SBC'
    WHEN sulista.indicadorescorporativos.filial = 20 THEN 'CRZ'
   END as filial
, CASE
    WHEN sulista.indicadorescorporativos.tipo = 1 THEN 'Meta' 
    WHEN sulista.indicadorescorporativos.tipo = 2 THEN 'Realizado'
  END as tipo
, CASE 
    WHEN sulista.indicadorescorporativos.indicador = 1 THEN 'Água'
    WHEN sulista.indicadorescorporativos.indicador = 2 THEN 'Energia'
    WHEN sulista.indicadorescorporativos.indicador = 3 THEN 'Resíduos'
    WHEN sulista.indicadorescorporativos.indicador = 4 THEN 'Treinamentos'
    WHEN sulista.indicadorescorporativos.indicador = 5 THEN 'Abensenteísmo'
    WHEN sulista.indicadorescorporativos.indicador = 6 THEN 'Opacidade'
    WHEN sulista.indicadorescorporativos.indicador = 7 THEN 'Acidentes'
    WHEN sulista.indicadorescorporativos.indicador = 8 THEN 'Performance Mot.'
    WHEN sulista.indicadorescorporativos.indicador = 9 THEN 'Co2'
    WHEN sulista.indicadorescorporativos.indicador = 10 THEN 'Satisfação Cliente Int.'
    WHEN sulista.indicadorescorporativos.indicador = 11 THEN 'Km Vazio'
    WHEN sulista.indicadorescorporativos.indicador = 12 THEN 'Satisfação Cliente Ext.' -- nps
    WHEN sulista.indicadorescorporativos.indicador = 13 THEN 'Segurança Viária' -- segurança
    WHEN sulista.indicadorescorporativos.indicador = 14 THEN 'Turnover'
    WHEN sulista.indicadorescorporativos.indicador = 15 THEN 'Manutenção Preventiva' -- preventiva
    WHEN sulista.indicadorescorporativos.indicador = 16 THEN 'Reclamações Clientes' 
  END as indicador

, TO_CHAR(sulista.indicadorescorporativos.anomes, 'DD/MM/YYYY') as data
, sulista.indicadorescorporativos.agua
, sulista.indicadorescorporativos.energia
, sulista.indicadorescorporativos.co2
, sulista.indicadorescorporativos.kmvazio
, sulista.indicadorescorporativos.res_peri_sol
, sulista.indicadorescorporativos.res_n_peri
, sulista.indicadorescorporativos.nrcolab
, TO_CHAR(sulista.indicadorescorporativos.horastotais, 'HH24:MI') AS horastotais
, sulista.indicadorescorporativos.horasindividuais
, sulista.indicadorescorporativos.absenteismo
, sulista.indicadorescorporativos.opacidade
, sulista.indicadorescorporativos.acidentes as acidente
, CASE 
    WHEN sulista.indicadorescorporativos.classificacao = 0 THEN 'Não'
    WHEN sulista.indicadorescorporativos.classificacao = 1 THEN 'Leve'
    WHEN sulista.indicadorescorporativos.classificacao = 2 THEN 'Médio'
    WHEN sulista.indicadorescorporativos.classificacao = 3 THEN 'Grave'
  END as Classificacao
, CASE 
    WHEN sulista.indicadorescorporativos.ocupacional = 1 THEN 'Sim'
    WHEN sulista.indicadorescorporativos.ocupacional = 2 THEN 'Não'
  END AS ocupacional
, CASE 
    WHEN sulista.indicadorescorporativos.derramamento = 1 THEN 'Sim'
    WHEN sulista.indicadorescorporativos.derramamento = 2 THEN 'Não'
  END AS derramamento
, sulista.indicadorescorporativos.performance
, sulista.indicadorescorporativos.clienteinterno
, sulista.indicadorescorporativos.reclamacoesclientes


, sulista.indicadorescorporativos.nps
, sulista.indicadorescorporativos.seguranca
, sulista.indicadorescorporativos.turnover
, sulista.indicadorescorporativos.preventiva


FROM
sulista.indicadorescorporativos

ORDER by sulista.indicadorescorporativos.id DESC