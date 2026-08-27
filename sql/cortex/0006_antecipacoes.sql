-- Antecipação de recebíveis: envios importados, títulos e sacados elegíveis.
--
-- Prefixo `ant_` porque `envios` já é do correio e `titulos` é nome genérico
-- demais para um schema que vai receber dez módulos.
--
-- As três colunas que no SQLite nasceram de `ALTER TABLE` condicional dentro
-- do `_conn()` (`impressao`, `vigente`, `origem`) entram aqui como coluna
-- normal: era exatamente esse remendo que a migration numerada substitui.
--
-- `origem` tem DEFAULT 'planilha' porque envio antigo é planilha por
-- definição — a API da Monkey não existia quando ele foi gravado.

CREATE TABLE IF NOT EXISTS ant_envios (
  id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts              text NOT NULL,
  usuario         text,
  arquivo         text NOT NULL,
  portal          text NOT NULL,
  portal_rotulo   text,
  titulos         integer NOT NULL,
  valor_nominal   double precision NOT NULL,
  valor_saldo     double precision NOT NULL,
  total_declarado double precision,
  divergencia     double precision,
  rejeitadas      integer NOT NULL DEFAULT 0,
  impressao       text,
  vigente         integer NOT NULL DEFAULT 1,
  origem          text NOT NULL DEFAULT 'planilha'
);

CREATE TABLE IF NOT EXISTS ant_titulos (
  envio_id      integer NOT NULL REFERENCES ant_envios(id) ON DELETE CASCADE,
  titulo        text, documento text, emissao text, vencimento text,
  valor_nominal double precision, valor_saldo double precision,
  antecipavel   integer,
  situacao      text, cnpj_cedente text, nome_cedente text,
  cnpj_sacado   text, nome_sacado text, chave text, id_portal text
);

CREATE INDEX IF NOT EXISTS ix_ant_tit_envio ON ant_titulos(envio_id);
CREATE INDEX IF NOT EXISTS ix_ant_tit_doc   ON ant_titulos(documento);

CREATE TABLE IF NOT EXISTS ant_sacados (
  cnpj          text PRIMARY KEY,
  nome          text,
  portal        text,
  elegivel      integer NOT NULL DEFAULT 1,
  origem        text,          -- 'arquivo' ou 'manual'
  atualizado_em text,
  observacao    text
);

COMMENT ON TABLE ant_envios IS
    'Cada arquivo importado, com quem enviou e os totais. `vigente=1` marca a
     posição ATUAL daquele portal — portais diferentes coexistem.';
COMMENT ON TABLE ant_titulos IS
    'Linhas do arquivo vigente de cada portal. Os títulos do envio anterior
     são apagados, senão o banco cresce 226 linhas por importação para sempre.';
COMMENT ON TABLE ant_sacados IS
    'Clientes com convênio de antecipação. `origem=manual` vence a importação:
     sacado desligado à mão não pode voltar a cada arquivo novo.';
