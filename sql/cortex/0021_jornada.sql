-- Jornada do motorista — as tabelas do CÓRTEX, alimentadas pela API da RasterJOR.
--
-- POR QUE TRAZER PARA CÁ o que já existia em `sulista.rasterjor_*` no AVA:
-- aquelas tabelas são alimentadas por uma rotina EXTERNA, que parou em
-- 15/04/2026 e ficou quatro meses e meio parada sem ninguém notar. O CÓRTEX
-- não tinha como consertar nem como saber — só descobriu porque alguém foi
-- montar uma tela em cima. Com a coleta aqui dentro, a falha vira linha
-- vermelha na Saúde do Servidor no dia em que acontece.
--
-- O AVA CONTINUA SENDO A ORIGEM DO HISTÓRICO: a carga inicial copia
-- `sulista.rasterjor_*` para cá (é dado real, de 01/01/2025 a 15/04/2026, e
-- jogar fora seria perder quinze meses). Daí para a frente quem escreve é a
-- coleta própria.
--
-- IDEMPOTÊNCIA POR CHAVE NATURAL, não por id do fornecedor. A API devolve a
-- jornada do dia inteira a cada chamada, e coletar duas vezes o mesmo dia é o
-- caso NORMAL (a rotina roda de hora em hora e o dia só fecha à noite). A
-- chave é (motorista, data) para a jornada e (motorista, tipo, início) para a
-- inconformidade — reprocessar sobrescreve em vez de duplicar.

-- ------------------------------------------------------------- motoristas --
-- `documento` (CPF) é a chave, e não o `driver_id` da RasterJOR: é por CPF que
-- esta tabela casa com a folha, com a CNH e com a jornada do ERP. O id do
-- fornecedor fica guardado para a próxima chamada de API, não para juntar.
CREATE TABLE IF NOT EXISTS jor_motoristas(
    documento       text PRIMARY KEY,
    nome            text NOT NULL DEFAULT '',
    api_id          bigint,
    ativo           integer NOT NULL DEFAULT 1,
    filial          text NOT NULL DEFAULT '',
    escala          text NOT NULL DEFAULT '',
    cargo           text NOT NULL DEFAULT '',
    admissao        date,
    cidade_base     text NOT NULL DEFAULT '',
    coletado_em     text NOT NULL DEFAULT '',
    origem          text NOT NULL DEFAULT 'api'
);

COMMENT ON COLUMN jor_motoristas.origem IS
    'api = veio da coleta; ava = veio da carga inicial de sulista.rasterjor_*.
     Distinguir importa no dia em que os números divergirem.';

-- ---------------------------------------------------------------- jornada --
-- Uma linha por motorista por DIA — é a granularidade que a RasterJOR entrega
-- em /productivity, e é a mesma da folha.
--
-- OS TEMPOS FICAM EM MINUTOS INTEIROS, como a API manda. Converter para
-- interval na gravação criaria uma segunda verdade sobre arredondamento; a
-- conversão para hora acontece na leitura, num lugar só.
CREATE TABLE IF NOT EXISTS jor_jornadas(
    documento           text NOT NULL,
    data                date NOT NULL,
    nome                text    NOT NULL DEFAULT '',
    filial              text    NOT NULL DEFAULT '',
    escala              text    NOT NULL DEFAULT '',
    tipo                text    NOT NULL DEFAULT '',
    inicio              timestamp,
    fim                 timestamp,
    min_total           integer NOT NULL DEFAULT 0,
    min_atividade       integer NOT NULL DEFAULT 0,
    min_direcao         integer NOT NULL DEFAULT 0,
    min_parado          integer NOT NULL DEFAULT 0,
    min_refeicao        integer NOT NULL DEFAULT 0,
    min_descanso        integer NOT NULL DEFAULT 0,
    min_repouso         integer NOT NULL DEFAULT 0,
    min_extra           integer NOT NULL DEFAULT 0,
    min_falta           integer NOT NULL DEFAULT 0,
    min_falta_repouso   integer NOT NULL DEFAULT 0,
    min_atividade_acima integer NOT NULL DEFAULT 0,
    km                  numeric(12,2),
    coletado_em         text NOT NULL DEFAULT '',
    origem              text NOT NULL DEFAULT 'api',
    PRIMARY KEY (documento, data)
);

CREATE INDEX IF NOT EXISTS ix_jor_jornadas_data ON jor_jornadas(data DESC);
CREATE INDEX IF NOT EXISTS ix_jor_jornadas_filial ON jor_jornadas(filial, data);

COMMENT ON TABLE jor_jornadas IS
    'Jornada apurada pela RasterJOR, uma linha por motorista por dia. A chave
     é (documento, data) e não um id do fornecedor: a API devolve o dia inteiro
     a cada chamada, e recoletar o mesmo dia é o caso normal — a rotina roda
     várias vezes e o dia só fecha à noite.';
COMMENT ON COLUMN jor_jornadas.tipo IS
    'journey_type da API (N, D, A, F). NÃO HÁ TABELA DE DOMÍNIO nem rótulo no
     payload: guarda-se a letra, e a tela mostra a letra com o que se observa
     em cada uma. Código sem domínio não vira rótulo inventado.';
