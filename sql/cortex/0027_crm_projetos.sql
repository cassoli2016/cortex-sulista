-- Controle de projetos: o que acontece DEPOIS da venda.
--
-- POR QUE UM OBJETO NOVO, e não mais um estágio da oportunidade. A oportunidade
-- termina em ganha ou perdida — ela responde "vamos fechar?". O projeto começa
-- aí e responde outra coisa: "está entrando no ar no prazo, com o escopo
-- combinado, rendendo o que foi prometido?". São perguntas com donos diferentes
-- (comercial × implantação), prazos diferentes e ciclos de vida diferentes.
-- Empilhar as duas no mesmo registro faria o kanban do funil ganhar quatro
-- colunas de execução e misturaria o que a diretoria olha semanalmente com o
-- que o comercial olha diariamente.
--
-- O MODELO VEIO DO AVACORP (`sulista.pipelineprojetos`, 194 projetos), mas não
-- é cópia dele. Três diferenças, e cada uma sai de ler o dado real de lá:
--
-- 1. **`aging_dias` não existe aqui.** No ERP essa coluna está preenchida em
--    ZERO de 194 linhas — e ainda por cima é `timestamp`, apesar do nome dizer
--    dias. A tela de CRM que a lia mostrava "—" em todas as linhas desde
--    sempre. Aqui a idade é DERIVADA das datas, como todo estado que envelhece
--    sozinho nesta casa.
--
-- 2. **Os campos de dinheiro não são digitados por padrão.** No ERP,
--    `rob_mensal`, `rol_mensal`, `lucro_bruto` e `csp` estão preenchidos em 33%
--    dos projetos — dois terços do pipeline sem valor nenhum. Aqui o valor sai
--    das LANES (`crm_lanes.projeto_id`), que já carregam R$/km, piso da ANTT e
--    margem contra o CKM; `rob_mensal_manual` é a exceção declarada, para o
--    projeto que ainda não tem lane.
--
-- 3. **Versão não é linha nova.** O ERP guarda até 5 linhas por `numeroid`,
--    uma por versão, e quem consulta tem de lembrar do `DISTINCT ON`. Aqui a
--    versão é um contador no próprio projeto e o histórico vive em
--    `crm_projeto_andamentos`, append-only — o mesmo par de `ges_acoes` e
--    `ges_andamentos`, que responde "há quanto tempo isto está parado" sem
--    precisar reconstruir nada.


-- --------------------------------------------------------------- projetos --
-- A CADEIA DE DATAS é o coração do controle, e ela tem duas metades que não se
-- confundem: o que foi COMBINADO (`inicio_previsto`, `deadline`) e o que
-- ACONTECEU (`inicio_real`, `entrega`, `aceite`). Guardar só uma das metades é
-- o que faz um projeto entregue com três meses de atraso parecer entregue no
-- prazo — e é o erro que o `data_entrega` sozinho do ERP permite.
--
-- NÃO EXISTE COLUNA DE ATRASO, nem de idade, nem de "dias em execução". Tudo
-- isso é derivado das datas contra hoje, pela mesma razão do atraso de ação na
-- Gestão e da vigência de contrato no CRM: estado gravado precisa de alguém
-- para virar, e no dia em que a rotina não roda a tela diz que está tudo em dia.
CREATE TABLE IF NOT EXISTS crm_projetos(
    id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conta_id          integer NOT NULL REFERENCES crm_contas(id) ON DELETE CASCADE,
    oportunidade_id   integer REFERENCES crm_oportunidades(id) ON DELETE SET NULL,
    contrato_id       integer REFERENCES crm_contratos(id) ON DELETE SET NULL,
    ano               integer NOT NULL,
    sequencia         integer NOT NULL,
    codigo            text    NOT NULL,
    nome              text    NOT NULL,
    escopo            text    NOT NULL DEFAULT '',
    detalhe           text    NOT NULL DEFAULT '',
    versao            integer NOT NULL DEFAULT 1,
    status            text    NOT NULL DEFAULT 'nao_iniciado',
    -- combinado
    recebimento       date,
    inicio_previsto   date,
    deadline          date,
    -- aconteceu
    inicio_real       date,
    entrega           date,
    aceite            date,
    prazo_cliente_dias integer,
    solicitante       text    NOT NULL DEFAULT '',
    responsavel_id    integer REFERENCES usuarios(id) ON DELETE SET NULL,
    responsavel_nome  text    NOT NULL DEFAULT '',
    rob_mensal_manual numeric(14,2),
    percentual        integer NOT NULL DEFAULT 0,
    motivo_encerramento text  NOT NULL DEFAULT '',
    encerrado_detalhe text    NOT NULL DEFAULT '',
    observacoes       text    NOT NULL DEFAULT '',
    criado_por        text    NOT NULL DEFAULT '',
    criado_em         text    NOT NULL DEFAULT '',
    alterado_por      text    NOT NULL DEFAULT '',
    alterado_em       text    NOT NULL DEFAULT '',
    CONSTRAINT crm_proj_seq_uk UNIQUE (ano, sequencia),
    CONSTRAINT crm_proj_quem_ck
        CHECK (responsavel_id IS NOT NULL OR responsavel_nome <> ''),
    CONSTRAINT crm_proj_status_ck
        CHECK (status IN ('nao_iniciado', 'implantacao', 'em_execucao',
                          'entregue', 'declinado', 'cancelado')),
    CONSTRAINT crm_proj_versao_ck  CHECK (versao >= 1),
    CONSTRAINT crm_proj_pct_ck     CHECK (percentual BETWEEN 0 AND 100),
    -- Encerramento sem motivo não ensina nada — mesma regra da oportunidade
    -- perdida, e pelo mesmo motivo: é a única hora em que alguém lembra.
    CONSTRAINT crm_proj_motivo_ck
        CHECK (status NOT IN ('declinado', 'cancelado')
               OR motivo_encerramento <> ''),
    -- Entregue exige a data da entrega, e o que não está entregue não pode
    -- tê-la: é dela que sai o cumprimento de prazo, e um dos dois lados errado
    -- faz a métrica mentir sem que nada pareça errado.
    CONSTRAINT crm_proj_entrega_ck
        CHECK ((status = 'entregue') = (entrega IS NOT NULL)),
    -- Datas em ordem. O banco recusa a inversão porque ela produz prazo
    -- NEGATIVO na tela, que se lê como "entregou antes de começar".
    CONSTRAINT crm_proj_ordem_ck
        CHECK ((inicio_real IS NULL OR recebimento IS NULL
                OR inicio_real >= recebimento)
           AND (entrega IS NULL OR inicio_real IS NULL OR entrega >= inicio_real)
           AND (aceite IS NULL OR entrega IS NULL OR aceite >= entrega))
);

