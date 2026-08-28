-- Segunda instância da Z-API (número reserva) — e a consequência dela na trilha.
--
-- POR QUE A COLUNA É OBRIGATÓRIA, e não um detalhe de relatório: o freio que
-- protege o número LÊ desta tabela. Ele conta destinatários distintos do dia,
-- porque é esse o gatilho de banimento que a Z-API documenta. Com dois números,
-- esse contador tem de ser POR NÚMERO — a reputação é de cada linha telefônica,
-- e o WhatsApp não bane o número B por causa do que o A fez.
--
-- Sem a coluna, os dois erros possíveis são ruins em direções opostas:
--   * contador compartilhado -> mandar 60 pelo principal BLOQUEIA o reserva,
--     que não fez nada;
--   * sem contador nenhum    -> duas vezes o limite no mesmo dia, e a conta
--     inteira em risco.
--
-- 'principal' como DEFAULT porque toda linha que já existe saiu da única
-- instância que havia até aqui. Reescrever o histórico com outro rótulo faria
-- a trilha mentir sobre de onde a mensagem saiu.
--
-- O índice repete o de `(telefone, ts)` com a instância na frente: é a consulta
-- que roda A CADA mensagem ("quantos números diferentes ESTE aparelho já falou
-- hoje"), não uma vez por tela.

ALTER TABLE zap_envios
    ADD COLUMN IF NOT EXISTS instancia text NOT NULL DEFAULT 'principal';

CREATE INDEX IF NOT EXISTS ix_zap_envios_inst
    ON zap_envios(instancia, telefone, ts);

COMMENT ON COLUMN zap_envios.instancia IS
    'Qual aparelho enviou: principal ou backup. O limite diário de
     destinatários distintos é contado POR INSTÂNCIA — cada número tem a sua
     própria reputação no WhatsApp.';
