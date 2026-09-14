-- 0093 — App do motorista, fase 2: APONTAMENTOS e a ÚLTIMA POSIÇÃO do celular
-- (14/09/2026). Pedido de quem opera, com as duas finalidades na mesa: ver
-- onde os agregados estão e comprovar a chegada e a saída no cliente.
--
-- DUAS TABELAS, E A DIFERENÇA ENTRE ELAS É O PONTO:
--
-- mot_apontamentos — o que o motorista registrou ("cheguei para carregar" e
--   os outros três), com o VEREDITO da cerca do cliente e a DISTÂNCIA até ela.
--   NÃO TEM coluna de latitude nem de longitude: a coordenada entra, decide
--   dentro/fora e é descartada — a mesma regra do ponto certificado (0077).
--   Com veredito e distância a torre confere; com a coordenada crua se
--   reconstruiria por onde a pessoa andou, que a casa não precisa guardar.
--   O guard é ESTRUTURAL e lê o information_schema
--   (tests/motorista/test_apontamento.py).
--
-- mot_posicoes — a ÚLTIMA posição de quem está em viagem com o app aberto. A
--   chave primária É o motorista: não há como existir trajeto nesta tabela,
--   só "onde ele estava da última vez". A linha some quando a viagem termina,
--   quando ele sai do app, quando retira a autorização, e passadas 24 h de
--   qualquer jeito.
--
-- O APP NÃO ESCREVE NO ERP (docs/APP_MOTORISTA.md §6): origem = 'app', e a
-- torre põe cada apontamento ao lado da ocorrência SAC do ERP que responde a
-- mesma pergunta (394/395 carregamento, 396/397 descarga).

CREATE TABLE IF NOT EXISTS mot_apontamentos(
    id               bigserial PRIMARY KEY,
    motorista_codigo text NOT NULL,
    viagem           text NOT NULL,
    placa            text NOT NULL DEFAULT '',
    tipo             text NOT NULL CHECK (tipo IN ('chegou_coleta', 'saiu_coleta',
                                                   'chegou_entrega', 'saiu_entrega')),
    em_servidor      timestamptz NOT NULL DEFAULT now(),
    em_aparelho      timestamptz,
    cerca            text NOT NULL CHECK (cerca IN ('dentro', 'fora', 'sem_cerca',
                                                    'nao_conferida')),
    referencia       text NOT NULL DEFAULT '' CHECK (referencia IN ('', 'poligono',
                                                                    'coordenada')),
    distancia_m      integer,
    precisao_m       integer,
    origem           text NOT NULL DEFAULT 'app',
    UNIQUE (motorista_codigo, viagem, tipo)
);

CREATE INDEX IF NOT EXISTS mot_apontamentos_em ON mot_apontamentos(em_servidor DESC);

COMMENT ON COLUMN mot_apontamentos.cerca IS
    'dentro/fora da cerca do CLIENTE (cadastro_poligono tipo 1 do ERP, ou a
     coordenada do cadastro com raio declarado). sem_cerca = o cliente não tem
     nenhuma das duas; nao_conferida = o ERP não respondeu na hora — nunca
     "fora", que afirmaria o que ninguém conferiu.';
COMMENT ON COLUMN mot_apontamentos.em_aparelho IS
    'A hora do CELULAR, guardada ao lado da do servidor e nunca no lugar dela:
     o relógio do aparelho é do motorista e pode estar errado. Quem decide usa
     em_servidor; esta existe para explicar a diferença quando ela aparecer.';

CREATE TABLE IF NOT EXISTS mot_posicoes(
    motorista_codigo text PRIMARY KEY,
    viagem           text NOT NULL,
    placa            text NOT NULL DEFAULT '',
    lat              double precision NOT NULL,
    lon              double precision NOT NULL,
    precisao_m       integer,
    em_aparelho      timestamptz,
    em_servidor      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE mot_posicoes IS
    'A ÚLTIMA posição do celular de quem está em viagem com o app aberto. A
     chave é o motorista: uma linha por pessoa, sem trajeto. Apagada no fim da
     viagem, na saída do app, na retirada da autorização e após 24 h.';

-- A AUTORIZAÇÃO DE LOCALIZAÇÃO. Registrada no servidor, e não só no navegador:
-- é ela que diz, depois, desde quando o motorista sabia o que era enviado.
-- NULL = não autorizou (ou retirou); aí o app não aponta nem envia posição.
ALTER TABLE mot_vinculos ADD COLUMN IF NOT EXISTS loc_aceite_em timestamptz;
