-- 0036 · Monkey (portal Tupy): o ESPELHO local de todos os recebíveis.
--
-- A posição de antecipação (ant_envios/ant_titulos) guarda só o que está EM
-- ABERTO — é o que o painel de Antecipações precisa. Mas a API entrega o
-- histórico INTEIRO do convênio (48,6 mil títulos desde jun/2024 na primeira
-- varredura), e é dele que sai a tela de VALIDAÇÃO do portal: quanto foi
-- antecipado por mês, a que taxa, com que deságio, quanto liquidou no prazo.
-- Guardar o espelho evita re-paginar 500 chamadas a cada pergunta.
--
-- CHAVE NATURAL MEDIDA (01/09/2026, 600 títulos): externalId é único e
-- sempre presente DENTRO do seller; invoiceKey vem vazio em 88% das linhas
-- (fora de cogitação). PK = (seller_id, external_id); o id opaco do próprio
-- recebível na Monkey (_links.self) fica de coluna.
CREATE TABLE IF NOT EXISTS mky_recebiveis(
    seller_id           text NOT NULL,     -- companyId do CNPJ Sulista
    external_id         text NOT NULL,     -- id do título no sistema da Tupy
    id_monkey           text,              -- id opaco do _links.self
    seller_cnpj         text,
    seller_nome         text,
    invoice_number      text,
    invoice_key         text,              -- chave da NF-e (quando vem)
    installment         integer,
    total_installment   integer,
    asset_type          text,
    status              text NOT NULL,
    invoice_date        date,
    payment_date        date,              -- vencimento previsto
    real_payment_date   date,
    effective_payment_date date,
    payment_value       double precision,  -- nominal
    receipt_value       double precision,  -- o que a Sulista recebe
    purchased_tax       double precision,
    fee_rate            double precision,
    fee_amount          double precision,
    sponsor_cnpj        text,              -- a âncora (TUPY) — o sacado
    sponsor_nome        text,
    buyer_cnpj          text,              -- o investidor que comprou
    buyer_nome          text,
    criado_fornecedor   timestamptz,       -- createdAt deles
    alterado_fornecedor timestamptz,       -- updatedAt deles
    visto_em            timestamptz NOT NULL DEFAULT now(),
    atualizado_em       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (seller_id, external_id)
);
CREATE INDEX IF NOT EXISTS mky_receb_venc_idx ON mky_recebiveis (payment_date);
CREATE INDEX IF NOT EXISTS mky_receb_status_idx ON mky_recebiveis (status);
CREATE INDEX IF NOT EXISTS mky_receb_doc_idx ON mky_recebiveis (invoice_number);

-- trilha da varredura do espelho: a Saúde e a tela leem o frescor DAQUI
CREATE TABLE IF NOT EXISTS mky_carga(
    id            bigserial PRIMARY KEY,
    iniciado_em   timestamptz NOT NULL,
    terminado_em  timestamptz,
    recebidos     integer NOT NULL DEFAULT 0,
    gravados      integer NOT NULL DEFAULT 0,
    sem_chave     integer NOT NULL DEFAULT 0,
    erro          text
);
