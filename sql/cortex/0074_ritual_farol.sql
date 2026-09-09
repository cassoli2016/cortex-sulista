-- 0074 · O farol do Ritual passa a sair da META, e não da opinião.
--
-- O QUE ESTAVA ACONTECENDO (medido em 08/09/2026)
-- ==============================================
-- Os 12 indicadores do Ritual estão com `meta_padrao` NULO — todos. Como
-- `_desvio()` devolve `None` sem meta, o desvio nunca aparecia, e o
-- verde/amarelo/vermelho era ESCOLHA LIVRE de quem preenchia.
--
-- Isso derrota metade da decisão fundadora do módulo. O texto dela é "o
-- realizado vem da FONTE, não do gerente, onde a casa já mede" — e o valor de
-- fato vinha da fonte. Só que o VEREDITO não vinha de lugar nenhum: o número
-- era objetivo e a cor era opinião, e é a cor que a reunião discute e que a
-- regra de fechamento usa. Na prática, a discussão voltaria a ser sobre a cor.
--
-- Agora o status é DERIVADO do desvio contra a meta, por faixas declaradas em
-- cada indicador. O gerente continua podendo discordar — mas discordar passa a
-- ser um ATO REGISTRADO, com justificativa e autor, em vez do estado normal.

-- ----------------------------------------------------- as faixas do farol
--
-- POR QUE POR INDICADOR, E NÃO UMA FAIXA DA CASA
-- ----------------------------------------------
-- Porque a tolerância não é a mesma. Receita 8% abaixo da meta é grave;
-- retorno vazio 8% acima do alvo pode ser uma semana ruim. Uma faixa única
-- obrigaria a escolher entre alarmar demais num indicador e de menos noutro —
-- e o alarme que acende à toa ensina a ignorar o alarme.
--
-- Os valores são PONTOS PERCENTUAIS DE DESVIO, já orientados por
-- `_desvio()`: positivo é sempre melhor que a meta, independentemente de o
-- indicador ser "quanto mais melhor" ou o contrário. Então a leitura é sempre
-- a mesma, em qualquer linha do painel:
--
--     desvio >= tol_verde     -> verde
--     desvio >= tol_vermelho  -> amarelo
--     abaixo disso            -> vermelho
--
-- Os padrões (0 e -10) dizem: "na meta ou melhor é verde; até 10 pontos
-- percentuais abaixo é amarelo; pior que isso é vermelho". São um ponto de
-- partida explícito, não uma verdade — cada indicador ajusta o seu.
ALTER TABLE ges_indicadores
  ADD COLUMN IF NOT EXISTS tol_verde    numeric(6,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tol_vermelho numeric(6,2) NOT NULL DEFAULT -10;

-- ------------------------------------------------------- a discordância
--
-- O gerente pode dizer que o farol calculado está errado — e às vezes está: o
-- mês teve um evento que a meta não previa, a fonte contou uma coisa que não
-- deveria. Tirar essa saída faria alguém contornar por fora (mexer na meta
-- para a cor sair certa), e aí o painel mente sem deixar rastro.
--
-- Mas discordar deixa de ser o estado normal e vira ATO: fica gravado o que o
-- sistema calculou (`status_calculado`), o que a pessoa escolheu (`status`),
-- e POR QUÊ. Sem o motivo não se sobrepõe — regra aplicada no Python, onde a
-- mensagem existe.
ALTER TABLE ges_apontamentos
  ADD COLUMN IF NOT EXISTS status_calculado text,
  ADD COLUMN IF NOT EXISTS status_motivo    text;

-- Uma pergunta que a diretoria vai fazer em algum momento — "com que
-- frequência a cor apresentada difere da calculada?" — e que sem índice
-- varreria a tabela inteira. Ela é pequena hoje (zero linhas), mas cresce uma
-- linha por indicador por semana e nunca é apagada.
CREATE INDEX IF NOT EXISTS ges_apontamentos_divergente
    ON ges_apontamentos (ciclo_id)
 WHERE status_calculado IS NOT NULL AND status IS DISTINCT FROM status_calculado;
