-- Suporte — chamados abertos pelo botão "Reportar", com ciclo de vida, conversa
-- entre quem abriu e o time, avisos por canal e espelho opcional na issue do
-- GitHub. Escrita do CÓRTEX, banco local.
--
-- O QUE EXISTIA: o report virava issue no repositório privado e sumia — quem
-- abriu não via status, não recebia resposta, e sem GITHUB_TOKEN o botão nem
-- aparecia. Aqui o CHAMADO é o registro canônico (local-first); a issue é
-- espelho.
--
-- CINCO DECISÕES:
--
-- 1. STATUS É GRAVADO PORQUE É DECISÃO HUMANA (assumir, perguntar, resolver,
--    encerrar), com quem e quando. O que envelhece sozinho NÃO tem coluna:
--    "sem resposta há N h", "SLA estourado", "esperando quem", "resolvido sem
--    confirmação há N dias", "respostas novas" e o tempo até a primeira
--    resposta são calculados na leitura, de `criado_em`, `status_em`, das
--    marcas de leitura e das mensagens. Nenhuma rotina vira status: no dia em
--    que ela não rodasse a tela mentiria (regra de `ges_acoes` e `crm_*`).
--
-- 2. A CONVERSA É APPEND-ONLY. Editar a resposta do suporte depois de lida
--    reescreveria a prova do que foi dito. Toda transição de status gera uma
--    mensagem de sistema NA MESMA transação: a conversa conta a história inteira.
--    `interna = 1` é nota do atendente — vai à issue, nunca ao usuário.
--
-- 3. ANEXO MORA NO BANCO. Não é cache reconstruível nem segredo (a regra do
--    "fora do banco" é para o que se reconstrói) e sem GitHub o chamado tem
--    de existir inteiro. `bytea` em tabela SEPARADA, como `usuario_fotos`: a
--    conversa nunca arrasta megabytes num SELECT.
--
-- 4. A TRILHA DE AVISOS GUARDA AS TRÊS RESPOSTAS (CLAUDE.md §7): enviado /
--    sem_canal (calou porque não há: sem telefone, canal não marcado, sem
--    inscrição de push, SMTP fora, já lido) / recusado (tentou e o motivo:
--    freio, janela, modelo desligado, GitHub 401). `adiado` é o WhatsApp fora
--    da janela, que sai na próxima passagem. Destinatário SEMPRE mascarado: o
--    repo é público e a trilha aparece na tela do atendente.
--
-- 5. O PAR (usuario_id, nome) SE REPETE, de propósito — convenção da casa
--    desde `ges_acoes`: o nome sobrevive ao ON DELETE SET NULL.

CREATE TABLE IF NOT EXISTS sup_chamados (
    id                 serial PRIMARY KEY,
    ano                integer     NOT NULL,
    sequencia          integer     NOT NULL,
    codigo             text        NOT NULL UNIQUE,          -- SUP-2026-0007
    usuario_id         integer     REFERENCES usuarios(id) ON DELETE SET NULL,
    usuario_nome       text        NOT NULL DEFAULT '',
    tipo               text        NOT NULL CHECK (tipo IN ('bug','melhoria','duvida')),
    gravidade          text        NOT NULL CHECK (gravidade IN ('alta','media','baixa')),
    titulo             text        NOT NULL,
    descricao          text        NOT NULL,
    tela               text        NOT NULL DEFAULT '',
    contexto           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status             text        NOT NULL DEFAULT 'aberto'
                       CHECK (status IN ('aberto','em_atendimento','aguardando_usuario','resolvido','fechado')),
    status_em          timestamptz NOT NULL DEFAULT now(),
    status_por         text        NOT NULL DEFAULT '',
    atribuido_id       integer     REFERENCES usuarios(id) ON DELETE SET NULL,
    atribuido_nome     text        NOT NULL DEFAULT '',
    avisar_email       integer     NOT NULL DEFAULT 1 CHECK (avisar_email IN (0,1)),
    avisar_whatsapp    integer     NOT NULL DEFAULT 0 CHECK (avisar_whatsapp IN (0,1)),
    motivo_fechamento  text        NOT NULL DEFAULT '',
    avaliacao          integer     CHECK (avaliacao IS NULL OR avaliacao BETWEEN 1 AND 5),
    avaliacao_texto    text        NOT NULL DEFAULT '',
    github_numero      integer,
    github_url         text        NOT NULL DEFAULT '',
    github_erro        text        NOT NULL DEFAULT '',
    github_sync_em     timestamptz,
    lido_usuario_em    timestamptz,
    lido_suporte_em    timestamptz,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    atualizado_em      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ano, sequencia)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sup_chamados_github
    ON sup_chamados (github_numero) WHERE github_numero IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_sup_chamados_usuario ON sup_chamados (usuario_id, status);
