-- Envio dos XML de PRODUCAO do CT-e de contrapartida para a contabilidade.
--
-- POR QUE UMA TABELA E NAO UM CARIMBO NA `emissao`
-- -----------------------------------------------
-- Sao dois fatos de naturezas diferentes: `emissao` responde "o que foi
-- transmitido a SEFAZ" e nao pode ganhar coluna por causa de cada consumidor
-- do arquivo. Aqui a pergunta e outra - "este XML ja saiu para a contabilidade,
-- quando, para quem, e se falhou por que" - e ela tem historico proprio
-- (tentativa, erro, reenfileiramento) que nao pertence ao registro fiscal.
--
-- A CHAVE E A CHAVE DO CT-e, e e PRIMARY KEY de proposito: e o que impede o
-- mesmo documento de ser mandado duas vezes. A contabilidade importa por
-- chave; XML repetido nao duplica documento, mas gera conferencia manual toda
-- vez que alguem tenta entender por que chegou de novo.
--
-- Linha existe = ja foi TENTADO. `ok` diz se chegou a sair.

CREATE TABLE IF NOT EXISTS cte_xml_email (
  chave         text PRIMARY KEY,
  cnpj_emitente text,
  serie         integer,
  numero        integer,
  -- carimbo da transmissao a SEFAZ (`emissao.quando`), para a tela ordenar
  -- pelo documento e nao pela hora em que o e-mail saiu
  emitido_em    text,
  -- Quantas vezes JA se tentou mandar este arquivo. Existe para que uma falha
  -- permanente (endereco errado, anexo recusado) pare de ser retentada a cada
  -- rodada do lote em vez de encher a trilha para sempre. Ao bater o teto o
  -- documento fica PARADO e visivel na tela - nunca descartado em silencio.
  tentativas    integer NOT NULL DEFAULT 0,
  enviado_em    text,
  ok            boolean NOT NULL DEFAULT false,
  erro          text,
  destinatarios text
);

-- A consulta feita a cada rodada do lote: o que ainda falta mandar.
CREATE INDEX IF NOT EXISTS ix_cte_xml_email_pendente
    ON cte_xml_email(ok, tentativas);

COMMENT ON TABLE cte_xml_email IS
    'Quais XML de PRODUCAO ja foram para a contabilidade. Homologacao NUNCA
     entra: documento de teste nao tem valor fiscal e escriturar um seria pior
     que nao mandar nenhum.';
COMMENT ON COLUMN cte_xml_email.tentativas IS
    'Teto de tentativas para que falha permanente nao vire retentativa eterna.
     Ao bater o teto o documento fica PARADO e aparece na tela, com o erro -
     nunca sai da fila em silencio.';
