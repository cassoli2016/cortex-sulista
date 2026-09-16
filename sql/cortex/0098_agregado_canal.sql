-- 0098 · O canal entre o SETOR DE AGREGADOS e o proprietário.
--
-- Pedido de quem opera (16/09/2026): *"no aplicativo do motorista temos um fale
-- com o RH; nesse do agregado nós vamos ter um fale com o setor de
-- agregados"*. A forma é a mesma do canal do RH (0063), e a razão de ela ser
-- assim está lá por escrito: **isto não é conversa, é FILA COM ASSUNTO, DONO E
-- ESTADO** — a mesma forma dos chamados do Suporte, que funciona há tempo.
--
-- | O que se teme num canal novo | O que impede aqui |
-- |---|---|
-- | "ninguém lê" | `visto_setor_em` / `visto_agregado_em`: a caixa ordena por quem espera há mais tempo, e a Saúde mede a fila parada |
-- | "expectativa que ninguém atende" | assunto de LISTA FECHADA + `status` + `atribuido_id`: "aberta há N dias" é número, não sensação |
--
-- POR QUE NÃO REUSAR `mot_conversas`. Ela é chaveada em `mot_vinculos`, e o
-- proprietário não é motorista: são públicos, escopos e assuntos diferentes
-- (acerto e pagamento de um lado, férias e contracheque do outro). Enfiar os
-- dois na mesma tabela faria a caixa do RH receber pedido de acerto e a do
-- setor de agregados receber pedido de férias — e a separação passaria a
-- depender de um `WHERE` que alguém esquece.
--
-- POR QUE NÃO REUSAR O WHATSAPP QUE JÁ EXISTE. Porque WhatsApp não tem estado:
-- "mandei no zap" não responde "quem está atendendo", "desde quando" e
-- "acabou?". O WhatsApp continua sendo o AVISO; o que tem estado mora aqui.

-- --------------------------------------------------------------- o assunto
--
-- LISTA FECHADA, EM TABELA E NÃO EM CONSTANTE DE CÓDIGO: o setor vai querer
-- acrescentar assunto (e desligar um que não usa) sem esperar entrega de
-- software. `ativo = false` DESLIGA sem apagar — conversa antiga aponta para o
-- assunto dela, e apagar a linha levaria o histórico junto.
CREATE TABLE IF NOT EXISTS agr_assuntos(
    chave        text PRIMARY KEY,
    rotulo       text NOT NULL,
    -- O que o dono lê ANTES de escrever. É este texto que resolve metade dos
    -- pedidos sem virar fila: "o acerto fecha toda sexta" responde sozinho.
    ajuda        text NOT NULL DEFAULT '',
    quem_abre    text NOT NULL DEFAULT 'agregado'
                 CHECK (quem_abre IN ('agregado','setor','ambos')),
    ordem        integer NOT NULL DEFAULT 100,
    ativo        boolean NOT NULL DEFAULT true
);

-- Os assuntos NASCEM aqui, e não numa tela de cadastro que ninguém preencheu:
-- canal vazio no primeiro dia é canal que ninguém abre no segundo. A lista saiu
-- do que o app já mostra — é sobre isso que o dono vai perguntar.
INSERT INTO agr_assuntos(chave, rotulo, ajuda, quem_abre, ordem)
VALUES
 ('acerto',     'Acerto e pagamento',
  'Dúvida sobre um acerto, valor líquido, data de pagamento ou parcela em '
  'aberto. Diga o NÚMERO do acerto — ele aparece na aba Acertos.',
  'agregado', 10),
 ('viagem',     'Viagem e frete',
  'Frete de uma viagem, km pago, carga que não entrou no acerto. Diga a PLACA '
  'e a data da viagem.',
  'agregado', 20),
 ('desconto',   'Desconto e lançamento',
  'Desconto no acerto, adicional que faltou, multa lançada. É aqui que se '
  'pergunta sobre multa: ela não é lançada no app, entra como desconto.',
  'agregado', 30),
 ('abastecimento', 'Abastecimento',
  'Litro, valor ou abastecimento que não apareceu. Diga a PLACA e o dia.',
  'agregado', 40),
 ('documento',  'Documento e cadastro',
  'CRLV, contrato, troca de placa, dados bancários e mudança de telefone.',
  'ambos', 50),
 ('outro',      'Outro assunto',
  'Quando não for nenhum dos acima. Diga em uma frase do que se trata.',
  'agregado', 90),
 ('recado',     'Recado da Sulista',
  'Aviso do setor de agregados para o proprietário.',
  'setor', 5)
ON CONFLICT (chave) DO NOTHING;

