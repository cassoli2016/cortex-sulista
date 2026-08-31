-- Fatura de pedágio da administradora de tag: a decomposição que o ERP não tem.
--
-- POR QUE ESTAS TABELAS EXISTEM
-- =============================
-- O gasto com o tag SEMPRE esteve no ERP — um título por mês em `contaapagar`
-- para o CNPJ da administradora, R$ 6,05 mi em 12 meses, MAIOR que o pedágio
-- cobrado do cliente no CT-e (R$ 5,03 mi). O que nunca esteve foi a
-- decomposição: qual placa, qual praça, qual travessia, a que tarifa.
--
-- Sem ela não dá para responder nada do que interessa — de quem é o gasto, se
-- a tarifa cobrada bate com a cadastrada, se o pedágio do agregado é recobrado.
-- Com ela, a tarifa CORRENTE de cada praça passa a ser observada todo mês, que
-- é o que `pracapedagio_valor` do ERP deixou de ser (a vigência mais recente de
-- toda aquela tabela é de 01/08/2025).
--
-- O ESCOPO É "ADMINISTRADORA DE TAG", NÃO "SEM PARAR"
-- ==================================================
-- A coluna `administradora` existe desde o primeiro dia, com o Sem Parar sendo
-- só o primeiro valor. Modelar para um fornecedor e generalizar depois custa
-- uma migration de dados; modelar com a coluna desde já custa uma palavra. E a
-- casa já tem quatro administradoras de vale (TARGET, GPS PAMCARY, EFRETE,
-- MOVE MAIS), então uma segunda fonte de tag é questão de tempo.
--
-- A TRAVESSIA NÃO TEM CHAVE NATURAL, E POR ISSO A REIMPORTAÇÃO É POR FATURA
-- ========================================================================
-- Duas travessias podem compartilhar placa, praça, segundo e valor sem que uma
-- seja cópia da outra, e o vale-pedágio imprime de propósito um par
-- débito/crédito com TODOS os campos iguais menos o D/C. Não há coluna que
-- distinga a linha repetida da linha duplicada.
--
-- Tentar um UNIQUE aqui repetiria o erro que custou 55 mil linhas na
-- RasterJOR: chave que inclui coluna anulável não restringe nada, porque no
-- Postgres NULL nunca colide com NULL. Então a idempotência é de OUTRO nível —
-- a fatura inteira é a unidade. Reimportar apaga as travessias daquela fatura
-- e regrava, tudo na mesma transação. A fatura TEM chave natural de verdade
-- (administradora + número), e ela é o UNIQUE.
--
-- Isso também dá o comportamento certo para o caso real: a mesma fatura
-- reenviada por engano não duplica nada, e a fatura reemitida pelo fornecedor
-- substitui a anterior em vez de conviver com ela.
--
-- O QUE NÃO É GRAVADO
-- ===================
-- A TARIFA POR EIXO não tem coluna. Ela é `valor / eixos`, calculada na
-- leitura, porque é derivada e porque gravá-la criaria dois armazéns do mesmo
-- parâmetro — que nesta casa já produziu uma tela de configuração dizendo
-- "salvo" enquanto o cálculo lia o outro lugar e o prêmio não mudava um
-- centavo.
--
-- O CONFRONTO com `pracapedagio_valor` também não é gravado: ele muda quando o
-- cadastro do ERP muda, e um confronto congelado acusaria como errada a praça
-- que já foi corrigida. Mesma regra do atraso de ação da Gestão.
--
-- `eixos` é gravado porque NÃO é derivável de fora: ele vem da leitura da
-- categoria (61 são 7 eixos, e isso é conhecimento do módulo, não do dado).

