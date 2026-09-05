-- O HODOMETRO NA INSPECAO — o que torna a taxa de desgaste DIRETA.
--
-- Ate aqui a taxa saia de uma derivacao: duas medicoes de sulco, a placa, e o
-- km que aquela placa rodou entre as datas segundo o abastecimento do ERP.
-- Funciona, foi conferido contra a Prolog (razao mediana 0,983), mas depende
-- de tres fontes concordarem.
--
-- `GET /api/v3/tire-inspections/vehicles` devolve `odometerReading` DENTRO de
-- cada inspecao. Com ele a conta vira uma subtracao entre duas leituras do
-- mesmo hodometro — sem placa, sem engate, sem janela de 365 dias. A derivacao
-- continua existindo como plano B para o pneu que nao tem duas inspecoes, e
-- como SEGUNDO CAMINHO para conferir esta.
--
-- FAIXA FISICA na leitura, nao aqui: hodometro de 1 km e de 7,3 milhoes ja
-- apareceram no mesmo campo em `pne_evento`, e quem filtra e
-- `api/pneus/historico._odometro`. A coluna aceita nulo de proposito — nem
-- toda inspecao acontece com o pneu num veiculo.
ALTER TABLE pne_inspecao ADD COLUMN IF NOT EXISTS km_veiculo NUMERIC(12,1);

-- A serie de desgaste le (pneu, data) em ordem; sem este indice ela varre a
-- tabela inteira por pneu.
CREATE INDEX IF NOT EXISTS pne_inspecao_pneu_km
  ON pne_inspecao (pneu_id, medido_em) WHERE km_veiculo IS NOT NULL;
