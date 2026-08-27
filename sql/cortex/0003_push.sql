-- Web Push: inscrições do navegador e o marcador do digest diário.
--
-- PREFIXO DO MÓDULO no nome da tabela (`push_*`), como o CLAUDE.md já manda
-- para o banco grande (`fin_*`, `com_*`, `op_*`). É um schema só para os dez
-- stores: `subs` e `meta` seriam nomes que a próxima migração disputaria —
-- `email.db` e `antecipacoes.db` TÊM, os dois, uma tabela `envios`.
--
-- `endpoint` é a URL opaca que o navegador dá — não é dado pessoal do ERP, mas
-- é longa (o FCM passa de 200 caracteres), então `text` e não `varchar(n)`.
--
-- `meta` guarda uma linha só (`ultimo_digest`), e existe para o digest não sair
-- duas vezes no mesmo dia quando a API reinicia dentro da janela das 07:00.

CREATE TABLE IF NOT EXISTS push_subs(
    endpoint  text PRIMARY KEY,
    p256dh    text NOT NULL,
    auth      text NOT NULL,
    usuario   text,
    criado_em text
);

CREATE TABLE IF NOT EXISTS push_meta(
    chave text PRIMARY KEY,
    valor text
);

-- o envio filtra por usuário para mandar só ao dono da sessão
CREATE INDEX IF NOT EXISTS ix_push_subs_usuario ON push_subs(usuario);

COMMENT ON TABLE push_subs IS
    'Inscrições de Web Push por navegador. Expiradas (404/410) são removidas
     no próprio envio — ver api/push.py.';
COMMENT ON TABLE push_meta IS
    'Marcadores do agendador do push. Hoje só ultimo_digest (AAAA-MM-DD).';
