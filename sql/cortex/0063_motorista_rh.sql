-- 0063 · O canal entre o RH e o motorista.
--
-- ==========================================================================
-- ISTO CONTRARIA O ESCOPO ESCRITO, E A CONTRARIEDADE ESTÁ PAGA AQUI
-- ==========================================================================
-- `docs/APP_MOTORISTA.md` §10 põe **chat** na lista do que fica de fora, com
-- uma razão que continua boa: "a casa já tem WhatsApp; um segundo canal de
-- conversa é um canal que ninguém lê e uma expectativa de resposta que ninguém
-- atende". Quem opera pediu o canal mesmo assim, em 07/09/2026, e a decisão é
-- dele — mas a razão não foi ignorada, foi ENDEREÇADA no desenho:
--
--   **isto não é conversa, é FILA COM DONO, ASSUNTO E ESTADO.**
--
-- É a mesma forma dos chamados do Suporte (`sup_chamados`, 0037), que já
-- funciona na casa há tempo, e cada peça dela existe para matar uma das duas
-- falhas que o escopo previa:
--
-- | O escopo temia | O que impede aqui |
-- |---|---|
-- | "ninguém lê" | `visto_rh_em` / `visto_motorista_em` — a caixa do RH ORDENA por quem espera há mais tempo, e a Saúde do Servidor mede a fila parada |
-- | "expectativa que ninguém atende" | `assunto` de LISTA FECHADA + `status` + `atribuido_id`: toda conversa tem dono e estado, e "aberta há N dias" é um número, não uma sensação |
--
-- **POR QUE NÃO REUSAR `sup_chamados`.** Ele é chaveado em `usuarios(id)`, e o
-- motorista não é uma linha em `usuarios` — é a decisão inteira do 0057, e ela
-- não se desfaz por conveniência de tabela. Enfiar o motorista lá exigiria as
-- ~300 contas de painel que o 0057 recusa por escrito.
--
-- **POR QUE NÃO REUSAR O WHATSAPP QUE JÁ EXISTE.** Porque WhatsApp não tem
-- estado: "mandei no zap" não responde "quem está atendendo", "desde quando" e
-- "acabou?". O WhatsApp continua sendo o AVISO ("você tem resposta do RH"); o
-- que tem estado mora aqui.

-- --------------------------------------------------------------- o assunto
--
-- LISTA FECHADA, EM TABELA E NÃO EM CONSTANTE DE CÓDIGO. A diferença importa:
-- o RH vai querer acrescentar assunto (e desligar um que não usa) sem esperar
-- entrega de software, e assunto que só existe no Python obriga um deploy para
-- cada palavra nova.
--
-- `quem_abre` é o que faz a lista ter dois lados sem ter duas tabelas:
-- 'motorista' aparece no app, 'rh' aparece no painel, 'ambos' nos dois.
--
-- `ativo = false` DESLIGA sem apagar: conversa antiga continua apontando para
-- o assunto dela (é FK), e apagar a linha levaria junto o histórico. Mesma
-- escolha do `ativo` de `prem_eixos`.
CREATE TABLE IF NOT EXISTS mot_assuntos(
    chave      text PRIMARY KEY,
    rotulo     text NOT NULL,
    -- O que o motorista lê ANTES de escrever. É este texto que evita metade
    -- dos pedidos: "seu contracheque está no app do Globus" resolve sem fila.
    ajuda      text NOT NULL DEFAULT '',
    quem_abre  text NOT NULL DEFAULT 'motorista'
               CHECK (quem_abre IN ('motorista','rh','ambos')),
    -- Comunicado do RH PEDE CIÊNCIA: o motorista aperta "li e entendi" e isso
    -- vira mensagem de sistema com data. É o que transforma "mandamos o
    -- comunicado" em prova de que ele leu.
    pede_ciencia boolean NOT NULL DEFAULT false,
    ordem      integer NOT NULL DEFAULT 100,
    ativo      boolean NOT NULL DEFAULT true
);

-- Os assuntos NASCEM aqui, e não numa tela de cadastro que ninguém preencheu:
-- canal vazio no primeiro dia é canal que ninguém abre no segundo. O RH ajusta
-- depois. `ON CONFLICT DO NOTHING` porque a migration roda em banco que já
-- pode ter a lista editada — reescrever apagaria o ajuste de quem opera.
INSERT INTO mot_assuntos(chave, rotulo, ajuda, quem_abre, pede_ciencia, ordem)
VALUES
 ('ferias',       'Férias',
  'Para pedir, adiantar ou tirar dúvida sobre o seu período de férias.',
  'motorista', false, 10),
 ('contracheque', 'Contracheque e descontos',
  'Dúvida sobre valor, desconto ou o holerite de um mês.',
  'motorista', false, 20),
 ('jornada',      'Ponto e jornada',
  'Marcação errada, hora extra, folga ou descanso. Diga o DIA que está errado — '
  'a correção é feita pelo RH, o app não altera nada da sua jornada.',
  'motorista', false, 30),
 ('documento',    'Documento e exame',
  'CNH, exame periódico, curso (MOPP, ANTT) e reciclagem.',
  'ambos', false, 40),
 ('beneficio',    'Benefício',
  'Plano de saúde, vale, cesta e convênio.',
  'motorista', false, 50),
 ('adiantamento', 'Adiantamento e vale',
  'Pedido de adiantamento e dúvida sobre o que já foi pago.',
  'motorista', false, 60),
 ('outro',        'Outro assunto',
  'Quando não for nenhum dos acima. Diga em uma frase do que se trata.',
  'motorista', false, 90),
 ('comunicado',   'Comunicado do RH',
  'Aviso da empresa. Você confirma que leu.',
  'rh', true, 5)
