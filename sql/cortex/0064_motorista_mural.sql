-- 0064 · O mural: um comunicado do RH para TODOS os motoristas de uma vez.
--
-- ==========================================================================
-- POR QUE ISTO NÃO É UMA CONVERSA COM 300 PESSOAS
-- ==========================================================================
-- O canal do RH (0063) recusa comunicado em massa por escrito, e a razão está
-- em `api/motorista/conversas.abrir_rh`: 300 conversas abertas de uma vez
-- entopem a fila que o resto do desenho existe para manter ATENDÍVEL. A caixa
-- ordena pelo mais parado e mede "paradas há 3+ dias"; despejar trezentas
-- linhas ali destrói os dois números no mesmo instante.
--
-- Aquele comentário também disse qual era a saída, e é esta:
--
--   > "Se um dia houver comunicado em massa, ele é OUTRO OBJETO — um mural,
--   >  sem fila e sem resposta —, e não este."
--
-- Quem opera pediu o comunicado em massa em 07/09/2026. O que muda não é a
-- decisão de manter a fila limpa; é que passa a existir um segundo objeto, com
-- forma própria:
--
-- | | conversa (0063) | mural (aqui) |
-- |---|---|---|
-- | quantos | uma pessoa | todo o público, de uma vez |
-- | tem fila? | sim — dono, estado, "parada há N dias" | **não** |
-- | tem resposta? | sim, os dois lados escrevem | **não** — quem quiser falar abre um pedido normal, e aí é fila |
-- | o que se cobra | atendimento | **ciência**: "45 de 80 confirmaram" |
--
-- Na tela do RH o mural é UM cartão com uma fração, não trezentas linhas. É
-- essa diferença que faz ele caber ao lado da caixa sem afogá-la.
--
-- ==========================================================================
-- O AVISO EM MASSA POR WHATSAPP CONTINUA FORA
-- ==========================================================================
-- Decisão de quem opera, tomada em 07/09/2026 com o número na mesa: o teto do
-- WhatsApp da casa é de 60 destinatários DISTINTOS por dia, e ele protege o
-- número que fala com clientes e fornecedores. Trezentos motoristas seriam
-- cinco dias de ondas gastando a reputação desse número — e no fim do quinto
-- dia o comunicado já não é notícia.
--
-- Quem avisa é a marca no app (a bolinha da aba do RH). O mural entra nela
-- pelo mesmo caminho das conversas não lidas.

-- ------------------------------------------------------------- o comunicado
CREATE TABLE IF NOT EXISTS mot_comunicados(
    id            bigserial PRIMARY KEY,
    titulo        text NOT NULL,
    texto         text NOT NULL,
    -- Quem publicou. `usuarios(id)` porque deste lado é gente do painel;
    -- `ON DELETE SET NULL` porque desligar quem publicou não pode apagar o
    -- comunicado — a prova de que a empresa comunicou é o que vale depois.
    autor_id      integer REFERENCES usuarios(id) ON DELETE SET NULL,
    autor_nome    text NOT NULL DEFAULT '',
    criado_em     timestamptz NOT NULL DEFAULT now(),
    -- ENCERRAR PARA DE COBRAR, mas não apaga: o comunicado sai da tela do
    -- motorista e continua no histórico com a fração de ciência congelada.
    -- Sem isto, um comunicado de março segue pedindo "li e entendi" para
    -- sempre, e a pessoa aprende a ignorar o pedido — inclusive no de hoje.
    encerrado_em  timestamptz,
    encerrado_por text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS mot_comunicados_vivos
    ON mot_comunicados(criado_em DESC) WHERE encerrado_em IS NULL;

COMMENT ON TABLE mot_comunicados IS
    'Mural: um aviso da empresa para todo o público de uma vez. NÃO é conversa —
     não tem dono, não tem estado e não se responde. O que se cobra aqui é
     CIÊNCIA, e quem quiser falar sobre ele abre um pedido normal (mot_conversas),
     que aí sim entra na fila com dono.';

-- --------------------------------------------------------------- a ciência
--
-- O PÚBLICO É FOTOGRAFADO NA PUBLICAÇÃO, e esta é a decisão que mais importa
-- neste arquivo.
--
-- A alternativa — calcular "todos os motoristas ativos" na LEITURA — parece
-- mais simples e mente de duas formas ao mesmo tempo:
--
--   1. o motorista contratado em novembro passaria a "dever ciência" de um
--      comunicado de setembro, sobre uma convenção que não o alcança;
--   2. "45 de 80 confirmaram" mudaria de denominador sozinho a cada
--      admissão e a cada desligamento — a fração andaria para trás sem
--      ninguém ter feito nada, que é o jeito mais rápido de um número perder
--      a confiança de quem o lê.
--
-- Uma linha por destinatário no ato da publicação custa ~300 linhas por
-- comunicado (é uma LISTA DE PRESENÇA, não uma fila) e faz o denominador ser
-- um FATO daquele dia. É a mesma regra do "denominador só contém quem pode
-- cumprir a regra" que tirou terceiros e carretas da cobertura de rastreador.
CREATE TABLE IF NOT EXISTS mot_comunicado_ciencia(
    comunicado_id    bigint NOT NULL REFERENCES mot_comunicados(id)
                            ON DELETE CASCADE,
    motorista_codigo text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                            ON DELETE CASCADE,
    -- ABRIU e CONFIRMOU são coisas diferentes, e as duas interessam: "ele viu
    -- e não confirmou" é uma conversa; "ele nunca abriu" é outra. Um campo só
    -- juntaria as duas num "não leu" que não distingue quem ignorou de quem
    -- nem soube.
    visto_em         timestamptz,
    ciencia_em       timestamptz,
    PRIMARY KEY (comunicado_id, motorista_codigo)
);

CREATE INDEX IF NOT EXISTS mot_ciencia_do_motorista
    ON mot_comunicado_ciencia(motorista_codigo)
    WHERE ciencia_em IS NULL;

COMMENT ON COLUMN mot_comunicado_ciencia.visto_em IS
    'Quando ele ABRIU o comunicado. Diferente de `ciencia_em`, que é quando ele
     apertou "li e entendi": "viu e não confirmou" e "nunca abriu" são duas
     conversas diferentes com a pessoa, e um campo só as fundiria.';
