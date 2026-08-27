-- Usuários, perfis de acesso, trilha de auditoria e políticas — o último store
-- migrado do SQLite (27/08/2026).
--
-- Deixado por último de propósito, apesar de ser o mais importante: é o mais
-- acoplado do sistema (167 comandos SQL num arquivo só) e o único cuja falha
-- derruba o LOGIN. Quando chegou a vez dele, os padrões já tinham sido provados
-- sete vezes em produção. Ver docs/MIGRACAO_POSTGRES.md.
--
-- `senha_hash` guarda o hash do Argon2, nunca a senha. `token_ver` é o que
-- permite invalidar as sessões de um usuário sem trocar o segredo do servidor:
-- incrementa e todo cookie emitido antes deixa de valer.
--
-- `audit_log` é a resposta a "quem mexeu no sistema" — separada da trilha de
-- e-mail (`correio_envios`, "o que saiu para fora") e da fiscal (`auditoria`,
-- "quem autorizou emitir por quem"). São perguntas diferentes com retenções
-- diferentes; o volume de uma não pode empurrar a outra para fora da tela.

CREATE TABLE IF NOT EXISTS perfis(
    id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome      text NOT NULL UNIQUE,
    descricao text DEFAULT '',
    admin     integer NOT NULL DEFAULT 0,
    criado_em text NOT NULL
);

CREATE TABLE IF NOT EXISTS perfil_telas(
    perfil_id integer NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    tela      text NOT NULL,
    PRIMARY KEY(perfil_id, tela)
);

CREATE TABLE IF NOT EXISTS usuarios(
    id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome              text NOT NULL,
    email             text NOT NULL UNIQUE,
    senha_hash        text NOT NULL,
    perfil_id         integer NOT NULL REFERENCES perfis(id),
    ativo             integer NOT NULL DEFAULT 1,
    deve_trocar_senha integer NOT NULL DEFAULT 1,
    token_ver         integer NOT NULL DEFAULT 0,
    falhas            integer NOT NULL DEFAULT 0,
    bloqueado_ate     text,
    criado_em         text NOT NULL,
    ultimo_login      text
);

CREATE TABLE IF NOT EXISTS audit_log(
    id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts      text NOT NULL,
    usuario text NOT NULL,
    acao    text NOT NULL,
    alvo    text DEFAULT '',
    detalhe text DEFAULT '',
    ip      text DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS config(
    chave text PRIMARY KEY,
    valor text NOT NULL
);

COMMENT ON COLUMN usuarios.token_ver IS
    'Versão do token. Incrementar invalida todas as sessões daquele usuário
     sem tocar no segredo do servidor.';
COMMENT ON TABLE config IS
    'Políticas de acesso (TTL de sessão, tentativas, bloqueio, tamanho de
     senha) e os marcadores de seed dos perfis-modelo.';
