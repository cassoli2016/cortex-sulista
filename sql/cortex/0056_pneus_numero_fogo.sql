-- O NUMERO DE FOGO VIRA A CHAVE DO PNEU — decisao de quem opera, nao minha.
--
-- A pergunta era "quando chega um pneu novo, o que a borracharia le nele para
-- identifica-lo?", e a resposta foi: o numero de fogo. E ele ja estava aqui,
-- na coluna ERRADA.
--
-- O QUE ACONTECEU. O `serialNumber` da Prolog e documentado no spec deles como
-- "Used as tire VISUAL identifier" — que e exatamente o numero de fogo, a
-- marcacao gravada na carcaca. A coleta o gravava em `serie` e passava NULL
-- para `numero_fogo`, entao a coluna que a operacao usa para achar o pneu no
-- patio estava vazia nos 8.572 enquanto o valor dela estava do lado.
--
-- MEDIDO antes de fazer dele a chave: 8.572 valores, 8.572 DISTINTOS, nenhum
-- vazio. Chave natural de verdade, nao esperanca.
--
-- O DOT NAO E CHAVE, e a medicao diz por que: 495 valores distintos em 8.036
-- pneus, porque ele e SEMANA + ANO de fabricacao (`0125` = semana 1 de 2025).
-- Ele responde a IDADE da carcaca, que e motivo de sucata sozinha — mas nao
-- identifica pneu nenhum. E `0000` aparece 164 vezes: e preenchimento, nao DOT.
UPDATE pne_pneu SET numero_fogo = serie
 WHERE numero_fogo IS NULL AND serie IS NOT NULL AND trim(serie) <> '';

-- `0000` NAO E DOT, e virar nulo e melhor que virar "semana zero de 2000":
-- a idade da carcaca sairia errada e ninguem desconfiaria de uma data.
UPDATE pne_pneu SET dot = NULL WHERE trim(coalesce(dot,'')) IN ('', '0000');

-- UNICO, e e isto que impede o cadastro proprio de criar o mesmo pneu duas
-- vezes. Sem a restricao no BANCO, duas telas abertas ao mesmo tempo criam os
-- dois — a checagem na aplicacao nao ve a outra transacao.
--
-- PARCIAL, porque `numero_fogo` continua aceitando nulo enquanto houver
-- cadastro antigo sem ele: indice unico comum trataria todos os nulos como
-- distintos de qualquer forma, mas o parcial DIZ a intencao.
CREATE UNIQUE INDEX IF NOT EXISTS pne_pneu_fogo_unico
    ON pne_pneu (numero_fogo) WHERE numero_fogo IS NOT NULL;
