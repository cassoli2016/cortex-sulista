-- Gestão de Motoristas (GMA) — os PARÂMETROS da régua, por grupo e por versão.
--
-- O QUE É CÓDIGO E O QUE É DADO, que é a regra da casa (`api/premiacao/config.py`):
-- o CATÁLOGO é código — os desvios D01–D14, os méritos M01–M10 e os contadores
-- de risco do GR existem porque alguém escreveu a consulta que os mede. Os
-- PESOS e as FAIXAS são dado: mudam com a diretoria, valem a partir de uma
-- competência e não podem reescrever o que já foi pago.
--
-- POR QUE PENDURADO EM `prem_versoes` E NÃO NUMA SEGUNDA LINHA DO TEMPO: a
-- premiação já tem uma tabela que responde "a partir de quando esta régua
-- vale", com a vigência checada por competência. Criar outra faria "a régua
-- mudou em agosto" ter DUAS respostas — o mesmo defeito que já custou a rota
-- `/params` removida na 0.153.0 (dois armazéns do mesmo parâmetro).
--
-- POR QUE POR GRUPO: rodoviário e manobrista têm pesos, faixas e piso de
-- viagens diferentes (é assim no modelo de quem opera). Guardar um parâmetro
-- só e "adaptar" na leitura seria decidir no código o que é decisão da mesa.

CREATE TABLE IF NOT EXISTS prm_param (
    versao_id bigint  NOT NULL REFERENCES prem_versoes(id) ON DELETE CASCADE,
    grupo     text    NOT NULL,
    chave     text    NOT NULL,
    valor     numeric NOT NULL,
    PRIMARY KEY (versao_id, grupo, chave),
    CONSTRAINT prm_param_grupo CHECK (grupo IN ('RODOVIARIO', 'MANOBRA'))
);

COMMENT ON TABLE prm_param IS
    'Pesos dos pilares, faixas de status e categoria, piso de viagens do GR —
     por GRUPO e por versão. O catálogo de desvios e méritos é código; isto
     aqui é o que a mesa muda.';

-- O DE-PARA DO ERP. Cada `ocorrenciamotorista` do AVA vira um desvio (D01–D14),
-- um mérito (M01–M10) ou fica IGNORADO.
--
-- É TABELA, e não constante no código, por dois motivos: o ERP ganha código
-- novo sem avisar (41 tipos em 2026, e o mais frequente NÃO é demérito), e
-- quem decide o que cada um significa é a operação, não quem programa. Código
-- do ERP que ninguém mapeou fica de fora da conta e APARECE na tela pedindo
-- decisão — nunca vira desvio por descuido nem some em silêncio.
--
-- A semente abaixo é o de-para do modelo que quem opera desenhou (18/09/2026).
CREATE TABLE IF NOT EXISTS prm_depara (
    codigo         integer PRIMARY KEY,
    alvo           text NOT NULL,
    atualizado_em  text,
    atualizado_por text,
    CONSTRAINT prm_depara_alvo CHECK (alvo ~ '^(D[0-9]{2}|M[0-9]{2}|IGNORAR)$')
);

COMMENT ON TABLE prm_depara IS
    'Código de ocorrência do ERP -> desvio (D), mérito (M) ou IGNORAR. Código
     não mapeado não entra na conta e aparece na tela pedindo decisão.';

INSERT INTO prm_depara (codigo, alvo, atualizado_em, atualizado_por) VALUES
    (60,'D07',NULL,'modelo'), (21,'D07',NULL,'modelo'), (39,'D07',NULL,'modelo'),
    (38,'D09',NULL,'modelo'), (70,'D05',NULL,'modelo'), (11,'D09',NULL,'modelo'),
    (6,'D03',NULL,'modelo'),  (16,'D03',NULL,'modelo'), (64,'D11',NULL,'modelo'),
    (63,'D11',NULL,'modelo'), (1,'D01',NULL,'modelo'),  (29,'D01',NULL,'modelo'),
    (56,'D01',NULL,'modelo'), (49,'D01',NULL,'modelo'), (28,'D01',NULL,'modelo'),
    (7,'D01',NULL,'modelo'),  (31,'D02',NULL,'modelo'), (12,'D04',NULL,'modelo'),
    (26,'D06',NULL,'modelo'), (27,'D06',NULL,'modelo'), (74,'D08',NULL,'modelo'),
    (13,'D04',NULL,'modelo'), (15,'D04',NULL,'modelo'), (17,'D04',NULL,'modelo'),
    (65,'D12',NULL,'modelo'), (2,'D12',NULL,'modelo'),  (66,'D13',NULL,'modelo'),
    (67,'D13',NULL,'modelo'), (53,'D14',NULL,'modelo'), (34,'D01',NULL,'modelo'),
    (35,'D04',NULL,'modelo'), (54,'D01',NULL,'modelo'), (73,'D01',NULL,'modelo'),
    (201,'M01',NULL,'modelo'),(202,'M02',NULL,'modelo'),(203,'M03',NULL,'modelo'),
    (204,'M04',NULL,'modelo'),(205,'M05',NULL,'modelo'),(206,'M06',NULL,'modelo'),
    (207,'M07',NULL,'modelo'),(208,'M08',NULL,'modelo'),(209,'M09',NULL,'modelo'),
    (210,'M10',NULL,'modelo'),(42,'M07',NULL,'modelo'), (77,'M08',NULL,'modelo'),
    (19,'IGNORAR',NULL,'modelo'), (76,'IGNORAR',NULL,'modelo')
ON CONFLICT (codigo) DO NOTHING;

-- O PESO DE CADA CONTADOR DE RISCO DO GR.
--
-- O modelo original pesava ~70 TIPOS de exceção, que vêm de uma planilha que
-- alguém importa todo mês. A decisão de quem opera (18/09/2026) foi usar o que
-- já chega sozinho: os contadores por viagem que o RasterIntegra devolve
-- (`gr_viagem_fim`), medidos em ~2.500 viagens e 190 motoristas por mês.
--
-- SÃO MENOS CATEGORIAS, e isso está dito na tela: um desvio de rota aqui não
-- se separa de "continua fora de rota". O peso de cada uma é dado, por versão.
--
-- `sem_posicao` NÃO ENTRA na semente, e o motivo é medição: a coluna vem
-- SEMPRE vazia em 6 meses de coleta. Peso para um contador que nunca chega
-- daria a impressão de que ele pesa.
CREATE TABLE IF NOT EXISTS prm_gr_peso (
    versao_id bigint  NOT NULL REFERENCES prem_versoes(id) ON DELETE CASCADE,
    contador  text    NOT NULL,
    peso      numeric NOT NULL DEFAULT 0,
    PRIMARY KEY (versao_id, contador),
    CONSTRAINT prm_gr_peso_positivo CHECK (peso >= 0)
);

COMMENT ON TABLE prm_gr_peso IS
    'Quanto cada contador de risco do RasterIntegra pesa na nota de GR, por
     versão. Contador que o fornecedor não manda (sem_posicao, vazio em 6 meses
     de coleta) fica fora em vez de pesar zero e parecer medido.';
