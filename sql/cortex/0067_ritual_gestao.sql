-- Ritual Semanal de Gestão — "Execução & Resultados".
--
-- A reunião de 30 minutos que acompanha, toda semana, o que cada gerência
-- prometeu na reunião de resultados. Quatro gerências hoje: Recursos Humanos,
-- Operação, Manutenção e Comercial.
--
-- O QUE ESTE SCHEMA RECUSA A CRIAR, E POR QUÊ
-- ===========================================
--
-- **Não existe tabela de "compromisso".** Compromisso É uma `ges_acoes` com
-- prazo na próxima reunião. Criar uma tabela paralela faria o plano de ação da
-- reunião de resultados e o da semanal viverem em dois lugares — que é
-- exatamente o PowerPoint paralelo que este ritual existe para matar, só que
-- dentro do banco, onde ninguém vê. A ligação vai em `ges_apontamentos.acao_id`.
--
-- **Não existe status "atrasado" gravado**, pela mesma razão que `ges_acoes`
-- não tem (ver 0020): atraso é `prazo < hoje AND status IN (aberta,
-- em_andamento)`, calculado na leitura. Status que envelhece sozinho precisa de
-- alguém para virar, e no dia em que ninguém vira a tela mente.
--
-- **Não existe coluna "cumpriu o compromisso da semana passada".** Ela sai do
-- cruzamento entre o prazo da ação e o ciclo — derivar é o que garante que a
-- resposta não discorde da própria ação depois de alguém editá-la.


-- --------------------------------------------------------------- gerências --
-- TABELA, e não constante no código, porque gerência muda com organograma e
-- organograma não deveria pedir deploy. E `gestor_id` é o que permite a tela
-- dizer QUEM ainda não preencheu -- que é informação de gestão por si só, e a
-- razão principal de o preenchimento ser antes da reunião.
CREATE TABLE IF NOT EXISTS ges_gerencias(
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chave      text    NOT NULL,
    nome       text    NOT NULL,
    gestor_id  integer REFERENCES usuarios(id) ON DELETE SET NULL,
    ordem      integer NOT NULL DEFAULT 0,
    ativa      integer NOT NULL DEFAULT 1,
    CONSTRAINT ges_gerencias_chave_uk UNIQUE (chave)
);

COMMENT ON COLUMN ges_gerencias.gestor_id IS
    'ON DELETE SET NULL: desligar o usuário não pode apagar a gerência nem o
     histórico de apontamento dela. A gerência fica sem gestor, à vista.';
COMMENT ON COLUMN ges_gerencias.ativa IS
    'Gerência que sai do organograma vira inativa, nunca DELETE: os ciclos
     passados citam ela, e apagar reescreveria a história das reuniões.';


-- ------------------------------------------------------------ indicadores --
-- O que cada gerência leva para a reunião. É CADASTRO, não código: a lista de
-- indicadores muda com o negócio, e cada mudança dela não pode custar entrega.
--
-- `fonte` é a decisão central deste módulo. 'manual' significa que o gerente
-- digita o realizado; qualquer outro valor é a CHAVE de uma fonte automática
-- registrada em `api/gestao_ritual.FONTES`, e aí o número chega sozinho, do
-- mesmo lugar que a tela do assunto mostra. Indicador automático não se digita
-- -- e é isso que faz a reunião discutir o número em vez de conferir digitação.
--
-- A chave é validada no Python, e não por CHECK aqui: o CHECK congelaria a
-- lista de fontes no schema e obrigaria migration a cada fonte nova. O guard
-- que vale é o teste que varre o cadastro contra o registro real (fonte órfã
-- não tem sintoma: o indicador simplesmente aparece vazio para sempre).
CREATE TABLE IF NOT EXISTS ges_indicadores(
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gerencia_id   integer NOT NULL REFERENCES ges_gerencias(id) ON DELETE CASCADE,
    nome          text    NOT NULL,
    unidade       text    NOT NULL DEFAULT '',
    direcao       text    NOT NULL DEFAULT 'maior_melhor',
    fonte         text    NOT NULL DEFAULT 'manual',
    meta_padrao   numeric(16,4),
    casas         integer NOT NULL DEFAULT 0,
    ordem         integer NOT NULL DEFAULT 0,
    ativo         integer NOT NULL DEFAULT 1,
    criado_em     text    NOT NULL DEFAULT '',
    CONSTRAINT ges_ind_direcao_ck
        CHECK (direcao IN ('maior_melhor', 'menor_melhor')),
    CONSTRAINT ges_ind_casas_ck CHECK (casas BETWEEN 0 AND 4)
);

CREATE INDEX IF NOT EXISTS ix_ges_ind_ger ON ges_indicadores(gerencia_id, ordem);