CREATE TABLE IF NOT EXISTS ped_faturas (
    id                SERIAL PRIMARY KEY,
    administradora    text        NOT NULL,
    numero_fatura     text        NOT NULL,
    numero_nf         text,
    cnpj_emissor      text,
    codigo_cliente    text,
    competencia       text,                    -- 'YYYY-MM' do FECHAMENTO
    dt_emissao        date,
    dt_fechamento     date,
    dt_vencimento     date,
    -- Os totais que a fatura IMPRIME. Guardados como ela os declara, para que
    -- a conferência continue possível depois — sem eles, uma travessia perdida
    -- numa reimportação futura não teria contra o que ser confrontada.
    total_fatura      numeric(14,2),
    total_passagens   numeric(14,2),
    total_vale        numeric(14,2),
    total_plano       numeric(14,2),
    total_estacion    numeric(14,2),
    total_creditos    numeric(14,2),
    qtd_declarada     integer,
    paginas           integer,
    arquivo_nome      text,
    arquivo_sha256    text,
    importado_em      timestamp   NOT NULL DEFAULT now(),
    importado_por     text,
    CONSTRAINT ped_faturas_chave UNIQUE (administradora, numero_fatura)
);

CREATE TABLE IF NOT EXISTS ped_travessias (
    id             BIGSERIAL PRIMARY KEY,
    fatura_id      integer     NOT NULL REFERENCES ped_faturas(id) ON DELETE CASCADE,
    -- 'tag'  = passagem paga pelo cartão da transportadora
    -- 'vale' = passagem coberta por vale-pedágio de embarcador (par D/C)
    tipo           text        NOT NULL CHECK (tipo IN ('tag', 'vale')),
    placa          text        NOT NULL,
    ts             timestamp   NOT NULL,
    concessionaria text,
    embarcador     text,                       -- só no vale; quem emitiu
    praca          text,                       -- o texto CRU, como a fatura escreve
    -- Decompostos do texto da praça. Ficam NULOS quando a fatura nomeia a praça
    -- só pela cidade ("ITATIAIA NORTE") em vez de rodovia + km: inventar
    -- rodovia faria a tarifa ser comparada contra a praça errada.
    rodovia        text,
    km             numeric(8,3),
    sentido        text,
    cidade         text,
    categoria      text,                       -- como vem: '1'..'6', '61', '62', '63'
    eixos          smallint,                   -- 61 -> 7. Nulo se a categoria for nova.
    viagem         text,
    valor          numeric(12,2) NOT NULL,
    dc             char(1)     NOT NULL CHECK (dc IN ('D', 'C'))
);

-- A DATA E A HORA SÃO COLUNAS SEPARADAS, e não um `timestamp`: nem toda linha
-- desta seção tem hora. As de veículo têm; as de ENCARGO da fatura inteira
-- ("ENCARGOS DE COBRANÇA", achado na fatura de jul/2026) trazem só a data, e
-- também não trazem placa nem tag — são lançamento do contrato, não do carro.
--
-- Completar a hora com meia-noite resolveria o NOT NULL inventando um horário
-- que a fonte não deu, e é a mesma decisão que a RasterJOR já obrigou a tomar:
-- lá `inicio` guarda a verdade e fica nulo quando é nulo, porque horário
-- inventado vira gráfico. Aqui ainda não vira, e é justamente por isso que a
-- hora de mentira passaria despercebida até o dia em que virasse.
CREATE TABLE IF NOT EXISTS ped_creditos (
    id          BIGSERIAL PRIMARY KEY,
    fatura_id   integer     NOT NULL REFERENCES ped_faturas(id) ON DELETE CASCADE,
    data        date        NOT NULL,
    hora        time,
    placa       text,
    tag         text,
    descricao   text,
    valor       numeric(12,2) NOT NULL,
    dc          char(1)     NOT NULL CHECK (dc IN ('D', 'C'))
);

-- A consulta que roda a cada leitura da tela é "as travessias desta competência
-- agrupadas por praça e eixos"; e a segunda é por placa.
CREATE INDEX IF NOT EXISTS ped_travessias_fatura_ix
    ON ped_travessias (fatura_id, tipo);
CREATE INDEX IF NOT EXISTS ped_travessias_praca_ix
    ON ped_travessias (rodovia, km) WHERE rodovia IS NOT NULL;
CREATE INDEX IF NOT EXISTS ped_travessias_placa_ix
    ON ped_travessias (placa, ts);
CREATE INDEX IF NOT EXISTS ped_creditos_fatura_ix
    ON ped_creditos (fatura_id);
