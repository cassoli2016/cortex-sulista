SELECT 
  coleta.grupo
, coleta.empresa
, coleta.filial
, CASE WHEN coleta.filial = 2 THEN 'SBC'
       WHEN coleta.filial = 22 THEN 'SJP'
       WHEN coleta.filial = 23 THEN 'SBC CD'
       WHEN coleta.filial = 19 THEN 'JOI'
       WHEN coleta.filial = 21 THEN 'POA'
       WHEN coleta.filial = 20 THEN 'CRU'
       WHEN coleta.filial = 1 THEN 'MTZ'
       WHEN coleta.filial = 15 THEN 'PA'
       WHEN coleta.filial = 7 THEN 'RES' 
       END AS filialapelido
, coleta.unidade
, coleta.diferenciadornumero
, coleta.serie
, coleta.numero AS coleta

, conhecimento.grupo AS grupo_cte
, conhecimento.empresa AS empresa_cte
, conhecimento.filial AS filial_cte
, conhecimento.unidade AS unidade_cte
, conhecimento.diferenciadornumero AS dif_cte
, conhecimento.serie AS serie_cte
, conhecimento.numero AS cte
, sulista.custoextra.conhecimentocomplementar
, CASE WHEN sulista.custoextra.tipocusto = 8 THEN 'Descarga'
    WHEN sulista.custoextra.tipocusto = 105 THEN 'Estadia'
    WHEN sulista.custoextra.tipocusto = 104 THEN 'Diária'
    WHEN sulista.custoextra.tipocusto = 106 THEN 'Coleta Frustrada'
    WHEN sulista.custoextra.tipocusto = 107 THEN 'Frete Compra'
    WHEN sulista.custoextra.tipocusto = 108 THEN 'Movimentação Balança'
    WHEN sulista.custoextra.tipocusto = 109 THEN 'Ajudante'
    WHEN sulista.custoextra.tipocusto = 110 THEN 'Carga Crítica'
    WHEN sulista.custoextra.tipocusto = 111 THEN 'Escolta'
   end as tipocusto
--, sulista.custoextra.statuscobranca
--, sulista.custoextra.justificativa

, CASE sulista.custoextra.statuscobranca
      WHEN 1 THEN '?? Emitido'
      WHEN 2 THEN '?? Não Cobrado'
      WHEN 3 THEN '?? Aguardando Cobrança'
      END AS statuscobranca

, CASE sulista.custoextra.justificativa
      WHEN 1 THEN 'Devido'
      WHEN 2 THEN 'Acordo comercial'
      WHEN 3 THEN 'Erro operacional'
      WHEN 4 THEN 'Já Contemplado'
      END AS justificativa
      
, sulista.custoextra.valorcusto
, sulista.custoextra.valorconhecimentocomplementar
, sulista.custoextra.valorcobrado
, CASE WHEN sulista.custoextra.fretecompra = 1 THEN 'Sim'
       WHEN sulista.custoextra.fretecompra = 2 THEN 'Não'
  else '? Sem Registro'
  END AS fretecompra
, sulista.custoextra.motivo
, usuarioinsert.nomecompleto AS userinclusao
, sulista.custoextra.dtinclusao
, usuarioalteracao.nomecompleto AS useralteracao
, sulista.custoextra.dtalteracao
, sulista.custoextra.id

FROM

coleta

LEFT JOIN coleta_composicao 
ON coleta_composicao.grupo = coleta.grupo
AND coleta_composicao.empresa = coleta.empresa
AND coleta_composicao.filial = coleta.filial
AND coleta_composicao.unidade = coleta.unidade 
AND coleta_composicao.diferenciadornumero = coleta.diferenciadornumero
AND coleta_composicao.serie = coleta.serie
AND coleta_composicao.numero = coleta.numero
AND coleta_composicao.tipodocumento in (6,13)
------- Fim de buscar a coleta de um cte

LEFT JOIN conhecimento_composicao
ON conhecimento_composicao.tipodocumento = 27
AND conhecimento_composicao.grupo= coleta.grupo
AND conhecimento_composicao.empresa = coleta.empresa
AND conhecimento_composicao.filialdocumento = coleta.filial
AND conhecimento_composicao.unidadedocumento = coleta.unidade
AND conhecimento_composicao.diferenciadornumerodocumento = coleta.diferenciadornumero
AND conhecimento_composicao.seriedocumento = coleta.serie
AND conhecimento_composicao.numerodocumento = coleta.numero

LEFT JOIN conhecimento
ON conhecimento.grupo = COALESCE(coleta_composicao.grupo,conhecimento_composicao.grupo)
AND conhecimento.empresa = COALESCE(coleta_composicao.empresa,conhecimento_composicao.empresa)
AND conhecimento.filial = COALESCE(coleta_composicao.filialdocumento,conhecimento_composicao.filial)
AND conhecimento.unidade = COALESCE(coleta_composicao.unidadedocumento,conhecimento_composicao.unidade)
AND conhecimento.diferenciadornumero = COALESCE(coleta_composicao.diferenciadornumerodocumento,conhecimento_composicao.diferenciadornumero)
AND conhecimento.serie = COALESCE(coleta_composicao.seriedocumento,conhecimento_composicao.serie)
AND conhecimento.numero = COALESCE(coleta_composicao.numerodocumento,conhecimento_composicao.numero)

LEFT JOIN sulista.custoextra
ON sulista.custoextra.grupo = conhecimento.grupo
AND sulista.custoextra.empresa = conhecimento.empresa
AND sulista.custoextra.filialdocumento = conhecimento.filial
AND sulista.custoextra.unidadedocumento = conhecimento.unidade
AND sulista.custoextra.diferenciadornumerodocumento = conhecimento.diferenciadornumero
AND sulista.custoextra.seriedocumento = conhecimento.serie
AND sulista.custoextra.numerodocumento = conhecimento.numero

LEFT JOIN tipodocumento
ON tipodocumento.codigo = sulista.custoextra.tipodocumento

LEFT JOIN tipocusto
ON tipocusto.codigo = sulista.custoextra.tipocusto

LEFT JOIN usuario usuarioinsert
ON usuarioinsert.codigo = sulista.custoextra.userinclusao

LEFT JOIN usuario usuarioalteracao
ON usuarioalteracao.codigo = sulista.custoextra.useralterecao


WHERE

sulista.custoextra.dtinclusao IS NOT NULL

ORDER BY dtinclusao desc