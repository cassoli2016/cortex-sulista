-- 0090 · WMS — o armazém da Sulista: endereços, estoque por endereço,
-- recebimento, armazenagem, separação, expedição e inventário.
--
-- POR QUE O WMS MORA AQUI, E NÃO NO ERP
-- =====================================
-- O Avacorp TEM um módulo WMS (`public.wms_*`, ~90 tabelas), e ele está VAZIO:
-- medido em 12/09/2026, só os catálogos têm linha (21 tipos de serviço, 10
-- motivos de bloqueio, 6 tipos de separação) — nenhum depósito, nenhum
-- endereço, nenhum saldo. O que o ERP tem, e muito, é a NOTA do cliente:
-- `coleta_notafiscal` (602 mil) e `coleta_notafiscal_item` (1,48 milhão de
-- itens, com o código do produto DO CLIENTE). Então o WMS escreve aqui e
-- BUSCA lá — e só busca: o núcleo funciona com o ERP fora do ar (recebimento
-- manual), porque armazém parado por dependência externa é caminhão parado.
--
-- O SALDO NÃO É UMA TABELA. É a soma do kardex (`wms_movimento`), e o banco
-- é quem garante as duas regras que não podem depender de a próxima rota
-- lembrar delas: saldo nunca negativo e kardex imutável. Total desnormalizado
-- discorda das próprias linhas no primeiro defeito; soma não discorda.

CREATE TABLE IF NOT EXISTS wms_armazem(
    id           serial PRIMARY KEY,
    codigo       text NOT NULL UNIQUE CHECK (codigo ~ '^[A-Z0-9]{2,10}$'),
    nome         text NOT NULL CHECK (length(trim(nome)) > 0),
    filial_erp   integer,                     -- a filial do Avacorp, se houver
    cidade       text NOT NULL DEFAULT '',
    uf           text NOT NULL DEFAULT '',
    ativo        boolean NOT NULL DEFAULT true,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    criado_por   text NOT NULL DEFAULT ''
);

-- O ENDEREÇO é a unidade do armazém: rua-prédio-nível-posição. Os tipos que
-- não guardam (doca, expedição, avaria) também são endereço, porque mercadoria
-- parada na doca é saldo — e saldo que não está em endereço nenhum é o
-- "sumiu no pátio" que um WMS existe para acabar.
CREATE TABLE IF NOT EXISTS wms_endereco(
    id                  serial PRIMARY KEY,
    armazem_id          integer NOT NULL REFERENCES wms_armazem(id),
    codigo              text NOT NULL CHECK (codigo ~ '^[A-Z0-9][A-Z0-9-]{0,23}$'),
    tipo                text NOT NULL CHECK (tipo IN
                        ('porta_palete','picking','blocado','doca','expedicao','avaria')),
    rua                 text NOT NULL DEFAULT '',
    capacidade_paletes  integer CHECK (capacidade_paletes IS NULL OR capacidade_paletes > 0),
    bloqueado           boolean NOT NULL DEFAULT false,
    motivo_bloqueio     text NOT NULL DEFAULT '',
    bloqueado_em        timestamptz,
    bloqueado_por       text NOT NULL DEFAULT '',
    ativo               boolean NOT NULL DEFAULT true,
    criado_em           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (armazem_id, codigo)
);
CREATE INDEX IF NOT EXISTS ix_wms_endereco_armazem ON wms_endereco (armazem_id, tipo);

-- DEPOSITANTE: o dono da mercadoria guardada. É o CLIENTE do ERP (`cadastro`)
-- copiado para cá no momento do cadastro, com a origem dita — o WMS precisa
-- do nome mesmo quando o ERP não responde.
CREATE TABLE IF NOT EXISTS wms_depositante(
    cnpj          text PRIMARY KEY CHECK (cnpj ~ '^([0-9]{11}|[0-9]{14})$'),
    razao_social  text NOT NULL CHECK (length(trim(razao_social)) > 0),
    nome_fantasia text NOT NULL DEFAULT '',
    cidade        text NOT NULL DEFAULT '',
    uf            text NOT NULL DEFAULT '',
    origem        text NOT NULL DEFAULT 'manual' CHECK (origem IN ('erp','manual')),
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    criado_por    text NOT NULL DEFAULT ''
);

