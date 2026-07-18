-- Certidoes e Licenças

SELECT
       CASE 
        WHEN certidoes.dtvencimento IS NULL THEN 0
        WHEN (certidoes.dtvencimento::date - current_date) <= 0 THEN 3 
        WHEN (certidoes.dtvencimento::date - current_date) <= 15 THEN 2 
        WHEN (certidoes.dtvencimento::date - current_date) <= 30 THEN 1 
        ELSE 0 
      END AS status_prazo

    , certidoes.id
    , certidoes.grupo
    , certidoes.empresa
    , CASE WHEN certidoes.tipoarquivo = 1 THEN 'CERTIDÃO'
           WHEN certidoes.tipoarquivo = 2 THEN 'LICENÇA'
           WHEN certidoes.tipoarquivo = 3 THEN 'ALVARÁ'
           WHEN certidoes.tipoarquivo = 4 THEN 'SOCIETÁRIO'
           WHEN certidoes.tipoarquivo = 5 THEN 'APÓLICE DE SEGURO'
      END AS tipoarquivo
    , CASE WHEN certidoes.filial = 1 THEN 'MTZ'
           WHEN certidoes.filial = 2 THEN 'SBC'
           WHEN certidoes.filial = 7 THEN 'RESENDE'
           WHEN certidoes.filial = 15 THEN 'POUSO ALEGRE'
           WHEN certidoes.filial = 19 THEN 'JOINVILLE'
           WHEN certidoes.filial = 20 THEN 'CRUZEIRO'
           WHEN certidoes.filial = 21 THEN 'PORTO ALEGRE'
           WHEN certidoes.filial = 23 THEN 'SBC CD'
           WHEN certidoes.filial = 24 THEN 'CURITIBA'
           WHEN certidoes.filial = 25 THEN 'CAMPO GRANDE'
       END AS filial
    , certidoes.unidade
    , certidoes.emissor
    , cadastro.razaosocial
    , certidoes.dtemissao
    , certidoes.dtvencimento
    , (certidoes.dtvencimento::date - current_date) AS dias_vencimento
    , UPPER(certidoes.observacao)
    , CASE WHEN certidoes.ativoinativo = 1 then 'Ativo'
           ELSE 'Inativo'
      END AS status
    , usuario.nomecompleto as usuarioinclusao
    , certidoes.dtinclusao
    , us.nomecompleto as usuarioalteracao
    , certidoes.dtalteracao
    , NOW() AS dataatual

FROM sulista.certidoes

LEFT JOIN cadastro
    on certidoes.emissor = avacorpi.fnc_Formata_CnpjCpf(cadastro.codigo)

LEFT JOIN usuario
    on certidoes.usuarioinclusao = usuario.codigo

LEFT JOIN usuario us
    on certidoes.usuarioalteracao = us.codigo

ORDER BY certidoes.id DESC;