ON CONFLICT (chave) DO NOTHING;

-- ---------------------------------------------------------------- a conversa
--
-- UMA CONVERSA É UM ASSUNTO, e o assunto vem da LISTA FECHADA acima
-- (`mot_assuntos`). Texto livre existe DENTRO dela, nas mensagens — o que não existe é
-- conversa sem assunto, que é precisamente o que vira caixa que ninguém
-- esvazia. Quem escolhe o assunto é quem abre, e é ele que decide o dono no RH.
CREATE TABLE IF NOT EXISTS mot_conversas(
    id                bigserial PRIMARY KEY,
    motorista_codigo  text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                           ON DELETE CASCADE,
    assunto           text NOT NULL REFERENCES mot_assuntos(chave),
    -- Quem ABRIU. Não é o mesmo que "de quem é a conversa": ela é sempre de UM
    -- motorista, mas quem puxou pode ter sido o RH (comunicado, pedido de
    -- documento) ou ele (férias, contracheque).
    origem            text NOT NULL CHECK (origem IN ('motorista','rh')),
    titulo            text NOT NULL DEFAULT '',
    status            text NOT NULL DEFAULT 'aberta'
                      CHECK (status IN ('aberta','em_atendimento',
                                        'aguardando_motorista','resolvida')),
    status_em         timestamptz NOT NULL DEFAULT now(),
    status_por        text NOT NULL DEFAULT '',
    -- O DONO NO RH. `usuarios(id)` porque deste lado quem atende É gente do
    -- painel; `ON DELETE SET NULL` porque desligar quem atendeu não pode
    -- apagar a conversa — a trilha do que foi dito é o que vale numa
    -- discussão trabalhista.
    atribuido_id      integer REFERENCES usuarios(id) ON DELETE SET NULL,
    atribuido_nome    text NOT NULL DEFAULT '',
    criada_em         timestamptz NOT NULL DEFAULT now(),
    -- Instante da ÚLTIMA mensagem. Desnormalizado de propósito, e é a única
    -- coisa desnormalizada aqui: a caixa do RH ordena por ele e a alternativa
    -- seria um `max()` sobre as mensagens em toda abertura de tela. Ele é
    -- reescrito por quem insere a mensagem, no mesmo lugar, e nunca somado —
    -- não é total, é carimbo.
    ultima_em         timestamptz NOT NULL DEFAULT now(),
    -- "VISTO POR ÚLTIMO", UM POR LADO. É daqui que sai o não-lido dos dois
    -- lados, e a escolha é a mesma de `aud_sessoes` e `mot_sessoes`: linha
    -- VIVA com carimbo, não um booleano por mensagem. Booleano por mensagem
    -- obrigaria a escrever N linhas para marcar uma conversa como lida.
    visto_motorista_em timestamptz,
    visto_rh_em        timestamptz
);

CREATE INDEX IF NOT EXISTS mot_conversas_mot
    ON mot_conversas(motorista_codigo, ultima_em DESC);
CREATE INDEX IF NOT EXISTS mot_conversas_fila
    ON mot_conversas(ultima_em) WHERE status <> 'resolvida';

COMMENT ON COLUMN mot_conversas.status IS
    'aberta = ninguém pegou · em_atendimento = alguém do RH pegou ·
     aguardando_motorista = o RH respondeu e espera ele · resolvida = acabou.
     ESTADO É CAMPO, NUNCA AUSÊNCIA DE DATA: "não respondida" derivado de
     `resposta_em IS NULL` mente no dia em que alguém responde por fora.';

COMMENT ON COLUMN mot_conversas.ultima_em IS
    'Carimbo da última mensagem, para a caixa do RH ordenar por quem espera há
     mais tempo. Reescrito por quem insere a mensagem. Não é total e não se
     soma — total desnormalizado é que discorda das próprias linhas.';

-- ------------------------------------------------------------- as mensagens
--
-- APPEND-ONLY, e isso não é zelo: o que foi dito entre a empresa e o
-- trabalhador é prova, e prova que se edita não é prova. Correção se faz com
-- mensagem NOVA, como no `audit_log` e no `sup_mensagens`.
--
-- `papel = 'sistema'` são os eventos (abertura, mudança de status, ciência):
-- eles moram na MESMA linha do tempo do texto humano porque é assim que a
-- conversa se lê depois — "ele pediu, fulano pegou, respondeu, ele deu
-- ciência" numa coluna só, sem juntar duas tabelas na cabeça de quem lê.
CREATE TABLE IF NOT EXISTS mot_mensagens(
    id           bigserial PRIMARY KEY,
    conversa_id  bigint NOT NULL REFERENCES mot_conversas(id) ON DELETE CASCADE,
    papel        text NOT NULL CHECK (papel IN ('motorista','rh','sistema')),
    -- Só quando `papel='rh'`. O motorista não tem id de usuário (0057), e o
    -- nome dele já está na conversa.
    autor_id     integer REFERENCES usuarios(id) ON DELETE SET NULL,
    autor_nome   text NOT NULL DEFAULT '',
    texto        text NOT NULL DEFAULT '',
    -- '' = texto humano. 'abertura' | 'status' | 'atribuicao' | 'ciencia'.
    evento       text NOT NULL DEFAULT '',
    criada_em    timestamptz NOT NULL DEFAULT now(),
    CHECK (texto <> '' OR evento <> '')
);

CREATE INDEX IF NOT EXISTS mot_mensagens_conversa
    ON mot_mensagens(conversa_id, id);

COMMENT ON TABLE mot_mensagens IS
    'Append-only: o que foi dito entre a empresa e o trabalhador é prova, e
     prova que se edita não é prova. Correção é mensagem nova.';
