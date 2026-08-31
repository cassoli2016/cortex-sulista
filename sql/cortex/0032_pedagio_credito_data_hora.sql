-- Conserta `ped_creditos`: `ts` vira `data` + `hora`, e a hora pode ser NULA.
--
-- POR QUE ESTA MIGRATION EXISTE, E É A PARTE QUE VALE GUARDAR
-- ==========================================================
-- A 0030 nasceu com `ts timestamp NOT NULL` e foi corrigida no MESMO dia para
-- `data date NOT NULL` + `hora time` — nem toda linha da seção de créditos tem
-- hora, e a de "ENCARGOS DE COBRANÇA" da fatura de jul/2026 derrubava a
-- importação inteira com `Invalid isoformat string: ''`.
--
-- Mas a correção do ARQUIVO chegou tarde demais: a 0030 já tinha sido aplicada
-- neste banco às 13:31, com o conteúdo antigo. O runner registra a migration
-- pelo NÚMERO, então editar o arquivo depois não muda nada no banco — e o
-- resultado foi produção com `ts` e código inserindo em `data`/`hora`:
--
--     Não foi possível gravar a fatura (UndefinedColumn)
--
-- E COMO ELA FOI APLICADA NO BANCO DE PRODUÇÃO SEM NINGUÉM MANDAR:
-- `TestClient(app)` DISPARA OS EVENTOS DE STARTUP, e o startup desta casa
-- chama `auth.init_db()`, que chama `migracoes.aplicar()` no schema PADRÃO.
-- Um teste de rota escrito para exercitar o upload aplicou DDL no `cortex` de
-- verdade. Não houve erro, não houve aviso: a migration simplesmente rodou.
--
-- A lição, que vale para qualquer módulo novo: usar `TestClient` contra
-- `api.main` é escrever no banco padrão. Quem quiser exercitar rota sem tocar
-- em produção redireciona o `ESQUEMA` do módulo ANTES de instanciar o cliente,
-- ou chama a função da rota direto, sem o cliente.
--
-- ELA PRECISA VALER NOS DOIS BANCOS, E ESSE É O CUIDADO QUE QUASE FALTOU
-- =====================================================================
-- Num banco que já rodou a 0030 ANTIGA existe `ts` e não existem `data`/`hora`.
-- Num banco NOVO a 0030 corrente já cria `data`/`hora` e `ts` nunca existiu —
-- e ali um `UPDATE ... SET data = ts::date` cru falharia com `UndefinedColumn`,
-- que é exatamente o erro que esta migration existe para consertar.
--
-- Daí o bloco condicional: ele pergunta ao catálogo se a coluna está lá antes
-- de tocá-la. `ADD COLUMN IF NOT EXISTS` e `DROP COLUMN IF EXISTS` já são
-- idempotentes sozinhos; quem precisa da guarda é a CONVERSÃO no meio.

ALTER TABLE ped_creditos ADD COLUMN IF NOT EXISTS data date;
ALTER TABLE ped_creditos ADD COLUMN IF NOT EXISTS hora time;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'ped_creditos'
                  AND column_name = 'ts') THEN
        -- Preserva o que houver, mesmo com a tabela vazia hoje em produção: uma
        -- migration que só funciona vazia é armadilha para quem a rodar noutro
        -- banco — o de homologação, o restaurado de backup, o da próxima máquina.
        EXECUTE 'UPDATE ped_creditos SET data = ts::date, hora = ts::time '
                'WHERE data IS NULL AND ts IS NOT NULL';
    END IF;
END $$;

ALTER TABLE ped_creditos DROP COLUMN IF EXISTS ts;

-- O NOT NULL entra DEPOIS da conversão, senão ele recusaria as linhas
-- existentes no instante em que a coluna nasce vazia.
ALTER TABLE ped_creditos ALTER COLUMN data SET NOT NULL;
