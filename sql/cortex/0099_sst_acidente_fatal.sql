-- 0099 · Segurança do trabalho: acidente com VÍTIMA FATAL.
--
-- Pedido de quem opera (16/09/2026), no painel de TV do RH: "acidente com
-- vítima seria com morte, e não grave". A tabela de indicadores da Qualidade
-- no ERP (`sulista.indicadorescorporativos`) só classifica o acidente em
-- leve, médio e grave — NÃO tem onde registrar morte. Sem registro, o cartão
-- "com vítima" da TV só poderia mostrar um zero que ninguém mediu, e zero que
-- é ausência de registro não é desempenho.
--
-- O registro é SÓ ACRÉSCIMO, e quem garante é o BANCO: não se apaga nem se
-- edita. Registro errado sai por RETIRADA — uma vez, com motivo e autor — e
-- a linha fica, porque a prova de que alguém registrou e depois retirou é
-- parte da história de um número que vai para a parede.

CREATE TABLE IF NOT EXISTS sst_acidente_fatal(
    id               bigserial PRIMARY KEY,
    data             date NOT NULL,
    filial           text NOT NULL,
    descricao        text NOT NULL,
    autor            text NOT NULL,
    em               timestamptz NOT NULL DEFAULT now(),
    retirado_em      timestamptz,
    retirado_por     text,
    retirado_motivo  text,
    CONSTRAINT sst_fatal_filial_ck CHECK (length(btrim(filial)) > 0),
    CONSTRAINT sst_fatal_desc_ck CHECK (length(btrim(descricao)) > 0),
    CONSTRAINT sst_fatal_autor_ck CHECK (length(btrim(autor)) > 0),
    CONSTRAINT sst_fatal_retirada_ck CHECK (
        (retirado_em IS NULL AND retirado_por IS NULL AND retirado_motivo IS NULL)
        OR (retirado_em IS NOT NULL AND length(btrim(retirado_por)) > 0
            AND length(btrim(retirado_motivo)) > 0))
);
CREATE INDEX IF NOT EXISTS ix_sst_fatal_data ON sst_acidente_fatal (data) WHERE retirado_em IS NULL;

COMMENT ON TABLE sst_acidente_fatal IS
    'Acidente com vítima fatal, registrado no CÓRTEX (o ERP não tem o campo).
     Só acréscimo: registro errado sai por retirada, com motivo.';

-- A única mudança aceita é a RETIRADA, e uma vez só: nenhum campo do registro
-- original muda, e retirada não se desfaz nem se reescreve.
CREATE OR REPLACE FUNCTION sst_acidente_fatal_guarda() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Acidente fatal: o registro não se apaga — retire com motivo.';
    END IF;
    IF OLD.retirado_em IS NOT NULL THEN
        RAISE EXCEPTION 'Acidente fatal: registro já retirado.';
    END IF;
    IF NEW.data IS DISTINCT FROM OLD.data OR NEW.filial IS DISTINCT FROM OLD.filial
       OR NEW.descricao IS DISTINCT FROM OLD.descricao OR NEW.autor IS DISTINCT FROM OLD.autor
       OR NEW.em IS DISTINCT FROM OLD.em OR NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'Acidente fatal: o registro não se edita — retire e registre de novo.';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS tg_sst_acidente_fatal_guarda ON sst_acidente_fatal;
CREATE TRIGGER tg_sst_acidente_fatal_guarda BEFORE UPDATE OR DELETE ON sst_acidente_fatal
    FOR EACH ROW EXECUTE FUNCTION sst_acidente_fatal_guarda();
