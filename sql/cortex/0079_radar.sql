-- 0079 · Radar do Transporte — o que a página inicial do CÓRTEX lê.
--
-- POR QUE ISTO ESTÁ NO BANCO, SE É TUDO PÚBLICO E RECONSTRUÍVEL
-- =============================================================
-- A regra da casa manda cache reconstruível para fora do banco. Esta é a
-- exceção, e por um motivo medido: a página inicial é a PRIMEIRA tela de todo
-- mundo, e ela não pode depender de quatro sites de terceiro responderem na
-- hora. A série do Brent inteira tem 1,8 MB e a Ipeadata a devolve em até
-- 40 s (medido em 11/09/2026: a primeira tentativa por http estourou os 40 s
-- sem um byte). Buscar na abertura da tela seria abrir o CÓRTEX olhando para
-- uma barra de carregamento — e o AutoDeploy reinicia a API várias vezes por
-- dia, então um cache só em memória seria pago de novo a cada push.
-- Com as tabelas, a tela lê o banco local (milissegundos) e quem fala com a
-- rede é o relógio (`api/radar/agendador.py`), no ritmo de cada fonte.
--
-- NADA AQUI É DADO DA SULISTA. Preço de bomba da ANP, Brent, PTAX e manchetes
-- — é justamente isso que permite a tela ser de TODO usuário logado.

-- Diesel semanal da ANP, média Brasil. A chave é (produto, semana): a planilha
-- é republicada inteira toda semana e a coleta regrava por cima, idempotente.
CREATE TABLE IF NOT EXISTS rad_combustivel (
    produto            text         NOT NULL,   -- diesel_s10 | diesel_s500
    semana_fim         date         NOT NULL,   -- sábado que fecha a pesquisa
    semana_inicio      date,
    postos             integer,                 -- postos pesquisados na semana
    unidade            text,
    preco_revenda      numeric(8,3),            -- média de bomba, R$/l
    preco_min          numeric(8,3),
    preco_max          numeric(8,3),
    preco_distribuicao numeric(8,3),            -- NULL desde ago/2020 (a ANP parou de coletar)
    coletado_em        timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (produto, semana_fim)
);

-- Séries diárias: `brent` (US$/barril, contrato futuro BZ=F, fechamento do
-- dia pelo Yahoo), `dolar` (R$ por US$, comercial, Yahoo) e `ptax` (PTAX de
-- venda, SGS 1 do Banco Central). Dia sem cotação NÃO tem linha — zero seria
-- um preço. A linha de HOJE é regravada a cada coleta enquanto o pregão anda.
CREATE TABLE IF NOT EXISTS rad_serie (
    serie        text          NOT NULL,
    dia          date          NOT NULL,
    valor        numeric(12,4) NOT NULL,
    coletado_em  timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (serie, dia)
);

-- O preço de AGORA de cada série de mercado: uma linha por série, regravada a
-- cada coleta. `momento` é a hora do ÚLTIMO NEGÓCIO dita pela fonte, não a da
-- coleta — num sábado ela é sexta à tarde, e a tela diz isso.
CREATE TABLE IF NOT EXISTS rad_cotacao (
    serie        text          PRIMARY KEY,     -- brent | dolar
    valor        numeric(12,4) NOT NULL,
    momento      timestamptz   NOT NULL,
    moeda        text,
    simbolo      text,
    fuso         text,                          -- o da bolsa: é nele que se lê o "dia" da série
    coletado_em  timestamptz   NOT NULL DEFAULT now()
);

-- Ocorrências nas rodovias AGORA (TomTom, só as que têm número de rodovia).
-- É um RETRATO: cada coleta boa substitui a anterior inteira, na mesma
-- transação. Coleta que falha não apaga o retrato velho — a tela mostra a
-- hora dele.
CREATE TABLE IF NOT EXISTS rad_rodovia (
    regiao        text     NOT NULL,            -- o corredor consultado
    ordem         integer  NOT NULL,
    rodovias      text,                         -- "BR-116 · SP-021"
    categoria     text     NOT NULL,            -- rótulo da TomTom (Via fechada, Obras…)
    bloqueia      boolean  NOT NULL,
    descricao     text,
    de            text,
    para          text,
    atraso_s      integer,                      -- NULL = a TomTom não estima (≠ zero)
    magnitude     text,
    coletado_em   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (regiao, ordem)
);

-- Manchetes. A identidade é o `guid` do RSS POR TEMA: a mesma matéria pode
-- responder a duas buscas (diesel e transporte), e ela aparece nas duas abas.
CREATE TABLE IF NOT EXISTS rad_noticia (
    tema          text         NOT NULL,        -- trc | diesel | reforma
    guid          text         NOT NULL,
    titulo        text         NOT NULL,
    fonte         text,                         -- o veículo
    link          text         NOT NULL,
    publicada_em  timestamptz  NOT NULL,
    visto_em      timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (tema, guid)
);
CREATE INDEX IF NOT EXISTS ix_rad_noticia_recente ON rad_noticia (tema, publicada_em DESC);

-- O estado de cada fonte. `tentativa_em` decide a cadência (a coleta não
-- martela um site fora do ar); `sucesso_em` é o que a Saúde mede. Falha NÃO
-- apaga o que já estava gravado: `itens` e `dado_ate` só andam com sucesso.
CREATE TABLE IF NOT EXISTS rad_coleta (
    fonte         text PRIMARY KEY,             -- anp | brent | ptax | noticias_<tema>
    tentativa_em  timestamptz,
    sucesso_em    timestamptz,
    ok            boolean,
    itens         integer,
    descartados   integer,                      -- fora da faixa física, ou velhas demais
    erro          text,                         -- o TIPO da falha, nunca a mensagem crua
    dado_ate      date                          -- o dado mais novo que a fonte tinha
);