COMMENT ON COLUMN jor_jornadas.min_parado IS
    'stopped_in_journey_time: em jornada, à disposição, sem dirigir. É a maior
     fatia do dia do motorista nesta operação — maior que a direção.';

-- -------------------------------------------------------- inconformidades --
-- O tipo vem NOMEADO pela RasterJOR (DIRECAO NOTURNA, EXCESSO DE JORNADA…).
-- Nada de código traduzido a dedo aqui.
CREATE TABLE IF NOT EXISTS jor_inconformidades(
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    documento     text NOT NULL,
    data          date NOT NULL,
    tipo          text NOT NULL,
    nome          text NOT NULL DEFAULT '',
    placa         text NOT NULL DEFAULT '',
    inicio        timestamp,
    fim           timestamp,
    -- CHAVE DO EVENTO, e a razão dela existir vale a linha extra:
    -- 56% das inconformidades NÃO TÊM hora de início. Medido: DIRECAO NOTURNA,
    -- DIRECAO ININTERRUPTA e EXCESSO DE VELOCIDADE sempre têm (43.092 linhas);
    -- EXCESSO DE JORNADA, JORNADA SEM PARADA PARA REFEICAO e NAO CUMPRIMENTO
    -- DO INTERVALO DE JORNADAS nunca têm (55.017) — são fatos do DIA, não
    -- intervalos.
    --
    -- Um UNIQUE sobre `inicio` nulo não restringe nada (no Postgres NULL é
    -- sempre distinto de NULL), então as 55 mil duplicariam a cada recarga. E
    -- preencher `inicio` com a meia-noite seria inventar um horário que a
    -- fonte não deu, que depois vira gráfico.
    --
    -- Daí a coluna separada: `inicio` guarda a VERDADE (nulo quando é nulo) e
    -- `chave_evento` guarda o que serve para deduplicar.
    chave_evento  timestamp NOT NULL,
    duracao_min   integer,
    velocidade    numeric(8,2),
    observacao    text NOT NULL DEFAULT '',
    coletado_em   text NOT NULL DEFAULT '',
    origem        text NOT NULL DEFAULT 'api',
    CONSTRAINT jor_inconf_uk UNIQUE (documento, tipo, chave_evento)
);

CREATE INDEX IF NOT EXISTS ix_jor_inconf_data ON jor_inconformidades(data DESC);
CREATE INDEX IF NOT EXISTS ix_jor_inconf_tipo ON jor_inconformidades(tipo, data);

COMMENT ON CONSTRAINT jor_inconf_uk ON jor_inconformidades IS
    'A chave natural. Sem ela, recoletar um dia duplicaria toda inconformidade
     dele — e recoletar é o caso normal, não a exceção. A tabela de origem no
     AVA não tem chave nenhuma e acumulou ~50% de duplicata por recarga
     repetida: 98.109 linhas para 49.446 eventos distintos.';
COMMENT ON COLUMN jor_inconformidades.inicio IS
    'Nulo nos tipos que são fato do DIA e não intervalo. Fica nulo de
     propósito: preencher com meia-noite inventaria um horário que a fonte não
     deu, e horário inventado vira gráfico.';

-- --------------------------------------------------------------- ausências --
CREATE TABLE IF NOT EXISTS jor_ausencias(
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    externo_id    bigint,
    documento     text NOT NULL DEFAULT '',
    nome          text NOT NULL DEFAULT '',
    tipo          text NOT NULL DEFAULT '',
    descricao     text NOT NULL DEFAULT '',
    observacao    text NOT NULL DEFAULT '',
    inicio        timestamp,
    fim           timestamp,
    coletado_em   text NOT NULL DEFAULT '',
    origem        text NOT NULL DEFAULT 'api',
    CONSTRAINT jor_ausencias_uk UNIQUE (documento, tipo, inicio)
);

CREATE INDEX IF NOT EXISTS ix_jor_ausencias_ini ON jor_ausencias(inicio DESC);

-- ------------------------------------------------------------ trilha de carga --
-- POR QUE ESTA TABELA EXISTE, e é ela que resolve o problema que motivou a
-- migração: a rotina do AVA parou e não havia onde olhar. Aqui cada passagem
-- da coleta grava — inclusive a que não trouxe nada e inclusive a que falhou.
--
-- `ok=0` com mensagem é MAIS importante que `ok=1`: é a linha que a Saúde lê
-- para dizer "parou de chegar" no dia em que parar, e não quatro meses depois.
CREATE TABLE IF NOT EXISTS jor_carga(
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           text    NOT NULL,
    recurso      text    NOT NULL,
    de           date,
    ate          date,
    ok           integer NOT NULL DEFAULT 0,
    lidos        integer NOT NULL DEFAULT 0,
    gravados     integer NOT NULL DEFAULT 0,
    ms           integer NOT NULL DEFAULT 0,
    mensagem     text    NOT NULL DEFAULT '',
    origem       text    NOT NULL DEFAULT 'api'
);

CREATE INDEX IF NOT EXISTS ix_jor_carga_ts ON jor_carga(ts DESC);

COMMENT ON TABLE jor_carga IS
    'Toda passagem da coleta, inclusive a que falhou e a que não trouxe nada.
     É daqui que a Saúde do Servidor descobre que a jornada parou de chegar —
     a rotina anterior vivia no AVA e ficou 136 dias parada sem sinal nenhum.';
