-- 0043 · Em que DIA cada placa comunicou com a 3S.
--
-- O `tress_posicao` guarda a ÚLTIMA posição, que responde "está viva?" mas não
-- responde "comunicou no dia 2?". E é essa a pergunta da régua diária: às
-- 09:00 de hoje, medindo o dia fechado de ontem, a última posição da maioria
-- das carretas já é de HOJE — prova que estão vivas, não que falaram ontem.
--
-- Sem esta tabela o aviso mediria por aproximação ("teve posição depois do dia
-- X, logo comunicou no dia X"), que é falso justamente para a carreta que
-- voltou a comunicar hoje depois de uma semana muda — a única que interessa.
--
-- Uma linha por (placa, dia): ~230 linhas/dia, ~84 mil/ano. A coleta preenche
-- a partir da data da posição que ela leu, então o histórico começa no dia em
-- que a coleta começou a rodar. Antes disso, o aviso usa o que o ERP tem, e
-- diz que é o que tem.

CREATE TABLE IF NOT EXISTS tress_visto_dia (
  placa  text  NOT NULL,
  dia    date  NOT NULL,
  PRIMARY KEY (placa, dia)
);

COMMENT ON TABLE tress_visto_dia IS
  'Dias em que cada placa teve posição na 3S. Responde "comunicou no dia X?" '
  'com exatidão, que a última posição sozinha não responde.';

CREATE INDEX IF NOT EXISTS ix_tress_visto_dia ON tress_visto_dia (dia DESC);
