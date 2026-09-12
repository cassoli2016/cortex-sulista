-- 0088 · Horas paradas: a estadia que se COBRA, cliente a cliente, do jeito
-- que cada um recebe.
--
-- Pedido de quem opera (12/09/2026): "um controle de horas paradas; cada
-- cliente recebe de um jeito e tem suas particularidades". A primeira
-- planilha que chegou era montada à mão a partir do Monitoramento SAC do ERP,
-- e conferida linha a linha contra ele ela mostrou as três coisas que esta
-- migração guarda:
--
-- 1. A REGRA DE COBRANÇA É DO CLIENTE, e não cabe no contrato do ERP. Quando
--    começa o relógio (na janela? na chegada? no que vier depois?), que
--    mercadoria usa qual cláusula, como arredondar, que colunas vão na
--    planilha. Isso vive em `hp_perfil.config`, e NÃO em código: o
--    repositório é público, e condição comercial de cliente não entra nele.
--
-- 2. TODA VERSÃO DA REGRA FICA. Regra de cobrança move dinheiro; mudar o
--    início do relógio de um cliente muda o total de todas as semanas que
--    forem reabertas. `hp_perfil_versao` guarda cada configuração salva, com
--    autor e data — a pergunta "desde quando cobramos assim?" tem resposta.
--
-- 3. A PLANILHA À MÃO CORRIGIA O ERP, e isso tem de continuar possível sem
--    virar planilha à mão de novo. Na primeira conferência, um terço das
--    cargas tinha um horário diferente do apontado no ERP (chegada corrigida,
--    janela de descarga remarcada) — e esses ajustes mudavam o total da
--    semana em cerca de 5%. `hp_ajuste` guarda cada correção com MOTIVO, AUTOR e a FOTO do
--    que o ERP dizia quando ela foi feita. O ajuste nunca apaga o dado do
--    ERP: a tela mostra os dois lados, e desfazer é apagar a linha.

CREATE TABLE IF NOT EXISTS hp_perfil(
    id              serial PRIMARY KEY,
    -- `agrupamentocliente.codigo` do ERP: é o mesmo agrupamento que o
    -- Monitoramento SAC e o contrato de freetime usam para dizer quem é o
    -- cliente de uma coleta (pelo pagador do frete).
    cliente_codigo  integer NOT NULL UNIQUE,
    cliente_nome    text NOT NULL DEFAULT '',
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,
    criado_por      text NOT NULL,
    criado_em       timestamptz NOT NULL DEFAULT now(),
    atualizado_por  text NOT NULL,
    atualizado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hp_perfil_versao(
    id         bigserial PRIMARY KEY,
    perfil_id  integer NOT NULL REFERENCES hp_perfil(id) ON DELETE CASCADE,
    config     jsonb NOT NULL,
    autor      text NOT NULL,
    em         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_hp_perfil_versao
    ON hp_perfil_versao (perfil_id, em DESC);

-- UM ajuste por (coleta, campo): corrigir de novo SUBSTITUI, e a trilha do
-- que havia antes fica no `audit_log`. A coleta é identificada pelas SETE
-- colunas da chave do ERP numa string só — número de coleta sozinho repete
-- entre filiais.
CREATE TABLE IF NOT EXISTS hp_ajuste(
    id            bigserial PRIMARY KEY,
    coleta_chave  text NOT NULL,
    campo         text NOT NULL CHECK (campo IN (
                    'carga_janela', 'carga_chegada', 'carga_saida',
                    'descarga_janela', 'descarga_chegada', 'descarga_saida',
                    'incluir', 'referencia')),
    valor         text NOT NULL,
    valor_erp     text,
    motivo        text NOT NULL,
    autor         text NOT NULL,
    em            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (coleta_chave, campo)
);
