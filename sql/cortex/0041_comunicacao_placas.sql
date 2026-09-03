-- 0041 · Quais placas, e não só quantas.
--
-- A 0040 grava a CONTAGEM do dia, que é o que a curva precisa. Isto aqui
-- responde outra pergunta: QUEM. Ela apareceu quando o aviso diário passou a
-- levar anexo só "quando a lista mudar" — e "mudou" não se decide com número.
-- 142 ontem e 142 hoje pode ser a mesma lista parada ou três carretas que
-- voltaram e três que caíram, que é notícia e some na contagem.
--
-- Guardar a placa também é o que permite dizer o que mudou em vez de só que
-- mudou: "entraram 3, saíram 1" é acionável; "142 → 142" não é.
--
-- POR QUE UMA TABELA E NÃO UMA COLUNA JSON na 0040: a linha da 0040 é por
-- (dia, rastreadora, com_motor) e esta é por (dia, placa). Naturezas
-- diferentes, e a lista dentro de um JSON vira dado que só o código lê —
-- ninguém consegue perguntar "desde quando esta placa está muda" sem
-- reprocessar tudo. Em linha, isso é um SELECT.
--
-- O volume é irrisório: ~430 linhas por dia, ~157 mil por ano.

CREATE TABLE IF NOT EXISTS com_placa_diaria (
  dia          date     NOT NULL,
  placa        text     NOT NULL,
  rastreadora  text     NOT NULL,
  com_motor    boolean  NOT NULL,
  -- 'comunicou' | 'parou' (até 15 dias) | 'mudo15' | 'nunca'
  situacao     text     NOT NULL,
  ultima       date,                    -- nulo quando situacao = 'nunca'
  PRIMARY KEY (dia, placa)
);

COMMENT ON TABLE com_placa_diaria IS
  'Situação de comunicação de CADA placa no dia fechado. Responde "quem", '
  'enquanto com_status_diario responde "quantos".';

CREATE INDEX IF NOT EXISTS ix_com_placa_dia_rastr
  ON com_placa_diaria (dia DESC, rastreadora);
CREATE INDEX IF NOT EXISTS ix_com_placa_placa
  ON com_placa_diaria (placa, dia DESC);
