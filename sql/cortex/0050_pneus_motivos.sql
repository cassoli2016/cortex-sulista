-- Os MOTIVOS da Prolog: por que um pneu foi descartado, e por que ele saiu de
-- onde estava.
--
-- POR QUE ELES PRECISAM MORAR AQUI. `pne_evento.motivo` esta 100% nulo, e a
-- regra da casa e que codigo sem tabela de dominio nao vira rotulo inventado.
-- Enquanto a tabela so existia na Prolog, a unica saida honesta era mostrar o
-- codigo cru. Com ela replicada, o rotulo passa a ter de onde vir — e continua
-- tendo no dia em que a integracao acabar, que e o ponto.
--
-- DUAS ESPECIES NA MESMA TABELA, separadas pela coluna: elas vem de dois
-- endpoints diferentes e respondem perguntas diferentes ("por que foi para a
-- sucata" x "por que saiu daquele veiculo"). Junta-las sem a coluna faria um
-- motivo de descarte aparecer como opcao de rodizio.
CREATE TABLE IF NOT EXISTS pne_motivo (
  id             SERIAL PRIMARY KEY,
  especie        TEXT NOT NULL CHECK (especie IN ('descarte','movimentacao')),
  -- O id do fornecedor e a chave natural. Quando a Prolog sair, ele vira um
  -- identificador historico e o `id` daqui assume — por isso os dois existem.
  prolog_id      TEXT NOT NULL,
  rotulo         TEXT NOT NULL,
  ativo          BOOLEAN NOT NULL DEFAULT TRUE,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (especie, prolog_id)
);
CREATE INDEX IF NOT EXISTS pne_motivo_especie ON pne_motivo (especie, ativo);
