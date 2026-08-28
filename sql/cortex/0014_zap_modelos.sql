-- Modelos (templates) de mensagem de WhatsApp, para o texto que sai em nome da
-- empresa ser escrito UMA vez, revisado, e reusado pelas áreas do sistema.
--
-- POR QUE `chave` EXISTE ALÉM DO `id`: quem chama um modelo de dentro do
-- código é outra área ("a régua de cobrança usa o primeiro aviso"), e ela
-- precisa de um nome estável. Se a chamada fosse pelo `id`, restaurar um
-- backup noutra ordem trocaria a mensagem; se fosse pelo NOME, renomear
-- "Cobrança — 1º aviso" para "Cobrança — aviso amigável" quebraria a rotina em
-- silêncio. A chave é o contrato: nasce do nome, e depois só muda de propósito.
--
-- `contexto` NÃO É CATEGORIA DE ORGANIZAÇÃO. É o que decide quais variáveis o
-- corpo pode usar. Um modelo escrito no contexto de cobrança conhece
-- {{titulo}} e {{vencimento}}; o mesmo texto disparado da torre de controle não
-- teria com que preencher esses campos, e a mensagem sairia truncada para um
-- cliente real. O catálogo de contextos vive em `api/whatsapp/modelos.py`,
-- perto da validação — em tabela, ele viraria dado editável e a validação
-- passaria a depender de linha de banco que ninguém revisa.
--
-- NÃO HÁ `ON DELETE` LIGANDO ISTO A `zap_envios`, de propósito: a trilha guarda
-- a chave do modelo como TEXTO, não como chave estrangeira. A trilha responde
-- "o que saiu para fora da empresa" e tem de sobreviver à exclusão do modelo —
-- é justamente quando alguém apaga o texto que se quer saber o que ele dizia.

CREATE TABLE IF NOT EXISTS zap_modelos(
    id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chave          text    NOT NULL UNIQUE,
    nome           text    NOT NULL,
    contexto       text    NOT NULL DEFAULT 'livre',
    descricao      text    NOT NULL DEFAULT '',
    corpo          text    NOT NULL,
    ativo          integer NOT NULL DEFAULT 1,
    criado_em      text    NOT NULL,
    criado_por     text    NOT NULL DEFAULT '',
    atualizado_em  text    NOT NULL,
    atualizado_por text    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_zap_modelos_ctx ON zap_modelos(contexto, nome);

-- Qual modelo gerou a mensagem. Sem esta coluna, a pergunta que sempre aparece
-- depois — "essa frase que o cliente reclamou saiu de onde?" — só teria como
-- resposta comparar textos à mão. Fica em `zap_envios` e não numa tabela de
-- ligação porque é UM valor por envio, e porque a trilha precisa continuar
-- legível com um SELECT só.
ALTER TABLE zap_envios ADD COLUMN IF NOT EXISTS modelo text NOT NULL DEFAULT '';

COMMENT ON COLUMN zap_modelos.chave IS
    'Nome estável pelo qual o código chama o modelo. Renomear o modelo não
     muda a chave; trocar a chave é mudança de contrato com quem a usa.';
COMMENT ON COLUMN zap_modelos.contexto IS
    'De onde o modelo vai ser disparado — decide o conjunto de variáveis
     permitidas no corpo. Catálogo em api/whatsapp/modelos.py.';
COMMENT ON COLUMN zap_envios.modelo IS
    'Chave do modelo que originou o texto, ou vazio para mensagem avulsa.
     Texto solto de propósito: a trilha sobrevive à exclusão do modelo.';
