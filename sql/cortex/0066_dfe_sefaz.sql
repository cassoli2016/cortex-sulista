-- 0066 · A caixa de entrada da SEFAZ: os documentos fiscais emitidos CONTRA a
-- Sulista (e os dela), recolhidos pelo serviço nacional de Distribuição de DFe.
--
-- POR QUE O XML VAI PARA O BANCO, E NÃO PARA data/
-- ================================================
--
-- Documento fiscal eletrônico tem guarda de CINCO ANOS, e a guarda é do XML
-- AUTORIZADO — não do PDF, não do resumo. O que já existe em `data/` é cache
-- reconstruível (telemetria, pneus, premiação) e segredo em arquivo: nenhuma
-- das duas coisas é isto.
--
-- E há uma razão operacional que decide sozinha: **o backup que a casa PROVA
-- todo dia é o do PostgreSQL** (`scripts/testar_restauracao.py` restaura o
-- dump, sobe a API em cima dele e compara o volume POR TABELA). Guardar cinco
-- anos de obrigação fiscal fora do único backup verificado seria confiar num
-- backup que ninguém testou.
--
-- Volume não é objeção: um XML de NF-e tem 5 a 15 KB. Mesmo a 5.000
-- documentos/mês, cinco anos cabem em poucos GB — o banco da casa hoje tem
-- 434 MB, e `xml` em `text` é comprimido pelo TOAST sem que ninguém peça.
--
-- SÃO DEZ CAIXAS, NÃO UMA
-- -----------------------
-- A Sulista é um CNPJ raiz (76.104.397) com onze filiais, dez ativas. O
-- serviço de distribuição é consultado por CNPJ de **14 dígitos**, e cada um
-- tem a sua própria sequência de NSU. Por isso `dfe_caixa` é uma linha POR
-- CNPJ, e o NSU é chave composta com ele — misturar as sequências faria uma
-- filial pular os documentos da outra, em silêncio.

-- ---------------------------------------------------------------- a caixa
--
-- O NSU É O ESTADO INTEIRO DA RECOLHA. É um contador que a SEFAZ mantém por
-- destinatário: pede-se "o que veio DEPOIS do NSU X" e ela devolve o próximo
-- lote. Perder este número não perde documento (dá para recomeçar do zero),
-- mas custa reler tudo — e o serviço tem freio de consumo indevido (cStat 656)
-- que pune quem consulta demais. Por isso ele é gravado a CADA lote, e não no
-- fim da varredura.
CREATE TABLE IF NOT EXISTS dfe_caixa (
  cnpj             varchar(14)  PRIMARY KEY,
  apelido          text,
  -- A UF é do INTERESSADO, e vai no `cUFAutor` da consulta. Não é enfeite:
  -- é ela que diz à SEFAZ quem está perguntando, e as filiais da Sulista
  -- estão em sete estados diferentes.
  uf               varchar(2),
  -- '000000000000000' = nunca consultada; a primeira varredura traz o histórico
  -- que a SEFAZ ainda guarda (ela retém cerca de três meses).
  ultimo_nsu       varchar(15)  NOT NULL DEFAULT '000000000000000',
  -- O MAIOR NSU que EXISTE na SEFAZ, que ela devolve em toda resposta. A
  -- distância entre ele e `ultimo_nsu` é quanto falta recolher — e é o único
  -- jeito de a tela dizer "faltam 400" em vez de "talvez tenha mais".
  max_nsu          varchar(15),
  ultima_consulta  timestamptz,
  ultimo_cstat     varchar(4),
  ultimo_motivo    text,
  -- Filial inativa no ERP não se consulta: gastaria a cota de um CNPJ que não
  -- recebe mais nota.
  ativo            boolean      NOT NULL DEFAULT true,
  criado_em        timestamptz  NOT NULL DEFAULT now()
);

