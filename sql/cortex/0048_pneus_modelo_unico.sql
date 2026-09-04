-- Pneus: o catálogo de modelo estava duplicando a cada semeadura.
--
-- A 0046 pôs `UNIQUE (marca, modelo, medida, desenho)` e a semeadura entra por
-- `ON CONFLICT … DO UPDATE`. Parecia certo. Medido na SEGUNDA passada, o
-- catálogo foi de 8.572 para 17.144 linhas — e 8.572 já era o número errado,
-- porque não existem 8.572 modelos de pneu: existe UM POR PNEU.
--
-- A causa é a regra de NULL do SQL: num índice único, `NULL` é sempre
-- DIFERENTE de `NULL`. Como `medida` vem vazia nos 8.572 (ela mora noutro
-- endpoint da Prolog e ainda não foi buscada), nenhuma linha jamais casa com
-- outra, o `ON CONFLICT` não encontra nada e insere de novo. A cada coleta o
-- catálogo dobraria — em silêncio, sem erro nenhum, e com o `modelo_id` de
-- cada pneu apontando para uma linha nova a cada passada.
--
-- A correção é a chave sobre a EXPRESSÃO, com o vazio normalizado. Não se
-- resolve trocando NULL por string vazia nos dados: "medida desconhecida" e
-- "medida em branco" são a mesma coisa aqui, mas o dia em que não forem, o
-- dado tem de continuar podendo dizer NULL.
--
-- O catálogo é DERIVADO — reconstruído da próxima semeadura —, então limpar e
-- refazer não perde nada que não volte sozinho.
UPDATE pne_pneu SET modelo_id = NULL;
DELETE FROM pne_modelo;

ALTER TABLE pne_modelo DROP CONSTRAINT IF EXISTS pne_modelo_marca_modelo_medida_desenho_key;

CREATE UNIQUE INDEX IF NOT EXISTS pne_modelo_chave
  ON pne_modelo (marca, modelo, coalesce(medida, ''), coalesce(desenho, ''));