-- PRODUTO é do depositante: o código é o DELE (o `produtocliente` da nota), e
-- dois clientes podem ter o mesmo código para coisas diferentes.
CREATE TABLE IF NOT EXISTS wms_produto(
    id                 serial PRIMARY KEY,
    depositante_cnpj   text NOT NULL REFERENCES wms_depositante(cnpj),
    codigo             text NOT NULL CHECK (length(trim(codigo)) > 0),
    descricao          text NOT NULL CHECK (length(trim(descricao)) > 0),
    unidade            text NOT NULL DEFAULT 'UN',
    ean                text NOT NULL DEFAULT '',
    peso_kg            numeric(14,3),
    controla_lote      boolean NOT NULL DEFAULT false,
    controla_validade  boolean NOT NULL DEFAULT false,
    origem             text NOT NULL DEFAULT 'manual' CHECK (origem IN ('erp','manual')),
    ativo              boolean NOT NULL DEFAULT true,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (depositante_cnpj, codigo)
);

-- ------------------------------------------------------------ recebimento
-- Estados GRAVADOS são só as decisões humanas: abrir, fechar a conferência,
-- cancelar. "Aguardando armazenagem" NÃO é estado do recebimento — é saldo
-- parado na doca, e se calcula do kardex (estado que envelhece sozinho não se
-- grava).
CREATE TABLE IF NOT EXISTS wms_recebimento(
    id                   serial PRIMARY KEY,
    armazem_id           integer NOT NULL REFERENCES wms_armazem(id),
    doca_id              integer NOT NULL REFERENCES wms_endereco(id),
    depositante_cnpj     text NOT NULL REFERENCES wms_depositante(cnpj),
    status               text NOT NULL DEFAULT 'aberto'
                         CHECK (status IN ('aberto','conferido','cancelado')),
    origem               text NOT NULL DEFAULT 'manual' CHECK (origem IN ('erp','manual')),
    nf_chave             text NOT NULL DEFAULT '' CHECK (nf_chave = '' OR nf_chave ~ '^[0-9]{44}$'),
    nf_numero            integer,
    nf_serie             text NOT NULL DEFAULT '',
    nf_emissao           date,
    emitente_cnpj        text NOT NULL DEFAULT '',
    valor_mercadoria     numeric(14,2),
    peso_kg              numeric(14,3),
    placa                text NOT NULL DEFAULT '',
    observacao           text NOT NULL DEFAULT '',
    criado_em            timestamptz NOT NULL DEFAULT now(),
    criado_por           text NOT NULL DEFAULT '',
    conferido_em         timestamptz,
    conferido_por        text NOT NULL DEFAULT '',
    cancelado_em         timestamptz,
    cancelado_por        text NOT NULL DEFAULT '',
    motivo_cancelamento  text NOT NULL DEFAULT ''
);
-- A MESMA NOTA NÃO ENTRA DUAS VEZES. Índice, e não `if` no Python: duas
-- pessoas abrindo o recebimento da mesma carreta ao mesmo tempo é o caso
-- normal de uma doca cheia, e a regra que só existe na rota é a que a
-- corrida atravessa. Cancelado não conta — a nota pode ser recebida de novo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_wms_recebimento_nf
    ON wms_recebimento (nf_chave) WHERE nf_chave <> '' AND status <> 'cancelado';
CREATE INDEX IF NOT EXISTS ix_wms_recebimento_status ON wms_recebimento (armazem_id, status);