-- --------------------------------------------------------- os documentos
--
-- IDEMPOTENTE POR (cnpj, nsu), e isso não é zelo: reler um trecho da sequência
-- é normal (recomeço após perda do controle, varredura manual), e sem a chave
-- a segunda leitura duplicaria a nota inteira.
--
-- `completo` É O CAMPO QUE MAIS IMPORTA AQUI. A SEFAZ devolve, para uma NF-e
-- de entrada, apenas o RESUMO (`resNFe`: chave, emitente, valor, situação)
-- enquanto o destinatário não manifestar ciência da operação. O XML inteiro
-- (`procNFe`) só vem DEPOIS da manifestação. Então o mesmo NSU pode chegar
-- duas vezes com conteúdo diferente, e a segunda é um UPGRADE: a gravação faz
-- ON CONFLICT DO UPDATE e nunca deixa um resumo sobrescrever um documento
-- completo (a regra vive no módulo, com teste).
CREATE TABLE IF NOT EXISTS dfe_documento (
  cnpj          varchar(14)  NOT NULL,
  nsu           varchar(15)  NOT NULL,
  -- o `schema` que a própria SEFAZ carimba no lote: resNFe_v1.01, procNFe_v4.00,
  -- resEvento_v1.01, procEventoNFe_v1.00 … É dele que sai o tipo, e guardá-lo
  -- cru permite entender um documento que o parser de hoje não conhece.
  esquema       text,
  tipo          text,                    -- 'nfe' | 'cte' | 'evento' | 'desconhecido'
  chave         varchar(44),
  emitente      varchar(14),
  emitente_nome text,
  destinatario  varchar(14),
  valor         numeric(15,2),
  emitido_em    timestamptz,
  -- situação da NF-e no resumo: 1 autorizada, 2 denegada, 3 cancelada.
  -- NÃO é derivada de ausência de campo — vem escrita no documento.
  situacao      text,
  completo      boolean      NOT NULL DEFAULT false,
  xml           text         NOT NULL,
  recebido_em   timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (cnpj, nsu)
);

-- A chave se repete entre CNPJs (a mesma nota chega ao destinatário e pode
-- voltar num evento), então o índice é de busca, não único.
CREATE INDEX IF NOT EXISTS ix_dfe_documento_chave ON dfe_documento (chave);
CREATE INDEX IF NOT EXISTS ix_dfe_documento_emitido
  ON dfe_documento (cnpj, emitido_em DESC);
-- O índice que a tela de pendências usa: o que ainda está só no resumo.
CREATE INDEX IF NOT EXISTS ix_dfe_documento_incompleto
  ON dfe_documento (cnpj) WHERE NOT completo;

-- ------------------------------------------------------- a manifestação
--
-- MANIFESTAR É ESCREVER NA SEFAZ, com efeito legal e prazo — é o único ponto
-- desta recolha que não é leitura. Por isso tem tabela própria e trilha: o que
-- foi manifestado, por quem, quando, e o que a SEFAZ respondeu.
--
-- A CIÊNCIA (210210) é o evento que destrava o XML completo e não afirma nada
-- sobre a operação — é "eu vi". Os outros três AFIRMAM: confirmação (210200),
-- desconhecimento (210220) e operação não realizada (210240) têm consequência
-- fiscal e não se automatizam. O módulo só emite ciência sozinho; os demais
-- exigem alguém pedindo, e é esta tabela que guarda quem foi.
CREATE TABLE IF NOT EXISTS dfe_manifestacao (
  id           bigserial    PRIMARY KEY,
  cnpj         varchar(14)  NOT NULL,
  chave        varchar(44)  NOT NULL,
  evento       varchar(6)   NOT NULL,   -- 210200 | 210210 | 210220 | 210240
  sequencia    smallint     NOT NULL DEFAULT 1,
  justificativa text,                   -- obrigatória em 210220 e 210240
  quem         text,                    -- e-mail do usuário; 'sistema' na ciência automática
  enviado_em   timestamptz  NOT NULL DEFAULT now(),
  cstat        varchar(4),
  motivo       text,
  protocolo    text,
  xml_retorno  text
);

CREATE INDEX IF NOT EXISTS ix_dfe_manifestacao_chave
  ON dfe_manifestacao (chave, enviado_em DESC);
-- Um evento por (chave, evento, sequência): reenviar o mesmo é o que a SEFAZ
-- rejeita com "evento já registrado", e é melhor descobrir aqui.
CREATE UNIQUE INDEX IF NOT EXISTS ux_dfe_manifestacao
  ON dfe_manifestacao (cnpj, chave, evento, sequencia);
