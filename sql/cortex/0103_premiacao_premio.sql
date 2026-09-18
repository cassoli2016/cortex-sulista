-- Gestão de Motoristas (GMA) — O PAGAMENTO: valor base, escada de tempo de
-- casa, ajuste individual e o FECHAMENTO do ciclo.
--
-- POR QUE O DINHEIRO MORA AQUI E NÃO NO CÓDIGO: o repositório é PÚBLICO. Valor
-- em reais não entra em migration, em seed nem em constante — é a regra da
-- casa (CLAUDE.md §8), e é por isso que estas tabelas nascem VAZIAS. Quem
-- opera preenche na tela; enquanto não preencher, a linha diz "filial sem
-- valor na tabela" em vez de pagar zero. Zero que é ausência de cadastro não é
-- prêmio de R$ 0,00: é um número que ninguém decidiu.
--
-- POR QUE PENDURADO EM `prem_versoes`, como os parâmetros: "desde quando este
-- valor vale" tem de ter UMA resposta só. A régua de setembro não pode
-- reescrever o que agosto pagou.

-- ---------------------------------------------------------------- valor base
-- O valor cheio (100% da nota) por GRUPO e FILIAL.
--
-- `usa_escada` é o que substitui um `IF filial IN ('SBC','JOI')` no código. No
-- modelo de quem opera a escada de tempo de casa vale hoje para as manobras de
-- duas filiais — mas isso é DECISÃO, não natureza: amanhã entra uma terceira,
-- e mexer em código para isso obrigaria um deploy (e poria nome de filial e
-- regra comercial no repositório público). A filial diz de si mesma como o
-- valor dela se forma.
CREATE TABLE IF NOT EXISTS prm_premio_base (
    versao_id  bigint  NOT NULL REFERENCES prem_versoes(id) ON DELETE CASCADE,
    grupo      text    NOT NULL,
    filial     text    NOT NULL,
    valor      numeric(12,2) NOT NULL,
    usa_escada boolean NOT NULL DEFAULT false,
    nota       text    NOT NULL DEFAULT '',
    PRIMARY KEY (versao_id, grupo, filial),
    CONSTRAINT prm_premio_base_grupo CHECK (grupo IN ('RODOVIARIO', 'MANOBRA')),
    CONSTRAINT prm_premio_base_valor CHECK (valor >= 0)
);

COMMENT ON TABLE prm_premio_base IS
    'Valor cheio do prêmio (100% da nota) por grupo e filial, por versão.
     Nasce vazia de proposito: valor em reais nao entra no repositorio.';
COMMENT ON COLUMN prm_premio_base.usa_escada IS
    'Quando verdadeiro, o valor desta filial sai da escada de tempo de casa e
     o campo `valor` vira apenas o teto informativo da tela.';
COMMENT ON COLUMN prm_premio_base.nota IS
    'O que a tela mostra ao lado do valor — por exemplo, filial cujo premio e
     pago dentro de outra verba por forca de convencao coletiva.';

-- ------------------------------------------------------- escada de tempo de casa
-- Degraus por tempo de casa, em MESES. Cada linha é "até N meses vale V"; o
-- último degrau é o teto (guardado como um `ate_meses` grande).
--
-- POR QUE EM MESES E NÃO EM ANOS: os degraus do modelo são 6, 8 e 12 meses —
-- o primeiro ano inteiro. Em anos, os três primeiros degraus não existiriam.
CREATE TABLE IF NOT EXISTS prm_premio_escada (
    versao_id  bigint  NOT NULL REFERENCES prem_versoes(id) ON DELETE CASCADE,
    grupo      text    NOT NULL,
    ate_meses  integer NOT NULL,
    valor      numeric(12,2) NOT NULL,
    PRIMARY KEY (versao_id, grupo, ate_meses),
    CONSTRAINT prm_premio_escada_grupo CHECK (grupo IN ('RODOVIARIO', 'MANOBRA')),
    CONSTRAINT prm_premio_escada_meses CHECK (ate_meses > 0),
    CONSTRAINT prm_premio_escada_valor CHECK (valor >= 0)
);

COMMENT ON TABLE prm_premio_escada IS
    'Degraus de tempo de casa (ate N meses -> valor), por grupo e versao. Vale
     para as filiais marcadas com `usa_escada` em prm_premio_base.';

