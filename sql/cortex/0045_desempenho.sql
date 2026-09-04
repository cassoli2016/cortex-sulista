-- Avaliação de Desempenho — nine box.
--
-- POR QUE A HIERARQUIA MORA AQUI E NÃO NO ERP: `vw_funcionarios` (Globus) tem
-- nome, cargo, área, seção, admissão e salário — e NENHUM campo de "a quem
-- responde". A relação gestor→equipe não existe na folha, então ou ela é nossa
-- ou o recorte "cada gestor vê a sua equipe" é ficção. Ela é nossa: o RH mapeia
-- o usuário do CÓRTEX a uma ou mais ÁREAS/SEÇÕES, que é como o ERP já organiza
-- as pessoas. Mapa vazio = o gestor não vê ninguém, e a tela diz isso — melhor
-- que abrir a casa inteira por omissão.
CREATE TABLE IF NOT EXISTS des_ciclo (
  id            SERIAL PRIMARY KEY,
  nome          TEXT NOT NULL,
  inicio        DATE NOT NULL,
  fim           DATE NOT NULL,
  -- ESTADO É CAMPO, não ausência de data: "aberto" é decisão de quem
  -- administra, e derivar isso de `fim < hoje` faria o ciclo fechar sozinho
  -- num domingo, no meio de uma avaliação.
  estado        TEXT NOT NULL DEFAULT 'rascunho'
                CHECK (estado IN ('rascunho','aberto','fechado')),
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
  criado_por    TEXT NOT NULL,
  fechado_em    TIMESTAMPTZ,
  fechado_por   TEXT
);

CREATE TABLE IF NOT EXISTS des_gestor (
  id            SERIAL PRIMARY KEY,
  email         TEXT NOT NULL,
  escopo_tipo   TEXT NOT NULL CHECK (escopo_tipo IN ('area','secao')),
  escopo_valor  TEXT NOT NULL,
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
  criado_por    TEXT NOT NULL,
  UNIQUE (email, escopo_tipo, escopo_valor)
);
CREATE INDEX IF NOT EXISTS des_gestor_email ON des_gestor (email);

CREATE TABLE IF NOT EXISTS des_avaliacao (
  id            SERIAL PRIMARY KEY,
  ciclo_id      INTEGER NOT NULL REFERENCES des_ciclo(id) ON DELETE CASCADE,
  -- A CHAVE É `codintfunc`, a interna da folha. `chapafunc` (matrícula) é o
  -- que a pessoa conhece e vai na foto, mas ela se reaproveita entre empresas
  -- do grupo e já mudou em recontratação.
  codintfunc    INTEGER NOT NULL,
  -- FOTO DO AVALIADO no momento da avaliação. O cargo muda, a área muda, a
  -- pessoa sai — e uma avaliação que só guarda a chave passa a mostrar o
  -- cargo de hoje ao lado da nota do ano passado. Mesma regra do
  -- `dre_excluido`.
  chapa         TEXT,
  nome          TEXT,
  cargo         TEXT,
  area          TEXT,
  secao         TEXT,
  -- 1 a 3, e é isso que faz a matriz ter nove caixas. Escala maior sem
  -- critério escrito vira média de opinião, não avaliação.
  desempenho    SMALLINT CHECK (desempenho BETWEEN 1 AND 3),
  potencial     SMALLINT CHECK (potencial BETWEEN 1 AND 3),
  -- JUSTIFICATIVA OBRIGATÓRIA na gravação (a regra vive no módulo, não aqui:
  -- o rascunho salvo pela metade tem de caber). Nota sem porquê não sustenta
  -- conversa de carreira nem decisão de promoção.
  justificativa TEXT,
  avaliador     TEXT NOT NULL,
  avaliado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
  atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ciclo_id, codintfunc)
);
CREATE INDEX IF NOT EXISTS des_avaliacao_ciclo ON des_avaliacao (ciclo_id);
CREATE INDEX IF NOT EXISTS des_avaliacao_avaliador ON des_avaliacao (avaliador);
