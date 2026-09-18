-- 0105 · Seis indicadores por gerência no Ritual Semanal.
--
-- (nasceu 0102 e foi renumerada: a frente de premiação levou 0102 a 0104 no
-- mesmo dia. Buraco na sequência é barato; descobrir no deploy não.)
--
-- Pedido de quem opera, 18/09/2026: "deixe essa parte bem encorpada para a
-- reunião de segunda, coloque uns 6 indicadores por área".
--
-- O seed do `0067` deu TRÊS por gerência, e o motivo escrito lá continua
-- valendo — três é o que cabe em dois minutos de fala. O que mudou é que a
-- casa passou a ter as duas colunas (no mês e no ano) e a sugestão de média:
-- a linha agora se lê sozinha, e a pauta pode carregar mais sem virar leitura
-- de planilha. Onze indicadores entram aqui, todos AUTOMÁTICOS — nenhum deles
-- pede digitação de ninguém.
--
-- A ESCOLHA NÃO FOI POR ABUNDÂNCIA, e sim por três critérios:
--
--   1. cada um responde uma pergunta que a reunião faz de qualquer jeito;
--   2. a leitura é barata (todas cronometradas contra o sistema vivo em
--      18/09/2026 — a mais cara, `embarques_mes`, custa 2,9 s, e o painel
--      passou a ler as fontes EM PARALELO no mesmo dia: 24 indicadores custam
--      menos que os 13 de antes em fila);
--   3. onde havia escolha, entrou o que ACUMULA no ano — indicador que só
--      existe no mês deixa a coluna nova vazia.
--
-- O que NÃO entrou, e por quê: `crm_ganhas` e `crm_contas_paradas` leem ZERO
-- enquanto o funil do CRM não for alimentado, e zero por falta de
-- preenchimento não é desempenho — entram quando o CRM estiver em uso.
-- `horas_extras_mes` ficou de fora em favor de `he_pct_folha`: o valor
-- absoluto cresce com o quadro, e o percentual é a régua.

INSERT INTO ges_indicadores(gerencia_id, nome, unidade, direcao, fonte, casas,
                            ordem, criado_em)
SELECT g.id, v.nome, v.unidade, v.direcao, v.fonte, v.casas,
       coalesce((SELECT max(i2.ordem) FROM ges_indicadores i2
                  WHERE i2.gerencia_id = g.id), 0) + v.ordem,
       ''
  FROM (VALUES
    -- Comercial: quanto se embarca, para quantos, e quão concentrado
    ('comercial',  'Embarques no mês (CT-e)',           'CT-e',     'maior_melhor', 'embarques_mes',       0, 1),
    ('comercial',  'Clientes com carga no mês',         'clientes', 'maior_melhor', 'clientes_ativos_mes', 0, 2),
    ('comercial',  'Concentração nos 10 maiores',       '%',        'menor_melhor', 'concentracao_top10',  1, 3),
    -- Operação: o que a frota rende e o que ela deixa de render
    ('operacao',   'Km por veículo no mês',             'km',       'maior_melhor', 'km_por_veiculo',      0, 1),
    ('operacao',   'Ociosidade da frota',               '%',        'menor_melhor', 'ociosidade_frota',    1, 2),
    -- Manutenção: o que o pneu custa e o que vai pedir dinheiro
    ('manutencao', 'CPK — custo de pneu por km',        'R$/km',    'menor_melhor', 'cpk_pneus',           3, 1),
    ('manutencao', 'Pneus abaixo do limite de sulco',   'pneus',    'menor_melhor', 'pneus_abaixo_limite', 0, 2),
    ('manutencao', 'Trocas de pneu previstas em 30 dias','pneus',   'menor_melhor', 'trocas_pneus_30d',    0, 3),
    -- RH: rotatividade, hora extra e diária
    ('rh',         'Turnover 12 meses',                 '%',        'menor_melhor', 'turnover',            1, 1),
    ('rh',         'Horas extras sobre a folha',        '%',        'menor_melhor', 'he_pct_folha',        1, 2),
    ('rh',         'Diária por dia trabalhado',         'R$',       'menor_melhor', 'diaria_por_dia',      2, 3)
  ) AS v(ger, nome, unidade, direcao, fonte, casas, ordem)
  JOIN ges_gerencias g ON g.chave = v.ger
 WHERE NOT EXISTS (SELECT 1 FROM ges_indicadores i
                    WHERE i.gerencia_id = g.id AND i.fonte = v.fonte);

-- A CONFERÊNCIA MORA AQUI DENTRO: seis por gerência é o que foi pedido, e
-- migration que cadastra e não confere se lê como feita. O piso é seis; o teto
-- não se trava aqui porque quem opera pode acrescentar pela tela de cadastro,
-- que é o lugar certo para isso.
DO $$
DECLARE magra text;
BEGIN
  SELECT string_agg(x.nome || ' (' || x.n || ')', ', ') INTO magra FROM (
    SELECT g.nome, count(i.id) AS n
      FROM ges_gerencias g
      LEFT JOIN ges_indicadores i ON i.gerencia_id = g.id AND i.ativo = 1
     WHERE g.ativa = 1
     GROUP BY g.nome HAVING count(i.id) < 6) x;
  IF magra IS NOT NULL THEN
    RAISE EXCEPTION 'gerência com menos de seis indicadores: %', magra;
  END IF;
END $$;
