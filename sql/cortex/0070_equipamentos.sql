-- 0070 · CADASTRO DE EQUIPAMENTOS — o registro de frota que é DO CÓRTEX.
--
-- POR QUE ISTO EXISTE, SE O ERP JÁ TEM UMA TABELA `veiculo`
-- =========================================================
--
-- Porque o ERP vai sair. A decisão de quem opera (07/09/2026) é que o módulo
-- TMS deixe de depender do Avacorp, e um cadastro que MORA no ERP não
-- sobrevive a essa saída: no dia em que o AVA for desligado, tudo que o
-- CÓRTEX sabe sobre um equipamento vai junto.
--
-- Então o cadastro nasce aqui, do lado de cá, e o ERP entra como UMA FONTE —
-- a principal de hoje, não a dona. É diferença de PROPRIEDADE, não de origem
-- do dado: hoje 100% da marca vem do AVA e amanhã pode vir da APIBrasil ou da
-- mão de quem cadastra, sem que nada mais no módulo mude.
--
-- A CHAVE É A PLACA
-- -----------------
-- Pelo mesmo motivo de `api/frota_identidade.py`: é única, está sempre
-- preenchida e é o que TODO fornecedor externo devolve — Gobrax, Detran,
-- APIBrasil, ANTT. `numerofrota` tem cobertura útil de 46% e some para
-- terceiro (4,2%); chavear por ele faria metade da frota desaparecer.
--
-- "EQUIPAMENTO", E NÃO "VEÍCULO"
-- ------------------------------
-- Porque boa parte da frota não é veículo no sentido de rodar sozinha:
-- carretas, dollys e implementos não têm motor, não têm motorista e não têm
-- consumo, mas TÊM placa, chassi, licenciamento e restrição — e é isso que
-- este cadastro guarda. Chamar de veículo faria o implemento parecer exceção
-- de um cadastro que na verdade foi feito para os dois.

