-- Previsão de fechamento: ajuste manual, snapshot diário e a trilha.
--
-- As tabelas já nasceram com o prefixo `prev_` no SQLite, então não há
-- renomeação aqui — a regra é não disputar nome, não usar um prefixo específico.
--
-- REGRA CENTRAL (herdada do orçamento): recalcular a previsão NUNCA apaga o
-- ajuste manual. O efetivo é `previsto_calculado + delta` (ou o valor
-- absoluto), resolvido no motor, não no banco.
--
-- `criado_em`/`quando` continuam TEXT nesta passada. O DEFAULT do SQLite era
-- `datetime('now','localtime')`; aqui é `to_char(now(), ...)`, que formata no
-- fuso da sessão — mesmo resultado num servidor local, e mesmo formato de
-- string, que é o que a tela lê.

CREATE TABLE IF NOT EXISTS prev_ajuste(
    mes       text NOT NULL,
    linha     text NOT NULL,
    tipo      text NOT NULL CHECK (tipo IN ('delta','valor')),
    valor     double precision NOT NULL,
    motivo    text NOT NULL,
    autor     text,
    criado_em text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    PRIMARY KEY (mes, linha)
);

CREATE TABLE IF NOT EXISTS prev_snapshot(
    data               text NOT NULL,
    mes                text NOT NULL,
    linha              text NOT NULL,
    previsto_base      double precision NOT NULL,
    previsto_otim      double precision,
    previsto_pess      double precision,
    realizado_contabil double precision,
    estrategia         text,
    PRIMARY KEY (data, mes, linha)
);

CREATE TABLE IF NOT EXISTS prev_log(
    id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quando  text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    autor   text,
    acao    text NOT NULL,
    detalhe text
);

CREATE INDEX IF NOT EXISTS ix_prev_snap_mes ON prev_snapshot(mes, data);

COMMENT ON TABLE prev_ajuste IS
    'Ajuste manual por mês e linha da DRE. Recalcular a previsão não apaga.';
COMMENT ON TABLE prev_snapshot IS
    'Foto diária do previsto: é como se compara o que se dizia ontem com o que
     aconteceu.';
COMMENT ON TABLE prev_log IS
    'Quem ajustou e quem APAGOU ajuste — em controladoria, a segunda é a
     pergunta da auditoria.';
