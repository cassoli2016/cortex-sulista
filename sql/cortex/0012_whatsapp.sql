-- Trilha das mensagens de WhatsApp enviadas pelo CORTEX (Z-API).
--
-- Mesma separacao do `correio_envios`: o `audit_log` responde "quem mexeu no
-- sistema" e esta responde "o que saiu para fora da empresa". Prefixo `zap_`
-- pela regra dos modulos -- `envios` ja existe duas vezes no schema.
--
-- POR QUE ESTA TABELA E TAMBEM UM MECANISMO DE PROTECAO, nao so um historico:
-- o limite de envio (envio.py) e calculado LENDO daqui. A propria Z-API
-- documenta que o fator numero 1 de banimento do numero e a quantidade de
-- DESTINATARIOS DISTINTOS alcancados numa janela curta -- nao o total de
-- mensagens. Por isso o indice e por (telefone, ts): a pergunta que o sistema
-- faz antes de cada envio e "quantos numeros diferentes ja falei hoje".
--
-- `ok` continua integer 0/1 pela mesma razao do correio: e o formato que a
-- tela e os resumos ja somam, e trocar o tipo aqui dobraria a superficie de
-- erro sem entregar nada.

CREATE TABLE IF NOT EXISTS zap_envios(
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts         text    NOT NULL,
    usuario    text    NOT NULL DEFAULT '',
    -- SEMPRE normalizado (so digitos, com DDI). Guardar o que o usuario
    -- digitou faria o contador de destinatarios distintos contar
    -- "47999998888", "+55 47 99999-8888" e "5547999998888" como tres numeros
    -- diferentes -- e o limite que protege a conta nunca dispararia.
    telefone   text    NOT NULL,
    mensagem   text    NOT NULL DEFAULT '',
    origem     text    NOT NULL DEFAULT '',
    ok         integer NOT NULL DEFAULT 0,
    erro       text    NOT NULL DEFAULT '',
    -- id devolvido pela Z-API (messageId). E o unico jeito de casar uma linha
    -- daqui com o que aparece no painel deles quando algo e contestado.
    message_id text    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_zap_envios_ts  ON zap_envios(ts);
CREATE INDEX IF NOT EXISTS ix_zap_envios_tel ON zap_envios(telefone, ts);

COMMENT ON TABLE zap_envios IS
    'Toda TENTATIVA de envio por WhatsApp, inclusive a que falhou. Tambem e a
     base do limite de destinatarios distintos que protege o numero de ser
     banido pelo WhatsApp.';
