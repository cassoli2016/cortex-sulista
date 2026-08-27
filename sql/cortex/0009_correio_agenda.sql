-- Relatorios por e-mail em horario agendado.
--
-- Separado de `correio_envios` (a trilha do que saiu) porque sao perguntas
-- diferentes: aqui esta a REGRA - o que mandar, para quem, quando - e la o
-- HISTORICO de cada tentativa. Juntar as duas faria a regra sumir no meio do
-- volume de envios, que cresce todo dia.
CREATE TABLE IF NOT EXISTS correio_agenda(
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    relatorio       text    NOT NULL,
    destinatarios   text    NOT NULL,
    -- 'diario' | 'semanal' | 'mensal'. Nao ha "a cada N horas" de proposito:
    -- relatorio que chega varias vezes por dia deixa de ser lido depois da
    -- primeira semana, e o que se queria era um aviso - que e push, nao
    -- e-mail.
    frequencia      text    NOT NULL DEFAULT 'diario',
    -- HH:MM local. O agendador do sistema dispara de tempos em tempos e quem
    -- decide se ja passou a hora e o CORTEX, pelo mesmo desenho da emissao de
    -- contrapartida: mudar o horario aqui vale na hora, sem reinstalar tarefa.
    hora            text    NOT NULL DEFAULT '07:00',
    -- 1=segunda ... 7=domingo (ISO). So vale em 'semanal'.
    dia_semana      integer,
    -- 1..28. So vale em 'mensal'. Limitado a 28 porque 29/30/31 nao existem
    -- em todo mes e o relatorio simplesmente nao sairia em fevereiro.
    dia_mes         integer,
    ativo           boolean NOT NULL DEFAULT false,
    ultima_execucao text,
    ultimo_resultado text,
    criado_por      text,
    criado_em       text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    alterado_por    text,
    alterado_em     text
);

CREATE INDEX IF NOT EXISTS ix_correio_agenda_ativo
    ON correio_agenda(ativo, relatorio);

COMMENT ON COLUMN correio_agenda.ativo IS
    'PADRAO FALSE. Ausencia de decisao nunca pode significar "manda e-mail
     para fora da empresa" - mesmo principio da automacao de emissao.';
COMMENT ON COLUMN correio_agenda.ultima_execucao IS
    'Marca a PASSAGEM da rotina, gravada mesmo quando nao houve o que enviar.
     Sem isto a rotina se acha sempre na primeira execucao e reenvia a cada
     disparo do agendador - defeito ja vivido na emissao de contrapartida.';
COMMENT ON COLUMN correio_agenda.dia_mes IS
    'Limitado a 28: 29, 30 e 31 nao existem em todo mes, e um relatorio
     mensal marcado no dia 31 nao sairia em fevereiro nenhum.';
