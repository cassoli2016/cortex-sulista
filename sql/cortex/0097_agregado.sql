-- App do Agregado — identidade, código de entrada e sessão presa ao aparelho.
--
-- A QUARTA PERGUNTA DE ACESSO DESTA CASA. O RBAC responde "que tela você abre"
-- (perfil × tela, 0011_auth.sql); o portal do cliente acrescentou "quais linhas
-- são suas" (0053); o app do motorista, "qual motorista você é" (0057). Aqui a
-- pergunta é "**de quem são estes veículos**" — o dono do agregado vê o que a
-- Sulista paga aos veículos DELE, e nada mais.
--
-- POR QUE UMA IDENTIDADE NOVA, E NÃO O `mot_vinculos` DO MOTORISTA
--
--   1. São pessoas diferentes com papéis diferentes. O motorista dirige; o
--      proprietário recebe. Medido em 16/09/2026: 201 donos para 298 veículos
--      AGR, e o maior deles tem 15 veículos — ninguém dirige 15 caminhões.
--   2. O ESCOPO é outro: lá a chave é a pessoa (`cadastro.codigo` do
--      motorista); aqui é o conjunto de veículos cujo `veiculo.proprietario`
--      aponta para o dono. Enfiar os dois na mesma tabela faria uma sessão de
--      motorista ganhar acesso a acerto por um `if` errado — e a regra da casa
--      é que escopo não se decide com `if`.
--   3. O que cada um pode ver é incompatível. O app do motorista não mostra
--      dinheiro da operação por decisão escrita; este app é, quase inteiro,
--      sobre dinheiro — o do dono.
--
-- O QUE NÃO ENTRA AQUI, E POR QUÊ
--
--   *  O documento do dono NÃO sai do servidor. `proprietario_codigo` é o
--      `cadastro.codigo` do ERP e, para os 80 donos que são pessoa física, ELE
--      É O CPF. Toda saída (token, trilha, payload) usa o `id` opaco — a mesma
--      correção que o app do motorista precisou fazer depois (0058).
--   *  Nada de veículo é guardado aqui. Quais placas são de quem é pergunta do
--      ERP, respondida na leitura: gravar a lista criaria uma segunda verdade
--      que envelhece no dia em que o dono vende um caminhão.

-- ---------------------------------------------------------------- o vínculo
--
-- QUEM É AGREGADO NO APP. Não basta o ERP dizer que a pessoa tem veículo:
-- alguém da casa liga o telefone ao código do proprietário, e é essa linha que
-- dá acesso. Sem ela não há entrada — nem para quem tem o telefone certo.
--
-- `proprietario_codigo` É TEXT, e o cast acontece na ENTRADA: o ERP grava
-- `cadastro.codigo` como `character varying` HOJE, e tabela de terceiro não tem
-- contrato de tipo (a `agrupadorgerencial` trocou `integer` por `varchar` em
-- 02/09/2026 e derrubou cinco telas).
CREATE TABLE IF NOT EXISTS agr_vinculos(
    proprietario_codigo text PRIMARY KEY,
    id                  bigserial UNIQUE,
    telefone            text NOT NULL,
    nome                text NOT NULL DEFAULT '',
    ativo               boolean NOT NULL DEFAULT true,
    criado_em           timestamptz NOT NULL DEFAULT now(),
    criado_por          text NOT NULL DEFAULT '',
    desligado_em        timestamptz,
    desligado_por       text NOT NULL DEFAULT ''
);

-- O telefone NÃO é único. No motorista isso foi medido (5 em 585 dividem o
-- número); aqui o caso é outro e mais comum: o mesmo telefone pode ser o do
-- dono pessoa física E o da empresa dele. Quem entra por um número que serve a
-- mais de um vínculo ESCOLHE quem é, depois de provar o código.
CREATE INDEX IF NOT EXISTS agr_vinculos_fone ON agr_vinculos(telefone)
    WHERE ativo;

COMMENT ON TABLE agr_vinculos IS
    'Quem entra no app do agregado. A chave é o `cadastro.codigo` do ERP, o
     mesmo que `veiculo.proprietario` aponta — é ele que amarra o dono aos
     veículos dele na leitura.';

COMMENT ON COLUMN agr_vinculos.id IS
    'Id OPACO, e é o único que pode sair do servidor (token, trilha, payload).
     O `proprietario_codigo` é CPF para pessoa física (80 dos 201 donos em
     16/09/2026) e fica só na junção interna com o AVA.';

