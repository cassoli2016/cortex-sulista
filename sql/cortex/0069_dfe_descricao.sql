-- 0069 · O que o documento DIZ que é — sem isso, evento é linha muda.
--
-- A primeira recolha com conteúdo real (07/09/2026) trouxe cinco documentos, e
-- os cinco eram EVENTO. Na tela apareceram sem data, sem valor e sem nada que
-- os identificasse: o parser sabia ler NOTA (`dhEmi`, `vNF`, `xNome`) e um
-- `resEvento` não tem nenhum dos três.
--
-- O que ele tem é isto, e é bastante:
--
--     <dhEvento>2026-09-07T19:50:32-03:00</dhEvento>
--     <tpEvento>510630</tpEvento>
--     <xEvento>Registro de Passagem Automatico Originado MDFe</xEvento>
--
-- `xEvento` é a frase que a própria SEFAZ escreve. Guardá-la é melhor que
-- traduzir `tpEvento` numa tabela nossa: código sem tabela de domínio não vira
-- rótulo inventado, e aqui o rótulo veio junto.
--
-- E NÃO É SÓ ARRUMAÇÃO DE TELA. O evento acima diz que um MDF-e da casa passou
-- por um posto fiscal — é rastreamento de viagem chegando de graça, pela mesma
-- porta da nota. Sem a descrição, isso ficaria invisível numa lista de linhas
-- iguais.
ALTER TABLE dfe_documento ADD COLUMN IF NOT EXISTS descricao text;

-- O tipo do evento (510630, 110111, 210210…), CRU. Ele identifica a espécie
-- para filtro e contagem; a frase legível vive em `descricao`.
ALTER TABLE dfe_documento ADD COLUMN IF NOT EXISTS evento_tipo varchar(6);

CREATE INDEX IF NOT EXISTS ix_dfe_documento_evento
  ON dfe_documento (evento_tipo) WHERE evento_tipo IS NOT NULL;
