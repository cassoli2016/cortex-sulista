-- 0101 · O indicador do ritual que dizia "Consumo — km por litro" e mostrava
-- um CUSTO, com o semáforo invertido.
--
-- MEDIDO EM 18/09/2026, a pedido de quem opera ("valide o km/l: uma tela diz
-- 1,81 e a outra 2,74"). As duas não eram duas réguas do mesmo número:
--
--   * `get_analise_km.diesel_km` é R$ POR KM RODADO (custo do diesel ÷ km) —
--     e a tela de Análise de KM sempre mostrou assim, "× R$ 1,99/km";
--   * a tela de Combustível publica km/l de TODA a frota (2,74);
--   * o caminhão próprio faz 3,10 km/l — que é o número de gestão.
--
-- O ritual (`0067`) copiou a chave `diesel_km` e semeou o indicador com o nome
-- "Consumo — km por litro", unidade `km/l` e direção MAIOR_MELHOR. Três erros
-- numa linha, e o terceiro é o que custa: o diesel encarecendo por km pintava
-- VERDE no painel da reunião. A linha era lida toda semana, e ninguém tem como
-- desconfiar de um indicador verde.
--
-- Esta migration:
--   1. corrige o indicador existente (nome, unidade, direção) — SÓ se ele
--      ainda estiver com o rótulo errado, para não desfazer ajuste que alguém
--      já tenha feito à mão pela tela de cadastro;
--   2. acrescenta o consumo de verdade (`consumo_proprio`, km/l do caminhão
--      próprio) como indicador PRÓPRIO da Operação.
--
-- O HISTÓRICO NÃO SE REESCREVE: `ges_apontamentos` guarda o que foi apontado
-- em cada semana, e aqueles números continuam sendo R$/km — que é o que eles
-- sempre foram. O que muda é o nome pelo qual a casa os chama daqui para
-- frente. Como não houve ciclo apontado até hoje (zero linhas em
-- `ges_apontamentos` em 18/09/2026), não há série a explicar.

UPDATE ges_indicadores
   SET nome = 'Diesel por km rodado',
       unidade = 'R$/km',
       direcao = 'menor_melhor',
       casas = 2
 WHERE fonte = 'diesel_km'
   AND direcao = 'maior_melhor'
   AND unidade = 'km/l';

-- O consumo entra ao lado, na mesma gerência, logo depois do custo. `ordem`
-- sai do MAIOR que já existe na gerência para não empatar com nada — empate
-- de ordem vira sorteio na hora de pintar a tabela.
INSERT INTO ges_indicadores(gerencia_id, nome, unidade, direcao, fonte, casas,
                            ordem, criado_em)
SELECT g.id, 'Consumo do caminhão próprio', 'km/l', 'maior_melhor',
       'consumo_proprio', 2,
       coalesce((SELECT max(i2.ordem) FROM ges_indicadores i2
                  WHERE i2.gerencia_id = g.id), 0) + 1,
       ''
  FROM ges_gerencias g
 WHERE g.chave = 'operacao'
   AND NOT EXISTS (SELECT 1 FROM ges_indicadores i
                    WHERE i.gerencia_id = g.id AND i.fonte = 'consumo_proprio');

-- A CONFERÊNCIA MORA AQUI DENTRO, na mesma transação: migration que arruma
-- cadastro e não confere o resultado se lê como feita.
DO $$
DECLARE erradas integer;
BEGIN
  SELECT count(*) INTO erradas FROM ges_indicadores
   WHERE fonte = 'diesel_km' AND (unidade <> 'R$/km' OR direcao <> 'menor_melhor');
  IF erradas > 0 THEN
    RAISE EXCEPTION 'sobrou % indicador de diesel com unidade/direção de consumo', erradas;
  END IF;
END $$;