COMMENT ON COLUMN agr_vinculos.telefone IS
    'Telefone NORMALIZADO pelo validador único da casa (api/whatsapp/numeros).
     Vem de `cadastro.celular`/`cadastro.fone`, que já trazem DDI+DDD: todos os
     201 donos de agregado têm telefone no cadastro (medido em 16/09/2026).';

COMMENT ON COLUMN agr_vinculos.ativo IS
    'Falso = desligado, e a sessão dele para de valer na requisição seguinte.
     Agregado que encerra contrato NÃO perde acesso sozinho: é regra de
     desligamento, com gente responsável.';

-- ------------------------------------------------------- o código de entrada
--
-- O CÓDIGO NUNCA É GRAVADO. Só o SHA-256, pela mesma razão do `senha_reset`
-- (0038) e do `mot_codigos` (0057): quem lê a tabela — backup, dump, consulta
-- de diagnóstico — não entra na conta de ninguém.
--
-- A LINHA É A TENTATIVA, não a sessão: nasce quando alguém PEDE um código e
-- morre quando ele é usado ou expira. Por isso `telefone` e não
-- `proprietario_codigo`: no instante do pedido ainda não se sabe (nem se pode
-- revelar) se aquele número pertence a alguém.
CREATE TABLE IF NOT EXISTS agr_codigos(
    id          bigserial PRIMARY KEY,
    telefone    text NOT NULL,
    codigo_hash text NOT NULL,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    expira_em   timestamptz NOT NULL,
    tentativas  int NOT NULL DEFAULT 0,
    usado_em    timestamptz,
    ip          text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS agr_codigos_fone ON agr_codigos(telefone, criado_em DESC);

COMMENT ON TABLE agr_codigos IS
    'Códigos de entrada em voo. Guarda o SHA-256, nunca o código. A linha
     sobrevive ao uso de propósito: é ela que responde "quantos pedidos saíram
     para este número na última hora", que é o freio antiabuso.';

-- ------------------------------------------------------------------ a sessão
--
-- POR QUE UMA TABELA se o cookie já é um JWT assinado: o JWT responde "este
-- token é meu e não expirou" e não responde "esta pessoa ainda pode entrar" —
-- e é a segunda que decide desligamento e aparelho perdido. Toda requisição
-- confere a linha; encerrar aqui derruba o acesso na requisição seguinte.
CREATE TABLE IF NOT EXISTS agr_sessoes(
    id                  bigserial PRIMARY KEY,
    proprietario_codigo text NOT NULL REFERENCES agr_vinculos(proprietario_codigo)
                             ON DELETE CASCADE,
    aparelho            text NOT NULL DEFAULT '',
    criada_em           timestamptz NOT NULL DEFAULT now(),
    vista_em            timestamptz NOT NULL DEFAULT now(),
    encerrada_em        timestamptz,
    mestre              boolean NOT NULL DEFAULT false,
    ip                  text NOT NULL DEFAULT '',
    agente              text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS agr_sessoes_dono ON agr_sessoes(proprietario_codigo)
    WHERE encerrada_em IS NULL;

COMMENT ON COLUMN agr_sessoes.vista_em IS
    '"Visto por último". A sessão é linha VIVA, como aud_sessoes: duração é
     coalesce(encerrada_em, vista_em) - criada_em, NUNCA now() — ninguém sai
     pelo botão, e o aparelho esquecido viraria uma sessão de semanas.';

COMMENT ON COLUMN agr_sessoes.mestre IS
    'Sessão aberta pelo código da casa (api/agregado/mestre.py) para conferir o
     que o app afirma. É a MESMA sessão em tudo o mais; a marca serve à tarja
     obrigatória na tela, ao prazo curto e à trilha que separa as duas
     entradas depois.';

-- ------------------------------------------------- as tentativas do mestre
--
-- O código mestre não expira: o que protege contra o laço é o TETO, e ele
-- precisa de onde contar. Guarda se a tentativa foi aceita — nunca o código.
CREATE TABLE IF NOT EXISTS agr_mestre_tentativas(
    id      bigserial PRIMARY KEY,
    ip      text NOT NULL DEFAULT '',
    quando  timestamptz NOT NULL DEFAULT now(),
    aceita  boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS agr_mestre_tent_ip ON agr_mestre_tentativas(ip, quando DESC);

COMMENT ON TABLE agr_mestre_tentativas IS
    'Trilha e freio do código mestre do app do agregado. Nunca guarda o código
     tentado — só se foi aceito, de onde e quando.';
