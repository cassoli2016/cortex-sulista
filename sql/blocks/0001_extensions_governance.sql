CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

-------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector (RAG)

-- ============================================================================
-- 1. GOVERNANÇA / ACESSO
-- ============================================================================
CREATE TABLE filiais (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    uf          char(2)
);

CREATE TABLE usuarios (
    id          serial PRIMARY KEY,
    email       text UNIQUE NOT NULL,
    nome        text NOT NULL,
    ativo       boolean NOT NULL DEFAULT true,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE papeis (
    id          serial PRIMARY KEY,
    nome        text UNIQUE NOT NULL          -- ceo, controller, fin_analista, ...
);

CREATE TABLE usuario_papel (
    usuario_id  int REFERENCES usuarios(id) ON DELETE CASCADE,
    papel_id    int REFERENCES papeis(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, papel_id)
);

CREATE TABLE usuario_filial (
    usuario_id  int REFERENCES usuarios(id) ON DELETE CASCADE,
    filial_id   int REFERENCES filiais(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, filial_id)
);

CREATE TABLE papel_modulo (
    papel_id    int REFERENCES papeis(id) ON DELETE CASCADE,
    modulo      text NOT NULL,                -- financeiro, comercial, ...
    permissao   text NOT NULL CHECK (permissao IN ('read','write','approve')),
    PRIMARY KEY (papel_id, modulo, permissao)
);

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    usuario_id  int REFERENCES usuarios(id),
    acao        text NOT NULL,                -- read|write|approve|login|...
    modulo      text,
    entidade    text,
    entidade_id text,
    detalhe     jsonb,
    ip          inet,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_criado ON audit_log (criado_em);
CREATE INDEX ix_audit_usuario ON audit_log (usuario_id, criado_em);

-- ============================================================================
