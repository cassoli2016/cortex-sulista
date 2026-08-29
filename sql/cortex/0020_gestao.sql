-- Gestão: atas de reunião e planos de ação (5W2H) com acompanhamento.
--
-- As tabelas `ges_atas`/`ges_acoes` existiam desde o commit inicial em
-- `sql/blocks/0003_financeiro_gestao.sql` — o schema da ARQUITETURA, que nunca
-- rodou. Este é o schema de verdade, e ele diverge do antigo em quatro pontos
-- que valem a explicação, porque cada um custou uma decisão:
--
-- 1. `quem` era `text NOT NULL`. Aqui o responsável é CHAVE ESTRANGEIRA para
--    `usuarios`, com `responsavel_nome` como alternativa. O motivo não é
--    normalização: é que só com o id dá para montar "minhas ações", mandar a
--    cobrança para o e-mail certo (`usuarios.email`) e sobreviver a alguém
--    mudar de nome. Mas nem todo responsável tem login — motorista, contador
--    externo, fornecedor — e recusar esses obrigaria a inventar usuário falso
--    só para atribuir tarefa. Daí os dois campos, com a regra "um ou outro,
--    nunca nenhum" garantida por CHECK.
--
-- 2. `status` incluía 'atrasada'. AQUI NÃO EXISTE ESSE STATUS, e é de
--    propósito: atraso é `prazo < hoje AND status IN ('aberta','em_andamento')`
--    — derivado, calculado na leitura. Status de atraso GRAVADO precisa de
--    alguém para virar, e no dia em que a rotina não roda a tela mente dizendo
--    que está tudo em dia. É a mesma classe de erro do marcador de manutenção
--    preventiva que parou em 77.534 km enquanto o odômetro ia a 531.970.
--
-- 3. Apagar a ata NÃO apaga as ações (`ON DELETE SET NULL`). O compromisso
--    assumido numa reunião não deixa de existir porque alguém arrumou o
--    registro dela; a ação continua viva, órfã e visível.
--
-- 4. Entra `ges_andamentos`, que não existia. Sem histórico, "em andamento"
--    é uma palavra sem data: ninguém sabe se a ação andou ontem ou há dois
--    meses, e o acompanhamento vira reunião de perguntar o óbvio.


-- ---------------------------------------------------------------- reuniões --
-- `codigo` é a referência HUMANA ("ATA-2026-007"), porque é assim que ata é
-- citada em e-mail e em outra ata — "a decisão da #43" não sobrevive a uma
-- restauração de backup que reordene ids. O par (ano, sequencia) tem UNIQUE:
-- num volume de poucas atas por mês a corrida é improvável, e se acontecer o
-- banco recusa em vez de gravar duas ATA-2026-007.
CREATE TABLE IF NOT EXISTS ges_reunioes(
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ano           integer NOT NULL,
    sequencia     integer NOT NULL,
    codigo        text    NOT NULL,
    titulo        text    NOT NULL,
    tipo          text    NOT NULL DEFAULT 'outra',
    area          text    NOT NULL DEFAULT '',
    data          date    NOT NULL,
    hora_inicio   text    NOT NULL DEFAULT '',
    hora_fim      text    NOT NULL DEFAULT '',
    local         text    NOT NULL DEFAULT '',
    pauta         text    NOT NULL DEFAULT '',
    discussao     text    NOT NULL DEFAULT '',
    decisoes      text    NOT NULL DEFAULT '',
    observacoes   text    NOT NULL DEFAULT '',
    status        text    NOT NULL DEFAULT 'rascunho',
    criado_por    text    NOT NULL DEFAULT '',
    criado_em     text    NOT NULL DEFAULT '',
    alterado_por  text    NOT NULL DEFAULT '',
    alterado_em   text    NOT NULL DEFAULT '',
    CONSTRAINT ges_reunioes_seq_uk UNIQUE (ano, sequencia),
    CONSTRAINT ges_reunioes_status_ck
        CHECK (status IN ('rascunho', 'publicada')),
    CONSTRAINT ges_reunioes_tipo_ck
        CHECK (tipo IN ('diretoria', 'area', 'projeto', 'comite',
                        'cliente', 'outra'))
);

CREATE INDEX IF NOT EXISTS ix_ges_reunioes_data ON ges_reunioes(data DESC);

COMMENT ON TABLE ges_reunioes IS
    'Atas de reunião. Nascem como rascunho: ata publicada é documento que
     outras pessoas passam a citar, e publicar não pode ser o efeito colateral
     de abrir o formulário.';
COMMENT ON COLUMN ges_reunioes.codigo IS
    'Referência humana ATA-<ano>-<sequência>. É por ela que a ata é citada
     fora do sistema, e por isso não pode ser o id — que muda em restauração.';
COMMENT ON COLUMN ges_reunioes.discussao IS
    'O que foi debatido. Separado de `decisoes` porque relatar discussão como
     decisão é o defeito clássico de ata: ninguém sabe o que foi combinado.';


-- ----------------------------------------------------------- participantes --
-- Mesma dupla id/nome do responsável de ação, e pelo mesmo motivo: participante
-- externo (cliente, auditor, candidato) não tem login e precisa constar.
-- `presente` distingue CONVOCADO de PRESENTE — ausência em reunião de decisão
-- é informação, e uma lista que só guarda quem apareceu apaga a pergunta
-- "quem faltou?".
CREATE TABLE IF NOT EXISTS ges_participantes(
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reuniao_id  integer NOT NULL REFERENCES ges_reunioes(id) ON DELETE CASCADE,
    usuario_id  integer REFERENCES usuarios(id) ON DELETE SET NULL,
    nome        text    NOT NULL DEFAULT '',
    papel       text    NOT NULL DEFAULT '',
    presente    integer NOT NULL DEFAULT 1,
    CONSTRAINT ges_participantes_quem_ck
        CHECK (usuario_id IS NOT NULL OR nome <> '')
);

