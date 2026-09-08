-- 0071 · A Smartec no lugar da consulta de placa avulsa.
--
-- O QUE ACONTECEU (08/09/2026)
-- ============================
-- A 0070 nasceu com uma integração paga de consulta de placa como fonte do
-- Detran. Antes de gastar a primeira consulta, mediu-se o catálogo da Smartec
-- — contratada, configurada e coletando todo dia nesta casa — e ele devolve o
-- mesmo: chassi, cor, espécie, anos e, principalmente, RESTRIÇÃO (roubo,
-- furto, Renajud, recall). A consulta avulsa custaria R$ 2,50 por veículo,
-- ~R$ 3.600 pela frota, por um dado já pago.
--
-- O que faltava não era fornecedor: `api/smartec/coleta.coletar_restricoes()`
-- estava escrita e nunca era chamada, porque consulta um renavam por vez e
-- não entrou em `coletar_tudo()`, que só faz o que devolve a frota inteira
-- numa chamada. `smt_restricoes` tinha ZERO linhas.
--
-- A LIÇÃO: antes de contratar fonte para um dado, procurar o dado no que a
-- casa JÁ assina. É a mesma do pedágio (a tarifa estava no ERP) e a mesma da
-- própria Smartec (já integrada ao ERP desde 2023, usando 1 de 12 recursos).

-- ------------------------------------------------- dois campos que ela traz
--
-- `licenciamento_mes` é o MÊS em que o veículo licencia, e é o único campo
-- que `smt_licenciamento` de fato preenche hoje — `valor_taxa`, `guia` e
-- `guia_vencimento` vieram vazios nas 303 linhas, porque dependem da coleta
-- por renavam que também não era chamada.
--
-- Ele NÃO é o vencimento do CRLV, e por isso ganha coluna própria em vez de
-- ser mapeado para `crlv_vencimento`: usar um pelo outro inventaria uma data,
-- e data errada num vencimento é pior que data nenhuma.
--
-- `cronotacografo_vencimento` vem de `smt_licencas`, é data de verdade e não
-- existe em lugar nenhum do ERP.
ALTER TABLE eqp_equipamento
  ADD COLUMN IF NOT EXISTS licenciamento_mes         int,
  ADD COLUMN IF NOT EXISTS cronotacografo_vencimento date,
  -- FINANCIADO NAO E O MESMO QUE ROUBADO, e por isso sao duas colunas.
  --
  -- MEDIDO em 19 veiculos da frota (08/09/2026): 10 tem restricao, e TODAS
  -- as 10 sao alienacao fiduciaria -- veiculo financiado, que numa
  -- transportadora e o estado NORMAL de boa parte da frota. Se ela entrasse
  -- no mesmo booleano de roubo, furto e Renajud, metade do painel ficaria
  -- vermelha o tempo todo, e vermelho permanente ensina a ignorar o vermelho.
  --
  -- `tem_restricao` fica sendo so o IMPEDITIVO (roubo, furto, Renajud,
  -- recall) -- o que impede o veiculo de rodar ou exige acao hoje.
  -- `alienacao_fiduciaria` guarda o banco credor, que e informacao util
  -- (vender o ativo exige quitar) e nao e alarme.
  ADD COLUMN IF NOT EXISTS alienacao_fiduciaria      text;

-- ------------------------------------------- o que a saída da APIBrasil leva
--
-- COLUNA SEMPRE VAZIA SE PREENCHE OU SE REMOVE. Estas três só existiam para
-- guardar o retorno da consulta paga; nenhuma fonte atual as preenche, e
-- deixá-las seria o pior dos dois mundos: a tela mostraria campo eternamente
-- em branco e o próximo a ler o schema acharia que a informação existe em
-- algum lugar.
--
-- `fipe_valor` FICA: o ERP a preenche em 16% do cadastro. É a única lacuna
-- que ainda valeria consulta paga (R$ 0,10 por placa), e por isso continua
-- declarada no catálogo de campos.
ALTER TABLE eqp_equipamento
  DROP COLUMN IF EXISTS fipe_codigo,
  DROP COLUMN IF EXISTS fipe_referencia,
  -- Potência, cilindrada, PBT e CMT vinham do produto "dados do veículo";
  -- exercício do CRLV e o booleano de licenciado, do produto "CRLV". A
  -- Smartec não publica nenhum dos seis, e o ERP também não.
  DROP COLUMN IF EXISTS potencia_cv,
  DROP COLUMN IF EXISTS cilindrada,
  DROP COLUMN IF EXISTS pbt_kg,
  DROP COLUMN IF EXISTS cmt_kg,
  DROP COLUMN IF EXISTS crlv_exercicio,
  DROP COLUMN IF EXISTS licenciado;

-- O livro-caixa das consultas pagas. Ele existia para responder "quanto da
-- cota do dia já foi gasto" — pergunta que deixou de existir junto com a
-- cobrança por consulta. As duas fontes de hoje leem banco: o ERP por réplica
-- e a Smartec pelas tabelas `smt_*` que a coleta dela enche.
--
-- Quem responde "a coleta está viva?" agora é `smt_carga`, que é onde a
-- Smartec já registra cada passagem, com itens, chamadas e falha.
DROP TABLE IF EXISTS eqp_consulta;
