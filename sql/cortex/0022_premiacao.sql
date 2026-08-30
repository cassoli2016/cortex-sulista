-- ═══════════════════════════════════════════════════════════════════════════
--  PREMIAÇÃO — parâmetros, eixos e classificação de ocorrência
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Os parâmetros viviam em `data/premiacao_params.json` com três campos
-- (valor_por_km, nota_minima, km_minimo). Isso servia enquanto a regra era
-- "nota × km"; não serve para uma premiação de seis eixos que decide dinheiro
-- de gente.
--
-- TRÊS DECISÕES DE MODELAGEM, e as três existem para o mesmo fim: um prêmio
-- pago em março tem de continuar explicável em dezembro.
--
-- 1. **VERSÃO POR COMPETÊNCIA, não edição no lugar.** Mudar o peso do eixo de
--    diesel não pode reescrever o passado. Cada mudança cria uma VERSÃO com
--    `vigente_de`; o cálculo de uma competência usa a última versão vigente
--    até ela. Editar por cima faria a pergunta "por que paguei isso?" ficar
--    sem resposta — e ela sempre aparece.
--
-- 2. **PARÂMETRO É CHAVE/VALOR, não coluna.** Uma coluna por parâmetro
--    obrigaria uma migration a cada regra nova, e regra de premiação muda com
--    a política da empresa, não com o software. A validação do que cada chave
--    aceita fica no módulo, onde dá para escrever a mensagem em português.
--
-- 3. **A CLASSIFICAÇÃO DA OCORRÊNCIA NÃO É VERSIONADA, e é de propósito.**
--    O que congela o passado é o SNAPSHOT do cálculo, que já guarda o
--    resultado de cada motorista. Versionar também a classificação criaria
--    duas verdades para a mesma pergunta. Aqui vale o estado atual: se um tipo
--    for reclassificado, vale da próxima apuração em diante.

CREATE TABLE IF NOT EXISTS prem_versoes(
    id            bigserial PRIMARY KEY,
    -- competência a partir da qual esta versão vale ('AAAA-MM')
    vigente_de    text    NOT NULL,
    regra         text    NOT NULL DEFAULT 'eixos',
    nota          text    NOT NULL DEFAULT '',   -- por que mudou
    criado_em     text    NOT NULL,
    criado_por    text    NOT NULL DEFAULT '',
    CONSTRAINT prem_versoes_comp CHECK (vigente_de ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT prem_versoes_unica UNIQUE (vigente_de)
);

CREATE TABLE IF NOT EXISTS prem_parametros(
    versao_id  bigint  NOT NULL REFERENCES prem_versoes(id) ON DELETE CASCADE,
    chave      text    NOT NULL,
    valor      numeric NOT NULL,
    PRIMARY KEY (versao_id, chave)
);

-- Peso de cada eixo. `ativo = 0` DESLIGA o eixo sem perder o peso configurado,
-- que é o que se quer ao ligar um eixo novo aos poucos: liga, olha o efeito,
-- desliga se estiver ruim — sem ter de redigitar o número depois.
CREATE TABLE IF NOT EXISTS prem_eixos(
    versao_id  bigint  NOT NULL REFERENCES prem_versoes(id) ON DELETE CASCADE,
    eixo       text    NOT NULL,
    peso       numeric NOT NULL DEFAULT 0,
    ativo      integer NOT NULL DEFAULT 1,
    PRIMARY KEY (versao_id, eixo),
    CONSTRAINT prem_eixos_peso CHECK (peso >= 0)
);

-- ── Classificação dos tipos de ocorrência do ERP ────────────────────────────
--
-- São 41 tipos e 563 ocorrências em 2026, e o mais frequente NÃO É DEMÉRITO:
-- "pontos de contratação novo agregado" são 187 (33%), com 182 motoristas
-- distintos — é registro de entrada. Uma contagem ingênua de ocorrências
-- penalizaria todo agregado por ter sido contratado.
--
-- Existe MÉRITO no cadastro ("mérito por ajudar a operação", "elogio de
-- clientes"), então a premiação pode somar e não só descontar.
--
-- `peso` multiplica dentro da classe: uma multa gravíssima não vale o mesmo
-- que uma leve. Quem decide o número é a operação, não o software.
CREATE TABLE IF NOT EXISTS prem_ocorrencia_classe(
    codigo         integer PRIMARY KEY,       -- ocorrenciamotorista (AVA)
    descricao      text    NOT NULL DEFAULT '',
    classe         text    NOT NULL DEFAULT 'nao_classificado',
    grupo          text    NOT NULL DEFAULT '',
    peso           numeric NOT NULL DEFAULT 1,
    bloqueia       integer NOT NULL DEFAULT 0,  -- trava o prêmio do mês
    atualizado_em  text    NOT NULL DEFAULT '',
    atualizado_por text    NOT NULL DEFAULT '',
    CONSTRAINT prem_classe_valida CHECK (
        classe IN ('demerito', 'neutro', 'merito', 'nao_classificado')),
    CONSTRAINT prem_classe_peso CHECK (peso >= 0)
);

-- TIPO NOVO NASCE `nao_classificado`, NÃO `neutro`. A diferença importa: o
-- ERP ganha tipo de ocorrência sem avisar ninguém, e um tipo novo que entrasse
-- como neutro sumiria da tela — a premiação seguiria ignorando algo que talvez
-- devesse contar. Não classificado APARECE, com aviso, até alguém decidir.

CREATE INDEX IF NOT EXISTS prem_classe_por_classe
    ON prem_ocorrencia_classe (classe);
