-- 0077 · Ponto Certificado — a batida com o VEREDITO, sem o rastro.
--
-- POR QUE ISTO EXISTE
-- ===================
--
-- A batida de ponto nasce no Ponto Certificado (REP-P em nuvem). O ERP lê o
-- mesmo fornecedor, mas só pelo AFD — formato da Portaria 671, que não tem
-- coordenada por desenho — e por importação MANUAL: mediana de 3 dias entre
-- execuções, máximo de 18, uma única pessoa executando. Medido em 09/09/2026,
-- o ERP enxergava até 06/09 enquanto o fornecedor já tinha a batida das 20h42
-- do próprio dia. Pela API a latência mediana é de 12 segundos.
--
-- O QUE ESTE ESQUEMA GUARDA, E O QUE ELE RECUSA A GUARDAR
-- =======================================================
--
-- A cerca precisa responder UMA pergunta: a batida caiu na unidade? Para isso
-- basta o VEREDITO e a DISTÂNCIA. A coordenada crua responderia muito mais —
-- por onde a pessoa andou, a que horas, em que dias — e isso é histórico de
-- deslocamento de trabalhador, que a empresa não precisa e não deve manter.
--
-- Então `pc_marcacao` guarda `situacao` (dentro / fora / sem_coordenada) e
-- `distancia_m` (um escalar até a cerca mais próxima), e NÃO guarda latitude
-- nem longitude. Com isso ainda se recalibra raio de cerca — que foi o achado
-- que originou esta frente: os raios cadastrados estão apertados, PIRAQUARA
-- com 40 m onde o p95 real é 87 m — sem reconstruir o trajeto de ninguém.
--
-- Pela mesma razão não entram CPF nem PIS: a MATRÍCULA (6 dígitos) identifica
-- as mesmas pessoas e é a chave que casa com a chapa do ERP. Medido: 261
-- marcações, 77 pessoas, e matrícula preenchida em 100% delas.
--
-- A CERCA é outra coisa: `pc_cerca` guarda latitude e longitude porque ali a
-- coordenada é de um PÁTIO DA EMPRESA, não de uma pessoa.
--
-- O CURSOR
-- ========
--
-- `pc_cursor` guarda o último id consumido. Três regras que custam caro se
-- erradas, todas medidas contra o serviço real:
--
--   1. O cursor NÃO parte de zero: `ultIdImportado=0` devolve lista VAZIA, não
--      o histórico. Um cursor gravado como 0 nunca anda, e a coleta fica parada
--      sem erro nenhum. Por isso `ultimo_id` tem CHECK de positivo — a primeira
--      carga é por período e semeia o cursor.
--   2. A página tem teto de 1.000. Quem parar na primeira perde o resto.
--   3. `id` é do fornecedor e é a chave natural: `ON CONFLICT DO UPDATE` faz a
--      coleta idempotente, que é o que permite rodar de novo depois de uma
--      queda sem duplicar nada.

CREATE TABLE IF NOT EXISTS pc_marcacao (
    id            BIGINT       PRIMARY KEY,          -- id do fornecedor
    nsr           BIGINT,
    matricula     TEXT         NOT NULL,
    marcada_em    TIMESTAMPTZ  NOT NULL,
    inserida_em   TIMESTAMPTZ,
    latencia_s    INTEGER,
    atividade     TEXT,                              -- vazia em 65% das batidas
    relogio       TEXT,
    -- 'dentro' | 'fora' | 'sem_coordenada'. O terceiro é o mais comum (44%) e
    -- NUNCA é infração: o fornecedor rotula "FORA DE CERCA" tudo que chega sem
    -- GPS, e tratar isso como estar fora do lugar foi o que encheu o alarme
    -- antigo com gente que não fez nada.
    situacao      TEXT         NOT NULL
                  CHECK (situacao IN ('dentro', 'fora', 'sem_coordenada')),
    local         TEXT,
    id_local      INTEGER,
    -- Distância até a cerca mais próxima, em metros. NULL quando não há
    -- coordenada — e NULL aqui é "não sei", nunca zero.
    distancia_m   INTEGER,
    cerca_proxima TEXT,
    coletada_em   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pc_marcacao_dia    ON pc_marcacao (marcada_em DESC);
CREATE INDEX IF NOT EXISTS pc_marcacao_pessoa ON pc_marcacao (matricula, marcada_em DESC);
-- Só as que exigem conferência: o índice parcial não carrega as 'dentro',
-- que são a maioria e não geram trabalho para ninguém.
CREATE INDEX IF NOT EXISTS pc_marcacao_fora   ON pc_marcacao (marcada_em DESC)
                                              WHERE situacao = 'fora';

CREATE TABLE IF NOT EXISTS pc_cerca (
    id_local     INTEGER      PRIMARY KEY,           -- a linha do fornecedor
    id_cerca     INTEGER      NOT NULL,              -- agrupa os vértices
    nome         TEXT         NOT NULL,
    descricao    TEXT,
    endereco     TEXT,
    -- 'circulo' usa raio_m; 'poligono' vem com raio 0 e uma LINHA POR VÉRTICE,
    -- todas com o mesmo id_cerca. Tratar polígono como círculo de raio zero
    -- reprova toda batida da unidade.
    forma        TEXT         NOT NULL CHECK (forma IN ('circulo', 'poligono')),
    raio_m       NUMERIC(8,1) NOT NULL DEFAULT 0,
    lat          NUMERIC(11,8) NOT NULL,
    lon          NUMERIC(11,8) NOT NULL,
    -- No corpo do fornecedor isto chega como TEXTO "True"/"False": bool("False")
    -- é True, e a cerca desligada passaria por ligada.
    ativa        BOOLEAN      NOT NULL DEFAULT TRUE,
    local_ativo  BOOLEAN      NOT NULL DEFAULT TRUE,
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pc_cerca_agrupada ON pc_cerca (id_cerca);

CREATE TABLE IF NOT EXISTS pc_cursor (
    chave           TEXT        PRIMARY KEY,
    ultimo_id       BIGINT      NOT NULL CHECK (ultimo_id > 0),
    marcacoes       BIGINT      NOT NULL DEFAULT 0,
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_coleta_em TIMESTAMPTZ,
    ultimo_erro     TEXT
);
