-- 0072 · O XML que chega POR FORA da caixa da SEFAZ — hoje, pelo e-mail
-- xml@sulista.com.br.
--
-- POR QUE NÃO CABE EM `dfe_documento`
-- ===================================
--
-- `dfe_documento` é a caixa da SEFAZ, e a chave primária dela é `(cnpj, nsu)`:
-- o CNPJ da FILIAL cuja caixa foi lida, e a posição do documento na sequência
-- daquela caixa. Os dois campos são o cursor da recolha, não descrições do
-- documento.
--
-- O XML que chega por e-mail não tem nenhum dos dois, e a razão é o motivo de
-- ele existir: **as pessoas mandam para lá justamente quando a Sulista NÃO é
-- parte na nota** — não é destinatária, nem transportadora, nem emitente. A
-- SEFAZ não entrega esse documento a ela em caixa nenhuma, porque legalmente
-- ele não é dela. Ele chega porque alguém precisa que a operação o tenha.
--
-- Enfiar isso ali com um NSU inventado corromperia o cursor: a varredura
-- calcula "até onde já li" a partir dessa coluna, e um número falso no meio
-- faz a recolha pular documento de verdade, em silêncio. Tabela separada, e
-- a UNIÃO acontece na LEITURA — que é onde a pergunta de quem opera vive
-- ("quais documentos eu tenho?"), e não onde os dois chegaram.
--
-- A IDENTIDADE AQUI É O ARQUIVO, NÃO O DOCUMENTO
-- ----------------------------------------------
-- A chave primária é o SHA-256 do XML, e isso resolve o problema real desta
-- porta: o MESMO arquivo chega várias vezes. O fornecedor manda, o cliente
-- reencaminha, alguém responde a todos, a mesma mensagem é lida de novo numa
-- recoleta. Byte a byte igual = uma linha só, sem depender de a mensagem ter
-- sido vista antes.
--
-- E o que NÃO se funde: dois arquivos DIFERENTES da mesma chave continuam dois
-- (a nota sem protocolo e a autorizada; a nota e o cancelamento dela). Fundir
-- pela chave apagaria um documento fiscal para caber num modelo — e o que se
-- guarda por cinco anos é o arquivo.
CREATE TABLE IF NOT EXISTS dfe_arquivo (
  sha256        char(64)     PRIMARY KEY,
  -- 'email' (a caixa xml@) ou 'upload' (alguém arrastou na tela). Dizer de
  -- onde veio não é enfeite: um XML que chegou por e-mail vale o que vale
  -- quem mandou, e isso é diferente de um documento que a SEFAZ entregou.
  origem        text         NOT NULL,
  esquema       text,                     -- nfeProc, NFe, cteProc, procEventoNFe…
  tipo          text,                     -- 'nfe' | 'cte' | 'mdfe' | 'evento' | 'desconhecido'
  chave         varchar(44),
  -- Autorizado E com protocolo. Um `<NFe>` sem `<protNFe>` é o documento sem a
  -- prova de que a SEFAZ o aceitou — e a guarda de cinco anos é da prova.
  completo      boolean      NOT NULL DEFAULT false,
  emitente      varchar(14),
  emitente_nome text,
  destinatario  varchar(14),
  valor         numeric(15,2),
  emitido_em    timestamptz,
  situacao      text,
  descricao     text,
  evento_tipo   varchar(6),
  xml           text         NOT NULL,
  -- O rastro de QUEM mandou. Numa porta aberta (qualquer um escreve para o
  -- endereço), saber a procedência é o que separa documento de arquivo
  -- anônimo — e é o que permite voltar na pessoa quando o XML vem torto.
  arquivo_nome  text,
  remetente     text,
  mensagem_id   text,
  assunto       text,
  recebido_em   timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_dfe_arquivo_chave   ON dfe_arquivo (chave);
CREATE INDEX IF NOT EXISTS ix_dfe_arquivo_emitido ON dfe_arquivo (emitido_em DESC);
CREATE INDEX IF NOT EXISTS ix_dfe_arquivo_origem  ON dfe_arquivo (origem, recebido_em DESC);

-- ------------------------------------------------------------ a mensagem
--
-- O QUE FOI LIDO DA CAIXA, e o que se fez com cada mensagem. Sem este
-- registro, "coletar de novo" significaria reabrir e reprocessar tudo toda
-- vez — e, pior, uma mensagem SEM anexo aproveitável (só o PDF do DANFE, só a
-- assinatura de e-mail) seria reaberta para sempre, porque não deixa rastro
-- em `dfe_arquivo`.
--
-- E ele responde a pergunta que a tela precisa fazer: chegou alguma coisa que
-- NÃO virou documento? Mensagem com `aproveitados = 0` é exatamente isso, e
-- ela tem de aparecer para alguém — senão o remetente acha que mandou e a
-- operação acha que não veio.
CREATE TABLE IF NOT EXISTS dfe_email_mensagem (
  -- O id da mensagem no provedor (Microsoft Graph). É opaco e estável para a
  -- mesma mensagem na mesma caixa, que é tudo o que precisa ser.
  id            text         PRIMARY KEY,
  caixa         text         NOT NULL,
  remetente     text,
  assunto       text,
  recebida_em   timestamptz,
  processada_em timestamptz  NOT NULL DEFAULT now(),
  anexos        integer      NOT NULL DEFAULT 0,
  aproveitados  integer      NOT NULL DEFAULT 0,
  ignorados     integer      NOT NULL DEFAULT 0,
  -- O tipo do erro, nunca o texto cru do provedor: mensagem de erro de API
  -- carrega token e endereço.
  erro          text
);

CREATE INDEX IF NOT EXISTS ix_dfe_email_mensagem_quando
  ON dfe_email_mensagem (processada_em DESC);
-- O que chegou e não virou documento: a lista que alguém precisa olhar.
CREATE INDEX IF NOT EXISTS ix_dfe_email_mensagem_vazia
  ON dfe_email_mensagem (processada_em DESC) WHERE aproveitados = 0;

-- --------------------------------------------------- a coleta ROLOU?
--
-- UMA LINHA POR CAIXA, e ela existe por um motivo que só aparece depois de a
-- coisa estar no ar: **"quando foi a última mensagem" NÃO é "quando foi a
-- última coleta".** Numa semana em que ninguém manda XML, `dfe_email_mensagem`
-- não ganha linha nenhuma — e um cartão de saúde que meça a mensagem mais
-- recente ficaria vermelho acusando uma coleta que está rodando de meia em
-- meia hora, sem falha alguma.
--
-- Alarme que acende sem haver problema ensina a ignorar alarme. Então o que se
-- mede aqui é a EXECUÇÃO: a rotina passou por aqui, e o que ela encontrou.
CREATE TABLE IF NOT EXISTS dfe_email_estado (
  caixa            text        PRIMARY KEY,
  ultima_coleta    timestamptz,
  -- A última que TERMINOU BEM. Separada da anterior porque uma coleta que roda
  -- e falha toda vez mantém `ultima_coleta` fresca — e o cartão diria "em dia"
  -- para uma integração que não traz nada desde ontem.
  ultimo_sucesso   timestamptz,
  mensagens_vistas integer      NOT NULL DEFAULT 0,
  -- O TIPO do erro, nunca o texto do provedor: mensagem de erro de API carrega
  -- token e endereço.
  ultimo_erro      text
);
