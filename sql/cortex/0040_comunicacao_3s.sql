-- 0040 · Foto diária da comunicação da frota com as rastreadoras.
--
-- POR QUE GRAVAR ISTO, se o número sai de uma consulta ao ERP a qualquer hora:
-- porque o que interessa não é o número de hoje, é a CURVA. A pergunta que
-- originou a tabela é "as 142 carretas da 3S que nunca comunicaram estão
-- diminuindo?", e essa pergunta não se responde com uma leitura só. O ERP
-- guarda posição, não guarda "quantas estavam mudas no dia 3" — reconstruir
-- isso depois é impossível, porque a carreta que passar a comunicar amanhã
-- apaga o rastro de que estava muda hoje.
--
-- UMA LINHA POR DIA FECHADO E POR RASTREADORA. O dia é fechado de propósito
-- (fecha às 23:59): o alerta das 09:00 que medisse o dia em curso contaria
-- como muda toda carreta que ainda não reportou desde a meia-noite, e o
-- número da manhã não teria nada a ver com o da tarde. Régua matinal mede dia
-- FECHADO — a mesma regra do aviso de faturamento.
--
-- `nunca` é coluna separada de `mudo_15d` porque são coisas diferentes:
-- ausência de leitura (pode ser equipamento não instalado, conta não
-- provisionada, integração que não traz) contra leitura velha (reportava e
-- parou). Somar as duas apagaria justamente a distinção que o painel existe
-- para mostrar.

CREATE TABLE IF NOT EXISTS com_status_diario (
  dia            date        NOT NULL,
  rastreadora    text        NOT NULL,
  com_motor      boolean     NOT NULL,
  frota          integer     NOT NULL,
  comunicou      integer     NOT NULL,   -- teve posição NO dia fechado
  mudo_15d       integer     NOT NULL,   -- última posição há mais de 15 dias
  nunca          integer     NOT NULL,   -- nenhuma posição, jamais
  medido_em      timestamp   NOT NULL DEFAULT now(),
  PRIMARY KEY (dia, rastreadora, com_motor)
);

-- A coleta é IDEMPOTENTE: rodar duas vezes no mesmo dia atualiza, nunca
-- duplica. O agendador do Windows repete quando a máquina acorda, e uma
-- segunda linha para o mesmo dia dobraria a frota no gráfico.
COMMENT ON TABLE com_status_diario IS
  'Foto diária (dia FECHADO) da comunicação por rastreadora e por tipo de '
  'equipamento. Alimenta o alerta de WhatsApp e a curva de evolução da 3S.';

CREATE INDEX IF NOT EXISTS ix_com_status_dia ON com_status_diario (dia DESC);