CREATE INDEX IF NOT EXISTS ix_crm_proj_conta   ON crm_projetos(conta_id);
CREATE INDEX IF NOT EXISTS ix_crm_proj_status  ON crm_projetos(status, deadline);
CREATE INDEX IF NOT EXISTS ix_crm_proj_resp    ON crm_projetos(responsavel_id, status);
CREATE INDEX IF NOT EXISTS ix_crm_proj_opo     ON crm_projetos(oportunidade_id);

COMMENT ON TABLE crm_projetos IS
    'Execução do que foi vendido. NÃO tem coluna de atraso nem de idade: as
     duas saem das datas contra hoje. Modelado a partir de
     sulista.pipelineprojetos, sem os campos que lá estão vazios.';
COMMENT ON COLUMN crm_projetos.deadline IS
    'O prazo COMBINADO. Junto de `entrega` (o que aconteceu) é o que permite
     dizer se entregou no prazo — guardar só a entrega faz projeto atrasado
     três meses parecer entregue em dia.';
COMMENT ON COLUMN crm_projetos.oportunidade_id IS
    'De onde o projeto nasceu. ON DELETE SET NULL: apagar o registro da venda
     não apaga a entrega que está acontecendo.';
COMMENT ON COLUMN crm_projetos.rob_mensal_manual IS
    'Exceção declarada, só enquanto o projeto não tiver lane. No ERP de origem
     os campos de dinheiro estão preenchidos em 33% dos projetos; aqui o valor
     sai das lanes, que têm conta por trás.';


-- ------------------------------------------------------------ andamentos --
-- Append-only, como `ges_andamentos` e `crm_interacoes`. É daqui que sai "há
-- quanto tempo este projeto não anda", que é a pergunta que um status sozinho
-- não responde: "em execução" há dois meses sem ninguém escrever nada não está
-- em execução, está esquecido.
CREATE TABLE IF NOT EXISTS crm_projeto_andamentos(
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    projeto_id   integer NOT NULL REFERENCES crm_projetos(id) ON DELETE CASCADE,
    ts           text    NOT NULL,
    usuario      text    NOT NULL DEFAULT '',
    texto        text    NOT NULL DEFAULT '',
    status_de    text,
    status_para  text,
    percentual   integer,
    versao       integer,
    CONSTRAINT crm_proj_and_pct_ck
        CHECK (percentual IS NULL OR percentual BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS ix_crm_proj_and ON crm_projeto_andamentos(projeto_id, ts DESC);

COMMENT ON TABLE crm_projeto_andamentos IS
    'Histórico do projeto, append-only. Andamento editável deixa de ser prova
     de que o projeto andou.';


-- ------------------------------------------------- a lane ganha um terceiro --
-- `crm_lanes` já servia à oportunidade (preço proposto) e ao contrato (preço
-- vigente). Agora serve ao projeto (escopo entregue), e continua sendo UMA
-- tabela pelo mesmo motivo de antes: três implementações do cálculo de R$/km e
-- do piso da ANTT divergiriam justamente entre o que foi vendido, o que foi
-- assinado e o que está sendo entregue — que é onde a divergência dói.
--
-- O CHECK passa de "um dos dois" para "exatamente um dos três". Sem ele, uma
-- lane órfã (os três nulos) não apareceria em tela nenhuma, e uma lane com dois
-- donos apareceria em duas com o mesmo id.
ALTER TABLE crm_lanes ADD COLUMN IF NOT EXISTS projeto_id integer;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'crm_lanes_projeto_fk') THEN
        ALTER TABLE crm_lanes
            ADD CONSTRAINT crm_lanes_projeto_fk
            FOREIGN KEY (projeto_id) REFERENCES crm_projetos(id)
            ON DELETE CASCADE;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'crm_lanes_dono_ck') THEN
        ALTER TABLE crm_lanes DROP CONSTRAINT crm_lanes_dono_ck;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'crm_lanes_dono3_ck') THEN
        ALTER TABLE crm_lanes ADD CONSTRAINT crm_lanes_dono3_ck CHECK (
            (CASE WHEN oportunidade_id IS NOT NULL THEN 1 ELSE 0 END
           + CASE WHEN contrato_id    IS NOT NULL THEN 1 ELSE 0 END
           + CASE WHEN projeto_id     IS NOT NULL THEN 1 ELSE 0 END) = 1);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_crm_lanes_proj ON crm_lanes(projeto_id, ordem);

COMMENT ON COLUMN crm_lanes.projeto_id IS
    'A lane do PROJETO é cópia da oportunidade no momento em que o projeto
     nasce — é o escopo prometido, congelado. Referenciar as da oportunidade
     faria uma correção na proposta reescrever o que se combinou entregar.';
