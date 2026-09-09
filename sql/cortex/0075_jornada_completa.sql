-- 0075 — a integração RasterJOR completa: diárias, macros, exceções, anomalias
--        e veículos.
--
-- POR QUE ESTAS TABELAS EXISTEM
-- =============================
-- O CÓRTEX coletava 4 dos 11 endpoints que a RasterJOR publica. Os outros
-- viviam numa ETL do ERP que MORREU sem alarme nenhum: as anomalias em
-- 27/05/2025, inconformidades e produtividade em 15/04/2026, a produtividade
-- espelhada em 18/05/2026 e — a que mais custou — a diária por dia em
-- 12/02/2026. O sintoma de todas foi o mesmo: uma tela vazia, que se lê como
-- "ninguém rodou".
--
-- Estas cinco tabelas trazem o resto da API para dentro da casa, com trilha em
-- `jor_carga` como as outras quatro. Depois delas o CÓRTEX não depende de
-- nenhuma rotina do ERP para saber da jornada.
--
-- O QUE NENHUMA DELAS GUARDA
-- ==========================
-- O CID médico. O contrato de ausência da RasterJOR tem o campo `cid`, o
-- coletor atual já o ignorava, e ele continua ignorado de propósito: é dado de
-- saúde, o repositório do código é PÚBLICO, e nada na casa precisa dele para
-- responder pergunta nenhuma. Guard em tests/jornada/test_integracao_completa.py.

-- ------------------------------------------------------------------ diárias --
-- A DIÁRIA APURADA PELO FORNECEDOR, que é outra coisa da diária PAGA pela
-- folha (`sulista.diariaspagas_globus`, no AVA). São as duas pontas que a
-- auditoria compara: o que a RasterJOR apurou × o que o Globus pagou.
--
-- A DATA VEM DO PEDIDO, NÃO DO PAYLOAD — e é a coisa mais importante a saber
-- sobre esta tabela. O endpoint /diarias/ devolve um AGREGADO do período:
-- pedindo 01/01 a 31/01 ele responde "fulano: 12 meias e 4 inteiras", sem
-- dizer em que dias. A granularidade de DIA é uma escolha da coleta (uma
-- chamada por dia), não um campo da fonte. Quem "otimizar" a coleta para pedir
-- a semana inteira e distribuir pelos dias estará INVENTANDO datas.
CREATE TABLE IF NOT EXISTS jor_diarias(
    documento       text NOT NULL,
    data            date NOT NULL,
    tipo            text NOT NULL,
    pais            text NOT NULL DEFAULT 'BR',
    nome            text NOT NULL DEFAULT '',
    quantidade      integer NOT NULL DEFAULT 0,
    valor_unitario  numeric(12,2),
    valor_total     numeric(12,2),
    coletado_em     text NOT NULL DEFAULT '',
    origem          text NOT NULL DEFAULT 'api',
    PRIMARY KEY (documento, data, tipo, pais)
);

CREATE INDEX IF NOT EXISTS ix_jor_diarias_data ON jor_diarias(data DESC);

COMMENT ON TABLE jor_diarias IS
    'Diária APURADA pela RasterJOR, por motorista e por dia. Não confundir com
     a diária PAGA, que vive no AVA (sulista.diariaspagas_globus) e é o outro
     lado da auditoria. A chave é o CPF, o que torna o cruzamento com
     jor_jornadas exato — a folha só tem o nome.';
COMMENT ON COLUMN jor_diarias.data IS
    'A data PEDIDA na chamada, não um campo do payload: o endpoint agrega o
     período e não diz em que dias as diárias caíram. Coleta-se um dia por
     chamada exatamente para que esta coluna signifique o que ela parece
     significar.';
COMMENT ON COLUMN jor_diarias.quantidade IS
    'Quantas diárias daquele tipo no dia. É o campo que a FOLHA nunca preencheu
     (referencia = 0,00 em todos os lançamentos, o que obrigava a tela a dizer
     "dá para saber quanto se pagou, não quantas foram"). Aqui vem preenchido.';

