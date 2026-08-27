-- Orçamento: versões, linhas (conta × mês) e a trilha de ajuste manual.
--
-- Maior store da migração — 21.696 linhas.
--
-- REGRA CENTRAL: `valor_efetivo = coalesce(valor_ajustado, valor_baseline)`.
-- Regerar o baseline recalcula APENAS `valor_baseline`; o ajuste manual
-- sobrevive, senão recalcular jogaria fora o trabalho da controladoria. Por
-- isso `valor_ajustado` é NULLABLE e NULL significa "não ajustado" — nunca
-- zero, que é um ajuste legítimo para zerar uma conta.
--
-- As quatro colunas que no SQLite nasceram de `ALTER TABLE` condicional
-- (`meses_base`, `metodo`, `aprovado_em`, `aprovado_por`) entram aqui como
-- coluna normal.
--
-- `meses_base` é JSON com os 'AAAA-MM' usados na derivação: é o que permite ao
-- comparativo saber quais meses do ano orçado estavam DENTRO da base (espelho
-- de si mesmos, comparação circular). Continua `text` nesta passada — vira
-- `jsonb` quando as datas virarem `timestamp`, não antes.

CREATE TABLE IF NOT EXISTS orc_versao(
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ano             integer NOT NULL,
    rotulo          text    NOT NULL,
    status          text    NOT NULL DEFAULT 'rascunho',
    fator_tendencia double precision NOT NULL DEFAULT 0,
    criado_em       text    NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    criado_por      text,
    meses_base      text,
    metodo          text    NOT NULL DEFAULT 'espelho',
    aprovado_em     text,
    aprovado_por    text
);

CREATE TABLE IF NOT EXISTS orc_linha(
    versao_id      integer NOT NULL REFERENCES orc_versao(id) ON DELETE CASCADE,
    conta          text    NOT NULL,
    mes            integer NOT NULL CHECK (mes BETWEEN 1 AND 12),
    valor_baseline double precision NOT NULL DEFAULT 0,
    valor_ajustado double precision,
    origem         text    NOT NULL DEFAULT 'sem_base',
    meses_com_dado integer NOT NULL DEFAULT 0,
    ajustado_em    text,
    ajustado_por   text,
    PRIMARY KEY (versao_id, conta, mes)
);

CREATE TABLE IF NOT EXISTS orc_log(
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    versao_id  integer NOT NULL,
    conta      text    NOT NULL,
    mes        integer NOT NULL,
    valor_de   double precision,
    valor_para double precision,
    quem       text,
    quando     text NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE INDEX IF NOT EXISTS ix_orc_linha_versao ON orc_linha(versao_id);
CREATE INDEX IF NOT EXISTS ix_orc_log_versao   ON orc_log(versao_id, id DESC);

COMMENT ON COLUMN orc_linha.valor_ajustado IS
    'NULL = não ajustado. Zero é ajuste legítimo (zerar a conta) e por isso os
     dois não podem ser a mesma coisa.';
COMMENT ON COLUMN orc_versao.status IS
    'rascunho | aprovado | arquivada. Arquivada é registro histórico: não
     reabre, não aprova, não ajusta.';