-- ---------------------------------------------------------------- a conversa
--
-- UMA CONVERSA É UM ASSUNTO, e o assunto vem da lista fechada acima. Texto
-- livre existe DENTRO dela, nas mensagens — o que não existe é conversa sem
-- assunto, que é o que vira caixa que ninguém esvazia.
CREATE TABLE IF NOT EXISTS agr_conversas(
    id                  bigserial PRIMARY KEY,
    proprietario_codigo text NOT NULL REFERENCES agr_vinculos(proprietario_codigo)
                             ON DELETE CASCADE,
    assunto             text NOT NULL REFERENCES agr_assuntos(chave),
    -- Quem ABRIU. Não é o mesmo que "de quem é a conversa": ela é sempre de UM
    -- proprietário, mas quem puxou pode ter sido o setor (um recado, um pedido
    -- de documento) ou ele.
    origem              text NOT NULL CHECK (origem IN ('agregado','setor')),
    titulo              text NOT NULL DEFAULT '',
    status              text NOT NULL DEFAULT 'aberta'
                        CHECK (status IN ('aberta','em_atendimento',
                                          'aguardando_agregado','resolvida')),
    status_em           timestamptz NOT NULL DEFAULT now(),
    status_por          text NOT NULL DEFAULT '',
    -- O DONO NO SETOR. `usuarios(id)` porque deste lado quem atende É gente do
    -- painel; `ON DELETE SET NULL` porque desligar quem atendeu não pode apagar
    -- a conversa — a trilha do que foi dito a um fornecedor é o que vale numa
    -- discussão de pagamento.
    atribuido_id        integer REFERENCES usuarios(id) ON DELETE SET NULL,
    atribuido_nome      text NOT NULL DEFAULT '',
    criada_em           timestamptz NOT NULL DEFAULT now(),
    -- Carimbo da ÚLTIMA mensagem. Desnormalizado de propósito, e é a única
    -- coisa desnormalizada aqui: a caixa ordena por ele, e a alternativa seria
    -- um `max()` sobre as mensagens em toda abertura de tela. Não é total e não
    -- se soma — total desnormalizado é que discorda das próprias linhas.
    ultima_em           timestamptz NOT NULL DEFAULT now(),
    -- "VISTO POR ÚLTIMO", UM POR LADO: é daqui que sai o não-lido dos dois
    -- lados. Linha VIVA com carimbo, não um booleano por mensagem — booleano
    -- por mensagem obrigaria a escrever N linhas para marcar uma conversa lida.
    visto_agregado_em   timestamptz,
    visto_setor_em      timestamptz
);

CREATE INDEX IF NOT EXISTS agr_conversas_dono
    ON agr_conversas(proprietario_codigo, ultima_em DESC);
CREATE INDEX IF NOT EXISTS agr_conversas_fila
    ON agr_conversas(ultima_em) WHERE status <> 'resolvida';

COMMENT ON COLUMN agr_conversas.status IS
    'aberta = ninguém pegou · em_atendimento = alguém do setor pegou ·
     aguardando_agregado = o setor respondeu e espera ele · resolvida = acabou.
     ESTADO É CAMPO, NUNCA AUSÊNCIA DE DATA: "não respondida" derivado de
     `resposta_em IS NULL` mente no dia em que alguém responde por fora.';

-- ------------------------------------------------------------- as mensagens
--
-- APPEND-ONLY, e isso não é zelo: o que foi dito entre a empresa e o
-- fornecedor sobre dinheiro é prova, e prova que se edita não é prova.
-- Correção se faz com mensagem NOVA, como no `audit_log` e no `sup_mensagens`.
--
-- `papel = 'sistema'` são os eventos (abertura, mudança de status,
-- atribuição): eles moram na MESMA linha do tempo do texto humano, porque é
-- assim que a conversa se lê depois.
CREATE TABLE IF NOT EXISTS agr_mensagens(
    id           bigserial PRIMARY KEY,
    conversa_id  bigint NOT NULL REFERENCES agr_conversas(id) ON DELETE CASCADE,
    papel        text NOT NULL CHECK (papel IN ('agregado','setor','sistema')),
    -- Só quando `papel='setor'`. O proprietário não tem id de usuário (0097), e
    -- o nome dele já está na conversa.
    autor_id     integer REFERENCES usuarios(id) ON DELETE SET NULL,
    autor_nome   text NOT NULL DEFAULT '',
    texto        text NOT NULL DEFAULT '',
    -- '' = texto humano. 'abertura' | 'status' | 'atribuicao'.
    evento       text NOT NULL DEFAULT '',
    criada_em    timestamptz NOT NULL DEFAULT now(),
    CHECK (texto <> '' OR evento <> '')
);

CREATE INDEX IF NOT EXISTS agr_mensagens_conversa
    ON agr_mensagens(conversa_id, id);

COMMENT ON TABLE agr_mensagens IS
    'Append-only: o que foi dito entre a empresa e o fornecedor sobre dinheiro é
     prova, e prova que se edita não é prova. Correção é mensagem nova.';
