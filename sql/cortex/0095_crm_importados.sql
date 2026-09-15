-- Rastro da importação do CRM do ERP para o CRM do CÓRTEX (15/09/2026).
--
-- Decisão de quem opera: o CÓRTEX passa a ser o CRM da casa, e o que o time
-- comercial lançou no Avacorp (`sulista.gestaocomercial`, `pipelineprojetos`,
-- `pipelineprojetos_repactuacoes`) vem para cá. A importação pode rodar de novo
-- sem duplicar — para pegar o que ainda for lançado lá até a virada — e é ESTA
-- tabela que torna isso possível: cada linha diz "o registro X do ERP virou o
-- registro Y daqui".
--
-- O QUE JÁ FOI IMPORTADO NUNCA É REESCRITO. A partir da importação o registro é
-- do CÓRTEX; reimportar por cima apagaria o que o time editou aqui. Por isso a
-- chave é (fonte, fonte_id, entidade) e a importação só consulta: existe, pula.
--
-- SEM CHAVE ESTRANGEIRA para o registro criado, de propósito, como o
-- `zap_envio_id` das interações: `registro_id` aponta para tabelas diferentes
-- conforme a `entidade`, e apagar uma oportunidade importada não pode ficar
-- impedido por um rastro. O rastro sobrevive, e a reimportação continua
-- sabendo que aquele lead já foi trazido — apagado aqui, não volta sozinho.
CREATE TABLE IF NOT EXISTS crm_importados(
    fonte        text    NOT NULL,
    fonte_id     text    NOT NULL,
    entidade     text    NOT NULL,
    registro_id  integer NOT NULL,
    importado_em text    NOT NULL,
    PRIMARY KEY (fonte, fonte_id, entidade),
    CONSTRAINT crm_importados_entidade_ck
        CHECK (entidade IN ('conta', 'contato', 'oportunidade', 'projeto',
                            'andamento', 'interacao'))
);

CREATE INDEX IF NOT EXISTS ix_crm_importados_registro
    ON crm_importados(entidade, registro_id);

COMMENT ON TABLE crm_importados IS
    'De onde veio cada registro importado do CRM do ERP (Avacorp). Torna a
     importação repetível sem duplicar; o que já foi importado nunca é
     reescrito — a partir da importação o registro é do CÓRTEX.';
COMMENT ON COLUMN crm_importados.fonte IS
    'erp.gestaocomercial (lead), erp.pipelineprojetos (projeto, por numeroid),
     erp.pipelineprojetos_repactuacoes (repactuação) ou erp.conta (conta criada
     a partir do nome do cliente no ERP, pelo nome normalizado).';
