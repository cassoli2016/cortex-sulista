-- Ritual Semanal: o TERCEIRO indicador de cada gerência.
--
-- POR QUE UMA MIGRATION NOVA, E NÃO UMA EDIÇÃO DA 0067
-- ====================================================
-- A 0067 já estava APLICADA no banco de produção quando este ajuste foi
-- pedido — e não por um deploy: a suíte completa sobe um uvicorn de verdade
-- (`tests/test_rotas_nao_travam.py`), e o `startup` da API aplica as migrations
-- pendentes no schema PADRÃO. É o vazamento que já queimou os números 59 e 108
-- nesta casa. O runner recusa número repetido com arquivo diferente, então
-- editar a 0067 daria erro na próxima aplicação de quem estivesse atrás.
--
-- Nada se perdeu: as tabelas que a suíte criou são as mesmas que a entrega
-- precisa, e ninguém as lê enquanto o código não sobe.
--
-- A ESCOLHA DE CADA UM
-- ====================
-- Três por gerência é o que cabe em dois minutos de fala sem virar leitura de
-- planilha. O terceiro de cada uma foi escolhido para ABRIR UMA DIMENSÃO que as
-- outras duas não cobriam — e não para acrescentar mais um número parecido:
--
--   Comercial    ATINGIMENTO DA META. As outras duas são valores (receita e
--                vencidos); esta é a RÉGUA, e é literalmente a pergunta da
--                primeira etapa do roteiro ("onde estamos versus meta?"). Sai
--                pronta do payload da Visão Geral: o atingimento é
--                realizado_acumulado ÷ meta_acumulada, e misturar numerador de
--                uma régua com denominador de outra é erro conhecido da casa.
--
--   Operação     RKM. Retorno vazio e km/l medem DESPERDÍCIO; o RKM mede o que
--                o km rodado rende. Sem ele a gerência discute só custo, e uma
--                operação pode estar enxuta e mal precificada ao mesmo tempo.
--
--   Manutenção   ORDENS DE COMPRA ATRASADAS. OS aberta e custo são o efeito;
--                peça que não chega é uma das causas, e ela mora em outra área
--                (Suprimentos). Pôr a causa no painel de quem sofre o efeito é
--                o que faz a reunião destravar em vez de cobrar.
--
--   RH           AFASTADOS. As outras duas são conformidade com prazo (férias,
--                CNH). Afastamento é a dimensão de gente, e é a que move
--                semana a semana. `cnh_vencidas` foi descartada de propósito:
--                está em ZERO hoje, e indicador que não pode mudar dentro do
--                ciclo é papel de parede — a mesma razão pela qual as fontes
--                da Operação usam mês corrente e não ano.
--
-- Metas continuam VAZIAS: meta é decisão de quem responde pelo número, e
-- semear um valor plausível faria a primeira reunião discutir uma meta que
-- ninguém combinou.
--
-- Toda `fonte` daqui existe em `api.gestao.ritual.FONTES`, e há teste que
-- confere os dois lados — chave inválida não daria erro nenhum: o indicador
-- entraria como automático e ficaria vazio para sempre.

INSERT INTO ges_indicadores(gerencia_id, nome, unidade, direcao, fonte, casas,
                            ordem, criado_em)
SELECT g.id, v.nome, v.unidade, v.direcao, v.fonte, v.casas, v.ordem, ''
  FROM (VALUES
    ('comercial',  'Atingimento da meta',         '%',      'maior_melhor', 'atingimento_meta', 1, 3),
    ('operacao',   'RKM — receita por km',        'R$/km',  'maior_melhor', 'rkm',              2, 3),
    ('manutencao', 'Ordens de compra atrasadas',  'OC',     'menor_melhor', 'oc_atrasadas',     0, 3),
    ('rh',         'Afastados',                   'pessoas','menor_melhor', 'afastados',        0, 3)
  ) AS v(ger, nome, unidade, direcao, fonte, casas, ordem)
  JOIN ges_gerencias g ON g.chave = v.ger
 WHERE NOT EXISTS (SELECT 1 FROM ges_indicadores i
                    WHERE i.gerencia_id = g.id AND i.nome = v.nome);
