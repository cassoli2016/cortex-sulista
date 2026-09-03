-- 0044 · Lançamentos tirados do resultado gerencial, à mão.
--
-- POR QUE ISTO EXISTE: a DRE gerencial não é a contábil. Há lançamento que o
-- razão precisa ter e o resultado gerencial não deve carregar — reclassificação
-- que entra e sai, provisão revertida, rateio que já foi contado noutra linha.
-- Até aqui isso se resolvia pedindo à Contabilidade que mexesse no razão, o que
-- é caro e às vezes impossível.
--
-- E POR QUE ELE É PERIGOSO: é um jeito de mudar o resultado publicado. Por isso
-- a tabela guarda o que guarda:
--
--   `motivo` é NOT NULL e o módulo recusa vazio. Exclusão sem motivo escrito é
--   irrastreável em seis meses — e o que se perde primeiro é sempre a razão.
--
--   `quem` e `quando` ficam AQUI, além do audit_log. A trilha responde "o que
--   aconteceu no sistema"; esta linha responde "por que este número é assim",
--   que é a pergunta de quem lê a DRE, não a de quem audita.
--
--   A FOTO do lançamento (valor, conta, histórico) fica gravada. O ERP é
--   réplica de terceiro e o lançamento pode mudar ou sumir depois; sem a foto,
--   a lista de exclusões viraria uma lista de chaves órfãs que ninguém sabe
--   mais o que eram. A DRE usa a chave para filtrar; a TELA usa a foto para
--   mostrar. São usos diferentes e é de propósito.
--
-- A chave é a do ERP, e são CINCO colunas: medido em 1.230.480 lançamentos de
-- 12 meses, `sequencia` sozinha colide (1.210.855 distintas) e
-- `(sequencia, data)` também (1.216.159). Só a chave completa não colide.

CREATE TABLE IF NOT EXISTS dre_excluido (
  grupo          integer   NOT NULL,
  empresa        integer   NOT NULL,
  reduzido       integer   NOT NULL,
  sequencia      bigint    NOT NULL,
  dtlancamento   date      NOT NULL,
  -- a foto, para a tela não depender do ERP responder
  valor_debito   numeric(18, 2),
  valor_credito  numeric(18, 2),
  conta          text,
  agrupador      text,
  historico      text,
  -- o porquê, que é o que não se recupera depois
  motivo         text      NOT NULL,
  quem           text      NOT NULL,
  quando         timestamp NOT NULL DEFAULT now(),
  PRIMARY KEY (grupo, empresa, reduzido, sequencia, dtlancamento)
);

COMMENT ON TABLE dre_excluido IS
  'Lançamentos que a DRE Gerencial ignora, marcados à mão. Não afeta '
  'Contabilidade, Orçamento nem Fechamento — cada tela responde uma pergunta '
  'diferente, e silenciar todas esconderia o lançamento de quem precisa achá-lo.';

CREATE INDEX IF NOT EXISTS ix_dre_excluido_data
  ON dre_excluido (dtlancamento);
