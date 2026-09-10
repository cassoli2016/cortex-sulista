-- 0078 · ANTT — a data que mede o frescor, e o valor que se paga.
--
-- POR QUE ISTO EXISTE
-- ===================
--
-- Quem opera pediu para validar as multas da ANTT em 10/09/2026, desconfiando
-- que a coleta tivesse parado. A tela mostrava "última: 02/05/2026" — quatro
-- meses atrás — e a memória da casa registrava "ANTT parada desde 02/05/2026".
--
-- A coleta NÃO estava parada. Forçada na hora, a API respondeu em 1,0 s com as
-- 209 autuações, e o último lote tinha sido EMITIDO em 11/07/2026 com 54
-- autuações — o maior mês da série. O que a tela chamava de "última" era a
-- data da INFRAÇÃO, e infração e emissão são separadas por meses:
--
--     emissão do PDF por mês   jan/26 43 · fev 5 · mar 38 · abr 30
--                              mai — · jun — · JUL 54 · ago — · set —
--
-- Lacunas de um a dois meses são o normal desta fonte. A régua estava lendo o
-- campo errado, e o campo certo — `DATA_EMISSAO`, que é por onde o próprio
-- endpoint filtra — existia só dentro do `detalhe` jsonb. Nenhum alarme
-- conseguia olhar para ele. É o que esta migration conserta.
--
-- E O VALOR: a tabela guarda `valor`, que é o ORIGINAL da autuação. Medido em
-- 10/09/2026, 88 das 209 já têm valor atualizado maior — R$ 713.256,77 contra
-- R$ 740.670,72, uma diferença de R$ 27.413,95. Nenhum dos dois é errado, mas
-- eles são números diferentes e quem vai PAGAR deve o atualizado. Guardar só
-- um obrigava a tela a escolher em silêncio; guardar os dois deixa a escolha
-- explícita e conferível.
--
-- O `vencimento` fica de fora desta migration DE PROPÓSITO: a coluna já
-- existe desde a 0029 e sempre esteve 100% vazia (0 de 209) porque o coletor
-- lia a chave `VENCIMENTO`, que não existe no payload — lá é
-- `BOLETO_VENCIMENTO`, presente em 199 das 209. Isso é defeito de leitura, não
-- de esquema, e se conserta em `armazenamento.gravar_antt`.
--
-- RETROATIVO SEM NOVA COLETA
-- ==========================
--
-- As duas colunas se preenchem a partir do `detalhe` que já está gravado — o
-- payload cru sempre foi guardado inteiro. Não é preciso esperar a próxima
-- coleta para a tela parar de mentir sobre o frescor, e o backfill é
-- idempotente: a coleta seguinte reescreve os mesmos valores.

ALTER TABLE smt_antt ADD COLUMN IF NOT EXISTS data_emissao     date;
ALTER TABLE smt_antt ADD COLUMN IF NOT EXISTS valor_atualizado numeric(14,2);

-- `to_date` com string vazia levanta; o `nullif` é o que segura isso. E o
-- filtro por formato existe porque um dia o fornecedor pode mandar ISO: sem
-- ele, a migration inteira falharia por causa de uma linha.
UPDATE smt_antt
   SET data_emissao = to_date(detalhe->>'DATA_EMISSAO', 'DD/MM/YYYY')
 WHERE data_emissao IS NULL
   AND nullif(btrim(coalesce(detalhe->>'DATA_EMISSAO', '')), '') ~ '^\d{2}/\d{2}/\d{4}$';

UPDATE smt_antt
   SET valor_atualizado = (detalhe->>'VALOR_ATUALIZADO')::numeric
 WHERE valor_atualizado IS NULL
   AND nullif(btrim(coalesce(detalhe->>'VALOR_ATUALIZADO', '')), '') ~ '^[0-9]+(\.[0-9]+)?$';

UPDATE smt_antt
   SET vencimento = to_date(detalhe->>'BOLETO_VENCIMENTO', 'DD/MM/YYYY')
 WHERE vencimento IS NULL
   AND nullif(btrim(coalesce(detalhe->>'BOLETO_VENCIMENTO', '')), '') ~ '^\d{2}/\d{2}/\d{4}$';

-- A varredura da tela ordena e mede por emissão; sem índice ela varre as 209
-- linhas, o que hoje não custa nada — o índice é para o dia em que forem
-- 20.000, e custa menos criá-lo agora que descobrir depois.
CREATE INDEX IF NOT EXISTS ix_smt_antt_emissao ON smt_antt(data_emissao DESC);
