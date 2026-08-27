-- CT-e de contrapartida: quem autoriza emitir por quem, com que certificado,
-- o que já foi emitido e os interruptores do módulo.
--
-- MÓDULO FISCAL. Emitir CT-e com o certificado do agregado é ASSINAR COMO ELE
-- — ato jurídico praticado por conta e ordem de terceiro. Daí a forma das
-- tabelas: autorização com ESCOPO e VALIDADE (sem data de fim o sistema não
-- sabe PARAR quando o agregado sai da frota), e trilha de auditoria que
-- responde meses depois quem autorizou o quê, inclusive contra o CÓRTEX.
--
-- O QUE NÃO ESTÁ AQUI, de propósito: a SENHA do certificado e o arquivo .pfx.
-- Ficam em `data/certificados/` com permissão 0600, fora do git — o
-- repositório do código é PÚBLICO, e senha de certificado em banco versionado
-- seria vazamento permanente. Ver `api/contrapartida/cadastro.py`.
--
-- O número 0010 e não 0009: o 0009 foi aplicado em produção por outra frente
-- (correio/agenda) antes de ser commitado. Ver docs/MIGRACAO_POSTGRES.md.

CREATE TABLE IF NOT EXISTS autorizacao (
  cnpj       text PRIMARY KEY,
  escopo     text NOT NULL,
  valida_de  text NOT NULL,
  valida_ate text NOT NULL,
  observacao text,
  criado_em  text NOT NULL,
  criado_por text NOT NULL
);

CREATE TABLE IF NOT EXISTS certificado (
  cnpj       text PRIMARY KEY,
  tipo       text NOT NULL,          -- 'A1' | 'A3'
  arquivo    text,                   -- nome do .pfx em data/certificados
  valida_ate text,
  titular    text,
  criado_em  text NOT NULL,
  criado_por text NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
  id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  quando  text NOT NULL,
  quem    text NOT NULL,
  acao    text NOT NULL,
  cnpj    text NOT NULL,
  detalhe text
);

-- O XML ASSINADO fica guardado: sem ele um documento autorizado não se
-- reconstrói. A chave e o protocolo provam que existe, mas quem precisa
-- IMPORTAR o documento (o ERP, a contabilidade, uma fiscalização) precisa do
-- arquivo. No SQLite `xml` e `xml_prot` entraram por ALTER depois; aqui já
-- nascem colunas.
CREATE TABLE IF NOT EXISTS emissao (
  id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  quando        text NOT NULL,
  quem          text NOT NULL,
  ambiente      text NOT NULL,
  cnpj_emitente text NOT NULL,
  serie         integer NOT NULL,
  numero        integer NOT NULL,
  chave         text,
  chave_origem  text NOT NULL,
  cstat         text,
  xmotivo       text,
  protocolo     text,
  xml           text,
  xml_prot      text
);

-- Interruptores do módulo: liberação de produção, ambiente ativo e o envio por
-- agregado (`envio:<cnpj>`). Mesma tabela porque são da mesma natureza — todos
-- ligam algo que emite documento fiscal sem alguém confirmando na hora.
CREATE TABLE IF NOT EXISTS lote_config (
  chave  text PRIMARY KEY,
  valor  text NOT NULL,
  quem   text NOT NULL,
  quando text NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_emissao_chave_origem ON emissao(chave_origem);
CREATE INDEX IF NOT EXISTS ix_auditoria_cnpj       ON auditoria(cnpj, id DESC);

COMMENT ON TABLE autorizacao IS
    'Escopo e validade do que cada agregado autorizou. A rotina não emite para
     quem não tem uma vigente.';
COMMENT ON TABLE auditoria IS
    'Quem autorizou emitir em nome de quem, e quando. Tem de ser respondível
     meses depois — inclusive contra o próprio CÓRTEX.';
COMMENT ON COLUMN certificado.tipo IS
    'A1 (arquivo, automatiza) ou A3 (token físico, NÃO automatiza — fica
     marcado como impedido, com o motivo, em vez de falhar na transmissão).';
