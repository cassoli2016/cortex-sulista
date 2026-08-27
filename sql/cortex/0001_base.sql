-- Fundação do banco local do CÓRTEX.
--
-- `schema_versao` é a única tabela que o runner conhece por nome: é ela que
-- diz o que já foi aplicado. Fica DENTRO do schema cortex, e não no public,
-- para que um schema de teste seja um universo completo — o teste aplica as
-- mesmas migrations e não depende de nada de fora.

CREATE TABLE IF NOT EXISTS schema_versao(
    versao      integer     PRIMARY KEY,
    arquivo     text        NOT NULL,
    aplicado_em timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE schema_versao IS
    'Migrations aplicadas neste schema. Ver docs/MIGRACAO_POSTGRES.md.';