COMMENT ON COLUMN ges_indicadores.direcao IS
    'Sem isto o semáforo erra metade dos indicadores. Receita abaixo da meta é
     vermelho; multa abaixo da meta é verde. Não existe "desvio ruim" sem saber
     para que lado o indicador é bom.';
COMMENT ON COLUMN ges_indicadores.meta_padrao IS
    'A meta que vale quando o ciclo não define outra. Fica no indicador porque
     meta que se redigita toda semana vira meta que ninguém confere.';


-- ----------------------------------------------------------------- ciclos --
-- Uma linha por semana de reunião. `ano`+`semana` é a semana ISO, e o UNIQUE
-- impede duas reuniões da mesma semana -- o erro que faria dois painéis
-- concorrentes existirem sem ninguém perceber qual é o bom.
--
-- `prazo_preenchimento` é o corte: até ele, o gerente preenche; a tela mostra
-- quem faltou. Não é trava -- preenchimento depois do corte é aceito e fica
-- MARCADO como atrasado. Recusar seria transformar "esqueci" em "não tenho o
-- número na reunião", que é pior para todo mundo na sala.
CREATE TABLE IF NOT EXISTS ges_ciclos(
    id                  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ano                 integer NOT NULL,
    semana              integer NOT NULL,
    data_reuniao        date    NOT NULL,
    prazo_preenchimento text    NOT NULL DEFAULT '',
    reuniao_id          integer REFERENCES ges_reunioes(id) ON DELETE SET NULL,
    status              text    NOT NULL DEFAULT 'aberto',
    observacoes         text    NOT NULL DEFAULT '',
    criado_por          text    NOT NULL DEFAULT '',
    criado_em           text    NOT NULL DEFAULT '',
    fechado_por         text    NOT NULL DEFAULT '',
    fechado_em          text    NOT NULL DEFAULT '',
    CONSTRAINT ges_ciclos_sem_uk UNIQUE (ano, semana),
    CONSTRAINT ges_ciclos_status_ck CHECK (status IN ('aberto', 'fechado')),
    CONSTRAINT ges_ciclos_semana_ck CHECK (semana BETWEEN 1 AND 53)
);

CREATE INDEX IF NOT EXISTS ix_ges_ciclos_data ON ges_ciclos(data_reuniao DESC);

COMMENT ON TABLE ges_ciclos IS
    'A semana do ritual. Fechar o ciclo é o que aplica as regras do jogo:
     desvio sem ação não fecha pauta. Ver api/gestao_ritual.fechar().';
COMMENT ON COLUMN ges_ciclos.reuniao_id IS
    'A ata, quando alguém quiser uma. Opcional de propósito: o painel da semana
     já é o registro do que foi combinado, e exigir ata faria o ritual depender
     de um segundo preenchimento que ninguém faria toda semana.';


-- ----------------------------------------------------------- apontamentos --
-- O painel único da semana: uma linha por indicador por ciclo.
--
-- `realizado_auto` guarda o que a fonte automática devolveu, SEPARADO de
-- `realizado`. Parece redundância e não é: quando a fonte muda de valor depois
-- da reunião (o ERP reprocessa, uma nota entra atrasada), a pergunta "o que
-- estava na tela quando decidimos" continua respondível. Sem os dois campos, a
-- decisão da semana passada passa a ser julgada por um número que ninguém viu.
--
-- `status` é o semáforo do gerente (verde/amarelo/vermelho). GRAVADO, e não
-- derivado de meta × realizado, porque o gerente pode estar 3% abaixo da meta
-- com o mês inteiro pela frente (amarelo) ou 3% abaixo com o mês fechado
-- (vermelho) -- o julgamento é dele, e é o que ele leva para a sala.
CREATE TABLE IF NOT EXISTS ges_apontamentos(
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ciclo_id        integer NOT NULL REFERENCES ges_ciclos(id) ON DELETE CASCADE,
    indicador_id    integer NOT NULL REFERENCES ges_indicadores(id) ON DELETE CASCADE,
    meta            numeric(16,4),
    realizado       numeric(16,4),
    realizado_auto  numeric(16,4),
    status          text    NOT NULL DEFAULT '',
    desvio          text    NOT NULL DEFAULT '',
    acao_id         integer REFERENCES ges_acoes(id) ON DELETE SET NULL,
    prioridade      integer,
    preenchido_por  text    NOT NULL DEFAULT '',
    preenchido_em   text    NOT NULL DEFAULT '',
    CONSTRAINT ges_apont_uk UNIQUE (ciclo_id, indicador_id),
    CONSTRAINT ges_apont_status_ck
        CHECK (status IN ('', 'verde', 'amarelo', 'vermelho')),
    CONSTRAINT ges_apont_prio_ck CHECK (prioridade IS NULL OR prioridade BETWEEN 1 AND 3)
);

