-- 6. FINANCEIRO
-- ============================================================================
CREATE TABLE fin_titulos (
    id          serial PRIMARY KEY,
    tipo        text NOT NULL CHECK (tipo IN ('receber','pagar')),
    cliente_id  int REFERENCES com_clientes(id),
    fornecedor_id int REFERENCES sup_fornecedores(id),
    valor       numeric(14,2) NOT NULL,
    emissao     date NOT NULL,
    vencimento  date NOT NULL,
    baixa       date,
    status      text NOT NULL DEFAULT 'aberto', -- aberto|pago|atrasado|cancelado
    cte_id      text,
    filial_id   int REFERENCES filiais(id)
);
CREATE INDEX ix_titulos_venc ON fin_titulos (vencimento, status);
CREATE INDEX ix_titulos_tipo ON fin_titulos (tipo, status);

CREATE TABLE fin_adiantamentos (
    id          serial PRIMARY KEY,
    motorista_id int REFERENCES rh_motoristas(id),
    fornecedor_id int REFERENCES sup_fornecedores(id),
    valor       numeric(14,2) NOT NULL,
    data        date NOT NULL,
    viagem_id   int REFERENCES op_viagens(id),
    status      text NOT NULL DEFAULT 'aberto'
);

CREATE TABLE fin_lancamentos (
    id          serial PRIMARY KEY,
    conta       text,
    centro_custo text,
    valor       numeric(14,2) NOT NULL,
    data        date NOT NULL,
    origem      text
);

CREATE TABLE fin_dre (
    id          serial PRIMARY KEY,
    competencia date NOT NULL,
    conta       text NOT NULL,
    grupo       text NOT NULL,                 -- receita|custo_var|custo_motorista|fixo|adm|fin
    valor       numeric(14,2) NOT NULL,
    centro_custo text
);
CREATE INDEX ix_dre_comp ON fin_dre (competencia, grupo);

-- ============================================================================
-- 7. GESTÃO (metas / OKR / atas / ações)
-- ============================================================================
CREATE TABLE ges_metas (
    id          serial PRIMARY KEY,
    area        text,
    indicador   text,
    meta        numeric(14,4),
    periodo     text,
    responsavel text
);

CREATE TABLE ges_okr (
    id          serial PRIMARY KEY,
    objetivo    text NOT NULL,
    key_result  text NOT NULL,
    baseline    numeric(14,4),
    atual       numeric(14,4),
    meta        numeric(14,4),
    prazo       date,
    dono        text
);

CREATE TABLE ges_atas (
    id          serial PRIMARY KEY,
    reuniao     text,
    data        date,
    participantes text[],
    pauta       text,
    decisoes    text
);

CREATE TABLE ges_acoes (
    id          serial PRIMARY KEY,
    ata_id      int REFERENCES ges_atas(id) ON DELETE SET NULL,
    okr_id      int REFERENCES ges_okr(id) ON DELETE SET NULL,
    o_que       text NOT NULL,
    quem        text NOT NULL,
    quando      date NOT NULL,
    como        text,
    status      text NOT NULL DEFAULT 'aberta', -- aberta|em_andamento|concluida|atrasada
    prioridade  text DEFAULT 'media'
);

-- ============================================================================