-- ================================================================ o cadastro
--
-- A TABELA CONSOLIDADA. Uma linha por placa, com o valor que VENCEU em cada
-- campo. Ela é DERIVADA — quem manda é `eqp_fonte` + `eqp_edicao`, e
-- `api/equipamentos/consolidacao.py` reconstrói esta tabela a partir delas.
--
-- Existir consolidada em vez de ser uma VIEW é decisão de leitura: a tela de
-- ~2.000 equipamentos com filtro e ordenação faria a precedência rodar a cada
-- clique, e a precedência é a parte cara (quatro fontes por placa).
CREATE TABLE IF NOT EXISTS eqp_equipamento (
  placa               varchar(10)  PRIMARY KEY,

  -- ---- identidade documental (o que o Detran conhece) ----
  renavam             varchar(11),
  chassi              varchar(25),
  numero_motor        text,
  placa_anterior      varchar(10),   -- a pré-Mercosul; é ela que explica os
                                     -- números de frota "repetidos" do ERP

  -- ---- o que o equipamento É ----
  -- `categoria` é NOSSA: tracao | implemento | leve | outro. Não vem pronta de
  -- fonte nenhuma — é derivada do tipo do ERP/Detran, e é ela que separa as
  -- duas populações que NUNCA devem ser somadas numa média (idade da tração
  -- 6,9 anos contra implemento 12,9).
  categoria           text,
  tipo                text,          -- o rótulo da fonte, cru
  especie             text,
  carroceria          text,

  -- ---- modelo ----
  marca               text,
  modelo              text,
  versao              text,
  ano_fabricacao      int,
  ano_modelo          int,
  cor                 text,
  combustivel         text,
  potencia_cv         int,
  cilindrada          int,

  -- ---- capacidade, em unidade de ORIGEM: quilo e litro, nunca tonelada ----
  -- Razão e percentual saem da unidade de origem; arredondar para tonelada
  -- antes de dividir move o número de lado da fronteira.
  tara_kg             int,
  capacidade_carga_kg int,
  capacidade_m3       numeric(10,2),
  capacidade_tanque_l int,
  pbt_kg              int,           -- peso bruto total
  cmt_kg              int,           -- capacidade máxima de tração
  eixos               int,

  -- ---- emplacamento ----
  uf                  varchar(2),
  municipio           text,

  -- ---- propriedade ----
  -- `vinculo` é proprio | agregado | terceiro. GRAVADO, e não derivado, porque
  -- no dia em que o ERP sair não haverá `tipofrota` de onde derivar.
  vinculo             text,
  proprietario_doc    varchar(14),
  proprietario_nome   text,

  -- ---- situação documental (só a APIBrasil/Detran sabe) ----
  situacao            text,          -- o que o Detran responde sobre a placa
  crlv_exercicio      int,
  crlv_vencimento     date,
  licenciado          boolean,
  -- TER restrição é uma coisa; QUAIS são é outra. O booleano é o que a tela
  -- pinta; a lista é o que ela mostra ao abrir. Booleano NULL = não
  -- consultado, e é diferente de false — "não sei" nunca é pintado de verde.
  tem_restricao       boolean,
  restricoes          jsonb,

  -- ---- valor ----
  fipe_codigo         text,
  fipe_valor          numeric(14,2),
  fipe_referencia     text,

  -- ---- estado operacional (hoje do ERP) ----
  ativo               boolean      NOT NULL DEFAULT true,
  filial              text,
  numero_frota        text,

  -- DE ONDE VEIO CADA CAMPO: {"marca": "erp", "fipe_valor": "apibrasil.fipe"}
  --
  -- Não é enfeite de auditoria: é o instrumento que torna a saída do ERP
  -- MENSURÁVEL. Com ele, "o que quebra se o AVA sair amanhã?" é uma CONSULTA
  -- — conta os campos cuja origem ainda é erp — em vez de uma leitura de
  -- código. Sem ele, a independência do Avacorp seria uma afirmação; e
  -- afirmação sobrevive ao instrumento, que foi o que o 1.0.0 quase carregou
  -- junto.
  origem              jsonb        NOT NULL DEFAULT '{}'::jsonb,

  criado_em           timestamptz  NOT NULL DEFAULT now(),
  atualizado_em       timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS eqp_equipamento_vinculo   ON eqp_equipamento (vinculo);
CREATE INDEX IF NOT EXISTS eqp_equipamento_categoria ON eqp_equipamento (categoria);
CREATE INDEX IF NOT EXISTS eqp_equipamento_ativo     ON eqp_equipamento (ativo);
CREATE INDEX IF NOT EXISTS eqp_equipamento_renavam   ON eqp_equipamento (renavam);

-- ================================================================== as fontes
--
-- O QUE CADA FONTE DISSE, SEPARADO, COM O CORPO CRU JUNTO.
--
-- Duas razões para guardar o payload inteiro, e não só os campos que hoje
-- interessam:
--
-- 1. A casa já pagou por não fazer isso: a Gobrax devolvia 14 indicadores e o
--    CÓRTEX lia 3, e os outros 11 só apareceram ao reler a resposta inteira
--    muito depois. A APIBrasil devolve "marca, modelo, versão, chassi e muito
--    mais", e a documentação pública não lista o "muito mais".
-- 2. Consulta de placa CUSTA. Reler um payload guardado é de graça;
--    reconsultar ~2.000 placas porque um campo novo virou útil é a fatura de
--    novo.
--
-- A chave natural é (placa, fonte), e é ela que faz a coleta ser idempotente:
-- reconsultar a mesma placa ATUALIZA, nunca duplica.
CREATE TABLE IF NOT EXISTS eqp_fonte (
  placa      varchar(10)  NOT NULL,
  -- erp | apibrasil.dados | apibrasil.crlv | apibrasil.fipe
  -- | apibrasil.seguranca | smartec
  fonte      text         NOT NULL,
  -- o que a fonte disse, JÁ traduzido para os nomes de `eqp_equipamento`
  campos     jsonb        NOT NULL DEFAULT '{}'::jsonb,
  -- o corpo CRU, inteiro, como chegou
  payload    jsonb,
  visto_em   timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (placa, fonte)
);

CREATE INDEX IF NOT EXISTS eqp_fonte_visto ON eqp_fonte (fonte, visto_em DESC);

-- ================================================================== a edição
--
-- O QUE UMA PESSOA CORRIGIU À MÃO — e que vence toda fonte automática.
--
-- É esta tabela que faz o cadastro ser DO CÓRTEX de verdade. Sem ela o módulo
-- seria um espelho: toda coleta seguinte desfaria a correção, e quem corrigiu
-- aprenderia em uma semana que corrigir não adianta.
--
-- Tabela separada, e não uma linha fonte='manual' em `eqp_fonte`, por causa do
-- AUTOR: correção de cadastro é ato de pessoa, com responsável e motivo, e
-- misturá-la com coleta automática apagaria justamente isso.
CREATE TABLE IF NOT EXISTS eqp_edicao (
  placa      varchar(10)  NOT NULL,
  campo      text         NOT NULL,
  -- text, e não jsonb: o valor é DIGITADO, e a conversão para o tipo da coluna
  -- acontece na consolidação, num lugar só, onde o erro tem mensagem.
  valor      text,
  motivo     text,
  autor      text         NOT NULL,
  criado_em  timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (placa, campo)
);

-- ================================================================= a consulta
--
-- O LIVRO-CAIXA DAS CHAMADAS À APIBRASIL.
--
-- Existe por três perguntas que não têm outra resposta:
--   · quanto da cota do dia já foi gasto (o plano tem teto diário);
--   · por que ESTA placa está vazia — nunca consultada, ou consultada e o
--     Detran não conhece? São coisas diferentes, e a tela precisa dizer qual;
--   · a coleta está viva? A Saúde do Servidor pergunta a esta tabela.
--
-- Sem ela, placa sem dado seria indistinguível de placa sem consulta, e a
-- ausência não teria sintoma nenhum — que é a classe de defeito mais cara
-- desta casa.
CREATE TABLE IF NOT EXISTS eqp_consulta (
  id         bigserial    PRIMARY KEY,
  placa      varchar(10)  NOT NULL,
  produto    text         NOT NULL,   -- dados | crlv | fipe | seguranca
  quando     timestamptz  NOT NULL DEFAULT now(),
  ok         boolean      NOT NULL,
  http       int,
  -- SEMPRE o tipo da exceção ou a mensagem do fornecedor JÁ sanitizada. Nunca
  -- str(exc) cru: o token da APIBrasil vai em cabeçalho, e biblioteca de HTTP
  -- ecoa cabeçalho em erro de conexão — cabeçalho ecoado em log é credencial
  -- publicada.
  erro       text,
  ms         int
);

CREATE INDEX IF NOT EXISTS eqp_consulta_quando ON eqp_consulta (quando DESC);
CREATE INDEX IF NOT EXISTS eqp_consulta_placa  ON eqp_consulta (placa, produto, quando DESC);
