-- 0035 · Gerenciamento de Risco (Fase 2): a coleta própria do RasterIntegra.
--
-- A Fase 1 lê o que o ERP recebe do hub (eventos por macro, cobertura,
-- frescor). O que o ERP NUNCA teve é o CONSOLIDADO DE RISCO POR VIAGEM que a
-- própria Raster calcula ao finalizar a SM: pânico, desvio de rota, violação
-- de painel/antena, paradas em área de risco, tempo sem posição. É isso que
-- estas tabelas guardam, coletadas direto do webservice RasterIntegra com a
-- credencial exclusiva do CÓRTEX.
--
-- O FORMATO DA COLETA FOI MEDIDO ANTES DE DESENHAR (01/09/2026, ao vivo):
-- o único filtro que o servidor respeita de verdade é Placa (+ janela de
-- datas sobre o FIM REAL); StatusViagem é ignorado e o modo cursor devolve
-- um backlog travado de viagens nunca finalizadas desde mar/2025. Por isso
-- a coleta é POR PLACA (as placas com viagem encerrada recente no ERP) e o
-- upsert é pela chave natural CodSolicitacao.
CREATE TABLE IF NOT EXISTS gr_viagem_fim(
    cod_solicitacao     bigint PRIMARY KEY,   -- chave natural da SM na Raster
    cod_filial          integer,
    placa               text NOT NULL,        -- normalizada (sem hífen, caixa alta)
    vinc_veiculo        text,                 -- A=Agregado F=Frota T=Terceiro
    placa_carreta1      text,
    cpf_motorista       text,                 -- PII: fica no banco local, nunca em URL/tela inteira
    vinc_motorista      text,
    cnpj_cliente_orig   text,
    cnpj_cliente_dest   text,
    cnpj_proprietario   text,
    rota                text,
    prev_ini            timestamptz,
    prev_fim            timestamptz,
    real_ini            timestamptz,
    real_fim            timestamptz,
    status              text NOT NULL,        -- L/I/F/C — só F carrega consolidado
    dentro_prazo        boolean,
    perc_atraso         double precision,
    vel_media           double precision,
    maior_vel           double precision,
    local_maior_vel     text,
    lat_maior_vel       double precision,
    lon_maior_vel       double precision,
    tempo_total_min     bigint,
    tempo_parado_min    bigint,
    tempo_mov_min       bigint,
    perc_mov            double precision,
    parado_area_risco_min bigint,
    parado_alvos_min    bigint,
    perc_pernoite       double precision,
    menor_pernoite_min  bigint,
    -- contadores de risco: o fornecedor OMITE o campo quando é zero (medido:
    -- viagem finalizada veio com ParadasAreaRisco=3 e BotaoPanico ausente).
    -- Guardamos o que veio (NULL = omitido); a leitura trata NULL como 0.
    botao_panico        integer,
    eventos_velocidade  integer,
    paradas_area_risco  integer,
    desvios_rota        integer,
    sem_posicao         integer,              -- vezes com +2h sem posicionar
    rodou_fora_horario  boolean,
    violacao_painel     integer,
    violacao_antena     integer,
    desengate           integer,
    coletas_entregas    integer,
    coletas_no_prazo    integer,
    link_timeline       text,
    visto_em            timestamptz NOT NULL DEFAULT now(),
    atualizado_em       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS gr_viagem_fim_fim_idx ON gr_viagem_fim (real_fim DESC);
CREATE INDEX IF NOT EXISTS gr_viagem_fim_placa_idx ON gr_viagem_fim (placa);

-- km por veículo e dia visto pela GR (getKMRodado): com viagem × sem viagem.
-- Uma chamada por DIA devolve a frota inteira — barato o bastante para
-- coletar D-1 e D-2 toda madrugada (o D-2 cura dado que chegou atrasado).
CREATE TABLE IF NOT EXISTS gr_km_dia(
    dia             date NOT NULL,
    placa           text NOT NULL,
    motorista       text,
    cpf             text,
    vinculo         text,
    km_com_viagem   double precision,
    km_sem_viagem   double precision,
    coletado_em     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dia, placa)
);

-- trilha de coleta: coleta vazia NUNCA vira snapshot completo, e a Saúde
-- mede o frescor daqui (alarme = "não coletou HOJE", nunca contagem de
-- tropeços históricos).
CREATE TABLE IF NOT EXISTS gr_carga(
    id            bigserial PRIMARY KEY,
    tipo          text NOT NULL,            -- 'viagens' | 'km'
    iniciado_em   timestamptz NOT NULL,
    terminado_em  timestamptz,
    janela        text,
    consultas     integer NOT NULL DEFAULT 0,
    gravadas      integer NOT NULL DEFAULT 0,
    erro          text
);
