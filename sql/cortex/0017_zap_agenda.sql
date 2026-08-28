-- Rotinas agendadas de WhatsApp: qual MODELO sai, para quem, e quando.
--
-- Tabela própria, e não uma coluna `canal` em `correio_agenda`: o que se agenda
-- ali é um RELATÓRIO do catálogo (assunto + corpo HTML) e aqui é um MODELO com
-- variáveis preenchidas por um provedor. Os destinatários também são de tipos
-- diferentes. O que os dois compartilham é o QUANDO — e esse mora em
-- `api/agendamento.py`, importado pelos dois, justamente para a lógica delicada
-- (idempotência, janela de atraso, padrão desligado) não existir em duplicata.
--
-- `ultima_execucao` É A GUARDA CONTRA REENVIO, não um enfeite de histórico. Ela
-- é gravada MESMO QUANDO NÃO HOUVE ENVIO: sem isso a rotina se acha sempre na
-- primeira execução e dispara a cada passagem do agendador do Windows — foi
-- exatamente o defeito da automação de emissão de CT-e, e lá ficou invisível
-- por horas.
--
-- `dias_uteis` existe porque um resumo de faturamento no domingo sai com "sem
-- meta no dia" e vira ruído que ensina a ignorar o remetente.
--
-- NÃO HÁ CHAVE ESTRANGEIRA PARA `zap_modelos`: a agenda guarda a CHAVE do
-- modelo como texto, pelo mesmo motivo que a trilha guarda. Excluir um modelo
-- não pode apagar a rotina em silêncio — a rotina passa a recusar dizendo que o
-- modelo não existe, que é uma falha visível, e não uma linha que sumiu.

CREATE TABLE IF NOT EXISTS zap_agenda(
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    modelo           text    NOT NULL,
    destinatarios    text    NOT NULL,
    instancia        text,
    frequencia       text    NOT NULL DEFAULT 'diario',
    hora             text    NOT NULL DEFAULT '08:00',
    dia_semana       integer,
    dia_mes          integer,
    dias_uteis       integer NOT NULL DEFAULT 1,
    ativo            integer NOT NULL DEFAULT 0,
    ultima_execucao  text,
    ultimo_resultado text,
    criado_por       text    NOT NULL DEFAULT '',
    criado_em        text    NOT NULL DEFAULT '',
    alterado_por     text    NOT NULL DEFAULT '',
    alterado_em      text    NOT NULL DEFAULT ''
);

COMMENT ON TABLE zap_agenda IS
    'Rotinas agendadas de WhatsApp. Nascem DESLIGADAS: ausência de decisão
     nunca significa mandar mensagem para fora da empresa.';
COMMENT ON COLUMN zap_agenda.ultima_execucao IS
    'Marcada mesmo quando não houve envio — é o que impede a rotina de
     disparar a cada passagem do agendador do Windows.';
COMMENT ON COLUMN zap_agenda.modelo IS
    'CHAVE do modelo, como texto e sem chave estrangeira: excluir o modelo faz
     a rotina recusar com explicação, em vez de a rotina sumir junto.';
