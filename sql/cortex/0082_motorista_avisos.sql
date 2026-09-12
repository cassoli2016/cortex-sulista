-- 0082 · App do motorista — os AVISOS: o que é novo para ele, no app e no celular.
--
-- Pedido de quem opera (11/09/2026): "notificações quando tiver algo novo
-- relacionado ao motorista ou recado do RH". Quatro tipos: recado do RH (a
-- conversa e o mural), multa nova, registro novo no ERP e viagem nova.
--
-- A LISTA É A FONTE, O PUSH É O MENSAGEIRO. Todo aviso nasce numa linha de
-- `mot_avisos`, que o app mostra na aba Avisos com "não lido"; o push só
-- entrega a quem ligou a notificação. Quem não ligou — ou está num iPhone sem o
-- app na Tela de Início, onde o navegador não entrega push — vê o mesmo aviso
-- ao abrir o app. Push que falha não perde nada.
--
-- O CÓDIGO DO ERP (para pessoa física, o CPF) é a chave interna, como em todo
-- `mot_*`, e não sai do servidor: nem no payload, nem no push.

-- Um aviso para UM motorista. A identidade é (motorista, tipo, ref): o mesmo
-- recado registrado duas vezes — a rota repetida, a varredura que passa de
-- novo — é UM aviso. `detalhe` é o que aparece DENTRO do app; o push não o leva.
CREATE TABLE IF NOT EXISTS mot_avisos(
    id               bigserial PRIMARY KEY,
    motorista_codigo text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                     ON DELETE CASCADE,
    tipo             text NOT NULL
                     CHECK (tipo IN ('rh','mural','multa','registro','viagem')),
    ref              text NOT NULL,
    detalhe          text NOT NULL DEFAULT '',
    criado_em        timestamptz NOT NULL DEFAULT now(),
    lido_em          timestamptz,
    -- a entrega do push: quando foi tentada e em quantos aparelhos chegou.
    -- NULL = ainda não tentada. Aviso de quem não tem aparelho inscrito é
    -- carimbado com 0 e não fica pendente para sempre.
    push_em          timestamptz,
    entregues        integer NOT NULL DEFAULT 0,
    UNIQUE (motorista_codigo, tipo, ref)
);
CREATE INDEX IF NOT EXISTS ix_mot_avisos_motorista
    ON mot_avisos (motorista_codigo, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_mot_avisos_pendentes
    ON mot_avisos (id) WHERE push_em IS NULL;

-- O que a VARREDURA já viu (multa, registro, viagem), por motorista. É contra
-- isto que "novo" se decide — e não contra a data, que no ERP é de dia inteiro
-- e se preenche com atraso.
CREATE TABLE IF NOT EXISTS mot_avisos_vistos(
    motorista_codigo text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                     ON DELETE CASCADE,
    tipo             text NOT NULL,
    ref              text NOT NULL,
    visto_em         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (motorista_codigo, tipo, ref)
);

-- A PRIMEIRA PASSADA NÃO AVISA. Sem esta marca, o primeiro dia do sistema — e
-- o primeiro dia de cada motorista novo — seria uma avalanche de "novidades" de
-- duas semanas atrás, e o motorista aprenderia no primeiro dia a ignorar o aviso.
CREATE TABLE IF NOT EXISTS mot_avisos_marca(
    motorista_codigo text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                     ON DELETE CASCADE,
    tipo             text NOT NULL,
    iniciado_em      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (motorista_codigo, tipo)
);

-- Os aparelhos que ligaram a notificação. SEPARADA de `push_subs` (a do
-- painel): o dono ali é um e-mail de usuário, aqui é um motorista, e um mesmo
-- endereço de push trocando de dono entre as duas tabelas mandaria o aviso de
-- um motorista para o celular de um usuário do painel.
CREATE TABLE IF NOT EXISTS mot_push_subs(
    endpoint         text PRIMARY KEY,
    p256dh           text NOT NULL,
    auth             text NOT NULL,
    motorista_codigo text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                     ON DELETE CASCADE,
    criado_em        timestamptz NOT NULL DEFAULT now(),
    ultimo_ok_em     timestamptz,
    falhas           integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_mot_push_subs_motorista
    ON mot_push_subs (motorista_codigo);

-- O estado da varredura, para a Saúde do Servidor: uma linha só. Sem ela, a
-- varredura parada não tem sintoma nenhum — o motorista só deixa de ser avisado.
CREATE TABLE IF NOT EXISTS mot_avisos_varredura(
    id        smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    rodou_em  timestamptz,
    erro      text,
    novos     integer NOT NULL DEFAULT 0
);
