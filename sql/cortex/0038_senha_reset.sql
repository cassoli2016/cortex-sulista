-- 0038 · Redefinição de senha pelo próprio usuário ("esqueci minha senha").
--
-- POR QUE UMA TABELA E NÃO UMA SENHA NOVA NA HORA. Já existe a máquina de
-- senha provisória (usuário criado com `deve_trocar_senha=1`, ou resetado por
-- um administrador). Reusá-la aqui — pedir "esqueci" e o sistema TROCAR a
-- senha e mandar a nova por e-mail — seria abrir um jeito de qualquer pessoa
-- que saiba um e-mail da empresa DERRUBAR o acesso de quem quiser, quantas
-- vezes quiser: a senha que a vítima usa para de valer sem que ela tenha
-- pedido nada. O pedido não pode mexer na conta; ele só cria uma PERMISSÃO
-- temporária de trocar. Até alguém abrir o link e escolher a senha nova, a
-- senha antiga continua valendo e nada mudou.
--
-- O TOKEN NÃO É GRAVADO. Guarda-se o SHA-256 dele, como se guarda senha: quem
-- lê esta tabela (backup, dump, tela de suporte) não consegue entrar na conta
-- de ninguém. A comparação é por hash, e é por isso que `token_hash` é UNIQUE
-- — a busca é pelo hash, nunca por usuário + varredura.
--
-- `usado_em` marca o consumo em vez de apagar a linha: o pedido que já virou
-- senha nova é justamente o que a auditoria precisa ver depois ("quem
-- redefiniu, quando, de que IP"). A limpeza das expiradas é do próprio fluxo.
CREATE TABLE IF NOT EXISTS senha_reset(
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_hash text    NOT NULL UNIQUE,
    criado_em  text    NOT NULL,
    expira_em  text    NOT NULL,
    usado_em   text,
    ip_pedido  text    NOT NULL DEFAULT ''
);

-- O índice serve às DUAS perguntas do fluxo: quantos pedidos este usuário fez
-- na última hora (o freio contra mandar e-mail em rajada para a mesma pessoa)
-- e quais os pedidos dele ainda de pé (invalidados quando um é consumido).
CREATE INDEX IF NOT EXISTS ix_senha_reset_usuario
    ON senha_reset(usuario_id, criado_em);
