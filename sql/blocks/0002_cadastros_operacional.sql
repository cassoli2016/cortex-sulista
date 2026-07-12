-- 2. CADASTROS BASE
-- ============================================================================
CREATE TABLE com_clientes (
    id              serial PRIMARY KEY,
    nome            text NOT NULL,
    cnpj            text UNIQUE,
    segmento        text,
    score           numeric(5,1),
    limite_credito  numeric(14,2) DEFAULT 0,
    filial_id       int REFERENCES filiais(id),
    criado_em       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rh_motoristas (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    cpf         text UNIQUE,
    cnh         text,
    categoria_cnh text,
    filial_id   int REFERENCES filiais(id),
    ativo       boolean NOT NULL DEFAULT true,
    admissao    date
);

CREATE TABLE fro_veiculos (
    id              serial PRIMARY KEY,
    placa           text UNIQUE NOT NULL,
    tipo            text,                      -- cavalo, truck, frigorifico...
    ano             int,
    valor_compra    numeric(14,2),
    valor_residual  numeric(14,2),
    vida_km         numeric(12,0),
    status          text DEFAULT 'ativo',      -- ativo|parado|manutencao|vendido
    filial_id       int REFERENCES filiais(id)
);

CREATE TABLE op_rotas (
    id              serial PRIMARY KEY,
    origem_uf       char(2),
    destino_uf      char(2),
    distancia_km    numeric(10,1),
    pedagio_estimado numeric(12,2)
);

CREATE TABLE sup_fornecedores (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    cnpj        text,
    tipo        text CHECK (tipo IN ('posto','oficina','agregado','outro')),
    avaliacao   numeric(3,1)
);

CREATE TABLE sup_agregados (
    id              serial PRIMARY KEY,
    fornecedor_id   int REFERENCES sup_fornecedores(id),
    rkm_acordado    numeric(10,4),
    rotas           int[]
);

CREATE TABLE sup_contratos (
    id              serial PRIMARY KEY,
    fornecedor_id   int REFERENCES sup_fornecedores(id),
    inicio          date,
    fim             date,
    termos          jsonb
);

-- ============================================================================
-- 3. OPERACIONAL
-- ============================================================================
CREATE TABLE op_viagens (
    id              serial PRIMARY KEY,
    cliente_id      int REFERENCES com_clientes(id),
    veiculo_id      int REFERENCES fro_veiculos(id),
    motorista_id    int REFERENCES rh_motoristas(id),
    rota_id         int REFERENCES op_rotas(id),
    km_carregado    numeric(10,1) NOT NULL DEFAULT 0,
    km_total        numeric(10,1) NOT NULL DEFAULT 0,
    receita_frete   numeric(14,2) NOT NULL DEFAULT 0,
    custo_variavel  numeric(14,2),             -- custo variável TOTAL apurado da viagem
    custo_fixo_rateado numeric(14,2),          -- fixo rateado p/ a viagem
    cte_id          text,
    modo            text NOT NULL DEFAULT 'proprio' CHECK (modo IN ('proprio','agregado')),
    status          text NOT NULL DEFAULT 'planejada', -- planejada|ativa|concluida|cancelada
    filial_id       int REFERENCES filiais(id),
    inicio          timestamptz,
    fim             timestamptz
);
CREATE INDEX ix_viagens_status ON op_viagens (status);
CREATE INDEX ix_viagens_cliente ON op_viagens (cliente_id, inicio);

CREATE TABLE op_cargas (
    id              serial PRIMARY KEY,
    viagem_id       int REFERENCES op_viagens(id) ON DELETE CASCADE,
    peso            numeric(12,2),
    valor_mercadoria numeric(14,2),
    nf_id           text
);

-- ============================================================================
-- 4. PROGRAMAÇÃO DE CARGAS
-- ============================================================================
CREATE TABLE prog_cargas (
    id              serial PRIMARY KEY,
    cliente_id      int REFERENCES com_clientes(id),
    origem          text,
    destino         text,
    janela_coleta   tstzrange,
    janela_entrega  tstzrange,
    peso            numeric(12,2),
    tipo_carga      text,
    status          text NOT NULL DEFAULT 'pendente' -- pendente|alocada|em_curso|entregue
);

CREATE TABLE prog_alocacao (
    id              serial PRIMARY KEY,
    carga_id        int REFERENCES prog_cargas(id) ON DELETE CASCADE,
    veiculo_id      int REFERENCES fro_veiculos(id),
    motorista_id    int REFERENCES rh_motoristas(id),
    status          text NOT NULL DEFAULT 'proposta',
    criado_em       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE prog_disponibilidade (
    id              serial PRIMARY KEY,
    veiculo_id      int REFERENCES fro_veiculos(id),
    inicio          timestamptz,
    fim             timestamptz,
    motivo          text
);

-- ============================================================================
-- 5. FROTA
-- ============================================================================
CREATE TABLE fro_manutencao (
    id          serial PRIMARY KEY,
    veiculo_id  int REFERENCES fro_veiculos(id),
    tipo        text CHECK (tipo IN ('prev','corr')),
    custo       numeric(14,2),
    data        date,
    km          numeric(12,0)
);

CREATE TABLE fro_pneus (
    id              serial PRIMARY KEY,
    veiculo_id      int REFERENCES fro_veiculos(id),
    posicao         text,
    custo_jogo      numeric(14,2),
    custo_recapes   numeric(14,2) DEFAULT 0,
    km_vida         numeric(12,0),
    instalado_em    date
);

-- ============================================================================
