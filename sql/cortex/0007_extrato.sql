-- Extrato bancário importado (OFX/CSV) — contas, importações, lançamentos e
-- as âncoras de saldo.
--
-- As tabelas já nasceram com o prefixo `ext_`.
--
-- `UNIQUE (conta_id, chave)` é o que torna o re-upload idempotente: a chave é
-- o FITID quando o banco manda um, e o hash de (dt, valor, histórico,
-- numerodoc) + a ordem da ocorrência quando não manda. Sem essa unicidade,
-- subir o mesmo arquivo duas vezes dobraria o extrato.
--
-- `tipo` (C/D) NUNCA é confiado ao arquivo de entrada: é derivado do sinal do
-- valor na gravação. Continua `text` aqui porque é isso que a tela lê.
--
-- `ext_saldo.origem` implementa a precedência 'linha' > 'ledgerbal': quem
-- manda um extrato por dia reenvia o LEDGERBAL (posição consolidada) com data
-- de um dia anterior, e ele sobrescrevia a linha impressa daquele dia, que é
-- a boa. Medido no Safra: R$ 10.502,92 do consolidado contra R$ 657,38 da
-- conta corrente, R$ 9.845,54 de divergência com o ERP por um número que o
-- próprio arquivo já trazia certo.

CREATE TABLE IF NOT EXISTS ext_conta(
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ident       text NOT NULL UNIQUE,
    rotulo      text NOT NULL,
    erp_banco   integer,
    erp_agencia text,
    erp_conta   text,
    mapa_csv    text,
    criado_em   text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS ext_importacao(
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id   integer NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
    arquivo    text NOT NULL,
    formato    text NOT NULL,
    dt_de      text,
    dt_ate     text,
    novas      integer NOT NULL DEFAULT 0,
    duplicadas integer NOT NULL DEFAULT 0,
    ignoradas  integer NOT NULL DEFAULT 0,
    quando     text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS ext_lancamento(
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id      integer NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
    importacao_id integer NOT NULL REFERENCES ext_importacao(id) ON DELETE CASCADE,
    dt            text NOT NULL,
    valor         double precision NOT NULL,
    tipo          text NOT NULL,
    historico     text NOT NULL DEFAULT '',
    numerodoc     text NOT NULL DEFAULT '',
    fitid         text,
    chave         text NOT NULL,
    UNIQUE (conta_id, chave)
);

CREATE TABLE IF NOT EXISTS ext_saldo(
    conta_id      integer NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
    dt            text NOT NULL,
    saldo         double precision NOT NULL,
    importacao_id integer REFERENCES ext_importacao(id) ON DELETE CASCADE,
    origem        text NOT NULL DEFAULT 'ledgerbal',
    PRIMARY KEY (conta_id, dt)
);

CREATE INDEX IF NOT EXISTS ix_ext_lanc_conta_dt ON ext_lancamento(conta_id, dt);
CREATE INDEX IF NOT EXISTS ix_ext_lanc_imp      ON ext_lancamento(importacao_id);

COMMENT ON TABLE ext_lancamento IS
    'Lançamentos importados. A unicidade (conta_id, chave) é o que faz o
     re-upload do mesmo arquivo não duplicar nada.';
COMMENT ON COLUMN ext_saldo.origem IS
    '"linha" (o banco imprimiu o saldo do dia) vence "ledgerbal" (posição
     final do arquivo). Ver gravar_saldo_extrato.';
