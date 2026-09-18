-- PROGRAMA DE DESEMPENHO — a campanha trimestral com sorteio de prêmio.
--
-- POR QUE NÃO É A MESMA COISA QUE A PREMIAÇÃO MENSAL (`prm_*`): aquela PAGA,
-- todo ciclo, por uma régua operacional que a mesa ajusta quando quer. Esta é
-- um REGULAMENTO — documento assinado, com vigência, público definido e um
-- sorteio no fim. As duas leem os mesmos três pilares e dão notas diferentes
-- de propósito, porque os PESOS são outros (50/30/20 contra 40/40/20) e as
-- faixas de categoria também.
--
-- POR ISSO A RÉGUA MORA NA CAMPANHA, e não em `prm_param`: o peso que decide
-- quem concorre a uma moto é o que está no papel que o motorista assinou. Se
-- alguém mudar a régua operacional em novembro, o trimestre em curso não pode
-- mudar junto — e uma régua versionada por competência mudaria.
--
-- O QUE ESTA TABELA NÃO GUARDA: valor de prêmio em reais (o prêmio aqui é um
-- BEM, descrito em texto) e CPF. A chave de quem participa é opaca — o código
-- do motorista agregado no ERP É o CPF (11 dígitos em 279 de 279, medido em
-- 18/09/2026), e publicá-lo na tela seria publicar documento.

CREATE TABLE IF NOT EXISTS cmp_campanha (
    id            bigserial PRIMARY KEY,
    nome          text NOT NULL,
    de_ciclo      text NOT NULL,
    ate_ciclo     text NOT NULL,
    sorteio_em    date,
    premio        text NOT NULL DEFAULT '',
    onde          text NOT NULL DEFAULT '',
    -- A RÉGUA DO REGULAMENTO, congelada na campanha.
    peso_gobrax   numeric(5,2) NOT NULL,
    peso_conduta  numeric(5,2) NOT NULL,
    peso_gr       numeric(5,2) NOT NULL,
    cat_elite     numeric(5,2) NOT NULL,
    cat_ouro      numeric(5,2) NOT NULL,
    cat_prata     numeric(5,2) NOT NULL,
    -- TELEMETRIA COMO CONDIÇÃO DE DISPUTA (decisão de quem opera, 18/09/2026):
    -- a Gobrax vale metade da nota e enxergava 34% dos agregados. Quem não tem
    -- leitura participa e vê a nota dele, mas fica FORA do sorteio — é a única
    -- forma de todos os que disputam serem medidos pela mesma régua.
    exige_gobrax  boolean NOT NULL DEFAULT true,
    situacao      text NOT NULL DEFAULT 'aberta',
    criado_em     text NOT NULL,
    criado_por    text NOT NULL,
    CONSTRAINT cmp_campanha_ciclos CHECK (de_ciclo <= ate_ciclo),
    CONSTRAINT cmp_campanha_ciclo_fmt CHECK (de_ciclo ~ '^[0-9]{4}-[0-9]{2}$'
                                         AND ate_ciclo ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT cmp_campanha_situacao CHECK (situacao IN ('aberta', 'encerrada')),
    CONSTRAINT cmp_campanha_pesos CHECK (peso_gobrax + peso_conduta + peso_gr = 100)
);

COMMENT ON TABLE cmp_campanha IS
    'Um programa de desempenho com vigencia e premio. A regua fica AQUI porque
     e a do regulamento assinado, e ela nao pode mudar no meio do trimestre.';

-- A FOTOGRAFIA MENSAL, que é o que o regulamento manda divulgar até o 10º dia
-- útil do mês seguinte. Ela existe pelo mesmo motivo do fechamento da
-- premiação: as quatro fontes continuam se mexendo, e a categoria de outubro
-- não pode mudar em dezembro — ela decide quem concorre.
CREATE TABLE IF NOT EXISTS cmp_foto (
    campanha_id bigint NOT NULL REFERENCES cmp_campanha(id) ON DELETE CASCADE,
    ciclo       text NOT NULL,
    grupo       text NOT NULL,
    chave       text NOT NULL,
    nome        text NOT NULL,
    gobrax      numeric(6,2),
    conduta     numeric(6,2),
    gr          numeric(6,2),
    nota        numeric(6,2),
    categoria   text,
    elegivel    boolean NOT NULL DEFAULT false,
    motivo      text NOT NULL DEFAULT '',
    PRIMARY KEY (campanha_id, ciclo, grupo, chave),
    CONSTRAINT cmp_foto_grupo CHECK (grupo IN ('FROTA', 'AGREGADO'))
);

COMMENT ON TABLE cmp_foto IS
    'A categoria de cada participante em cada ciclo do programa, congelada.
     `motivo` diz por que alguem NAO esta elegivel — nunca um silencio.';
COMMENT ON COLUMN cmp_foto.chave IS
    'Chave OPACA do participante. O codigo do motorista agregado no ERP e o
     CPF, e ele nao trafega: quem faz a ponte e o servidor.';

-- O SORTEIO, auditável. O regulamento promete "conduzido de forma transparente
-- e auditável", e isso não é um adjetivo: é a lista congelada ANTES, a semente
-- registrada, e o resultado com suplente. Sem os três, "foi sorteado" é uma
-- afirmação que ninguém pode conferir depois.
CREATE TABLE IF NOT EXISTS cmp_sorteio (
    id           bigserial PRIMARY KEY,
    campanha_id  bigint NOT NULL REFERENCES cmp_campanha(id) ON DELETE CASCADE,
    grupo        text NOT NULL,
    ciclo        text NOT NULL,
    elegiveis    integer NOT NULL,
    semente      text NOT NULL,
    ganhador     text NOT NULL,
    ganhador_nome text NOT NULL,
    suplente     text NOT NULL DEFAULT '',
    suplente_nome text NOT NULL DEFAULT '',
    ata          text NOT NULL DEFAULT '',
    realizado_em text NOT NULL,
    realizado_por text NOT NULL,
    CONSTRAINT cmp_sorteio_grupo CHECK (grupo IN ('FROTA', 'AGREGADO'))
);

COMMENT ON TABLE cmp_sorteio IS
    'O resultado do sorteio com a SEMENTE e o numero de elegiveis: com os dois,
     qualquer pessoa refaz o sorteio e chega no mesmo nome.';

CREATE INDEX IF NOT EXISTS cmp_foto_campanha_idx ON cmp_foto (campanha_id, ciclo);
