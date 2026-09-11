-- 0081 · Radar — a lentidão nos corredores pela velocidade da NOSSA frota.
--
-- Em 11/09/2026 a franquia grátis de trânsito da TomTom acabou na primeira
-- semana do mês (ela é MENSAL: 20 mil consultas de fluxo e 2.500 de
-- ocorrências), e o cartão "Rodovias agora" da página inicial ficou sem nada ao
-- vivo. Quem opera pediu que aparecesse e estivesse certo, e escolheu a fonte:
-- a velocidade dos próprios caminhões (`api/radar/frota.py`).
--
-- É UM RETRATO, como `rad_rodovia`: uma linha por corredor, a coleta substitui
-- as quatro na mesma transação, e a coleta que falha não apaga a anterior.
--
-- DIFERENTE DO RESTO DO RADAR, ISTO É DADO DA SULISTA — e por isso só
-- CONTAGEM. A página inicial é de todo usuário logado: nada de placa,
-- motorista ou coordenada aqui (o guard lê o information_schema, não este
-- texto).
CREATE TABLE IF NOT EXISTS rad_frota (
    regiao         text        PRIMARY KEY,   -- o corredor (rodovias.CORREDORES)
    caminhoes      integer     NOT NULL,      -- em viagem, com posição de agora no corredor
    andando        integer     NOT NULL,      -- 40 km/h ou mais
    lentos         integer     NOT NULL,      -- 2+ leituras seguidas entre 8 e 40 km/h
    parados        integer     NOT NULL,      -- abaixo de 8 km/h, motivo não informado
    indefinidos    integer     NOT NULL,      -- sem leitura firme (uma leitura lenta só)
    lento_max_min  integer,                   -- há quanto tempo está o lento mais antigo
    vel_lentos     integer,                   -- mediana da velocidade dos lentos, km/h
    coletado_em    timestamptz NOT NULL DEFAULT now()
);
