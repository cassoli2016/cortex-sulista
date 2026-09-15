-- 0094 · Cobrança: a TRATATIVA de cada valor em aberto.
--
-- Pedido de quem opera (15/09/2026): na Régua de Cobrança, o responsável
-- registra o que está sendo EFETIVAMENTE feito com os valores em aberto de
-- cada cliente — e todo o histórico fica.
--
-- A unidade é a LINHA DA RÉGUA (o grupo de cliente, ou o cliente sem grupo),
-- identificada por `ref`: um resumo da chave do grupo feito por
-- `api/queries.cobranca_ref()`. A chave em si leva o CNPJ quando não há grupo
-- e não sai do servidor — nem para a tela, nem para cá.
--
-- `vencido_ref` e `titulos_ref` são a FOTO do ERP no registro: lido meses
-- depois, o histórico precisa dizer do que se falava, e o ERP já terá mudado.
--
-- A SITUAÇÃO (promessa vencida, retorno atrasado, sem movimento) NÃO é
-- coluna: depende de hoje e é calculada na leitura, em
-- `api/financeiro/cobranca_tratativa.py`. Status gravado precisa de uma rotina
-- para virar, e no dia em que ela não roda a tela diz que está tudo em dia.

CREATE TABLE IF NOT EXISTS cob_tratativa(
    id              bigserial PRIMARY KEY,
    ref             text NOT NULL,
    cliente         text NOT NULL DEFAULT '',
    tipo            text NOT NULL,
    canal           text,
    descricao       text NOT NULL,
    promessa_data   date,
    promessa_valor  numeric(14,2),
    retorno_em      date,
    titulos         text[] NOT NULL DEFAULT '{}',
    vencido_ref     numeric(14,2),
    titulos_ref     integer,
    autor           text NOT NULL,
    em              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cob_trat_ref_ck CHECK (ref ~ '^[0-9a-f]{16}$'),
    CONSTRAINT cob_trat_tipo_ck CHECK (tipo IN ('contato', 'promessa', 'negociacao',
        'contestacao', 'sem_retorno', 'protesto', 'juridico', 'outro')),
    CONSTRAINT cob_trat_canal_ck CHECK (canal IS NULL
        OR canal IN ('ligacao', 'email', 'whatsapp', 'visita', 'outro')),
    CONSTRAINT cob_trat_promessa_ck CHECK ((tipo = 'promessa') = (promessa_data IS NOT NULL)),
    CONSTRAINT cob_trat_valor_ck CHECK (promessa_valor IS NULL
        OR (tipo = 'promessa' AND promessa_valor > 0)),
    CONSTRAINT cob_trat_desc_ck CHECK (length(btrim(descricao)) > 0),
    CONSTRAINT cob_trat_autor_ck CHECK (length(btrim(autor)) > 0)
);
CREATE INDEX IF NOT EXISTS ix_cob_trat_ref ON cob_tratativa (ref, em DESC, id DESC);

COMMENT ON TABLE cob_tratativa IS
    'O que se faz com o valor em aberto de cada cliente da Régua de Cobrança.
     Só acréscimo: registro errado se corrige com um registro novo.';

-- SÓ ACRÉSCIMO, e quem garante é o BANCO. Editar ou apagar um registro
-- apagaria justamente a prova do que foi dito a quem e quando — que é a razão
-- de o histórico existir. Regra que só existe no Python é regra que a próxima
-- rota esquece.
CREATE OR REPLACE FUNCTION cob_tratativa_imutavel() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Cobrança: o histórico da tratativa é imutável — corrija com um registro novo.';
END $$;

DROP TRIGGER IF EXISTS tg_cob_tratativa_imutavel ON cob_tratativa;
CREATE TRIGGER tg_cob_tratativa_imutavel BEFORE UPDATE OR DELETE ON cob_tratativa
    FOR EACH ROW EXECUTE FUNCTION cob_tratativa_imutavel();
