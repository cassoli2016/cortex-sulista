-- 0092 · Horas paradas: o histórico dos e-mails enviados ao cliente.
--
-- Pedido de quem opera (13/09/2026): montar o e-mail com as horas paradas e
-- a planilha anexada, para os destinatários que quem está na tela escolher,
-- com um endereço de resposta — o e-mail sai do noreply.
--
-- O envio passa pelo módulo de correio da casa, que já grava TODA tentativa
-- em `correio_envios` (o que saiu da empresa, com o corpo). Esta tabela é a
-- outra pergunta: "a planilha desta semana deste cliente já foi mandada, para
-- quem, e por quem?" — que é o que a tela precisa responder antes de alguém
-- mandar de novo.
--
-- A linha nasce ANTES do envio (`ok` NULL) e é fechada depois: um envio que
-- derrubou o processo no meio fica visível como "sem resposta", em vez de
-- sumir.

CREATE TABLE IF NOT EXISTS hp_envio(
    id              bigserial PRIMARY KEY,
    perfil_id       integer NOT NULL REFERENCES hp_perfil(id) ON DELETE CASCADE,
    de              date NOT NULL,
    ate             date NOT NULL,
    destinatarios   text NOT NULL,
    responder_para  text NOT NULL DEFAULT '',
    assunto         text NOT NULL,
    arquivo         text NOT NULL DEFAULT '',
    cargas          integer NOT NULL DEFAULT 0,
    valor_total     numeric(14,2) NOT NULL DEFAULT 0,
    ok              boolean,
    erro            text NOT NULL DEFAULT '',
    autor           text NOT NULL,
    em              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_hp_envio_perfil ON hp_envio (perfil_id, em DESC);
