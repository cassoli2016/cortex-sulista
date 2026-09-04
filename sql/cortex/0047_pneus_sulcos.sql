-- Pneus: o sulco tem QUATRO medidas, não três.
--
-- A 0046 criou `pne_inspecao` com `sulco_int_mm`, `sulco_cen_mm` e
-- `sulco_ext_mm` — interno, central, externo. Parecia certo e estava errado:
-- medido no instantâneo real, **os 8.572 pneus têm exatamente 4 medidas de
-- sulco**, sem exceção. Três colunas jogariam uma medida fora em todo pneu da
-- frota, e o desgaste irregular — que é o diagnóstico inteiro desta tabela —
-- se lê justamente na diferença entre os pontos.
--
-- Vai como ARRAY e não como quatro colunas nomeadas porque o nome mente: qual
-- ponto é "interno" depende do lado em que o pneu está montado, e um pneu
-- rodiziado troca de lado sem trocar de medida. O array preserva a ORDEM em
-- que o aparelho mediu, que é o que permite comparar duas leituras do mesmo
-- pneu. Quem precisa do menor faz `min` sobre quatro elementos — é barato, e é
-- honesto sobre o que se sabe.
--
-- Migration nova em vez de editar a 0046: ela já está aplicada em produção
-- (implantada em 04/09/2026 20:19), e migration aplicada não se reescreve —
-- editar o arquivo não muda banco nenhum que já rodou. As tabelas estão
-- VAZIAS, então a troca não perde dado.
ALTER TABLE pne_inspecao DROP COLUMN IF EXISTS sulco_int_mm;
ALTER TABLE pne_inspecao DROP COLUMN IF EXISTS sulco_cen_mm;
ALTER TABLE pne_inspecao DROP COLUMN IF EXISTS sulco_ext_mm;

-- As medidas na ordem em que foram tiradas, em milímetros.
ALTER TABLE pne_inspecao ADD COLUMN IF NOT EXISTS sulcos_mm NUMERIC(5,2)[];

-- Pneu DIRECIONAL gasta diferente de pneu de tração, e o instantâneo traz o
-- campo preenchido em 8.572 de 8.572 — comparar CPK sem separar os dois é
-- comparar coisas que se desgastam por motivos diferentes.
ALTER TABLE pne_modelo ADD COLUMN IF NOT EXISTS direcional BOOLEAN;