-- ------------------------------------------------------------------- macros --
-- OS EVENTOS DO MOTORISTA — as "macros". É a camada mais crua que a API
-- publica: cada troca de estado (EM DESCANSO, EM REFEICAO…) com início, fim,
-- duração e ORIGEM. É delas que sai a resposta para "macro errada" e
-- "apontamento divergente": a jornada apurada é a consequência, o evento é a
-- causa.
--
-- É A MAIOR TABELA DA FAMÍLIA — medido: ~558 eventos por dia, ~140 mil em
-- 2026. Daí os dois índices; sem eles a tela de apontamentos varre tudo.
CREATE TABLE IF NOT EXISTS jor_eventos(
    documento       text NOT NULL,
    codigo          integer NOT NULL,
    inicio          timestamp NOT NULL,
    nome            text NOT NULL DEFAULT '',
    evento          text NOT NULL DEFAULT '',
    fim             timestamp,
    duracao_min     integer,
    origem_evento   text NOT NULL DEFAULT '',
    placa           text NOT NULL DEFAULT '',
    filial          text NOT NULL DEFAULT '',
    escala          text NOT NULL DEFAULT '',
    coletado_em     text NOT NULL DEFAULT '',
    origem          text NOT NULL DEFAULT 'api',
    PRIMARY KEY (documento, codigo, inicio)
);

CREATE INDEX IF NOT EXISTS ix_jor_eventos_inicio ON jor_eventos(inicio DESC);
CREATE INDEX IF NOT EXISTS ix_jor_eventos_origem ON jor_eventos(origem_evento, inicio DESC);

COMMENT ON TABLE jor_eventos IS
    'Eventos (macros) do motorista, vindos de /external-api/driver-events/. A
     chave natural é (documento, codigo, inicio) porque a API não devolve id: o
     mesmo evento recoletado tem os três iguais, e recoletar é o caso normal.';
COMMENT ON COLUMN jor_eventos.origem_evento IS
    'O `origin` da API (ex.: FULL_JOURNEY). Guarda-se a string CRUA: não há
     tabela de domínio no contrato, e código sem domínio não vira rótulo
     inventado. É por esta coluna que se separa o que veio do equipamento do
     que veio de digitação.';

-- ---------------------------------------------------------------- exceções --
-- OS APONTAMENTOS COM STATUS. Diferente das inconformidades (que são fatos
-- apurados), a exceção tem um FLUXO: `status_excecao` e `nivel_excecao`.
--
-- ESTA É A ÚNICA TABELA DA FAMÍLIA SEM CPF, e isso é limitação da fonte, não
-- escolha nossa: /journey-exceptions/ devolve `nome_motorista` e mais nada que
-- identifique a pessoa. Guarda-se o nome CRU e o nome NORMALIZADO ao lado —
-- o normalizado é o que casa com o resto da casa, e tê-lo numa coluna evita
-- que cada consulta reinvente a normalização (duas normalizações diferentes
-- fariam duas telas discordarem sobre quem é a mesma pessoa).
CREATE TABLE IF NOT EXISTS jor_excecoes(
    gerada_em       timestamp NOT NULL,
    nome            text NOT NULL,
    nome_norm       text NOT NULL DEFAULT '',
    codigo_tipo     integer NOT NULL,
    tipo            text NOT NULL DEFAULT '',
    veiculo         text NOT NULL DEFAULT '',
    status          integer,
    nivel           integer,
    coletado_em     text NOT NULL DEFAULT '',
    origem          text NOT NULL DEFAULT 'api',
    PRIMARY KEY (gerada_em, nome, codigo_tipo)
);

CREATE INDEX IF NOT EXISTS ix_jor_excecoes_data ON jor_excecoes(gerada_em DESC);
CREATE INDEX IF NOT EXISTS ix_jor_excecoes_norm ON jor_excecoes(nome_norm, gerada_em DESC);

