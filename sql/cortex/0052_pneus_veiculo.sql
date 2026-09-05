-- O QUE O VEICULO E, para o modulo proprio poder validar.
--
-- `pne_veiculo` existia com placa e filial e nada mais: `diagrama_id` estava
-- nulo nas 292 linhas. Sem ele nao ha como afirmar que a posicao "3DE" existe
-- naquele veiculo — e um cadastro proprio de montagem aceitaria qualquer coisa
-- digitada, que e o oposto de "modulo proprio".
--
-- `GET /api/v3/vehicles` traz `tiresLayout.id` (o diagrama) e, de quebra, dois
-- numeros que valem por si: quantos pneus o veiculo TEM e quantos ele DEVERIA
-- ter. A diferenca e um veiculo rodando incompleto, e isso ninguem media.
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS tem_motor        BOOLEAN;
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS km_atual         NUMERIC(12,1);
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS pneus_instalados SMALLINT;
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS pneus_esperados  SMALLINT;
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS estepes          SMALLINT;
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS ativo            BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pne_veiculo ADD COLUMN IF NOT EXISTS frota            TEXT;

CREATE INDEX IF NOT EXISTS pne_veiculo_diagrama ON pne_veiculo (diagrama_id);