CREATE INDEX IF NOT EXISTS ix_ges_part_reuniao ON ges_participantes(reuniao_id);
CREATE INDEX IF NOT EXISTS ix_ges_part_usuario ON ges_participantes(usuario_id);

COMMENT ON COLUMN ges_participantes.usuario_id IS
    'ON DELETE SET NULL e não CASCADE: excluir um usuário não pode apagar o
     registro de que ele esteve na reunião. O nome fica em `nome`.';


-- ------------------------------------------------------------------ ações --
-- O 5W2H inteiro, com os nomes do método nos comentários e nomes de coluna em
-- português corrente — quem preenche é gestor, não analista.
--
-- `prioridade` e `status` são texto com CHECK, não tabela de domínio: são
-- listas fechadas de cinco itens que mudam de década em década, e uma tabela
-- satélite aqui só acrescentaria um JOIN a toda consulta.
--
-- `percentual` existe junto de `status` porque os dois respondem perguntas
-- diferentes: status é o compromisso ("isto ainda está de pé?"), percentual é
-- o avanço. Ação 90% concluída e ação recém-começada têm o mesmo status.
CREATE TABLE IF NOT EXISTS ges_acoes(
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reuniao_id       integer REFERENCES ges_reunioes(id) ON DELETE SET NULL,
    o_que            text    NOT NULL,                    -- What
    por_que          text    NOT NULL DEFAULT '',         -- Why
    como             text    NOT NULL DEFAULT '',         -- How
    onde             text    NOT NULL DEFAULT '',         -- Where
    quanto           numeric(14,2),                       -- How much
    responsavel_id   integer REFERENCES usuarios(id) ON DELETE SET NULL,
    responsavel_nome text    NOT NULL DEFAULT '',         -- Who (sem login)
    prazo            date    NOT NULL,                    -- When
    area             text    NOT NULL DEFAULT '',
    prioridade       text    NOT NULL DEFAULT 'media',
    status           text    NOT NULL DEFAULT 'aberta',
    percentual       integer NOT NULL DEFAULT 0,
    concluida_em     text,
    criado_por       text    NOT NULL DEFAULT '',
    criado_em        text    NOT NULL DEFAULT '',
    alterado_por     text    NOT NULL DEFAULT '',
    alterado_em      text    NOT NULL DEFAULT '',
    CONSTRAINT ges_acoes_quem_ck
        CHECK (responsavel_id IS NOT NULL OR responsavel_nome <> ''),
    CONSTRAINT ges_acoes_status_ck
        CHECK (status IN ('aberta', 'em_andamento', 'concluida', 'cancelada')),
    CONSTRAINT ges_acoes_prioridade_ck
        CHECK (prioridade IN ('baixa', 'media', 'alta', 'critica')),
    CONSTRAINT ges_acoes_percentual_ck
        CHECK (percentual BETWEEN 0 AND 100)
);

-- Os três recortes que a tela realmente faz: a fila do responsável, o que
-- vence, e as ações de uma ata.
CREATE INDEX IF NOT EXISTS ix_ges_acoes_resp   ON ges_acoes(responsavel_id, status);
CREATE INDEX IF NOT EXISTS ix_ges_acoes_prazo  ON ges_acoes(prazo);
CREATE INDEX IF NOT EXISTS ix_ges_acoes_reuniao ON ges_acoes(reuniao_id);

COMMENT ON TABLE ges_acoes IS
    'Plano de ação em 5W2H. NÃO existe status "atrasada": atraso é
     prazo < hoje AND status IN (aberta, em_andamento), calculado na leitura.
     Status de atraso gravado depende de alguém virar, e no dia em que a rotina
     falha a tela diz que está tudo em dia.';
COMMENT ON COLUMN ges_acoes.reuniao_id IS
    'ON DELETE SET NULL: apagar a ata não apaga o compromisso assumido nela.';
COMMENT ON COLUMN ges_acoes.concluida_em IS
    'Carimbo de quando virou concluída — é dele que sai o tempo de ciclo. NULL
     enquanto não concluiu; volta a NULL se reabrir.';


-- ------------------------------------------------------------- andamentos --
-- O histórico. É append-only por decisão: andamento que se edita deixa de ser
-- prova de que a ação andou. Quem errou o texto acrescenta outro.
--
-- `status_de`/`status_para` ficam NULOS quando o andamento é só um comentário.
-- Guardar a transição AQUI, e não só o status atual em `ges_acoes`, é o que
-- responde "há quanto tempo isto está parado" sem inventar.
CREATE TABLE IF NOT EXISTS ges_andamentos(
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    acao_id      integer NOT NULL REFERENCES ges_acoes(id) ON DELETE CASCADE,
    ts           text    NOT NULL,
    usuario      text    NOT NULL DEFAULT '',
    texto        text    NOT NULL DEFAULT '',
    status_de    text,
    status_para  text,
    percentual   integer,
    CONSTRAINT ges_andamentos_pct_ck
        CHECK (percentual IS NULL OR percentual BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS ix_ges_and_acao ON ges_andamentos(acao_id, ts DESC);

COMMENT ON TABLE ges_andamentos IS
    'Histórico da ação, append-only. Andamento editável deixa de ser prova de
     que a ação andou — quem errou o texto acrescenta outro.';