COMMENT ON TABLE jor_excecoes IS
    'Exceções de jornada (/external-api/journey-exceptions/), com status e
     nível. ÚNICA tabela jor_* sem CPF: a fonte só manda o nome. O cruzamento
     com as outras passa por nome_norm e é, por isso, o elo mais fraco da
     família — o que a tela precisa dizer quando alguém não casar.';
COMMENT ON COLUMN jor_excecoes.status IS
    'status_excecao cru. Sem tabela de domínio no contrato: guarda-se o número
     e a tela mostra o número, em vez de inventar rótulo.';

-- --------------------------------------------------------------- anomalias --
-- A RÉGUA DO PRÓPRIO FORNECEDOR. É a única coisa aqui que não é dado bruto:
-- é o julgamento da RasterJOR sobre o que ela viu, com uma bandeira de
-- `resolved`. Ficou quinze meses sem chegar (a cópia do ERP parou em
-- 27/05/2025) e ninguém notou, porque a ausência de julgamento parece
-- concordância.
CREATE TABLE IF NOT EXISTS jor_anomalias(
    id_externo      bigint PRIMARY KEY,
    momento         timestamp,
    criada_em       timestamp,
    tipo            integer,
    placa           text NOT NULL DEFAULT '',
    nome            text NOT NULL DEFAULT '',
    documento       text NOT NULL DEFAULT '',
    descricao       text NOT NULL DEFAULT '',
    resolvida       integer NOT NULL DEFAULT 0,
    coletado_em     text NOT NULL DEFAULT '',
    origem          text NOT NULL DEFAULT 'api'
);

CREATE INDEX IF NOT EXISTS ix_jor_anomalias_momento ON jor_anomalias(momento DESC);

COMMENT ON TABLE jor_anomalias IS
    'Anomalias apontadas pela própria RasterJOR. A chave é o id DELA: é o único
     recurso da família em que o fornecedor dá identidade estável, e usá-la é
     o que permite ver a mesma anomalia mudar de `resolvida` sem duplicar.';

-- ---------------------------------------------------------------- veículos --
-- SNAPSHOT, NÃO HISTÓRICO — e a diferença custa caro. A tabela equivalente no
-- ERP (`sulista.rasterjor_vehicles`) acumulou 124.665 linhas guardando cada
-- leitura da mesma posição dos mesmos ~175 veículos; virou um log que ninguém
-- consulta e que só cresce. Aqui a placa é a chave e guarda-se o ESTADO, com
-- a hora em que ele foi lido.
--
-- Posição de veículo para operar NÃO sai daqui: quem funde Gobrax + ERP e
-- vence a leitura mais recente é `api/posicoes.py`. Esta tabela responde
-- "o que a RasterJOR sabe da frota", que é pergunta de conferência de cadastro.
CREATE TABLE IF NOT EXISTS jor_veiculos(
    placa           text PRIMARY KEY,
    motorista       text NOT NULL DEFAULT '',
    ultima_posicao  text NOT NULL DEFAULT '',
    latitude        numeric(12,7),
    longitude       numeric(12,7),
    evento_atual    text NOT NULL DEFAULT '',
    evento_duracao  text NOT NULL DEFAULT '',
    coletado_em     text NOT NULL DEFAULT '',
    origem          text NOT NULL DEFAULT 'api'
);

COMMENT ON TABLE jor_veiculos IS
    'Estado atual dos veículos conhecidos pela RasterJOR — SNAPSHOT por placa,
     não histórico. A cópia no ERP guardava cada leitura e chegou a 124.665
     linhas para 175 veículos. Posição para operar vem de api/posicoes.py.';
COMMENT ON COLUMN jor_veiculos.ultima_posicao IS
    'Texto CRU do fornecedor ("08/09/2026 22:53:00 - 0.02 km de ..."). Não é
     parseado: o formato é dele e pode mudar, e a lat/long vêm em colunas
     próprias para quem precisa do número.';
