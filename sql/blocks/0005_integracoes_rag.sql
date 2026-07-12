-- 9. CENTRAL DE INTEGRAÇÕES
-- ============================================================================
CREATE TABLE int_conectores (
    id          serial PRIMARY KEY,
    name        text UNIQUE NOT NULL,
    mode        text CHECK (mode IN ('pull','push','both')),
    capabilities text[],
    ativo       boolean NOT NULL DEFAULT true,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE int_credenciais (
    id          serial PRIMARY KEY,
    conector_id int REFERENCES int_conectores(id) ON DELETE CASCADE,
    ref_cofre   text NOT NULL,                 -- REFERÊNCIA ao cofre, nunca o segredo
    escopo      text,
    expira_em   timestamptz
);

CREATE TABLE int_sync_state (
    conector_id int REFERENCES int_conectores(id) ON DELETE CASCADE,
    capability  text NOT NULL,
    cursor      text,
    ultima_sync timestamptz,
    status      text DEFAULT 'ok',             -- ok|atrasado|circuit_open
    PRIMARY KEY (conector_id, capability)
);

CREATE TABLE int_raw_events (
    id          bigserial PRIMARY KEY,
    conector    text NOT NULL,
    chave_idem  text UNIQUE NOT NULL,          -- idempotência
    tipo        text NOT NULL,
    recebido_em timestamptz NOT NULL DEFAULT now(),
    payload     jsonb NOT NULL
);
CREATE INDEX ix_raw_conector ON int_raw_events (conector, recebido_em DESC);

CREATE TABLE int_dead_letter (
    id          bigserial PRIMARY KEY,
    conector    text NOT NULL,
    erro        text,
    tentativas  int DEFAULT 0,
    payload     jsonb,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE int_webhook_log (
    id              bigserial PRIMARY KEY,
    conector        text NOT NULL,
    assinatura_valida boolean,
    recebido_em     timestamptz NOT NULL DEFAULT now(),
    status          text
);

-- ============================================================================
-- 10. RAG (pgvector) — base de conhecimento
-- ============================================================================
CREATE TABLE kb_documentos (
    id          serial PRIMARY KEY,
    titulo      text,
    modulo      text,                          -- tag de escopo p/ RBAC do RAG
    filial_id   int REFERENCES filiais(id),
    conteudo    text,
    embedding   vector(768)
);
CREATE INDEX ix_kb_embedding ON kb_documentos USING ivfflat (embedding vector_cosine_ops);

-- ============================================================================