-- --------------------------------------------------------------- ajuste individual
-- O valor base de UMA pessoa em UM ciclo, decidido à mão.
--
-- É POR CICLO, e não um campo no cadastro do motorista: ajuste que fica colado
-- na pessoa some da vista e continua valendo dois anos depois, quando quem
-- decidiu já não trabalha aqui. Aqui ele expira sozinho e cada ciclo diz quem
-- ajustou, quando e por quê — motivo é NOT NULL porque ajuste sem motivo é
-- exatamente o que ninguém consegue explicar na auditoria.
CREATE TABLE IF NOT EXISTS prm_premio_ajuste (
    ciclo      text NOT NULL,
    cpf        text NOT NULL REFERENCES prm_motorista(cpf) ON DELETE CASCADE,
    valor      numeric(12,2) NOT NULL,
    motivo     text NOT NULL,
    autor      text NOT NULL,
    criado_em  text NOT NULL,
    PRIMARY KEY (ciclo, cpf),
    CONSTRAINT prm_premio_ajuste_valor CHECK (valor >= 0),
    CONSTRAINT prm_premio_ajuste_motivo CHECK (btrim(motivo) <> ''),
    CONSTRAINT prm_premio_ajuste_ciclo CHECK (ciclo ~ '^[0-9]{4}-[0-9]{2}$')
);

COMMENT ON TABLE prm_premio_ajuste IS
    'Valor base decidido a mao para um motorista num ciclo. Expira com o ciclo;
     motivo e autor sao obrigatorios.';

-- ------------------------------------------------------------------ fechamento
-- A FOTOGRAFIA do ciclo. Mês pago não se recalcula.
--
-- Este é o ponto em que o cálculo vira número pago. Depois do fechamento a
-- tela mostra a FOTO, não o cálculo: a Gobrax reprocessa um mês, o ERP corrige
-- uma ocorrência com três semanas de atraso, alguém arruma o de-para — e
-- qualquer um desses movimentos mudaria, em silêncio, um valor que já saiu na
-- folha. A régua que a premiação antiga já segue.
--
-- REABRIR É POSSÍVEL e fica REGISTRADO. Regra sem escape vira regra contornada
-- por fora (alguém fecha de novo por cima, ou paga por planilha), e aí o
-- sistema deixa de ser a fonte. Reabrir exige motivo, e o motivo fica.
CREATE TABLE IF NOT EXISTS prm_fechamento (
    ciclo       text NOT NULL PRIMARY KEY,
    situacao    text NOT NULL DEFAULT 'fechado',
    total       numeric(14,2) NOT NULL DEFAULT 0,
    motoristas  integer NOT NULL DEFAULT 0,
    sem_nota    integer NOT NULL DEFAULT 0,
    nota        text NOT NULL DEFAULT '',
    fechado_em  text NOT NULL,
    fechado_por text NOT NULL,
    CONSTRAINT prm_fechamento_situacao CHECK (situacao IN ('fechado', 'reaberto')),
    CONSTRAINT prm_fechamento_ciclo CHECK (ciclo ~ '^[0-9]{4}-[0-9]{2}$')
);

COMMENT ON TABLE prm_fechamento IS
    'O ciclo fechado: a partir daqui a tela mostra a fotografia, nao o calculo.';

-- Uma linha por motorista, com TUDO que decidiu o valor — inclusive as notas
-- dos três pilares. Guardar só o valor faria a pergunta "por que ele recebeu
-- isto?" não ter resposta seis meses depois, que é justamente quando ela é
-- feita.
CREATE TABLE IF NOT EXISTS prm_fechamento_linha (
    ciclo        text NOT NULL,
    cpf          text NOT NULL,
    motorista    text NOT NULL,
    nome         text NOT NULL,
    grupo        text NOT NULL,
    filial       text,
    gobrax       numeric(6,2),
    conduta      numeric(6,2),
    gr           numeric(6,2),
    nota         numeric(6,2),
    status       text,
    categoria    text,
    base         numeric(12,2),
    base_origem  text,
    pct          numeric(6,2),
    valor        numeric(12,2),
    motivo       text NOT NULL DEFAULT '',
    PRIMARY KEY (ciclo, cpf)
);

COMMENT ON TABLE prm_fechamento_linha IS
    'A foto por motorista: notas, valor base, de onde o base veio, percentual e
     valor pago. Guardar so o valor deixa "por que ele recebeu isto?" sem
     resposta.';
COMMENT ON COLUMN prm_fechamento_linha.motivo IS
    'Por que nao ha valor, quando nao ha: sem nota no ciclo, filial sem valor
     na tabela. Ausencia com motivo, nunca R$ 0,00 calado.';

-- O histórico do que se fez com o fechamento. Append-only por convenção do
-- módulo: fechar, reabrir e fechar de novo deixam três linhas.
CREATE TABLE IF NOT EXISTS prm_fechamento_evento (
    id        bigserial PRIMARY KEY,
    ciclo     text NOT NULL,
    acao      text NOT NULL,
    motivo    text NOT NULL DEFAULT '',
    total     numeric(14,2),
    autor     text NOT NULL,
    criado_em text NOT NULL,
    CONSTRAINT prm_fechamento_evento_acao CHECK (acao IN ('fechou', 'reabriu'))
);

CREATE INDEX IF NOT EXISTS prm_fechamento_evento_ciclo_idx
    ON prm_fechamento_evento (ciclo, id);