-- O UNIQUE PARCIAL é o que faz "3 prioridades" ser regra do banco, e não
-- promessa da tela: a saída obrigatória da reunião são três entregas críticas,
-- e uma quarta entrando em silêncio é como a lista deixa de significar
-- prioridade. `WHERE prioridade IS NOT NULL` porque a maioria das linhas não é
-- prioridade e NULL não colidiria de qualquer forma.
CREATE UNIQUE INDEX IF NOT EXISTS ux_ges_apont_prio
    ON ges_apontamentos(ciclo_id, prioridade)
    WHERE prioridade IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_ges_apont_ciclo ON ges_apontamentos(ciclo_id);
CREATE INDEX IF NOT EXISTS ix_ges_apont_acao  ON ges_apontamentos(acao_id);

COMMENT ON COLUMN ges_apontamentos.realizado_auto IS
    'O que a fonte automática devolveu na hora do apontamento. Guardado à parte
     de `realizado` para a pergunta "o que estava na tela quando decidimos"
     sobreviver a um reprocessamento do ERP.';
COMMENT ON COLUMN ges_apontamentos.acao_id IS
    'A ação que responde a este desvio -- uma `ges_acoes`, a mesma tabela do
     plano de ação. Desvio amarelo ou vermelho sem ação aqui é o que impede o
     ciclo de fechar.';
COMMENT ON COLUMN ges_apontamentos.status IS
    'Semáforo do gerente, gravado e não derivado: 3% abaixo da meta no dia 5 e
     no dia 30 são a mesma conta e julgamentos diferentes.';


-- ------------------------------------------------------------------ seed --
-- As quatro gerências de hoje. `ON CONFLICT DO NOTHING` porque migration roda
-- de novo em banco de teste e em restauração, e semear duas vezes duplicaria.
INSERT INTO ges_gerencias(chave, nome, ordem) VALUES
    ('comercial',  'Comercial',        1),
    ('operacao',   'Operação',         2),
    ('manutencao', 'Manutenção',       3),
    ('rh',         'Recursos Humanos', 4)
ON CONFLICT (chave) DO NOTHING;

-- ------------------------------------------------------------ indicadores --
-- DOIS POR GERÊNCIA, todos AUTOMÁTICOS, para o ritual poder rodar na primeira
-- semana sem ninguém cadastrar nada. É semente, não catálogo: a lista real é
-- da empresa e se edita na tela, e é por isso que indicador é cadastro e não
-- código. As metas nascem VAZIAS de propósito — meta é decisão de quem
-- responde pelo número, e semear um valor plausível faria a primeira reunião
-- discutir uma meta que ninguém combinou.
--
-- A `fonte` de cada um existe em `api.gestao.ritual.FONTES`, e há teste que
-- confere os dois lados: chave inválida aqui não daria erro nenhum -- o
-- indicador entraria como automático e ficaria vazio para sempre.
INSERT INTO ges_indicadores(gerencia_id, nome, unidade, direcao, fonte, casas,
                            ordem, criado_em)
SELECT g.id, v.nome, v.unidade, v.direcao, v.fonte, v.casas, v.ordem, ''
  FROM (VALUES
    ('comercial',  'Receita faturada no mês',        'R$',        'maior_melhor', 'receita_faturada_mes', 0, 1),
    ('comercial',  'Contas a receber vencidas',      'R$',        'menor_melhor', 'receber_vencido',      0, 2),
    ('operacao',   'Retorno vazio',                  '%',         'menor_melhor', 'retorno_vazio',        1, 1),
    ('operacao',   'Consumo — km por litro',         'km/l',      'maior_melhor', 'diesel_km',            2, 2),
    ('manutencao', 'Ordens de serviço abertas',      'OS',        'menor_melhor', 'os_abertas',           0, 1),
    ('manutencao', 'Custo de manutenção no mês',     'R$',        'menor_melhor', 'manutencao_mes',       0, 2),
    ('rh',         'Férias vencidas sem agendamento','pessoas',   'menor_melhor', 'ferias_sem_agenda',    0, 1),
    ('rh',         'CNH vencendo no prazo',          'motoristas','menor_melhor', 'cnh_vence_prazo',      0, 2)
  ) AS v(ger, nome, unidade, direcao, fonte, casas, ordem)
  JOIN ges_gerencias g ON g.chave = v.ger
 WHERE NOT EXISTS (SELECT 1 FROM ges_indicadores i
                    WHERE i.gerencia_id = g.id AND i.nome = v.nome);