-- A divergência (conferido − nota) NÃO é coluna: calcula-se na leitura.
CREATE TABLE IF NOT EXISTS wms_recebimento_item(
    id              serial PRIMARY KEY,
    recebimento_id  integer NOT NULL REFERENCES wms_recebimento(id) ON DELETE CASCADE,
    seq             integer NOT NULL,
    produto_id      integer NOT NULL REFERENCES wms_produto(id),
    qtd_nf          numeric(14,3) NOT NULL CHECK (qtd_nf >= 0),
    qtd_conferida   numeric(14,3) CHECK (qtd_conferida IS NULL OR qtd_conferida >= 0),
    qtd_avaria      numeric(14,3) NOT NULL DEFAULT 0 CHECK (qtd_avaria >= 0),
    lote            text NOT NULL DEFAULT '',
    validade        date,
    conferido_em    timestamptz,
    conferido_por   text NOT NULL DEFAULT '',
    UNIQUE (recebimento_id, seq),
    CHECK (qtd_conferida IS NULL OR qtd_avaria <= qtd_conferida)
);

-- ------------------------------------------------------------ expedição
-- `liberado` = já tem tarefa de separação. "Em separação" e "separado" são
-- CALCULADOS das tarefas: gravá-los seria uma segunda verdade sobre a mesma
-- coisa, e a primeira confirmação fora de ordem as faria discordar.
CREATE TABLE IF NOT EXISTS wms_pedido(
    id                   serial PRIMARY KEY,
    armazem_id           integer NOT NULL REFERENCES wms_armazem(id),
    depositante_cnpj     text NOT NULL REFERENCES wms_depositante(cnpj),
    status               text NOT NULL DEFAULT 'aberto'
                         CHECK (status IN ('aberto','liberado','expedido','cancelado')),
    origem               text NOT NULL DEFAULT 'manual' CHECK (origem IN ('erp','manual')),
    numero               text NOT NULL DEFAULT '',     -- o pedido do cliente
    nf_chave             text NOT NULL DEFAULT '' CHECK (nf_chave = '' OR nf_chave ~ '^[0-9]{44}$'),
    destinatario         text NOT NULL DEFAULT '',
    previsto_para        date,
    placa                text NOT NULL DEFAULT '',
    motorista            text NOT NULL DEFAULT '',
    observacao           text NOT NULL DEFAULT '',
    criado_em            timestamptz NOT NULL DEFAULT now(),
    criado_por           text NOT NULL DEFAULT '',
    liberado_em          timestamptz,
    liberado_por         text NOT NULL DEFAULT '',
    expedido_em          timestamptz,
    expedido_por         text NOT NULL DEFAULT '',
    cancelado_em         timestamptz,
    cancelado_por        text NOT NULL DEFAULT '',
    motivo_cancelamento  text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_wms_pedido_status ON wms_pedido (armazem_id, status);

CREATE TABLE IF NOT EXISTS wms_pedido_item(
    id          serial PRIMARY KEY,
    pedido_id   integer NOT NULL REFERENCES wms_pedido(id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    produto_id  integer NOT NULL REFERENCES wms_produto(id),
    qtd         numeric(14,3) NOT NULL CHECK (qtd > 0),
    lote        text NOT NULL DEFAULT '',             -- lote exigido pelo cliente, se houver
    UNIQUE (pedido_id, seq)
);

-- A TAREFA DE SEPARAÇÃO é a reserva: enquanto `pendente`, a quantidade dela
-- sai do DISPONÍVEL daquele endereço (o físico continua lá até alguém tirar).
CREATE TABLE IF NOT EXISTS wms_tarefa(
    id              serial PRIMARY KEY,
    pedido_id       integer NOT NULL REFERENCES wms_pedido(id) ON DELETE CASCADE,
    pedido_item_id  integer NOT NULL REFERENCES wms_pedido_item(id) ON DELETE CASCADE,
    produto_id      integer NOT NULL REFERENCES wms_produto(id),
    endereco_id     integer NOT NULL REFERENCES wms_endereco(id),
    lote            text NOT NULL DEFAULT '',
    validade        date,
    qtd             numeric(14,3) NOT NULL CHECK (qtd > 0),
    status          text NOT NULL DEFAULT 'pendente'
                    CHECK (status IN ('pendente','separada','cancelada')),
    qtd_separada    numeric(14,3) CHECK (qtd_separada IS NULL OR qtd_separada >= 0),
    -- a área de expedição onde a separação deixou a mercadoria: é de lá que a
    -- expedição tira, e é para a origem que o cancelamento a devolve
    destino_id      integer REFERENCES wms_endereco(id),
    separado_em     timestamptz,
    separado_por    text NOT NULL DEFAULT '',
    CHECK (qtd_separada IS NULL OR qtd_separada <= qtd)
);
CREATE INDEX IF NOT EXISTS ix_wms_tarefa_pendente
    ON wms_tarefa (produto_id, endereco_id, lote) WHERE status = 'pendente';
CREATE INDEX IF NOT EXISTS ix_wms_tarefa_pedido ON wms_tarefa (pedido_id);

-- ------------------------------------------------------------ inventário
CREATE TABLE IF NOT EXISTS wms_inventario(
    id           serial PRIMARY KEY,
    armazem_id   integer NOT NULL REFERENCES wms_armazem(id),
    descricao    text NOT NULL DEFAULT '',
    status       text NOT NULL DEFAULT 'aberto'
                 CHECK (status IN ('aberto','fechado','cancelado')),
    criado_em    timestamptz NOT NULL DEFAULT now(),
    criado_por   text NOT NULL DEFAULT '',
    fechado_em   timestamptz,
    fechado_por  text NOT NULL DEFAULT ''
);

-- O ESCOPO do inventário. `bloqueou` diz se foi ESTE inventário que bloqueou o
-- endereço: fechar não pode desbloquear o que já estava bloqueado por avaria.
CREATE TABLE IF NOT EXISTS wms_inventario_endereco(
    inventario_id  integer NOT NULL REFERENCES wms_inventario(id) ON DELETE CASCADE,
    endereco_id    integer NOT NULL REFERENCES wms_endereco(id),
    bloqueou       boolean NOT NULL DEFAULT false,
    contado_em     timestamptz,           -- NULL = ninguém contou ainda
    contado_por    text NOT NULL DEFAULT '',
    PRIMARY KEY (inventario_id, endereco_id)
);

CREATE TABLE IF NOT EXISTS wms_inventario_contagem(
    id             serial PRIMARY KEY,
    inventario_id  integer NOT NULL REFERENCES wms_inventario(id) ON DELETE CASCADE,
    endereco_id    integer NOT NULL REFERENCES wms_endereco(id),
    produto_id     integer NOT NULL REFERENCES wms_produto(id),
    lote           text NOT NULL DEFAULT '',
    qtd            numeric(14,3) NOT NULL CHECK (qtd >= 0),
    contado_em     timestamptz NOT NULL DEFAULT now(),
    contado_por    text NOT NULL DEFAULT '',
    UNIQUE (inventario_id, endereco_id, produto_id, lote)
);

-- ------------------------------------------------------------ kardex
CREATE TABLE IF NOT EXISTS wms_movimento(
    id           bigserial PRIMARY KEY,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    usuario      text NOT NULL DEFAULT '',
    tipo         text NOT NULL CHECK (tipo IN ('entrada','transferencia','saida','ajuste')),
    produto_id   integer NOT NULL REFERENCES wms_produto(id),
    endereco_id  integer NOT NULL REFERENCES wms_endereco(id),
    lote         text NOT NULL DEFAULT '',
    validade     date,
    qtd          numeric(14,3) NOT NULL CHECK (qtd <> 0),
    doc_tipo     text NOT NULL CHECK (doc_tipo IN
                 ('recebimento','armazenagem','movimentacao','separacao','expedicao','inventario','ajuste')),
    doc_id       integer,
    grupo        uuid,                   -- as duas pernas de uma transferência
    motivo       text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_wms_mov_saldo ON wms_movimento (produto_id, endereco_id, lote);
CREATE INDEX IF NOT EXISTS ix_wms_mov_endereco ON wms_movimento (endereco_id);
CREATE INDEX IF NOT EXISTS ix_wms_mov_data ON wms_movimento (criado_em);
CREATE INDEX IF NOT EXISTS ix_wms_mov_doc ON wms_movimento (doc_tipo, doc_id);

-- O SALDO É A SOMA. `primeira_entrada` é a mais antiga das entradas ainda
-- somadas ali — é ela que diz há quanto tempo a mercadoria está parada na
-- doca, e ela desempata o FIFO quando não há validade.
CREATE OR REPLACE VIEW wms_saldo AS
SELECT produto_id, endereco_id, lote,
       max(validade)                                AS validade,
       sum(qtd)                                     AS qtd,
       min(criado_em) FILTER (WHERE qtd > 0)        AS primeira_entrada,
       max(criado_em)                               AS ultimo_movimento
  FROM wms_movimento
 GROUP BY produto_id, endereco_id, lote
HAVING sum(qtd) <> 0;

-- SALDO NUNCA NEGATIVO, garantido pelo banco.
--
-- A trava consultiva serializa quem mexe no MESMO produto: sem ela, duas
-- separações simultâneas leriam o mesmo saldo, as duas passariam e o endereço
-- terminaria em −10 com o commit das duas. Em READ COMMITTED cada comando do
-- PL/pgSQL tira uma foto nova, então a soma lida DEPOIS de conseguir a trava
-- já enxerga o que a outra transação gravou.
CREATE OR REPLACE FUNCTION wms_movimento_confere() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_saldo  numeric;
    v_end    record;
BEGIN
    PERFORM pg_advisory_xact_lock(84084, NEW.produto_id);
    SELECT e.codigo, e.bloqueado, e.motivo_bloqueio, e.ativo INTO v_end
      FROM wms_endereco e WHERE e.id = NEW.endereco_id;
    -- Endereço bloqueado não recebe nem entrega — exceto a correção de quem
    -- bloqueou para contar (inventário) ou para ajustar.
    IF v_end.bloqueado AND NEW.doc_tipo NOT IN ('inventario','ajuste') THEN
        RAISE EXCEPTION 'WMS: o endereço % está bloqueado (%) e não aceita movimentação.',
            v_end.codigo, coalesce(nullif(v_end.motivo_bloqueio, ''), 'sem motivo');
    END IF;
    IF NOT v_end.ativo AND NEW.qtd > 0 THEN
        RAISE EXCEPTION 'WMS: o endereço % está inativo e não recebe mercadoria.', v_end.codigo;
    END IF;
    IF NEW.qtd < 0 THEN
        SELECT coalesce(sum(qtd), 0) INTO v_saldo FROM wms_movimento
         WHERE produto_id = NEW.produto_id AND endereco_id = NEW.endereco_id
           AND lote = NEW.lote;
        IF v_saldo < 0 THEN
            RAISE EXCEPTION 'WMS: saldo insuficiente no endereço % (faltam %).',
                v_end.codigo, trim(to_char(-v_saldo, 'FM999999990.###'));
        END IF;
    END IF;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS tg_wms_movimento_confere ON wms_movimento;
CREATE TRIGGER tg_wms_movimento_confere AFTER INSERT ON wms_movimento
    FOR EACH ROW EXECUTE FUNCTION wms_movimento_confere();

-- KARDEX IMUTÁVEL. Movimento errado se ESTORNA com movimento novo; editar o
-- histórico apaga a única prova de por que o saldo é o que é.
CREATE OR REPLACE FUNCTION wms_movimento_imutavel() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'WMS: o kardex é imutável — corrija com um movimento novo (ajuste).';
END $$;

DROP TRIGGER IF EXISTS tg_wms_movimento_imutavel ON wms_movimento;
CREATE TRIGGER tg_wms_movimento_imutavel BEFORE UPDATE OR DELETE ON wms_movimento
    FOR EACH ROW EXECUTE FUNCTION wms_movimento_imutavel();
