-- Aviso de carga por WhatsApp, pedido na página pública de rastreio.
--
-- ISTO É UMA CAIXA DE ENTRADA ABERTA À INTERNET, e o desenho parte daí: quem
-- se inscreve não tem conta, não faz login e não é identificável. Sem cuidado,
-- a página vira um jeito confortável de mandar mensagem de hora em hora para o
-- telefone de um desafeto — basta ter um número de CT-e e o telefone dele.
--
-- O QUE SEGURA ISSO, e por que cada peça existe:
--
-- 1. O SEGUNDO FATOR VALE AQUI TAMBÉM. Inscrever exige o mesmo documento em
--    mãos e os quatro dígitos do CNPJ que a busca exige. Não impede o abuso de
--    quem tem os dois, mas tira do caminho quem só tem o telefone da vítima.
--
-- 2. TELEFONE NORMALIZADO E ÚNICO POR CARGA. Sem a unicidade, o mesmo número
--    entraria dez vezes na mesma carga e receberia dez mensagens por hora —
--    e o freio da casa, que conta destinatários DISTINTOS, não veria problema
--    nenhum nisso.
--
-- 3. A INSCRIÇÃO MORRE SOZINHA. `expira_em` existe porque ninguém volta para
--    cancelar: a carga é entregue, a pessoa esquece, e o aviso continuaria
--    para sempre. Entrega encerra; o prazo encerra o resto.
--
-- 4. O QUE FOI DITO FICA GRAVADO (`ultimo_texto`). Não é histórico por gosto:
--    é o que permite NÃO repetir a mesma mensagem quando nada mudou. Um
--    caminhão parado geraria a mesma frase de hora em hora, e a pessoa bloqueia
--    o número da empresa — o estrago não é a mensagem, é a reputação do número
--    que atende todos os outros clientes.
CREATE TABLE IF NOT EXISTS rst_inscricao (
  id             BIGSERIAL PRIMARY KEY,
  -- A carga, pelas chaves do documento no ERP. Guardar o token opaco não
  -- serviria: ele depende de um segredo que pode ser trocado, e a inscrição
  -- precisa sobreviver a isso.
  grupo          INTEGER NOT NULL,
  empresa        INTEGER NOT NULL,
  filial         INTEGER NOT NULL,
  numero         BIGINT  NOT NULL,
  serie          INTEGER NOT NULL,
  -- NORMALIZADO, sempre. A casa tem UM validador de telefone
  -- (`api/whatsapp/numeros.py`) e é ele que decide o formato; a tela
  -- reformata na exibição.
  telefone       TEXT NOT NULL,
  criado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
  criado_ip      TEXT,
  ativo          BOOLEAN NOT NULL DEFAULT TRUE,
  cancelado_em   TIMESTAMPTZ,
  cancelado_por  TEXT,
  expira_em      TIMESTAMPTZ NOT NULL,
  ultimo_envio   TIMESTAMPTZ,
  ultimo_texto   TEXT,
  envios         INTEGER NOT NULL DEFAULT 0,
  UNIQUE (grupo, empresa, filial, numero, serie, telefone)
);
CREATE INDEX IF NOT EXISTS rst_inscricao_ativa
  ON rst_inscricao (ativo, expira_em);
CREATE INDEX IF NOT EXISTS rst_inscricao_fone
  ON rst_inscricao (telefone, criado_em);
