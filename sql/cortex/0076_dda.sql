-- 0076 · DDA — os boletos que já estão NO BANCO e ainda não estão no ERP.
--
-- POR QUE ISTO EXISTE
-- ===================
--
-- A projeção de caixa de médio prazo esbarra num fato medido: o ERP só conhece
-- ~45% das contas a pagar de um mês no dia 1º dele, e ~70% no dia 10 (curva dos
-- 12 meses fechados até ago/2026). O resto entra ao longo do mês. Projetar em
-- cima do lançado é, por construção, projetar um mês barato demais.
--
-- O DDA (Débito Direto Autorizado) é a outra metade da mesma conta, e vem de
-- fora do ERP: é a lista dos boletos que fornecedores REGISTRARAM contra o CNPJ
-- da empresa. Um boleto registrado é uma obrigação com nome, CNPJ, valor e
-- vencimento — não uma estimativa. Importado em 09/09/2026 (extrato de 03/09),
-- 1.061 boletos somando R$ 6,40 mi, confrontados com `contaapagar`:
--
--     casados                 540    R$ 4,03 mi   63%
--     valor diferente         172    R$  216 mil   3%
--     vencimento prorrogado     9    R$   54 mil   1%
--     SEM TÍTULO NO ERP       340    R$ 2,10 mi   33%
--
-- e os R$ 2,10 mi que faltam se concentram onde doem: R$ 1,14 mi vencendo em
-- set/2026 e R$ 887 mil em out/2026 — mês em que o ERP inteiro só tinha
-- R$ 3,18 mi lançados contra uma média de R$ 12,1 mi nos meses fechados.
--
-- Então o DDA não substitui a estimativa estatística: ele dá PISO a ela, e dá
-- NOME ao que falta. "Faltam lançar R$ 1,8 mi" é um número; "faltam lançar
-- R$ 1,8 mi, dos quais R$ 1,2 mi já são boleto registrado destes 40
-- fornecedores" é uma lista de trabalho.
--
-- A IDENTIDADE É O CÓDIGO DE BARRAS
-- ---------------------------------
-- 44 dígitos, presente e ÚNICO nas 1.061 linhas do primeiro extrato real. É a
-- chave que o próprio sistema bancário usa, e é estável entre extrações — o que
-- permite reconhecer o mesmo boleto de uma semana para a outra sem depender de
-- nome de fornecedor (que vem com grafia variada: o mesmo pagador aparece como
-- "TRANSPORTADORA SULISTA S/A", "S A", "SA" e "S.A." no MESMO arquivo).
--
-- O EXTRATO É UM RETRATO, E RETRATO NÃO SE ACUMULA
-- ------------------------------------------------
-- Boleto pago SOME da extração seguinte. Se cada carga só INSERISSE, a base
-- viraria a soma histórica de tudo que já foi devido — e a projeção passaria a
-- somar boleto pago em julho contra o caixa de outubro.
--
-- Por isso `visto_em`/`sumiu_em`, com o fechamento ancorado no INÍCIO da carga
-- (mesma regra da recolha da SEFAZ): tudo que estava vivo e não veio na carga
-- nova é marcado como sumido NAQUELE instante. A posição atual é
-- `sumiu_em IS NULL`; o histórico continua respondendo "quando este boleto
-- deixou de existir", que é o que separa "foi pago" de "nunca vi".
--
-- CARGA PARCIAL NÃO FECHA NADA
-- ----------------------------
-- O fechamento só roda quando a carga é do escopo inteiro. Uma extração de uma
-- conta só, ou filtrada por período, marcaria como sumido o que ela nunca teve
-- a chance de trazer — e a tela diria "R$ 4 mi de boletos foram pagos" no dia
-- em que alguém exportou meia planilha.
CREATE TABLE IF NOT EXISTS dda_carga (
  id            serial       PRIMARY KEY,
  -- SHA-256 do arquivo. Reimportar o MESMO arquivo não cria carga nova (clicar
  -- duas vezes é acidente comum) e não refaz o fechamento.
  impressao     char(64)     NOT NULL UNIQUE,
  arquivo       text         NOT NULL,
  -- O carimbo que o PRÓPRIO extrato declara ("Data/Hora: 03/09/2026 às 17:.."),
  -- não a hora do upload: é ele que diz a idade do dado. Uma planilha de duas
  -- semanas atrás importada hoje é dado de duas semanas atrás, e a tela precisa
  -- poder dizer isso.
  extraido_em   timestamptz,
  importado_em  timestamptz  NOT NULL DEFAULT now(),
  usuario       text         NOT NULL DEFAULT '',
  -- CNPJ do pagador e a conta declarados no cabeçalho do extrato. Guardados
  -- porque o extrato é POR CONTA no portal do banco: saber qual conta veio é o
  -- que permite descobrir que uma filial nunca foi importada.
  pagador_cnpj  varchar(14),
  conta         text,
  boletos       integer      NOT NULL DEFAULT 0,
  valor         numeric(15,2) NOT NULL DEFAULT 0,
  -- Carga do escopo inteiro (fecha o que sumiu) × carga parcial (não fecha).
  completa      boolean      NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS ix_dda_carga_quando ON dda_carga (importado_em DESC);

CREATE TABLE IF NOT EXISTS dda_boleto (
  barras        varchar(44)  PRIMARY KEY,
  beneficiario  text         NOT NULL DEFAULT '',
  -- Só dígitos, como o ERP guarda em `cadastro.codigo` — é por ele que o
  -- casamento com `contaapagar` acontece. Casar por NOME não funciona: o mesmo
  -- fornecedor aparece com grafias diferentes no mesmo arquivo.
  beneficiario_doc varchar(14),
  vencimento    date         NOT NULL,
  -- `valor` é o NOMINAL (coluna "Até Venc." do extrato) — o comparável com
  -- `contaapagar.valortitulo`. `a_pagar` é o que sairia hoje, com juros/multa
  -- de quem já venceu: os dois divergem em 170 das 1.061 linhas do primeiro
  -- extrato, e usar um no lugar do outro erra o casamento e o caixa.
  valor         numeric(15,2) NOT NULL,
  a_pagar       numeric(15,2),
  documento     text,
  tipo          text,
  banco         varchar(3),
  observacao    text,
  primeiro_em   timestamptz  NOT NULL DEFAULT now(),
  visto_em      timestamptz  NOT NULL DEFAULT now(),
  -- NULL = vivo na última carga completa. Preenchido = não veio mais.
  sumiu_em      timestamptz,
  carga_id      integer      REFERENCES dda_carga(id)
);

CREATE INDEX IF NOT EXISTS ix_dda_boleto_venc  ON dda_boleto (vencimento)
  WHERE sumiu_em IS NULL;
CREATE INDEX IF NOT EXISTS ix_dda_boleto_doc   ON dda_boleto (beneficiario_doc, vencimento)
  WHERE sumiu_em IS NULL;
