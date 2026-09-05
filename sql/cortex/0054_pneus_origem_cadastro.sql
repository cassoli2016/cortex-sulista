-- QUEM CRIOU CADA CADASTRO — a coluna que protege o trabalho digitado aqui.
--
-- `pne_evento` e `pne_inspecao` ja sabiam dizer se a linha veio da Prolog ou
-- foi escrita pela casa. Os SEIS CADASTROS nao sabiam: pneu, modelo, veiculo,
-- diagrama, motivo e vida. Enquanto tudo vinha importado isso nao doia — a
-- partir do momento em que alguem cadastra um pneu aqui, doi muito.
--
-- O MODO DE FALHA que ela existe para impedir: a coleta roda de 20 em 20
-- minutos e grava por `ON CONFLICT ... DO UPDATE`. Um pneu cadastrado no
-- CORTEX que por acaso colidisse com a chave de um da Prolog seria
-- SOBRESCRITO na passada seguinte — sem erro, sem log, e a pessoa que digitou
-- veria o proprio trabalho virar outra coisa. Com a coluna, a coleta pode (e
-- passa a) pular a linha de origem `cortex`.
--
-- O PADRAO E `cortex` DE PROPOSITO. Quem insere sem dizer a origem e o codigo
-- da casa; a coleta passa a dizer `prolog` explicitamente. Errar para o lado de
-- "isto e nosso, nao sobrescreva" e o lado seguro: no pior caso uma linha
-- importada deixa de ser atualizada e alguem repara; no outro lado, trabalho
-- digitado some.
--
-- AS LINHAS QUE JA EXISTEM SAO TODAS DA PROLOG — nada foi cadastrado aqui
-- ainda — entao o backfill e literal, nao heuristica.

ALTER TABLE pne_pneu     ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'cortex';
ALTER TABLE pne_modelo   ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'cortex';
ALTER TABLE pne_veiculo  ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'cortex';
ALTER TABLE pne_diagrama ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'cortex';
ALTER TABLE pne_motivo   ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'cortex';
ALTER TABLE pne_vida     ADD COLUMN IF NOT EXISTS origem TEXT NOT NULL DEFAULT 'cortex';

-- BACKFILL PELO `prolog_id`, nao por "tudo que existe hoje": o segundo daria
-- certo agora e erraria se esta migration fosse reaplicada depois de alguem ja
-- ter cadastrado algo. Quem tem id do fornecedor veio do fornecedor.
UPDATE pne_pneu     SET origem = 'prolog' WHERE prolog_id IS NOT NULL;
UPDATE pne_modelo   SET origem = 'prolog' WHERE prolog_id IS NOT NULL;
UPDATE pne_veiculo  SET origem = 'prolog' WHERE prolog_id IS NOT NULL;
UPDATE pne_diagrama SET origem = 'prolog' WHERE prolog_id IS NOT NULL;
UPDATE pne_motivo   SET origem = 'prolog' WHERE prolog_id IS NOT NULL;
UPDATE pne_vida     SET origem = 'prolog' WHERE prolog_id IS NOT NULL;

-- `pne_modelo` nao tem `prolog_id` preenchido (o modelo e deduzido do pneu),
-- mas os 284 que existem hoje vieram todos da semeadura. Este UPDATE e datado
-- de proposito: so alcanca o que ja estava la quando a migration rodou.
UPDATE pne_modelo SET origem = 'prolog'
 WHERE origem = 'cortex' AND criado_em < now();

ALTER TABLE pne_pneu     ADD CONSTRAINT pne_pneu_origem_ck     CHECK (origem IN ('prolog','cortex')) NOT VALID;
ALTER TABLE pne_modelo   ADD CONSTRAINT pne_modelo_origem_ck   CHECK (origem IN ('prolog','cortex')) NOT VALID;
ALTER TABLE pne_veiculo  ADD CONSTRAINT pne_veiculo_origem_ck  CHECK (origem IN ('prolog','cortex')) NOT VALID;
ALTER TABLE pne_diagrama ADD CONSTRAINT pne_diagrama_origem_ck CHECK (origem IN ('prolog','cortex')) NOT VALID;
ALTER TABLE pne_motivo   ADD CONSTRAINT pne_motivo_origem_ck   CHECK (origem IN ('prolog','cortex')) NOT VALID;
ALTER TABLE pne_vida     ADD CONSTRAINT pne_vida_origem_ck     CHECK (origem IN ('prolog','cortex')) NOT VALID;

CREATE INDEX IF NOT EXISTS pne_pneu_origem    ON pne_pneu (origem);
CREATE INDEX IF NOT EXISTS pne_modelo_origem  ON pne_modelo (origem);
CREATE INDEX IF NOT EXISTS pne_veiculo_origem ON pne_veiculo (origem);
