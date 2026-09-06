-- App do Motorista — identidade, código de entrada e sessão presa ao aparelho.
--
-- A TERCEIRA PERGUNTA DE ACESSO DESTA CASA. O RBAC respondia "que tela você
-- abre" (perfil × tela, 0011_auth.sql); o portal do cliente acrescentou "quais
-- linhas são suas" (`usuarios.cliente_cnpj_raiz`, 0053). Aqui a pergunta é a
-- mais estreita das três: **qual motorista você é** — as linhas de UMA pessoa.
--
-- POR QUE O MOTORISTA NÃO É UMA LINHA EM `usuarios`, mudando o que o rascunho
-- de escopo (docs/APP_MOTORISTA.md) supunha ao copiar o caminho do `cliop`:
--
--   1. O usuário do `cliop` é gente que loga no PAINEL, com e-mail e senha, e
--      cujo perfil decide telas. O motorista não abre o painel: ele abre
--      `motorista.html`, não tem tela nenhuma e entra por código no WhatsApp.
--      Enfiá-lo em `usuarios` seria criar ~300 contas de painel cujo único
--      controle contra abrir o CÓRTEX inteiro é um perfil com zero telas.
--   2. `usuarios.email` é a identidade lá, e 121 dos 606 motoristas têm e-mail.
--      Sobraria e-mail sintético — identidade inventada por nós, que ninguém
--      confere, num lugar onde a identidade é o que segura tudo.
--   3. `/api/auth/esqueci-senha` é público e trabalha por e-mail. Motorista em
--      `usuarios` herdaria esse caminho de graça, e um dia alguém entraria no
--      painel por ele. Aqui, o caminho simplesmente não existe.
--
-- O preço é uma segunda autenticação para manter, e ele está pago no
-- docstring de `api/motorista/__init__.py`: identidade separada, cookie
-- separado, e NENHUMA rota do painel alcançável por uma sessão de motorista.

-- ---------------------------------------------------------------- o vínculo
--
-- QUEM É MOTORISTA NO APP. Não basta o ERP dizer que a pessoa dirigiu: alguém
-- da casa liga o telefone ao código do motorista, e é essa linha que dá
-- acesso. Sem ela não há entrada — nem para quem tem o telefone certo.
--
-- `motorista_codigo` É TEXT, e o cast acontece na ENTRADA. O ERP grava
-- `cadastro.codigo` como `character varying` HOJE; em 02/09/2026 a
-- `agrupadorgerencial` foi recriada com `grupo` mudando de `integer` para
-- `varchar` e cinco telas morreram no `operator does not exist`. Tabela de
-- terceiro não tem contrato de tipo: o dublê tem o tipo que NÓS escrevemos.
CREATE TABLE IF NOT EXISTS mot_vinculos(
    motorista_codigo text PRIMARY KEY,
    telefone         text NOT NULL,
    nome             text NOT NULL DEFAULT '',
    ativo            boolean NOT NULL DEFAULT true,
    criado_em        timestamptz NOT NULL DEFAULT now(),
    criado_por       text NOT NULL DEFAULT '',
    desligado_em     timestamptz,
    desligado_por    text NOT NULL DEFAULT ''
);

-- O telefone NÃO é único, e isso é um requisito medido, não uma frouxidão:
-- em 05/09/2026, 5 dos 585 motoristas com celular válido dividem o número com
-- outro motorista. Telefone compartilhado significa que um canal serve duas
-- identidades — quem entra por ele escolhe QUEM é, depois de provar o código.
-- Um UNIQUE aqui deixaria essas pessoas de fora sem ninguém entender por quê.
CREATE INDEX IF NOT EXISTS mot_vinculos_fone ON mot_vinculos(telefone)
    WHERE ativo;

COMMENT ON COLUMN mot_vinculos.telefone IS
    'Telefone NORMALIZADO pelo validador único da casa (api/whatsapp/numeros).
     Guardado normalizado porque é assim que comparação e contagem batem; a
     tela reformata na exibição. Vem de cadastro.celular, que já traz DDI+DDD:
     concatenar dddcelular com ele quebra o número (0,2% de válidos, medido).';

COMMENT ON COLUMN mot_vinculos.ativo IS
    'Falso = desligado, e a sessão dele para de valer na requisição seguinte.
     Motorista que sai da casa (ou agregado que troca de transportadora) NÃO
     perde acesso sozinho: é regra de desligamento, com gente responsável.';

-- ------------------------------------------------------- o código de entrada
--
-- O CÓDIGO NUNCA É GRAVADO. Só o SHA-256 dele, pela mesma razão que
-- `senha_reset` (0038) guarda o token em hash: quem lê a tabela — backup,
-- dump, uma consulta de diagnóstico — não pode entrar na conta de ninguém.
--
-- A LINHA É A TENTATIVA, não a sessão: ela nasce quando alguém PEDE um código
-- e morre quando o código é usado ou expira. Por isso `telefone` e não
-- `motorista_codigo`: no instante do pedido ainda não se sabe (nem se pode
-- revelar) se aquele número pertence a alguém.
CREATE TABLE IF NOT EXISTS mot_codigos(
    id          bigserial PRIMARY KEY,
    telefone    text NOT NULL,
    codigo_hash text NOT NULL,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    expira_em   timestamptz NOT NULL,
    tentativas  int NOT NULL DEFAULT 0,
    usado_em    timestamptz,
    ip          text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS mot_codigos_fone ON mot_codigos(telefone, criado_em DESC);

COMMENT ON TABLE mot_codigos IS
    'Códigos de entrada em voo. Guarda o SHA-256, nunca o código. A linha
     sobrevive ao uso de propósito: é a trilha que responde "quantos pedidos
     saíram para este número na última hora", que é o freio antiabuso.';

-- ------------------------------------------------------------------ a sessão
--
-- POR QUE UMA TABELA se o cookie já é um JWT assinado: o JWT responde "este
-- token é meu e não expirou" e não responde "esta pessoa ainda pode entrar" —
-- e é a segunda que decide desligamento e aparelho perdido. Toda requisição
-- confere a linha; encerrar aqui derruba o acesso na requisição seguinte, sem
-- esperar o token vencer.
--
-- `aparelho` é um id OPACO gerado no navegador do motorista. Não é fingerprint
-- e não identifica o aparelho de verdade: serve para "sair de todos os
-- aparelhos" e para a casa ver que o mesmo login está em dois lugares. Não se
-- guarda modelo, IMEI, nem nada que descreva o telefone da pessoa.
CREATE TABLE IF NOT EXISTS mot_sessoes(
    id               bigserial PRIMARY KEY,
    motorista_codigo text NOT NULL REFERENCES mot_vinculos(motorista_codigo)
                          ON DELETE CASCADE,
    aparelho         text NOT NULL DEFAULT '',
    criada_em        timestamptz NOT NULL DEFAULT now(),
    vista_em         timestamptz NOT NULL DEFAULT now(),
    encerrada_em     timestamptz,
    ip               text NOT NULL DEFAULT '',
    agente           text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS mot_sessoes_mot ON mot_sessoes(motorista_codigo)
    WHERE encerrada_em IS NULL;

COMMENT ON COLUMN mot_sessoes.vista_em IS
    '"Visto por último". A sessão é linha VIVA, como aud_sessoes: duração é
     coalesce(encerrada_em, vista_em) - criada_em, NUNCA now() — ninguém sai
     pelo botão, e o aparelho esquecido viraria uma sessão de semanas.';