CREATE INDEX IF NOT EXISTS ix_sup_chamados_status  ON sup_chamados (status, atualizado_em DESC);

CREATE TABLE IF NOT EXISTS sup_mensagens (
    id                 serial PRIMARY KEY,
    chamado_id         integer     NOT NULL REFERENCES sup_chamados(id) ON DELETE CASCADE,
    papel              text        NOT NULL CHECK (papel IN ('usuario','suporte','sistema')),
    autor_id           integer     REFERENCES usuarios(id) ON DELETE SET NULL,
    autor_nome         text        NOT NULL DEFAULT '',
    texto              text        NOT NULL DEFAULT '',
    evento             text        NOT NULL DEFAULT '',   -- '' texto humano · status · atribuicao · reaberto · avaliacao · github
    status_de          text        NOT NULL DEFAULT '',
    status_para        text        NOT NULL DEFAULT '',
    interna            integer     NOT NULL DEFAULT 0 CHECK (interna IN (0,1)),
    origem             text        NOT NULL DEFAULT 'painel' CHECK (origem IN ('painel','github','sistema')),
    github_comment_id  bigint,
    espelhada_em       timestamptz,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    CHECK (interna = 0 OR papel = 'suporte')
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sup_mensagens_github
    ON sup_mensagens (github_comment_id) WHERE github_comment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_sup_mensagens_chamado ON sup_mensagens (chamado_id, id);

CREATE TABLE IF NOT EXISTS sup_anexos (
    id            serial PRIMARY KEY,
    chamado_id    integer     NOT NULL REFERENCES sup_chamados(id) ON DELETE CASCADE,
    mensagem_id   integer     REFERENCES sup_mensagens(id) ON DELETE SET NULL,   -- NULL = anexo do relato
    nome          text        NOT NULL,       -- gerado: só a extensão do navegador sobrevive
    mime          text        NOT NULL,
    tamanho       integer     NOT NULL,
    bytes         bytea       NOT NULL,
    github_url    text        NOT NULL DEFAULT '',
    criado_em     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sup_anexos_chamado ON sup_anexos (chamado_id);

CREATE TABLE IF NOT EXISTS sup_avisos (
    id            serial PRIMARY KEY,
    chamado_id    integer     NOT NULL REFERENCES sup_chamados(id) ON DELETE CASCADE,
    mensagem_id   integer     REFERENCES sup_mensagens(id) ON DELETE SET NULL,
    canal         text        NOT NULL CHECK (canal IN ('email','whatsapp','push','github')),
    lado          text        NOT NULL CHECK (lado IN ('usuario','suporte')),
    evento        text        NOT NULL DEFAULT '',
    destinatario  text        NOT NULL DEFAULT '',    -- SEMPRE mascarado
    resultado     text        NOT NULL CHECK (resultado IN ('enviado','sem_canal','recusado','adiado')),
    detalhe       text        NOT NULL DEFAULT '',
    trilha_id     integer,                              -- id em zap_envios / correio_envios, sem FK
    tentar_apos   timestamptz,                          -- só adiado
    criado_em     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sup_avisos_chamado ON sup_avisos (chamado_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_sup_avisos_adiados ON sup_avisos (tentar_apos) WHERE resultado = 'adiado';

-- Regras editáveis pelo administrador: chave ausente = padrão do código
-- (`api/suporte/comum.py`), como a `config` da auth. Nenhum destinatário
-- nasce aqui (repo público): e-mail do time começa vazio.
CREATE TABLE IF NOT EXISTS sup_config (
    chave          text PRIMARY KEY,
    valor          text NOT NULL,
    atualizado_em  timestamptz NOT NULL DEFAULT now(),
    atualizado_por text NOT NULL DEFAULT ''
);

-- Modelo do aviso por WhatsApp (molde 0031): texto revisado uma vez, editável
-- em Gestão › WhatsApp; `limite_dia` próprio para o aviso interno nunca comer
-- a cota de cobrança do número. Sem título nem texto do chamado: sai por
-- fornecedor externo.
INSERT INTO zap_modelos (chave, nome, contexto, descricao, corpo, ativo, limite_dia,
                         criado_em, criado_por, atualizado_em, atualizado_por)
VALUES (
  'suporte-aviso',
  'Suporte — aviso de chamado',
  'suporte',
  'Aviso automático a quem abriu um chamado no CÓRTEX quando o suporte responde '
  'ou muda o status. Não leva o texto da resposta: só o número, o que mudou e o link.',
  E'Olá, {{nome}}. Seu chamado *{{numero}}* no CÓRTEX tem novidade: {{evento}}.\nVeja e responda pelo painel: {{link}}',
  1, 20, now(), 'sistema', now(), 'sistema')
ON CONFLICT (chave) DO NOTHING;
