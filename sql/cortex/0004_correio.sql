-- Trilha dos e-mails enviados pelo CÓRTEX.
--
-- `correio_envios`, com o prefixo do módulo: `antecipacoes.db` também tem uma
-- tabela `envios`, e no schema único as duas disputariam o mesmo nome. Foi a
-- primeira colisão real da migração, achada aqui e não depois.
--
-- Separada do `audit_log` de propósito: o audit responde "quem mexeu no
-- sistema" e esta responde "o que saiu para fora da empresa", com o corpo da
-- mensagem. Perguntas diferentes, retenções diferentes — e o volume de uma não
-- pode empurrar a outra para fora da tela.
--
-- `ok` continua INTEGER 0/1 e não boolean nesta passada: a tela e o resumo já
-- somam `CASE WHEN ok=1`, e trocar o tipo junto com o banco dobraria a
-- superfície de erro. Vira boolean quando as datas virarem timestamp.

CREATE TABLE IF NOT EXISTS correio_envios(
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts            text    NOT NULL,
    usuario       text    NOT NULL DEFAULT '',
    destinatarios text    NOT NULL,
    assunto       text    NOT NULL DEFAULT '',
    corpo         text    NOT NULL DEFAULT '',
    origem        text    NOT NULL DEFAULT '',
    ok            integer NOT NULL DEFAULT 0,
    erro          text    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_correio_envios_ts ON correio_envios(ts);

COMMENT ON TABLE correio_envios IS
    'Toda TENTATIVA de envio, inclusive a que falhou — trilha só de sucesso
     esconde justamente o caso que se precisa investigar.';
