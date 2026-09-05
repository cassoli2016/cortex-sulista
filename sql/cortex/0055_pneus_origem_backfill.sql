-- CONSERTO DO BACKFILL DA 0054, e o motivo de ser uma migration NOVA e nao uma
-- edicao da anterior: a 0054 JA FOI APLICADA. Editar migration aplicada nao
-- conserta banco nenhum — o `migrar_schema.py` controla por numero e nunca a
-- roda de novo. A licao ja esta em docs/LICOES.md; esta e a segunda vez que ela
-- cobra o preco.
--
-- A 0054 marcou como `prolog` quem tinha `prolog_id` preenchido. Duas tabelas
-- escaparam por motivos diferentes, e as duas SAO da Prolog:
--
-- 1. `pne_vida` TEM a coluna `prolog_id`, mas a semeadura nunca a preencheu: a
--    vida e deduzida do proprio pneu, nao e uma entidade que o fornecedor
--    identifique. As 13.632 linhas ficaram `cortex` sem nunca ter sido
--    escritas por ninguem daqui.
-- 2. `pne_veiculo` tem 5 placas sem `prolog_id` — elas entraram pela SEMEADURA
--    (que cria a linha ao ver a placa num pneu) e nao pelo endpoint de
--    veiculos, entao nunca receberam o id. Sao Prolog do mesmo jeito.
--
-- A PROVA DE QUE E SEGURO marcar tudo como `prolog`: nenhuma linha de
-- `pne_evento` ou `pne_inspecao` tem origem `cortex`, ou seja, a camada de
-- escrita ainda nao foi usada por ninguem. Nao ha trabalho digitado para
-- perder. Depois que houver, um backfill assim seria destrutivo — por isso ele
-- vai AGORA e com a condicao explicita abaixo.
UPDATE pne_vida SET origem = 'prolog'
 WHERE origem = 'cortex'
   AND NOT EXISTS (SELECT 1 FROM pne_evento WHERE origem = 'cortex');

UPDATE pne_veiculo SET origem = 'prolog'
 WHERE origem = 'cortex'
   AND NOT EXISTS (SELECT 1 FROM pne_evento WHERE origem = 'cortex');
